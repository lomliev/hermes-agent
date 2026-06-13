"""Send Message Tool -- cross-channel messaging via platform APIs.

Sends a message to a user or channel on any connected messaging platform
(Telegram, Discord, Slack). Supports listing available targets and resolving
human-friendly channel names to IDs. Works in both CLI and gateway contexts.
"""

import asyncio
import json
import logging
import os
import re
import ssl
import time
from email.utils import formatdate
from pathlib import Path
from typing import Any, Dict, Optional

from agent.redact import redact_sensitive_text

logger = logging.getLogger(__name__)

_TELEGRAM_TOPIC_TARGET_RE = re.compile(r"^\s*(-?\d+)(?::(\d+))?\s*$")
_FEISHU_TARGET_RE = re.compile(r"^\s*((?:oc|ou|on|chat|open)_[-A-Za-z0-9]+)(?::([-A-Za-z0-9_]+))?\s*$")
# Slack conversation IDs: C (public channel), G (private/group channel), D (DM).
# Must be uppercase alphanumeric, 9+ chars. User IDs (U...) and workspace IDs
# (W...) are NOT valid chat.postMessage channel values — posting to them fails
# because the API requires a conversation ID. To DM a user you must first call
# conversations.open to obtain a D... ID. Without this gate, Slack IDs fall
# through to channel-name resolution, which only matches by name and fails.
_SLACK_TARGET_RE = re.compile(r"^\s*([CGDU][A-Z0-9]{8,})\s*$")
# Session-derived Slack thread targets use "<conversation_id>:<thread_ts>".
_SLACK_THREAD_TARGET_RE = re.compile(r"^\s*([CGD][A-Z0-9]{8,}):([^\s:]+)\s*$")
_WEIXIN_TARGET_RE = re.compile(r"^\s*((?:wxid|gh|v\d+|wm|wb)_[A-Za-z0-9_-]+|[A-Za-z0-9._-]+@chatroom|filehelper)\s*$")
_YUANBAO_TARGET_RE = re.compile(r"^\s*((?:group|direct):[^:]+)\s*$")
# Discord snowflake IDs are numeric, same regex pattern as Telegram topic targets.
_NUMERIC_TOPIC_RE = _TELEGRAM_TOPIC_TARGET_RE
# Platforms that address recipients by phone number and accept E.164 format
# (with a leading '+'). Without this, "+15551234567" fails the isdigit() check
# below and falls through to channel-name resolution, which has no way to
# resolve a raw phone number. Keeping the '+' preserves the E.164 form that
# downstream adapters (signal, etc.) expect.
_PHONE_PLATFORMS = frozenset({"signal", "sms", "whatsapp"})
_E164_TARGET_RE = re.compile(r"^\s*\+(\d{7,15})\s*$")
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".3gp"}
_AUDIO_EXTS = {".ogg", ".opus", ".mp3", ".wav", ".m4a", ".flac"}
_VOICE_EXTS = {".ogg", ".opus"}
# Telegram's Bot API sendAudio only accepts MP3 / M4A. Other audio
# formats either route through sendVoice (Opus/OGG) or fall back to
# document delivery.
_TELEGRAM_SEND_AUDIO_EXTS = {".mp3", ".m4a"}
_URL_SECRET_QUERY_RE = re.compile(
    r"([?&](?:access_token|api[_-]?key|auth[_-]?token|token|signature|sig)=)([^&#\s]+)",
    re.IGNORECASE,
)
_GENERIC_SECRET_ASSIGN_RE = re.compile(
    r"\b(access_token|api[_-]?key|auth[_-]?token|signature|sig)\s*=\s*([^\s,;]+)",
    re.IGNORECASE,
)


def _sanitize_error_text(text) -> str:
    """Redact secrets from error text before surfacing it to users/models."""
    redacted = redact_sensitive_text(text)
    redacted = _URL_SECRET_QUERY_RE.sub(lambda m: f"{m.group(1)}***", redacted)
    redacted = _GENERIC_SECRET_ASSIGN_RE.sub(lambda m: f"{m.group(1)}=***", redacted)
    return redacted


def _error(message: str) -> dict:
    """Build a standardized error payload with redacted content."""
    return {"error": _sanitize_error_text(message)}


def _telegram_retry_delay(exc: Exception, attempt: int) -> float | None:
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        try:
            return max(float(retry_after), 0.0)
        except (TypeError, ValueError):
            return 1.0

    text = str(exc).lower()
    if "timed out" in text or "timeout" in text:
        return None
    if (
        "bad gateway" in text
        or "502" in text
        or "too many requests" in text
        or "429" in text
        or "service unavailable" in text
        or "503" in text
        or "gateway timeout" in text
        or "504" in text
    ):
        return float(2 ** attempt)
    return None


async def _send_telegram_message_with_retry(bot, *, attempts: int = 3, **kwargs):
    for attempt in range(attempts):
        try:
            return await bot.send_message(**kwargs)
        except Exception as exc:
            delay = _telegram_retry_delay(exc, attempt)
            if delay is None or attempt >= attempts - 1:
                raise
            logger.warning(
                "Transient Telegram send failure (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                attempts,
                delay,
                _sanitize_error_text(exc),
            )
            await asyncio.sleep(delay)


SEND_MESSAGE_SCHEMA = {
    "name": "send_message",
    "description": (
        "Send a message to a connected messaging platform, or list available targets.\n\n"
        "IMPORTANT: When the user asks to send to a specific channel or person "
        "(not just a bare platform name), call send_message(action='list') FIRST to see "
        "available targets, then send to the correct one.\n"
        "If the user just says a platform name like 'send to telegram', send directly "
        "to the home channel without listing first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["send", "list", "list_threads", "resolve_thread", "create_thread", "send_to_thread", "rename_thread_by_id", "read_channel_messages", "read_thread_messages", "list_category_channels", "rename_channel_by_id", "create_text_channel_in_category"],
                "description": "Action to perform. 'send' (default) sends a message. 'list' returns available targets. Discord-only bounded thread actions: 'list_threads', 'resolve_thread', 'create_thread', 'send_to_thread', 'rename_thread_by_id', 'read_channel_messages', 'read_thread_messages'. Discord-only bounded channel admin actions: 'list_category_channels', 'rename_channel_by_id', 'create_text_channel_in_category'."
            },
            "target": {
                "type": "string",
                "description": "Delivery target. Format: 'platform' (uses home channel), 'platform:#channel-name', 'platform:chat_id', or 'platform:chat_id:thread_id' for Telegram topics and Discord threads. Examples: 'telegram', 'telegram:-1001234567890:17585', 'discord:999888777:555444333', 'discord:#bot-home', 'slack:#engineering', 'signal:+155****4567', 'matrix:!roomid:server.org', 'matrix:@user:server.org', 'yuanbao:direct:<account_id>' (DM), 'yuanbao:group:<group_code>' (group chat)"
            },
            "message": {
                "type": "string",
                "description": "The message text to send. To send an image or file, include MEDIA:<local_path> (e.g. 'MEDIA:/tmp/hermes/cache/img_xxx.jpg') in the message — the platform will deliver it as a native media attachment. For Discord colleague notifications, use @Alex/@Алекс and @Ivo/@Иво; known aliases are converted to real Discord mentions."
            },
            "parent_channel": {
                "type": "string",
                "description": "Discord thread actions only: approved parent channel name/target/id (e.g. discord:#sky-next-backend-api-monolith or 1504852408227069993)."
            },
            "thread_id": {
                "type": "string",
                "description": "Discord send_to_thread/rename_thread_by_id/read_thread_messages only: Discord thread/channel ID."
            },
            "limit": {
                "type": "integer",
                "description": "Discord read_*_messages only: number of messages to fetch, 1-100 (default 50)."
            },
            "before_message_id": {
                "type": "string",
                "description": "Discord read_*_messages only: fetch messages before this message ID for pagination."
            },
            "after_message_id": {
                "type": "string",
                "description": "Discord read_*_messages only: fetch messages after this message ID."
            },
            "around_message_id": {
                "type": "string",
                "description": "Discord read_*_messages only: fetch messages around this message ID."
            },
            "parent_channel_id": {
                "type": "string",
                "description": "Discord rename_thread_by_id only: approved SkyVision Next parent channel ID."
            },
            "new_title": {
                "type": "string",
                "description": "Discord rename_thread_by_id only: replacement thread title, non-empty and within Discord title limits."
            },
            "title": {
                "type": "string",
                "description": "Discord create_thread/resolve_thread only: thread title."
            },
            "query": {
                "type": "string",
                "description": "Discord list_threads/resolve_thread only: incident ID, title fragment, or search query."
            },
            "starter_message": {
                "type": "string",
                "description": "Discord create_thread only: optional first message to post inside the created thread."
            },
            "category_id": {
                "type": "string",
                "description": "Discord bounded channel admin only: approved SkyVision Next category ID. Required for list_category_channels/create_text_channel_in_category."
            },
            "channel_id": {
                "type": "string",
                "description": "Discord bounded channel admin only: existing channel ID inside the approved SkyVision Next category. Required for rename_channel_by_id."
            },
            "new_name": {
                "type": "string",
                "description": "Discord bounded channel admin only: approved canonical replacement channel name for rename_channel_by_id."
            },
            "name": {
                "type": "string",
                "description": "Discord bounded channel admin only: approved text channel name for create_text_channel_in_category."
            }
        },
        "required": []
    }
}


def send_message_tool(args, **kw):
    """Handle cross-channel send_message tool calls."""
    action = args.get("action", "send")

    if action == "list":
        return _handle_list()

    if action in {"list_threads", "resolve_thread", "create_thread", "send_to_thread", "rename_thread_by_id", "read_channel_messages", "read_thread_messages"}:
        return _handle_discord_thread_action(args, action)

    if action in {"list_category_channels", "rename_channel_by_id", "create_text_channel_in_category"}:
        return _handle_discord_channel_admin_action(args, action)

    return _handle_send(args)


def _handle_list():
    """Return formatted list of available messaging targets."""
    try:
        from gateway.channel_directory import format_directory_for_display
        return json.dumps({"targets": format_directory_for_display()})
    except Exception as e:
        return json.dumps(_error(f"Failed to load channel directory: {e}"))


_DISCORD_SKYVISION_NEXT_CANONICAL_LANES = {
    "control-tower": "1504852355588423801",
    "backend": "1504852408227069993",
    "frontend": "1504852444407140402",
    "devops": "1504852485083496561",
    "booking-ops": "1504852553031221391",
    "business-accounting-legal": "1504852628373373028",
    "nasi-ai-ops": "1505499746939174993",
    "chatbot": "1507239516409167942",
    "marketing-growth": "1507239177350283274",
    "suppliers": "1507239385010016308",
    "chatbot-web-monitoring": "1510888721614901358",
}
_DISCORD_SKYVISION_NEXT_ALIAS_LANES = {
    "sky-next-control-tower": "1504852355588423801",
    "sky-next-backend-api-monolith": "1504852408227069993",
    "sky-next-frontend": "1504852444407140402",
    "sky-next-devops-gitlab-cloudflare": "1504852485083496561",
    "sky-next-booking-ops": "1504852553031221391",
    "sky-next-business-accounting-legal": "1504852628373373028",
    "sky-next-business-accounts": "1504852628373373028",
    "sky-next-nasi-ai-ops": "1505499746939174993",
    "chatbot-ops": "1507239516409167942",
    "skyvision-marketing": "1507239177350283274",
    "supplier-onboarding": "1507239385010016308",
    "suppliers-onboarding": "1507239385010016308",
    "skyvision-chatbot-monitoring": "1510888721614901358",
}
# Active bounded Discord thread lanes: final 10 SkyVision Next channels plus
# explicitly safe legacy aliases. Plain #marketing is intentionally excluded: it
# is an external/general channel and must not auto-route to #marketing-growth.
_DISCORD_APPROVED_THREAD_LANES = {
    **_DISCORD_SKYVISION_NEXT_CANONICAL_LANES,
    **_DISCORD_SKYVISION_NEXT_ALIAS_LANES,
}
_DISCORD_APPROVED_THREAD_IDS = frozenset(_DISCORD_SKYVISION_NEXT_CANONICAL_LANES.values())
_DISCORD_APPROVED_THREAD_RENAME_PARENT_IDS = _DISCORD_APPROVED_THREAD_IDS
_DISCORD_APPROVED_HISTORY_PARENT_IDS = _DISCORD_APPROVED_THREAD_IDS
_DISCORD_EXTERNAL_GENERAL_MARKETING_ID = "1282928816104276019"
_DISCORD_HISTORY_LIMIT_DEFAULT = 50
_DISCORD_HISTORY_LIMIT_MAX = 100
_DISCORD_THREAD_TITLE_MAX_LENGTH = 100
_DISCORD_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DISCORD_USER_MENTION_ALIASES = {
    "alex": "1282940511962791959",
    "aleks": "1282940511962791959",
    "алекс": "1282940511962791959",
    "ivo": "1283039346295050271",
    "ivo popov": "1283039346295050271",
    "иво": "1283039346295050271",
    "иво попов": "1283039346295050271",
    "ивчо": "1283039346295050271",
    "ivs": "1391703330711142472",
    "ivelina": "1391703330711142472",
    "ивс": "1391703330711142472",
    "ивелина": "1391703330711142472",
}


def _discord_alias_to_pattern(alias: str) -> str:
    """Build a regex fragment for an @alias, tolerating spaces in full names."""
    return r"\s+".join(re.escape(part) for part in alias.split())


