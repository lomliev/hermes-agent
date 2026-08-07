#!/usr/bin/env python3
"""Signed, target-neutral contract for cloud-native production releases.

The model decides *what* work should be released.  This module only validates
the exact structured release identity, bounded scheduling window, immutable
artifact identity, and Ed25519 signature.  It contains no prose classifier or
semantic routing logic.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


MANIFEST_SCHEMA = "muncho-cloud-release-manifest.v1"
ENVELOPE_SCHEMA = "muncho-cloud-release-envelope.v1"
SKYAI_TARGET = "skyai_prod"
SKYAI_REPOSITORY = "lomliev/hermes-agent"
SKYAI_SOURCE_REF = "main"
SKYAI_RELEASE_BUCKET = "adventico-ai-platform-skyai-releases"
MAX_RELEASE_DELAY_SECONDS = 24 * 60 * 60
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_ENVELOPE_BYTES = 128 * 1024

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BEHAVIOR = re.compile(r"^v[1-9][0-9]*\.[0-9]+$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,239}$")

_MANIFEST_FIELDS = frozenset({
    "schema",
    "target",
    "repository",
    "source_ref",
    "source_sha",
    "source_tree_sha",
    "behavior_version",
    "artifact_bucket",
    "artifact_object",
    "artifact_sha256",
    "artifact_size",
    "queued_at_unix",
    "not_before_unix",
    "deploy_by_unix",
    "case_id",
    "requester_id",
    "reason_sha256",
    "ci_run_id",
    "ci_run_url",
})
_ENVELOPE_FIELDS = frozenset({"schema", "key_id", "payload", "signature"})


class CloudReleaseContractError(ValueError):
    """Stable fail-closed release contract validation failure."""


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CloudReleaseContractError("release_json_invalid") from exc


def public_key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()


def load_private_key(raw: bytes) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except (TypeError, ValueError) as exc:
        raise CloudReleaseContractError("release_private_key_invalid") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise CloudReleaseContractError("release_private_key_invalid")
    return key


def load_public_key(raw: bytes) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(raw)
    except (TypeError, ValueError) as exc:
        raise CloudReleaseContractError("release_public_key_invalid") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise CloudReleaseContractError("release_public_key_invalid")
    return key


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _MANIFEST_FIELDS:
        raise CloudReleaseContractError("release_manifest_shape_invalid")
    result = dict(value)
    if (
        result["schema"] != MANIFEST_SCHEMA
        or result["target"] != SKYAI_TARGET
        or result["repository"] != SKYAI_REPOSITORY
        or result["source_ref"] != SKYAI_SOURCE_REF
        or result["artifact_bucket"] != SKYAI_RELEASE_BUCKET
    ):
        raise CloudReleaseContractError("release_manifest_identity_invalid")
    source_sha = result["source_sha"]
    source_tree_sha = result["source_tree_sha"]
    artifact_sha256 = result["artifact_sha256"]
    reason_sha256 = result["reason_sha256"]
    if (
        not isinstance(source_sha, str)
        or _SHA40.fullmatch(source_sha) is None
        or not isinstance(source_tree_sha, str)
        or _SHA40.fullmatch(source_tree_sha) is None
        or not isinstance(artifact_sha256, str)
        or _SHA256.fullmatch(artifact_sha256) is None
        or not isinstance(reason_sha256, str)
        or _SHA256.fullmatch(reason_sha256) is None
    ):
        raise CloudReleaseContractError("release_manifest_digest_invalid")
    behavior = result["behavior_version"]
    if not isinstance(behavior, str) or _BEHAVIOR.fullmatch(behavior) is None:
        raise CloudReleaseContractError("release_behavior_version_invalid")
    artifact_object = result["artifact_object"]
    expected_object = f"artifacts/{source_sha}/{artifact_sha256}.tar.gz"
    if artifact_object != expected_object:
        raise CloudReleaseContractError("release_artifact_object_invalid")
    artifact_size = result["artifact_size"]
    if type(artifact_size) is not int or not 1 <= artifact_size <= MAX_ARTIFACT_BYTES:
        raise CloudReleaseContractError("release_artifact_size_invalid")
    queued_at = result["queued_at_unix"]
    not_before = result["not_before_unix"]
    deploy_by = result["deploy_by_unix"]
    if (
        any(
            type(item) is not int or item < 1
            for item in (queued_at, not_before, deploy_by)
        )
        or not queued_at <= not_before <= deploy_by
        or deploy_by - queued_at > MAX_RELEASE_DELAY_SECONDS
    ):
        raise CloudReleaseContractError("release_schedule_invalid")
    for name in ("case_id", "requester_id"):
        item = result[name]
        if not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None:
            raise CloudReleaseContractError("release_request_identity_invalid")
    ci_run_id = result["ci_run_id"]
    ci_run_url = result["ci_run_url"]
    if (
        type(ci_run_id) is not int
        or ci_run_id < 1
        or not isinstance(ci_run_url, str)
        or ci_run_url
        != f"https://github.com/{SKYAI_REPOSITORY}/actions/runs/{ci_run_id}"
    ):
        raise CloudReleaseContractError("release_ci_identity_invalid")
    canonical_json_bytes(result)
    return result


def sign_manifest(value: Mapping[str, Any], private_key_raw: bytes) -> dict[str, Any]:
    payload = validate_manifest(value)
    private_key = load_private_key(private_key_raw)
    body = canonical_json_bytes(payload)
    signature = private_key.sign(body)
    envelope = {
        "schema": ENVELOPE_SCHEMA,
        "key_id": public_key_id(private_key.public_key()),
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    if len(canonical_json_bytes(envelope)) > MAX_ENVELOPE_BYTES:
        raise CloudReleaseContractError("release_envelope_too_large")
    return envelope


def verify_envelope(value: Any, public_key_raw: bytes) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _ENVELOPE_FIELDS:
        raise CloudReleaseContractError("release_envelope_shape_invalid")
    if value["schema"] != ENVELOPE_SCHEMA:
        raise CloudReleaseContractError("release_envelope_schema_invalid")
    public_key = load_public_key(public_key_raw)
    if value["key_id"] != public_key_id(public_key):
        raise CloudReleaseContractError("release_key_id_invalid")
    signature_text = value["signature"]
    if not isinstance(signature_text, str) or len(signature_text) > 256:
        raise CloudReleaseContractError("release_signature_invalid")
    try:
        signature = base64.b64decode(signature_text, validate=True)
        public_key.verify(signature, canonical_json_bytes(value["payload"]))
    except (ValueError, InvalidSignature) as exc:
        raise CloudReleaseContractError("release_signature_invalid") from exc
    return validate_manifest(value["payload"])


__all__ = [
    "CloudReleaseContractError",
    "ENVELOPE_SCHEMA",
    "MANIFEST_SCHEMA",
    "MAX_ARTIFACT_BYTES",
    "MAX_ENVELOPE_BYTES",
    "MAX_RELEASE_DELAY_SECONDS",
    "SKYAI_RELEASE_BUCKET",
    "SKYAI_REPOSITORY",
    "SKYAI_SOURCE_REF",
    "SKYAI_TARGET",
    "canonical_json_bytes",
    "load_private_key",
    "load_public_key",
    "public_key_id",
    "sign_manifest",
    "validate_manifest",
    "verify_envelope",
]
