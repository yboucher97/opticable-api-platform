# State and entity contracts

AUTHORITATIVE CURRENT. State is recovered before observers, approvals or executors resume. Zoho owns business facts; local journals and independent R2 claims own replay safety. Provider truth cannot reconstruct lost action authority. Schemas reside in the named workflow modules; no new merged DB is implied.

## Active and historical stores

All active DBs are under `/var/lib/opticable-workflow-api/output/automation`, owned by `opticable-workflow-api`; online backup snapshots them with integrity verification. Canonical writers listed here are authority boundaries, not grants to execute.

| Store | Schema / writer → readers | Rebuildability, retention, restore order |
|---|---|---|
| `automation.db` | `automation/store.py`, delta/desired-journal/native/effect modules; authenticated intake + fixed workers → execution/readiness/history | Events, runs, idempotency, checkpoints and audit mandatory; core online `database/automation.db` snapshot supersedes WAL/SHM. Restore first; indefinite immutable evidence. Saved cursor never moved to mask failure. |
| `phase9-form-receipts.db` | `phase9_form_receipts.py`; GET collector/contained export → receipts/source/sales | Source namespace+provider inquiry ID/link chronology required; provider alone cannot reproduce received chronology. Restore with root export/config before receipt observer. Cache30d expendable. |
| `phase9-intake.db` | `phase9_intake.py`; exact reviewed provider readback/feedback → source trace/sales | Inquiry, canonical links, first/return/feedback chronology required indefinitely. Restore after core/receipt identities, before attribution reads. |
| `phase10-service-events.db` | `service_events.py`; GET-only service observer → lifecycle/recurring/Today | Durable occurrence identity required; five-module display snapshots rebuildable from provider reads, 300s TTL/daily full audit. Restore occurrences before hourly observer. |
| `phase12-autonomy.db` | `business_autonomy.py`; central reviewed action/approval/reconciliation → operator/readiness | Immutable envelope/payload hash, approval consumption, provider effects/claims required indefinitely; never delete/recreate to retry. Restore before any executor; compare off-host newer effects. |

Three archived stores remain read-only recovery evidence: `/var/lib/optibrain/phase9/mission2/form-receipts-stage.db`, `/var/lib/optibrain/phase9/closure/phase9-intake.before-permission-fix.db`, `/var/lib/optibrain/phase10/test-lab/lifecycle-events.db`. They are backed up, integrity-checked and restored for compatibility; no active route/timer consumes them as current authority. Eight stores, five active, zero ambiguous ownership.

## Other canonical stores

| Store | Owner / canonical writer / readers | Recovery/retention contract |
|---|---|---|
| Root protected baselines, TEST registry, operations crosswalk (`/etc/optibrain`) | root reviewed readback/registration → transport ownership and operator projections | Required; preserve IDs/lineage/hash/name-based ownership. Version comparison baseline is `protected-runtime-versions.json`; golden restore derives it from its named archived root provider-summary artifact. Marker alone never establishes ownership. |
| `/var/lib/optibrain/phase12`, earlier Test/reconciliation evidence | root exact executor/manual reconciler → root runner/operator evidence | Required intent/result/readback/ownership evidence; preserve indefinitely, old authorizations excluded from restore. |
| R2 `business-effects/v1/` | root exact conditional claim/result writer → independent reconciliation | Create-only, locked, no deletion/TTL. Critical non-local safety source; reconcile newer-than-backup effects before any writer. No provider-only reconstruction of ambiguity. |
| `/var/lib/opticable-api-platform/shared/zoho-oauth.json` | approved OAuth flow/API refresh → API/PDF | Secret; protected backup or owner reconnect; credential-bound cache lock/modes. Do not revert a newer rotation from a stale release backup. |
| Root release receipts, archive manifests, upload/readback/hold evidence and `/var/lib/optibrain/recovery-source/current.bundle` | root release/backup/uploader → health/recovery | Required exact hashes and immutable history; current pointers plus retained historical records. The latest complete-history bundle is included in application backups and permits exact-source Git reconstruction when GitHub is unavailable. |
| `/var/lib/optibrain/customer-communications` | fixed root customer runner → exact Mail boundary and read-only operator projection | Required immutable source/authorization, initialized effect/hold state, suppression and passed-family checkpoint. Never initialize missing live state or reset counters; restore/reconcile newer R2 effects. Separate from internal lifecycle authority. |
| Connector Cloudflare OAUTH KV + immutable receipt export | separate connector OAuth/intake owner → gateway/collector | External provider state; VPS loss does not delete it. Root backup contains connector source/bundle and references, not exported secret/KV values; owner/provider recovery if whole Cloudflare account lost. |
| Mail observation metadata/cache, CRM display snapshots, provider metrics | GET observers/scoped transport → read views/readiness | Rebuildable incidental state. Mail cache30d, daily7d content audit/two-day overlap; gaps>7d require reviewed backfill. Metrics30d/10k rows. Not mutation/ownership evidence. |
| `/run/optibrain-readiness`, Today process cache, diagnostic logs, Omada browser cache | bounded read sampler/process → views | Expendable; regenerate. Today60s private/no-store display cache; logs rotate; browser execution not required by contained Omada health. |
| PDF/Omada local output/job files | contained local support processes → internal read views | Backed up for lineage/support, no public replay path. Retired provider actions stay denied. |

