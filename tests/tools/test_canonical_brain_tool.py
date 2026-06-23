from __future__ import annotations

import json

import pytest

from tools import canonical_brain_tool as cbt


def test_route_back_sent_requires_receipt_message_id():
    out = cbt.route_back_tool(
        case_id="case:test",
        target_ref={"id": "emil"},
        message_summary="summary",
        source_refs={"platform": "discord", "message_id": "m1"},
        mode="record_sent_receipt",
        receipt={},
    )
    data = json.loads(out)
    assert "requires receipt.message_id" in data["error"]


def test_canonical_event_append_blocks_keyword_authority_secret_like_payload():
    out = cbt.canonical_event_append_tool(
        event_type="case.note",
        case_id="case:test",
        summary="summary",
        source_refs={"platform": "discord", "message_id": "m1"},
        payload={"note": "token=abc"},
    )
    data = json.loads(out)
    assert "secret_like_content_blocked" in data["error"]


def test_event_uuid_is_deterministic_from_idempotency_key():
    assert cbt._event_uuid("same-key") == cbt._event_uuid("same-key")
    assert cbt._event_uuid("same-key") != cbt._event_uuid("different-key")


class _FakeSock:
    def close(self):
        pass


class _FakeHelper:
    def __init__(self):
        self.queries = []

    @staticmethod
    def get_secret_value():
        return "not-printed"

    @staticmethod
    def connect(password):
        assert password == "not-printed"
        return _FakeSock()

    @staticmethod
    def sql_quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    @staticmethod
    def json_sql(value):
        return _FakeHelper.sql_quote(json.dumps(value, sort_keys=True, separators=(",", ":"))) + "::jsonb"

    def query(self, sock, sql):
        self.queries.append(sql)
        if sql.lstrip().upper().startswith("SELECT"):
            return {"rows": [["event-id", "case.note", "case:test", "2026-01-01", "idem"]], "command_tag": "SELECT 1"}
        return {"rows": [], "command_tag": "INSERT 0 1"}


def test_append_uses_helper_and_returns_readback(monkeypatch):
    fake = _FakeHelper()
    monkeypatch.setattr(cbt, "_load_helper", lambda: fake)
    out = cbt.canonical_event_append_tool(
        event_type="case.note",
        case_id="case:test",
        summary="summary",
        source_refs={"platform": "discord", "message_id": "m1"},
        idempotency_key="idem",
    )
    data = json.loads(out)
    assert data["success"] is True
    assert data["status"] == "CANONICAL_EVENT_APPEND_PASS"
    assert data["idempotency_key"] == "idem"
    assert data["inserted"] is True
    assert any("INSERT INTO canonical_event_log" in q for q in fake.queries)
