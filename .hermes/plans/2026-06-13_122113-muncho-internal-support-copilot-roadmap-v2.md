# Muncho Internal Support Copilot Roadmap v2.0

> **Status:** OWNER APPROVED for Phase 0 start.  
> **Approval received in Discord thread:** `1506738130521297046`  
> **Approval phrase:** `ОДОБРЯВАМ MUNCHO INTERNAL SUPPORT COPILOT ROADMAP V2.0: започни Phase 0 architecture/hosting lock за Local-first Muncho + Cloud Standby/Failover Muncho + Canonical Brain.`

## Goal

Да изградим **Muncho Internal Support Copilot** за вътрешна оперативна поддръжка в Discord thread:

```text
1506738130521297046
```

Copilot-ът трябва:

- да работи **local-first** от MacBook-а, когато локалният Мунчо е online;
- да има **cloud standby/failover Muncho**, когато MacBook-ът е изключен/offline или owner изрично превключи към cloud;
- да пази обща canonical памет, approvals, traces, workflow state и locks;
- да помага с evidence-first triage, routing, runbook learning и bounded Codex-assisted workflows;
- да избягва split-brain, double replies и double Codex tasks чрез active runtime lease;
- да не смесва internal operator tooling с customer-facing chatbot продукта.

Customer Hermes / chatbot продуктът остава отделен workstream в thread:

```text
1507026708702826617
```

---

## Target Architecture

```text
Discord Internal Support Thread
        |
        v
Runtime Router / Health / Lease
        |
        +-- Local Muncho on MacBook
        |     - default active runtime
        |     - Discord gateway/routing
        |     - Hermes/Muncho runtime
        |     - GPT via local owner OAuth lane
        |     - Codex CLI worker
        |     - local tools/profile/repos
        |
        +-- Cloud Standby/Failover Muncho
              - activated on local offline/manual switch
              - Hermes/Muncho runtime
              - Discord gateway/routing
              - GPT via owner-approved cloud OAuth lane
              - Codex CLI worker
              - Git/tooling
              - encrypted persistent cloud home/profile

Canonical Brain
        |
        +-- Git knowledge pack
        +-- Postgres event/trace/approval/workflow store
        +-- Redis locks/cache/session state
```

---

## Core Decision

Избраният модел е:

```text
Local-first Muncho + Cloud Standby/Failover Muncho + Canonical Brain
```

Това означава:

1. **Локалният Мунчо е default.**
2. **Cloud Мунчо не е отделен “втори мозък”, а standby runtime към същия canonical brain.**
3. **Екипът работи в същия Discord lane**, независимо кой runtime е активен.
4. **Cloud Мунчо трябва да е реална алтернатива**, не просто queue/helper.
5. **Само един runtime може да бъде active в даден момент.**

---

## Runtime Rules

Default runtime:

```text
local-muncho
```

Cloud Muncho става active само ако:

- local gateway е offline/unhealthy;
- active runtime lease изтече;
- owner изрично одобри switch to cloud;
- owner стартира manual cloud override;
- local runtime е paused/maintenance.

Когато local Muncho се върне online, системата **не трябва автоматично да прави опасен switch-back**, ако има active cloud task. Връщането към local трябва да е:

- автоматично само ако няма active work;
- или owner-approved, ако cloud runtime има активни Codex/tasks/cases.

---

## Canonical Brain

Canonical Brain е shared source of truth между local и cloud.

### 1. Git Knowledge Pack

Съдържа:

- support runbooks;
- routing rules;
- known decisions;
- escalation templates;
- safety policies;
- Codex task policies;
- customer/internal boundary rules;
- owner-approved learning.

Примерна структура:

```text
muncho-knowledge/
  internal-support/
    runbooks/
    routing/
    templates/
    decisions/
    safety/
    codex/
  customer-hermes-shared/
    customer-safe-rules/
  evals/
    internal-support/
```

### 2. Postgres

Съдържа:

- Discord events;
- support cases;
- message traces;
- approvals;
- workflow runs;
- Codex task records;
- routing decisions;
- audit records;
- runtime switch history.

### 3. Redis / Valkey

Съдържа краткоживеещо runtime state:

- active runtime lease;
- message idempotency locks;
- Codex task locks;
- cache;
- session state;
- failover election markers.

Redis не е source of truth. Ако Redis падне, системата трябва да fail-close за actions, които могат да доведат до double replies/tasks.

---

## Active Runtime Lease

Преди runtime да направи каквото и да е от следните:

- да отговори в Discord;
- да route-не case;
- да стартира Codex;
- да пише workflow decision;
- да изпрати handoff;
- да маркира case като resolved;

той трябва да държи валиден active lease.

Минимален модел:

```text
active_runtime: local | cloud | paused
lease_owner: local-muncho | cloud-muncho
lease_expires_at: timestamp
manual_override: none | force-local | force-cloud | pause-all
```

---

## Cloud OAuth Policy

### Позволено

- Owner прави отделен interactive login в cloud runtime със същия акаунт.
- Cloud runtime пази собствен cloud Hermes/Codex profile.
- Cloud credentials се пазят в encrypted persistent storage.
- Cloud Muncho може да използва GPT/OAuth lane и Codex CLI worker за internal operator usage.

### Забранено

- Не копираме директно локални OAuth/auth файлове от MacBook-а.
- Не качваме `~/.hermes/auth.json`, `~/.codex/auth.json`, browser cookies или локални session files като artifact.
- Не вкарваме operator OAuth credentials в customer-facing assistant.
- Не използваме cloud operator OAuth за публичен customer chatbot backend.

### Kill / revoke plan

Трябва да има процедура за:

- disable cloud runtime;
- revoke OAuth session;
- destroy encrypted profile volume;
- rotate router/bridge tokens;
- audit recent cloud actions;
- switch active runtime to local or paused.

---

## Customer Hermes Boundary

Customer Hermes / chatbot продуктът:

- остава в отделен thread `1507026708702826617`;
- има отделен runtime/policy;
- не наследява internal operator OAuth;
- не получава Codex/internal tools;
- може да чете само customer-safe approved knowledge;
- може да бъде dependency/source за Internal Support case, но не се смесва execution thread-ът.

---

# Phase 0 — Architecture Lock and Hosting Decision

## Objective

Да заключим архитектурните решения преди implementation.

## Steps

### Step 0.1 — Confirm target architecture

Потвърждаваме:

- Local-first Muncho;
- Cloud Standby/Failover Muncho;
- Canonical Brain;
- active runtime lease;
- Codex като bounded worker;
- Customer Hermes separation.

### Step 0.2 — Choose cloud standby mode

Варианти:

#### A) Cold standby

Cloud VM е stopped/offline, стартира се при нужда.

**Плюс:** най-евтино.  
**Минус:** failover може да отнеме 1–5 минути.

#### B) Warm standby

Cloud VM работи, но heavy worker/Codex не е постоянно активен.

**Плюс:** по-бързо failover.  
**Минус:** има постоянен VM разход.

#### C) Minimal always-on router + on-demand worker

Малък router/health service работи постоянно, cloud Muncho worker се стартира при нужда.

**Плюс:** добър баланс.  
**Минус:** по-сложна архитектура.

#### D) Always-on cloud Muncho

Cloud Muncho работи постоянно.

**Плюс:** най-просто operationally.  
**Минус:** най-висок постоянен разход.

### Step 0.3 — Hosting decision

За full alternative runtime препоръката е:

```text
VM / cloud workstation > Render web service
```

Причина: Cloud Muncho има нужда от:

- persistent encrypted home/profile;
- interactive OAuth login;
- Codex CLI;
- PTY;
- Git/tooling;
- long-running jobs;
- watchdog/system service.

Render остава подходящ за:

- Postgres/Redis/data-plane;
- helper APIs;
- lightweight router;
- monitoring endpoints.

### Step 0.4 — Define failover rules

Да се определи:

- heartbeat interval;
- lease TTL;
- local offline threshold;
- manual override commands;
- recovery behavior;
- switch-back policy;
- who can approve runtime switch.

### Step 0.5 — Define credential policy

Да се документира:

- no local OAuth file copy;
- separate cloud login;
- encrypted persistent cloud profile;
- revoke/kill process;
- operator/customer credential separation.

## Acceptance Criteria

PASS ако:

- target architecture е одобрена;
- standby mode е избран за MVP;
- hosting decision е документиран;
- active runtime lease policy е описана;
- OAuth handling policy е приета;
- Customer Hermes separation е потвърдена.

---

# Phase 1 — Canonical Brain MVP

## Objective

Да създадем shared state layer, на който local и cloud runtime-и се доверяват.

## Steps

### Step 1.1 — Git knowledge pack contract

Да се дефинират:

- папки;
- owner;
- review flow;
- versioning;
- release/tag policy;
- customer-safe vs internal-only rules.

### Step 1.2 — Postgres conceptual schema

