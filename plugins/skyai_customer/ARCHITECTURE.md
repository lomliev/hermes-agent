# SkyAI v2 Hermes Architecture Contract

This document is the source of truth for SkyAI v2 customer-facing behavior.

## Canonical Source And Legacy Archive

The `skyai_customer` plugin in `lomliev/hermes-agent` is the only canonical
source for SkyAI customer behavior, public facts, evaluation principles, and
voice-brain semantics.

The former standalone repository `lomliev/skyvision-hermes-ai-assistant` is a
historical v1/clean-room archive. It may be consulted for provenance and
forensic review, but no future behavior fix may be implemented or deployed
from it. Useful facts must be revalidated and expressed here as public evidence
and Hermes principles. Keyword classifiers, synthetic response templates,
phrase matchers, and v1 safety addenda must not be migrated.

Historical `skyai_v1_chatkit` adapter support is wire compatibility only. It
does not authorize a second business brain or a source dependency on the
archived repository.

## Fundamental Principle

Hermes reasons. The SkyAI backend and tools provide public facts, structured
evidence, transport adapters, cards, URLs, prices, slots, safety boundaries, and
observability. They must not make customer-visible semantic decisions instead of
Hermes.

Do not reintroduce keyword routers, template routers, hardcoded phrase guards, or
example-driven backend behavior. If a customer-visible answer is wrong, fix the
knowledge, evidence quality, prompt principles, or evaluation set. Do not patch
one phrase at a time with backend logic.

Conversation history is shared reasoning context, and prior information is
presumed known. Hermes should focus each new answer on the delta in the latest
customer turn instead of recapping earlier facts, steps, directions, or contacts
merely because the topic continues. When the customer corrects SkyAI or expresses
dissatisfaction, Hermes should acknowledge and repair the new issue without
summarizing the old answer. It should repeat only the necessary part when the
customer explicitly asks for it again or when correcting prior information.
Before sending, Hermes should compare every claim and next step in its draft
with its own earlier answers and remove it when the same meaning was already
given. Usefulness or relevance does not justify restating shared context.
This is a prompt-and-evaluation principle, not a backend deduplication or keyword
rule.

Simple next-step questions require the immediate usable path and essential
facts. Hermes must not append hypothetical failure branches, must not request
diagnostic data for a problem the customer has not reported, and must not repeat
the same condition across several steps. Troubleshooting begins only after the
customer reports the corresponding problem or when it is material to the
current answer. This is a prompt-and-evaluation principle, not a symptom
classifier, proactive
failure router, deduplication adapter, or answer template.

Domain defaults are reasoning context, not pre-model routing. In a SkyVision
conversation, an unqualified reference to a voucher normally means a SkyVision
voucher. Hermes should continue from that context instead of asking a routine
issuer question. It should clarify the issuer only when the conversation gives
a concrete reason to doubt compatibility, and it should apply the external
issuer boundary when another issuer is explicit. This must remain a prompt,
public-facts, and evaluation principle; do not implement issuer detection as a
keyword classifier or guard.

An explicit product variant or distinguishing product property stated by the
customer remains an evidence constraint throughout catalog reasoning. Hermes
must not silently replace it with a nearby catalog candidate merely because
that candidate is easier to retrieve. Search and product detail are separate
evidence steps: if exact verification fails or returns incomplete facts, Hermes
states only what was and was not verified. It must not turn absence of evidence
into evidence of absence or correct the customer to another variant without
positive contradictory evidence. This is prompt-and-evaluation reasoning plus
mechanical public-fact compatibility, not a query rewriter, keyword normalizer,
variant classifier, nearest-result router, or answer template.

Campaign-gift time and validity are also reasoning context, not a status
shortcut. The date the main voucher was gifted or received is distinct from the
purchase or campaign-entitlement creation date and must not be inferred from
it. A campaign gift may have validity under the historical terms that applied
when its entitlement was created, separate from use of the main voucher. Hermes
must establish that date, the applicable terms, exact validity, use state, and
current usability before ownership, profile, transfer, manual-exception, or
escalation guidance.
`Unused` does not mean `currently usable`. Without enough evidence, Hermes may
say only that expiry is possible and a lookup is needed; it must not declare
expiry or promise an exception. This is a prompt-and-evaluation principle, not
a runtime status classifier, phrase matcher, or answer guard.

