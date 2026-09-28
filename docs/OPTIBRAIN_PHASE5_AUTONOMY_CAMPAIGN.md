# OptiBrain Phase 5 — Business-System Autonomy

## Immutable starting point

- Repository: `yboucher97/opticable-api-platform`
- Phase 5 branch: `hardening/phase5-business-autonomy-v1`
- Exact Phase 4 production baseline: `209aac07160e1376381faebd86fb38a18f92582a`
- Phase 4 recovery tag: `recovery/post-phase4-durable-events-v1-20260928`
- Production API at start: `1.9.0`
- Production automation DB at start: `user_version=2`
- Phase 4 event ledger, dedupe, replay, quarantine, watchdog, delta-sync foundations, backup/restore and off-host recovery are production-proven.

Phase 5 must preserve every Phase 3/4 execution, ambiguity, recovery, backup and security invariant.

## Mission

Turn OptiBrain from a safe event/execution platform into the declarative business control plane for Opticable.

The system should be able to inspect, plan, reconcile, verify and continuously detect drift across the business systems that matter most, beginning with Zoho CRM and then extending the same model to Google and other providers.

Phase 5 is not permission to make uncontrolled provider changes. Configuration must become versioned desired state, reviewed by machine before mutation, applied through conservative provider adapters, verified after application, and recoverable.

## Current Zoho CRM facts from the live audit

Do not rediscover by guessing; verify these facts read-only before relying on them.

### Existing operational modules

The CRM already contains substantial Opticable structure, including:

- Leads
- Contacts
- Accounts
- Deals
- Buildings (`Buildings`)
- Service Locations (`Service_Locations`)
- Installations (`Installations`)
- Services (`Services`)
- Installation X Services (`Installation_X_Services`)
- Accounts X Buildings
- Contacts X Buildings
- integrated Books/finance modules for Estimates, Invoices, Sales Orders and Purchase Orders

Do not replace this model with a new parallel CRM model without compelling evidence.

### Existing Lead data model

Do not recreate fields that already exist. Existing Leads include, among others:

- `Normalized_Email`
- `Normalized_Phone`
- `Ingestion_Source`
- `Source_Record_ID`
- `Inquiry_ID`
- `First_Source`
- `First_Medium`
- `First_Campaign`
- `First_Campaign_ID`
- `First_Term`
- `First_Content`
- `First_Landing_URL`
- `First_Referrer`
- `First_Site`
- `First_Touch_Time`
- `Last_Source`
- `Last_Medium`
- `Last_Campaign`
- `Last_Campaign_ID`
- `Last_Term`
- `Last_Content`
- `Last_Landing_URL`
- `Last_Referrer`
- `Last_Site`
- `Last_Touch_Time`
- `Google_GCLID`
- `Google_GBRAID`
- `Google_WBRAID`
- `Meta_FBCLID`
- `Meta_FBP`
- `Meta_FBC`
- `Visitor_ID`
- `Total_Units`
- `Building_Vocation`
- `Building_Status`

These are recent attribution/deduplication foundations and should be governed, not duplicated.

### Existing Deal model

The Deals pipeline already contains Opticable-specific stages including:

- Qualification
- Estimate Sent
- Estimate Accepted
- Contracts In Progress
- Contracts Signed
- Scheduling
- Installation
- Invoice Sent
- Payment Received
- Closed Lost / competition variants

Existing Deal fields also include:

- `Deal_Number` (autonumber, `OPP-` prefix)
- `Service_Types`
- `Books_Estimate_Number`
- `Books_Estimate_ID`
- shipping address fields
- `Ingestion_Source`
- `Source_Record_ID`
- `Inquiry_ID`
- first/last attribution fields and Google/Meta identifiers

Do not silently redesign the live sales pipeline.

### Existing workflow rules

The live audit found three active CRM workflow rules:

1. `Wifi Installation` on Services — existing operational workflow around signed Wi-Fi service contracts.
2. `General Terms Signed - Process Services` on Accounts.
3. `Notify on Leads` on Leads create.

Preserve all three until a replacement has been proven in parallel and an explicit migration plan exists.

### Legacy webhooks

Two old Zoho Flow webhook definitions from 2021 were found and currently report `associated: false`.

Treat them as legacy inventory. Do not expose their URLs/tokens. Do not delete them automatically. Retirement is a separate destructive cleanup decision after dependency verification.

## Existing OptiBrain desired-state foundation

The repository already contains:

- `workflow/automation/desired_state.py`
- `DesiredStateDocument`
- `DesiredStateRegistry`
- `DesiredStateController`
- dependency ordering
- actions: create/update/delete/noop/manual/blocked
- risk classes: low/medium/high/destructive
- explicit high/destructive apply gates
- `ZohoCrmFieldReconciler`
- `config/automation/desired-state/README.md`

The API already registers `zoho_crm/field` with `ZohoCrmFieldReconciler`.

Extend this architecture. Do not create a second configuration engine.

## Phase 5A — Complete live inventory and source of truth

