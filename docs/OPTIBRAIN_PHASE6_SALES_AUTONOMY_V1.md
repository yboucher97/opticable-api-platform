# OptiBrain Phase 6 — Sales Autonomy v1

Status: engineering contract created 2026-09-28. No production change is authorized by this document.

## Baseline and release identity

- Repository: `yboucher97/opticable-api-platform`
- Phase 6 branch: `phase6/sales-autonomy-v1`
- Exact Phase 5 production/main baseline: `52f11d4fc14d8582c03837e0317f849efe8aa3d7`
- Phase 5 recovery tag: `recovery/post-phase5-business-autonomy-v1-20260928`
- Starting API: `1.10.0`
- Starting automation schema: `2`
- Target API for the first Phase 6 candidate: `1.11.0`
- Database migration is not required for the initial Phase 6 scope. Existing schema-V2 durable events, runs, audit/journal, approvals and workflow definitions remain the control plane.

Phase 6 starts only from the exact verified Phase 5 identity. Production, `main`, the Phase 5 recovery tag, the protected Cloudflare diagnostic and the root-owned recovery runbook are not modified during engineering.

## Objective

Convert the Phase 5 observe-first lead lifecycle into a bounded sales-operations assistant that can keep Opticable's sales queue organized without silently becoming an autonomous salesperson.

Phase 6 v1 may autonomously perform low-risk internal operations that are reversible and independently verifiable. It may prepare customer communication, but it must not send external customer communication without explicit human approval. Zoho Books remains read-only/human-approved. Lead conversion and Deal/Contact/Account creation from an existing Zoho Lead remain outside the automatic path until identity and rollback contracts are proven separately.

## Existing capabilities reused rather than duplicated

Phase 5 already provides:

- authenticated/deduplicated Zoho Lead notifications plus bounded CRM delta fallback;
- versioned lead review events and durable internal follow-up evidence;
- optional conditional normalization updates and one deterministic internal CRM Task per active Lead under policy `phase5-lead-v1`;
- `Leads.Service_Types` and `Leads.Next_Followup_At` as canonical optional fields;
- exact write-intent journaling, no-blind-retry behavior and provider readback;
- native notification drift/renewal monitoring;
- synthetic delivery proof that cannot masquerade as provider-origin evidence.

The broader lifecycle layer already provides:

- mailbox observation and durable email intake;
- AI-assisted qualification and email analysis;
- Zoho Mail draft creation;
- an explicitly approved reply action;
- approval-gated contract sending;
- read-only Books observation.

Phase 6 connects these existing primitives. It does not invent a second event bus, a second approval system or a second provider-write journal.

## Safety invariants

These are release blockers, not recommendations.

1. **Books remains human-approved/read-only by default.** Phase 6 introduces no autonomous Books create/update/delete action.
2. **No autonomous customer send.** Email/SMS/phone/customer-facing message transmission requires an explicit durable human approval tied to the exact recipient, content hash and source Lead/message identity.
3. **No autonomous Lead conversion or Account/Contact/Deal creation from an existing Zoho Lead.** Existing lifecycle promotion code remains outside the automatic Phase 6 Lead workflow.
4. **No owner reassignment.** Existing Zoho ownership remains authoritative.
5. **No destructive CRM metadata changes.** No field/layout/workflow deletion, no legacy webhook retirement and no high-risk Desired State mutation.
6. **No secret/customer body persistence in audit metadata.** Audit/journal evidence stores identities, hashes, bounded categories and provider operation IDs only.
7. **No blind provider retry.** Any ambiguous write outcome remains `human_action_required` until exact readback reconciliation proves success.
8. **AI never authorizes a write or send by itself.** AI output may classify, summarize or draft. Deterministic policy and/or explicit approval decides whether an operation is allowed.
9. **Stale record protection.** CRM Lead writes use the reviewed record version and `If-Unmodified-Since`; a changed Lead becomes superseded and is re-reviewed.
10. **Observe mode is the rollback.** Disabling the Phase 6 policy must stop new sales mutations without deleting Phase 5 fields, tasks, audit evidence or historical drafts.

