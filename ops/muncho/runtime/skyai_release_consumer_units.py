#!/usr/bin/env python3
"""Render the release-pinned SkyAI cloud consumer service and timer.

This is a pure renderer.  Provisioning the service identity, public signing
key, or systemd files remains an explicit global-security bootstrap action.
Once bootstrapped, ordinary SkyAI releases require no workstation, passkey,
SSH session, or long-lived human credential.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


BUNDLE_SCHEMA = "skyai-cloud-release-consumer-unit-bundle.v1"
SERVICE_UNIT = "skyai-cloud-release-consumer.service"
TIMER_UNIT = "skyai-cloud-release-consumer.timer"
INSTALL_ROOT = Path("/opt/skyai-release-consumer")
PUBLIC_KEY_FILE = Path("/etc/skyai/skyai-release-signing-public.pem")
SKYAI_ROOT = Path("/opt/skyai-v2")
SKYAI_ENV = Path("/etc/skyai/skyai-v2-prod.env")

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SkyAIConsumerUnitError(ValueError):
    pass


@dataclass(frozen=True)
class SkyAIConsumerUnitBundle:
    revision: str
    release_root: Path
    units: Mapping[str, bytes]
    manifest: Mapping[str, Any]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _service(revision: str, release: Path) -> bytes:
    interpreter = SKYAI_ROOT / "venv/bin/python"
    lines = [
        "# Signed cloud release consumer. Generated; do not edit.",
        f"# ReleaseRevision={revision}",
        "[Unit]",
        "Description=Consume one signed immutable SkyAI production release",
        "After=network-online.target skyai-v2-hermes-prod.service",
        "Wants=network-online.target",
        f"AssertPathExists={interpreter}",
        f"AssertPathExists={release / 'ops/muncho/runtime/skyai_release_consumer.py'}",
        f"AssertPathExists={release / 'ops/muncho/runtime/cloud_release_contract.py'}",
        f"AssertPathExists={PUBLIC_KEY_FILE}",
        f"AssertPathExists={SKYAI_ENV}",
        "",
        "[Service]",
        "Type=oneshot",
        "User=root",
        "Group=root",
        f"WorkingDirectory={release}",
        (
            f"ExecStart={interpreter} -I -B "
            f"{release / 'ops/muncho/runtime/skyai_release_consumer.py'} "
            "run-once"
        ),
        "TimeoutStartSec=15min",
        "RuntimeDirectory=skyai-release-consumer",
        "RuntimeDirectoryMode=0700",
        "StateDirectory=skyai-release-consumer",
        "StateDirectoryMode=0700",
        "Environment=HOME=/var/lib/skyai-release-consumer",
        "Environment=LANG=C.UTF-8",
        "Environment=LC_ALL=C.UTF-8",
        "Environment=PATH=/usr/bin:/bin",
        "Environment=PYTHONDONTWRITEBYTECODE=1",
        "Environment=PYTHONNOUSERSITE=1",
        "Environment=TZ=UTC",
        "UnsetEnvironment=PYTHONPATH PYTHONHOME BASH_ENV ENV CDPATH",
        "NoNewPrivileges=yes",
        "CapabilityBoundingSet=CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER",
        "AmbientCapabilities=",
        "LockPersonality=yes",
        "PrivateDevices=yes",
        "PrivateTmp=yes",
        "ProtectClock=yes",
        "ProtectControlGroups=yes",
        "ProtectHome=yes",
        "ProtectHostname=yes",
        "ProtectKernelLogs=yes",
        "ProtectKernelModules=yes",
        "ProtectKernelTunables=yes",
        "ProtectProc=invisible",
        "ProtectSystem=strict",
        "RemoveIPC=yes",
        "RestrictNamespaces=yes",
        "RestrictRealtime=yes",
        "RestrictSUIDSGID=yes",
        "SystemCallArchitectures=native",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "UMask=0077",
        f"ReadOnlyPaths={release}",
        f"ReadOnlyPaths={PUBLIC_KEY_FILE}",
        f"ReadWritePaths={SKYAI_ROOT}",
        f"ReadWritePaths={SKYAI_ENV}",
        "ReadWritePaths=/var/lib/skyai-release-consumer",
        "ReadWritePaths=/run/skyai-release-consumer",
        "StandardInput=null",
        "StandardOutput=journal",
        "StandardError=journal",
        "",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _timer(revision: str) -> bytes:
    lines = [
        "# Signed cloud release consumer timer. Generated; do not edit.",
        f"# ReleaseRevision={revision}",
        "[Unit]",
        "Description=Poll for signed SkyAI releases every five minutes",
        "",
        "[Timer]",
        "OnBootSec=3min",
        "OnUnitActiveSec=5min",
        "RandomizedDelaySec=30s",
        "AccuracySec=15s",
        "Persistent=true",
        f"Unit={SERVICE_UNIT}",
        "",
        "[Install]",
        "WantedBy=timers.target",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def render_skyai_consumer_units(
    *, revision: str, signing_public_key_id: str
) -> SkyAIConsumerUnitBundle:
    if (
        _SHA40.fullmatch(revision or "") is None
        or _SHA256.fullmatch(signing_public_key_id or "") is None
    ):
        raise SkyAIConsumerUnitError("skyai_consumer_identity_invalid")
    release = INSTALL_ROOT / "releases" / revision
    units = {
        SERVICE_UNIT: _service(revision, release),
        TIMER_UNIT: _timer(revision),
    }
    for name, raw in units.items():
        text = raw.decode("utf-8")
        if text.count(f"# ReleaseRevision={revision}\n") != 1:
            raise SkyAIConsumerUnitError("skyai_consumer_unit_drift")
        if name == SERVICE_UNIT and (
            text.count("ExecStart=") != 1
            or "EnvironmentFile=" in text
            or "PassEnvironment=" in text
            or "ProtectSystem=strict\n" not in text
            or "NoNewPrivileges=yes\n" not in text
        ):
            raise SkyAIConsumerUnitError("skyai_consumer_unit_drift")
    unsigned = {
        "schema": BUNDLE_SCHEMA,
        "revision": revision,
        "release_root": str(release),
        "signing_public_key_id": signing_public_key_id,
        "personal_mac_required_for_routine_releases": False,
        "poll_interval_seconds": 5 * 60,
        "maximum_queue_to_deploy_seconds": 24 * 60 * 60,
        "units": {name: _sha256(raw) for name, raw in units.items()},
    }
    manifest = {**unsigned, "bundle_sha256": _sha256(_canonical(unsigned))}
    return SkyAIConsumerUnitBundle(
        revision=revision,
        release_root=release,
        units=units,
        manifest=manifest,
    )


__all__ = [
    "BUNDLE_SCHEMA",
    "INSTALL_ROOT",
    "PUBLIC_KEY_FILE",
    "SERVICE_UNIT",
    "TIMER_UNIT",
    "SkyAIConsumerUnitBundle",
    "SkyAIConsumerUnitError",
    "render_skyai_consumer_units",
]
