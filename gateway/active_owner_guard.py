"""Active-owner guard for split-brain gateway prevention.

This guard is intentionally opt-in.  It is used by operational deployments
that run more than one possible Hermes gateway runtime for the same bot
identity, where only one runtime should answer user messages at a time.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActiveOwnerGuardConfig:
    """Resolved active-owner guard settings."""

    enabled: bool = False
    runtime_id: str = ""
    state_path: Path | None = None
    fail_closed: bool = True


@dataclass(frozen=True)
class ActiveOwnerGuardDecision:
    """Decision returned by the active-owner guard."""

    allowed: bool
    reason: str
    runtime_id: str = ""
    active_owner: str = ""
    state_path: str = ""

    def log_message(self) -> str:
        parts = [self.reason]
        if self.runtime_id:
            parts.append(f"runtime={self.runtime_id}")
        if self.active_owner:
            parts.append(f"active_owner={self.active_owner}")
        if self.state_path:
            parts.append(f"state_path={self.state_path}")
        return "; ".join(parts)


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


def _default_state_path() -> Path:
    return get_hermes_home() / "state" / "muncho-active-owner.json"


def _normalise_owner(value: Any) -> str:
    return str(value or "").strip().lower()


def resolve_active_owner_guard_config(platform_config: Any) -> ActiveOwnerGuardConfig:
    """Resolve guard settings from a platform config's ``extra`` mapping.

    Supported shape:

    ``active_owner_guard: {enabled: true, runtime_id: "cloud", state_path: "..."}``

    ``muncho_active_owner_guard`` is accepted as an alias for existing
    operational overlays that prefer a more explicit key.
    """

    extra = getattr(platform_config, "extra", {}) or {}
    if not isinstance(extra, Mapping):
        return ActiveOwnerGuardConfig()

    raw = extra.get("active_owner_guard")
    if raw is None:
        raw = extra.get("muncho_active_owner_guard")
    if raw is None:
        return ActiveOwnerGuardConfig()

    if isinstance(raw, Mapping):
        enabled = _coerce_bool(raw.get("enabled"), False)
        runtime_id = _normalise_owner(
            raw.get("runtime_id") or raw.get("node_id") or raw.get("owner_id")
        )
        state_raw = raw.get("state_path")
        state_path = Path(str(state_raw)).expanduser() if state_raw else None
        fail_closed = _coerce_bool(raw.get("fail_closed"), True)
        return ActiveOwnerGuardConfig(
            enabled=enabled,
            runtime_id=runtime_id,
            state_path=state_path,
            fail_closed=fail_closed,
        )

    enabled = _coerce_bool(raw, False)
    return ActiveOwnerGuardConfig(enabled=enabled)


def check_active_owner(platform_config: Any) -> ActiveOwnerGuardDecision:
    """Return whether this gateway runtime may start processing a message."""

    cfg = resolve_active_owner_guard_config(platform_config)
    if not cfg.enabled:
        return ActiveOwnerGuardDecision(True, "active-owner guard disabled")

    state_path = cfg.state_path or _default_state_path()
    state_path_str = str(state_path)

    if not cfg.runtime_id:
        return ActiveOwnerGuardDecision(
            allowed=not cfg.fail_closed,
            reason="active-owner guard missing runtime_id",
            state_path=state_path_str,
        )

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ActiveOwnerGuardDecision(
            allowed=not cfg.fail_closed,
            reason="active-owner state file missing",
            runtime_id=cfg.runtime_id,
            state_path=state_path_str,
        )
    except Exception as exc:
        return ActiveOwnerGuardDecision(
            allowed=not cfg.fail_closed,
            reason=f"active-owner state unreadable: {exc}",
            runtime_id=cfg.runtime_id,
            state_path=state_path_str,
        )

    active_owner = _normalise_owner(
        state.get("active_owner") or state.get("owner") or state.get("desired_owner")
    )
    if not active_owner:
        return ActiveOwnerGuardDecision(
            allowed=not cfg.fail_closed,
            reason="active-owner state has no active_owner",
            runtime_id=cfg.runtime_id,
            state_path=state_path_str,
        )

    if active_owner == cfg.runtime_id:
        return ActiveOwnerGuardDecision(
            True,
            "active owner matches runtime",
            runtime_id=cfg.runtime_id,
            active_owner=active_owner,
            state_path=state_path_str,
        )

    return ActiveOwnerGuardDecision(
        False,
        "active owner does not match this runtime",
        runtime_id=cfg.runtime_id,
        active_owner=active_owner,
        state_path=state_path_str,
    )


def should_start_gateway_message(platform_config: Any) -> bool:
    """Return True when the current runtime may start a gateway turn."""

    decision = check_active_owner(platform_config)
    if decision.allowed:
        return True
    logger.warning("Active-owner guard blocked inbound gateway message: %s", decision.log_message())
    return False
