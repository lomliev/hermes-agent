#!/usr/bin/env python3
"""Exact structural safety contract for one Stage-C release transition.

The release updater must not turn a caller supplied boolean into evidence that
voice or public ingress is safe.  This module derives the only allowed service
cohorts and local readiness probes from the immutable production consumer
catalog.  The resulting self-hashed document is bound by the owner-signed
release-update plan and consumed by Stage 0 before any host mutation.

This module is deliberately data-only.  It does not inspect systemd, open a
socket, call a health endpoint, change Caddy, or start a service.  Those live
observations belong to the fixed root host-action backend, which must return
receipts matching this exact contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, NoReturn

from scripts.canary import production_release_consumer_inventory as inventory


RUNTIME_SAFETY_PLAN_SCHEMA = "muncho-production-release-runtime-safety-plan.v1"
VOICE_GUARD_RECEIPT_SCHEMA = "muncho-production-release-voice-guard.v1"
INGRESS_GATE_RECEIPT_SCHEMA = "muncho-production-release-ingress-gate.v1"
HEALTH_OBSERVATION_SCHEMA = "muncho-production-release-health-observation.v1"
SESSION_DRAIN_RECEIPT_SCHEMA = (
    "muncho-production-release-session-drain-receipt.v1"
)

GATEWAY_UNIT = "hermes-cloud-gateway.service"
CONNECTOR_UNIT = "muncho-discord-connector.service"
WRITER_UNIT = "muncho-canonical-writer.service"
BROWSER_UNIT = "muncho-capability-browser.service"
ROUTEBACK_UNIT = "muncho-discord-egress.service"
ISOLATED_WORKER_UNIT = "muncho-isolated-worker.service"
MAC_OPS_UNIT = "muncho-mac-ops-edge.service"
PHASE_B_READINESS_UNIT = "muncho-canonical-writer-phase-b-readiness.service"
PUBLIC_INGRESS_SERVICE_UNITS = (CONNECTOR_UNIT, GATEWAY_UNIT)

VOICE_CALL_GUARD_PATH = (
    "/opt/adventico-ai-platform/canonical-brain/state/runtime/"
    "voice-skyai-active-calls.json"
)
VOICE_CALL_LEASE_TOOL_PATH = (
    "/opt/adventico-ai-platform/hermes-home/bin/voice-skyai-call-lease"
)
GATEWAY_RUNTIME_STATUS_PATH = (
    "/opt/adventico-ai-platform/hermes-home/gateway_state.json"
)
CONNECTOR_SOCKET_PATH = "/run/muncho-discord-connector/connector.sock"
CONNECTOR_READINESS_PATH = "/run/muncho-discord-connector/readiness.json"
GATEWAY_READINESS_PATH = (
    "/run/hermes-cloud-gateway/canonical-writer-readiness.json"
)
WRITER_SOCKET_PATH = "/run/muncho-canonical-writer/writer.sock"
WRITER_ATTESTATION_PATH = (
    "/run/muncho-canonical-writer/runtime-attestation.json"
)
BROWSER_SOCKET_PATH = "/run/muncho-browser-controller/controller.sock"
ROUTEBACK_SOCKET_PATH = "/run/muncho-discord-egress/edge.sock"
ROUTEBACK_READINESS_PATH = "/run/muncho-discord-egress/runtime-attestation.json"
ISOLATED_WORKER_SOCKET_PATH = "/run/muncho-isolated-worker/worker.sock"
MAC_OPS_SOCKET_PATH = "/run/muncho-mac-ops/edge.sock"
OPERATIONAL_EDGE_READINESS_PATH = (
    "/var/lib/muncho-operational-edge/readiness.json"
)
PHASE_B_RECEIPT_PATH = (
    "/var/lib/muncho/canonical-writer-phase-b/runtime-receipt.json"
)

CADDY_CONTROLLER_MODULE = "scripts.canary.owner_gate_caddy_cutover"
CADDY_PUBLIC_HOST = "auth.lomliev.com"
CADDY_PUBLIC_PATH = "/readyz"
CADDY_MAINTENANCE_RECEIPT_SCHEMA = (
    "muncho-owner-gate-caddy-cutover-maintenance-observation.v1"
)
CADDY_TERMINAL_RECEIPT_SCHEMA = (
    "muncho-owner-gate-caddy-cutover-terminal.v1"
)

_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = frozenset(
    {
        "schema",
        "predecessor_revision",
        "release_revision",
        "release_consumer_set_sha256",
        "consumer_catalog_sha256",
        "service_operation_classes",
        "protected_voice_service_units",
        "public_ingress_service_units",
        "precommit_long_running_service_units",
        "postcommit_public_start_order",
        "startup_oneshot_service_units",
        "precommit_disabled_trigger_units",
        "postcommit_enabled_trigger_units",
        "voice_guard_probes",
        "precommit_health_probes",
        "postcommit_health_probes",
        "session_drain",
        "external_ingress_gate",
        "secret_material_recorded",
        "secret_digest_recorded",
        "runtime_safety_plan_sha256",
    }
)


class ProductionReleaseRuntimeSafetyError(ValueError):
    """Stable failure at the signed structural runtime-safety boundary."""


def _fail(code: str) -> NoReturn:
    raise ProductionReleaseRuntimeSafetyError(code) from None


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii", errors="strict")
    except (TypeError, ValueError, UnicodeError):
        _fail("release_runtime_safety_json_invalid")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _revision(value: Any) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        _fail("release_runtime_safety_plan_invalid")
    return value


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail("release_runtime_safety_plan_invalid")
    return value


def _long_running_units() -> list[str]:
    catalog = inventory.expected_consumer_catalog()
    units = sorted(
        name
        for name, spec in catalog.items()
        if spec.activation_class == inventory.ACTIVATION_CLASS_LONG_RUNNING
    )
    if len(units) != inventory.EXPECTED_LONG_RUNNING_SERVICE_COUNT:
        _fail("release_runtime_safety_catalog_invalid")
    return units


def _trigger_units() -> list[str]:
    catalog = inventory.expected_consumer_catalog()
    units = sorted(
        name for name, spec in catalog.items() if spec.kind in {"socket", "timer"}
    )
    if len(units) != inventory.EXPECTED_TRIGGER_UNIT_COUNT:
        _fail("release_runtime_safety_catalog_invalid")
    return units


def _startup_oneshot_units() -> list[str]:
    catalog = inventory.expected_consumer_catalog()
    units = sorted(
        name
        for name, spec in catalog.items()
        if spec.activation_class == inventory.ACTIVATION_CLASS_STARTUP_ONESHOT
    )
    if units != [PHASE_B_READINESS_UNIT]:
        _fail("release_runtime_safety_catalog_invalid")
    return units


def _operational_edge_units() -> list[str]:
    units = sorted(
        name
        for name in _long_running_units()
        if name.startswith("muncho-operational-edge-")
    )
    if len(units) != 11:
        _fail("release_runtime_safety_catalog_invalid")
    return units


def _service_operation_classes() -> dict[str, str]:
    """Return the closed, source-derived network/authority class per service."""

    classes = {
        GATEWAY_UNIT: "public_ingress_voice_and_text",
        CONNECTOR_UNIT: "ordinary_public_ingress_and_session_replies",
        WRITER_UNIT: "local_privileged_state_authority",
        BROWSER_UNIT: "local_capability_controller",
        ROUTEBACK_UNIT: "outbound_only_routeback",
        ISOLATED_WORKER_UNIT: "local_isolated_execution",
        MAC_OPS_UNIT: "local_mac_operations_edge",
        **{
            unit: "local_operational_edge"
            for unit in _operational_edge_units()
        },
    }
    if sorted(classes) != _long_running_units():
        _fail("release_runtime_safety_catalog_invalid")
    return dict(sorted(classes.items()))


def _probe(
    *,
    name: str,
    service_units: list[str],
    probe_kind: str,
    path: str,
    expected_contract: str,
    operation: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "service_units": service_units,
        "probe_kind": probe_kind,
        "path": path,
        "expected_contract": expected_contract,
        "operation": operation,
        "requires_current_boot": True,
        "requires_target_revision": True,
        "requires_live_peer_identity": True,
    }


def _voice_guard_probes() -> list[dict[str, Any]]:
    return [
        {
            **_probe(
                name="gateway_voice_call_lease_guard",
                service_units=[GATEWAY_UNIT],
                probe_kind="root_collected_voice_call_lease_status",
                path=VOICE_CALL_GUARD_PATH,
                expected_contract="voice-skyai-active-calls-status.v1",
                operation="status --json",
            ),
            "lease_tool_path": VOICE_CALL_LEASE_TOOL_PATH,
            "bypass_allowed": False,
            "receipt_schema": VOICE_GUARD_RECEIPT_SCHEMA,
        }
    ]


def _precommit_health_probes() -> list[dict[str, Any]]:
    return [
        _probe(
            name="canonical_writer_ping",
            service_units=[WRITER_UNIT],
            probe_kind="unix_request_response",
            path=WRITER_SOCKET_PATH,
            expected_contract="canonical-writer.v1",
            operation="ping",
        ),
        _probe(
            name="canonical_writer_runtime_attestation",
            service_units=[WRITER_UNIT],
            probe_kind="runtime_attestation",
            path=WRITER_ATTESTATION_PATH,
            expected_contract="canonical-writer-runtime-attestation-v2",
            operation="validate",
        ),
        _probe(
            name="browser_controller_socket",
            service_units=[BROWSER_UNIT],
            probe_kind="systemd_notify_unix_socket",
            path=BROWSER_SOCKET_PATH,
            expected_contract="hermes-browser-controller-ready-v1",
            operation="peer_connect",
        ),
        _probe(
            name="discord_routeback_readiness",
            service_units=[ROUTEBACK_UNIT],
            probe_kind="signed_runtime_attestation_and_unix_socket",
            path=ROUTEBACK_READINESS_PATH,
            expected_contract="muncho-discord-edge-readiness-v1",
            operation="validate_signed_local_routeback",
        ),
        _probe(
            name="isolated_worker_socket",
            service_units=[ISOLATED_WORKER_UNIT],
            probe_kind="unix_request_response",
            path=ISOLATED_WORKER_SOCKET_PATH,
            expected_contract="muncho.isolated-worker.v1",
            operation="proof.status",
        ),
        _probe(
            name="mac_ops_ping",
            service_units=[MAC_OPS_UNIT],
            probe_kind="unix_request_response",
            path=MAC_OPS_SOCKET_PATH,
            expected_contract="muncho-mac-ops-edge.v1",
            operation="ping",
        ),
        _probe(
            name="operational_edge_aggregate",
            service_units=_operational_edge_units(),
            probe_kind="root_collected_socket_round_trip_receipt",
            path=OPERATIONAL_EDGE_READINESS_PATH,
            expected_contract="muncho-operational-edge-readiness.v2",
            operation="validate_all_required_jobs_ready",
        ),
        _probe(
            name="phase_b_readiness",
            service_units=[PHASE_B_READINESS_UNIT],
            probe_kind="root_owned_terminal_receipt",
            path=PHASE_B_RECEIPT_PATH,
            expected_contract=(
                "muncho-canonical-writer-foundation-phase-b-readiness.v1"
            ),
            operation="validate_all_17_public_routines",
        ),
    ]


def _postcommit_health_probes() -> list[dict[str, Any]]:
    return [
        _probe(
            name="discord_public_connector_readiness",
            service_units=[CONNECTOR_UNIT],
            probe_kind="discord_gateway_and_unix_socket_readiness",
            path=CONNECTOR_READINESS_PATH,
            expected_contract="muncho-discord-public-connector-readiness.v2",
            operation="validate_public_targets_and_clean_journal",
        ),
        _probe(
            name="gateway_writer_readiness",
            service_units=[GATEWAY_UNIT],
            probe_kind="gateway_process_bound_writer_ping_receipt",
            path=GATEWAY_READINESS_PATH,
            expected_contract="canonical-writer-readiness-v1",
            operation="validate",
        ),
        _probe(
            name="gateway_loopback_health",
            service_units=[GATEWAY_UNIT],
            probe_kind="loopback_http_get",
            path="http://127.0.0.1:8642/health",
            expected_contract="gateway.api_server.GET./health",
            operation="GET",
        ),
    ]


def _session_drain() -> dict[str, Any]:
    return {
        "schema": SESSION_DRAIN_RECEIPT_SCHEMA,
        "public_ingress_service_units": list(
            PUBLIC_INGRESS_SERVICE_UNITS
        ),
        "gateway": {
            "service_unit": GATEWAY_UNIT,
            "runtime_status_path": GATEWAY_RUNTIME_STATUS_PATH,
            "required_gateway_state_before_stop": "draining",
            "required_active_agents": 0,
            "required_active_session_keys": [],
            "runtime_status_contract": "gateway.status.gateway_state.json",
        },
        "connector": {
            "service_unit": CONNECTOR_UNIT,
            "socket_path": CONNECTOR_SOCKET_PATH,
            "shutdown_contract": (
                "listener_closed_then_live_request_handler_set_empty"
            ),
            "maximum_request_drain_seconds": 45,
            "required_socket_state_after_stop": "absent",
        },
        "receipt_path_template": (
            "$TRANSACTION_ROOT/session-drain-receipt.json"
        ),
        "receipt_requires_current_boot": True,
        "receipt_requires_target_intent": True,
        "caller_boolean_accepted": False,
    }


def _external_ingress_gate() -> dict[str, Any]:
    return {
        "schema": INGRESS_GATE_RECEIPT_SCHEMA,
        "public_ingress_service_units": [CONNECTOR_UNIT, GATEWAY_UNIT],
        "precommit_required_active_state": "inactive",
        "precommit_required_readiness_paths_absent": [
            CONNECTOR_READINESS_PATH,
            GATEWAY_READINESS_PATH,
        ],
        "precommit_session_drain_receipt_schema": (
            SESSION_DRAIN_RECEIPT_SCHEMA
        ),
        "precommit_session_drain_receipt_path_template": (
            "$TRANSACTION_ROOT/session-drain-receipt.json"
        ),
        "precommit_caddy_controller_module": CADDY_CONTROLLER_MODULE,
        "precommit_caddy_receipt_schema": CADDY_MAINTENANCE_RECEIPT_SCHEMA,
        "precommit_caddy_expected_outcome": "maintenance",
        "precommit_caddy_expected_status": 503,
        "postcommit_start_order": [CONNECTOR_UNIT, GATEWAY_UNIT],
        "postcommit_caddy_controller_module": CADDY_CONTROLLER_MODULE,
        "postcommit_caddy_receipt_schema": CADDY_TERMINAL_RECEIPT_SCHEMA,
        "postcommit_caddy_expected_outcome": "private_v2_active",
        "postcommit_caddy_expected_status": 200,
        "caddy_public_host": CADDY_PUBLIC_HOST,
        "caddy_public_path": CADDY_PUBLIC_PATH,
        "transaction_phase_order": [
            "precommit_gate_intent",
            "precommit_gate_applied",
            "precommit_gate_readback",
            "postcommit_gate_intent",
            "postcommit_gate_applied",
            "postcommit_gate_readback",
        ],
        "precommit_crash_policy": "restore_exact_predecessor_ingress",
        "postcommit_crash_policy": "forward_only_target_or_maintenance",
        "caller_boolean_accepted": False,
    }


def build_runtime_safety_plan(
    *,
    predecessor_revision: str,
    release_revision: str,
    release_consumer_set_sha256: str,
    consumer_catalog_sha256: str,
) -> Mapping[str, Any]:
    """Build the one exact safety plan allowed for the current catalog."""

    predecessor = _revision(predecessor_revision)
    release = _revision(release_revision)
    consumer_set = _sha256(release_consumer_set_sha256)
    catalog_sha = _sha256(consumer_catalog_sha256)
    if predecessor == release or predecessor[:12] == release[:12]:
        _fail("release_runtime_safety_plan_invalid")

    long_running = _long_running_units()
    public_ingress = list(PUBLIC_INGRESS_SERVICE_UNITS)
    precommit = sorted(set(long_running).difference(public_ingress))
    if (
        len(precommit) != 16
        or set(precommit).intersection(public_ingress)
        or sorted(precommit + public_ingress) != long_running
    ):
        _fail("release_runtime_safety_catalog_invalid")

    unsigned = {
        "schema": RUNTIME_SAFETY_PLAN_SCHEMA,
        "predecessor_revision": predecessor,
        "release_revision": release,
        "release_consumer_set_sha256": consumer_set,
        "consumer_catalog_sha256": catalog_sha,
        "service_operation_classes": _service_operation_classes(),
        "protected_voice_service_units": [GATEWAY_UNIT],
        "public_ingress_service_units": public_ingress,
        "precommit_long_running_service_units": precommit,
        "postcommit_public_start_order": [CONNECTOR_UNIT, GATEWAY_UNIT],
        "startup_oneshot_service_units": _startup_oneshot_units(),
        "precommit_disabled_trigger_units": _trigger_units(),
        "postcommit_enabled_trigger_units": _trigger_units(),
        "voice_guard_probes": _voice_guard_probes(),
        "precommit_health_probes": _precommit_health_probes(),
        "postcommit_health_probes": _postcommit_health_probes(),
        "session_drain": _session_drain(),
        "external_ingress_gate": _external_ingress_gate(),
        "secret_material_recorded": False,
        "secret_digest_recorded": False,
    }
    return {
        **unsigned,
        "runtime_safety_plan_sha256": sha256_bytes(canonical_bytes(unsigned)),
    }


def validate_runtime_safety_plan(
    value: Any,
    *,
    predecessor_revision: str,
    release_revision: str,
    release_consumer_set: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate exact cohorts, probes, ingress transaction, and bindings."""

    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        _fail("release_runtime_safety_plan_invalid")
    raw = dict(value)
    digest = _sha256(raw.get("runtime_safety_plan_sha256"))
    unsigned = {
        name: item
        for name, item in raw.items()
        if name != "runtime_safety_plan_sha256"
    }
    if digest != sha256_bytes(canonical_bytes(unsigned)):
        _fail("release_runtime_safety_plan_invalid")
    if not isinstance(release_consumer_set, Mapping):
        _fail("release_runtime_safety_consumer_set_invalid")
    expected = build_runtime_safety_plan(
        predecessor_revision=predecessor_revision,
        release_revision=release_revision,
        release_consumer_set_sha256=_sha256(
            release_consumer_set.get("consumer_set_sha256")
        ),
        consumer_catalog_sha256=_sha256(
            release_consumer_set.get("catalog_sha256")
        ),
    )
    if raw != expected:
        _fail("release_runtime_safety_plan_invalid")
    return raw


__all__ = [
    "GATEWAY_UNIT",
    "CONNECTOR_UNIT",
    "HEALTH_OBSERVATION_SCHEMA",
    "INGRESS_GATE_RECEIPT_SCHEMA",
    "ProductionReleaseRuntimeSafetyError",
    "PUBLIC_INGRESS_SERVICE_UNITS",
    "RUNTIME_SAFETY_PLAN_SCHEMA",
    "SESSION_DRAIN_RECEIPT_SCHEMA",
    "VOICE_CALL_GUARD_PATH",
    "VOICE_CALL_LEASE_TOOL_PATH",
    "VOICE_GUARD_RECEIPT_SCHEMA",
    "build_runtime_safety_plan",
    "validate_runtime_safety_plan",
]