def _discord_render_user_mentions(message: str) -> tuple[str, list[str]]:
    """Convert known Discord @name aliases to mention tokens and return ping IDs.

    Discord only notifies users for real mention tokens like ``<@123>``. Plain
    text such as ``@Alex`` looks mention-like to humans but does not ping. Keep
    the conversion deliberately small and explicit so arbitrary LLM text cannot
    become a broad notification surface.
    """
    rendered = str(message or "")
    user_ids: list[str] = []

    def remember(user_id: str) -> None:
        if user_id and user_id not in user_ids:
            user_ids.append(user_id)

    for user_id in re.findall(r"<@!?(\d{15,25})>", rendered):
        remember(user_id)

    sorted_aliases = sorted(
        _DISCORD_USER_MENTION_ALIASES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    def alias_replacer(match: re.Match[str]) -> str:
        prefix = match.group("prefix") or ""
        alias = re.sub(r"\s+", " ", match.group("alias")).casefold()
        user_id = _DISCORD_USER_MENTION_ALIASES.get(alias)
        if not user_id:
            return match.group(0)
        remember(user_id)
        return f"{prefix}<@{user_id}>"

    # Common handoff style: "Иво/Alex, моля..." at the start of a Discord
    # message. Treat only the opening addressee segment as notification intent;
    # bare names elsewhere remain plain text.
    leading_match = re.match(r"^([^\n,:\u2014-]{2,80})([,:\u2014-]\s+)", rendered)
    if leading_match:
        leading = leading_match.group(1)
        delimiter = leading_match.group(2)
        if re.search(r"\s*(?:/|,|&|\+|\bи\b|\band\b)\s*", leading, re.IGNORECASE):
            alias_names = "|".join(_discord_alias_to_pattern(alias) for alias, _uid in sorted_aliases)
            leading_pattern = re.compile(
                rf"(?P<prefix>^|[/,&+\s]+)(?P<alias>{alias_names})(?=$|[/,&+\s]+)",
                re.IGNORECASE,
            )
            converted = leading_pattern.sub(alias_replacer, leading)
            if converted != leading:
                rendered = converted + delimiter + rendered[leading_match.end():]

    for alias, user_id in sorted_aliases:
        pattern = re.compile(
            rf"(?<![\w<])@{_discord_alias_to_pattern(alias)}(?![\w-])",
            re.IGNORECASE,
        )

        def replace(match: re.Match[str], uid: str = user_id) -> str:
            remember(uid)
            return f"<@{uid}>"

        rendered = pattern.sub(replace, rendered)

    return rendered, user_ids


def _discord_message_payload(content: str, *, attachments: list[dict[str, str]] | None = None) -> dict[str, Any]:
    rendered, user_ids = _discord_render_user_mentions(content)
    allowed_mentions: dict[str, Any] = {"parse": []}
    if user_ids:
        allowed_mentions["users"] = user_ids
    payload: dict[str, Any] = {
        "content": rendered,
        "allowed_mentions": allowed_mentions,
    }
    if attachments is not None:
        payload["attachments"] = attachments
    return payload


_DISCORD_APPROVED_CHANNEL_RENAME_NAMES = frozenset({
    "control-tower",
    "backend",
    "frontend",
    "devops",
    "booking-ops",
    "business-accounting-legal",
    "nasi-ai-ops",
})
_DISCORD_APPROVED_CHANNEL_CREATE_NAMES = frozenset({"chatbot", "marketing-growth", "suppliers"})
_DISCORD_APPROVED_CHANNEL_ADMIN_NAMES = _DISCORD_APPROVED_CHANNEL_RENAME_NAMES | _DISCORD_APPROVED_CHANNEL_CREATE_NAMES
_DISCORD_CHANNEL_TYPE_GUILD_TEXT = 0
_DISCORD_CHANNEL_TYPE_GUILD_CATEGORY = 4


def _discord_admin_error(message: str) -> str:
    return json.dumps(_error(message))


def _normalize_discord_channel_name(value: str | None) -> str:
    return (value or "").strip().lstrip("#").lower()


def _get_approved_skyvision_next_category_id(pconfig) -> tuple[str | None, str | None]:
    """Read the single approved SkyVision Next category ID from config/env.

    The tool is intentionally fail-closed: without an explicit category ID it
    can neither list children nor mutate channels. This avoids exposing a
    generic Discord admin surface when local metadata lacks category context.
    """
    extra = getattr(pconfig, "extra", {}) or {}
    value = (
        extra.get("skyvision_next_category_id")
        or extra.get("skyvision_next_category")
        or os.getenv("DISCORD_SKYVISION_NEXT_CATEGORY_ID")
        or ""
    )
    value = str(value).strip()
    if not value:
        return None, "SkyVision Next category ID is not configured; set discord.skyvision_next_category_id or DISCORD_SKYVISION_NEXT_CATEGORY_ID before using bounded channel admin actions."
    if not value.isdigit():
        return None, "Configured SkyVision Next category ID is invalid."
    return value, None


def _require_approved_category_id(requested_category_id: str | None, approved_category_id: str) -> tuple[str | None, str | None]:
    requested = str(requested_category_id or approved_category_id or "").strip()
    if not requested:
        return None, "category_id is required for this bounded Discord channel admin action."
    if requested != approved_category_id:
        return None, "Discord channel admin action rejected: category outside approved SkyVision Next category."
    return requested, None


async def _discord_get_channel(token: str, channel_id: str) -> tuple[dict[str, Any] | None, str | None]:
    data, err = await _discord_api_request(token, "GET", f"/channels/{channel_id}")
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "Discord channel lookup returned unexpected response."
    return data, None


async def _discord_list_category_channels(token: str, category_id: str) -> tuple[list[dict[str, Any]], str | None]:
    category, err = await _discord_get_channel(token, category_id)
    if err:
        return [], err
    if category.get("type") != _DISCORD_CHANNEL_TYPE_GUILD_CATEGORY:
        return [], "Approved SkyVision Next category ID does not resolve to a Discord category."
    guild_id = str(category.get("guild_id") or "")
    if not guild_id:
        return [], "Discord category response did not include guild_id."
    data, err = await _discord_api_request(token, "GET", f"/guilds/{guild_id}/channels")
    if err:
        return [], err
    if not isinstance(data, list):
        return [], "Discord guild channel listing returned unexpected response."
    children = []
    for ch in data:
        if not isinstance(ch, dict):
            continue
        if str(ch.get("parent_id") or "") != category_id:
            continue
        children.append({
            "channel_id": str(ch.get("id") or ""),
            "name": str(ch.get("name") or ""),
            "type": ch.get("type"),
            "parent_id": str(ch.get("parent_id") or ""),
            "position": ch.get("position"),
        })
    children.sort(key=lambda item: (item.get("position") is None, item.get("position") or 0, item.get("name") or ""))
    return children, None


def _validate_channel_admin_name(name: str | None, *, for_create: bool) -> tuple[str | None, str | None]:
    normalized = _normalize_discord_channel_name(name)
    if not normalized:
        return None, "name/new_name is required for this bounded Discord channel admin action."
    allowed = _DISCORD_APPROVED_CHANNEL_CREATE_NAMES if for_create else _DISCORD_APPROVED_CHANNEL_RENAME_NAMES
    if normalized not in allowed:
        allowed_text = ", ".join(f"#{item}" for item in sorted(allowed))
        return None, f"Discord channel admin action rejected: channel name is outside approved SkyVision Next lane names ({allowed_text})."
    return normalized, None


def _validate_channel_in_approved_category(channel: dict[str, Any], approved_category_id: str) -> str | None:
    if str(channel.get("parent_id") or "") != approved_category_id:
        return "Discord channel admin action rejected: channel ID is outside approved SkyVision Next category."
    if channel.get("type") != _DISCORD_CHANNEL_TYPE_GUILD_TEXT:
        return "Discord channel admin action rejected: only text channels inside SkyVision Next category are allowed."
    return None


def _handle_discord_channel_admin_action(args: dict[str, Any], action: str) -> str:
    """Bounded SkyVision Next Discord channel admin tooling.

    Exposes only three tightly-scoped actions and performs live category/channel
    validation before any mutation. No delete, permission, role, message, thread,
    webhook, or broad guild admin operations are reachable through this path.
    """
    pconfig, cfg_error = _get_discord_platform_config()
    if cfg_error:
        return _discord_admin_error(cfg_error)
    token = pconfig.token
    approved_category_id, category_error = _get_approved_skyvision_next_category_id(pconfig)
    if category_error:
        return _discord_admin_error(category_error)
    category_id, category_error = _require_approved_category_id(args.get("category_id"), approved_category_id)
    if category_error:
        return _discord_admin_error(category_error)

    from model_tools import _run_async

    try:
        if action == "list_category_channels":
            channels, err = _run_async(_discord_list_category_channels(token, category_id))
            if err:
                return _discord_admin_error(err)
            return json.dumps({"success": True, "platform": "discord", "category_id": category_id, "channels": channels, "count": len(channels)})

        if action == "rename_channel_by_id":
            channel_id = str(args.get("channel_id") or "").strip()
            if not channel_id:
                return _discord_admin_error("channel_id is required for rename_channel_by_id.")
            new_name, name_error = _validate_channel_admin_name(args.get("new_name") or args.get("name"), for_create=False)
            if name_error:
                return _discord_admin_error(name_error)
            channel, err = _run_async(_discord_get_channel(token, channel_id))
            if err:
                return _discord_admin_error(err)
            validation_error = _validate_channel_in_approved_category(channel, category_id)
            if validation_error:
                return _discord_admin_error(validation_error)
            updated, err = _run_async(_discord_api_request(token, "PATCH", f"/channels/{channel_id}", json_body={"name": new_name}))
            if err:
                return _discord_admin_error(err)
            if not isinstance(updated, dict):
                return _discord_admin_error("Discord channel rename returned unexpected response.")
            return json.dumps({
                "success": True,
                "platform": "discord",
                "action": action,
                "category_id": category_id,
                "channel_id": str(updated.get("id") or channel_id),
                "old_name": str(channel.get("name") or ""),
                "new_name": str(updated.get("name") or new_name),
            })

        if action == "create_text_channel_in_category":
            name, name_error = _validate_channel_admin_name(args.get("name") or args.get("new_name"), for_create=True)
            if name_error:
                return _discord_admin_error(name_error)
            category, err = _run_async(_discord_get_channel(token, category_id))
            if err:
                return _discord_admin_error(err)
            if not isinstance(category, dict) or category.get("type") != _DISCORD_CHANNEL_TYPE_GUILD_CATEGORY:
                return _discord_admin_error("Approved SkyVision Next category ID does not resolve to a Discord category.")
            guild_id = str(category.get("guild_id") or "")
            if not guild_id:
                return _discord_admin_error("Discord category response did not include guild_id.")
            existing, err = _run_async(_discord_list_category_channels(token, category_id))
            if err:
                return _discord_admin_error(err)
            for ch in existing:
                if _normalize_discord_channel_name(ch.get("name")) == name:
                    return json.dumps({
                        "success": True,
                        "platform": "discord",
                        "action": action,
                        "category_id": category_id,
                        "channel_id": ch.get("channel_id"),
                        "name": name,
                        "existed": True,
                        "note": "Exact channel already exists in approved category; no duplicate channel created.",
                    })
            body = {"name": name, "type": _DISCORD_CHANNEL_TYPE_GUILD_TEXT, "parent_id": category_id}
            created, err = _run_async(_discord_api_request(token, "POST", f"/guilds/{guild_id}/channels", json_body=body))
            if err:
                return _discord_admin_error(err)
            if not isinstance(created, dict) or not created.get("id"):
                return _discord_admin_error("Discord channel creation returned unexpected response.")
            if str(created.get("parent_id") or "") != category_id or created.get("type") != _DISCORD_CHANNEL_TYPE_GUILD_TEXT:
                return _discord_admin_error("Discord channel creation returned a channel outside the approved category/text-channel scope.")
            return json.dumps({
                "success": True,
                "platform": "discord",
                "action": action,
                "category_id": category_id,
                "channel_id": str(created.get("id")),
                "name": str(created.get("name") or name),
                "existed": False,
            })
    except Exception as exc:
        return _discord_admin_error(f"Discord bounded channel admin action failed: {exc}")

    return _discord_admin_error(f"Unsupported Discord bounded channel admin action: {action}")


def _discord_thread_error(message: str) -> str:
    return json.dumps(_error(message))


def _get_discord_platform_config():
    """Return the configured Discord PlatformConfig without exposing secrets."""
    try:
        from gateway.config import Platform, load_gateway_config
        config = load_gateway_config()
        pconfig = config.platforms.get(Platform.DISCORD)
    except Exception as exc:
        return None, f"Failed to load gateway config: {exc}"
    if not pconfig or not getattr(pconfig, "enabled", False):
        return None, "Discord platform is not enabled in the active gateway config."
    if not (getattr(pconfig, "token", "") or "").strip():
        return None, "Discord bot token is not available in this runtime."
    return pconfig, None


def _resolve_approved_discord_parent_channel(raw: str | None) -> tuple[str | None, str | None]:
    """Resolve a parent channel input and enforce SkyVision-approved lanes only."""
    value = (raw or "").strip()
    if not value:
        return None, "parent_channel or target is required for this Discord thread action."
    if value.startswith("discord:"):
        value = value.split(":", 1)[1].strip()
    if value == _DISCORD_EXTERNAL_GENERAL_MARKETING_ID:
        return None, "#marketing is external/general and unmanaged; use #marketing-growth only for explicit SkyVision Next marketing lane context."
    if value in _DISCORD_APPROVED_THREAD_IDS:
        return value, None
    name = value.lstrip("#").strip().lower()
    if name == "marketing":
        return None, "Ambiguous #marketing is external/general and unmanaged; use #marketing-growth for the SkyVision Next marketing lane."
    if name in _DISCORD_APPROVED_THREAD_LANES:
        return _DISCORD_APPROVED_THREAD_LANES[name], None
    try:
        from gateway.channel_directory import resolve_channel_name
        resolved = resolve_channel_name("discord", value)
        if resolved:
            channel_id, _thread_id, explicit = _parse_target_ref("discord", resolved)
            if channel_id == _DISCORD_EXTERNAL_GENERAL_MARKETING_ID:
                return None, "#marketing is external/general and unmanaged; use #marketing-growth only for explicit SkyVision Next marketing lane context."
            if explicit and channel_id in _DISCORD_APPROVED_THREAD_IDS:
                return channel_id, None
    except Exception:
        pass
    allowed = ", ".join(f"#{name}" for name in sorted(_DISCORD_APPROVED_THREAD_LANES))
    return None, f"Discord thread tooling is limited to approved internal lanes only: {allowed}."

def _validate_discord_snowflake(value: str | None, field_name: str) -> tuple[str | None, str | None]:
    snowflake = str(value or "").strip()
    if not snowflake:
        return None, f"{field_name} is required for rename_thread_by_id."
    if not snowflake.isdigit():
        return None, f"{field_name} must be a numeric Discord snowflake."
    return snowflake, None


def _validate_thread_rename_parent_id(value: str | None) -> tuple[str | None, str | None]:
    parent_id, error = _validate_discord_snowflake(value, "parent_channel_id")
    if error:
        return None, error
    if parent_id not in _DISCORD_APPROVED_THREAD_RENAME_PARENT_IDS:
        allowed = ", ".join(sorted(_DISCORD_APPROVED_THREAD_RENAME_PARENT_IDS))
        return None, f"Discord thread rename rejected: parent_channel_id must be an approved SkyVision Next lane ({allowed})."
    return parent_id, None


def _validate_discord_history_limit(value: Any) -> tuple[int | None, str | None]:
    if value in (None, ""):
        return _DISCORD_HISTORY_LIMIT_DEFAULT, None
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return None, "limit must be an integer between 1 and 100."
    if limit < 1 or limit > _DISCORD_HISTORY_LIMIT_MAX:
        return None, "limit must be between 1 and 100."
    return limit, None


def _build_discord_messages_path(channel_id: str, args: dict[str, Any]) -> tuple[str | None, str | None]:
    limit, limit_error = _validate_discord_history_limit(args.get("limit"))
    if limit_error:
        return None, limit_error
    assert limit is not None
    query = [f"limit={limit}"]
    cursor_fields = [
        ("before", args.get("before_message_id")),
        ("after", args.get("after_message_id")),
        ("around", args.get("around_message_id")),
    ]
    supplied = [(name, str(value).strip()) for name, value in cursor_fields if str(value or "").strip()]
    if len(supplied) > 1:
        return None, "Use at most one of before_message_id, after_message_id, or around_message_id."
    for name, message_id in supplied:
        if not message_id.isdigit():
            return None, f"{name}_message_id must be a numeric Discord snowflake."
        query.append(f"{name}={message_id}")
    return f"/channels/{channel_id}/messages?{'&'.join(query)}", None


def _format_discord_history_message(raw: dict[str, Any]) -> dict[str, Any]:
    author = raw.get("author") or {}
    attachments = raw.get("attachments") or []
    embeds = raw.get("embeds") or []
    return {
        "id": str(raw.get("id") or ""),
        "timestamp": raw.get("timestamp"),
        "author": {
            "id": str(author.get("id") or ""),
            "username": str(author.get("username") or ""),
            "global_name": author.get("global_name"),
            "bot": bool(author.get("bot")),
        },
        "content": str(raw.get("content") or ""),
        "mentions": [str((m or {}).get("id") or "") for m in (raw.get("mentions") or []) if isinstance(m, dict)],
        "attachments": [
            {
                "id": str((att or {}).get("id") or ""),
                "filename": str((att or {}).get("filename") or ""),
                "url": str((att or {}).get("url") or ""),
                "content_type": (att or {}).get("content_type"),
            }
            for att in attachments
            if isinstance(att, dict)
        ],
        "embeds_count": len(embeds) if isinstance(embeds, list) else 0,
        "referenced_message_id": str((raw.get("referenced_message") or {}).get("id") or "") if isinstance(raw.get("referenced_message"), dict) else None,
    }


async def _discord_read_messages(token: str, channel_id: str, args: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    path, path_error = _build_discord_messages_path(channel_id, args)
    if path_error:
        return [], path_error
    assert path is not None
    data, err = await _discord_api_request(token, "GET", path)
    if err:
        return [], err
    if not isinstance(data, list):
        return [], "Discord messages lookup returned unexpected response."
    messages = [_format_discord_history_message(item) for item in data if isinstance(item, dict)]
    messages.reverse()  # Present chronologically; Discord REST returns newest first.
    return messages, None


def _validate_thread_rename_title(value: str | None) -> tuple[str | None, str | None]:
    raw = str(value or "")
    title = raw.strip()
    if not title:
        return None, "new_title is required for rename_thread_by_id."
    if "\n" in raw or "\r" in raw:
        return None, "new_title must not contain newlines."
    if _DISCORD_CONTROL_CHAR_RE.search(raw):
        return None, "new_title must not contain suspicious control characters."
    if len(title) > _DISCORD_THREAD_TITLE_MAX_LENGTH:
        return None, f"new_title must be {_DISCORD_THREAD_TITLE_MAX_LENGTH} characters or fewer."
    return title, None


def _validate_thread_can_be_renamed(thread: dict[str, Any], parent_channel_id: str) -> tuple[str | None, str | None]:
    if thread.get("type") not in {10, 11, 12}:
        return None, "Discord thread rename rejected: target channel is not a thread."
    actual_parent_id = str(thread.get("parent_id") or "")
    if actual_parent_id != parent_channel_id:
        return None, "Discord thread rename rejected: thread.parent_id does not match approved parent_channel_id."
    metadata = thread.get("thread_metadata") or {}
    if metadata.get("archived") or metadata.get("locked"):
        return None, "Discord thread rename rejected: thread is archived or locked."
    return actual_parent_id, None


async def _discord_api_request(token: str, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    """Small Discord REST helper that never returns or logs the token."""
    try:
        import aiohttp
        from gateway.platforms.base import resolve_proxy_url, proxy_kwargs_for_aiohttp
        _proxy = resolve_proxy_url(platform_env_var="DISCORD_PROXY")
        _sess_kw, _req_kw = proxy_kwargs_for_aiohttp(_proxy)
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        url = f"https://discord.com/api/v10{path}"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), **_sess_kw) as session:
            async with session.request(method, url, headers=headers, json=json_body, **_req_kw) as resp:
                if resp.status == 204:
                    return None, None
                text = await resp.text()
                if resp.status not in {200, 201}:
                    return None, _sanitize_error_text(f"Discord API error ({resp.status}): {text}")
                try:
                    return json.loads(text), None
                except Exception:
                    return None, f"Discord API returned non-JSON response ({resp.status})."
    except Exception as exc:
        return None, _sanitize_error_text(f"Discord API request failed: {exc}")


async def _discord_get_thread_info(token: str, thread_id: str) -> tuple[dict[str, Any] | None, str | None]:
    data, err = await _discord_api_request(token, "GET", f"/channels/{thread_id}")
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "Discord thread lookup returned unexpected response."
    parent_id = str(data.get("parent_id") or "")
    if parent_id not in _DISCORD_APPROVED_THREAD_IDS:
        return None, "Resolved Discord thread is outside approved internal lanes."
    if data.get("type") not in {10, 11, 12}:
        return None, "Resolved Discord channel is not a thread."
    return data, None


async def _discord_list_threads(token: str, parent_channel_id: str, query: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """List active/recent public archived threads for one approved parent channel."""
    parent_info, parent_err = await _discord_api_request(token, "GET", f"/channels/{parent_channel_id}")
    if parent_err:
        return [], parent_err
    guild_id = str((parent_info or {}).get("guild_id") or "") if isinstance(parent_info, dict) else ""
    paths = []
    if guild_id:
        paths.append(f"/guilds/{guild_id}/threads/active")
    paths.append(f"/channels/{parent_channel_id}/threads/archived/public?limit=50")
    seen: set[str] = set()
    matches: list[dict[str, Any]] = []
    q = (query or "").casefold().strip()
    warnings: list[str] = []
    for path in paths:
        data, err = await _discord_api_request(token, "GET", path)
        if err:
            # Some Discord channel types/permission combinations expose active
            # thread listing but return 404 for archived-public listing. Keep
            # list/resolve usable without treating that best-effort archive
            # probe as a hard failure.
            if "/threads/archived/public" in path and "Discord API error (404)" in err:
                warnings.append("archived public thread listing unavailable for this channel/runtime")
                continue
            return [], err
        threads = []
        if isinstance(data, dict):
            threads = data.get("threads") or []
        for thread in threads:
            tid = str(thread.get("id") or "")
            title = str(thread.get("name") or "")
            thread_parent_id = str(thread.get("parent_id") or parent_channel_id)
            if thread_parent_id != parent_channel_id:
                continue
            if not tid or tid in seen:
                continue
            if q and q not in title.casefold() and q not in tid:
                continue
            seen.add(tid)
            matches.append({
                "thread_id": tid,
                "title": title,
                "parent_channel_id": thread_parent_id,
                "archived": bool((thread.get("thread_metadata") or {}).get("archived")),
                "locked": bool((thread.get("thread_metadata") or {}).get("locked")),
            })
    if warnings:
        for item in matches:
            item.setdefault("warnings", warnings)
    return matches, None


def _handle_discord_thread_action(args: dict[str, Any], action: str) -> str:
    """Bounded Discord thread tooling exposed through send_message."""
    pconfig, cfg_error = _get_discord_platform_config()
    if cfg_error:
        return _discord_thread_error(cfg_error)
    token = pconfig.token
    assert token is not None
    from model_tools import _run_async

    try:
        if action in {"list_threads", "resolve_thread", "create_thread"}:
            parent_raw = args.get("parent_channel") or args.get("target")
            parent_id, parent_error = _resolve_approved_discord_parent_channel(parent_raw)
            if parent_error:
                return _discord_thread_error(parent_error)

        if action == "list_threads":
            query = args.get("query") or args.get("title")
            threads, err = _run_async(_discord_list_threads(token, parent_id, query))
            if err:
                return _discord_thread_error(err)
            return json.dumps({"success": True, "platform": "discord", "parent_channel_id": parent_id, "threads": threads, "count": len(threads)})

        if action == "resolve_thread":
            query = args.get("query") or args.get("title")
            if not (query or "").strip():
                return _discord_thread_error("query or title is required for resolve_thread.")
            threads, err = _run_async(_discord_list_threads(token, parent_id, query))
            if err:
                return _discord_thread_error(err)
            exact = [t for t in threads if t.get("title") == query]
            chosen = exact[0] if len(exact) == 1 else (threads[0] if len(threads) == 1 else None)
            return json.dumps({"success": True, "platform": "discord", "parent_channel_id": parent_id, "thread": chosen, "matches": threads, "count": len(threads)})

        if action == "create_thread":
            title = (args.get("title") or "").strip()
            if not title:
                return _discord_thread_error("title is required for create_thread.")
            existing, err = _run_async(_discord_list_threads(token, parent_id, title))
            if err:
                return _discord_thread_error(err)
            exact_existing = [t for t in existing if t.get("title") == title]
            if exact_existing:
                return json.dumps({
                    "success": True,
                    "platform": "discord",
                    "parent_channel_id": parent_id,
                    "thread_id": exact_existing[0]["thread_id"],
                    "existed": True,
                    "starter_message_id": None,
                    "note": "Exact thread already exists; no duplicate thread or starter message posted.",
                })
            body = {"name": title, "auto_archive_duration": int(args.get("auto_archive_duration") or 10080), "type": 11}
            thread, err = _run_async(_discord_api_request(token, "POST", f"/channels/{parent_id}/threads", json_body=body))
            if err:
                return _discord_thread_error(err)
            if not isinstance(thread, dict) or not thread.get("id"):
                return _discord_thread_error("Discord thread creation returned unexpected response.")
            thread_id = str(thread["id"])
            starter_message_id = None
            starter_message = args.get("starter_message") or args.get("message") or ""
            if starter_message.strip():
                send_result = _run_async(_send_discord(token, parent_id, starter_message, thread_id=thread_id))
                if isinstance(send_result, dict) and send_result.get("error"):
                    return json.dumps({
                        "success": False,
                        "platform": "discord",
                        "parent_channel_id": parent_id,
                        "thread_id": thread_id,
                        "error": send_result.get("error"),
                        "note": "Thread was created but starter message failed.",
                    })
                if isinstance(send_result, dict):
                    starter_message_id = send_result.get("message_id")
            return json.dumps({"success": True, "platform": "discord", "parent_channel_id": parent_id, "thread_id": thread_id, "starter_message_id": starter_message_id, "existed": False})

        if action == "read_channel_messages":
            parent_raw = args.get("parent_channel") or args.get("target") or args.get("channel_id")
            parent_id, parent_error = _resolve_approved_discord_parent_channel(parent_raw)
            if parent_error:
                return _discord_thread_error(parent_error)
            assert parent_id is not None
            messages, err = _run_async(_discord_read_messages(token, parent_id, args))
            if err:
                return _discord_thread_error(err)
            return json.dumps({
                "success": True,
                "platform": "discord",
                "action": action,
                "channel_id": parent_id,
                "parent_channel_id": parent_id,
                "messages": messages,
                "count": len(messages),
                "order": "chronological",
            })

        if action == "read_thread_messages":
            thread_id, thread_error = _validate_discord_snowflake(args.get("thread_id") or args.get("target"), "thread_id")
            if thread_error:
                return _discord_thread_error(thread_error.replace("rename_thread_by_id", "read_thread_messages"))
            assert thread_id is not None
            thread_info, err = _run_async(_discord_get_thread_info(token, thread_id))
            if err:
                return _discord_thread_error(err)
            parent_id = str(thread_info.get("parent_id") or "")
            if parent_id not in _DISCORD_APPROVED_HISTORY_PARENT_IDS:
                return _discord_thread_error("Discord history reads are limited to approved internal lanes only.")
            messages, err = _run_async(_discord_read_messages(token, thread_id, args))
            if err:
                return _discord_thread_error(err)
            return json.dumps({
                "success": True,
                "platform": "discord",
                "action": action,
                "thread_id": thread_id,
                "parent_channel_id": parent_id,
                "thread_title": str(thread_info.get("name") or ""),
                "messages": messages,
                "count": len(messages),
                "order": "chronological",
            })

        if action == "rename_thread_by_id":
            thread_id, thread_error = _validate_discord_snowflake(args.get("thread_id"), "thread_id")
            if thread_error:
                return _discord_thread_error(thread_error)
            parent_id, parent_error = _validate_thread_rename_parent_id(args.get("parent_channel_id"))
            if parent_error:
                return _discord_thread_error(parent_error)
            new_title, title_error = _validate_thread_rename_title(args.get("new_title"))
            if title_error:
                return _discord_thread_error(title_error)
            assert thread_id is not None
            assert parent_id is not None
            assert new_title is not None
            assert token is not None
            thread_info, err = _run_async(_discord_get_thread_info(token, thread_id))
            if err:
                return _discord_thread_error(err)
            _actual_parent_id, validation_error = _validate_thread_can_be_renamed(thread_info, parent_id)
            if validation_error:
                return _discord_thread_error(validation_error)
            updated, err = _run_async(_discord_api_request(token, "PATCH", f"/channels/{thread_id}", json_body={"name": new_title}))
            if err:
                return _discord_thread_error(err)
            if not isinstance(updated, dict):
                return _discord_thread_error("Discord thread rename returned unexpected response.")
            updated_parent_id = str(updated.get("parent_id") or parent_id)
            if updated_parent_id != parent_id:
                return _discord_thread_error("Discord thread rename returned a thread outside the approved parent channel.")
            return json.dumps({
                "success": True,
                "platform": "discord",
                "action": action,
                "thread_id": str(updated.get("id") or thread_id),
                "parent_channel_id": parent_id,
                "old_title": str(thread_info.get("name") or ""),
                "new_title": str(updated.get("name") or new_title),
            })

        if action == "send_to_thread":
            thread_id = (args.get("thread_id") or "").strip()
            if not thread_id:
                # Allow title/query resolution when a parent channel is supplied.
                parent_raw = args.get("parent_channel") or args.get("target")
                parent_id, parent_error = _resolve_approved_discord_parent_channel(parent_raw)
                if parent_error:
                    return _discord_thread_error("thread_id is required unless parent_channel plus query/title resolves exactly.")
                query = args.get("query") or args.get("title")
                threads, err = _run_async(_discord_list_threads(token, parent_id, query))
                if err:
                    return _discord_thread_error(err)
                if len(threads) != 1:
                    return _discord_thread_error(f"Could not resolve exactly one thread; matches={len(threads)}.")
                thread_id = threads[0]["thread_id"]
            thread_info, err = _run_async(_discord_get_thread_info(token, thread_id))
            if err:
                return _discord_thread_error(err)
            parent_id = str(thread_info.get("parent_id") or "")
            message = args.get("message") or args.get("starter_message") or ""
            if not message.strip():
                return _discord_thread_error("message is required for send_to_thread.")
            result = _run_async(_send_discord(token, parent_id, message, thread_id=thread_id))
            if isinstance(result, dict) and result.get("error"):
                return json.dumps(result)
            if isinstance(result, dict):
                result["thread_id"] = thread_id
                result["parent_channel_id"] = parent_id
            return json.dumps(result)
    except Exception as exc:
        return _discord_thread_error(f"Discord thread action failed: {exc}")

    return _discord_thread_error(f"Unsupported Discord thread action: {action}")


def _handle_send(args):
    """Send a message to a platform target."""
    target = args.get("target", "")
    message = args.get("message", "")
    if not target or not message:
        return tool_error("Both 'target' and 'message' are required when action='send'")

    parts = target.split(":", 1)
    platform_name = parts[0].strip().lower()
    target_ref = parts[1].strip() if len(parts) > 1 else None
    chat_id = None
    thread_id = None

    if target_ref:
        chat_id, thread_id, is_explicit = _parse_target_ref(platform_name, target_ref)
    else:
        is_explicit = False

    # Resolve human-friendly channel names to numeric IDs
    if target_ref and not is_explicit:
        try:
            from gateway.channel_directory import resolve_channel_name
            resolved = resolve_channel_name(platform_name, target_ref)
            if resolved:
                chat_id, thread_id, _ = _parse_target_ref(platform_name, resolved)
            else:
                return json.dumps({
                    "error": f"Could not resolve '{target_ref}' on {platform_name}. "
                    f"Use send_message(action='list') to see available targets."
                })
        except Exception:
            return json.dumps({
                "error": f"Could not resolve '{target_ref}' on {platform_name}. "
                f"Try using a numeric channel ID instead."
            })

    from tools.interrupt import is_interrupted
    if is_interrupted():
        return tool_error("Interrupted")

    try:
        from gateway.config import load_gateway_config, Platform
        config = load_gateway_config()
    except Exception as e:
        return json.dumps(_error(f"Failed to load gateway config: {e}"))

    # Accept any platform name — built-in names resolve to their enum
    # member, plugin platform names create dynamic members via _missing_().
    try:
        platform = Platform(platform_name)
    except (ValueError, KeyError):
        return tool_error(f"Unknown platform: {platform_name}")

    pconfig = config.platforms.get(platform)
    if not pconfig or not pconfig.enabled:
        # Weixin can be configured purely via .env; synthesize a pconfig so
        # send_message and cron delivery work without a gateway.yaml entry.
        if platform_name == "weixin":
            wx_token = os.getenv("WEIXIN_TOKEN", "").strip()
            wx_account = os.getenv("WEIXIN_ACCOUNT_ID", "").strip()
            if wx_token and wx_account:
                from gateway.config import PlatformConfig
                pconfig = PlatformConfig(
                    enabled=True,
                    token=wx_token,
                    extra={
                        "account_id": wx_account,
                        "base_url": os.getenv("WEIXIN_BASE_URL", "").strip(),
                        "cdn_base_url": os.getenv("WEIXIN_CDN_BASE_URL", "").strip(),
                    },
                )
            else:
                return tool_error(f"Platform '{platform_name}' is not configured. Set up credentials in ~/.hermes/config.yaml or environment variables.")
        else:
            return tool_error(f"Platform '{platform_name}' is not configured. Set up credentials in ~/.hermes/config.yaml or environment variables.")

    from gateway.platforms.base import BasePlatformAdapter

    # Capture [[as_document]] directive before extract_media strips it.
    # Image-extension files in this batch will route through send_document
    # instead of send_photo so the original bytes survive (e.g. info-graph
    # JPGs where Telegram's sendPhoto recompresses to 1280px).
    force_document_attachments = "[[as_document]]" in message

    media_files, cleaned_message = BasePlatformAdapter.extract_media(message)
    mirror_text = cleaned_message.strip() or _describe_media_for_mirror(media_files)

    used_home_channel = False
    if not chat_id:
        home = config.get_home_channel(platform)
        if not home and platform_name == "weixin":
            wx_home = os.getenv("WEIXIN_HOME_CHANNEL", "").strip()
            if wx_home:
                from gateway.config import HomeChannel
                home = HomeChannel(platform=platform, chat_id=wx_home, name="Weixin Home")
        if home:
            chat_id = home.chat_id
            used_home_channel = True
        else:
            return json.dumps({
                "error": f"No home channel set for {platform_name} to determine where to send the message. "
                f"Either specify a channel directly with '{platform_name}:CHANNEL_NAME', "
                f"or set a home channel via: hermes config set {platform_name.upper()}_HOME_CHANNEL <channel_id>"
            })

    duplicate_skip = _maybe_skip_cron_duplicate_send(platform_name, chat_id, thread_id)
    if duplicate_skip:
        return json.dumps(duplicate_skip)

    # Slack: resolve user IDs (U...) to DM channel IDs via conversations.open
    if platform_name == "slack" and chat_id and chat_id.startswith("U"):
        try:
            import aiohttp
            async def _open_slack_dm(token, user_id):
                url = "https://slack.com/api/conversations.open"
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                    async with session.post(url, headers=headers, json={"users": [user_id]}) as resp:
                        data = await resp.json()
                        if data.get("ok"):
                            return data["channel"]["id"]
                        return None
            from model_tools import _run_async
            dm_channel = _run_async(_open_slack_dm(pconfig.token, chat_id))
            if dm_channel:
                chat_id = dm_channel
            else:
                return json.dumps({"error": f"Could not open DM with Slack user {chat_id}. Check bot permissions (im:write)."})
        except Exception as e:
            return json.dumps({"error": f"Failed to open Slack DM: {e}"})

    try:
        from model_tools import _run_async
        result = _run_async(
            _send_to_platform(
                platform,
                pconfig,
                chat_id,
                cleaned_message,
                thread_id=thread_id,
                media_files=media_files,
                force_document=force_document_attachments,
            )
        )
        if used_home_channel and isinstance(result, dict) and result.get("success"):
            result["note"] = f"Sent to {platform_name} home channel (chat_id: {chat_id})"

        # Mirror the sent message into the target's gateway session
        if isinstance(result, dict) and result.get("success") and mirror_text:
            try:
                from gateway.mirror import mirror_to_session
                from gateway.session_context import get_session_env
                from gateway.routing_context import (
                    format_target as _format_route_target,
                    record_outbound_route,
                )
                source_label = get_session_env("HERMES_SESSION_PLATFORM", "cli")
                source_chat_id = get_session_env("HERMES_SESSION_CHAT_ID", "")
                source_chat_name = get_session_env("HERMES_SESSION_CHAT_NAME", "")
                source_thread_id = get_session_env("HERMES_SESSION_THREAD_ID", "")
                user_id = get_session_env("HERMES_SESSION_USER_ID", "") or None
                user_name = get_session_env("HERMES_SESSION_USER_NAME", "")
                source_target = _format_route_target(
                    source_label,
                    source_chat_id,
                    source_thread_id,
                )
                delivered_chat_id = (
                    str(result.get("thread_id") or "")
                    if platform_name == "discord" and (thread_id or result.get("thread_id"))
                    else str(chat_id)
                )
                delivered_thread_id = str(result.get("thread_id") or thread_id or "")
                delivered_target = _format_route_target(
                    platform_name,
                    delivered_chat_id,
                    delivered_thread_id,
                )
                mirror_body = _with_route_back_context(
                    mirror_text,
                    return_target=source_target,
                    return_label=source_chat_name,
                    return_user=user_name,
                    delivered_target=delivered_target,
                )
                mirror_chat_id = delivered_chat_id if platform_name == "discord" else chat_id
                mirror_thread_id = delivered_thread_id or thread_id
                if mirror_to_session(
                    platform_name,
                    mirror_chat_id,
                    mirror_body,
                    source_label=source_label,
                    thread_id=mirror_thread_id,
                    user_id=user_id,
                ):
                    result["mirrored"] = True
                if (
                    result.get("message_id")
                    and source_target
                    and delivered_target
                    and source_target != delivered_target
                ):
                    if record_outbound_route(
                        platform=platform_name,
                        chat_id=delivered_chat_id,
                        thread_id=delivered_thread_id,
                        message_id=str(result.get("message_id")),
                        return_target=source_target,
                        return_label=source_chat_name,
                        return_user=user_name,
                        original_message=mirror_text,
                    ):
                        result["route_back_recorded"] = True
            except Exception:
                pass

        if isinstance(result, dict) and "error" in result:
            result["error"] = _sanitize_error_text(result["error"])
        return json.dumps(result)
    except Exception as e:
        return json.dumps(_error(f"Send failed: {e}"))


def _with_route_back_context(
    message_text: str,
    *,
    return_target: str | None,
    return_label: str = "",
    return_user: str = "",
    delivered_target: str | None = None,
) -> str:
    """Add route-back instructions to the target session mirror only."""
    text = str(message_text or "")
    return_target = (return_target or "").strip()
    delivered_target = (delivered_target or "").strip()
    if not return_target or not delivered_target or return_target == delivered_target:
        return text

    label_bits = []
    if return_user:
        label_bits.append(str(return_user).strip())
    if return_label and str(return_label).strip() not in label_bits:
        label_bits.append(str(return_label).strip())
    source_label = " / ".join(bit for bit in label_bits if bit) or return_target

    return (
        "[Delivery mirror for routed message]\n"
        f"Original source: {source_label}\n"
        f"Return target: `{return_target}`\n"
        "When this routed request gets an answer, fix, decision, or status update "
        "here, send a concise update back to the return target with send_message. "
        "Do not assume the original requester can see this destination chat.\n\n"
        "Delivered message:\n"
        f"{text}"
    )


def _parse_target_ref(platform_name: str, target_ref: str):
    """Parse a tool target into chat_id/thread_id and whether it is explicit."""
    if platform_name == "telegram":
        match = _TELEGRAM_TOPIC_TARGET_RE.fullmatch(target_ref)
        if match:
            return match.group(1), match.group(2), True
    if platform_name == "feishu":
        match = _FEISHU_TARGET_RE.fullmatch(target_ref)
        if match:
            return match.group(1), match.group(2), True
    if platform_name == "discord":
        match = _NUMERIC_TOPIC_RE.fullmatch(target_ref)
        if match:
            return match.group(1), match.group(2), True
    if platform_name == "slack":
        match = _SLACK_THREAD_TARGET_RE.fullmatch(target_ref)
        if match:
            return match.group(1), match.group(2), True
        match = _SLACK_TARGET_RE.fullmatch(target_ref)
        if match:
            chat_id = match.group(1)
            # Slack user IDs (U...) and workspace IDs (W...) are NOT valid
            # explicit send targets — chat.postMessage rejects them. A DM
            # must be opened first via conversations.open to get a D...
            # conversation ID. Caller still gets the chat_id so the U→D
            # resolution path in send_message() can run.
            is_explicit = chat_id[0] not in {"U", "W"}
            return chat_id, None, is_explicit
    if platform_name == "matrix":
        trimmed = target_ref.strip()
        split_idx = trimmed.rfind(":$")
        if split_idx > 0:
            return trimmed[:split_idx], trimmed[split_idx + 1 :], True
    if platform_name == "weixin":
        match = _WEIXIN_TARGET_RE.fullmatch(target_ref)
        if match:
            return match.group(1), None, True
    if platform_name == "yuanbao":
        match = _YUANBAO_TARGET_RE.fullmatch(target_ref)
        if match:
            return match.group(1), None, True
        if target_ref.strip().isdigit():
            return f"group:{target_ref.strip()}", None, True
        return None, None, False
    if platform_name in _PHONE_PLATFORMS:
        match = _E164_TARGET_RE.fullmatch(target_ref)
        if match:
            # Preserve the leading '+' — signal-cli and sms/whatsapp adapters
            # expect E.164 format for direct recipients.
            return target_ref.strip(), None, True
    if target_ref.lstrip("-").isdigit():
        return target_ref, None, True
    # Matrix room IDs (start with !) and user IDs (start with @) are explicit
    if platform_name == "matrix" and (target_ref.startswith("!") or target_ref.startswith("@")):
        return target_ref, None, True
    # XMPP JIDs (user@server or room@conference.server) are explicit
    if platform_name == "xmpp" and "@" in target_ref:
        return target_ref, None, True
    return None, None, False


def _describe_media_for_mirror(media_files):
    """Return a human-readable mirror summary when a message only contains media."""
    if not media_files:
        return ""
    if len(media_files) == 1:
        media_path, is_voice = media_files[0]
        ext = os.path.splitext(media_path)[1].lower()
        if is_voice and ext in _VOICE_EXTS:
            return "[Sent voice message]"
        if ext in _IMAGE_EXTS:
            return "[Sent image attachment]"
        if ext in _VIDEO_EXTS:
            return "[Sent video attachment]"
        if ext in _AUDIO_EXTS:
            return "[Sent audio attachment]"
        return "[Sent document attachment]"
    return f"[Sent {len(media_files)} media attachments]"


def _get_cron_auto_delivery_target():
    """Return the cron scheduler's auto-delivery target for the current run, if any."""
    from gateway.session_context import get_session_env
    platform = get_session_env("HERMES_CRON_AUTO_DELIVER_PLATFORM", "").strip().lower()
    chat_id = get_session_env("HERMES_CRON_AUTO_DELIVER_CHAT_ID", "").strip()
    if not platform or not chat_id:
        return None
    thread_id = get_session_env("HERMES_CRON_AUTO_DELIVER_THREAD_ID", "").strip() or None
    return {
        "platform": platform,
        "chat_id": chat_id,
        "thread_id": thread_id,
    }


def _maybe_skip_cron_duplicate_send(platform_name: str, chat_id: str, thread_id: str | None):
    """Skip redundant cron send_message calls when the scheduler will auto-deliver there."""
    auto_target = _get_cron_auto_delivery_target()
    if not auto_target:
        return None

    same_target = (
        auto_target["platform"] == platform_name
        and str(auto_target["chat_id"]) == str(chat_id)
        and auto_target.get("thread_id") == thread_id
    )
    if not same_target:
        return None

    target_label = f"{platform_name}:{chat_id}"
    if thread_id is not None:
        target_label += f":{thread_id}"

    return {
        "success": True,
        "skipped": True,
        "reason": "cron_auto_delivery_duplicate_target",
        "target": target_label,
        "note": (
            f"Skipped send_message to {target_label}. This cron job will already auto-deliver "
            "its final response to that same target. Put the intended user-facing content in "
            "your final response instead, or use a different target if you want an additional message."
        ),
    }


async def _send_via_adapter(
    platform,
    pconfig,
    chat_id,
    chunk,
    *,
    thread_id=None,
    media_files=None,
    force_document=False,
):
    """Send a message via a live gateway adapter, with a standalone fallback
    for out-of-process callers (e.g. cron running separately from the gateway).

    Order of attempts:
      1. Live in-process adapter via ``_gateway_runner_ref()`` (the path that
         existed before this change).
      2. The plugin's ``standalone_sender_fn`` registered on its
         ``PlatformEntry`` (used when the gateway is not in this process, so
         the runner weakref is ``None``).
      3. A descriptive error explaining both options.
    """
    runner = None
    try:
        from gateway.run import _gateway_runner_ref
        runner = _gateway_runner_ref()
    except Exception:
        runner = None

    if runner is not None:
        try:
            adapter = runner.adapters.get(platform)
        except Exception:
            adapter = None
        if adapter is not None:
            try:
                metadata = {"thread_id": thread_id} if thread_id else None
                result = await adapter.send(chat_id=chat_id, content=chunk, metadata=metadata)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                return {"error": f"Plugin platform send failed: {e}"}
            if result.success:
                return {"success": True, "message_id": result.message_id}
            return {"error": f"Adapter send failed: {result.error}"}

    platform_name = platform.value if hasattr(platform, "value") else str(platform)
    entry = None
    try:
        from gateway.platform_registry import platform_registry
        entry = platform_registry.get(platform_name)
    except Exception:
        entry = None

    if entry is not None and entry.standalone_sender_fn is not None:
        try:
            result = await entry.standalone_sender_fn(
                pconfig,
                chat_id,
                chunk,
                thread_id=thread_id,
                media_files=media_files,
                force_document=force_document,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("Plugin standalone send for %s raised", platform_name, exc_info=True)
            return {"error": f"Plugin standalone send failed: {e}"}

        if isinstance(result, dict) and (result.get("success") or result.get("error")):
            return result
        return {
            "error": (
                f"Plugin standalone send for '{platform_name}' returned an "
                f"invalid result: expected a dict with 'success' or 'error' "
                f"keys, got {type(result).__name__}"
            )
        }

    return {
        "error": (
            f"No live adapter for platform '{platform_name}'. Is the gateway "
            f"running with this platform connected? For out-of-process delivery "
            f"(e.g. cron in a separate process), the platform plugin must "
            f"register a standalone_sender_fn on its PlatformEntry."
        )
    }


async def _send_to_platform(platform, pconfig, chat_id, message, thread_id=None, media_files=None, force_document=False):
    """Route a message to the appropriate platform sender.

    Long messages are automatically chunked to fit within platform limits
    using the same smart-splitting algorithm as the gateway adapters
    (preserves code-block boundaries, adds part indicators).
    """
    from gateway.config import Platform
    from gateway.platforms.base import BasePlatformAdapter, utf16_len
    from gateway.platforms.discord import DiscordAdapter
    from gateway.platforms.slack import SlackAdapter

    # Telegram adapter import is optional (requires python-telegram-bot)
    try:
        from gateway.platforms.telegram import TelegramAdapter
        _telegram_available = True
    except ImportError:
        _telegram_available = False

    # Feishu adapter import is optional (requires lark-oapi)
    try:
        from gateway.platforms.feishu import FeishuAdapter
        _feishu_available = True
    except ImportError:
        _feishu_available = False

    media_files = media_files or []

    if platform == Platform.SLACK and message:
        try:
            slack_adapter = SlackAdapter.__new__(SlackAdapter)
            message = slack_adapter.format_message(message)
        except Exception:
            logger.debug("Failed to apply Slack mrkdwn formatting in _send_to_platform", exc_info=True)

    # Platform message length limits (from adapter class attributes)
    _MAX_LENGTHS = {
        Platform.TELEGRAM: TelegramAdapter.MAX_MESSAGE_LENGTH if _telegram_available else 4096,
        Platform.DISCORD: DiscordAdapter.MAX_MESSAGE_LENGTH,
        Platform.SLACK: SlackAdapter.MAX_MESSAGE_LENGTH,
    }
    if _feishu_available:
        _MAX_LENGTHS[Platform.FEISHU] = FeishuAdapter.MAX_MESSAGE_LENGTH

    # Check plugin registry for max_message_length
    if platform not in _MAX_LENGTHS:
        try:
            from gateway.platform_registry import platform_registry
            entry = platform_registry.get(platform.value)
            if entry and entry.max_message_length > 0:
                _MAX_LENGTHS[platform] = entry.max_message_length
        except Exception:
            pass

    # Smart-chunk the message to fit within platform limits.
    # For short messages or platforms without a known limit this is a no-op.
    # Telegram measures length in UTF-16 code units, not Unicode codepoints.
    max_len = _MAX_LENGTHS.get(platform)
    if max_len:
        _len_fn = utf16_len if platform == Platform.TELEGRAM else None
        chunks = BasePlatformAdapter.truncate_message(message, max_len, len_fn=_len_fn)
    else:
        chunks = [message]

    # --- Telegram: special handling for media attachments ---
    if platform == Platform.TELEGRAM:
        last_result = None
        disable_link_previews = bool(getattr(pconfig, "extra", {}) and pconfig.extra.get("disable_link_previews"))
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            result = await _send_telegram(
                pconfig.token,
                chat_id,
                chunk,
                media_files=media_files if is_last else [],
                thread_id=thread_id,
                disable_link_previews=disable_link_previews,
                force_document=force_document,
            )
            if isinstance(result, dict) and result.get("error"):
                return result
            last_result = result
        return last_result

    # --- Weixin: use the native one-shot adapter helper for text + media ---
    if platform == Platform.WEIXIN:
        return await _send_weixin(pconfig, chat_id, message, media_files=media_files)

    # --- Discord: special handling for media attachments ---
    if platform == Platform.DISCORD:
        last_result = None
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            result = await _send_discord(
                pconfig.token,
                chat_id,
                chunk,
                media_files=media_files if is_last else [],
                thread_id=thread_id,
            )
            if isinstance(result, dict) and result.get("error"):
                return result
            last_result = result
        return last_result

    # --- Matrix: use the native adapter helper when media is present ---
    if platform == Platform.MATRIX and media_files:
        last_result = None
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            result = await _send_matrix_via_adapter(
                pconfig,
                chat_id,
                chunk,
                media_files=media_files if is_last else [],
                thread_id=thread_id,
            )
            if isinstance(result, dict) and result.get("error"):
                return result
            last_result = result
        return last_result

    # --- Signal: native attachment support via JSON-RPC attachments param ---
    if platform == Platform.SIGNAL and media_files:
        last_result = None
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            result = await _send_signal(
                pconfig.extra,
                chat_id,
                chunk,
                media_files=media_files if is_last else [],
            )
            if isinstance(result, dict) and result.get("error"):
                return result
            last_result = result
        return last_result

    # --- Yuanbao: native media attachment support via running gateway adapter ---
    if platform == Platform.YUANBAO and media_files:
        last_result = None
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            result = await _send_yuanbao(
                chat_id,
                chunk,
                media_files=media_files if is_last else None,
            )
            if isinstance(result, dict) and result.get("error"):
                return result
            last_result = result
        return last_result

    # --- Feishu: native media attachment support via adapter ---
    if platform == Platform.FEISHU and media_files:
        last_result = None
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            result = await _send_feishu(
                pconfig,
                chat_id,
                chunk,
                media_files=media_files if is_last else None,
                thread_id=thread_id,
            )
            if isinstance(result, dict) and result.get("error"):
                return result
            last_result = result
        return last_result

    # --- Non-media platforms ---
    if media_files and not message.strip():
        return {
            "error": (
                f"send_message MEDIA delivery is currently only supported for telegram, discord, matrix, weixin, signal, yuanbao and feishu; "
                f"target {platform.value} had only media attachments"
            )
        }
    warning = None
    if media_files:
        warning = (
            f"MEDIA attachments were omitted for {platform.value}; "
            "native send_message media delivery is currently only supported for telegram, discord, matrix, weixin, signal, yuanbao and feishu"
        )

    last_result = None
    for chunk in chunks:
        if platform == Platform.SLACK:
            result = await _send_slack(pconfig.token, chat_id, chunk)
        elif platform == Platform.WHATSAPP:
            result = await _send_whatsapp(pconfig.extra, chat_id, chunk)
        elif platform == Platform.SIGNAL:
            result = await _send_signal(pconfig.extra, chat_id, chunk)
        elif platform == Platform.EMAIL:
            result = await _send_email(pconfig.extra, chat_id, chunk)
        elif platform == Platform.SMS:
            result = await _send_sms(pconfig.api_key, chat_id, chunk)
        elif platform == Platform.MATTERMOST:
            result = await _send_mattermost(pconfig.token, pconfig.extra, chat_id, chunk)
        elif platform == Platform.MATRIX:
            result = await _send_matrix(pconfig.token, pconfig.extra, chat_id, chunk)
        elif platform == Platform.HOMEASSISTANT:
            result = await _send_homeassistant(pconfig.token, pconfig.extra, chat_id, chunk)
        elif platform == Platform.DINGTALK:
            result = await _send_dingtalk(pconfig.extra, chat_id, chunk)
        elif platform == Platform.FEISHU:
            result = await _send_feishu(pconfig, chat_id, chunk, thread_id=thread_id)
        elif platform == Platform.WECOM:
            result = await _send_wecom(pconfig.extra, chat_id, chunk)
        elif platform == Platform.BLUEBUBBLES:
            result = await _send_bluebubbles(pconfig.extra, chat_id, chunk)
        elif platform == Platform.QQBOT:
            result = await _send_qqbot(pconfig, chat_id, chunk)
        elif platform == Platform.YUANBAO:
            result = await _send_yuanbao(chat_id, chunk)
        else:
            # Plugin platform: route through the gateway's live adapter if
            # available, otherwise the plugin's standalone_sender_fn.
            result = await _send_via_adapter(
                platform,
                pconfig,
                chat_id,
                chunk,
                thread_id=thread_id,
                media_files=media_files,
                force_document=force_document,
            )

        if isinstance(result, dict) and result.get("error"):
            return result
        last_result = result

    if warning and isinstance(last_result, dict) and last_result.get("success"):
        warnings = list(last_result.get("warnings", []))
        warnings.append(warning)
        last_result["warnings"] = warnings
    return last_result


def _is_telegram_thread_not_found(error: Exception) -> bool:
    """Check if a Telegram error is a thread-not-found failure.

    Matches the gateway adapter's ``_is_thread_not_found_error`` for
    the standalone ``_send_telegram`` path (issue #27012).
    """
    return "thread not found" in str(error).lower()


async def _send_telegram(token, chat_id, message, media_files=None, thread_id=None, disable_link_previews=False, force_document=False):
    """Send via Telegram Bot API (one-shot, no polling needed).

    Applies markdown→MarkdownV2 formatting (same as the gateway adapter)
    so that bold, links, and headers render correctly.  If the message
    already contains HTML tags, it is sent with ``parse_mode='HTML'``
    instead, bypassing MarkdownV2 conversion.
    """
    try:
        from telegram import Bot
        from telegram.constants import ParseMode

        # Auto-detect HTML tags — if present, skip MarkdownV2 and send as HTML.
        # Inspired by github.com/ashaney — PR #1568.
        _has_html = bool(re.search(r'<[a-zA-Z/][^>]*>', message))

        if _has_html:
            formatted = message
            send_parse_mode = ParseMode.HTML
        else:
            # Reuse the gateway adapter's format_message for markdown→MarkdownV2
            try:
                from gateway.platforms.telegram import TelegramAdapter
                _adapter = TelegramAdapter.__new__(TelegramAdapter)
                formatted = _adapter.format_message(message)
            except Exception:
                # Fallback: send as-is if formatting unavailable
                formatted = message
            send_parse_mode = ParseMode.MARKDOWN_V2

        # Honour a configured proxy (telegram.proxy_url in config.yaml, exported
        # as TELEGRAM_PROXY env var by load_gateway_config). Without this, the
        # standalone send path bypasses the proxy and times out in regions
        # where api.telegram.org is blocked. The in-gateway adapter does the
        # same thing in gateway/platforms/telegram.py.
        try:
            from gateway.platforms.base import resolve_proxy_url
            _tg_proxy = resolve_proxy_url("TELEGRAM_PROXY", target_hosts=["api.telegram.org"])
        except Exception:
            _tg_proxy = None
        if _tg_proxy:
            try:
                from telegram.request import HTTPXRequest
                logger.info("send_message: standalone Telegram send routed through proxy %s", _tg_proxy)
                bot = Bot(
                    token=token,
                    request=HTTPXRequest(proxy=_tg_proxy),
                    get_updates_request=HTTPXRequest(proxy=_tg_proxy),
                )
            except Exception as _proxy_err:
                logger.warning("send_message: failed to attach Telegram proxy (%s), falling back to direct connection", _proxy_err)
                bot = Bot(token=token)
        else:
            bot = Bot(token=token)
        int_chat_id = int(chat_id)
        media_files = media_files or []
        thread_kwargs = {}
        if thread_id is not None:
            # Reuse the gateway adapter's General-topic mapping: in Telegram
            # forum supergroups, the General topic is addressed as
            # message_thread_id="1" on incoming updates, but Bot API
            # sendMessage rejects message_thread_id=1 with "Message thread
            # not found". The adapter's helper maps "1" to None for that
            # reason; the send_message tool needs the same mapping or a
            # send to a forum group's General topic always errors out
            # (see issue #22267).
            try:
                from gateway.platforms.telegram import TelegramAdapter
                effective_thread_id = TelegramAdapter._message_thread_id_for_send(
                    str(thread_id)
                )
            except Exception:
                # Fallback: explicit mapping in case the adapter import
                # fails (e.g. python-telegram-bot missing in this venv).
                effective_thread_id = (
                    None if str(thread_id) == "1" else int(thread_id)
                )
            if effective_thread_id is not None:
                thread_kwargs["message_thread_id"] = effective_thread_id
        # disable_web_page_preview is only valid for send_message, not
        # send_photo/send_video/etc.  Keep it separate so media sends
        # don't inherit an invalid parameter (issue #27012).
        text_kwargs = dict(thread_kwargs)
        if disable_link_previews:
            text_kwargs["disable_web_page_preview"] = True

        last_msg = None
        warnings = []

        if formatted.strip():
            try:
                last_msg = await _send_telegram_message_with_retry(
                    bot,
                    chat_id=int_chat_id, text=formatted,
                    parse_mode=send_parse_mode, **text_kwargs
                )
            except Exception as md_error:
                # Thread not found — retry without message_thread_id so the
                # message still delivers (matching the gateway adapter's
                # fallback behaviour, issue #27012).
                if _is_telegram_thread_not_found(md_error) and thread_kwargs:
                    logger.warning(
                        "Thread %s not found in _send_telegram, retrying without message_thread_id",
                        thread_kwargs.get("message_thread_id"),
                    )
                    text_kwargs.pop("message_thread_id", None)
                    last_msg = await _send_telegram_message_with_retry(
                        bot,
                        chat_id=int_chat_id, text=formatted,
                        parse_mode=send_parse_mode, **text_kwargs
                    )
                elif "parse" in str(md_error).lower() or "markdown" in str(md_error).lower() or "html" in str(md_error).lower():
                    logger.warning(
                        "Parse mode %s failed in _send_telegram, falling back to plain text: %s",
                        send_parse_mode,
                        _sanitize_error_text(md_error),
                    )
                    if not _has_html:
                        try:
                            from gateway.platforms.telegram import _strip_mdv2
                            plain = _strip_mdv2(formatted)
                        except Exception:
                            plain = message
                    else:
                        plain = message
                    last_msg = await _send_telegram_message_with_retry(
                        bot,
                        chat_id=int_chat_id, text=plain,
                        parse_mode=None, **text_kwargs
                    )
                else:
                    raise

        for media_path, is_voice in media_files:
            if not os.path.exists(media_path):
                warning = f"Media file not found, skipping: {media_path}"
                logger.warning(warning)
                warnings.append(warning)
                continue

            ext = os.path.splitext(media_path)[1].lower()
            try:
                with open(media_path, "rb") as f:
                    media_kwargs = dict(thread_kwargs)
                    try:
                        if ext in _IMAGE_EXTS and not force_document:
                            last_msg = await bot.send_photo(
                                chat_id=int_chat_id, photo=f, **media_kwargs
                            )
                        elif ext in _VIDEO_EXTS:
                            last_msg = await bot.send_video(
                                chat_id=int_chat_id, video=f, **media_kwargs
                            )
                        elif ext in _VOICE_EXTS and is_voice:
                            last_msg = await bot.send_voice(
                                chat_id=int_chat_id, voice=f, **media_kwargs
                            )
                        elif ext in _TELEGRAM_SEND_AUDIO_EXTS:
                            last_msg = await bot.send_audio(
                                chat_id=int_chat_id, audio=f, **media_kwargs
                            )
                        else:
                            last_msg = await bot.send_document(
                                chat_id=int_chat_id, document=f, **media_kwargs
                            )
                    except Exception as media_err:
                        if _is_telegram_thread_not_found(media_err) and media_kwargs.get("message_thread_id"):
                            # Thread not found for media — retry without
                            # message_thread_id (issue #27012).
                            logger.warning(
                                "Thread %s not found for media send, retrying without message_thread_id",
                                media_kwargs["message_thread_id"],
                            )
                            # Re-seek the file since the first attempt consumed it
                            f.seek(0)
                            media_kwargs.pop("message_thread_id", None)
                            if ext in _IMAGE_EXTS and not force_document:
                                last_msg = await bot.send_photo(
                                    chat_id=int_chat_id, photo=f, **media_kwargs
                                )
                            elif ext in _VIDEO_EXTS:
                                last_msg = await bot.send_video(
                                    chat_id=int_chat_id, video=f, **media_kwargs
                                )
                            elif ext in _VOICE_EXTS and is_voice:
                                last_msg = await bot.send_voice(
                                    chat_id=int_chat_id, voice=f, **media_kwargs
                                )
                            elif ext in _TELEGRAM_SEND_AUDIO_EXTS:
                                last_msg = await bot.send_audio(
                                    chat_id=int_chat_id, audio=f, **media_kwargs
                                )
                            else:
                                last_msg = await bot.send_document(
                                    chat_id=int_chat_id, document=f, **media_kwargs
                                )
                        else:
                            raise
            except Exception as e:
                warning = _sanitize_error_text(f"Failed to send media {media_path}: {e}")
                logger.error(warning)
                warnings.append(warning)

        if last_msg is None:
            error = "No deliverable text or media remained after processing MEDIA tags"
            if warnings:
                return {"error": error, "warnings": warnings}
            return {"error": error}

        result = {
            "success": True,
            "platform": "telegram",
            "chat_id": chat_id,
            "message_id": str(last_msg.message_id),
        }
        if warnings:
            result["warnings"] = warnings
        return result
    except ImportError:
        return {"error": "python-telegram-bot not installed. Run: pip install python-telegram-bot"}
    except Exception as e:
        return _error(f"Telegram send failed: {e}")


def _derive_forum_thread_name(message: str) -> str:
    """Derive a thread name from the first line of the message, capped at 100 chars."""
    first_line = message.strip().split("\n", 1)[0].strip()
    # Strip common markdown heading prefixes
    first_line = first_line.lstrip("#").strip()
    if not first_line:
        first_line = "New Post"
    return first_line[:100]


# Process-local cache for Discord channel-type probes.  Avoids re-probing the
# same channel on every send when the directory cache has no entry (e.g. fresh
# install, or channel created after the last directory build).
_DISCORD_CHANNEL_TYPE_PROBE_CACHE: Dict[str, bool] = {}


def _remember_channel_is_forum(chat_id: str, is_forum: bool) -> None:
    _DISCORD_CHANNEL_TYPE_PROBE_CACHE[str(chat_id)] = bool(is_forum)


def _probe_is_forum_cached(chat_id: str) -> Optional[bool]:
    return _DISCORD_CHANNEL_TYPE_PROBE_CACHE.get(str(chat_id))


async def _send_discord(token, chat_id, message, thread_id=None, media_files=None):
    """Send a single message via Discord REST API (no websocket client needed).

    Chunking is handled by _send_to_platform() before this is called.

    When thread_id is provided, the message is sent directly to that thread
    via the /channels/{thread_id}/messages endpoint.

    Media files are uploaded one-by-one via multipart/form-data after the
    text message is sent (same pattern as Telegram).

    Forum channels (type 15) reject POST /messages — a thread post is created
    automatically via POST /channels/{id}/threads.  Media files are uploaded
    as multipart attachments on the starter message of the new thread.

    Channel type is resolved from the channel directory first, then a
    process-local probe cache, and only as a last resort with a live
    GET /channels/{id} probe (whose result is memoized).
    """
    try:
        import aiohttp
    except ImportError:
        return {"error": "aiohttp not installed. Run: pip install aiohttp"}
    try:
        from gateway.platforms.base import resolve_proxy_url, proxy_kwargs_for_aiohttp
        _proxy = resolve_proxy_url(platform_env_var="DISCORD_PROXY")
        _sess_kw, _req_kw = proxy_kwargs_for_aiohttp(_proxy)
        auth_headers = {"Authorization": f"Bot {token}"}
        json_headers = {**auth_headers, "Content-Type": "application/json"}
        media_files = media_files or []
        last_data = None
        warnings = []

        # Thread endpoint: Discord threads are channels; send directly to the thread ID.
        if thread_id:
            url = f"https://discord.com/api/v10/channels/{thread_id}/messages"
        else:
            # Check if the target channel is a forum channel (type 15).
            # Forum channels reject POST /messages — create a thread post instead.
            # Three-layer detection: directory cache → process-local probe
            # cache → GET /channels/{id} probe (with result memoized).
            _channel_type = None
            try:
                from gateway.channel_directory import lookup_channel_type
                _channel_type = lookup_channel_type("discord", chat_id)
            except Exception:
                pass

            if _channel_type == "forum":
                is_forum = True
            elif _channel_type is not None:
                is_forum = False
            else:
                cached = _probe_is_forum_cached(chat_id)
                if cached is not None:
                    is_forum = cached
                else:
                    is_forum = False
                    try:
                        info_url = f"https://discord.com/api/v10/channels/{chat_id}"
                        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), **_sess_kw) as info_sess:
                            async with info_sess.get(info_url, headers=json_headers, **_req_kw) as info_resp:
                                if info_resp.status == 200:
                                    info = await info_resp.json()
                                    is_forum = info.get("type") == 15
                                    _remember_channel_is_forum(chat_id, is_forum)
                    except Exception:
                        logger.debug("Failed to probe channel type for %s", chat_id, exc_info=True)

            if is_forum:
                thread_name = _derive_forum_thread_name(message)
                thread_url = f"https://discord.com/api/v10/channels/{chat_id}/threads"

                # Filter to readable media files up front so we can pick the
                # right code path (JSON vs multipart) before opening a session.
                valid_media = []
                for media_path, _is_voice in media_files:
                    if not os.path.exists(media_path):
                        warning = f"Media file not found, skipping: {media_path}"
                        logger.warning(warning)
                        warnings.append(warning)
                        continue
                    valid_media.append(media_path)

                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60), **_sess_kw) as session:
                    if valid_media:
                        # Multipart: payload_json + files[N] creates a forum
                        # thread with the starter message plus attachments in
                        # a single API call.
                        attachments_meta = [
                            {"id": str(idx), "filename": os.path.basename(path)}
                            for idx, path in enumerate(valid_media)
                        ]
                        starter_message = _discord_message_payload(
                            message,
                            attachments=attachments_meta,
                        )
                        payload_json = json.dumps({"name": thread_name, "message": starter_message})

                        form = aiohttp.FormData()
                        form.add_field("payload_json", payload_json, content_type="application/json")

                        # Buffer file bytes up front — aiohttp's FormData can
                        # read lazily and we don't want handles closing under
                        # it on retry.
                        try:
                            for idx, media_path in enumerate(valid_media):
                                with open(media_path, "rb") as fh:
                                    form.add_field(
                                        f"files[{idx}]",
                                        fh.read(),
                                        filename=os.path.basename(media_path),
                                    )
                            async with session.post(thread_url, headers=auth_headers, data=form, **_req_kw) as resp:
                                if resp.status not in {200, 201}:
                                    body = await resp.text()
                                    return _error(f"Discord forum thread creation error ({resp.status}): {body}")
                                data = await resp.json()
                        except Exception as e:
                            return _error(_sanitize_error_text(f"Discord forum thread upload failed: {e}"))
                    else:
                        # No media — simple JSON POST creates the thread with
                        # just the text starter.
                        async with session.post(
                            thread_url,
                            headers=json_headers,
                            json={
                                "name": thread_name,
                                "message": _discord_message_payload(message),
                            },
                            **_req_kw,
                        ) as resp:
                            if resp.status not in {200, 201}:
                                body = await resp.text()
                                return _error(f"Discord forum thread creation error ({resp.status}): {body}")
                            data = await resp.json()

                thread_id_created = data.get("id")
                starter_msg_id = (data.get("message") or {}).get("id", thread_id_created)
                result = {
                    "success": True,
                    "platform": "discord",
                    "chat_id": chat_id,
                    "thread_id": thread_id_created,
                    "message_id": starter_msg_id,
                }
                if warnings:
                    result["warnings"] = warnings
                return result

            url = f"https://discord.com/api/v10/channels/{chat_id}/messages"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), **_sess_kw) as session:
            # Send text message (skip if empty and media is present)
            if message.strip() or not media_files:
                async with session.post(url, headers=json_headers, json=_discord_message_payload(message), **_req_kw) as resp:
                    if resp.status not in {200, 201}:
                        body = await resp.text()
                        return _error(f"Discord API error ({resp.status}): {body}")
                    last_data = await resp.json()

            # Send each media file as a separate multipart upload
            for media_path, _is_voice in media_files:
                if not os.path.exists(media_path):
                    warning = f"Media file not found, skipping: {media_path}"
                    logger.warning(warning)
                    warnings.append(warning)
                    continue
                try:
                    form = aiohttp.FormData()
                    filename = os.path.basename(media_path)
                    with open(media_path, "rb") as f:
                        form.add_field("files[0]", f, filename=filename)
                        async with session.post(url, headers=auth_headers, data=form, **_req_kw) as resp:
                            if resp.status not in {200, 201}:
                                body = await resp.text()
                                warning = _sanitize_error_text(f"Failed to send media {media_path}: Discord API error ({resp.status}): {body}")
                                logger.error(warning)
                                warnings.append(warning)
                                continue
                            last_data = await resp.json()
                except Exception as e:
                    warning = _sanitize_error_text(f"Failed to send media {media_path}: {e}")
                    logger.error(warning)
                    warnings.append(warning)

        if last_data is None:
            error = "No deliverable text or media remained after processing"
            if warnings:
                return {"error": error, "warnings": warnings}
            return {"error": error}

        result = {"success": True, "platform": "discord", "chat_id": chat_id, "message_id": last_data.get("id")}
        if warnings:
            result["warnings"] = warnings
        return result
    except Exception as e:
        return _error(f"Discord send failed: {e}")