## Phase 6 v1 functional scope

### 1. Deterministic sales decision object

Create a bounded `SalesDecision` derived from a versioned Lead snapshot. It contains only decision metadata, not raw message bodies.

Required fields:

- Lead ID and reviewed `Modified_Time`;
- active/converted status;
- service type/category if already present or safely classified;
- language (`fr`, `en`, `unknown`);
- priority (`low`, `normal`, `high`, `urgent`);
- recommended internal next action (`review`, `call`, `draft_reply`, `site_visit`, `quote_review`, `wait`);
- missing-information categories;
- follow-up due timestamp;
- consent/contactability gates;
- deterministic policy version and decision hash.

AI may propose service/language/priority/recommended action, but deterministic code validates allowed values and contactability. AI confidence alone never creates permission to write or send.

### 2. Activate bounded internal Lead maintenance

Supersede the Phase 5 opt-in name with a Phase 6 policy version, while preserving the same fail-closed journal and conditional-update contract.

Allowed automatic CRM Lead changes:

- `Normalized_Email` when syntactically safe and actually different;
- `Normalized_Phone` when Phase 5 normalization rules are satisfied;
- `Next_Followup_At` when the deterministic decision requires follow-up and the record version still matches;
- `Service_Types` only when the current value is empty and the decision comes from an allowed bounded service taxonomy with sufficient deterministic evidence. Existing non-empty values are never overwritten automatically.

No other Lead field is changed by Phase 6 v1.

### 3. Deterministic internal CRM Tasks

Maintain at most one active OptiBrain follow-up Task per Lead/action generation.

The Task may contain:

- bounded subject;
- Lead linkage;
- due date;
- internal action category;
- priority if supported by the existing provider contract.

It must not contain raw private email/message bodies. Existing matching tasks are reconciled by identity/readback. Collisions or ambiguous provider outcomes stop and require review.

### 4. Automatic draft preparation, never automatic send

When a Lead is contactable and the decision recommends `draft_reply`, Phase 6 may create or refresh a Zoho Mail draft using the existing draft mechanism.

Draft generation requirements:

- opt-out/consent gates are checked before drafting;
- recipient identity must be derived from the exact reviewed Lead or inbound message, never AI-generated;
- language follows deterministic/validated `fr`/`en` classification;
- content is generated as a draft only;
- the draft is linked in durable audit evidence by provider ID and content hash;
- repeated processing of the same Lead version must not create duplicate drafts;
- a newer Lead/message version may supersede the previous draft but never silently send it.

### 5. Explicit approval envelope for outbound sends

Introduce a reusable approval envelope rather than a boolean hidden inside workflow input.

Minimum approval evidence:

- approval ID;
- actor;
- approved timestamp;
- exact Lead/message identity;
- recipient address;
- from address;
- subject/content hash;
- action type (`send_new_email` or `reply_email`);
- expiry;
- single-use state.

A send action must re-read the approval immediately before the network call and verify all hashes/identities. A changed draft or recipient invalidates approval. Provider response loss remains ambiguous and must never trigger an automatic second send.

Phase 6 v1 may implement the reusable approval envelope and retain sends disabled in production until a separate live-safe send proof is explicitly approved.

### 6. Sales queue / SLA observability

Expose authenticated, payload-safe inspection for:

- leads requiring human review;
- overdue follow-up;
- high/urgent internal priority;
- drafts waiting for approval;
- ambiguous provider operations;
- delta/native notification health relevant to lead processing.

No endpoint returns stored credentials or raw customer email bodies by default.

### 7. Follow-up cadence

Use `Next_Followup_At` as the canonical Lead-level timestamp.

Initial deterministic cadence:

- urgent: same-day review;
- high: within one business day;
- normal: within two business days;
- low/wait: explicit future date only when supported by Lead state.

The implementation must use `America/Toronto` for business-day/daypart calculations while persisting canonical timezone-aware timestamps.

Cadence does not automatically send a message. It schedules internal work and draft preparation only.

