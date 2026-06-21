import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from gateway.canonical_brain_audit import (
    _METADATA_KEY,
    CanonicalBrainAuditBridge,
    CanonicalBrainAuditConfig,
    load_audit_config,
    reset_audit_bridge_cache,
)
from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType, SendResult
from gateway.session import SessionSource


def _source() -> SessionSource:
    return SessionSource(
        platform=Platform.DISCORD,
        chat_id="channel-123",
        chat_type="thread",
        user_id="user-456",
        user_name="Operator",
        thread_id="thread-789",
        guild_id="guild-abc",
    )


def _bridge(tmp_path: Path) -> CanonicalBrainAuditBridge:
    return CanonicalBrainAuditBridge(
        CanonicalBrainAuditConfig(
            enabled=True,
            jsonl_path=tmp_path / "audit.jsonl",
            runtime_id="cloud-hermes",
            role="primary-discord-runtime",
            host="ai-platform-runtime-01",
        )
    )


def _read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_load_audit_config_defaults_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("gateway.canonical_brain_audit.get_hermes_home", lambda: tmp_path)
    reset_audit_bridge_cache()

    cfg = load_audit_config()

    assert cfg.enabled is False
    assert cfg.backend == "jsonl"


def test_load_audit_config_reads_yaml_gate(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        """
canonical_brain:
  audit_bridge:
    enabled: true
    backend: jsonl
    jsonl_path: /tmp/canonical-audit.jsonl
    runtime_id: cloud-hermes
    role: primary-discord-runtime
  runtime_lease:
    enforcement_enabled: true
    send_path_blocking_enabled: false
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("gateway.canonical_brain_audit.get_hermes_home", lambda: tmp_path)
    reset_audit_bridge_cache()

    cfg = load_audit_config()

    assert cfg.enabled is True
    assert cfg.jsonl_path == Path("/tmp/canonical-audit.jsonl")
    assert cfg.runtime_id == "cloud-hermes"
    assert cfg.runtime_lease_enforcement_enabled is True
    assert cfg.runtime_lease_send_path_blocking_enabled is False


def test_inbound_event_is_metadata_only_and_stable(tmp_path):
    bridge = _bridge(tmp_path)
    event = MessageEvent(
        text="Do not retain this raw operational message",
        message_type=MessageType.TEXT,
        source=_source(),
        message_id="message-001",
    )

    asyncio.run(bridge.record_inbound(event, "agent:main:discord:channel-123:thread-789"))
    asyncio.run(bridge.record_inbound(event, "agent:main:discord:channel-123:thread-789"))

    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    events = _read_events(tmp_path / "audit.jsonl")
    assert len(events) == 2
    assert events[0]["event_id"] == events[1]["event_id"]
    assert events[0]["event_type"] == "discord.inbound.received"
    assert events[0]["payload"]["message_length"] == len(event.text)
    assert "Do not retain" not in raw
    assert "message-001" not in raw
    assert "user-456" not in raw


def test_assistant_status_event_is_metadata_only(tmp_path):
    bridge = _bridge(tmp_path)

    asyncio.run(
        bridge.record_assistant_status(
            source=_source(),
            session_key="agent:main:discord:channel-123:thread-789",
            session_id="session-001",
            inbound_message_id="message-001",
            run_generation=3,
            status="completed",
            response_chars=42,
            api_calls=2,
            elapsed_seconds=1.5,
        )
    )

    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    event = _read_events(tmp_path / "audit.jsonl")[0]
    assert event["event_type"] == "assistant.status"
    assert event["status"]["state"] == "pass"
    assert event["payload"]["response_chars"] == 42
    assert "session-001" not in raw
    assert "message-001" not in raw


def test_outbound_intent_and_receipt_are_metadata_only(tmp_path):
    bridge = _bridge(tmp_path)
    source = _source()
    marker = bridge.intent_marker(
        source=source,
        session_key="agent:main:discord:channel-123:thread-789",
        inbound_message_id="message-001",
        intent_kind="assistant.final_response",
    )
    metadata = {_METADATA_KEY: marker, "thread_id": source.thread_id}

    asyncio.run(
        bridge.record_outbound_intent(
            source=source,
            session_key="agent:main:discord:channel-123:thread-789",
            marker=marker,
            content="Do not retain this assistant response",
        )
    )
    asyncio.run(
        bridge.record_outbound_receipt(
            chat_id=source.chat_id,
            metadata=metadata,
            result=SendResult(
                success=True,
                message_id="discord-response-001",
                raw_response={"message_ids": ["discord-response-001"]},
            ),
            content="Do not retain this assistant response",
        )
    )

    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    events = _read_events(tmp_path / "audit.jsonl")
    assert [event["event_type"] for event in events] == [
        "outbound.intent.recorded",
        "outbound.receipt.recorded",
    ]
    assert events[0]["case"]["case_id"] == events[1]["case"]["case_id"]
    assert events[1]["payload"]["message_count"] == 1
    assert "Do not retain" not in raw
    assert "discord-response-001" not in raw


def test_outbound_intent_marker_carries_disabled_enforcement_flags(tmp_path):
    bridge = _bridge(tmp_path)
    source = _source()

    marker = bridge.intent_marker(
        source=source,
        session_key="agent:main:discord:channel-123:thread-789",
        inbound_message_id="message-001",
        intent_kind="assistant.final_response",
    )

    preflight = marker["runtime_lease_enforcement"]
    assert preflight["config_path"] == "canonical_brain.runtime_lease"
    assert preflight["enforcement_enabled"] is False
    assert preflight["send_path_blocking_enabled"] is False
    assert preflight["blocking_effective"] is False
    assert preflight["preflight_read_at"]