async def _send_slack(token, chat_id, message):
    """Send via Slack Web API."""
    try:
        import aiohttp
    except ImportError:
        return {"error": "aiohttp not installed. Run: pip install aiohttp"}
    try:
        from gateway.platforms.base import resolve_proxy_url, proxy_kwargs_for_aiohttp
        _proxy = resolve_proxy_url()
        _sess_kw, _req_kw = proxy_kwargs_for_aiohttp(_proxy)
        url = "https://slack.com/api/chat.postMessage"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), **_sess_kw) as session:
            payload = {"channel": chat_id, "text": message, "mrkdwn": True}
            async with session.post(url, headers=headers, json=payload, **_req_kw) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return {"success": True, "platform": "slack", "chat_id": chat_id, "message_id": data.get("ts")}
                return _error(f"Slack API error: {data.get('error', 'unknown')}")
    except Exception as e:
        return _error(f"Slack send failed: {e}")


async def _send_whatsapp(extra, chat_id, message):
    """Send via the local WhatsApp bridge HTTP API."""
    try:
        import aiohttp
    except ImportError:
        return {"error": "aiohttp not installed. Run: pip install aiohttp"}
    try:
        bridge_port = extra.get("bridge_port", 3000)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://localhost:{bridge_port}/send",
                json={"chatId": chat_id, "message": message},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "success": True,
                        "platform": "whatsapp",
                        "chat_id": chat_id,
                        "message_id": data.get("messageId"),
                    }
                body = await resp.text()
                return _error(f"WhatsApp bridge error ({resp.status}): {body}")
    except Exception as e:
        return _error(f"WhatsApp send failed: {e}")


