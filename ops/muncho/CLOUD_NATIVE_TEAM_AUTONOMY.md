# Cloud-native team autonomy contract

## Product outcome

Muncho is a continuously available cloud worker for the trusted Adventico and
SkyVision team. A normal engineering, reporting, SkyAI-training, CI, merge, or
production-release workflow must not depend on Emil's personal Mac, an
interactive passkey, or repeated owner approvals.

All configured team members may run routine work and sensitive read-only
reports. Nassi, Ivs, Alex, and Plamenka have the `top` operator tier and may
direct SkyAI analysis, training, review, merge, and production release from end
to end. The owner remains the authority only for trust membership, service
identities and keys, global security boundaries, irreversible destruction, and
other genuinely global high-risk changes.

## Semantic authority

The selected LLM is the only semantic authority. Runtime code must not infer
intent, sensitivity, risk, or routing from free-form words, regular
expressions, allow/deny vocabularies, or keyword scores. The model chooses an
exact structured operation. Deterministic code may then validate only the
operation ID and schema, exact actor/target identities, signatures, immutable
revision and artifact hashes, numeric bounds, CI results, and technical
runtime invariants.

## Release path

```text
trusted team instruction
  -> model-authored implementation and tests
  -> PR + aggregate green CI
  -> top operator selects exact SkyAI SHA and <=24h schedule
  -> cloud operational edge verifies main/CI/tree/artifact identities
  -> Ed25519-signed manifest + immutable archive in protected GCS
  -> SkyAI VM timer verifies signature and artifact
  -> isolated production import/dependency probe
  -> atomic symlink/environment cutover
  -> local health + public identity + real live-model smoke
  -> success receipt, or automatic rollback and bounded retry
```

The GCS queue is a transport and commit log, not a semantic dispatcher. A
target consumer never interprets prose. It accepts one exact signed schema and
deploys the newest eligible release. A ready SkyAI training release may be
grouped with nearby work, but `deploy_by_unix` is never more than 24 hours
after publication.

Routine releases use short-lived VM service-account tokens from the metadata
server. GitHub credentials and the release-signing private key remain inside a
domain-exclusive operational-edge service. The SkyAI target receives only the
public verification key and read-only bucket access. The personal Mac is an
emergency/admin surface, not a runtime dependency.

## Increment and upstream discipline

Ship small completed increments. Each increment has one exact merged SHA,
green aggregate CI, an immutable artifact, target health checks, and a tested
rollback. Do not accumulate unrelated autonomy, UI, provider, SkyAI, and
upstream changes into one production release.

The three-hour Nous upstream rail prepares or updates an isolated fork PR. It
never silently auto-merges conflicts. Every systemd-referenced immutable
release must be retention-pinned; a missing pinned release or first
`AssertPathExists` failure is a P0 alert. Feature work rebases or merges the
green upstream-sync result before its own merge so active work does not remain
an isolated fork.

## Target adapters

SkyAI is the first adapter for the signed release contract. SkyVision follows
the same pattern for Alex and the engineering team: cloud workspace, exact
GitLab branch/MR/pipeline identity, immutable deployable artifact, target-side
verification, smoke checks, rollback, and receipt. Target-specific build and
health probes are adapters; trust and semantic policy stay shared.
