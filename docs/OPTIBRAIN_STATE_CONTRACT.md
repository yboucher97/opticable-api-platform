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
| Connector Cloudflare OAUTH KV + immutable receipt export | separate connector OAuth/intake owner → gateway/collector | External provider state; VPS loss does not delete it. Root backup contains connector source/bundle and references, not exported secret/KV values; owner/provider recovery if whole Cloudflare account lost. |
| Mail observation metadata/cache, CRM display snapshots, provider metrics | GET observers/scoped transport → read views/readiness | Rebuildable incidental state. Mail cache30d, daily7d content audit/two-day overlap; gaps>7d require reviewed backfill. Metrics30d/10k rows. Not mutation/ownership evidence. |
| `/run/optibrain-readiness`, Today process cache, diagnostic logs, Omada browser cache | bounded read sampler/process → views | Expendable; regenerate. Today60s private/no-store display cache; logs rotate; browser execution not required by contained Omada health. |
| PDF/Omada local output/job files | contained local support processes → internal read views | Backed up for lineage/support, no public replay path. Retired provider actions stay denied. |

Restore ordering: fresh root denial + users → root baselines/registries/credential references → core online DB → receipt/intake/service/action stores + root evidence → read-only integrity/identity → contained API → newer provider/off-host reconciliation → authenticated health/backup → traffic → explicitly approved observers later. No restored timestamp/approval grants a new effect.

## Entity identity

Provider CRM IDs are numeric strings scoped to module/account. They are not internal OptiBrain IDs, email addresses or proof of TEST ownership. Operational OB IDs are minted once by `operations.stable_id`, persisted in root crosswalk and not regenerated on provider replacement; their initial suffix is a module+provider-ID hash. Re-link only through reviewed lineage evidence.

| Entity | Provider relation / internal relation |
|---|---|
| Lead | CRM Leads ID; receipt/canonical intake references it. Lead conversion is forbidden in this mission; no implicit Contact merge. |
| Contact | Contacts ID; Account relation; `OB-P-…` crosswalk identity |
| Account | Accounts ID; customer grouping; `OB-C-…` |
| Service Location | Service_Locations ID linked to Account/primary Contact; `OB-S-…` |
| Service | Services ID linked to location/Deal; `OB-SV-…`; durable service occurrences distinct from display snapshots |
| Deal | Deals ID linked to Account/Contact/location/service context; `OB-J-…` operational project identity |
| Project | Current operations projection over registered Deal (`OB-J-…`); no assumption that a Zoho Projects project exists or is authorized |
| Work Order | Installations ID linked to Service/Project; `OB-WO-…` |
| Case | Cases ID linked to Account/related operational object; `OB-T-…` |
| Task | Tasks ID and module-qualified What_Id relation; `OB-TK-…`; exact TEST registry/protected fence independent |
| Attribution event | Immutable source receipt/intake occurred/received time and source metadata; first/return/feedback references preserved, not CRM last-modified time |
| Intake event | Source+inquiry hash `OB-I-…`; inquiry identifies replay, new inquiry for a returning person; canonical CRM ID explicitly linked |
| Business action | Immutable action_id + action type/target/provider version/payload hash; independent off-host claim key. Duplicate effect fencing survives rollback. |
| Approval | Single-use approval_id bound to exact action/payload/identity/version/expiry; a stale approval cannot revive transport |
| Exception | Retained action/run/step identity plus reason/state; REAL CURRENT/TEST_ONLY/HISTORICAL/RESOLVED are display scopes, not retry/resolve authority |

Critical non-rebuildable-from-provider stores are immutable receipt/action/run/approval/claim lineage and root identity registries. Display caches and observations are rebuildable, but deleting them is not a reconciliation procedure. Retention never removes provider-effect evidence to reduce disk usage.
