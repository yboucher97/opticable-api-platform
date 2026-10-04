# OptiBrain: start here

AUTHORITATIVE CURRENT. API **1.20.0**. OptiBrain is Opticable’s observation, owner-review and guarded workflow platform. Broad real automatic writes are **OFF**. Individual new-record internal scopes and four independently proven operational Mail families may be active under [scope](OPTIBRAIN_REAL_AUTOMATION_SCOPE.md) and [communications](OPTIBRAIN_CUSTOMER_COMMUNICATION_CONTRACT.md); inspect both root policies/timers. `REAL_CANARY_ALLOWED=false`, TEST business writes **OFF**, and the persistent Codex development worker **OFF**. All 123 protected business records are read-only. This entry point is sufficient without any phase conversation.

Read this file, [architecture](OPTIBRAIN_ARCHITECTURE_BLUEPRINT.md), [runbook](OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md), then the relevant [operator](OPTIBRAIN_OPERATOR_GUIDE.md), [deployment](OPTIBRAIN_DEPLOYMENT_GUIDE.md) or [recovery](OPTIBRAIN_RECOVERY_GUIDE.md) guide. [Configuration](OPTIBRAIN_CONFIGURATION_INVENTORY.md), [runtime](OPTIBRAIN_RUNTIME_CONTRACT.md), [state](OPTIBRAIN_STATE_CONTRACT.md) and [documentation index](OPTIBRAIN_DOCUMENTATION_INDEX.md) settle precise contracts. Current instructions supersede all historical phase instructions. Root policies and verified runtime evidence determine actual state; a document never grants provider-write authority.

## First 15 minutes

Production source: `/opt/opticable-api-platform` (detached release). Engineering main: `/home/optibrain/phase10-lifecycle` (the name is incidental). GitHub: `yboucher97/opticable-api-platform`, `main`. Develop on an isolated worktree/PR. Do not clean production or install into its active venv.

Run these read-only commands on the VPS; use a unique timestamp in each report name:

```bash
git -C /opt/opticable-api-platform rev-parse HEAD
curl -fsS http://127.0.0.1:8100/v1/system/health
sudo cat /var/lib/optibrain/releases/current.json
sudo systemctl status opticable-workflow-api opticable-password-pdf opticable-omada-site caddy --no-pager
sudo optibrain-admin scheduler  # backup/upload pair only
sudo systemctl list-timers --all optibrain-backup.timer optibrain-phase2a-upload.timer opticable-phase9-intake-receipts.timer opticable-phase10-service-events.timer opticable-phase12-test-runner.timer opticable-lifecycle-internal.timer opticable-customer-communications.timer --no-pager
sudo cat /run/optibrain-readiness/status.json
sudo cat /run/optibrain-readiness/queue-depth.json
sudo cat /etc/optibrain/mutation-control.json
sudo cat /etc/optibrain/customer-communication-control.json
sudo cat /run/optibrain-readiness/lifecycle.json
sudo cat /run/optibrain-readiness/customer-communications.json
sudo optibrain-admin verify-latest
sudo cat /var/lib/optibrain/phase2a/state.json
df -h /
sudo /opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -I /opt/opticable-api-platform/ops/phase15/inspect_host.py --output /var/lib/optibrain/inspection-YYYYMMDDTHHMMSSZ.json
```