Restore ordering: fresh root denial + users → root baselines/registries/credential references → core online DB → receipt/intake/service/action stores + root evidence → read-only integrity/identity → contained API → newer provider/off-host reconciliation → authenticated health/backup → traffic → explicitly approved observers later. No restored timestamp/approval grants a new effect.

## Entity identity

Provider CRM IDs are numeric strings scoped to module/account. They are not internal OptiBrain IDs, email addresses or proof of TEST ownership. Operational OB IDs are minted once by `operations.stable_id`, persisted in root crosswalk and not regenerated on provider replacement; their initial suffix is a module+provider-ID hash. Re-link only through reviewed lineage evidence.

| Entity | Provider relation / internal relation |
|---|---|
| Lead | CRM Leads ID; receipt/canonical intake references it. Eligible new Leads convert only after verified human qualification; no implicit protected/fuzzy Contact merge. |
| Contact | Contacts ID; Account relation; `OB-P-…` crosswalk identity |
| Account | Accounts ID; customer grouping; `OB-C-…` |
| Service Location | Service_Locations ID linked to Account/primary Contact; `OB-S-…` |
| Service | Services ID linked to location/original Deal; `OB-SV-…`; durable across later Deals/visits; original Deal is not overwritten to express a new visit |
| Deal | Deals ID linked to Account/Contact/location/service context; `OB-J-…` operational project identity |
| Project | Current operations projection over registered Deal (`OB-J-…`); no assumption that a Zoho Projects project exists or is authorized |
| Work Order | Installations ID linked through primary Service and native joins; `OB-WO-…`; root visit lineage supplies its current Deal when the Service's original Deal differs |
| Case | Cases ID linked to Account/Contact/Deal; `OB-T-…`; validated site/Service/visit context retained with lineage. Unproven urgency or routing needs human review. |
| Task | Tasks ID and module-qualified What_Id relation; `OB-TK-…`; exact TEST registry/protected fence independent |
| Attribution event | Immutable source receipt/intake occurred/received time and source metadata; first/return/feedback references preserved, not CRM last-modified time |
| Intake event | Source+inquiry hash `OB-I-…`; inquiry identifies replay, new inquiry for a returning person; canonical CRM ID explicitly linked |
| Business action | Immutable action_id + action type/target/provider version/payload hash; independent off-host claim key. Duplicate effect fencing survives rollback. |
| Approval | Single-use approval_id bound to exact action/payload/identity/version/expiry; a stale approval cannot revive transport |
| Exception | Retained action/run/step identity plus reason/state; REAL CURRENT/TEST_ONLY/HISTORICAL/RESOLVED are display scopes, not retry/resolve authority |

Critical non-rebuildable-from-provider stores are immutable receipt/action/run/approval/claim lineage and root identity registries. Display caches and observations are rebuildable, but deleting them is not a reconciliation procedure. Retention never removes provider-effect evidence to reduce disk usage.

## Current internal lifecycle evidence

`/var/lib/optibrain/lifecycle` (root0700) contains activation/checkpoint, immutable source/authorization files, ownership and per-effect projection, local contract context and HOLD state. Root runner is the only writer; API cannot grant this authority. `REAL_NEW` is post-activation native creation; `REAL_REFERENCE` permits approved nonprotected Account/Contact/Site/Service/WorkDrive associations, never target updates. Native conversion may touch parent system timestamps while preserving content, so protected references are forbidden. Back up evidence before any state restore; stale/missing state cannot defeat R2 claims. Existing phase12 action DB has append-only lifecycle intent/evidence tables; no additional CRM database. TEST lineage is boolean plus root run registry, including the native Books TEST customer; transaction metrics never use raw contact counts.

