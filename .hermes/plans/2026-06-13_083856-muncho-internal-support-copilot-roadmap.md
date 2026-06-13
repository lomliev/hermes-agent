# Muncho Internal Support Copilot Roadmap v1.1

> **For Hermes/Muncho:** След одобрение изпълнявай този план step-by-step в Discord thread `1506738130521297046`. Преди всяка стъпка обявявай точната фаза/step: „Започвам Фаза X / Step Y…“. Не смесвай execution с Customer Hermes / customer-facing chatbot thread `1507026708702826617`.

**Goal:** Да изградим отделен Muncho Internal Support Copilot като единен мозък за вътрешна SkyVision/Adventico support/backend/devops координация: Discord-wide history ingestion, cross-thread logical state graph, evidence-first triage, правилен resolver routing, статус tracking, runbook learning и безопасно Codex-assisted execution.

**Architecture:** Muncho е master Hermes / internal support orchestrator и source-of-truth coordinator. Всички Discord канали/threads, до които ботът има разрешен достъп и history permission, трябва да се нормализират в общ event store + case graph, така че отделните разговори да се обединяват в една логическа сесия. Discord threads са conversation layer, Kanban/status artifacts са ownership/next-action layer, docs/runbooks са durable learning layer. Codex е bounded worker/reviewer върху sanitized контекст, не source of truth.

**Out of scope:** Customer-facing Hermes/chatbot runtime, customer ChatKit/FAB execution, public customer answers, authenticated customer actions. Customer Hermes thread `1507026708702826617` може да е dependency/source само когато вътрешен support case зависи от customer-facing продукта.

**Approval phrase to start execution:**

```text
Одобрявам Muncho Internal Support Copilot roadmap v1.1 за execution в Discord thread 1506738130521297046.
```

---

## Current Context / Assumptions

- Работният thread за този план е `1506738130521297046`.
- Първият приоритет е Muncho да стане единен Discord-wide мозък: да чете/индексира разрешената история от всички релевантни канали/threads, да прави логическа връзка между тях и да актуализира общите планове/next steps според нова информация от всеки колега.
- Customer Hermes / chatbot продуктът има отделен план и работен thread `1507026708702826617`.
- Muncho трябва да помага активно: не само да препраща, а да прави triage, evidence checks, resolver proposal, missing-info questions, safe next step, approval phrase, runbook learning.
- Canonical handles/routing се спазват: `Пламенка`, `Ивчо`, `Алекс`, `Кожухаров`, `Емо`, `Фатих`, `Наси`.
- High-risk действия искат exact approval: merge, PROD deploy, rollback, firewall unban, access changes, Shopify write, secrets, destructive git, protected customer/voucher/booking/payment mutations.

---

## Operating Contract

Every Muncho internal-support response should aim for this shape:

```text
VERDICT: PASS/FAIL/BLOCKED/NEEDS_INFO
TL;DR: ...
CATEGORY: support/backend/devops/frontend/customer-hermes/adventico/ops
EVIDENCE_CHECKED: files/thread IDs/tool results/snapshots/known source
EVIDENCE_GAP: what is missing, if any
OWNER/RESOLVER: canonical handle + lane/thread
STATUS: one of the allowed status enum
NEXT_ACTION: exact next action
APPROVAL_NEEDED: no / yes + exact phrase
RISK: low/medium/high + why
```

Allowed status enum:

```text
done
blocked
needs-details
waiting_on_requester
waiting_on_resolver
reassigned
code-fix-needed
resolved_pending_verification
owner_decision_needed
deploy-gate-blocked
```

---

## Phase 0 — Discord-wide Unified Context Foundation

**Objective:** Muncho да стане единен мозък, а не отделни „Мунчовци“ по канали. Всички релевантни Discord канали/threads трябва да се четат, нормализират, индексират и свързват в обща operational state картина.

