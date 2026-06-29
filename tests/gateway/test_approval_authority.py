from types import SimpleNamespace

from gateway.approval_authority import (
    format_gateway_approval_authority_block,
    gateway_approval_authority_decision,
)


def _source(user_id="u1", user_name="Tester", user_id_alt=None):
    return SimpleNamespace(
        user_id=user_id,
        user_name=user_name,
        user_id_alt=user_id_alt,
    )


def test_gateway_approval_authority_unrestricted_without_allowlist():
    decision = gateway_approval_authority_decision(
        {"approvals": {}},
        _source(user_id="reporter", user_name="Plamena"),
    )

    assert decision.restricted is False
    assert decision.allowed is True


def test_gateway_approval_authority_allows_configured_user_id():
    decision = gateway_approval_authority_decision(
        {
            "approvals": {
                "gateway_authorized_user_ids": ["1279454038731264061"],
                "gateway_authorized_labels": ["Емил"],
            }
        },
        _source(user_id="1279454038731264061", user_name="Emil"),
    )

    assert decision.restricted is True
    assert decision.allowed is True


def test_gateway_approval_authority_allows_configured_display_name():
    decision = gateway_approval_authority_decision(
        {
            "approvals": {
                "gateway_authorized_user_names": ["Алекс", "Alex"],
            }
        },
        _source(user_id="unknown-id", user_name="alex"),
    )

    assert decision.restricted is True
    assert decision.allowed is True


def test_gateway_approval_authority_blocks_reporter_and_hides_command():
    decision = gateway_approval_authority_decision(
        {
            "approvals": {
                "gateway_authorized_user_ids": ["1279454038731264061"],
                "gateway_authorized_labels": ["Емил", "Алекс"],
            }
        },
        _source(user_id="1282940574533423125", user_name="Plamena"),
    )

    assert decision.restricted is True
    assert decision.allowed is False
    assert decision.reason == "source_not_in_gateway_approval_authority_allowlist"

    message = format_gateway_approval_authority_block(decision)
    assert "Командата не е изпълнена" in message
    assert "Емил, Алекс" in message
    assert "rm -rf" not in message
    assert "```" not in message