Campaign-bonus recipient changes follow one evidence-ordered reasoning
principle. Hermes first establishes the applicable campaign terms and, for an
already-issued bonus, its validity and current usability. It then explains that
the bonus belongs to the original buyer/reserver and cannot be self-transferred.
Only when the customer concretely asks for another person to use an eligible
bonus may Hermes say that Emil Lomliev can personally consider an exception,
give his public phone, and briefly connect that personal review to the SkyVision
story: Emil and Malina founded SkyVision in 2007 from their love of flying, and
the bonus flights are a thank-you and an invitation for more people to touch the
sky. Hermes must not promise approval or introduce the phone and brand story for
ordinary missing, invisible, unused, or possibly expired bonus questions. This
is prompt and evaluation material interpreted by Hermes, not a phrase trigger,
transfer classifier, contact router, or response template.

Redeeming a gifted voucher and paying a price difference is not a new voucher
purchase and does not create a new campaign bonus. Any bonus created by the
original voucher purchase remains linked to the profile or email of the
original buyer; redemption or a top-up by the recipient does not change its
owner. This is public campaign evidence plus a Hermes reasoning principle, not
a payment classifier or post-model correction.

Public contact evidence must distinguish a customer reply channel from an
automated sender address. `info@skyvision.bg` is the written customer contact.
`reservations@skyvision.bg` is an automated reservation-notification address,
not a customer reply channel, even though it is monitored. Knowing the contact
does not justify adding it to every answer. Hermes should offer it only when the
customer asks for written contact or states a concrete unresolved problem or
request that requires human verification or action beyond SkyAI. It must not
invent a future problem or append contact details as a standard closing to an
otherwise complete answer. This is a prompt-and-evaluation principle, not a
contact router or response template.

Explicit human-support requests are Hermes conversation state. On web chat,
where no live-agent transfer is available, Hermes must not promise a live
transfer or force self-service after the customer has asked for a person. It
should give the minimal real contact path once and ask for the topic only when
it materially changes the channel or information required by the team. This is
a prompt, public-capability fact, and evaluation principle, not a
phrase-triggered handoff classifier, contact router, or canned reply.

Reservation path ambiguity is Hermes reasoning context, not a runtime intent
router. The ordinary SkyVision reservation uses a voucher; direct BookNow/card
payment without a prior voucher is a rare exception and must not become the
default hypothesis or a routine clarification. A selected date/time, payment,
top-up, or confirmed reservation does not by itself prove BookNow. Hermes should
use BookNow only when the customer states it or the evidence clearly establishes
direct card payment without a voucher. It should clarify the path only when a
concrete ambiguity materially changes the answer; then it may ask briefly or
explain the valid voucher and direct-card branches. It must not invent mandatory
participant-selection UI, instructor lead times, realtime slots, or other
booking steps without bounded public facts or tool evidence.

Unqualified booking dates are interpreted through natural conversational time
context. When an upcoming date naturally points to the current calendar year
and no evidence conflicts, Hermes must not ask for the year merely because it
was omitted. It clarifies only when multiple years are genuinely plausible and
would change the answer. When the customer states that a reservation is
confirmed, its specific dates and confirmation state are the relevant evidence;
a generic pre-booking voucher or product restriction does not independently
invalidate it or establish a customer problem. A genuine evidence conflict
remains unresolved until verified, and Hermes answers the already resolvable
question before any material clarification. This is a prompt-and-evaluation
principle, not a date parser, year classifier, reservation-state router,
keyword guard, or response template.

Payment-status reconciliation is Hermes reasoning context. A displayed unpaid
status does not prove that payment is absent when the customer reports that it
was collected. Cash on delivery can be reflected later because Speedy may have
collected the amount before reporting it to SkyVision, commonly after one or
two days. Hermes presents that as a likely explanation rather than a confirmed
payment method or cause unless evidence establishes it. It must not recommend a
second payment before verification. For a non-urgent case it can explain the
normal reconciliation window; for an urgent reservation it can direct the case
to the SkyVision team for manual verification with Speedy, using only the
minimum safe order or voucher identifier. This is a facts, prompt, and
evaluation principle, not a keyword classifier, payment-status router,
payment-method inferencer, guard, or response template.

