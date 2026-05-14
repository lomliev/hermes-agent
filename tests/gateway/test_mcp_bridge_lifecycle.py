from __future__ import annotations

from gateway import mcp_bridge
from gateway import mcp_bridge_tools


def _valid_payload(title: str = "002CT Canonical lifecycle mirror helper") -> dict:
    return {
        "title": title,
        "project": "hermes-agent",
        "mode": "local",
        "worktree_scope": {"path": "/tmp/hermes-worktree"},
        "task_contract": {
            "objective": "Implement canonical lifecycle mirror state without executing tasks.",
            "acceptance_criteria": ["terminal mirror state is normalized"],
        },
        "allowed_actions": ["read files", "edit scoped bridge files", "run targeted tests"],
        "forbidden_actions": ["run_shell", "git_push", "docker_run"],
        "return_format": {"sections": ["summary", "tests"]},
        "training_notes": {"preserve": "metadata-like payload content"},
    }


def test_mirror_task_result_sets_canonical_completed_lifecycle(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_MCP_BRIDGE_HOME", raising=False)
    monkeypatch.delenv("HERMES_MCP_BRIDGE_TASKS_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    submitted = mcp_bridge.submit_task(_valid_payload())
    before = mcp_bridge.get_task_result(submitted["task_id"])["record"]

    assert mcp_bridge.mirror_task_result(
        submitted["task_id"],
        "Lifecycle response.",
        platform="discord",
    ) is True

    after = mcp_bridge.get_task_result(submitted["task_id"])["record"]
    assert after["status"] == "completed"
    assert after["execution"]["state"] == "completed"
    assert after["execution"]["result_mirrored_by"] == "Hermes"
    assert after["result"] == {
        "source": "discord_gateway_final_response",
        "platform": "discord",
        "response": "Lifecycle response.",
    }
    assert after["result"] is not None
    assert after["updated_at"] != before["updated_at"]
    assert after["payload"] == before["payload"]
    assert after["payload"]["task_contract"] == before["payload"]["task_contract"]
    assert after["payload"]["training_notes"] == before["payload"]["training_notes"]


def test_mirror_task_result_supports_manual_discord_result_source(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_MCP_BRIDGE_HOME", raising=False)
    monkeypatch.delenv("HERMES_MCP_BRIDGE_TASKS_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    submitted = mcp_bridge.submit_task(_valid_payload())

    mirrored = mcp_bridge.mirror_task_result(
        submitted["task_id"],
        "Manual mirror response.",
        platform="discord",
        source="discord_manual_result_mirror",
    )

    assert mirrored is True
    record = mcp_bridge.get_task_result(submitted["task_id"])["record"]
    assert record["status"] == "completed"
    assert record["result"]["source"] == "discord_manual_result_mirror"
    assert record["result"]["response"] == "Manual mirror response."


def test_mirror_task_result_is_idempotent_for_same_response(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_MCP_BRIDGE_HOME", raising=False)
    monkeypatch.delenv("HERMES_MCP_BRIDGE_TASKS_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    submitted = mcp_bridge.submit_task(_valid_payload())

    assert mcp_bridge.mirror_task_result(
        submitted["task_id"],
        "Same final response.",
        platform="discord",
    ) is True
    first = mcp_bridge.get_task_result(submitted["task_id"])["record"]

    assert mcp_bridge.mirror_task_result(
        submitted["task_id"],
        "Same final response.",
        platform="discord",
    ) is True
    second = mcp_bridge.get_task_result(submitted["task_id"])["record"]

    assert second == first


def test_mirror_task_result_keeps_refused_records_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_MCP_BRIDGE_HOME", raising=False)
    monkeypatch.delenv("HERMES_MCP_BRIDGE_TASKS_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    payload = _valid_payload()
    payload.pop("worktree_scope")
    submitted = mcp_bridge.submit_task(payload)
    before = mcp_bridge.get_task_result(submitted["task_id"])["record"]

    assert mcp_bridge.mirror_task_result(
        submitted["task_id"],
        "Should not complete.",
        platform="discord",
    ) is False

    after = mcp_bridge.get_task_result(submitted["task_id"])["record"]
    assert after == before
    assert after["status"] == "refused"
    assert after["execution"]["state"] == "not_executed"
    assert after["result"] is None


def test_mcp_bridge_exposed_tool_surface_stays_exact_four():
    assert {schema["name"] for schema in mcp_bridge_tools.TOOL_SCHEMAS} == {
        "submit_task",
        "get_task_status",
        "get_task_result",
        "list_recent_tasks",
    }
    assert set(mcp_bridge_tools.TOOL_HANDLERS) == {
        "submit_task",
        "get_task_status",
        "get_task_result",
        "list_recent_tasks",
    }