Минимални таблици/обекти:

- `discord_events`;
- `support_cases`;
- `case_links`;
- `approvals`;
- `runtime_events`;
- `codex_tasks`;
- `routing_decisions`;
- `audit_log`;
- `knowledge_versions`.

### Step 1.3 — Redis lock model

Locks:

- `active_runtime_lease`;
- `message_processing_lock`;
- `codex_task_lock`;
- `case_update_lock`;
- `runtime_switch_lock`.

### Step 1.4 — Audit event model

Всеки significant action записва:

- timestamp;
- runtime;
- actor/requester;
- Discord thread/message;
- evidence refs;
- decision;
- approval status;
- result;
- risk class.

## Acceptance Criteria

PASS ако:

- local/cloud имат общ state contract;
- every action може да се trace-не;
- duplicate replies са предотвратими;
- duplicate Codex tasks са предотвратими;
- knowledge pack има owner-reviewable initial structure.

---

# Phase 2 — Local Muncho as Primary Runtime

## Objective

Да направим локалния Мунчо default production lane за Internal Support Copilot.

## Steps

### Step 2.1 — Local runtime heartbeat

Local Muncho изпраща heartbeat към Canonical Brain / router.

### Step 2.2 — Lease acquisition

Local runtime взима lease, когато:

- е healthy;
- няма manual cloud override;
- cloud не държи active task lease;
- Redis/Postgres са reachable или има safe degraded policy.

### Step 2.3 — Evidence-first triage behavior

Всяка internal support реакция трябва да включва:

```text
VERDICT
TL;DR
CATEGORY
EVIDENCE_CHECKED
EVIDENCE_GAP
OWNER/RESOLVER
STATUS
NEXT_ACTION
APPROVAL_NEEDED
RISK
```

### Step 2.4 — Local Codex workflow

Локалният Мунчо продължава да използва Codex като bounded worker, но:

- task scope е explicit;
- repo/file scope е explicit;
- output е evidence candidate до Hermes/Muncho validation;
- no destructive/PROD actions без approval.

## Acceptance Criteria

PASS ако:

- local Muncho е default active runtime;
- отговаря само с active lease;
- записва traces/approvals/events;
- triage-ва с evidence;
- Codex задачите са bounded;
- Customer Hermes runtime не се пипа.

---

# Phase 3 — Cloud Standby / Failover Muncho

## Objective

Cloud Muncho да стане реална алтернатива на локалния Мунчо.

## Steps

### Step 3.1 — Provision cloud environment

Изборът се прави във Phase 0, но environment трябва да поддържа:

- persistent encrypted storage;
- Hermes runtime;
- Codex CLI;
- Git/tooling;
- long-running processes;
- watchdog;
- restricted access;
- audit logs.

### Step 3.2 — Install Hermes/Muncho

Cloud runtime трябва да има:

- Hermes/Muncho;
- Discord gateway/routing;
- required toolsets;
- skills/knowledge sync;
- config isolation;
- no copied local auth files.

### Step 3.3 — Owner cloud OAuth login

Owner прави interactive login в cloud runtime.

Policy:

```text
Allowed: separate cloud login with owner account.
Forbidden: copying local auth/session files.
```

### Step 3.4 — Configure Codex CLI worker

Cloud runtime трябва да може:

- да стартира Codex CLI;
- да работи в bounded worktree;
- да пази logs/audit;
- да спира при auth/session failure;
- да не пипа PROD/destructive actions без exact approval.

### Step 3.5 — Connect to Canonical Brain

Cloud runtime използва същите:

- Git knowledge pack;
- Postgres;
- Redis lease/locks;
- safety policies.

### Step 3.6 — Cloud kill/revoke path

Документирана процедура:

- disable cloud runtime;
- revoke OAuth;
- rotate tokens;
- destroy encrypted profile if needed;
- audit last actions;
- force active runtime to local/paused.

## Acceptance Criteria

PASS ако:

- cloud Muncho може да поеме thread-а при offline local;
- cloud runtime използва separate login, not copied auth files;
- credentials са encrypted at rest;
- cloud runtime obeys same safety gates;
- cloud не отговаря без active lease;
- owner може да го kill/revoke-не.

---

# Phase 4 — Runtime Router, Lease and Failover UX

## Objective

Екипът да вижда един Copilot lane, а системата да предотвратява split-brain.

## Steps

### Step 4.1 — Router/health service design

Router следи:

- local health;
- cloud health;
- active runtime;
- lease owner;
- manual override;
- degraded status.