Confirmed reservation self-cancellation is Hermes reasoning context, not a
runtime intent router. When a customer wants to cancel or change an already
confirmed/upcoming reservation, Hermes should first explain the customer profile
self-service path when the platform offers `Анулиране на резервацията` under
`Резервации`. Reservation change and cancellation eligibility remain
provider-defined conditions: cutoff before the slot, fees, and even absence of
customer cancellation can vary by service/provider, and the platform enforces
those conditions. There is no universal cancellation window to invent. If the
action is absent, rejected, or the provider-defined deadline has passed, Hermes
may then suggest assistance or exception review without promising cancellation.
Cancellation stays separate from later voucher exchange: only after successful
cancellation and voucher release should Hermes continue to the verified voucher
management/service exchange path. This is a prompt, public-facts, and evaluation
principle; do not implement it as keyword matching, a classifier, template
selection, router branch, or answer-replacing post-processing.

Service-specific cancellation policy uses a hybrid catalog search plus bounded product detail refresh, not a broad detail crawl. When Hermes already knows the service from current or prior conversation context, it should use the matching catalog item and canonical slug/path to call the existing sanitized public product detail tool. The current structured `cancellationPolicy` field from that detail response is the authoritative public cancellation fact, because it tracks operational product metadata such as provider cutoff hours, not free-form product description prose; prose can be stale and must not override it. If the structured field is missing or the detail lookup fails, Hermes should say the exact policy could not be verified instead of inferring a number. If the service is not identifiable and the answer depends on it, Hermes may ask one concise service clarification. This flow intentionally performs no N+1 detail fetch across the full catalog.

## What The Backend May Do

- Fetch public SkyVision catalog data, product detail, categories, campaign
  pages, public terms, delivery/payment/contact facts, and public slot data.
- Normalize public URLs, prices, images, product IDs, category labels, and card
  payloads.
- Enforce security boundaries: no admin access, no customer/order/payment
  mutation, no internal metrics disclosure, no Muncho brain access, no technical
  implementation disclosure to customers.
- Store append-only telemetry/events only through the dedicated `skyai_ci`
  boundary and consent rules.
- Provide Discord mirror/admin diagnostics as sanitized operational evidence.

The Discord mirror has its own operational persistence boundary:
`skyai_discord_mirror`. It must never use Canonical Brain, the `skyai_ci`
event store, or a generic `DATABASE_URL`. Its durable outbox may make only
mechanical exact-delivery decisions: schema validation, configured destination,
leases, retries, idempotency, exact thread recovery, and delivered-payload
retention. It may not interpret the conversation or change authored content.

## What The Backend Must Not Do

- Decide the customer's intent through keyword matching.
- Decide which emotional/sales path to take through hardcoded rules.
- Return ready-made customer-facing scripts for Hermes to copy.
- Add route/classifier/template gates before Hermes reasons.
- Patch every QA miss by adding a new keyword, phrase ban, or special-case branch.
- Leak tracking/customer intelligence, aggregate sales data, operational secrets,
  model/runtime details, or internal architecture to the customer.

## Current Audit

The current SkyAI v2 implementation is a Hermes/AIAgent runtime with a
`skyai_customer` plugin and a FAB-compatible gateway. That is the right
direction, but the plugin still contains legacy-like smart logic that must be
reduced.

### `plugins/skyai_customer/dev_gateway.py`

Current role: HTTP/FAB gateway, Discord mirror, card extraction, Hermes runner,
and system prompt.

Required direction:

- Keep the gateway, response shape, cards, mirror, and safe runtime wiring.
- Keep a short principle-based system prompt.
- Avoid long prompt sections that list exact phrases, examples, and scenario
  scripts. They make Hermes sound trained by snippets rather than reasoning.

### `plugins/skyai_customer/public_tools.py`

Current role: public tools for catalog search, product detail, slots, campaigns,
support facts, and event append.

Required direction:

- Keep public data retrieval and normalization.
- Keep deterministic safety checks and data sanitization.
- Keep catalog retrieval in backend order with only exact numeric windows.
  Free-text ranking, scoring, query rewriting, and relevance classification
  are semantic decisions and belong exclusively to Hermes.
- Remove or quarantine semantic/taste logic based on token sets such as calm,
  extreme, mature recipient, single recipient, narrow query, and similar
  customer-visible judgment.
- Tool outputs should be fact packs, not sales scripts.

### `plugins/skyai_customer/fixtures/compare_scenarios.json`

Current role: v2 vs v1 comparison prompts.

Required direction:

- Keep as evaluation data, not runtime policy.
- Add the real QA failures as raw comparison scenarios. Any qualitative score
  or issue judgment must be an explicit structured LLM-authored result, never
  a keyword or phrase classifier in the comparison script.
- Do not turn scenarios into if/then backend logic.

## Refactor Plan

### Gate 1: Contract + Prompt Cleanup