### Step 0.1 — Discord access & permissions audit

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/discord_access_audit.md`
- `~/.hermes/notes/skyvision/internal-support/discord_channel_scope.md`

**Content:**
- списък с всички разрешени канали/threads за Muncho;
- дали bot token има `View Channel`, `Read Message History`, `Send Messages`, `Create Public Threads`, `Send Messages in Threads`;
- кои канали са listen-only, кои са routing/action lanes, кои са owner/control lanes;
- кои канали са out-of-scope или forbidden.

**Acceptance criteria:**
- PASS ако Muncho знае точно кои канали може да чете и кои не.
- PASS ако липсващ history permission се връща като BLOCKED с точна причина, не като “няма контекст”.

**Gate:** Hermes/Muncho не може магически да чете Discord history извън messages, доставени до gateway/session, освен ако Discord adapter/tooling бъде разширен или конфигуриран с bot-token history ingestion. Това е техническа prerequisite работа, не prompt-only промяна.

### Step 0.2 — Historical backfill / ingestion pipeline

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/discord_history_ingestion_plan.md`
- `~/.hermes/state/skyvision_internal_support/discord_events.sqlite` или еквивалентен event store

**Required behavior:**
- backfill на история от allowlisted channels/threads;
- incremental sync за нови съобщения;
- message metadata: channel_id, thread_id, message_id, author, timestamp, reply refs, attachments, mentions;
- safe attachment index: filename/path/hash, без raw secret dump;
- dedupe/idempotency по Discord message_id;
- redaction/classification преди LLM/Codex употреба.

**Acceptance criteria:**
- PASS ако Muncho може да отговори “какво се случи по case X във всички threads?” с evidence refs.
- PASS ако повторно sync-ване не дублира events.
- PASS ако deleted/edited messages се маркират като state changes, не се игнорират.

### Step 0.3 — Cross-thread case graph

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/cross_thread_case_graph.md`
- `~/.hermes/state/skyvision_internal_support/case_graph.sqlite` или еквивалентен graph/index

**Graph links:**
- same case identifiers: voucher/order/booking ID, customer-safe refs, issue title, task code;
- resolver links: Алекс/Ивчо/Фатих/Кожухаров/Пламенка etc.;
- dependency links: “Пламенка каза X → променя next step за Алекс”;
- status transitions;
- blocker/approval dependencies;
- Customer Hermes dependency links, но без смесване на execution threads.

**Acceptance criteria:**
- PASS ако ново съобщение в канала на Пламенка може да trigger-не актуализация на next step в case-а на Алекс, когато има evidence-backed dependency.
- PASS ако Muncho може да обясни защо свързва два разговора: exact messages/threads/IDs + logic.
- PASS ако conflicting info се маркира като conflict, а не се overwrite-ва silently.

### Step 0.4 — Unified status synthesis and owner brief

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/unified_status_brief_template.md`
- recurring/status command design for channel `1504852355588423801` and any thread where Emil asks.

**Behavior:**
- On request “как вървят нещата?”, Muncho synthesizes across all ingested channels/threads.
- Output includes: active cases, changed since last brief, blockers, who is waiting on whom, next logical move, what needs Emil approval.
- Muncho gives personal proposals/nasoki, not just summaries.

**Acceptance criteria:**
- PASS ако brief цитира evidence refs and cross-thread links.
- PASS ако Muncho updates next steps globally when any teammate adds relevant info in another channel.
- PASS ако owner sees one coherent plan, not fragmented channel-local memory.

### Step 0.5 — Discord history ingestion implementation plan / tool gap

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/discord_history_tool_gap.md`

**Potential implementation paths:**
1. Extend Hermes Discord adapter/toolset with read-history/list-channel/list-thread ingestion using the existing Discord bot token and permission gates.
2. Add a bounded local ingestion script using Discord API, allowlisted channel IDs, read-only mode, redaction, and SQLite event store.
3. Add scheduled incremental sync/watchdog with no noisy output unless relevant case changes.

**Acceptance criteria:**
- PASS ако we identify exact current limitation, required bot permissions, data store, and first safe backfill scope.
- PASS ако no colleague messages are sent and no channels are mutated during read-only ingestion.

**Gate:** Before any real Discord history backfill, Emil must approve exact allowlist of channels/threads and confirm bot permissions. No broad “all Discord forever” scrape without scope/permission review.

---

## Phase 1 — Boundary, Source Map, and Safety Classes

**Objective:** Lock the separation between Internal Support Copilot and Customer Hermes, then define what evidence Muncho can use and how it is classified.

### Step 1.1 — Create scope artifact

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/muncho_internal_support_scope.md`

