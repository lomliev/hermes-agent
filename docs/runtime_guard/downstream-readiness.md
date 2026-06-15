# Runtime Guard Downstream Readiness

This packet is for continuing runtime guard work while an upstream fork PR is
waiting on maintainer review or workflow approval. It is intentionally public
safe: it contains no customer context, private paths, secrets, live service
instructions, or deployment credentials.

## Current Surface

The runtime guard is disabled by default and reads platform-local configuration
from `PlatformConfig.extra.runtime_guard`. The current local test package covers:

- guard defaults, provider coercion, dry-run decisions, and audit sanitization;
- inbound message blocking before session processing starts;
- assistant final response blocking before visible send;
- stream suppression and first-visible stream checks;
- delivery router, kanban notification, send-message tool, and cron delivery
  surface policies.

Current default delivery policy highlights:

- `assistant_final`: `guard`
- `assistant_stream`: `disable`
- `assistant_interim`: `disable`
- `delivery_router`: `allow`
- `tool_progress`: `disable`
- `command_ack`: `allow`
- `interaction_ack`: `allow`
- `send_message_tool`: `block`
- `send_message_reaction`: `block`
- `cron_delivery`: `allow`
- `kanban_notification`: `allow`
- `process_notification`: `allow`

## Fork-Continuation Branch Policy

- Keep the upstream PR branch review-ready. Do not use the continuation branch
  as a place to rewrite the upstream branch history.
- Keep continuation commits additive, narrow, and cherry-pickable. Prefer docs,
  readiness checklists, and focused tests over behavior changes while review is
  pending.
- Do not mix runtime guard behavior changes with unrelated gateway cleanup.
  Behavior fixes requested by maintainers should land on the upstream PR path
  first, then be brought back to the continuation branch.
- Do not include secrets, credentials, live chat IDs, private host paths,
  customer names, or local user details in continuation artifacts.
- Avoid public PR mutation from the continuation branch unless explicitly
  assigned. Local validation and local diffs are enough for downstream
  readiness work.
- Do not start, stop, restart, or deploy live gateways from this branch. Treat
  activation as a separate operator-approved step after merge.

## Post-Merge Dry-Run Activation Gates

Use these gates after the upstream runtime guard PR has merged and a downstream
environment is ready for approved configuration-only validation.

1. **Code gate:** confirm the deployed candidate contains the merged runtime
   guard code and the runtime guard test package passes locally.
2. **Config-shape gate:** add configuration only under the target platform's
   `extra.runtime_guard` map. Do not add a new user-facing environment variable.
3. **Scope gate:** start with the narrowest practical scope, such as one
   platform plus one chat, thread, session key, or guild. Do not begin with a
   whole-platform scope.
4. **Provider gate:** use an available provider name and verify provider errors
   are understood before enforcement. Keep `fail_closed: true` unless the
   provider has a documented operational reason to fail open.
5. **Dry-run gate:** set `enabled: true` and `dry_run: true` first. In dry-run,
   provider or surface blocks should report would-block decisions without
   suppressing visible delivery.
6. **Streaming gate:** remember that enforced `streaming.policy: disable`
   suppresses visible stream sends. Keep dry-run on until the expected streaming
   behavior is accepted.
7. **Surface gate:** review every non-allow delivery surface before enforcement,
   especially `assistant_final`, `assistant_stream`, `tool_progress`, and
   `send_message_tool`.
8. **Enforcement gate:** switch `dry_run: false` only after dry-run output,
   rollback steps, and ownership for live monitoring are all agreed.

Example dry-run shape with placeholder IDs. A machine-checkable JSON version
lives in
[`docs/runtime_guard/examples/dry-run-activation.json`](examples/dry-run-activation.json)
and is validated by
[`tests/gateway/test_runtime_guard_downstream_example.py`](../../tests/gateway/test_runtime_guard_downstream_example.py).

