#!/usr/bin/env python3
"""Cloud-native SkyAI release publisher for the operational edge.

The publisher accepts one exact, already-green Git commit selected by the
model.  It verifies the main-branch and CI identities, downloads the immutable
GitHub archive, verifies its structural SkyAI identity, signs a bounded
release manifest, and uploads the archive followed by the queue envelope to
GCS.  Publishing the envelope is the commit point.

No free-form text is classified and no personal workstation credential is
used.  The production service account supplies a short-lived GCP token through
the metadata server; GitHub and Ed25519 credentials are service-private files.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tarfile
import time
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request

# Operational-edge assets execute as release-pinned scripts under ``-I``.
# Locate only the immutable release root that contains this exact contract;
# do not inherit PYTHONPATH or a mutable user site.
if __package__ in {None, ""}:
    for _candidate_root in Path(__file__).resolve().parents:
        if (_candidate_root / "ops/muncho/runtime/cloud_release_contract.py").is_file():
            sys.path.insert(0, str(_candidate_root))
            break

from ops.muncho.runtime.cloud_release_contract import (
    MANIFEST_SCHEMA,
    MAX_ARTIFACT_BYTES,
    MAX_RELEASE_DELAY_SECONDS,
    SKYAI_RELEASE_BUCKET,
    SKYAI_REPOSITORY,
    SKYAI_SOURCE_REF,
    SKYAI_TARGET,
    canonical_json_bytes,
    sign_manifest,
)


GITHUB_API = "https://api.github.com"
GITHUB_ARCHIVE = f"{GITHUB_API}/repos/{SKYAI_REPOSITORY}/tarball"
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)
GCS_UPLOAD_BASE = "https://storage.googleapis.com/upload/storage/v1"
PUBLIC_VERSION_URL = "https://skyai-prod-ingress-lo4jl44wdq-ey.a.run.app/version"
DEFAULT_GITHUB_ENV = Path(
    "/opt/adventico-ai-platform/hermes-home/secrets/github_ops.env"
)
DEFAULT_SIGNING_KEY = Path("/etc/muncho/keys/skyai-release-signing-private.pem")
MAX_GITHUB_RESPONSE_BYTES = 8 * 1024 * 1024
AGGREGATE_CHECK_NAME = "All required checks pass"
CI_WORKFLOW_NAME = "CI"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_BEHAVIOR = re.compile(r"^v[1-9][0-9]*\.[0-9]+$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,239}$")


class SkyAIReleaseBrokerError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _emit(status: str, *, code: int = 0, **extra: Any) -> None:
    print(
        json.dumps(
            {
                "schema": "muncho-skyai-release-broker-result.v1",
                "status": status,
                "target": SKYAI_TARGET,
                "repository": SKYAI_REPOSITORY,
                "source_ref": SKYAI_SOURCE_REF,
                **extra,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    raise SystemExit(code)


def _stable_regular(path: Path, *, maximum: int) -> bytes:
    descriptor = -1
    try:
        before = os.lstat(path)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise SkyAIReleaseBrokerError("release_credential_invalid")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        raw = b""
        while len(raw) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
        after = os.fstat(descriptor)
    except SkyAIReleaseBrokerError:
        raise
    except OSError as exc:
        raise SkyAIReleaseBrokerError("release_credential_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
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
        len(raw) != before.st_size
        or len(raw) > maximum
        or identity(before) != identity(opened)
        or identity(before) != identity(after)
    ):
        raise SkyAIReleaseBrokerError("release_credential_changed")
    return raw


def _env_file(path: Path) -> dict[str, str]:
    raw = _stable_regular(path, maximum=64 * 1024)
    result: dict[str, str] = {}
    try:
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise SkyAIReleaseBrokerError("github_credential_invalid") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        result[name.strip()] = value.strip().strip("'\"")
    return result


def _github_token(path: Path) -> str:
    values = _env_file(path)
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_OPS_TOKEN"):
        value = values.get(name)
        if (
            isinstance(value, str)
            and value
            and not any(char.isspace() for char in value)
        ):
            return value
    raise SkyAIReleaseBrokerError("github_credential_invalid")


def _request_bytes(
    url: str,
    *,
    method: str = "GET",
    token: str = "",
    metadata: bool = False,
    payload: bytes | None = None,
    content_type: str = "application/json",
    maximum: int = MAX_GITHUB_RESPONSE_BYTES,
) -> tuple[int, bytes, Mapping[str, str]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "muncho-skyai-release-broker/1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if metadata:
        headers["Metadata-Flavor"] = "Google"
    if payload is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read(maximum + 1)
            if len(raw) > maximum:
                raise SkyAIReleaseBrokerError("remote_response_too_large")
            return response.status, raw, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read(4096)
        return exc.code, raw, dict(exc.headers)
    except (OSError, urllib.error.URLError) as exc:
        raise SkyAIReleaseBrokerError("remote_request_failed") from exc


def _request_json(
    url: str, *, token: str = "", metadata: bool = False
) -> dict[str, Any]:
    status, raw, _headers = _request_bytes(url, token=token, metadata=metadata)
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkyAIReleaseBrokerError("remote_json_invalid") from exc
    if status != 200 or not isinstance(value, dict):
        raise SkyAIReleaseBrokerError("remote_request_rejected")
    return value


def _github(
    token: str, path: str, query: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    suffix = ""
    if query:
        suffix = "?" + urllib.parse.urlencode(query)
    return _request_json(
        f"{GITHUB_API}/repos/{SKYAI_REPOSITORY}{path}{suffix}", token=token
    )


def verify_github_candidate(token: str, sha: str) -> dict[str, Any]:
    if _SHA40.fullmatch(sha) is None:
        raise SkyAIReleaseBrokerError("source_sha_invalid")
    commit = _github(token, f"/commits/{sha}")
    if commit.get("sha") != sha:
        raise SkyAIReleaseBrokerError("source_sha_mismatch")
    tree = ((commit.get("commit") or {}).get("tree") or {}).get("sha")
    if not isinstance(tree, str) or _SHA40.fullmatch(tree) is None:
        raise SkyAIReleaseBrokerError("source_tree_invalid")
    comparison = _github(token, f"/compare/{sha}...{SKYAI_SOURCE_REF}")
    if comparison.get("status") not in {"ahead", "identical"}:
        raise SkyAIReleaseBrokerError("source_not_on_main")
    runs = _github(
        token,
        "/actions/runs",
        {
            "head_sha": sha,
            "branch": SKYAI_SOURCE_REF,
            "event": "push",
            "per_page": 100,
        },
    ).get("workflow_runs")
    if not isinstance(runs, list):
        raise SkyAIReleaseBrokerError("ci_runs_invalid")
    candidates = [
        row
        for row in runs
        if isinstance(row, dict)
        and row.get("name") == CI_WORKFLOW_NAME
        and row.get("head_sha") == sha
        and row.get("head_branch") == SKYAI_SOURCE_REF
        and row.get("event") == "push"
        and row.get("status") == "completed"
        and row.get("conclusion") == "success"
        and type(row.get("id")) is int
    ]
    if not candidates:
        raise SkyAIReleaseBrokerError("ci_aggregate_not_green")
    run = max(candidates, key=lambda row: row["id"])
    jobs = _github(token, f"/actions/runs/{run['id']}/jobs", {"per_page": 100}).get(
        "jobs"
    )
    if not isinstance(jobs, list) or not any(
        isinstance(job, dict)
        and job.get("name") == AGGREGATE_CHECK_NAME
        and job.get("status") == "completed"
        and job.get("conclusion") == "success"
        for job in jobs
    ):
        raise SkyAIReleaseBrokerError("ci_aggregate_not_green")
    return {"source_tree_sha": tree, "ci_run_id": run["id"]}


def download_archive(token: str, sha: str) -> bytes:
    status, raw, _headers = _request_bytes(
        f"{GITHUB_ARCHIVE}/{sha}",
        token=token,
        maximum=MAX_ARTIFACT_BYTES,
    )
    if status != 200 or not raw.startswith(b"\x1f\x8b"):
        raise SkyAIReleaseBrokerError("source_archive_invalid")
    return raw


def archive_behavior_version(raw: bytes) -> str:
    required_suffix = "/plugins/skyai_customer/dev_gateway.py"
    found: list[tarfile.TarInfo] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                if (
                    not parts
                    or member.name.startswith("/")
                    or ".." in parts
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or member.isfifo()
                ):
                    raise SkyAIReleaseBrokerError("source_archive_member_invalid")
                if member.name.endswith(required_suffix):
                    found.append(member)
            if len(found) != 1:
                raise SkyAIReleaseBrokerError("source_archive_skyai_identity_invalid")
            source_file = archive.extractfile(found[0])
            if source_file is None:
                raise SkyAIReleaseBrokerError("source_archive_skyai_identity_invalid")
            source = source_file.read(2 * 1024 * 1024 + 1)
    except (tarfile.TarError, OSError) as exc:
        raise SkyAIReleaseBrokerError("source_archive_invalid") from exc
    if len(source) > 2 * 1024 * 1024:
        raise SkyAIReleaseBrokerError("source_archive_skyai_identity_invalid")
    try:
        tree = ast.parse(source.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise SkyAIReleaseBrokerError("source_archive_skyai_identity_invalid") from exc
    values: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == "SKYAI_BEHAVIOR_VERSION"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            values.append(node.value.value)
    if len(values) != 1 or _BEHAVIOR.fullmatch(values[0]) is None:
        raise SkyAIReleaseBrokerError("source_behavior_version_invalid")
    return values[0]


def _metadata_token() -> str:
    value = _request_json(METADATA_TOKEN_URL, metadata=True)
    token = value.get("access_token")
    if not isinstance(token, str) or not token:
        raise SkyAIReleaseBrokerError("gcp_metadata_token_invalid")
    return token


def _upload_object(token: str, name: str, raw: bytes, *, content_type: str) -> str:
    query = urllib.parse.urlencode({
        "uploadType": "media",
        "name": name,
        "ifGenerationMatch": "0",
    })
    url = f"{GCS_UPLOAD_BASE}/b/{SKYAI_RELEASE_BUCKET}/o?{query}"
    status, body, headers = _request_bytes(
        url,
        method="POST",
        token=token,
        payload=raw,
        content_type=content_type,
        maximum=1024 * 1024,
    )
    if status == 412:
        # The object name is content-addressed.  A pre-existing exact name is
        # therefore the idempotent result of a previous completed upload.
        return "already_exists"
    if status != 200:
        raise SkyAIReleaseBrokerError("gcs_upload_failed")
    try:
        value = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkyAIReleaseBrokerError("gcs_upload_receipt_invalid") from exc
    if not isinstance(value, dict) or value.get("name") != name:
        raise SkyAIReleaseBrokerError("gcs_upload_receipt_invalid")
    generation = value.get("generation") or headers.get("x-goog-generation")
    return str(generation or "uploaded")


def cmd_status(_args: argparse.Namespace) -> None:
    value = _request_json(PUBLIC_VERSION_URL)
    _emit(
        "PASS",
        production={
            "behavior_version": value.get("behavior_version"),
            "build_commit": value.get("build_commit"),
            "live_model": value.get("live_model"),
            "runtime_mode": value.get("runtime_mode"),
        },
        release_bucket=SKYAI_RELEASE_BUCKET,
        personal_mac_required=False,
    )


def cmd_publish(args: argparse.Namespace) -> None:
    now = int(time.time())
    if (
        _SHA40.fullmatch(args.sha or "") is None
        or _BEHAVIOR.fullmatch(args.behavior_version or "") is None
        or _IDENTIFIER.fullmatch(args.case_id or "") is None
        or _IDENTIFIER.fullmatch(args.requester_id or "") is None
        or not isinstance(args.reason, str)
        or not 1 <= len(args.reason) <= 2000
    ):
        raise SkyAIReleaseBrokerError("publish_arguments_invalid")
    not_before = args.not_before_unix or now
    deploy_by = args.deploy_by_unix or now + MAX_RELEASE_DELAY_SECONDS
    if (
        type(not_before) is not int
        or type(deploy_by) is not int
        or not now <= not_before <= deploy_by
        or deploy_by - now > MAX_RELEASE_DELAY_SECONDS
    ):
        raise SkyAIReleaseBrokerError("publish_schedule_invalid")
    token = _github_token(Path(args.github_env))
    github = verify_github_candidate(token, args.sha)
    archive = download_archive(token, args.sha)
    source_behavior = archive_behavior_version(archive)
    if source_behavior != args.behavior_version:
        raise SkyAIReleaseBrokerError("publish_behavior_version_mismatch")
    artifact_sha256 = hashlib.sha256(archive).hexdigest()
    artifact_object = f"artifacts/{args.sha}/{artifact_sha256}.tar.gz"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "target": SKYAI_TARGET,
        "repository": SKYAI_REPOSITORY,
        "source_ref": SKYAI_SOURCE_REF,
        "source_sha": args.sha,
        "source_tree_sha": github["source_tree_sha"],
        "behavior_version": source_behavior,
        "artifact_bucket": SKYAI_RELEASE_BUCKET,
        "artifact_object": artifact_object,
        "artifact_sha256": artifact_sha256,
        "artifact_size": len(archive),
        "queued_at_unix": now,
        "not_before_unix": not_before,
        "deploy_by_unix": deploy_by,
        "case_id": args.case_id,
        "requester_id": args.requester_id,
        "reason_sha256": hashlib.sha256(args.reason.encode("utf-8")).hexdigest(),
        "ci_run_id": github["ci_run_id"],
        "ci_run_url": (
            f"https://github.com/{SKYAI_REPOSITORY}/actions/runs/{github['ci_run_id']}"
        ),
    }
    signing_key = _stable_regular(Path(args.signing_key), maximum=64 * 1024)
    envelope = sign_manifest(manifest, signing_key)
    envelope_raw = canonical_json_bytes(envelope) + b"\n"
    envelope_sha256 = hashlib.sha256(envelope_raw).hexdigest()
    queue_object = f"queue/{now:010d}-{args.sha}-{envelope_sha256}.json"
    gcp_token = _metadata_token()
    artifact_generation = _upload_object(
        gcp_token,
        artifact_object,
        archive,
        content_type="application/gzip",
    )
    queue_generation = _upload_object(
        gcp_token,
        queue_object,
        envelope_raw,
        content_type="application/json",
    )
    _emit(
        "QUEUED",
        source_sha=args.sha,
        source_tree_sha=github["source_tree_sha"],
        behavior_version=source_behavior,
        ci_run_id=github["ci_run_id"],
        artifact_object=artifact_object,
        artifact_sha256=artifact_sha256,
        artifact_generation=artifact_generation,
        queue_object=queue_object,
        queue_generation=queue_generation,
        not_before_unix=not_before,
        deploy_by_unix=deploy_by,
        maximum_release_delay_seconds=MAX_RELEASE_DELAY_SECONDS,
        personal_mac_required=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cloud-native SkyAI release broker")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.set_defaults(handler=cmd_status)
    publish = sub.add_parser("publish")
    publish.add_argument("--sha", required=True)
    publish.add_argument("--behavior-version", required=True)
    publish.add_argument("--case-id", required=True)
    publish.add_argument("--requester-id", required=True)
    publish.add_argument("--reason", required=True)
    publish.add_argument("--not-before-unix", type=int)
    publish.add_argument("--deploy-by-unix", type=int)
    publish.add_argument("--github-env", default=str(DEFAULT_GITHUB_ENV))
    publish.add_argument("--signing-key", default=str(DEFAULT_SIGNING_KEY))
    publish.set_defaults(handler=cmd_publish)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
    except SkyAIReleaseBrokerError as exc:
        _emit("BLOCKED", code=2, reason=exc.code, personal_mac_required=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