**Content:**
- Muncho role: internal support copilot / master operator.
- Customer Hermes role: customer-facing assistant.
- Explicit thread separation:
  - Internal Support Copilot: `1506738130521297046`
  - Customer Hermes product: `1507026708702826617`
- Out-of-scope list for this plan.

**Acceptance criteria:**
- PASS if a new operator can read the artifact and not confuse the two products.
- PASS if it names which thread gets execution updates for this roadmap.

### Step 1.2 — Create evidence/source registry

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/source_registry.md`
- `~/.hermes/notes/skyvision/internal-support/safety_classes.md`

**Safety classes:**
- `PUBLIC_SAFE`
- `CUSTOMER_SUPPORT_SAFE`
- `INTERNAL_TEAM_SAFE`
- `PROTECTED_LIVE`
- `FORBIDDEN_TO_LLM`
- `OUTDATED_OR_UNVERIFIED`

**Acceptance criteria:**
- PASS if every source has owner, freshness, trust level, allowed use, forbidden use.
- PASS if `PROTECTED_LIVE` / `FORBIDDEN_TO_LLM` are never sent raw to Codex/LLM.

**Gate:** Stop before using any raw logs, `.env`, tokens, auth headers, cookies, customer/payment payloads, or private keys in prompts.

---

## Phase 2 — Support Case Intake & Routing Model

**Objective:** Standardize how Muncho receives, classifies, routes, tracks, and reports internal support cases.

### Step 2.1 — Define case schema

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/support_case_schema.md`

**Fields:**
- case_id / title
- requester
- resolver
- lane/channel/thread
- source thread/message IDs
- domain/category
- status enum
- current evidence
- evidence gaps
- next action
- approval gate, if any
- runbook/learning outcome
- linked Customer Hermes dependency, if relevant

**Acceptance criteria:**
- PASS if every routed case can be represented without free-form guessing.
- PASS if `resolver_visible_thread_id` and `requester_return_thread_id` are separate fields.

### Step 2.2 — Define routing matrix

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/resolver_routing_matrix.md`

**Baseline lanes:**
- Backend/API/monolith → Алекс/Ивчо lane.
- Frontend/widget/UI → Фатих lane.
- DevOps/GitLab/Cloudflare/GCP/cPanel/firewall → Кожухаров lane.
- Booking/support ops → support/booking lane with Пламенка/Нина as relevant.
- Owner decisions/cross-lane blockers → control tower.

**Acceptance criteria:**
- PASS if Muncho can answer “who can see this?” before claiming routed/delivered.
- PASS if every delivery claim requires tool evidence: target, thread ID, message ID.

**Gate:** No “sent/routed/tracked” claim without resolver-visible delivery evidence.

---

## Phase 3 — Active Copilot Workflow MVP

**Objective:** Muncho becomes useful in the thread immediately: triage, propose next step, route safely, track state, and report back.

### Step 3.1 — Intake response template

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/templates/intake_response.md`

**Template includes:**
- VERDICT
- TL;DR
- Category
- Known facts
- Evidence checked
- Evidence gap
- Proposed resolver
- Proposed target thread/lane
- Next action
- Approval phrase if needed

**Acceptance criteria:**
- PASS if a support case gets actionable output in one message.
- PASS if missing data is asked as exact questions, not vague “send more details”.

### Step 3.2 — Resolver handoff template

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/templates/resolver_handoff.md`

**Rules:**
- Use a dedicated resolver-visible thread for new operational issues when tooling supports it.
- Existing issue goes to existing thread.
- Include requester, symptom, evidence, reproduction/smoke, impact, risk, requested answer shape.
- No colleague DMs unless explicitly approved.

**Acceptance criteria:**
- PASS if the resolver can act without reading the origin thread.
- PASS if the origin thread receives status with delivery evidence.

### Step 3.3 — Follow-up/status tracking template

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/templates/status_update.md`

