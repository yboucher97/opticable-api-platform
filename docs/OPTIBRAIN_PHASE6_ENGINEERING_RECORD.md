# OptiBrain Phase 6 engineering record

This record is append-only engineering evidence for Phase 6. It is not the privileged root-owned production recovery runbook. The root runbook remains protected during branch engineering and is synchronized only through a separately reviewed deployment/recovery procedure.

## 2026-09-28 — Phase 6 start

### Verified starting state

- Exact Phase 5 production/main/recovery identity: `52f11d4fc14d8582c03837e0317f849efe8aa3d7`.
- Phase 5 final recovery tag: `recovery/post-phase5-business-autonomy-v1-20260928`.
- API `1.10.0`.
- Automation DB schema V2.
- Phase 5 final backup/restore/off-host gates already passed before this branch was created.
- Books safety remains read-only/human-approved.
- Native Zoho Lead subscription remains independently managed by the Phase 5 reviewed renewal contract.

### New branch

Created `phase6/sales-autonomy-v1` directly from exact baseline `52f11d4fc14d8582c03837e0317f849efe8aa3d7`.

No production checkout, service, database, environment, provider, `main`, recovery tag or protected production file was changed by branch creation.

### Authoritative Phase 6 contract

Commit `70d591e396e3090dcd3cda564eb237ab6557aaf4` added `docs/OPTIBRAIN_PHASE6_SALES_AUTONOMY_V1.md`.

The contract deliberately keeps the first release bounded:

- internal lead maintenance and task orchestration may become automatic after proof;
- mail drafts may be prepared automatically;
- external customer sends require exact durable human approval;
- Books remains human-approved/read-only;
- no autonomous existing-Lead conversion or Account/Contact/Deal creation;
- no owner reassignment or destructive CRM metadata operation;
- AI may classify/draft but cannot independently authorize provider writes or sends;
- Phase 5 event/journal/retry/recovery machinery is reused rather than replaced.

### Gate B pure decision layer

Commit `dd16768769ecc9b365ccb65c1d7aaf2d3e8930ee` added `apps/workflow-api/workflow/automation/sales_decision.py`.

Properties:

- pure/local module with zero provider access;
- policy version `phase6-sales-v1`;
- validates exact Lead identity and timezone-aware record version;
- separates active/converted state;
- honors email opt-out before allowing draft recommendation;
- bounds language, priority and next-action values;
- advisory AI values are ignored unless they fit deterministic allowed values/state/contactability;
- `Contact in Future` preserves an explicit future `Next_Followup_At`;
- business-day deadlines use `America/Toronto` and persist UTC timezone-aware timestamps;
- decision evidence includes a stable hash over payload-safe decision metadata;
- no provider identifier, address, phone number or customer body is invented by AI.

Commit `12efc71197b1604bde7a956d0c8cd2b67167307d` added `apps/workflow-api/tests/test_phase6_sales_decision.py` with ten focused tests covering:

- converted lead refusal;
- email opt-out;
- invalid AI language/action/priority;
- stale/pre-qualified priority;
- explicit future follow-up preservation;
- Friday/weekend business-day boundaries;
- after-hours same-day rollover;
- bounded missing-information metadata;
- deterministic decision hashing;
- invalid IDs and naive timestamps fail closed.

### Gate B validation — PASS

The isolated VPS worktree validation completed against candidate `268332bac72295cc57e683524553fe8f915984cc`.

- pure import/provider boundary: PASS;
- focused Phase 6 tests: 10/10 PASS;
- complete inherited regression: 434 tests, 374 subtests, 0 failures, 0 errors, 0 skips;
- compileall: PASS;
- production remained `52f11d4fc14d8582c03837e0317f849efe8aa3d7`;
- remote `main` remained `52f11d4fc14d8582c03837e0317f849efe8aa3d7`;
- provider writes: 0;
- production changes: 0.

This closes Gate B.

## 2026-09-28 — Gate C internal CRM action hardening

### Decision-envelope hardening

Commit `9a02c970c371b94e4ae74bba66582ed7a6f1b317` strengthened the pure Phase 6 decision contract before provider wiring:

- existing future `Next_Followup_At` is preserved for any active Lead so repeated notifications do not continually shift the SLA;
- `Service_Types` trusted fill is separated from AI hints and accepts only an exact bounded service value plus a reviewed non-AI evidence category (`explicit_customer_selection` or `validated_intake`);
- the decision now records whether service type came from existing provider state or a trusted hint;
- a full decision-envelope hash validator rejects tampered policy/version/decision fields.

Commit `b517090750e42efed0e10e06727ac412d755631b` expanded pure decision tests for stable future follow-up, trusted-service separation and tamper rejection.

### Existing Lead writer extended, not duplicated

Commit `438a7573231511ec532fd71bd88f2d75606ed99f` extends `workflow/automation/providers/crm_leads.py` under the separate opt-in policy `phase6-sales-v1` while preserving legacy `phase5-lead-v1` behavior.