async def _send_signal(extra, chat_id, message, media_files=None):
    """Send via signal-cli JSON-RPC API.

    Supports both text-only and text-with-attachments (images/audio/documents).
    Multi-attachment sends are chunked into batches of
    SIGNAL_MAX_ATTACHMENTS_PER_MSG and metered by the process-wide
    SignalAttachmentScheduler — same bucket the gateway adapter uses, so
    sends from this tool and inbound-driven replies share rate-limit state.
    """
    try:
        import httpx
    except ImportError:
        return {"error": "httpx not installed"}

    from gateway.platforms.signal_rate_limit import (
        SIGNAL_BATCH_PACING_NOTICE_THRESHOLD,
        SIGNAL_MAX_ATTACHMENTS_PER_MSG,
        SIGNAL_RATE_LIMIT_MAX_ATTEMPTS,
        _extract_retry_after_seconds,
        _format_wait,
        _is_signal_rate_limit_error,
        _signal_send_timeout,
        get_scheduler,
    )

    try:
        http_url = extra.get("http_url", "http://127.0.0.1:8080").rstrip("/")
        account = extra.get("account", "")
        if not account:
            return {"error": "Signal account not configured"}

        valid_media = media_files or []
        attachment_paths = []
        for media_path, _is_voice in valid_media:
            if os.path.exists(media_path):
                attachment_paths.append(media_path)
            else:
                logger.warning("Signal media file not found, skipping: %s", media_path)

        # Chunk attachments. With no attachments we still emit one batch
        # (text only). With attachments, the text rides on batch #0 so the
        # caption isn't repeated across every chunk.
        if attachment_paths:
            att_batches = [
                attachment_paths[i:i + SIGNAL_MAX_ATTACHMENTS_PER_MSG]
                for i in range(0, len(attachment_paths), SIGNAL_MAX_ATTACHMENTS_PER_MSG)
            ]
        else:
            att_batches = [[]]

        async def _post(batch_attachments, batch_message):
            params = {"account": account, "message": batch_message}
            if chat_id.startswith("group:"):
                params["groupId"] = chat_id[6:]
            else:
                params["recipient"] = [chat_id]
            if batch_attachments:
                params["attachments"] = batch_attachments

            payload = {
                "jsonrpc": "2.0",
                "method": "send",
                "params": params,
                "id": f"send_{int(time.time() * 1000)}",
            }
            timeout = _signal_send_timeout(len(batch_attachments) if batch_attachments else 0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{http_url}/api/v1/rpc", json=payload)
                resp.raise_for_status()
                return resp.json()

        async def _send_inline_notice(text: str) -> None:
            """Best-effort one-shot RPC for a user-facing pacing notice."""
            notice_params = {"account": account, "message": text}
            if chat_id.startswith("group:"):
                notice_params["groupId"] = chat_id[6:]
            else:
                notice_params["recipient"] = [chat_id]
            try:
                async with httpx.AsyncClient(timeout=30.0) as _client:
                    await _client.post(
                        f"{http_url}/api/v1/rpc",
                        json={
                            "jsonrpc": "2.0",
                            "method": "send",
                            "params": notice_params,
                            "id": f"notice_{int(time.time() * 1000)}",
                        },
                    )
            except Exception as _e:
                logger.warning("Signal: inline notice failed: %s", _e)

        scheduler = get_scheduler()
        logger.info(
            "send_message Signal: scheduler state=%s, %d attachment(s) in %d batch(es)",
            scheduler.state(), len(attachment_paths), len(att_batches),
        )
        failed_batches: list[int] = []
        for idx, att_batch in enumerate(att_batches):
            n = len(att_batch)
            if n > 0:
                estimated = scheduler.estimate_wait(n)
                if estimated >= SIGNAL_BATCH_PACING_NOTICE_THRESHOLD:
                    await _send_inline_notice(
                        f"(More images coming — pausing ~{_format_wait(estimated)} "
                        f"for Signal rate limit, batch {idx + 1}/{len(att_batches)}.)"
                    )

            batch_message = message if idx == 0 else ""

            for attempt in range(1, SIGNAL_RATE_LIMIT_MAX_ATTEMPTS + 1):
                try:
                    await scheduler.acquire(n)
                    _rpc_t0 = time.monotonic()
                    data = await _post(att_batch, batch_message)
                    _rpc_duration = time.monotonic() - _rpc_t0
                    if "error" not in data:
                        await scheduler.report_rpc_duration(_rpc_duration, n)
                        break

                    err = data["error"]

                    if not _is_signal_rate_limit_error(err):
                        return _error(f"Signal RPC error on batch {idx + 1}/{len(att_batches)}: {err}")

                    server_retry_after = _extract_retry_after_seconds(err)
                    scheduler.feedback(server_retry_after, n)

                    if attempt >= SIGNAL_RATE_LIMIT_MAX_ATTEMPTS:
                        failed_batches.append(idx + 1)
                        logger.error(
                            "Signal: rate-limit retries exhausted on batch %d/%d "
                            "(%d attachments lost, server retry_after=%s)",
                            idx + 1, len(att_batches), n,
                            f"{server_retry_after:.0f}s" if server_retry_after else "unknown",
                        )
                        break
                    logger.warning(
                        "Signal: rate-limited on batch %d/%d "
                        "(attempt %d/%d, server retry_after=%s); "
                        "scheduler will pace the retry",
                        idx + 1, len(att_batches),
                        attempt, SIGNAL_RATE_LIMIT_MAX_ATTEMPTS,
                        f"{server_retry_after:.0f}s" if server_retry_after else "unknown",
                    )
                except Exception as e:
                    if attempt >= SIGNAL_RATE_LIMIT_MAX_ATTEMPTS:
                        failed_batches.append(idx + 1)
                        logger.error(
                            "Signal: send error on batch %d/%d after %d attempts: %s",
                            idx + 1, len(att_batches), attempt, str(e)
                        )
                        break
                    logger.warning(
                        "Signal: transient error on batch %d/%d (attempt %d/%d): %s; will retry",
                        idx + 1, len(att_batches), attempt, SIGNAL_RATE_LIMIT_MAX_ATTEMPTS, str(e)
                    )

        warnings = []
        if len(attachment_paths) < len(valid_media):
            warnings.append("Some media files were skipped (not found on disk)")
        if failed_batches:
            warnings.append(
                f"Signal rate-limited {len(failed_batches)} batch(es) "
                f"(#{', #'.join(str(b) for b in failed_batches)})"
            )

        if failed_batches and len(failed_batches) == len(att_batches):
            return _error(
                f"Signal: every batch ({len(att_batches)}) hit rate limit; "
                f"no attachments delivered"
            )

        result = {"success": True, "platform": "signal", "chat_id": chat_id}
        if warnings:
            result["warnings"] = warnings
        return result
    except Exception as e:
        return _error(f"Signal send failed: {e}")


async def _send_email(extra, chat_id, message):
    """Send via SMTP (one-shot, no persistent connection needed)."""
    import smtplib
    from email.mime.text import MIMEText
    from email.utils import formatdate

    address = extra.get("address") or os.getenv("EMAIL_ADDRESS", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    smtp_host = extra.get("smtp_host") or os.getenv("EMAIL_SMTP_HOST", "")
    try:
        smtp_port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    except (ValueError, TypeError):
        smtp_port = 587

    if not all([address, password, smtp_host]):
        return {"error": "Email not configured (EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_SMTP_HOST required)"}

    try:
        msg = MIMEText(message, "plain", "utf-8")
        msg["From"] = address
        msg["To"] = chat_id
        msg["Subject"] = "Hermes Agent"
        msg["Date"] = formatdate(localtime=True)

        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls(context=ssl.create_default_context())
        server.login(address, password)
        server.send_message(msg)
        server.quit()
        return {"success": True, "platform": "email", "chat_id": chat_id}
    except Exception as e:
        return _error(f"Email send failed: {e}")


async def _send_sms(auth_token, chat_id, message):
    """Send a single SMS via Twilio REST API.

    Uses HTTP Basic auth (Account SID : Auth Token) and form-encoded POST.
    Chunking is handled by _send_to_platform() before this is called.
    """
    try:
        import aiohttp
    except ImportError:
        return {"error": "aiohttp not installed. Run: pip install aiohttp"}

    import base64

    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    from_number = os.getenv("TWILIO_PHONE_NUMBER", "")
    if not account_sid or not auth_token or not from_number:
        return {"error": "SMS not configured (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER required)"}

    # Strip markdown — SMS renders it as literal characters
    message = re.sub(r"\*\*(.+?)\*\*", r"\1", message, flags=re.DOTALL)
    message = re.sub(r"\*(.+?)\*", r"\1", message, flags=re.DOTALL)
    message = re.sub(r"__(.+?)__", r"\1", message, flags=re.DOTALL)
    message = re.sub(r"_(.+?)_", r"\1", message, flags=re.DOTALL)
    message = re.sub(r"```[a-z]*\n?", "", message)
    message = re.sub(r"`(.+?)`", r"\1", message)
    message = re.sub(r"^#{1,6}\s+", "", message, flags=re.MULTILINE)
    message = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", message)
    message = re.sub(r"\n{3,}", "\n\n", message)
    message = message.strip()

    try:
        from gateway.platforms.base import resolve_proxy_url, proxy_kwargs_for_aiohttp
        _proxy = resolve_proxy_url()
        _sess_kw, _req_kw = proxy_kwargs_for_aiohttp(_proxy)
        creds = f"{account_sid}:{auth_token}"
        encoded = base64.b64encode(creds.encode("ascii")).decode("ascii")
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        headers = {"Authorization": f"Basic {encoded}"}

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), **_sess_kw) as session:
            form_data = aiohttp.FormData()
            form_data.add_field("From", from_number)
            form_data.add_field("To", chat_id)
            form_data.add_field("Body", message)

            async with session.post(url, data=form_data, headers=headers, **_req_kw) as resp:
                body = await resp.json()
                if resp.status >= 400:
                    error_msg = body.get("message", str(body))
                    return _error(f"Twilio API error ({resp.status}): {error_msg}")
                msg_sid = body.get("sid", "")
                return {"success": True, "platform": "sms", "chat_id": chat_id, "message_id": msg_sid}
    except Exception as e:
        return _error(f"SMS send failed: {e}")