Build a bounded read-only inventory collector for the Zoho CRM configuration actually in use.

Inventory at minimum:

- modules
- fields and field types
- layouts and sections
- picklists / global picklists relevant to operations
- workflow rules and their complete actions
- workflow tasks
- field updates
- webhooks (redacted; never persist secrets)
- assignment rules
- scoring rules
- validation rules
- cadences where used
- relevant custom buttons/functions only if safely discoverable
- lead conversion mappings
- module relationships / linking modules

Inventory must be deterministic and machine-comparable. Redact credentials, tokens and secret-bearing URLs before persistence.

Create a versioned snapshot format and a drift report. Do not store a raw provider dump containing secrets.

## Phase 5B — Desired-state adapters

Extend the existing Desired State registry with conservative Zoho CRM adapters.

Priority kinds:

1. `field` — harden existing adapter rather than replace it.
2. `layout`
3. `workflow`
4. `webhook`
5. `field_update`
6. `assignment_rule`
7. `scoring_rule`
8. `validation_rule`

Modules/functions/buttons may be added only after their provider behavior and rollback semantics are well understood.

Every adapter must implement:

- read current state
- normalize provider output
- plan
- risk classification
- apply
- immediate verification
- clear reconciliation evidence
- no blind retry of ambiguous writes
- no delete by default
- deterministic identity resolution
- bounded API use

Provider request IDs are reconciliation evidence only, never proof that retry is safe.

## Phase 5C — Real Opticable CRM desired state

Create real Git-versioned desired-state documents under:

`apps/workflow-api/config/automation/desired-state/`

Start by declaring important configuration that already exists so the first plan is predominantly `noop`. This establishes governance without changing the business system.

Then identify genuine gaps based on Opticable's actual operating model.

Candidate business concepts to evaluate — never create blindly:

- service interest / requested services normalized taxonomy
- lead qualification state
- urgency / requested timeline
- commercial vs residential / project type
- recurring-revenue opportunity
- lead source normalization
- next follow-up timestamp
- follow-up status
- loss reason normalization
- sales owner / routing metadata
- consent / communication preference when not already represented
- project/site linkage
- originating form/site/ad attribution

Prefer existing fields if semantics are close enough. Do not create synonym fields simply for naming preference.

## Phase 5D — Zoho → OptiBrain event-driven intake

Use the Phase 4 event ledger as the central business-event backbone.

Target architecture:

Zoho CRM event
→ authenticated OptiBrain webhook / notification
→ durable Phase 4 event ledger
→ normalization
→ routing
→ workflow run
→ Phase 3 execution controls
→ provider actions

Do not route Zoho events directly into irreversible writes outside the existing execution engine.

Prioritize Leads create/update first, then Deals and relevant operational modules.

If Zoho's native notification mechanism differs from workflow webhooks, use the mechanism with the strongest verifiable authentication/replay semantics supported by the existing Phase 4 adapter. Do not invent security guarantees.

Keep delta-sync/reconciliation as a fallback for missed events where necessary.

## Phase 5E — Business automation

After reliable intake is proven, implement conservative high-value automation.

Priority outcomes:

- normalize/dedupe inbound leads
- preserve first-touch attribution and update last-touch attribution
- route leads by service type / geography / source where data supports it
- create bounded follow-up tasks
- surface stale/unanswered leads
- maintain next-action state
- create internal alerts for leads needing human action
- synchronize qualified lead context into Deals without duplicating existing records
- preserve project/site/account/contact relationships
- use the event ledger to make automation explainable and auditable

Do not auto-send customer-facing communication until the exact sending policy, templates and approval semantics are explicitly represented and tested.

Do not introduce uncontrolled mass updates.

## Phase 5F — Zoho workflow migration strategy

Do not immediately delete the three existing active CRM workflow rules.

For each existing rule:

1. capture its complete normalized configuration
2. identify every action and dependency
3. determine whether OptiBrain should own it, Zoho should keep it, or a hybrid is safer
4. create a parallel replacement only where justified
5. prove event delivery and action equivalence with non-destructive tests
6. provide explicit cutover/rollback steps

Legacy unassociated webhooks should only be removed after proving they are unused and receiving explicit destructive approval.

## Books boundary

Zoho Books remains a deliberate human-approval boundary.

Autonomous operations may:

- inspect Books data
- reconcile read-only mappings
- compute proposed changes
- generate plans/reports

Autonomous operations must NOT:

- create/update/delete Books transactions
- issue invoices/estimates/payments/credits
- alter accounting configuration

unless a future explicit policy grants that specific mutation.

Existing CRM fields that reference Books IDs/numbers may be read and maintained only when the owning workflow semantics are already proven safe; do not turn this into autonomous accounting writes.

## Safety policy for live CRM mutation

Before the first Phase 5 live CRM mutation:

1. capture a redacted metadata snapshot
2. create exact desired-state document
3. generate plan
4. independently review plan for duplicates and semantic collisions
5. verify provider limits
6. create recovery/rollback description
7. apply only additive low-risk changes first
8. immediately re-plan and require resulting `noop`
9. log provider evidence without secrets

