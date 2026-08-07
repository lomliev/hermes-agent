from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from ops.muncho.runtime import skyai_release_broker as broker


SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[3]


def _archive(behavior: str = "v2.19", *, unsafe: bool = False) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        source = f"SKYAI_BEHAVIOR_VERSION = {behavior!r}\n".encode()
        info = tarfile.TarInfo(
            "repo/plugins/skyai_customer/dev_gateway.py"
            if not unsafe
            else "../plugins/skyai_customer/dev_gateway.py"
        )
        info.size = len(source)
        archive.addfile(info, io.BytesIO(source))
    return buffer.getvalue()


def test_archive_behavior_identity_is_parsed_structurally() -> None:
    assert broker.archive_behavior_version(_archive()) == "v2.19"
    with pytest.raises(broker.SkyAIReleaseBrokerError):
        broker.archive_behavior_version(_archive(unsafe=True))


def test_github_candidate_requires_main_ancestry_and_green_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def github(_token: str, path: str, query=None):
        calls.append(path)
        if path == f"/commits/{SHA}":
            return {"sha": SHA, "commit": {"tree": {"sha": "b" * 40}}}
        if path == f"/compare/{SHA}...main":
            return {"status": "ahead"}
        if path == "/actions/runs":
            return {
                "workflow_runs": [
                    {
                        "id": 42,
                        "name": "CI",
                        "head_sha": SHA,
                        "head_branch": "main",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }
        if path == "/actions/runs/42/jobs":
            return {
                "jobs": [
                    {
                        "name": "All required checks pass",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(broker, "_github", github)
    assert broker.verify_github_candidate("token", SHA) == {
        "source_tree_sha": "b" * 40,
        "ci_run_id": 42,
    }
    assert calls == [
        f"/commits/{SHA}",
        f"/compare/{SHA}...main",
        "/actions/runs",
        "/actions/runs/42/jobs",
    ]


def test_github_candidate_rejects_missing_green_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def github(_token: str, path: str, query=None):
        if path == f"/commits/{SHA}":
            return {"sha": SHA, "commit": {"tree": {"sha": "b" * 40}}}
        if path == f"/compare/{SHA}...main":
            return {"status": "identical"}
        if path == "/actions/runs":
            return {"workflow_runs": []}
        raise AssertionError(path)

    monkeypatch.setattr(broker, "_github", github)
    with pytest.raises(broker.SkyAIReleaseBrokerError, match="ci_aggregate_not_green"):
        broker.verify_github_candidate("token", SHA)


def test_release_pinned_broker_script_imports_under_isolated_python() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(ROOT / "ops/muncho/runtime/skyai_release_broker.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