async def _send_mattermost(token, extra, chat_id, message):
    """Send via Mattermost REST API."""
    try:
        import aiohttp
    except ImportError:
        return {"error": "aiohttp not installed. Run: pip install aiohttp"}
    try:
        base_url = (extra.get("url") or os.getenv("MATTERMOST_URL", "")).rstrip("/")
        token = token or os.getenv("MATTERMOST_TOKEN", "")
        if not base_url or not token:
            return {"error": "Mattermost not configured (MATTERMOST_URL, MATTERMOST_TOKEN required)"}
        url = f"{base_url}/api/v4/posts"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(url, headers=headers, json={"channel_id": chat_id, "message": message}) as resp:
                if resp.status not in {200, 201}:
                    body = await resp.text()
                    return _error(f"Mattermost API error ({resp.status}): {body}")
                data = await resp.json()
        return {"success": True, "platform": "mattermost", "chat_id": chat_id, "message_id": data.get("id")}
    except Exception as e:
        return _error(f"Mattermost send failed: {e}")


async def _send_matrix(token, extra, chat_id, message):
    """Send via Matrix Client-Server API.

    Converts markdown to HTML for rich rendering in Matrix clients.
    Falls back to plain text if the ``markdown`` library is not installed.
    """
    try:
        import aiohttp
    except ImportError:
        return {"error": "aiohttp not installed. Run: pip install aiohttp"}
    try:
        homeserver = (extra.get("homeserver") or os.getenv("MATRIX_HOMESERVER", "")).rstrip("/")
        token = token or os.getenv("MATRIX_ACCESS_TOKEN", "")
        if not homeserver or not token:
            return {"error": "Matrix not configured (MATRIX_HOMESERVER, MATRIX_ACCESS_TOKEN required)"}
        txn_id = f"hermes_{int(time.time() * 1000)}_{os.urandom(4).hex()}"
        from urllib.parse import quote
        encoded_room = quote(chat_id, safe="")
        url = f"{homeserver}/_matrix/client/v3/rooms/{encoded_room}/send/m.room.message/{txn_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Build message payload with optional HTML formatted_body.
        payload = {"msgtype": "m.text", "body": message}
        try:
            import markdown as _md
            html = _md.markdown(message, extensions=["fenced_code", "tables"])
            # Convert h1-h6 to bold for Element X compatibility.
            html = re.sub(r"<h[1-6]>(.*?)</h[1-6]>", r"<strong>\1</strong>", html)
            payload["format"] = "org.matrix.custom.html"
            payload["formatted_body"] = html
        except ImportError:
            pass

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.put(url, headers=headers, json=payload) as resp:
                if resp.status not in {200, 201}:
                    body = await resp.text()
                    return _error(f"Matrix API error ({resp.status}): {body}")
                data = await resp.json()
        return {"success": True, "platform": "matrix", "chat_id": chat_id, "message_id": data.get("event_id")}
    except Exception as e:
        return _error(f"Matrix send failed: {e}")