**Acceptance criteria:**
- PASS if Muncho separates:
  - resolver says fixed;
  - technically deployed;
  - operator/customer smoke confirmed;
  - still blocked.

**Gate:** Do not mark “done” solely from deploy/MR evidence; use `resolved_pending_verification` until smoke/owner confirmation exists.

---

## Phase 4 — Knowledge Centralization & Runbook Learning

**Objective:** Every repeated case teaches Muncho durable behavior without polluting memory with stale task state.

### Step 4.1 — Internal support playbook

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/muncho_internal_support_playbook.md`

**Sections:**
- voucher/platform support triage
- BookNow/reservation triage
- frontend/widget triage
- backend/API triage
- devops/deploy/firewall triage
- Adventico ↔ SkyVision cross-system triage
- Customer Hermes dependency triage

**Acceptance criteria:**
- PASS if recurring classes become reusable procedures.
- PASS if one-off IDs/PRs/SHAs stay out of durable memory.

### Step 4.2 — Open questions and decisions log

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/internal_support_open_questions.md`
- `~/.hermes/notes/skyvision/internal-support/internal_support_decisions_log.md`

**Acceptance criteria:**
- PASS if unresolved business/technical policy is captured as explicit blocker.
- PASS if owner/team answers are converted into durable decisions only after evidence.

---

## Phase 5 — Codex-Assisted Internal Support Workflow

**Objective:** Use Codex for bounded deep audits, test/routing fixture design, patch proposals, and code review without making Codex a source of truth.

### Step 5.1 — Codex prompt contracts

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/codex_prompt_contract.md`

**Allowed Codex tasks:**
- sanitized audit reports;
- runbook drafts;
- test fixture proposals;
- code review;
- patch proposals in approved local/dev scope;
- reproduction checklist generation.

**Forbidden without separate approval:**
- PROD deploy;
- customer/partner messages;
- Shopify writes;
- voucher/booking/payment/order/customer mutations;
- secret reads/prints;
- destructive git;
- broad shell/local secrets/session DB access from cloud agents.

**Acceptance criteria:**
- PASS if every Codex run has scope, allowed paths, forbidden actions, expected output shape.
- PASS if Hermes/Muncho validates Codex results before presenting them as facts.

### Step 5.2 — Codex validation package

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/codex_validation_checklist.md`

**Checks:**
- diff/scope review;
- tests/smokes;
- secret scan;
- no protected data leak;
- no PROD/destructive action;
- evidence path validation;
- Bulgarian summary back to operator.

**Acceptance criteria:**
- PASS if Codex output is marked as `evidence candidate` until independently verified.

---

## Phase 6 — Muncho Bridge MVP for Managed Nodes

**Objective:** Define safe future bridge between local Muncho/master Hermes and managed cloud agents.

