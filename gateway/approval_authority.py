"""Gateway dangerous-command approval authority helpers.

The upstream gateway approval flow asks the user in the same conversation that
triggered the tool call.  That is correct for personal bots, but team
operations often have reporters who should not be asked to approve shell/code
execution.  This module keeps that policy config-driven so Hermes core does not
learn organization-specific names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ApprovalAuthorityDecision:
    restricted: bool
    allowed: bool
    reason: str = ""
    authorized_labels: tuple[str, ...] = ()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, Iterable):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _casefold_set(values: Iterable[str]) -> set[str]:
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def gateway_approval_authority_decision(
    config: dict[str, Any] | None,
    source: Any,
) -> ApprovalAuthorityDecision:
    """Return whether *source* may receive gateway command approvals.

    Config keys under ``approvals``:
      - ``gateway_authorized_user_ids``: exact platform user IDs.
      - ``gateway_authorized_user_names``: fallback display/user names.
      - ``gateway_authorized_labels``: human-readable labels for block text.

    If both allowlists are empty, the gateway keeps the upstream behavior and
    prompts the current conversation.
    """

    approvals = (config or {}).get("approvals") or {}
    if not isinstance(approvals, dict):
        approvals = {}

    user_ids = set(_as_list(approvals.get("gateway_authorized_user_ids")))
    user_names = _casefold_set(approvals.get("gateway_authorized_user_names") or [])
    labels = tuple(_as_list(approvals.get("gateway_authorized_labels")))

    if not user_ids and not user_names:
        return ApprovalAuthorityDecision(restricted=False, allowed=True)

    source_ids = {
        str(getattr(source, "user_id", "") or "").strip(),
        str(getattr(source, "user_id_alt", "") or "").strip(),
    }
    source_ids.discard("")
    source_names = _casefold_set(
        [
            str(getattr(source, "user_name", "") or ""),
            str(getattr(source, "chat_name", "") or ""),
        ]
    )

    if source_ids & user_ids:
        return ApprovalAuthorityDecision(
            restricted=True,
            allowed=True,
            authorized_labels=labels,
        )
    if source_names & user_names:
        return ApprovalAuthorityDecision(
            restricted=True,
            allowed=True,
            authorized_labels=labels,
        )

    return ApprovalAuthorityDecision(
        restricted=True,
        allowed=False,
        reason="source_not_in_gateway_approval_authority_allowlist",
        authorized_labels=labels,
    )


def format_gateway_approval_authority_block(decision: ApprovalAuthorityDecision) -> str:
    """User-facing block text for non-authorized approval recipients."""

    if decision.authorized_labels:
        labels = ", ".join(decision.authorized_labels)
        authority_text = f"Одобрение може да даде само: {labels}."
    else:
        authority_text = "Одобрение може да даде само упълномощен operator."
    return (
        "⚠️ Тази стъпка изисква command approval, но този канал/потребител "
        "не е в списъка с хора, които могат да одобряват команди. "
        "Командата не е изпълнена и няма да показвам approval prompt тук. "
        f"{authority_text}"
    )
