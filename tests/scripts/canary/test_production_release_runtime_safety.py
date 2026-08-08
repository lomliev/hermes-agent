from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.canary import production_release_consumer_inventory as inventory
from scripts.canary import production_release_runtime_safety as safety


PREDECESSOR = "1" * 40
TARGET = "2" * 40
CONSUMER_SET_SHA256 = "3" * 64
CATALOG_SHA256 = "4" * 64


def _plan() -> dict[str, object]:
    return dict(
        safety.build_runtime_safety_plan(
            predecessor_revision=PREDECESSOR,
            release_revision=TARGET,
            release_consumer_set_sha256=CONSUMER_SET_SHA256,
            consumer_catalog_sha256=CATALOG_SHA256,
        )
    )


def _consumer_set() -> dict[str, str]:
    return {
        "consumer_set_sha256": CONSUMER_SET_SHA256,
        "catalog_sha256": CATALOG_SHA256,
    }


def _rehash(plan: dict[str, object]) -> None:
    unsigned = {
        name: item
        for name, item in plan.items()
        if name != "runtime_safety_plan_sha256"
    }
    plan["runtime_safety_plan_sha256"] = safety.sha256_bytes(
        safety.canonical_bytes(unsigned)
    )


def test_runtime_safety_plan_binds_exact_structural_cohorts() -> None:
    plan = _plan()
    long_running = sorted(
        name
        for name, spec in inventory.expected_consumer_catalog().items()
        if spec.activation_class == inventory.ACTIVATION_CLASS_LONG_RUNNING
    )

    assert plan["protected_voice_service_units"] == [safety.GATEWAY_UNIT]
    assert plan["public_ingress_service_units"] == [
        safety.CONNECTOR_UNIT,
        safety.GATEWAY_UNIT,
    ]
    assert plan["postcommit_public_start_order"] == [
        safety.CONNECTOR_UNIT,
        safety.GATEWAY_UNIT,
    ]
    assert len(plan["precommit_long_running_service_units"]) == 16
    assert sorted(
        plan["precommit_long_running_service_units"]
        + plan["public_ingress_service_units"]
    ) == long_running
    assert len(plan["precommit_disabled_trigger_units"]) == 30
    assert plan["postcommit_enabled_trigger_units"] == plan[
        "precommit_disabled_trigger_units"
    ]
    assert plan["startup_oneshot_service_units"] == [
        safety.PHASE_B_READINESS_UNIT
    ]
    assert plan["service_operation_classes"][safety.CONNECTOR_UNIT] == (
        "ordinary_public_ingress_and_session_replies"
    )
    assert plan["service_operation_classes"][safety.GATEWAY_UNIT] == (
        "public_ingress_voice_and_text"
    )
    assert plan["service_operation_classes"][
        "muncho-discord-egress.service"
    ] == "outbound_only_routeback"


def test_runtime_safety_plan_separates_voice_from_public_ingress() -> None:
    plan = _plan()
    assert safety.CONNECTOR_UNIT in plan["public_ingress_service_units"]
    assert safety.CONNECTOR_UNIT not in plan["protected_voice_service_units"]
    assert plan["voice_guard_probes"] == [
        {
            "name": "gateway_voice_call_lease_guard",
            "service_units": [safety.GATEWAY_UNIT],
            "probe_kind": "root_collected_voice_call_lease_status",
            "path": safety.VOICE_CALL_GUARD_PATH,
            "expected_contract": "voice-skyai-active-calls-status.v1",
            "operation": "status --json",
            "requires_current_boot": True,
            "requires_target_revision": True,
            "requires_live_peer_identity": True,
            "lease_tool_path": safety.VOICE_CALL_LEASE_TOOL_PATH,
            "bypass_allowed": False,
            "receipt_schema": safety.VOICE_GUARD_RECEIPT_SCHEMA,
        }
    ]


def test_runtime_safety_plan_has_no_caller_boolean_ingress_evidence() -> None:
    gate = _plan()["external_ingress_gate"]
    assert gate["caller_boolean_accepted"] is False
    assert gate["precommit_required_active_state"] == "inactive"
    assert gate["precommit_session_drain_receipt_schema"] == (
        safety.SESSION_DRAIN_RECEIPT_SCHEMA
    )
    assert gate["postcommit_start_order"] == [
        safety.CONNECTOR_UNIT,
        safety.GATEWAY_UNIT,
    ]
    assert gate["transaction_phase_order"] == [
        "precommit_gate_intent",
        "precommit_gate_applied",
        "precommit_gate_readback",
        "postcommit_gate_intent",
        "postcommit_gate_applied",
        "postcommit_gate_readback",
    ]
    assert gate["precommit_crash_policy"] == (
        "restore_exact_predecessor_ingress"
    )
    assert gate["postcommit_crash_policy"] == (
        "forward_only_target_or_maintenance"
    )