Each Deal stores its accepted transaction/scope, initial Installation, `visits` and deterministic `return_visits`. Each completed visit retains native human transition identity/time, notes/proof and Account/Contact/Deal/Site/Service context. Operational observations never erase the original visit or create another Service for a technician visit. Newly owned Services may record installed/last-service dates after completion; Active reference Services keep current visit dates in root history without provider edits. Native Invoice observations and the complete linked invoice set prevent one paid Invoice from clearing attention for another unpaid/unknown one.

Customer effects bind family/object/cadence or schedule revision, exact recipient/template, native source proofs and attempt time. A schedule revision includes native human event provenance, date/time, contact, site, technician and access context; returning to an earlier date is still a new revision. Sent reconciliation records native Mail identity and exact content. The root customer state is mandatory recovery evidence, not a cache. The root-owned0644 `/run/optibrain-readiness/{lifecycle,customer-communications}.json` files remain rebuildable display only.

Root-only `/var/lib/optibrain/lifecycle/business-observation.json` is a rebuildable hourly native CRM/Books snapshot and lineage/value projection, not an effect journal or accounting ledger. Optional root owner-reviewed `recurring-links.json` records native profile/customer/Account/Site/Service IDs plus reviewer/time/proof; it cannot override conflicting native parents. Readiness `recurring.json` and `marketing.json` in `/run/optibrain-readiness` are derived display only. Private snapshots are backed up; display rebuilds. No migration or new DB exists. Acquisition outcome keys are projections with external uploads OFF; they are not successful provider effect claims.

Business-observation cache schema3 includes bounded Books payments/expense observations and native base currency. Root:opticable-workflow-api0640 `/run/optibrain-readiness/business.json` is minimized owner-only derived display, recreated from that cache; never authority or a financial ledger. No DB migration. All eight existing stores remain unchanged.

Native Finance detail cache is reusable only for matching transaction/customer/modification identities; each hourly refresh adds at most8 detail GETs within the existing160-read cycle. `lifecycle/finance-links.json` and immutable `finance-link-confirmations/` are explicit owner evidence, not expendable caches: back up and revalidate native parents after restore. `lifecycle/measurement-status.json` is reviewed display health, not upload authority. Conversion event/source/validation/diagnostic receipts under `/var/lib/optibrain/conversion-export` and R2 `conversion-effects/v1/` are independent immutable upload fencing; never restore stale local state to authorize another upload. New host recovery keeps conversion policy OFF. All these root state/config paths are included in the existing whole root-state/application backup; no ninth DB or warehouse.

## Shadow sales observation

[Sales contract](OPTIBRAIN_SALES_INTELLIGENCE_CONTRACT.md): fixed zero-credit Apollo reads and dated public project research run as an optional display domain of the existing internal observer. Twelve internal/four customer scopes are preserved; **no cold-outbound or Apollo mutation scope exists**. Root rebuildable `/var/lib/optibrain/sales-intelligence` caches feed private0640 `/run/optibrain-readiness/sales-intelligence.json`. Existing `phase12-autonomy.db` adds append-only `sales_shadow_feedback` (actor/version/time), local review only; retain DNC feedback after restore. `sales-intelligence/STOP` stops only this observer. No new DB/service/timer/credential; missing/stale evidence holds contact recommendations. Existing Apollo contacts, sequences, templates, mailboxes and suppression remain provider-owned production state.

## Rebuildable acquisition evidence

The [acquisition contract](OPTIBRAIN_ACQUISITION_INTELLIGENCE_CONTRACT.md) adds `acquisition_*` derived tables to existing `phase12-autonomy.db`, not another business source/database. Root acquisition snapshots/inputs retain raw provenance and exact aliases; source age and conflicting facts are preserved. Private0640 owner projection contains no people directory. Existing eight production/history database inventory, protected baseline and immutable business/effect journals remain preserved. Research `lab.sqlite` is nonproduction and expendable. Root acquisition STOP affects only this optional observer; recovery does not arm writers.
