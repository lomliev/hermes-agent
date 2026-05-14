"""Private lifecycle helpers for local MCP bridge task records.

This module is deliberately not part of the public MCP tool facade. It only
coordinates stored bridge records that were already accepted by submit_task.
"""

from __future__ import annotations

import json
import re
from typing import Any

from gateway import mcp_bridge


_ELIGIBLE_STATUSES = {"accepted", "notification_dispatched", "accepted_no_dispatch"}
_ELIGIBLE_STATES = {"not_executed", "notification_dispatched", "accepted_no_dispatch"}
_TERMINAL_STATUSES = {"refused", "completed", "blocked", "failed"}
_TERMINAL_STATES = {"approval_required", "completed", "blocked", "failed"}

_SAFE_INTENT_PATTERN = re.compile(
    r"\b(read[-\s]?only|diagnos(?:e|tic)|pre[-\s]?check|notification[-\s]?only|"
    r"health|status|inventory|list(?:ing)?|list[_ -]?tools|process\s+status)\b",
    re.I,
)
_SAFE_ACTION_PATTERN = re.compile(
    r"\b(read|inspect|list|inventory|check|status|diagnos(?:e|tic)|pre[-\s]?check|"
    r"notification|summari[sz]e|report)\b",
    re.I,
)
_ESCALATION_PATTERN = re.compile(
    r"\b(approval|approve|escalat(?:e|ion)|sudo|secret|token|credential|\.env|"
    r"write|edit|modify|mutation|mutate|delete|remove|deploy|release|restart|"
    r"reload|refresh|submit[_ -]?task|run[_ -]?shell|raw\s+shell|shell\s+access|"
    r"direct\s+command|execute\s+command|openai\s+api|openai[_ -]?call|"
    r"docker|shopify|prod(?:uction)?|git\s+(?:reset|clean|merge|rebase|stash|"
    r"tag|fetch|pull|push)|force\s+push|run\s+tests?|targeted\s+tests?)\b",
    re.I,
)