def test_runtime_safety_plan_binds_gateway_and_connector_session_drain() -> None:
    drain = _plan()["session_drain"]
    assert drain["public_ingress_service_units"] == [
        safety.CONNECTOR_UNIT,
        safety.GATEWAY_UNIT,
    ]
    assert drain["gateway"] == {
        "service_unit": safety.GATEWAY_UNIT,
        "runtime_status_path": safety.GATEWAY_RUNTIME_STATUS_PATH,
        "required_gateway_state_before_stop": "draining",
        "required_active_agents": 0,
        "required_active_session_keys": [],
        "runtime_status_contract": "gateway.status.gateway_state.json",
    }
    assert drain["connector"]["service_unit"] == safety.CONNECTOR_UNIT
    assert drain["connector"]["socket_path"] == safety.CONNECTOR_SOCKET_PATH
    assert drain["connector"]["maximum_request_drain_seconds"] == 45
    assert drain["connector"]["required_socket_state_after_stop"] == "absent"
    assert drain["caller_boolean_accepted"] is False


def test_structural_receipt_identities_are_exact_catalog_derivatives() -> None:
    plan = _plan()
    identities = safety.structural_receipt_identities()

    assert identities == {
        "protected_service_set_sha256": safety.sha256_bytes(
            safety.canonical_bytes(plan["protected_voice_service_units"])
        ),
        "precommit_service_set_sha256": safety.sha256_bytes(
            safety.canonical_bytes(plan["precommit_long_running_service_units"])
        ),
        "disabled_trigger_set_sha256": safety.sha256_bytes(
            safety.canonical_bytes(plan["precommit_disabled_trigger_units"])
        ),
        "enabled_trigger_set_sha256": safety.sha256_bytes(
            safety.canonical_bytes(plan["postcommit_enabled_trigger_units"])
        ),
        "precommit_probe_catalog_sha256": safety.sha256_bytes(
            safety.canonical_bytes(plan["precommit_health_probes"])
        ),
        "postcommit_probe_catalog_sha256": safety.sha256_bytes(
            safety.canonical_bytes(plan["postcommit_health_probes"])
        ),
        "public_start_order_sha256": safety.sha256_bytes(
            safety.canonical_bytes(plan["postcommit_public_start_order"])
        ),
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("protected_voice_service_units", []),
        ("protected_voice_service_units", [safety.CONNECTOR_UNIT]),
        ("public_ingress_service_units", [safety.GATEWAY_UNIT]),
        ("precommit_long_running_service_units", []),
        ("postcommit_public_start_order", [safety.GATEWAY_UNIT]),
        ("precommit_disabled_trigger_units", []),
        ("postcommit_enabled_trigger_units", []),
        ("voice_guard_probes", []),
        ("precommit_health_probes", []),
        ("postcommit_health_probes", []),
        ("session_drain", {}),
        ("service_operation_classes", {}),
    ],
)
def test_runtime_safety_plan_rejects_omission_and_substitution(
    field: str,
    replacement: object,
) -> None:
    plan = _plan()
    plan[field] = replacement
    _rehash(plan)
    with pytest.raises(
        safety.ProductionReleaseRuntimeSafetyError,
        match="release_runtime_safety_plan_invalid",
    ):
        safety.validate_runtime_safety_plan(
            plan,
            predecessor_revision=PREDECESSOR,
            release_revision=TARGET,
            release_consumer_set=_consumer_set(),
        )


def test_runtime_safety_plan_rejects_cross_release_replay() -> None:
    with pytest.raises(
        safety.ProductionReleaseRuntimeSafetyError,
        match="release_runtime_safety_plan_invalid",
    ):
        safety.validate_runtime_safety_plan(
            _plan(),
            predecessor_revision=PREDECESSOR,
            release_revision="5" * 40,
            release_consumer_set=_consumer_set(),
        )


def test_runtime_safety_plan_rejects_consumer_set_replay() -> None:
    consumer_set = _consumer_set()
    consumer_set["consumer_set_sha256"] = "6" * 64
    with pytest.raises(
        safety.ProductionReleaseRuntimeSafetyError,
        match="release_runtime_safety_plan_invalid",
    ):
        safety.validate_runtime_safety_plan(
            _plan(),
            predecessor_revision=PREDECESSOR,
            release_revision=TARGET,
            release_consumer_set=consumer_set,
        )


def test_runtime_safety_plan_rejects_phase_order_power_loss_downgrade() -> None:
    plan = _plan()
    gate = deepcopy(plan["external_ingress_gate"])
    gate["transaction_phase_order"] = [
        phase
        for phase in gate["transaction_phase_order"]
        if phase != "precommit_gate_readback"
    ]
    plan["external_ingress_gate"] = gate
    _rehash(plan)
    with pytest.raises(
        safety.ProductionReleaseRuntimeSafetyError,
        match="release_runtime_safety_plan_invalid",
    ):
        safety.validate_runtime_safety_plan(
            plan,
            predecessor_revision=PREDECESSOR,
            release_revision=TARGET,
            release_consumer_set=_consumer_set(),
        )


def test_runtime_safety_plan_validates_exact_document() -> None:
    assert safety.validate_runtime_safety_plan(
        _plan(),
        predecessor_revision=PREDECESSOR,
        release_revision=TARGET,
        release_consumer_set=_consumer_set(),
    ) == _plan()