async def _send_matrix_via_adapter(pconfig, chat_id, message, media_files=None, thread_id=None):
    """Send via the Matrix adapter so native Matrix media uploads are preserved."""
    try:
        from gateway.platforms.matrix import MatrixAdapter
    except ImportError:
        return {"error": "Matrix dependencies not installed. Run: pip install 'mautrix[encryption]'"}

    media_files = media_files or []

    try:
        adapter = MatrixAdapter(pconfig)
        connected = await adapter.connect()
        if not connected:
            return _error("Matrix connect failed")

        metadata = {"thread_id": thread_id} if thread_id else None
        last_result = None

        if message.strip():
            last_result = await adapter.send(chat_id, message, metadata=metadata)
            if not last_result.success:
                return _error(f"Matrix send failed: {last_result.error}")

        for media_path, is_voice in media_files:
            if not os.path.exists(media_path):
                return _error(f"Media file not found: {media_path}")

            ext = os.path.splitext(media_path)[1].lower()
            if ext in _IMAGE_EXTS:
                last_result = await adapter.send_image_file(chat_id, media_path, metadata=metadata)
            elif ext in _VIDEO_EXTS:
                last_result = await adapter.send_video(chat_id, media_path, metadata=metadata)
            elif ext in _VOICE_EXTS and is_voice:
                last_result = await adapter.send_voice(chat_id, media_path, metadata=metadata)
            elif ext in _AUDIO_EXTS:
                last_result = await adapter.send_voice(chat_id, media_path, metadata=metadata)
            else:
                last_result = await adapter.send_document(chat_id, media_path, metadata=metadata)

            if not last_result.success:
                return _error(f"Matrix media send failed: {last_result.error}")

        if last_result is None:
            return {"error": "No deliverable text or media remained after processing MEDIA tags"}

        return {
            "success": True,
            "platform": "matrix",
            "chat_id": chat_id,
            "message_id": last_result.message_id,
        }
    except Exception as e:
        return _error(f"Matrix send failed: {e}")
    finally:
        try:
            await adapter.disconnect()
        except Exception:
            pass


