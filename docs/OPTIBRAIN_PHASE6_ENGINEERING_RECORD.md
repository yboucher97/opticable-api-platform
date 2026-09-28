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

### Validation state

GitHub has no automatic workflow run for commit `12efc71197b1604bde7a956d0c8cd2b67167307d`. Focused and complete regression validation therefore remains a required gate before any provider-facing Phase 6 code is added.

### Production impact

Zero. At this point Phase 6 exists only on `phase6/sales-autonomy-v1`; `main` and production remain at the Phase 5 baseline.

### Next gate

Run the focused Phase 6 tests, complete inherited regression suite and compile checks in an isolated engineering worktree. If all pass, record exact counts and proceed to Gate C design for the existing Lead reconciler. Do not enable sales writes or drafts before that validation.
