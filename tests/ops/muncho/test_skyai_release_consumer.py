from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from ops.muncho.runtime import skyai_release_consumer as consumer


ROOT = Path(__file__).resolve().parents[3]


def _archive(*, member: str = "repo/file.txt") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        raw = b"safe"
        info = tarfile.TarInfo(member)
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


def test_safe_extract_strips_single_archive_root_and_rejects_traversal(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "release"
    consumer.safe_extract_archive(_archive(), destination)
    assert (destination / "file.txt").read_bytes() == b"safe"

    with pytest.raises(consumer.SkyAIReleaseConsumerError):
        consumer.safe_extract_archive(
            _archive(member="../outside.txt"), tmp_path / "unsafe"
        )
    assert not (tmp_path / "outside.txt").exists()


def test_service_environment_supports_systemd_export_and_exact_rewrite() -> None:
    raw = b"# production\nexport FOO='bar'\nSKYAI_V2_BUILD_COMMIT=old\n"
    assert consumer._parse_env(raw) == {
        "FOO": "bar",
        "SKYAI_V2_BUILD_COMMIT": "old",
    }
    assert consumer._rewrite_build_commit(raw, "a" * 40) == (
        b"# production\nexport FOO='bar'\nSKYAI_V2_BUILD_COMMIT=" + b"a" * 40 + b"\n"
    )


def test_candidate_selection_honors_not_before_and_retry_without_semantic_routing() -> (
    None
):
    first = {
        "not_before_unix": 100,
        "queued_at_unix": 100,
        "deploy_by_unix": 200,
    }
    second = {
        "not_before_unix": 110,
        "queued_at_unix": 110,
        "deploy_by_unix": 210,
    }
    state = {
        "records": {"queue/second.json": {"status": "RETRY", "next_retry_unix": 150}}
    }
    assert consumer.select_candidate(
        [("queue/first.json", first), ("queue/second.json", second)],
        now=120,
        state=state,
    ) == ("queue/first.json", first)
    assert consumer.select_candidate(
        [("queue/first.json", first), ("queue/second.json", second)],
        now=160,
        state=state,
    ) == ("queue/second.json", second)


def test_target_consumer_script_imports_under_isolated_python() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(ROOT / "ops/muncho/runtime/skyai_release_consumer.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
