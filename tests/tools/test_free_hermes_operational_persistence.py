from __future__ import annotations

import json

from tools import canonical_brain_tool as cbt


def test_plamena_class_route_back_replay_uses_hermes_tool_not_keyword_authority(monkeypatch):
    captured = {}

    def fake_append(**kwargs):
        captured.update(kwargs)
        return json.dumps({"success": True, "status": "CANONICAL_EVENT_APPEND_PASS", "event_type": kwargs["event_type"]})

    monkeypatch.setattr(cbt, "canonical_event_append_tool", fake_append)
    out = cbt.route_back_tool(
        case_id="case:replay-directed-colleague-route-back",
        target_ref={"id": "emil_lomliev", "lane": "owner_control_tower"},
        message_summary="Colleague asked Hermes to notify a target person; origin reply alone is not completion.",
        source_refs={"platform": "discord", "thread_id": "1518976443168854146", "message_id": "fixture-message"},
        mode="record_required_only",
        idempotency_key="fixture-directed-route-back",
    )
    data = json.loads(out)
    assert data["success"] is True
    assert captured["event_type"] == "route_back.required"
    assert captured["payload"]["route_back"]["target_ref"]["id"] == "emil_lomliev"
    assert captured["safety"]["contains_secret"] is False


def test_casual_discussion_can_be_recorded_as_case_note_without_handoff():
    # This verifies the tool contract is not a keyword classifier: Hermes may
    # choose a case.note for durable context without creating route_back state.
    event_id = cbt._event_uuid("casual-note")
    assert event_id
    assert "route_back.required" in cbt.ALLOWED_EVENT_TYPES
    assert "case.note" in cbt.ALLOWED_EVENT_TYPES


def test_sent_claim_requires_mechanical_receipt_not_llm_text():
    out = cbt.route_back_tool(
        case_id="case:replay-directed-colleague-route-back",
        target_ref={"id": "emil_lomliev"},
        message_summary="LLM text saying sent is not a receipt",
        source_refs={"platform": "discord", "message_id": "fixture-message"},
        mode="record_sent_receipt",
        receipt={"note": "Hermes said it sent it, but no message_id exists"},
    )
    data = json.loads(out)
    assert "requires receipt.message_id" in data["error"]