def _flatten(value: Any) -> str:
    parts: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            parts.append(str(key))
            parts.append(_flatten(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            parts.append(_flatten(item))
    elif value is not None:
        parts.append(str(value))
    return " ".join(part for part in parts if part)


def _task_owner(record: dict[str, Any]) -> str | None:
    execution = record.get("execution")
    if not isinstance(execution, dict):
        return None
    owner = execution.get("owner")
    return str(owner) if owner else None


def _record_is_terminal(record: dict[str, Any]) -> bool:
    execution = record.get("execution")
    execution_state = execution.get("state") if isinstance(execution, dict) else None
    return record.get("status") in _TERMINAL_STATUSES or execution_state in _TERMINAL_STATES


def _safe_read_only_diagnostic(record: dict[str, Any]) -> bool:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return False

    positive_fields = {
        "title": payload.get("title"),
        "mode": payload.get("mode"),
        "task_contract": payload.get("task_contract"),
        "allowed_actions": payload.get("allowed_actions"),
        "repo_scope": payload.get("repo_scope"),
        "worktree_scope": payload.get("worktree_scope"),
        "approvals": payload.get("approvals"),
        "labels": payload.get("labels"),
        "tags": payload.get("tags"),
        "kind": payload.get("kind"),
    }
    positive_text = _flatten(positive_fields)
    if not _SAFE_INTENT_PATTERN.search(positive_text):
        return False
    if _ESCALATION_PATTERN.search(positive_text):
        return False

    allowed_actions = payload.get("allowed_actions")
    if not isinstance(allowed_actions, list) or not allowed_actions:
        return False
    for action in allowed_actions:
        action_text = _flatten(action)
        if not _SAFE_ACTION_PATTERN.search(action_text):
            return False
        if _ESCALATION_PATTERN.search(action_text):
            return False
    return True


def is_execution_candidate(record: dict[str, Any]) -> bool:
    """Return whether an accepted record is eligible for a private runner."""
    if not isinstance(record, dict):
        return False
    if _record_is_terminal(record):
        return False
    if record.get("approval_required_reason"):
        return False
    if record.get("status") not in _ELIGIBLE_STATUSES:
        return False

    execution = record.get("execution")
    execution_state = execution.get("state") if isinstance(execution, dict) else None
    if execution_state not in _ELIGIBLE_STATES:
        return False
    return _safe_read_only_diagnostic(record)


def list_execution_candidates(limit: int = 20) -> dict[str, Any]:
    """List private execution candidates without mutating records."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise mcp_bridge.MCPBridgeError("limit must be an integer") from None
    if limit < 1 or limit > 100:
        raise mcp_bridge.MCPBridgeError("limit must be between 1 and 100")

    directory = mcp_bridge._task_dir()
    records: list[dict[str, Any]] = []
    if directory.exists():
        for path in directory.glob("mcp_*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if is_execution_candidate(record):
                records.append(record)

    records.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return {
        "ok": True,
        "tasks": [
            {
                "task_id": record.get("task_id"),
                "status": record.get("status"),
                "created_at": record.get("created_at"),
                "updated_at": record.get("updated_at"),
                "project": record.get("project"),
                "title": record.get("title"),
                "execution": record.get("execution"),
            }
            for record in records[:limit]
        ],
    }


def claim_execution_candidate(task_id: str, *, owner: str) -> dict[str, Any]:
    """Claim an eligible record for one private owner."""
    owner = str(owner or "").strip()
    if not owner:
        raise mcp_bridge.MCPBridgeError("owner is required")

    record = mcp_bridge._read_record(task_id)
    execution = record.get("execution")
    execution_state = execution.get("state") if isinstance(execution, dict) else None
    current_owner = _task_owner(record)

    if execution_state == "claimed":
        if current_owner == owner:
            return {"ok": True, "claimed": True, "task_id": task_id, "owner": owner}
        return {
            "ok": False,
            "claimed": False,
            "task_id": task_id,
            "owner": owner,
            "reason": "task already claimed by another owner",
        }

    if not is_execution_candidate(record):
        return {
            "ok": False,
            "claimed": False,
            "task_id": task_id,
            "owner": owner,
            "reason": "task is not an execution candidate",
        }

    mcp_bridge.update_task_lifecycle(
        task_id,
        status="accepted",
        execution_state="claimed",
        execution_updates={
            "owner": owner,
            "claimed_at": mcp_bridge._now_iso(),
            "message": "Claimed by private MCP bridge lifecycle helper.",
        },
    )
    return {"ok": True, "claimed": True, "task_id": task_id, "owner": owner}


def _transition_claimed_or_running(
    task_id: str,
    *,
    owner: str,
    status: str,
    execution_state: str,
    result: dict[str, Any] | None = None,
    message: str,
    extra_execution: dict[str, Any] | None = None,
) -> bool:
    owner = str(owner or "").strip()
    if not owner:
        raise mcp_bridge.MCPBridgeError("owner is required")

    record = mcp_bridge._read_record(task_id)
    if _record_is_terminal(record):
        return False
    execution = record.get("execution")
    current_state = execution.get("state") if isinstance(execution, dict) else None
    if current_state not in {"claimed", "running"}:
        return False
    if _task_owner(record) != owner:
        return False

    updates = {
        "owner": owner,
        "message": message,
        f"{execution_state}_at": mcp_bridge._now_iso(),
    }
    if extra_execution:
        updates.update(extra_execution)
    return mcp_bridge.update_task_lifecycle(
        task_id,
        status=status,
        execution_state=execution_state,
        result=result,
        execution_updates=updates,
    )


def mark_task_running(task_id: str, *, owner: str) -> bool:
    return _transition_claimed_or_running(
        task_id,
        owner=owner,
        status="accepted",
        execution_state="running",
        message="Private MCP bridge lifecycle helper marked the task running.",
    )


def complete_task(task_id: str, *, owner: str, result: dict[str, Any]) -> bool:
    return _transition_claimed_or_running(
        task_id,
        owner=owner,
        status="completed",
        execution_state="completed",
        result=mcp_bridge._jsonable(result),
        message="Private MCP bridge lifecycle helper completed the task.",
    )


def block_task(task_id: str, *, owner: str, reason: str) -> bool:
    reason = str(reason or "")
    return _transition_claimed_or_running(
        task_id,
        owner=owner,
        status="blocked",
        execution_state="blocked",
        result={"source": "mcp_bridge_lifecycle", "status": "BLOCKED", "reason": reason},
        message=reason or "Private MCP bridge lifecycle helper blocked the task.",
        extra_execution={"block_reason": reason},
    )


def fail_task(task_id: str, *, owner: str, error: str) -> bool:
    error = str(error or "")
    return _transition_claimed_or_running(
        task_id,
        owner=owner,
        status="failed",
        execution_state="failed",
        result={"source": "mcp_bridge_lifecycle", "status": "FAILED", "error": error},
        message=error or "Private MCP bridge lifecycle helper failed the task.",
        extra_execution={"error": error},
    )