### Step 6.1 — Bridge contract

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/muncho_bridge_contract.md`

**MVP verbs:**
- `heartbeat`
- `alert`
- `knowledge_query`
- `eval_push`

**Security requirements:**
- HMAC signed requests;
- timestamp/replay protection;
- HTTPS except localhost dev;
- payload size limits;
- redaction before send;
- audit log;
- no mutation commands in MVP.

**Acceptance criteria:**
- PASS if a cloud node can report status/alerts/evals without seeing local secrets/session DB/Codex.
- PASS if mutation verbs are absent from MVP.

**Gate:** No broad shell, local secrets, local session DB, or Codex execution exposed to managed nodes without explicit Muncho-side approval.

---

## Phase 7 — Validation, Evals, and Regression Pack

**Objective:** Prove the copilot follows routing, evidence, safety, and approval rules.

### Step 7.1 — Scenario fixtures

**Artifacts:**
- `~/.hermes/notes/skyvision/internal-support/evals/internal_support_scenarios.md`

**Fixtures:**
- wrong resolver visibility;
- canonical handle mismatch;
- “sent/routed” claim without tool evidence;
- high-risk deploy approval missing;
- solved-by-resolver but not smoke-confirmed;
- customer Hermes dependency accidentally mixed into internal plan;
- raw PII/secret-looking payload in evidence;
- old/outdated source conflict.

**Acceptance criteria:**
- PASS if Muncho returns BLOCKED/NEEDS_INFO instead of hallucinating progress.
- PASS if exact approval phrase is requested for high-risk actions.

### Step 7.2 — Live pilot in this thread

**Artifacts:**
- Thread `1506738130521297046` operating note.
- Pilot case log under internal-support notes.

**Pilot behavior:**
- Use this thread for roadmap execution status.
- For each real case, announce phase/step when relevant.
- Return concise Bulgarian status with evidence and next action.

**Acceptance criteria:**
- PASS if Emil can review progress in this thread and see what requires his action.
- PASS if no live external/team action happens without explicit approval where needed.

---

## Files Likely to Change After Approval

Planning/docs first:

```text
~/.hermes/notes/skyvision/internal-support/discord_access_audit.md
~/.hermes/notes/skyvision/internal-support/discord_channel_scope.md
~/.hermes/notes/skyvision/internal-support/discord_history_ingestion_plan.md
~/.hermes/notes/skyvision/internal-support/cross_thread_case_graph.md
~/.hermes/notes/skyvision/internal-support/unified_status_brief_template.md
~/.hermes/notes/skyvision/internal-support/discord_history_tool_gap.md
~/.hermes/notes/skyvision/internal-support/muncho_internal_support_scope.md
~/.hermes/notes/skyvision/internal-support/source_registry.md
~/.hermes/notes/skyvision/internal-support/safety_classes.md
~/.hermes/notes/skyvision/internal-support/support_case_schema.md
~/.hermes/notes/skyvision/internal-support/resolver_routing_matrix.md
~/.hermes/notes/skyvision/internal-support/muncho_internal_support_playbook.md
~/.hermes/notes/skyvision/internal-support/internal_support_open_questions.md
~/.hermes/notes/skyvision/internal-support/internal_support_decisions_log.md
~/.hermes/notes/skyvision/internal-support/codex_prompt_contract.md
~/.hermes/notes/skyvision/internal-support/codex_validation_checklist.md
~/.hermes/notes/skyvision/internal-support/muncho_bridge_contract.md
~/.hermes/notes/skyvision/internal-support/evals/internal_support_scenarios.md
~/.hermes/notes/skyvision/internal-support/templates/intake_response.md
~/.hermes/notes/skyvision/internal-support/templates/resolver_handoff.md
~/.hermes/notes/skyvision/internal-support/templates/status_update.md
```

Potential code changes later, only after separate implementation approval:

```text
Hermes/Muncho runtime gates
Discord routing evidence validators
Kanban sync adapters
Bridge API handlers
Redaction/eval tests
```

---

## Risks / Tradeoffs

- **Risk:** Muncho becomes another messenger.  
  **Control:** every response must add triage/evidence/next-action value.

- **Risk:** False routing/delivery claims.  
  **Control:** delivery claims require tool evidence: target, thread ID, message ID.

- **Risk:** Customer Hermes work contaminates internal-support roadmap.  
  **Control:** thread and artifact separation; Customer Hermes is dependency only.

- **Risk:** Codex output treated as truth.  
  **Control:** Codex output is evidence candidate until Muncho validates.

- **Risk:** Protected data leaks into LLM/Codex.  
  **Control:** safety classes + redaction + stop gate for raw logs/secrets/customer/payment data.

- **Risk:** Over-automation of risky operations.  
  **Control:** exact approval phrases for high-risk actions; no mutation bridge MVP.

---

## Execution Start Checklist After Approval

1. Announce: `Започвам Фаза 0 / Step 0.1: Discord access & permissions audit.`
2. Audit current Hermes/Discord capability and identify whether history ingestion is available or needs implementation.
3. Create channel/thread allowlist proposal and tool-gap artifact.
4. Return PASS/FAIL with artifact paths and exact blocker/approval needs.
5. Continue to Phase 1 only if Phase 0 acceptance criteria pass or Emil explicitly approves a bounded implementation/backfill path.

---

## Final Approval Gate

No execution beyond this saved plan starts until Emil sends exactly:

```text
Одобрявам Muncho Internal Support Copilot roadmap v1.1 за execution в Discord thread 1506738130521297046.
```