The last command privately authenticates health/readiness and checks five active DBs, service/mask state and writer policy. It does not print keys or customer fields. Add `--protected` for the GET-only 123-record version comparison; add `--ovh` for one direct GET of the production VPS. Never print service environments. Open [Today](https://optibrain.opticable.ca/v1/operator/today) in the owner’s normal Cloudflare Access session; `curl -I https://optibrain.opticable.ca/v1/operator/today` should encounter Access login, while unauthenticated origin GET should return 401. Never forge a production owner JWT.

## System in one minute

Ubuntu 24.04, FastAPI/Python 3.12 API on loopback 8100; PDF support on 8000; contained Omada/Node 22 support on 3210; Caddy on public 80/443. SSH is public 22. Five separate active SQLite stores retain events, receipts, intake, service occurrences and action evidence; eight stores are backed up including three historical copies. CRM owns business entities; local journals own event chronology, dedupe, approvals and execution evidence. Cloudflare’s cron/queues/Workflow deliver authenticated observations. The connector has a separate OAuth domain and remains contained. GitHub has one scheduled public health monitor; three business schedules remain disabled.

Seven VPS timers: backup, off-host upload, receipt observation, service observation, bounded TEST reconciliation/readiness, scoped internal lifecycle and separate customer communications. An active TEST timer does **not** mean TEST writes are enabled. Six `optibrain-agent-{dispatch,status,usage}.{service,timer}` units remain masked/inactive. Rebuild initially masks all reconstructed timers and consequential application services; deliberate recovery resumes backups/observers before any writers.

## Mandatory boundaries

Universal root mutation control, central action authority, protected baseline, exact TEST ownership, immutable journal and off-host effect claims act together. Missing/corrupt policy denies transport. Protected ownership wins over any synthetic marker. State loss, code rollback or an old approval cannot authorize replay. Books writes are independently denied. Legacy Mail/Sign, PDF/WorkDrive, Omada and connector provider writers remain denied/contained. Native Forms CRM integrations are owner-disabled; Forms fallback is OFF. Authentication fails closed. HTTP 200 proves API liveness only.

Never mutate protected records, delete real Leads, fuzzy-merge identities, send outside an explicitly graduated family, perform marketing/SMS/calls/Sign sends, write Books, invoice/pay/credit, enable broad automation/canary, automatic pricing/scheduling, revive the development worker, destroy evidence, upload/regenerate the offline AGE identity or destructively alter production/OVH without explicit human authority for that exact action. Existing family authorization covers only its validated triggers/eligible records, not a broad send/write flag. Ordinary engineering inside the authorized mission needs no routine approval.

Customer-only stop: `sudo /usr/bin/python3 -I /usr/local/lib/optibrain/customer_runner.py --stop`; internal intake/Tasks/attribution/Finance observation continue. Internal stop remains `sudo /usr/bin/python3 -I /usr/local/lib/optibrain/lifecycle_runner.py --stop`. Original internal cutoff/run is preserved; expiry/verification-limit renewal is deliberate and recorded, never a reset of claims or an unnoticed outage.

## Recovery orientation

Source tag, local online backup, encrypted immutable R2 backup, confirmed OVH snapshot and tested clean reconstruction are distinct recovery layers. AGE **public recipient only** is on the VPS; the private identity remains owner-held offline. Owner access/MFA to OVH, Cloudflare, GitHub, Zoho and DNS ownership is documented in configuration. OVH access is BOTH direct VPS credentials in `/etc/opticable-workflow-api.env` and gateway Worker secret bindings. Provider credential scopes are broad; the enforced client boundaries below remain authoritative. Production is `vps-214ba8cd.vps.ovh.ca`, service `41299869`, `ovh-ca`, region `os-bhs6`.

The direct OVH client rejects non-GET operations; gateway mutations require explicit human confirmation, reason and audit. Business automation grants no infrastructure mutation authority. Follow the recovery guide for a fresh OS. Do not run old installers, copy a live server blindly, replay old journals or depend on a VM snapshot. Full production DNS cutover/provider reconnect and a guaranteed RTO are not claimed by the isolated test.

Read the [lifecycle matrix](OPTIBRAIN_LIFECYCLE_AUTOMATION_MATRIX.md) before modifying business behavior. New eligible Leads may convert only after the owner’s CRM UI qualification; protected customer associations are excluded. Finance remains native CRM UI backed by Books. Root authorization is independent of the service-writable DB and each effect has a fresh off-host claim.

Scheduling/field work, pricing and Finance create/send remain human. Sign sends remain manual under the provider license limitation. Service reuse, return visits, native completion evidence and invoice/payment observations now organize operational work. Automatic Case creation remains unarmed without a deterministic support producer. English Forms delivery, Forms campaign continuity, GA4 and genuine Deal-linked revenue attribution remain bounded noncritical gaps; do not fabricate evidence or restore an uncontrolled native Forms CRM writer.

Read [recurring service](OPTIBRAIN_RECURRING_SERVICE_CONTRACT.md) and [marketing attribution](OPTIBRAIN_MARKETING_ATTRIBUTION_CONTRACT.md) before changing those observers. Existing root internal runner provides hourly GET-only projections and owner Recurring/Marketing Sources views. Books recurring invoicing is canonical; no financial/advertising writer or new business module exists. Most historical Finance records lack Deal/source lineage and remain unattributed. GA4/Ads destination/consent and Forms continuity limits are explicit; do not confuse an internal conversion plan with provider upload authority.

Read [measurement](OPTIBRAIN_MEASUREMENT_CONTRACT.md) and [Business Overview](OPTIBRAIN_BUSINESS_INTELLIGENCE_CONTRACT.md) for current GA4/Ads observations, historical native linkage gaps, metric/period definitions, owner reporting and cost limitations. Conversion export is READY for manual first-event verification after native secondary destination/schema proof; uploads stay OFF pending a genuine eligible click/advertising-consent/outcome receipt. No export timer is active. GA4/Forms remain PARTIAL with the single owner batch. No historical attribution or margin is inferred.

## Apollo coexistence and Today Sales

Read [sales intelligence contract](OPTIBRAIN_SALES_INTELLIGENCE_CONTRACT.md) and [current Claude/Apollo flow](CURRENT_CLAUDE_APOLLO_FLOW.md). `/v1/operator/sales` adds coordinated reply/Lead/Deal/Estimate/customer attention and up to five additive public project reviews. Existing Apollo outreach stays under Claude/Apollo; new OptiBrain prospecting is SHADOW ONLY, with no sends/enrollments/CRM bulk promotion. Exact collision and suppression holds never grant contact clearance. Local owner feedback does not alter Apollo suppression. No takeover/migration is authorized.

## Acquisition intelligence — research only

[Acquisition](https://optibrain.opticable.ca/v1/operator/acquisition) combines search, company/project signals, competitors, SEO/content and future paid research into a handful of owner actions. Read the [acquisition contract](OPTIBRAIN_ACQUISITION_INTELLIGENCE_CONTRACT.md), [market policy](OPTIBRAIN_MARKET_OPPORTUNITY_CONTRACT.md) and [sources](OPTIBRAIN_MARKETING_DATA_SOURCES.md). Raw research stays outside CRM; Claude/Apollo keeps outreach. Priorities are market-based, with unknown demand/CPC/ROI labeled. Existing pages are improved before duplicate pages are proposed; new-page candidates need owner expertise and demand validation. No content publication, campaign change, cold send or conversion upload is enabled by this view.

Completion remediation1–2: GA4 canonical530093120, restored consented site collection, strict Forms acquisition-context parser (native field setup remains owner-bound), sample/geography confidence and fail-closed trigger target reviews. Google uploads remain READY BUT OFF. See [current capability matrix](OPTIBRAIN_SYSTEM_CAPABILITY_MATRIX.md) and [owner actions](OPTIBRAIN_OWNER_ACTIONS_CURRENT.md).