Medium-risk updates must be demonstrably reversible and have before-state evidence.

High-risk or destructive changes require explicit human approval even under Full Access.

Never delete a field/module/layout/workflow merely because it is absent from a first draft desired-state document. Desired state manages only explicitly declared resources.

## Desired-state API hardening

Expose authenticated control-plane endpoints if they are not already present:

- list adapters
- load/validate desired-state documents
- plan
- apply low-risk additive plan
- inspect last apply result
- drift report

All mutation endpoints must fail closed if the inspection API key is unset.

Apply requests must include an immutable plan identity/digest so stale plans cannot be applied after provider state changes.

Re-plan or provider-state verification must happen immediately before mutation.

## Auditability

Phase 5 configuration changes must be attributable through durable evidence.

Record at minimum:

- desired-state document name/version/hash
- plan hash
- resource id
- provider/kind
- normalized before state hash
- normalized desired state hash
- action
- risk
- result
- provider operation/request IDs when available
- verification result
- actor
- timestamp

Do not store credentials or full secret-bearing provider responses.

## Testing

Add comprehensive tests for:

- desired-state validation
- dependency cycles
- stable plan hashing
- stale-plan rejection
- current-state drift between plan and apply
- field noops
- additive field creation
- duplicate semantic field detection
- field update risk classification
- standard-field deletion denial
- custom-field deletion destructive gate
- layout noops and bounded additive changes
- workflow normalization
- workflow create/update/noop
- existing workflow preservation
- webhook redaction
- webhook authentication configuration
- ambiguous provider write handling
- provider 401/429/5xx/timeouts
- request IDs as evidence only
- post-apply verification
- failed verification becomes human/manual state, not blind retry
- Books mutation policy remains blocked
- Phase 3 execution regression
- Phase 4 event/dedupe/replay/watchdog regression

Run the complete workflow API suite before candidate completion.

## Failure drills

Use mocked/fake provider state or isolated OptiBrain environments for destructive drills.

Test:

- provider mutation accepted but response lost
- provider timeout before send
- provider timeout after possible send
- duplicate apply request
- stale desired-state plan
- concurrent reconciler apply
- event duplicated by Zoho
- process restart after event durable but before routing
- event replay
- provider rate limiting
- provider auth expiration

No ambiguous CRM mutation may be blindly repeated.

## Git / production workflow

Work only on:

`hardening/phase5-business-autonomy-v1`

until every candidate gate passes.

Do not change `main` during development.

Maintain logical commits and a Phase 5 engineering record covering:

- live inventory
- design decisions
- files changed
- tests
- failures
- fixes
- provider limitations
- live CRM changes performed
- before/after evidence
- rollback procedures
- deployment procedure
- final identities/hashes

Preserve:

- `ops/backup/optibrain-cloudflare-auth-diagnostic.sh`
- root recovery runbook
- Phase 4 recovery tags
- Phase 4 backup/recovery behavior

Use the corrected production source-mode/materialization safeguards introduced at the end of Phase 4.

## Deployment gates

Before promoting Phase 5 application code:

- exact Phase 4 baseline established
- full suite PASS
- provider mutation tests PASS
- no secret leakage
- source permissions correct
- predeployment backup PASS
- isolated restore PASS
- production readiness PASS
- authenticated health PASS
- safe internal smoke PASS
- any live Zoho mutations separately verified
- postdeployment backup PASS
- isolated restore PASS
- encrypted off-host verification PASS
- recovery tag published
- zero failed systemd units
- protected diagnostic unchanged

No DB migration should be introduced unless Phase 5 truly requires durable schema changes. If a migration is needed, use the Phase 4 migration discipline against an actual restored production copy before production mutation.

## Autonomy

Operate autonomously inside existing authorization boundaries.

Do not stop for routine engineering decisions, test failures, refactors, inventory discoveries or low-risk additive implementation work.

Do not expand privileges, alter sudoers, weaken authentication, expose credentials, or bypass intentional boundaries.

High-risk/destructive provider changes and Zoho Books mutations remain human approval boundaries.

If a final root-only deployment operation is required, finish everything else first and return exactly one minimal pinned sudo command.

## Phase 5 completion definition

Phase 5 is complete only when:

- Zoho CRM configuration has a redacted deterministic inventory
- important existing CRM configuration is represented in Git desired state
- drift detection works
- field/layout/workflow/webhook reconciliation is tested and conservative
- lead events enter the Phase 4 ledger through an authenticated/replay-safe path
- a useful initial lead lifecycle automation is working without duplicate writes
- existing critical workflows remain functional or have a proven replacement
- no Books mutation boundary was crossed
- full regressions pass
- production and off-host recovery gates pass
- exact final baseline/recovery identities are recorded

Do not claim `OPTIBRAIN_PHASE5_COMPLETE: PASS` until every applicable completion gate is directly verified.