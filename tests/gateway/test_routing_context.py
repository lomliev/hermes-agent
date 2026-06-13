"""Tests for cross-chat route-back context."""

import json

import gateway.routing_context as routing_context
from gateway.routing_context import (
    format_route_context_note,
    format_target,
    lookup_outbound_route,
    record_outbound_route,
)


def test_format_target_omits_duplicate_thread_id():
    assert format_target("discord", "1509473981860941844", "1509473981860941844") == (
        "discord:1509473981860941844"
    )
    assert format_target("telegram", "-1001", "42") == "telegram:-1001:42"


def test_record_and_lookup_route_context(tmp_path, monkeypatch):
    state_path = tmp_path / "routing_context.json"
    monkeypatch.setattr(routing_context, "_STATE_PATH", state_path)

    ok = record_outbound_route(
        platform="discord",
        chat_id="1504852408227069993",
        message_id="1510000000000000000",
        return_target="discord:1509473981860941844",
        return_label="Ivs discount thread",
        return_user="Ivs",
        original_message="Иво/Alex, моля проверете казуса",
    )

    assert ok is True
    route = lookup_outbound_route(
        platform="discord",
        chat_id="1504852408227069993",
        message_id="1510000000000000000",
    )
    assert route["return_target"] == "discord:1509473981860941844"
    assert route["return_user"] == "Ivs"

    data = json.loads(state_path.read_text())
    assert "discord:1504852408227069993:1510000000000000000" in data["routes"]


def test_format_route_context_note_mentions_return_target():
    note = format_route_context_note(
        {
            "return_target": "discord:1509473981860941844",
            "return_label": "Ivs discount thread",
            "return_user": "Ivs",
        }
    )

    assert "Return target: `discord:1509473981860941844`" in note
    assert "send_message" in note
