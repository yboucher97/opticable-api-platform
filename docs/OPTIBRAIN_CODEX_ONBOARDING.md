# OptiBrain Codex onboarding

Start here. Current API contract: `1.12.0`. Phase 14 is a manually authorized technical implementation; it grants no real business-write or customer-contact authority. Read the latest user instruction for task scope. Use `/var/lib/optibrain/releases/current.json` and `/var/lib/optibrain/phase14/final-verification.json` for the deployed SHA and verified result. Git history preserves the Phase 13 baseline `4bc1beec112c55b161c3025529733d0f0b1213b3` and documentation-only reconnaissance `1a13a8d41684bb8d40620c829a4e9bda6554ab6a` as implementation ancestors.

Read [safety invariants](OPTIBRAIN-SAFETY-INVARIANTS.md), [current architecture](OPTIBRAIN_ARCHITECTURE_BLUEPRINT.md) and [master runbook](OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md). Then select the relevant [runtime matrix](phase14-runtime-matrix.md), [state contracts](phase14-state-store-matrix.md), [provider usage](phase14-provider-usage.md), [retention policy](phase14-retention-policy.md), [deployment](../deploy/README.md), or [recovery procedure](phase14-recovery-runbook.md). [The documentation index](README.md) separates current contracts from historical phase records and audit/recovery evidence. Older phase statements never override current root policy.

## Architecture and authority

One VPS hosts the FastAPI core and five separate SQLite stores. Zoho CRM owns business records. Local journals own receipt chronology, crosswalks and action evidence. Cloudflare's durable control plane schedules and delivers authenticated observation events. The separate connector handles contained intake/receipt export and its own OAuth domain. Owner HTML views use Cloudflare Access JWT verification, allowlists and private/no-store responses.

Canonical code is `apps/workflow-api/workflow`. Central mutation control, the CRM ownership fence and immutable business-action/off-host claims are independent guards. Read projections, Today caches, workflow enabled settings and HTTP health cannot authorize mutations. The TEST runner reconciles before honoring the global kill. PDF/WorkDrive, Omada and legacy Mail/Sign writers retain explicit denial surfaces.

Production: `/opt/opticable-api-platform`, detached release. Local main: `/home/optibrain/phase10-lifecycle`. Implementation worktree: `/home/optibrain/phase14-implementation`. Never run `git clean` on production or overwrite credentials from old release copies. Never execute candidate checkout scripts as unattended root release authority. Manual Codex sessions retain full sudo/root.

## Runtime and state

Three application services: `opticable-workflow-api`, `opticable-password-pdf`, `opticable-omada-site`; shared proxy `caddy`. Core listens on loopback 8100. Five legitimate application timers remain: backup, off-host upload, receipt collection, service observation and bounded TEST reconciliation. The TEST runner additionally samples local readiness every 30 minutes. No new timer or persistent development worker was added. All six `optibrain-agent-{dispatch,status,usage}.{service,timer}` units remain masked/inactive.

Canonical state lives in `/var/lib/opticable-workflow-api/output/automation`: `automation.db`, `phase9-form-receipts.db`, `phase9-intake.db`, `phase10-service-events.db`, `phase12-autonomy.db`. Root policy/registries are under `/etc/optibrain`; root attempt/recovery evidence under `/var/lib/optibrain`. Local backups are `/var/backups/optibrain`; encrypted spool is `/var/lib/optibrain/phase2a`. Online backup covers five active and three historical DBs. AGE private identity remains offline with the owner.

Core Zoho refresh credentials: `/var/lib/opticable-api-platform/shared/zoho-oauth.json`. Do not print credentials, process environments or provider payloads. Access-token cache uses a trusted process/file lock and credential binding. A read-only 401 permits one refresh/retry; 403, throttle, transport ambiguity and mutations are not blindly retried. Inspect and reconcile before credential replacement.

## Current safety state

Protected records: 123, read-only. Protected mutations, customer sends and Books writes: 0. Real/Test automatic business writes: OFF. `REAL_CANARY_ALLOWED=false`. Native French/English Forms CRM integrations remain DISABLED under the Phase 13 owner-UI closure evidence; their current native state is not exposed by the supported API. Fallback enrichment OFF. Connector and Omada contained; PDF/WorkDrive and legacy Mail/Sign denied; Books transport write denial independent of flags. Authentication fails closed. State-loss/stale-journal duplicate fences and backup integrity remain mandatory.

Forbidden without a new explicit mission: real canary, protected-record changes, Lead conversion/deletion, customer email/SMS/calls, invoices/payments/credits/Books changes, broad real CRM or Mail automation, restoring the retired development worker, moving the owner AGE key online or deleting recovery/audit evidence.

## Health and deployment

```bash
curl -fsS http://127.0.0.1:8100/v1/system/health
sudo optibrain-admin scheduler
sudo optibrain-admin verify-latest
sudo cat /run/optibrain-readiness/status.json
sudo cat /var/lib/optibrain/releases/current.json
```

Authenticated `/v1/system/readiness` reports OK, DEGRADED, ACTION REQUIRED or UNKNOWN without provider calls. Owner home: `https://optibrain.opticable.ca/v1/operator/today`; technical drill-down: `/v1/operator/system-health`. Never forge an operator JWT for live validation. Fake/unit validation uses `python -I ops/phase6/validate.py`; focused patterns require `--suite focused --pattern ...`. Full regression runs once for the final local executable candidate, then exact-head release CI.

Canonical deploy is the installed root-owned `/usr/local/sbin/opticable-api-deploy-root EXACT_SHA`, sourced from `deploy/manual-guarded-release.py`. It needs root-reviewed exact-SHA authority, successful main CI, a verified rollback archive and immutable dependency environment. It pins source/version, restarts only the API, checks health/state and writes a schema-1 release receipt; failure restores code, environment, manifest and venv without replaying old DB state. The SSH wrapper requests this same gate. Old installers/release helpers refuse direct execution; see deprecations.

Revalidate runtime and protected baselines before new work. Phase 13 recovery evidence remains valid within its documented limits; complete replacement OS, live provider reconnect, DNS/TLS cutover and guaranteed RTO are not proven. Do not repeat completed destructive recovery drills merely to update documentation.
