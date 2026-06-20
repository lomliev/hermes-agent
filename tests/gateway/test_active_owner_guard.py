import asyncio
import json

import pytest

from gateway.active_owner_guard import check_active_owner, resolve_active_owner_guard_config
from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from gateway.session import SessionSource


def _write_state(path, active_owner="cloud"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "muncho-active-owner.v1",
                "active_owner": active_owner,
                "enforcement": "gateway_guard",
            }
        ),
        encoding="utf-8",
    )


def _guard_config(path, *, runtime_id="cloud", enabled=True, fail_closed=True):
    return PlatformConfig(
        enabled=True,
        token="test",
        extra={
            "active_owner_guard": {
                "enabled": enabled,
                "runtime_id": runtime_id,
                "state_path": str(path),
                "fail_closed": fail_closed,
            }
        },
    )


def test_guard_is_disabled_by_default():
    decision = check_active_owner(PlatformConfig(enabled=True, extra={}))

    assert decision.allowed is True
    assert decision.reason == "active-owner guard disabled"


def test_guard_allows_matching_active_owner(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path, active_owner="cloud")

    decision = check_active_owner(_guard_config(state_path, runtime_id="cloud"))

    assert decision.allowed is True
    assert decision.active_owner == "cloud"
    assert decision.runtime_id == "cloud"


def test_guard_blocks_mismatched_active_owner(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path, active_owner="cloud")

    decision = check_active_owner(_guard_config(state_path, runtime_id="local"))

    assert decision.allowed is False
    assert decision.active_owner == "cloud"
    assert "does not match" in decision.reason


def test_guard_fail_closed_blocks_missing_state(tmp_path):
    state_path = tmp_path / "missing.json"

    decision = check_active_owner(_guard_config(state_path, runtime_id="cloud"))

    assert decision.allowed is False
    assert decision.reason == "active-owner state file missing"


def test_guard_can_fail_open_for_break_glass_diagnostics(tmp_path):
    state_path = tmp_path / "missing.json"

    decision = check_active_owner(
        _guard_config(state_path, runtime_id="cloud", fail_closed=False)
    )

    assert decision.allowed is True
    assert decision.reason == "active-owner state file missing"


def test_guard_accepts_explicit_alias_key(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path, active_owner="local")
    config = PlatformConfig(
        enabled=True,
        extra={
            "muncho_active_owner_guard": {
                "enabled": "yes",
                "node_id": "local",
                "state_path": str(state_path),
            }
        },
    )

    resolved = resolve_active_owner_guard_config(config)
    decision = check_active_owner(config)

    assert resolved.enabled is True
    assert resolved.runtime_id == "local"
    assert decision.allowed is True


class _GuardedAdapter(BasePlatformAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sent_messages = []

    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent_messages.append((chat_id, content))
        return SendResult(success=True, message_id="sent-1")

    async def get_chat_info(self, chat_id):
        return {"name": "Test", "type": "dm"}


def _event(text="hello"):
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=Platform.DISCORD,
            chat_id="channel-1",
            chat_type="channel",
            user_id="user-1",
        ),
        message_id="msg-1",
    )


@pytest.mark.asyncio
async def test_handle_message_does_not_start_handler_when_owner_mismatches(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path, active_owner="cloud")
    adapter = _GuardedAdapter(_guard_config(state_path, runtime_id="local"), Platform.DISCORD)
    called = asyncio.Event()

    async def handler(_event):
        called.set()
        return None

    adapter.set_message_handler(handler)

    await adapter.handle_message(_event())
    await asyncio.sleep(0)

    assert called.is_set() is False
    assert adapter._active_sessions == {}
    assert adapter._session_tasks == {}


@pytest.mark.asyncio
async def test_handle_message_starts_handler_when_owner_matches(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path, active_owner="cloud")
    adapter = _GuardedAdapter(_guard_config(state_path, runtime_id="cloud"), Platform.DISCORD)
    called = asyncio.Event()

    async def handler(_event):
        called.set()
        return None

    adapter.set_message_handler(handler)

    await adapter.handle_message(_event())
    await asyncio.wait_for(called.wait(), timeout=1)


@pytest.mark.asyncio
async def test_send_with_retry_blocks_when_owner_switches_mid_run(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path, active_owner="cloud")
    adapter = _GuardedAdapter(_guard_config(state_path, runtime_id="cloud"), Platform.DISCORD)

    _write_state(state_path, active_owner="local")
    result = await adapter._send_with_retry("channel-1", "old runtime response")

    assert result.success is False
    assert "active-owner guard blocked send" in (result.error or "")
    assert adapter.sent_messages == []