async def _send_homeassistant(token, extra, chat_id, message):
    """Send via Home Assistant notify service."""
    try:
        import aiohttp
    except ImportError:
        return {"error": "aiohttp not installed. Run: pip install aiohttp"}
    try:
        hass_url = (extra.get("url") or os.getenv("HASS_URL", "")).rstrip("/")
        token = token or os.getenv("HASS_TOKEN", "")
        if not hass_url or not token:
            return {"error": "Home Assistant not configured (HASS_URL, HASS_TOKEN required)"}
        url = f"{hass_url}/api/services/notify/notify"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(url, headers=headers, json={"message": message, "target": chat_id}) as resp:
                if resp.status not in {200, 201}:
                    body = await resp.text()
                    return _error(f"Home Assistant API error ({resp.status}): {body}")
        return {"success": True, "platform": "homeassistant", "chat_id": chat_id}
    except Exception as e:
        return _error(f"Home Assistant send failed: {e}")


async def _send_dingtalk(extra, chat_id, message):
    """Send via DingTalk robot webhook.

    Note: The gateway's DingTalk adapter uses per-session webhook URLs from
    incoming messages (dingtalk-stream SDK).  For cross-platform send_message
    delivery we use a static robot webhook URL instead, which must be
    configured via ``DINGTALK_WEBHOOK_URL`` env var or ``webhook_url`` in the
    platform's extra config.
    """
    try:
        import httpx
    except ImportError:
        return {"error": "httpx not installed"}
    try:
        webhook_url = extra.get("webhook_url") or os.getenv("DINGTALK_WEBHOOK_URL", "")
        if not webhook_url:
            return {"error": "DingTalk not configured. Set DINGTALK_WEBHOOK_URL env var or webhook_url in dingtalk platform extra config."}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                webhook_url,
                json={"msgtype": "text", "text": {"content": message}},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode", 0) != 0:
                return _error(f"DingTalk API error: {data.get('errmsg', 'unknown')}")
        return {"success": True, "platform": "dingtalk", "chat_id": chat_id}
    except Exception as e:
        return _error(f"DingTalk send failed: {e}")


