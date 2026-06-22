"""Support Ops teammate routing guards for Discord sends.

This module is intentionally small and deterministic: it does not call Discord,
read secrets, or mutate config.  It resolves well-known internal Support Ops
routing phrases to exact Discord mentions and blocks unsafe teammate handles
before they can be sent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

UNKNOWN_USER_RE = re.compile(r"(?<![\w-])@unknown-user\b", re.IGNORECASE)
DISCORD_MENTION_RE = re.compile(r"<@!?(\d+)>")

KOZHUHAROV_MENTION = "<@1504852485083496561>"
BACKEND_MENTION = "<@1504852408227069993>"
FATIH_MENTION = "<@1504852444407140402>"

KNOWN_ROUTE_MENTIONS = {
    "devops_kozhuharov": KOZHUHAROV_MENTION,
    "backend_alex_ivcho": BACKEND_MENTION,
    "frontend_fatih": FATIH_MENTION,
}


@dataclass(frozen=True)
class TeammateRoute:
    lane: str
    mention: str
    reason: str


@dataclass(frozen=True)
class MentionLintResult:
    ok: bool
    content: str
    route: Optional[TeammateRoute] = None
    blocked_reason: Optional[str] = None


def _lower(text: str) -> str:
    return (text or "").casefold()


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = _lower(text)
    return any(needle.casefold() in lowered for needle in needles)


def _has_noncanonical_support_ops_handle(text: str) -> bool:
    lowered = _lower(text)
    if re.search(r"(?<!\w)иво(?!\w)", lowered):
        return True
    return _has_any(
        text,
        (
            "пламена",
            "plamena",
            "пламенна",
        ),
    )


def _mentions(text: str) -> set[str]:
    return {f"<@{match}>" for match in DISCORD_MENTION_RE.findall(text or "")}


def _looks_like_colleague_dm_request(text: str) -> bool:
    lowered = _lower(text)
    return bool(
        re.search(r"\bdm\b", lowered)
        or "директ" in lowered
        or "лично" in lowered
        or "на лично" in lowered
    )


def resolve_teammate_route(text: str) -> Optional[TeammateRoute]:
    """Resolve approved Support Ops teammate lane from names + topic context.

    Exact routing requires BOTH a teammate/lane alias and domain keywords so a
    casual mention of a colleague does not get auto-pinged.
    """

    if not text:
        return None

    kozhuharov_alias = _has_any(
        text,
        (
            "кожухаров",
            "емо к",
            "емо кожухаров",
            "emo k",
            "emo kozhuharov",
            "kozhuharov",
        ),
    )
    pbx_context = _has_any(
        text,
        (
            "pbx",
            "sip",
            "централ",
            "ip",
            "firewall",
            "network",
            "мреж",
            "37.63.76.203",
        ),
    )
    if kozhuharov_alias and pbx_context:
        return TeammateRoute(
            lane="devops_kozhuharov",
            mention=KOZHUHAROV_MENTION,
            reason="Кожухаров/PBX-SIP-network context resolved to approved DevOps lane",
        )

    backend_alias = _has_any(
        text,
        (
            "алекс",
            "ивчо",
            "alex",
            "ivcho",
        ),
    )
    backend_context = _has_any(
        text,
        (
            "voucher",
            "ваучер",
            "reservation",
            "резервац",
            "booking",
            "backend",
            "api",
            "automation",
            "автоматич",
            "vs941215",
        ),
    )
    if backend_alias and backend_context:
        return TeammateRoute(
            lane="backend_alex_ivcho",
            mention=BACKEND_MENTION,
            reason="Алекс/Ивчо voucher-reservation/backend context resolved to approved backend lane",
        )

    fatih_alias = _has_any(
        text,
        (
            "фатих",
            "fatih",
        ),
    )
    frontend_context = _has_any(
        text,
        (
            "frontend",
            "front-end",
            "front end",
            "fe",
            "ui",
            "интерфейс",
            "визуал",
        ),
    )
    if fatih_alias and frontend_context:
        return TeammateRoute(
            lane="frontend_fatih",
            mention=FATIH_MENTION,
            reason="Фатих/frontend context resolved to approved frontend lane",
        )

    return None


def lint_and_resolve_discord_content(
    content: str,
    *,
    owner_dm_approved: bool = False,
) -> MentionLintResult:
    """Resolve known internal routes and fail-closed on unsafe handles.

    ``@unknown-user`` is never sendable. Known routes get their exact mention
    inserted if missing. Wrong-lane mentions and colleague DM requests without
    an explicit owner approval are blocked before send.
    """

    text = str(content or "")

    if _has_noncanonical_support_ops_handle(text):
        return MentionLintResult(
            ok=False,
            content=text,
            blocked_reason="blocked_noncanonical_support_ops_handle",
        )

    route = resolve_teammate_route(text)
    if route:
        if _looks_like_colleague_dm_request(text) and not owner_dm_approved:
            return MentionLintResult(
                ok=False,
                content=text,
                route=route,
                blocked_reason="blocked_colleague_dm_without_exact_owner_approval",
            )

        text_mentions = _mentions(text)
        wrong_mentions = text_mentions - {route.mention}
        known_wrong_mentions = wrong_mentions.intersection(set(KNOWN_ROUTE_MENTIONS.values()))
        if known_wrong_mentions:
            return MentionLintResult(
                ok=False,
                content=text,
                route=route,
                blocked_reason="blocked_wrong_support_ops_lane_mention",
            )

        if UNKNOWN_USER_RE.search(text):
            text = UNKNOWN_USER_RE.sub(route.mention, text)
        elif route.mention not in text_mentions:
            text = f"{text.rstrip()} {route.mention}"

    if UNKNOWN_USER_RE.search(text):
        return MentionLintResult(
            ok=False,
            content=text,
            route=route,
            blocked_reason="blocked_unresolved_unknown_user_placeholder",
        )

    return MentionLintResult(ok=True, content=text, route=route)


def classify_support_ops_case_signal(text: str) -> Optional[str]:
    """Return a compact internal case signal for public-safe audit payloads."""

    lowered = _lower(text)
    closure_markers = (
        "централата вече работи",
        "случаят е готов",
        "case is ready",
        "case closed",
        "resolved",
    )
    if any(marker in lowered for marker in closure_markers):
        return "case_closure"
    return None
