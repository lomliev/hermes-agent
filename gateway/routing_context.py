"""Route-back context for cross-chat handoffs.

When the agent sends a request from one chat to another, the destination
answer may arrive in a different gateway session.  This module records the
outbound bot message ID so replies to it can carry a return target back to the
model.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from hermes_cli.config import get_hermes_home
from utils import atomic_json_write

logger = logging.getLogger(__name__)

_STATE_PATH = get_hermes_home() / "gateway" / "routing_context.json"
_LOCK = threading.Lock()
_MAX_ROUTES = 500
_TTL_SECONDS = 14 * 24 * 60 * 60


def format_target(platform: str, chat_id: str, thread_id: str | None = None) -> str | None:
    """Return a send_message target for a platform chat/thread."""
    platform = (platform or "").strip().lower()
    chat_id = str(chat_id or "").strip()
    thread_id = str(thread_id or "").strip()
    if not platform or not chat_id:
        return None
    if thread_id and thread_id != chat_id:
        return f"{platform}:{chat_id}:{thread_id}"
    return f"{platform}:{chat_id}"


def record_outbound_route(
    *,
    platform: str,
    chat_id: str,
    message_id: str,
    return_target: str,
    return_label: str = "",
    return_user: str = "",
    original_message: str = "",
    thread_id: str | None = None,
) -> bool:
    """Record where a reply to an outbound handoff should be returned."""
    platform = (platform or "").strip().lower()
    chat_id = str(chat_id or "").strip()
    message_id = str(message_id or "").strip()
    return_target = str(return_target or "").strip()
    if not platform or not chat_id or not message_id or not return_target:
        return False

    route = {
        "platform": platform,
        "chat_id": chat_id,
        "thread_id": str(thread_id or "").strip(),
        "message_id": message_id,
        "return_target": return_target,
        "return_label": str(return_label or "").strip(),
        "return_user": str(return_user or "").strip(),
        "original_message": str(original_message or "").strip()[:2000],
        "created_at": time.time(),
    }

    try:
        with _LOCK:
            data = _load_state_unlocked()
            routes = data.setdefault("routes", {})
            routes[_route_key(platform, chat_id, message_id)] = route
            _prune_routes_unlocked(routes)
            atomic_json_write(_STATE_PATH, data, indent=2)
        return True
    except Exception as exc:
        logger.debug("Failed to record route context: %s", exc, exc_info=True)
        return False


def lookup_outbound_route(
    *,
    platform: str,
    chat_id: str,
    message_id: str,
) -> dict[str, Any] | None:
    """Find route-back context for a reply to a previously sent message."""
    platform = (platform or "").strip().lower()
    chat_id = str(chat_id or "").strip()
    message_id = str(message_id or "").strip()
    if not platform or not chat_id or not message_id:
        return None

    try:
        with _LOCK:
            data = _load_state_unlocked()
            routes = data.get("routes") or {}
            route = routes.get(_route_key(platform, chat_id, message_id))
            if not isinstance(route, dict):
                return None
            created_at = float(route.get("created_at") or 0)
            if created_at and time.time() - created_at > _TTL_SECONDS:
                return None
            return dict(route)
    except Exception as exc:
        logger.debug("Failed to look up route context: %s", exc, exc_info=True)
        return None


def format_route_context_note(route: dict[str, Any] | None) -> str | None:
    """Render route context as a compact agent-visible instruction."""
    if not route:
        return None
    return_target = str(route.get("return_target") or "").strip()
    if not return_target:
        return None

    label = str(route.get("return_label") or "").strip()
    user = str(route.get("return_user") or "").strip()
    source_bits = []
    if user:
        source_bits.append(user)
    if label and label != user:
        source_bits.append(label)
    source = " / ".join(source_bits) if source_bits else return_target

    return (
        "[Route-back context: this message is responding to a request routed "
        f"from {source}. Return target: `{return_target}`. If the reply contains "
        "an answer, fix, decision, or status update, send a concise update back "
        "to that return target with send_message; do not assume the requester "
        "can see this channel.]"
    )


def _route_key(platform: str, chat_id: str, message_id: str) -> str:
    return f"{platform}:{chat_id}:{message_id}"


def _load_state_unlocked() -> dict[str, Any]:
    if not _STATE_PATH.exists():
        return {"version": 1, "routes": {}}
    try:
        with open(_STATE_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {"version": 1, "routes": {}}
    if not isinstance(data, dict):
        return {"version": 1, "routes": {}}
    if not isinstance(data.get("routes"), dict):
        data["routes"] = {}
    data.setdefault("version", 1)
    return data


def _prune_routes_unlocked(routes: dict[str, Any]) -> None:
    now = time.time()
    expired = [
        key for key, route in routes.items()
        if not isinstance(route, dict)
        or now - float(route.get("created_at") or 0) > _TTL_SECONDS
    ]
    for key in expired:
        routes.pop(key, None)

    if len(routes) <= _MAX_ROUTES:
        return
    ordered = sorted(
        routes.items(),
        key=lambda item: float((item[1] or {}).get("created_at") or 0),
    )
    for key, _route in ordered[: max(0, len(routes) - _MAX_ROUTES)]:
        routes.pop(key, None)