async def _send_wecom(extra, chat_id, message):
    """Send via WeCom using the adapter's WebSocket send pipeline."""
    try:
        from gateway.platforms.wecom import WeComAdapter, check_wecom_requirements
        if not check_wecom_requirements():
            return {"error": "WeCom requirements not met. Need aiohttp + WECOM_BOT_ID/SECRET."}
    except ImportError:
        return {"error": "WeCom adapter not available."}

    try:
        from gateway.config import PlatformConfig
        pconfig = PlatformConfig(extra=extra)
        adapter = WeComAdapter(pconfig)
        connected = await adapter.connect()
        if not connected:
            return _error(f"WeCom: failed to connect - {adapter.fatal_error_message or 'unknown error'}")
        try:
            result = await adapter.send(chat_id, message)
            if not result.success:
                return _error(f"WeCom send failed: {result.error}")
            return {"success": True, "platform": "wecom", "chat_id": chat_id, "message_id": result.message_id}
        finally:
            await adapter.disconnect()
    except Exception as e:
        return _error(f"WeCom send failed: {e}")


async def _send_weixin(pconfig, chat_id, message, media_files=None):
    """Send via Weixin iLink using the native adapter helper."""
    try:
        from gateway.platforms.weixin import check_weixin_requirements, send_weixin_direct
        if not check_weixin_requirements():
            return {"error": "Weixin requirements not met. Need aiohttp + cryptography."}
    except ImportError:
        return {"error": "Weixin adapter not available."}

    try:
        return await send_weixin_direct(
            extra=pconfig.extra,
            token=pconfig.token,
            chat_id=chat_id,
            message=message,
            media_files=media_files,
        )
    except Exception as e:
        return _error(f"Weixin send failed: {e}")


async def _send_bluebubbles(extra, chat_id, message):
    """Send via BlueBubbles iMessage server using the adapter's REST API."""
    try:
        from gateway.platforms.bluebubbles import BlueBubblesAdapter, check_bluebubbles_requirements
        if not check_bluebubbles_requirements():
            return {"error": "BlueBubbles requirements not met (need aiohttp + httpx)."}
    except ImportError:
        return {"error": "BlueBubbles adapter not available."}

    try:
        from gateway.config import PlatformConfig
        pconfig = PlatformConfig(extra=extra)
        adapter = BlueBubblesAdapter(pconfig)
        connected = await adapter.connect()
        if not connected:
            return _error("BlueBubbles: failed to connect to server")
        try:
            result = await adapter.send(chat_id, message)
            if not result.success:
                return _error(f"BlueBubbles send failed: {result.error}")
            return {"success": True, "platform": "bluebubbles", "chat_id": chat_id, "message_id": result.message_id}
        finally:
            await adapter.disconnect()
    except Exception as e:
        return _error(f"BlueBubbles send failed: {e}")


async def _send_feishu(pconfig, chat_id, message, media_files=None, thread_id=None):
    """Send via Feishu/Lark using the adapter's send pipeline."""
    try:
        from gateway.platforms.feishu import FeishuAdapter, FEISHU_AVAILABLE
        if not FEISHU_AVAILABLE:
            return {"error": "Feishu dependencies not installed. Run: pip install 'hermes-agent[feishu]'"}
        from gateway.platforms.feishu import FEISHU_DOMAIN, LARK_DOMAIN
    except ImportError:
        return {"error": "Feishu dependencies not installed. Run: pip install 'hermes-agent[feishu]'"}

    media_files = media_files or []

    try:
        adapter = FeishuAdapter(pconfig)
        domain_name = getattr(adapter, "_domain_name", "feishu")
        domain = FEISHU_DOMAIN if domain_name != "lark" else LARK_DOMAIN
        adapter._client = adapter._build_lark_client(domain)
        metadata = {"thread_id": thread_id} if thread_id else None

        last_result = None
        if message.strip():
            last_result = await adapter.send(chat_id, message, metadata=metadata)
            if not last_result.success:
                return _error(f"Feishu send failed: {last_result.error}")

        for media_path, is_voice in media_files:
            if not os.path.exists(media_path):
                return _error(f"Media file not found: {media_path}")

            ext = os.path.splitext(media_path)[1].lower()
            if ext in _IMAGE_EXTS:
                last_result = await adapter.send_image_file(chat_id, media_path, metadata=metadata)
            elif ext in _VIDEO_EXTS:
                last_result = await adapter.send_video(chat_id, media_path, metadata=metadata)
            elif ext in _VOICE_EXTS and is_voice:
                last_result = await adapter.send_voice(chat_id, media_path, metadata=metadata)
            elif ext in _AUDIO_EXTS:
                last_result = await adapter.send_voice(chat_id, media_path, metadata=metadata)
            else:
                last_result = await adapter.send_document(chat_id, media_path, metadata=metadata)

            if not last_result.success:
                return _error(f"Feishu media send failed: {last_result.error}")

        if last_result is None:
            return {"error": "No deliverable text or media remained after processing MEDIA tags"}

        return {
            "success": True,
            "platform": "feishu",
            "chat_id": chat_id,
            "message_id": last_result.message_id,
        }
    except Exception as e:
        return _error(f"Feishu send failed: {e}")


def _check_send_message():
    """Gate send_message on gateway running (always available on messaging platforms).

    Also passes for kanban workers — the dispatcher sets ``HERMES_KANBAN_TASK``
    on every spawned worker, but those workers run with the assignee profile's
    ``HERMES_HOME`` which has no ``gateway.pid``, so the gateway-running check
    would fail even though the parent gateway is alive. Honoring the env var
    lets workers call ``send_message`` to deliver rich content directly to the
    originating chat (paired with ``kanban_complete`` for the short notifier
    summary), which is the canonical pattern for any worker that needs to
    reply with more than the ~200-char first-line truncation the kanban
    notifier applies.
    """
    if os.environ.get("HERMES_KANBAN_TASK"):
        return True
    from gateway.session_context import get_session_env
    platform = get_session_env("HERMES_SESSION_PLATFORM", "")
    if platform and platform != "local":
        return True
    try:
        from gateway.status import is_gateway_running
        return is_gateway_running()
    except Exception:
        return False


async def _send_qqbot(pconfig, chat_id, message):
    """Send via QQBot using the REST API directly (no WebSocket needed).

    Uses the QQ Bot Open Platform REST endpoints to get an access token
    and post a message. Supports guild channels, C2C (private) chats,
    and group chats by trying the appropriate endpoints.
    """
    try:
        import httpx
    except ImportError:
        return _error("QQBot direct send requires httpx. Run: pip install httpx")

    extra = pconfig.extra or {}
    appid = extra.get("app_id") or os.getenv("QQ_APP_ID", "")
    secret = (pconfig.token or extra.get("client_secret")
              or os.getenv("QQ_CLIENT_SECRET", ""))
    if not appid or not secret:
        return _error("QQBot: QQ_APP_ID / QQ_CLIENT_SECRET not configured.")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Step 1: Get access token
            token_resp = await client.post(
                "https://bots.qq.com/app/getAppAccessToken",
                json={"appId": str(appid), "clientSecret": str(secret)},
            )
            if token_resp.status_code != 200:
                return _error(f"QQBot token request failed: {token_resp.status_code}")
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                return _error(f"QQBot: no access_token in response")

            # Step 2: Send message via REST
            # QQ Bot API has separate endpoints for channels, C2C, and groups.
            # We try them in order: channel first, then fallback to C2C.
            headers = {
                "Authorization": f"QQBot {access_token}",
                "Content-Type": "application/json",
            }
            payload = {"content": message[:4000], "msg_type": 0}

            # Try channel endpoint first (works for guild channels)
            url = f"https://api.sgroup.qq.com/channels/{chat_id}/messages"
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code in {200, 201}:
                data = resp.json()
                return {"success": True, "platform": "qqbot", "chat_id": chat_id,
                        "message_id": data.get("id")}

            # If channel endpoint failed (likely "频道不存在"), try C2C endpoint
            url_c2c = f"https://api.sgroup.qq.com/v2/users/{chat_id}/messages"
            resp_c2c = await client.post(url_c2c, json=payload, headers=headers)
            if resp_c2c.status_code in {200, 201}:
                data = resp_c2c.json()
                return {"success": True, "platform": "qqbot", "chat_id": chat_id,
                        "message_id": data.get("id")}

            # If C2C also failed, try group endpoint
            url_group = f"https://api.sgroup.qq.com/v2/groups/{chat_id}/messages"
            resp_group = await client.post(url_group, json=payload, headers=headers)
            if resp_group.status_code in {200, 201}:
                data = resp_group.json()
                return {"success": True, "platform": "qqbot", "chat_id": chat_id,
                        "message_id": data.get("id")}

            # All endpoints failed — return the most informative error
            return _error(f"QQBot send failed: channel={resp.status_code} c2c={resp_c2c.status_code} group={resp_group.status_code}")
    except Exception as e:
        return _error(f"QQBot send failed: {e}")


async def _send_yuanbao(chat_id, message, media_files=None):
    """Send via Yuanbao using the running gateway adapter's WebSocket connection.

    Yuanbao uses a persistent WebSocket — unlike HTTP-based platforms, we
    cannot create a throwaway client.  We obtain the running singleton from
    the adapter module itself (``get_active_adapter``).

    chat_id format:
      - Group: "group:<group_code>"
      - DM:    "direct:<account_id>" or just "<account_id>"
    """
    try:
        from gateway.platforms.yuanbao import get_active_adapter, send_yuanbao_direct
    except ImportError:
        return _error("Yuanbao adapter module not available.")

    adapter = get_active_adapter()
    if adapter is None:
        return _error(
            "Yuanbao adapter is not running. "
            "Start the gateway with yuanbao platform enabled first."
        )

    try:
        return await send_yuanbao_direct(adapter, chat_id, message, media_files=media_files)
    except Exception as e:
        return _error(f"Yuanbao send failed: {e}")


# --- Registry ---
from tools.registry import registry, tool_error

registry.register(
    name="send_message",
    toolset="messaging",
    schema=SEND_MESSAGE_SCHEMA,
    handler=send_message_tool,
    check_fn=_check_send_message,
    emoji="📨",
)