## Explicitly out of scope for Phase 6 v1

- autonomous Books mutations;
- autonomous quote/invoice creation;
- autonomous Lead conversion;
- automatic Account/Contact/Deal creation from an existing Zoho Lead;
- owner reassignment;
- automatic phone calls or SMS;
- autonomous cold outreach to addresses that did not come from the reviewed record/source;
- deletion of CRM records, fields, workflows, tasks or legacy webhooks;
- replacement of existing Zoho active workflows;
- unbounded historical CRM scans;
- AI-created provider identifiers, email addresses, phone numbers or monetary values.

## Engineering sequence

### Gate A — frozen baseline and inventory

- prove `main`, production and Phase 5 post tag equal `52f11d4fc14d8582c03837e0317f849efe8aa3d7`;
- capture current Lead field/task/mail draft provider behavior read-only;
- re-run complete Phase 5 regression before Phase 6 runtime work;
- record exact current production environment policy without exposing secrets.

### Gate B — pure decision engine

Implement `SalesDecision` and deterministic cadence with no provider mutation. Unit tests must cover language/priority bounds, converted/inactive Leads, opt-out, stale versions, missing contact data and timezone/business-day edges.

### Gate C — internal CRM action hardening

Extend the existing Lead reconciler rather than adding a parallel writer. Prove normalization, `Next_Followup_At`, optional empty `Service_Types` fill and one-task identity with fake providers, lost-response reconciliation and restart behavior.

### Gate D — draft lifecycle

Reuse the existing mail draft provider. Add Lead-version/draft identity and dedupe. Prove opt-out/no-recipient produces zero mail mutations. Drafting remains separate from sending.

### Gate E — approval envelope

Implement durable approval issuance/inspection/consume semantics. Tests must prove changed content, changed recipient, expiry, duplicate consumption, restart and ambiguous send result all fail closed.

### Gate F — live read-only/canary validation

Production-facing validation initially performs reads, internal smoke events and optionally one explicitly approved reversible internal CRM test record operation. No customer send is part of the default deployment campaign.

### Gate G — recovery and promotion

Match or exceed Phase 5 gates:

- full regression;
- fresh local backup;
- restored DB/API/restart/dedupe drill;
- encrypted off-host upload and download-hash verification;
- protected-file/source-mode checks;
- zero failed systemd units;
- provider governance noops;
- exact production health;
- guarded normal fast-forward of `main` only after all recovery gates;
- final recovery tag;
- final equality: candidate = production = remote main = peeled post tag.

## Release acceptance criteria

Phase 6 v1 cannot be promoted unless all of the following are true:

- complete previous regression suite passes with zero failures/errors/skips;
- new Phase 6 tests pass;
- production Lead notification/delta ingestion remains healthy;
- Books mutation count is zero;
- customer sends during deployment are zero;
- no Lead conversion/Account/Contact/Deal automatic creation occurs;
- bounded internal CRM changes have durable intent and readback proof;
- drafts are deduplicated by exact source/version identity;
- send approval cannot be reused or silently widened;
- fresh backup and restored-production drill pass;
- encrypted off-host verification passes;
- protected diagnostic remains unchanged;
- root recovery/runbook synchronization is performed only through its separately reviewed privileged procedure;
- `main` promotion occurs only after every preceding gate.

## Rollback / disable strategy

The first rollback is policy disable, not destructive provider reversal.

- Disable Phase 6 sales-write/draft policy.
- Preserve existing Phase 5 notification and delta ingestion.
- Preserve audit/journal history, created internal Tasks and Mail drafts for evidence.
- Do not delete Phase 5 Lead fields.
- Do not delete provider records automatically.
- Any ambiguous outbound or CRM write remains human-reconciled before further action.

## Initial implementation target

The first engineering commit after this contract should be pure/local:

1. `SalesDecision` model and deterministic policy;
2. business-day follow-up calculator using `America/Toronto`;
3. tests only;
4. zero provider writes and zero production changes.

Only after that pure layer passes the full regression suite should Phase 6 touch the existing Lead reconciler or mail draft workflow.
