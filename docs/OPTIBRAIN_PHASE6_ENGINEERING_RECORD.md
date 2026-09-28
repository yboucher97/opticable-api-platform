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
