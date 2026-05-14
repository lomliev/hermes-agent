import json
from datetime import datetime, timezone
from pathlib import Path

from gateway import mcp_bridge


def _write_record(tasks_dir: Path, task_id: str, title: str) -> Path:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "task_id": task_id,
        "status": "accepted",
        "created_at": now,
        "updated_at": now,
        "project": "Adventico AI Ops",
        "title": title,
        "mode": "TEST",
        "repo_scope": None,
        "worktree_scope": None,
        "payload": {
            "title": title,
            "approvals": {"same_record_result_update_allowed": True},
        },
        "refusal_reason": None,
        "execution": {"state": "not_executed"},
        "result": None,
    }
    path = tasks_dir / f"{task_id}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def test_resolves_playground_bridge_home_when_gateway_home_is_default(monkeypatch, tmp_path):
    gateway_home = tmp_path / "gateway_home"
    bridge_tasks = gateway_home / "mcp_bridge_playground_home" / "mcp_bridge_tasks"
    task_id = "mcp_0e1cdfaec0ca4d0681a50902ff9ec8b4"
    _write_record(bridge_tasks, task_id, "002CA Discord mirror live test")

    monkeypatch.setenv("HERMES_HOME", str(gateway_home))
    monkeypatch.delenv("HERMES_MCP_BRIDGE_HOME", raising=False)
    monkeypatch.delenv("HERMES_MCP_BRIDGE_TASKS_DIR", raising=False)

    assert mcp_bridge.resolve_task_id_from_text("Continue 002CA") == task_id


def test_explicit_bridge_home_resolves_and_mirror_writes_without_global_home(monkeypatch, tmp_path):
    gateway_home = tmp_path / "gateway_home"
    bridge_home = tmp_path / "dedicated_bridge_home"
    bridge_tasks = bridge_home / "mcp_bridge_tasks"
    task_id = "mcp_1234567890abcdef"
    record_path = _write_record(bridge_tasks, task_id, "002CC Mirror inbox path test")

    monkeypatch.setenv("HERMES_HOME", str(gateway_home))
    monkeypatch.setenv("HERMES_MCP_BRIDGE_HOME", str(bridge_home))
    monkeypatch.delenv("HERMES_MCP_BRIDGE_TASKS_DIR", raising=False)

    assert mcp_bridge.resolve_task_id_from_text("Continue 002CC") == task_id
    assert mcp_bridge.mirror_task_result(task_id, "final discord response", platform="discord") is True

    updated = json.loads(record_path.read_text(encoding="utf-8"))
    assert updated["result"] == {
        "source": "discord_gateway_final_response",
        "platform": "discord",
        "response": "final discord response",
    }
    assert updated["execution"]["state"] == "completed"
    assert updated["execution"]["result_mirrored_by"] == "Hermes"


def test_explicit_tasks_dir_overrides_bridge_home(monkeypatch, tmp_path):
    gateway_home = tmp_path / "gateway_home"
    bridge_home = tmp_path / "empty_bridge_home"
    tasks_dir = tmp_path / "explicit_tasks"
    task_id = "mcp_explicitdir123"
    _write_record(tasks_dir, task_id, "002CD Explicit tasks dir test")

    monkeypatch.setenv("HERMES_HOME", str(gateway_home))
    monkeypatch.setenv("HERMES_MCP_BRIDGE_HOME", str(bridge_home))
    monkeypatch.setenv("HERMES_MCP_BRIDGE_TASKS_DIR", str(tasks_dir))

    assert mcp_bridge.resolve_task_id_from_text("Continue 002CD") == task_id
