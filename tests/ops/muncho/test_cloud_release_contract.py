from __future__ import annotations

import base64
import copy
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ops.muncho.runtime.cloud_release_contract import (
    CloudReleaseContractError,
    MANIFEST_SCHEMA,
    SKYAI_RELEASE_BUCKET,
    SKYAI_REPOSITORY,
    SKYAI_SOURCE_REF,
    SKYAI_TARGET,
    sign_manifest,
    validate_manifest,
    verify_envelope,
)


def _manifest() -> dict[str, object]:
    source_sha = "a" * 40
    artifact_sha = "c" * 64
    return {
        "schema": MANIFEST_SCHEMA,
        "target": SKYAI_TARGET,
        "repository": SKYAI_REPOSITORY,
        "source_ref": SKYAI_SOURCE_REF,
        "source_sha": source_sha,
        "source_tree_sha": "b" * 40,
        "behavior_version": "v2.19",
        "artifact_bucket": SKYAI_RELEASE_BUCKET,
        "artifact_object": f"artifacts/{source_sha}/{artifact_sha}.tar.gz",
        "artifact_sha256": artifact_sha,
        "artifact_size": 1234,
        "queued_at_unix": 2_000_000_000,
        "not_before_unix": 2_000_000_100,
        "deploy_by_unix": 2_000_086_400,
        "case_id": "case:skyai-training-17",
        "requester_id": "1282938967888498720",
        "reason_sha256": hashlib.sha256(b"approved model-authored reason").hexdigest(),
        "ci_run_id": 311_441_237_48,
        "ci_run_url": (
            "https://github.com/lomliev/hermes-agent/actions/runs/31144123748"
        ),
    }


def _keys() -> tuple[bytes, bytes]:
    private = Ed25519PrivateKey.generate()
    return (
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    )


def test_signed_manifest_round_trip_is_exact_and_bounded() -> None:
    private, public = _keys()
    manifest = _manifest()

    envelope = sign_manifest(manifest, private)

    assert verify_envelope(envelope, public) == manifest
    assert validate_manifest(manifest) == manifest


def test_manifest_rejects_unknown_fields_unbounded_schedule_and_object_drift() -> None:
    for mutation in (
        lambda row: row.update({"semantic_risk": "low"}),
        lambda row: row.update({"deploy_by_unix": 2_000_086_401}),
        lambda row: row.update({"artifact_object": "artifacts/other.tar.gz"}),
    ):
        value = _manifest()
        mutation(value)
        with pytest.raises(CloudReleaseContractError):
            validate_manifest(value)


def test_envelope_rejects_payload_and_signature_tampering() -> None:
    private, public = _keys()
    envelope = sign_manifest(_manifest(), private)
    payload_tampered = copy.deepcopy(envelope)
    payload_tampered["payload"]["behavior_version"] = "v2.20"
    with pytest.raises(CloudReleaseContractError, match="release_signature_invalid"):
        verify_envelope(payload_tampered, public)

    signature_tampered = copy.deepcopy(envelope)
    signature_tampered["signature"] = base64.b64encode(b"x" * 64).decode("ascii")
    with pytest.raises(CloudReleaseContractError, match="release_signature_invalid"):
        verify_envelope(signature_tampered, public)