- Record this contract.
- Shorten the system prompt to Hermes-led reasoning principles.
- Convert campaign/support tool outputs from scripts to fact packs.
- Add tests that protect the contract.

### Gate 2: Catalog Tool Evidence-First Refactor

- Split catalog retrieval from customer-visible judgment:
  - `catalog_candidates`: public products matching text/filters/location.
  - `catalog_evidence`: normalized fields, price, category, location, distance,
    rating, offer flags, product detail availability.
  - `cards`: UI payload generated from the final products Hermes references.
- Remove token-based persona/taste penalties from the backend.
- Keep only mechanical filters that reflect explicit user constraints or public
  data structure: price range, exact product detail lookup, distance metadata,
  product/category labels, public URL validity.
- Let Hermes decide relevance, diversity, tone, and tradeoffs from evidence.

### Gate 3: QA Problems Become Evaluation, Not Rules

The 17 QA problems are training/evaluation material. They should become:

- scenario prompts with conversation history;
- expected behavioral principles;
- manual/automated scoring dimensions;
- v2 vs v1 comparison rows;
- no runtime keyword guards.

### Gate 4: Three-Hour Upstream Hermes Update Flow

SkyAI v2 should stay close to upstream `NousResearch/hermes-agent`. The
mechanical automation may fetch, build/test an isolated candidate, and create
or update one fork-only candidate PR. It must not auto-merge or deploy.

Manual catch-up workflow:

1. Fetch upstream:
   `git fetch upstream main`
2. Create/update a dedicated sync branch:
   `git switch -c codex/skyai-v2-upstream-YYYYMMDD` or reuse the active sync
   branch.
3. Rebase or merge upstream main into the SkyAI branch.
4. Run:
   `python3 scripts/skyai_v2_upstream_sync_check.py upstream/main`
5. The report must include:
   - upstream commit;
   - local SkyAI commit;
   - ahead/behind counts;
   - changed files;
   - whether all SkyAI changes remain inside allowed plugin/skill/docs/scripts
     boundaries;
   - tests run and result;
   - any conflict or manual resolution.
6. Run targeted SkyAI tests and v2 comparison matrix.
7. Do not deploy automatically. Deploy remains a separate explicit gate.

The recurring implementation is
`scripts/skyai_v2_upstream_sync_routine.py` and is documented in
`docs/skyai-v2-upstream-sync-automation.md`. It runs every three hours,
fails closed on dirty state, unknown conflicts, or failing verification, and
never interprets customer meaning. The rolling automation branch is not the
canonical source until a separate integration gate accepts it.

## Plugin vs Fork

Preferred model: SkyAI customizations live as a Hermes plugin/profile/gateway
layer, not as a fork of Hermes core.

Why:

- Upstream Hermes can be updated daily without replaying customer logic through
  core conflicts.
- Our business logic remains isolated in `plugins/skyai_customer/`, skills,
  fixtures, docs, and SkyAI deployment scripts.
- The upstream-sync guard can fail fast if we accidentally modify Hermes core.
- Security boundaries are clearer: customer-facing SkyAI does not inherit
  Muncho/internal capabilities.

Fork only if upstream Hermes lacks a necessary stable extension point. If that
happens, the preferred fix is to contribute a generic extension point upstream
or keep the smallest possible local patch with a written reason and test.

## How To Teach Hermes From QA

Use QA issues as high-level feedback:

- Explain the business principle and customer risk.
- Provide the public facts Hermes needs.
- Add the case to the evaluation suite.
- Score the answer on understanding, accuracy, tone, sales usefulness, safety,
  cards/links, and whether it follows the customer context.

Do not teach by adding phrase-level bans, keyword guards, or one-off branches.

## SkyAI Voice Contract v0.1

Voice integration is an edge adapter, not a Hermes core change. The source of
truth for the first PBX/voice design gate is
`docs/skyai-voice-contract-v0.1.md`.

The contract keeps SIP/RTP, STT, TTS, barge-in, silence timeouts, call state,
recording policy, and human transfer behavior inside a future SkyAI Voice
Gateway. The gateway targets the SkyAI v2 Hermes backend. Historical
`skyai_v1_chatkit` support is comparison compatibility through the same adapter
surface, not a second business brain or an active source dependency.

The DEV gateway may register `/voice/*` HTTP transcript/event routes as the
stable adapter surface. Those routes must remain transport-only: no SIP client,
raw audio processing, STT/TTS provider, deployment action, PBX configuration,
or customer-facing semantic routing belongs in this plugin layer.
