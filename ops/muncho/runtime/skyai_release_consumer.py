#!/usr/bin/env python3
"""Fail-closed target-side consumer for signed SkyAI cloud releases.

The consumer runs on ``skyai-runtime-prod-01`` from a systemd timer.  It has no
model and makes no semantic decisions.  It accepts only a correctly signed,
bounded release manifest, verifies the immutable archive, stages it outside
the active symlink, probes it with the production interpreter/environment,
performs one atomic cutover, and automatically restores the previous release
and environment on failure.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, Iterable, Mapping
import urllib.error
import urllib.parse
import urllib.request

# The target unit executes this release-pinned file under ``-I``.  Admit only
# the immutable release root holding the sibling contract, never PYTHONPATH or
# a user site directory.
if __package__ in {None, ""}:
    for _candidate_root in Path(__file__).resolve().parents:
        if (_candidate_root / "ops/muncho/runtime/cloud_release_contract.py").is_file():
            sys.path.insert(0, str(_candidate_root))
            break

from ops.muncho.runtime.cloud_release_contract import (
    MAX_ARTIFACT_BYTES,
    MAX_ENVELOPE_BYTES,
    SKYAI_RELEASE_BUCKET,
    canonical_json_bytes,
    verify_envelope,
)


METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)
GCS_JSON_BASE = "https://storage.googleapis.com/storage/v1"
SERVICE_UNIT = "skyai-v2-hermes-prod.service"
SERVICE_ENV = Path("/etc/skyai/skyai-v2-prod.env")
RELEASE_ROOT = Path("/opt/skyai-v2/releases")
CURRENT_LINK = Path("/opt/skyai-v2/current")
PYTHON = Path("/opt/skyai-v2/venv/bin/python")
STATE_ROOT = Path("/var/lib/skyai-release-consumer")
STATE_FILE = STATE_ROOT / "state.json"
LOCK_FILE = Path("/run/skyai-release-consumer.lock")
PUBLIC_KEY_FILE = Path("/etc/skyai/skyai-release-signing-public.pem")
LOCAL_BASE_URL = "http://10.80.0.4:8787"
PUBLIC_BASE_URL = "https://skyai-prod-ingress-lo4jl44wdq-ey.a.run.app"
MAX_QUEUE_OBJECTS = 1000
RETRY_BASE_SECONDS = 5 * 60
RETRY_MAX_SECONDS = 6 * 60 * 60
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SkyAIReleaseConsumerError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical_write(
    path: Path, value: Mapping[str, Any], *, mode: int = 0o600
) -> None:
    raw = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    replaced = False
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
        os.fchmod(descriptor, mode)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        replaced = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not replaced:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _stable_regular(
    path: Path,
    *,
    maximum: int,
    allowed_modes: frozenset[int],
    expected_uid: int | None = 0,
) -> bytes:
    descriptor = -1
    try:
        before = os.lstat(path)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) not in allowed_modes
            or expected_uid is not None
            and before.st_uid != expected_uid
            or not 0 < before.st_size <= maximum
        ):
            raise SkyAIReleaseConsumerError("protected_file_invalid")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    except SkyAIReleaseConsumerError:
        raise
    except OSError as exc:
        raise SkyAIReleaseConsumerError("protected_file_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    raw = b"".join(chunks)
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_uid,
        item.st_gid,
        item.st_nlink,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if (
        len(raw) > maximum
        or len(raw) != before.st_size
        or identity(before) != identity(opened)
        or identity(before) != identity(after)
    ):
        raise SkyAIReleaseConsumerError("protected_file_changed")
    return raw


def _request_bytes(
    url: str,
    *,
    token: str = "",
    metadata: bool = False,
    payload: bytes | None = None,
    method: str = "GET",
    maximum: int,
) -> tuple[int, bytes]:
    headers = {"Accept": "application/json", "User-Agent": "skyai-release-consumer/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if metadata:
        headers["Metadata-Flavor"] = "Google"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read(maximum + 1)
            if len(raw) > maximum:
                raise SkyAIReleaseConsumerError("remote_response_too_large")
            return response.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(min(4096, maximum))
    except (OSError, urllib.error.URLError) as exc:
        raise SkyAIReleaseConsumerError("remote_request_failed") from exc


def _request_json(
    url: str,
    *,
    token: str = "",
    metadata: bool = False,
    maximum: int = 4 * 1024 * 1024,
) -> dict[str, Any]:
    status, raw = _request_bytes(url, token=token, metadata=metadata, maximum=maximum)
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkyAIReleaseConsumerError("remote_json_invalid") from exc
    if status != 200 or not isinstance(value, dict):
        raise SkyAIReleaseConsumerError("remote_request_rejected")
    return value


def metadata_token() -> str:
    value = _request_json(METADATA_TOKEN_URL, metadata=True)
    token = value.get("access_token")
    if not isinstance(token, str) or not token:
        raise SkyAIReleaseConsumerError("gcp_metadata_token_invalid")
    return token


class GCSReader:
    def __init__(self, token: str) -> None:
        self.token = token

    def list_queue(self) -> list[str]:
        names: list[str] = []
        page_token = ""
        while True:
            query: dict[str, Any] = {
                "prefix": "queue/",
                "maxResults": 1000,
                "fields": "items(name,size),nextPageToken",
            }
            if page_token:
                query["pageToken"] = page_token
            url = (
                f"{GCS_JSON_BASE}/b/{SKYAI_RELEASE_BUCKET}/o?"
                + urllib.parse.urlencode(query)
            )
            value = _request_json(url, token=self.token)
            items = value.get("items", [])
            if not isinstance(items, list):
                raise SkyAIReleaseConsumerError("gcs_queue_invalid")
            for item in items:
                if not isinstance(item, dict):
                    raise SkyAIReleaseConsumerError("gcs_queue_invalid")
                name = item.get("name")
                size = item.get("size")
                if (
                    not isinstance(name, str)
                    or not name.startswith("queue/")
                    or not name.endswith(".json")
                    or not isinstance(size, str)
                    or not size.isdigit()
                    or not 1 <= int(size) <= MAX_ENVELOPE_BYTES
                ):
                    raise SkyAIReleaseConsumerError("gcs_queue_invalid")
                names.append(name)
                if len(names) > MAX_QUEUE_OBJECTS:
                    raise SkyAIReleaseConsumerError("gcs_queue_too_large")
            page_token = value.get("nextPageToken", "")
            if not page_token:
                break
            if not isinstance(page_token, str):
                raise SkyAIReleaseConsumerError("gcs_queue_invalid")
        return sorted(set(names))

    def download(self, name: str, *, maximum: int) -> bytes:
        encoded = urllib.parse.quote(name, safe="")
        status, raw = _request_bytes(
            f"{GCS_JSON_BASE}/b/{SKYAI_RELEASE_BUCKET}/o/{encoded}?alt=media",
            token=self.token,
            maximum=maximum,
        )
        if status != 200:
            raise SkyAIReleaseConsumerError("gcs_download_failed")
        return raw


def load_state(path: Path = STATE_FILE) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema": "skyai-release-consumer-state.v1",
            "deployed_sha": "",
            "records": {},
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkyAIReleaseConsumerError("consumer_state_invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "deployed_sha", "records"}
        or value["schema"] != "skyai-release-consumer-state.v1"
        or not isinstance(value["deployed_sha"], str)
        or not isinstance(value["records"], dict)
    ):
        raise SkyAIReleaseConsumerError("consumer_state_invalid")
    return value


def _active_release() -> tuple[Path, str]:
    try:
        target = CURRENT_LINK.resolve(strict=True)
    except OSError as exc:
        raise SkyAIReleaseConsumerError("active_release_invalid") from exc
    if target.parent != RELEASE_ROOT or not target.is_dir():
        raise SkyAIReleaseConsumerError("active_release_invalid")
    try:
        build = (target / ".skyai-build-commit").read_text(encoding="utf-8").strip()
    except OSError:
        build = ""
    return target, build


def _parse_env(raw: bytes) -> dict[str, str]:
    try:
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise SkyAIReleaseConsumerError("service_environment_invalid") from exc
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        name, value = stripped.split("=", 1)
        name = name.strip()
        if _ENV_NAME.fullmatch(name) is None:
            raise SkyAIReleaseConsumerError("service_environment_invalid")
        values[name] = value.strip().strip("'\"")
    return values


def _rewrite_build_commit(raw: bytes, source_sha: str) -> bytes:
    try:
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise SkyAIReleaseConsumerError("service_environment_invalid") from exc
    output: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        exported = stripped.startswith("export ")
        assignment = stripped[7:].lstrip() if exported else stripped
        if assignment.startswith("SKYAI_V2_BUILD_COMMIT="):
            if replaced:
                raise SkyAIReleaseConsumerError("service_environment_invalid")
            prefix = "export " if exported else ""
            output.append(f"{prefix}SKYAI_V2_BUILD_COMMIT={source_sha}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f"SKYAI_V2_BUILD_COMMIT={source_sha}")
    return ("\n".join(output) + "\n").encode("utf-8")


def safe_extract_archive(raw: bytes, destination: Path) -> None:
    if destination.exists():
        raise SkyAIReleaseConsumerError("candidate_release_exists")
    destination.mkdir(parents=True, mode=0o755)
    roots: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            members = archive.getmembers()
            if not members:
                raise SkyAIReleaseConsumerError("source_archive_empty")
            for member in members:
                parts = Path(member.name).parts
                if (
                    len(parts) < 1
                    or member.name.startswith("/")
                    or ".." in parts
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or member.isfifo()
                    or not (member.isfile() or member.isdir())
                ):
                    raise SkyAIReleaseConsumerError("source_archive_member_invalid")
                roots.add(parts[0])
            if len(roots) != 1:
                raise SkyAIReleaseConsumerError("source_archive_root_invalid")
            root = next(iter(roots))
            for member in members:
                relative_parts = Path(member.name).parts[1:]
                if not relative_parts:
                    continue
                target = destination.joinpath(*relative_parts)
                if target != destination and destination not in target.parents:
                    raise SkyAIReleaseConsumerError("source_archive_member_invalid")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    os.chmod(target, 0o755)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise SkyAIReleaseConsumerError("source_archive_member_invalid")
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o755 if member.mode & 0o111 else 0o644,
                )
                try:
                    with os.fdopen(os.dup(descriptor), "wb") as target_stream:
                        shutil.copyfileobj(source, target_stream)
                        target_stream.flush()
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
    except SkyAIReleaseConsumerError:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    except (OSError, tarfile.TarError) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise SkyAIReleaseConsumerError("source_archive_extract_failed") from exc


def _run(
    command: list[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    timeout: int = 600,
) -> str:
    try:
        completed = subprocess.run(
            command,
            env=dict(env) if env is not None else None,
            cwd=str(cwd) if cwd is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SkyAIReleaseConsumerError("candidate_command_failed") from exc
    if completed.returncode != 0:
        raise SkyAIReleaseConsumerError("candidate_command_failed")
    return completed.stdout[-32_000:]


def _probe_json(
    base_url: str, path: str, *, maximum: int = 512 * 1024
) -> dict[str, Any]:
    return _request_json(base_url + path, maximum=maximum)


def _wait_for_runtime(
    source_sha: str,
    behavior: str | None,
    *,
    timeout_seconds: int = 120,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            health = _probe_json(LOCAL_BASE_URL, "/health")
            version = _probe_json(LOCAL_BASE_URL, "/version")
            if (
                health.get("status") == "ok"
                and health.get("live_model") is True
                and health.get("build_commit") == source_sha
                and version.get("build_commit") == source_sha
                and version.get("runtime_mode") == "production"
                and (
                    behavior is None
                    or health.get("behavior_version") == behavior
                    and version.get("behavior_version") == behavior
                )
            ):
                return
        except Exception as exc:  # bounded retry of a starting local service
            last_error = exc
        time.sleep(2)
    raise SkyAIReleaseConsumerError("runtime_health_timeout") from last_error


def _real_chat_smoke(source_sha: str, behavior: str) -> dict[str, Any]:
    payload = canonical_json_bytes({
        "message": "Кратък системен тест: потвърди, че SkyAI е на линия.",
        "history": [],
        "conversation_id": f"release-smoke-{source_sha[:12]}-{int(time.time())}",
        "delivery_id": f"release-smoke-{source_sha[:12]}",
        "metadata": {"surface": "release_smoke", "synthetic": True},
    })
    status, raw = _request_bytes(
        LOCAL_BASE_URL + "/chatkit/message",
        payload=payload,
        method="POST",
        maximum=2 * 1024 * 1024,
    )
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkyAIReleaseConsumerError("real_chat_smoke_invalid") from exc
    trace = value.get("trace", {}) if isinstance(value, dict) else {}
    if (
        status != 200
        or not isinstance(value, dict)
        or value.get("status") != "ok"
        or value.get("build_commit") != source_sha
        or value.get("behavior_version") != behavior
        or not isinstance(trace, dict)
        or trace.get("live_model") is not True
        or trace.get("fallback") is not False
    ):
        raise SkyAIReleaseConsumerError("real_chat_smoke_failed")
    return {
        "status": "ok",
        "build_commit": value.get("build_commit"),
        "behavior_version": value.get("behavior_version"),
        "live_model": trace.get("live_model"),
        "fallback": trace.get("fallback"),
    }


def _wait_for_public_version(
    source_sha: str,
    behavior: str,
    *,
    timeout_seconds: int = 120,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = _probe_json(PUBLIC_BASE_URL, "/version")
            if (
                value.get("build_commit") == source_sha
                and value.get("behavior_version") == behavior
                and value.get("live_model") is True
                and value.get("runtime_mode") == "production"
            ):
                return
        except Exception as exc:  # bounded propagation/startup retry
            last_error = exc
        time.sleep(2)
    raise SkyAIReleaseConsumerError("public_version_smoke_failed") from last_error


def _atomic_replace_env(raw: bytes) -> None:
    before = os.stat(SERVICE_ENV, follow_symlinks=False)
    descriptor, temporary = tempfile.mkstemp(
        prefix=SERVICE_ENV.name + ".", dir=SERVICE_ENV.parent
    )
    replaced = False
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
        os.fchmod(descriptor, stat.S_IMODE(before.st_mode))
        os.fchown(descriptor, before.st_uid, before.st_gid)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, SERVICE_ENV)
        replaced = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not replaced:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)


def _atomic_symlink(target: Path) -> None:
    temporary = CURRENT_LINK.with_name(CURRENT_LINK.name + f".next-{os.getpid()}")
    with contextlib.suppress(FileNotFoundError):
        temporary.unlink()
    os.symlink(target, temporary)
    os.replace(temporary, CURRENT_LINK)


def _prepare_candidate(manifest: Mapping[str, Any], archive: bytes) -> Path:
    source_sha = manifest["source_sha"]
    release = RELEASE_ROOT / (
        f"{source_sha[:12]}-skyai-{manifest['behavior_version'].replace('.', '-')}-"
        f"{manifest['queued_at_unix']}"
    )
    safe_extract_archive(archive, release)
    (release / ".skyai-build-commit").write_text(source_sha, encoding="utf-8")
    (release / ".skyai-behavior-version").write_text(
        manifest["behavior_version"], encoding="utf-8"
    )
    env_raw = _stable_regular(
        SERVICE_ENV,
        maximum=1024 * 1024,
        allowed_modes=frozenset({0o400, 0o600, 0o640}),
    )
    environment = os.environ.copy()
    environment.update(_parse_env(env_raw))
    environment.update({
        "PYTHONPATH": str(release),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "SKYAI_V2_BUILD_COMMIT": source_sha,
    })
    probe = (
        "from plugins.skyai_customer.production_gateway import "
        "load_production_settings,verify_production_dependencies;"
        "import os; s=load_production_settings(os.environ);"
        "verify_production_dependencies();"
        "assert s.build_commit==os.environ['SKYAI_V2_BUILD_COMMIT'];"
        "print(s.behavior_version,s.build_commit)"
    )
    isolated_probe = "import os,sys;sys.path.insert(0,os.getcwd());" + probe
    _run(
        [str(PYTHON), "-I", "-B", "-c", isolated_probe],
        env=environment,
        cwd=release,
        timeout=120,
    )
    for directory, child_directories, files in os.walk(release):
        for name in files:
            path = Path(directory) / name
            os.chown(path, 0, 0)
            os.chmod(path, 0o444 | (stat.S_IMODE(path.stat().st_mode) & 0o111))
        for name in child_directories:
            path = Path(directory) / name
            os.chown(path, 0, 0)
            os.chmod(path, 0o555)
    os.chown(release, 0, 0)
    os.chmod(release, 0o555)
    return release


def deploy_release(manifest: Mapping[str, Any], archive: bytes) -> dict[str, Any]:
    if (
        len(archive) != manifest["artifact_size"]
        or hashlib.sha256(archive).hexdigest() != manifest["artifact_sha256"]
    ):
        raise SkyAIReleaseConsumerError("artifact_digest_mismatch")
    previous_release, previous_sha = _active_release()
    env_raw = _stable_regular(
        SERVICE_ENV,
        maximum=1024 * 1024,
        allowed_modes=frozenset({0o400, 0o600, 0o640}),
    )
    candidate = _prepare_candidate(manifest, archive)
    mutated = False
    try:
        _atomic_replace_env(_rewrite_build_commit(env_raw, manifest["source_sha"]))
        _atomic_symlink(candidate)
        mutated = True
        _run(["/usr/bin/systemctl", "restart", SERVICE_UNIT], timeout=60)
        _wait_for_runtime(manifest["source_sha"], manifest["behavior_version"])
        _wait_for_public_version(manifest["source_sha"], manifest["behavior_version"])
        real_smoke = _real_chat_smoke(
            manifest["source_sha"], manifest["behavior_version"]
        )
        return {
            "status": "DEPLOYED",
            "source_sha": manifest["source_sha"],
            "behavior_version": manifest["behavior_version"],
            "release_path": str(candidate),
            "previous_release": str(previous_release),
            "previous_sha": previous_sha,
            "real_chat_smoke": real_smoke,
        }
    except Exception as exc:
        if mutated:
            rollback_error = ""
            try:
                _atomic_replace_env(env_raw)
                _atomic_symlink(previous_release)
                _run(["/usr/bin/systemctl", "restart", SERVICE_UNIT], timeout=60)
                if previous_sha:
                    _wait_for_runtime(previous_sha, None)
            except Exception as rollback_exc:  # preserve both exact failure classes
                rollback_error = type(rollback_exc).__name__
            if rollback_error:
                raise SkyAIReleaseConsumerError("rollback_failed") from exc
        raise


def select_candidate(
    entries: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    now: int,
    state: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any]] | None:
    records = state.get("records", {})
    eligible: list[tuple[str, Mapping[str, Any]]] = []
    for name, manifest in entries:
        record = records.get(name, {}) if isinstance(records, Mapping) else {}
        if isinstance(record, Mapping):
            if record.get("status") == "DEPLOYED":
                continue
            retry_at = record.get("next_retry_unix", 0)
            if type(retry_at) is int and retry_at > now:
                continue
        if manifest["not_before_unix"] <= now:
            eligible.append((name, manifest))
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (item[1]["queued_at_unix"], item[0]),
    )


def run_once(
    *,
    reader: GCSReader | None = None,
    public_key_raw: bytes | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    observed_at = int(time.time()) if now is None else now
    state = load_state()
    key_raw = public_key_raw or _stable_regular(
        PUBLIC_KEY_FILE,
        maximum=64 * 1024,
        allowed_modes=frozenset({0o400, 0o440, 0o444, 0o600, 0o640, 0o644}),
    )
    gcs = reader or GCSReader(metadata_token())
    valid: list[tuple[str, Mapping[str, Any]]] = []
    invalid: list[str] = []
    for name in gcs.list_queue():
        try:
            raw = gcs.download(name, maximum=MAX_ENVELOPE_BYTES)
            value = json.loads(raw.decode("utf-8", errors="strict"))
            manifest = verify_envelope(value, key_raw)
            valid.append((name, manifest))
        except Exception:
            invalid.append(name)
    selected = select_candidate(valid, now=observed_at, state=state)
    if selected is None:
        return {
            "schema": "skyai-release-consumer-result.v1",
            "status": "IDLE",
            "observed_at_unix": observed_at,
            "valid_queue_count": len(valid),
            "invalid_queue_count": len(invalid),
            "deployed_sha": state.get("deployed_sha", ""),
            "personal_mac_required": False,
        }
    name, manifest = selected
    records = state["records"]
    existing = records.get(name, {}) if isinstance(records.get(name), Mapping) else {}
    attempts = int(existing.get("attempts", 0)) + 1
    try:
        archive = gcs.download(manifest["artifact_object"], maximum=MAX_ARTIFACT_BYTES)
        result = deploy_release(manifest, archive)
        records[name] = {
            "status": "DEPLOYED",
            "attempts": attempts,
            "completed_at_unix": int(time.time()),
            "source_sha": manifest["source_sha"],
        }
        state["deployed_sha"] = manifest["source_sha"]
        _canonical_write(STATE_FILE, state)
        return {
            "schema": "skyai-release-consumer-result.v1",
            **result,
            "queue_object": name,
            "deadline_missed": observed_at > manifest["deploy_by_unix"],
            "personal_mac_required": False,
        }
    except Exception as exc:
        delay = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** min(attempts - 1, 6)))
        records[name] = {
            "status": "RETRY",
            "attempts": attempts,
            "last_failure": (
                exc.code
                if isinstance(exc, SkyAIReleaseConsumerError)
                else type(exc).__name__
            ),
            "next_retry_unix": observed_at + delay,
            "source_sha": manifest["source_sha"],
        }
        _canonical_write(STATE_FILE, state)
        raise


@contextlib.contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise SkyAIReleaseConsumerError("consumer_already_running") from exc
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Consume one signed SkyAI release")
    parser.add_argument("command", choices=("run-once", "status"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            state = load_state()
            result = {
                "schema": "skyai-release-consumer-result.v1",
                "status": "PASS",
                "deployed_sha": state.get("deployed_sha", ""),
                "personal_mac_required": False,
            }
        else:
            with _exclusive_lock(LOCK_FILE):
                result = run_once()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except SkyAIReleaseConsumerError as exc:
        print(
            json.dumps(
                {
                    "schema": "skyai-release-consumer-result.v1",
                    "status": "BLOCKED",
                    "reason": exc.code,
                    "personal_mac_required": False,
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