### Step 4.2 — Owner commands

Команди:

```text
MUNCHO STATUS
MUNCHO SWITCH CLOUD
MUNCHO SWITCH LOCAL
MUNCHO PAUSE ALL
MUNCHO RESUME
MUNCHO KILL CLOUD
```

Български aliases:

```text
МУНЧО СТАТУС
ПРЕВКЛЮЧИ КЪМ CLOUD MUNCHO
ВЪРНИ КЪМ LOCAL MUNCHO
СПРИ ВСИЧКИ ОТГОВОРИ
ПУСНИ ОТГОВОРИТЕ
СПРИ CLOUD MUNCHO
```

### Step 4.3 — Idempotency

Всеки Discord event получава idempotency key:

```text
discord:{channel_id}:{thread_id}:{message_id}
```

Всеки Codex task:

```text
codex:{case_id}:{task_hash}
```

### Step 4.4 — Failover drill

Test scenarios:

1. local online → local replies;
2. local offline → cloud takes lease;
3. local returns → no automatic unsafe switch;
4. manual switch cloud;
5. manual switch local;
6. double event delivery → one reply only;
7. cloud killed → paused/degraded mode.

## Acceptance Criteria

PASS ако:

- local/cloud не могат да отговорят едновременно;
- runtime switch е visible/auditable;
- owner вижда кой runtime е active;
- failover работи при simulated local offline;
- degraded mode не hallucinate-ва progress.

---

# Phase 5 — Discord History Ingestion and Case Graph

## Objective

Muncho да има unified operational context, а не fragmented thread-local memory.

## Steps

### Step 5.1 — Channel/thread allowlist

Да се одобри точен allowlist:

- кои channels/threads се четат;
- кои са read-only;
- кои са action/routing lanes;
- кои са forbidden.

### Step 5.2 — History ingestion

Ingest:

- message ID;
- author;
- timestamp;
- channel/thread;
- reply refs;
- attachments metadata;
- edits/deletes;
- mentions.

Без raw secrets/customer/payment payloads в LLM/Codex prompts.

### Step 5.3 — Case graph

Graph links:

- same issue;
- same resolver;
- same blocker;
- same Customer Hermes dependency;
- same Codex task;
- same approval.

### Step 5.4 — Evidence retrieval

Muncho трябва да може да каже:

```text
Това го знам от:
- message X в thread Y
- decision Z
- runbook version N
```

## Acceptance Criteria

PASS ако:

- Muncho може да даде status across threads с evidence refs;
- repeated issues се link-ват;
- conflicting facts се маркират като conflict;
- Customer Hermes context не се смесва без explicit dependency.

---

# Phase 6 — Routing and Runbook Learning

## Objective

Muncho да помага активно, не само да препраща.

## Steps

### Step 6.1 — Support categories

Категории:

- backend/API;
- frontend/widget/UI;
- DevOps/GitLab/GCP/Cloudflare/cPanel;
- voucher/platform support;
- BookNow/reservation;
- payment/checkout;
- email/PDF;
- Customer Hermes dependency;
- unknown/needs owner.

### Step 6.2 — Resolver routing matrix

Baseline:

- BE/API → Алекс/Ивчо lane;
- FE/UI/widget → Фатих lane;
- DevOps/infra → Кожухаров lane;
- support ops/booking → relevant support lane;
- owner decisions → control tower.

### Step 6.3 — Confidence policy

- high confidence → propose next action;
- medium confidence → ask exact clarifying question;
- low confidence → owner decision needed.

### Step 6.4 — Runbook learning

Resolved cases produce:

- candidate runbook update;
- owner review;
- Git knowledge pack update;
- version bump.

## Acceptance Criteria

PASS ако:

- routing is consistent;
- Muncho asks exact missing-info questions;
- runbook updates are owner-reviewed;
- low-confidence cases are not over-automated.

---

# Phase 7 — Codex-Assisted Workflow with Safety Gates

## Objective

Codex да помага за engineering/support задачи, но Muncho да остане orchestrator.

## Allowed Codex Tasks

- read-only investigation;
- narrow DEV/local patch;
- test/log analysis;
- runbook/documentation update;
- reproduction checklist;
- code review;
- bounded PR/diff proposal.

## Forbidden Without Separate Approval

- PROD mutation;
- customer/order/voucher/payment/booking mutation;
- Shopify writes;
- destructive git;
- secrets reads/prints;
- broad unsupervised refactor;
- external/customer communication;
- deploy/merge/push without explicit approval.

## Steps

