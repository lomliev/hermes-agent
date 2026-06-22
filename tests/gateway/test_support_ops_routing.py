import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gateway.canonical_brain_audit import CanonicalBrainAuditBridge, CanonicalBrainAuditConfig
from gateway.config import Platform
from gateway.run import _prepare_gateway_status_message, _send_or_update_status_coro
from gateway.session import SessionSource
from gateway.support_ops_routing import (
    BACKEND_MENTION,
    FATIH_MENTION,
    KOZHUHAROV_MENTION,
    classify_support_ops_case_signal,
    lint_and_resolve_discord_content,
    resolve_teammate_route,
)


async def _noop_send_message(*args, **kwargs):
    return SimpleNamespace(success=True, message_id="safe-message")


def test_kozhuharov_pbx_unknown_user_resolves_to_exact_devops_mention():
    text = "PBX/SIP outage SIP1/SIP2, ново IP 37.63.76.203 — да пишем на Емо Кожухаров @unknown-user"

    result = lint_and_resolve_discord_content(text)

    assert result.ok is True
    assert result.route is not None
    assert result.route.lane == "devops_kozhuharov"
    assert KOZHUHAROV_MENTION in result.content
    assert BACKEND_MENTION not in result.content
    assert "@unknown-user" not in result.content


def test_alex_ivcho_voucher_unknown_user_resolves_to_exact_backend_mention():
    text = "Voucher VS941215 / автоматична резервация не е сработила — Алекс/Ивчо @unknown-user"

    result = lint_and_resolve_discord_content(text)

    assert result.ok is True
    assert result.route is not None
    assert result.route.lane == "backend_alex_ivcho"
    assert BACKEND_MENTION in result.content
    assert KOZHUHAROV_MENTION not in result.content
    assert "@unknown-user" not in result.content


def test_fatih_frontend_unknown_user_resolves_to_exact_frontend_mention():
    result = lint_and_resolve_discord_content("Фатих frontend regression @unknown-user")

    assert result.ok is True
    assert result.route is not None
    assert result.route.lane == "frontend_fatih"
    assert FATIH_MENTION in result.content
    assert "@unknown-user" not in result.content


def test_unknown_user_without_exact_route_fails_closed():
    result = lint_and_resolve_discord_content("моля @unknown-user да погледне")

    assert result.ok is False
    assert result.blocked_reason == "blocked_unresolved_unknown_user_placeholder"


def test_wrong_canonical_handles_fail_closed_before_send():
    for text in (
        "пиши на Иво за voucher/reservation @unknown-user",
        "Plamena asked to route this support case",
        "Пламена поиска да пишем на Кожухаров за SIP",
    ):
        result = lint_and_resolve_discord_content(text)
        assert result.ok is False
        assert result.blocked_reason == "blocked_noncanonical_support_ops_handle"


def test_known_route_forces_exact_mention_when_missing():
    result = lint_and_resolve_discord_content("Кожухаров SIP incident, моля да се погледне")

    assert result.ok is True
    assert result.route is not None
    assert result.route.lane == "devops_kozhuharov"
    assert KOZHUHAROV_MENTION in result.content


def test_wrong_lane_mention_fails_closed():
    result = lint_and_resolve_discord_content(f"Кожухаров SIP incident {BACKEND_MENTION}")

    assert result.ok is False
    assert result.blocked_reason == "blocked_wrong_support_ops_lane_mention"


def test_colleague_dm_without_exact_owner_approval_fails_closed():
    result = lint_and_resolve_discord_content(f"DM Кожухаров за SIP incident {KOZHUHAROV_MENTION}")

    assert result.ok is False
    assert result.blocked_reason == "blocked_colleague_dm_without_exact_owner_approval"


def test_colleague_dm_with_exact_owner_approval_passes():
    result = lint_and_resolve_discord_content(
        f"DM Кожухаров за SIP incident {KOZHUHAROV_MENTION}",
        owner_dm_approved=True,
    )

    assert result.ok is True


def test_route_requires_name_and_domain_context():
    assert resolve_teammate_route("Кожухаров FYI") is None
    assert resolve_teammate_route("има SIP проблем, но няма зададен teammate") is None


def test_discord_internal_codex_runtime_notice_is_suppressed():
    assert _prepare_gateway_status_message(
        Platform.DISCORD,
        "compression",
        "Runtime Codex GPT-5.5 compression notice: compacting context — summarizing earlier conversation",
    ) is None


def test_discord_status_send_path_suppresses_codex_runtime_notice():
    adapter = SimpleNamespace(send=AsyncMock(side_effect=_noop_send_message))

    result = asyncio.run(
        _send_or_update_status_coro(
            adapter,
            "channel-safe",
            "compression",
            "Codex GPT-5.5 runtime compression notice: compacting context — summarizing earlier conversation",
            {"thread_id": "thread-safe", "nonconversational": True},
        )
    )

    assert result is None
    adapter.send.assert_not_awaited()


def test_case_closure_phrases_classified():
    assert classify_support_ops_case_signal("Централата вече работи") == "case_closure"
    assert classify_support_ops_case_signal("случаят е готов") == "case_closure"


def test_canonical_audit_records_case_closure_signal(tmp_path):
    bridge = CanonicalBrainAuditBridge(
        CanonicalBrainAuditConfig(enabled=True, jsonl_path=tmp_path / "audit.jsonl")
    )
    source = SessionSource(
        platform=Platform.DISCORD,
        chat_id="channel-safe",
        user_id="operator-safe",
        user_name="operator",
        chat_type="group",
    )
    event = SimpleNamespace(
        text="Централата вече работи / случаят е готов",
        source=source,
        message_id="msg-safe",
        message_type="text",
        media_urls=[],
    )

    asyncio.run(bridge.record_inbound(event, "session-safe"))

    line = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert '"support_ops_case_signal":"case_closure"' in line
    assert "Централата" not in line