Phase 6 automatic Lead writes are allowlisted to exactly:

- `Normalized_Email`;
- `Normalized_Phone`;
- `Next_Followup_At`;
- `Service_Types` only when empty and backed by the trusted non-AI decision source.

Other properties:

- the exact reviewed Lead version is required before any mutation;
- writes keep `If-Unmodified-Since`, `trigger: []` and cadence suppression;
- no conversion, owner reassignment, Account/Contact/Deal creation, customer communication or Books mutation is introduced;
- reviewed events now carry a payload-safe hashed `SalesDecision` envelope;
- audit metadata stores categories, timestamps and hashes, not normalized email/phone values;
- future follow-up timestamps remain stable across self-induced/new notifications;
- task generation identity is derived from policy + Lead + internal action + follow-up timestamp, avoiding duplicate tasks for repeated versions of the same schedule;
- one exact task identity is searched/read back before creation.

### Lost-response reconciliation without retry

Phase 6 records a hash of the exact intended bounded Lead-field subset before the provider call. If the response is lost:

- the operation is still recorded `manual`/human-required;
- no second provider write is issued;
- a later Lead event may close the ambiguity only when exact readback of those same fields hashes to the prior intended hash;
- any mismatch remains human-required.

Task creation follows the same no-blind-retry rule. A lost Task response is reconciled only by an exact deterministic subject + Lead linkage readback; absence/collision does not authorize a second POST.

This improves recoverability without storing raw email/phone values in journal evidence.

### Gate C tests prepared

Commit `43b2eb3431aa1198762ec3849472a9184187cf4e` added focused fake-provider tests for:

- normalization + `Next_Followup_At` + one internal Task;
- stable follow-up/task identity across newer Lead versions;
- accepted-but-response-lost Lead update reconciled by exact hash with no second PUT;
- mismatch after a lost response remaining manual with no retry;
- accepted-but-response-lost Task reconciled by deterministic identity with no second POST;
- trusted empty `Service_Types` fill from a hashed reviewed decision;
- tampered decision failing before provider writes;
- converted Lead performing zero Phase 6 provider writes.

Commit `b05cffd4a1920a744f872c3bb8b2a00c9b7ca1dd` versions the internal reconciliation workflow description for Phase 6. No provider workflow is modified by this source change.

### Gate C validation state

Gate C code is engineering-only on `phase6/sales-autonomy-v1`. It has not been deployed and `OPTIBRAIN_CRM_LEAD_WRITES` has not been changed in production. Focused Phase 6 tests, complete regression and compile checks must pass before any live/read-only Phase 6 provider validation or draft-lifecycle work begins.

### Gate C validation and exact-readback correction — PASS

Initial validation of exact remote candidate `2b1326999710e6c6dc8d789ff41f92cde684d37a`:

- clean worktree; exact seven-file contract scope; 10 commits ahead / 0 behind the Phase 5 baseline;
- remote Phase 6 ref matched the candidate; production and remote main matched `52f11d4fc14d8582c03837e0317f849efe8aa3d7`;
- decision tests: 13; CRM-action tests: 8; Phase 5 Lead compatibility: 16 tests / 3 subtests;
- full regression: 445 tests / 374 subtests, zero failures/errors/skips.

Independent inspection found a release-blocking gap despite those passing tests: Task search reconciliation checked Lead linkage but did not check the returned subject and due date. Commit `820e41dd9c369e645ac8ec71d460fc43bf59c529` now requires exact subject, Lead linkage, due date, valid provider ID and a recognized Task status. Completed matching Tasks are retained as fulfilled generations without creating replacements. Immediate readback also checks the returned operation ID.

Validation of corrected candidate `820e41dd9c369e645ac8ec71d460fc43bf59c529`:

- focused CRM tests: 12 tests / 5 subtests, including exact mismatches, stale review, durable restart, and absent ambiguous Task;
- complete regression: **449 tests / 379 subtests, 0 failures, 0 errors, 0 skips**;
- compileall and diff whitespace checks: PASS;
- static provider boundary: only Lead reads/conditional PUT and Task reads/POST; no Books, Account/Contact/Deal, conversion or customer-send path;
- tests used temporary databases, fake providers and a runner that clears inherited environment and blocks socket connections;
- real provider writes, customer sends, Books mutations and Lead conversions during validation: **0**;
- production and remote main remain `52f11d4fc14d8582c03837e0317f849efe8aa3d7`; production health reports `ok`, API `1.10.0`;
- protected diagnostic SHA-256 remains `7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000`; root recovery runbook untouched;
- validation logs retained locally under `/var/tmp/optibrain-phase6-validation/`.

Gate C is closed after the correction. Gate D may proceed on the engineering branch only. No production policy, service, database or recovery artifact was changed.

## 2026-09-28 — Gate D draft lifecycle — PASS