### Step 7.1 — Codex task contract

Всеки Codex task има:

- title;
- case ID;
- runtime owner;
- repo/path scope;
- allowed files/actions;
- forbidden files/actions;
- expected output;
- approval status.

### Step 7.2 — Codex lock

Само runtime с active lease може да стартира Codex.

### Step 7.3 — Validation

След Codex:

- diff review;
- tests/smoke;
- secret scan;
- no PROD/destructive check;
- Bulgarian summary to owner/thread.

## Acceptance Criteria

PASS ако:

- няма duplicate Codex tasks при failover;
- Codex output не се третира като истина без validation;
- owner може да pause/kill/reject Codex task;
- high-risk actions искат exact approval.

---

# Phase 8 — Hardening, Monitoring and Owner Review

## Objective

Да подготвим системата за надеждна вътрешна употреба.

## Monitoring

Следим:

- local runtime health;
- cloud runtime health;
- active lease;
- Discord gateway;
- Postgres;
- Redis;
- Codex worker;
- OAuth status;
- event lag;
- failed/suppressed actions.

## Audit Reports

Daily/weekly summary:

- active cases;
- approvals requested;
- actions taken;
- blocked actions;
- routing corrections;
- Codex tasks;
- failover events;
- safety gate triggers.

## Disaster Recovery

Runbooks:

- cloud kill/revoke;
- local recovery;
- Redis unavailable;
- Postgres unavailable;
- OAuth invalidated;
- duplicate Discord events;
- cloud VM compromised/suspected;
- owner account revoke.

## Acceptance Criteria

PASS ако:

- failover е тестван;
- split-brain prevention е тестван;
- kill/revoke е тестван;
- owner може да разбере какво е направил Muncho и защо;
- system е готов за limited team rollout.

---

# Main Risks and Controls

## Risk 1 — Split-brain / double replies

**Risk:** local и cloud отговарят едновременно.  
**Control:** active runtime lease, Redis locks, idempotency keys, audit before action.

## Risk 2 — OAuth credential exposure

**Risk:** cloud runtime пази owner OAuth.  
**Control:** no local copy, separate login, encrypted storage, revoke/kill path, no customer assistant access.

## Risk 3 — Cloud Muncho не е реална алтернатива

**Risk:** cloud приема messages, но не може да прави GPT/Codex work.  
**Control:** cloud runtime трябва да има Hermes, GPT OAuth lane, Codex CLI, Git/tooling, persistent profile.

## Risk 4 — Customer/Internal boundary confusion

**Risk:** Customer Hermes наследява internal tools/OAuth.  
**Control:** separate runtime, separate thread, customer-safe knowledge only.

## Risk 5 — Codex overreach

**Risk:** Codex действа извън scope.  
**Control:** Codex is bounded worker, task contracts, approvals, no destructive/PROD actions.

## Risk 6 — Hosting mismatch

**Risk:** Render/web-service hosting не е удобен за OAuth/Codex/PTY/long jobs.  
**Control:** Phase 0 hosting decision; full alternative runtime предпочита VM/cloud workstation.

---

# Recommended MVP Path

Редът за изпълнение след одобрение:

1. **Phase 0:** Architecture/hosting lock.
2. **Phase 1:** Canonical Brain contract.
3. **Phase 2:** Local Muncho as primary.
4. **Phase 4:** Router/lease/failover UX.
5. **Phase 3:** Cloud standby as real alternative.
6. **Phase 5:** Discord history ingestion and case graph.
7. **Phase 6:** Routing/runbook learning.
8. **Phase 7:** Codex-assisted workflows.
9. **Phase 8:** Hardening and team rollout.

Забележка: Phase 4 идва преди Phase 3 в MVP execution, защото lease/router моделът трябва да е ясен преди cloud runtime да започне да отговаря.

---

# Execution Start Checklist

1. Записване на този roadmap като официален execution plan.
2. Създаване на Phase 0 architecture/hosting lock artifact.
3. Фиксиране на Phase 0 decisions/open questions.
4. Спиране преди реален cloud provisioning, credential setup, OAuth login или live gateway/routing промяна без отделно explicit approval.

---

# Next Approval Gates

След Phase 0 трябва отделно да бъдат одобрени:

- exact hosting provider/model;
- standby mode;
- дали да се provisioning-ва VM/cloud workstation;
- дали да се прави interactive cloud OAuth login;
- дали да се стартира cloud runtime;
- дали да се свързва към Discord lane;
- дали да се активира failover router/lease service.