```yaml
platforms:
  discord:
    enabled: true
    extra:
      runtime_guard:
        enabled: true
        provider: noop
        dry_run: true
        fail_closed: true
        scope:
          platforms: ["discord"]
          chat_ids: ["example-channel-id"]
          thread_ids: ["example-thread-id"]
        streaming:
          policy: guard_first_visible
        delivery_surfaces:
          assistant_final: guard
          assistant_stream: disable
          tool_progress: disable
          send_message_tool: block
```

## Requested-Changes Response Playbook

When maintainers request changes on the upstream PR:

1. Freeze continuation work and read the review request as a behavior contract,
   not just a patch suggestion.
2. Classify the request as behavior, integration wiring, test coverage, docs,
   or public-safety cleanup.
3. Reproduce the relevant premise against the current upstream PR state. Point
   to the line or test where the requested behavior manifests.
4. Patch the upstream PR path first when the request affects runtime behavior.
   Keep continuation-only docs and readiness artifacts separate unless the
   reviewer asks for them.
5. Re-run the runtime guard validation package below.
6. Update this readiness packet if the review changes surface names, default
   actions, config shape, or activation gates.
7. Bring accepted upstream changes back into the continuation branch with the
   smallest possible local diff.

## Rollback Checklist

Rollback should be configuration-first unless the code itself is faulty.

- Set `extra.runtime_guard.enabled: false` for the affected platform, or remove
  the `runtime_guard` block from that platform's `extra` map.
- If only enforcement caused the issue, set `dry_run: true` before disabling
  the provider entirely.
- If streaming is the issue, set `streaming.policy: allow` or remove the scoped
  runtime guard config for the affected chat or thread.
- If scheduled or indirect delivery is the issue, set the affected surface to
  `allow`, for example `cron_delivery`, `delivery_router`, or
  `kanban_notification`.
- If tool-originated sends are blocked unexpectedly, review
  `send_message_tool` and `send_message_reaction` before widening the whole
  scope.
- Preserve the narrow scope during rollback so unrelated platforms or chats do
  not change behavior.
- Use the normal approved configuration rollout path for live systems. Do not
  perform ad-hoc restarts or manual service mutations as part of readiness work.
- After rollback, re-run the targeted local validation package and record which
  gate failed.

## Fork PR Workflow Approval States

Fork PRs can show GitHub workflow states that are not code failures:

- **Waiting for approval:** maintainers must approve workflow execution for the
  fork. Treat this as blocked-by-workflow, not failed CI.
- **Pending with no logs:** usually means the workflow has not started. Avoid
  pushing no-op commits just to retrigger it.
- **Skipped:** verify whether the workflow is intentionally path-filtered or
  disabled for forks before treating it as a missing validation signal.
- **Action required:** a maintainer or repository owner likely needs to approve
  or rerun the workflow.
- **Failed with logs:** debug as a normal CI failure. Prefer reproducing locally
  with the targeted validation commands before changing code.
- **Green after approval:** downstream readiness work can continue locally, but
  activation still waits for merge plus the dry-run gates above.

## Validation Commands

Use the repository's existing environment. Do not install packages or update
lockfiles just to run this package.

Targeted runtime guard pytest package:

```bash
python -m pytest \
  tests/gateway/test_runtime_guard_downstream_example.py \
  tests/gateway/test_runtime_guard.py \
  tests/gateway/test_runtime_guard_platform_base.py \
  tests/gateway/test_runtime_guard_streaming.py \
  tests/gateway/test_runtime_guard_stream_consumer_wiring.py \
  tests/gateway/test_runtime_guard_gateway_wiring.py \
  tests/gateway/test_runtime_guard_delivery_surfaces.py \
  tests/cron/test_runtime_guard_cron_policy.py
```

Cheap static checks:

```bash
python -m py_compile \
  gateway/runtime_guard.py \
  gateway/platforms/base.py \
  gateway/stream_consumer.py \
  gateway/delivery.py \
  gateway/kanban_watchers.py \
  cron/scheduler.py \
  tools/send_message_tool.py

git diff --check
```

Also run a local public-safety scan for private project markers, customer
names, non-public labels, private host paths, and local user details.
Expected result: no matches.