Implementation candidate: `2872da4a2727d8ade85e1109efccf79f2a2bd5ee`, following Gate C evidence commit `8f9993bde36458f052ccb5898f6e2892cb636263`.

### Existing mechanism reused

The existing `lifecycle.mail_save_draft` now calls a shared `save_mail_draft` transport. The Phase 6 `lifecycle.sales_draft` action calls the same transport. It permits only the existing Mail POST with `mode: draft`, a numeric account ID and a small payload allowlist; send/scheduling fields cannot pass. The existing lifecycle draft compatibility tests pass.

Provider contract reference: [Zoho Mail Save Draft / Template](https://www.zoho.com/mail/help/api/post-save-draft-template.html). This documents the existing POST endpoint and required draft mode. Gate D has **not** performed a live Mail write or claimed live response-shape verification. A response without an explicit success envelope and provider message ID remains human-required.

### Deterministic policy and durable evidence

- New workflow `opticable.sales-draft` consumes internal `opticable.crm.lead.reviewed` events and has one write attempt.
- `OPTIBRAIN_SALES_DRAFTS=phase6-sales-v1` is a separate explicit opt-in. Its default and every other value return observe before provider access. Disabling it is rechecked immediately before the POST.
- The mailbox must be explicitly configured using `OPTIBRAIN_SALES_DRAFT_ACCOUNT_ID` and `OPTIBRAIN_SALES_DRAFT_FROM`; the sender must be a valid Opticable address. No production environment was edited.
- Fixed French/English templates provide bounded draft content without an AI call. A reviewed decision with unknown language stops for review; this gate does not assume that production CRM exposes a configured language field. Language classification/intake configuration must be established before live enablement.
- Recipient comes only from a freshly read Lead matching the exact reviewed version. Converted/inactive state, opt-out or unknown consent, missing/invalid/multiple recipients, and internal sender loops produce zero Mail writes.
- Optional message binding reads the immutable existing event ledger entry using its event ID and exact content hash. Source type, sender, mailbox and Lead correspondence must match; reply headers must be present and valid. Missing headers stop for review, rather than treating a provider message ID as an Internet Message-ID. The current mailbox poller does not guarantee these headers, so message reply binding remains fail-closed until they are available.
- Journal identity binds the connected Lead identity, optional exact message identity, reviewed version and content hash. Changing notification account metadata cannot bypass dedupe or an unresolved operation.
- The existing cross-process `DesiredJournal` lock serializes writes. Started intent is durable before POST. Response loss, malformed acknowledgement and a crash after provider acceptance all fence the same source, including newer versions, without another POST. No automatic ambiguous-draft readback/reconciliation is claimed.
- Reprocessing the same source/version/content returns the stored draft ID across restart. Changed content on the same version requires review. A newer version may create a new draft with `supersedes_draft_id`; earlier drafts are preserved and never sent/deleted.
- Evidence and action results contain IDs, bounded categories and hashes, not recipients or raw message bodies. Existing captured inbound source events retain their pre-existing intake semantics; their body is not copied into new journal evidence.
- Lead state, recipient and policy are rechecked immediately before writing. Mail POST cannot atomically condition itself on a CRM version; a later concurrent CRM edit is a cross-provider limitation. This path creates drafts only.

### Validation

- Focused draft lifecycle: **23 tests / 26 subtests**.
- Existing lifecycle compatibility: **4 tests**, all PASS.
- Complete regression on exact candidate `2872da4a2727d8ade85e1109efccf79f2a2bd5ee`: **472 tests / 405 subtests, 0 failures, 0 errors, 0 skips**.
- Compileall and whitespace checks: PASS.
- Static Phase 6 draft provider boundary: CRM Lead GET plus shared Mail draft POST only; no Account/Contact/Deal, Books, owner, conversion, metadata, customer send or delete operation.
- Fault coverage includes response loss, malformed/error acknowledgements, missing provider ID, process loss before verified journal commit, concurrent journal locking, source/hash mismatch, changed recipient, stale versions, policy disable during execution, restart dedupe and newer-version supersession.
- Validation used isolated temporary databases, fake providers, cleared inherited environment and blocked Python socket connections. Real provider writes, customer sends, Books mutations and Lead conversions: **0**.
- Production and remote main remain `52f11d4fc14d8582c03837e0317f849efe8aa3d7`; live local health remains `ok`, API `1.10.0`.
- Protected diagnostic SHA-256 unchanged: `7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000`.
- Root-owned production runbook SHA-256 unchanged: `cdab559d264fb7a17c469fd10953827a98a24ac4a926939db1055522a6dfc085`.
- Logs: `/var/tmp/optibrain-phase6-validation/gate-d-focused.log`, `gate-d-compatibility.log`, `gate-d-full.log`.

Gate D engineering is closed. No production policy was enabled, no deployment/reconciliation campaign was run, and no manual VPS validation is needed for this engineering result. Gate E (durable outbound approval envelope) and Gates F/G remain separate, unfinished release gates; automatic sends remain outside this draft workflow.
