# OptiBrain: start here

AUTHORITATIVE CURRENT. API **1.12.0**. OptiBrain is Opticable’s observation, owner-review and guarded workflow platform. Production real automatic writes are **OFF**, `REAL_CANARY_ALLOWED=false`, TEST business writes **OFF**, and the persistent Codex development worker **OFF**. All 123 protected business records are read-only. This entry point is sufficient without any phase conversation.

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
sudo systemctl list-timers --all optibrain-backup.timer optibrain-phase2a-upload.timer opticable-phase9-intake-receipts.timer opticable-phase10-service-events.timer opticable-phase12-test-runner.timer --no-pager
sudo cat /run/optibrain-readiness/status.json
sudo cat /run/optibrain-readiness/queue-depth.json
sudo cat /etc/optibrain/mutation-control.json
sudo optibrain-admin verify-latest
sudo cat /var/lib/optibrain/phase2a/state.json
df -h /
sudo /opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -I /opt/opticable-api-platform/ops/phase15/inspect_host.py --output /var/lib/optibrain/inspection-YYYYMMDDTHHMMSSZ.json
```

The last command privately authenticates health/readiness and checks five active DBs, service/mask state and writer policy. It does not print keys or customer fields. Add `--protected` for the GET-only 123-record version comparison; add `--ovh` for one direct GET of the production VPS. Never print service environments. Open [Today](https://optibrain.opticable.ca/v1/operator/today) in the owner’s normal Cloudflare Access session; `curl -I https://optibrain.opticable.ca/v1/operator/today` should encounter Access login, while unauthenticated origin GET should return 401. Never forge a production owner JWT.

## System in one minute

Ubuntu 24.04, FastAPI/Python 3.12 API on loopback 8100; PDF support on 8000; contained Omada/Node 22 support on 3210; Caddy on public 80/443. SSH is public 22. Five separate active SQLite stores retain events, receipts, intake, service occurrences and action evidence; eight stores are backed up including three historical copies. CRM owns business entities; local journals own event chronology, dedupe, approvals and execution evidence. Cloudflare’s cron/queues/Workflow deliver authenticated observations. The connector has a separate OAuth domain and remains contained. GitHub has one scheduled public health monitor; three business schedules remain disabled.

Five VPS timers: local backup, off-host upload, receipt observation, service observation, bounded TEST reconciliation/readiness. An active TEST timer does **not** mean TEST writes are enabled. Six `optibrain-agent-{dispatch,status,usage}.{service,timer}` units remain masked/inactive. A rebuilt host initially masks **all five** application timers and the TEST service as well.

## Mandatory boundaries

Universal root mutation control, central action authority, protected baseline, exact TEST ownership, immutable journal and off-host effect claims act together. Missing/corrupt policy denies transport. Protected ownership wins over any synthetic marker. State loss, code rollback or an old approval cannot authorize replay. Books writes are independently denied. Legacy Mail/Sign, PDF/WorkDrive, Omada and connector provider writers remain denied/contained. Native Forms CRM integrations are owner-disabled; Forms fallback is OFF. Authentication fails closed. HTTP 200 proves API liveness only.

Never mutate protected records, convert/delete real Leads, merge real identities, contact customers/prospects, send Mail/SMS/Sign, call, write Books, invoice/pay/credit, enable real automation/canary, revive the development worker, destroy audit evidence, upload/regenerate the offline AGE identity, restore a snapshot over production, reinstall a live VPS, or perform destructive OVH operations without a **new explicit human mission** covering the exact action. Ordinary engineering within an authorized mission does not need another routine approval.

## Recovery orientation

Source tag, local online backup, encrypted immutable R2 backup, confirmed OVH snapshot and tested clean reconstruction are distinct recovery layers. AGE **public recipient only** is on the VPS; the private identity remains owner-held offline. Owner access/MFA to OVH, Cloudflare, GitHub, Zoho and DNS ownership is documented in configuration. OVH access is BOTH direct VPS credentials in `/etc/opticable-workflow-api.env` and gateway Worker secret bindings. Both clients allow current runtime reads only, despite broad provider credential scopes. Production is `vps-214ba8cd.vps.ovh.ca`, service `41299869`, `ovh-ca`, region `os-bhs6`.

Follow the recovery guide for a fresh OS. Do not run old installers, copy a live server blindly, replay old journals, or depend on a VM snapshot. Full production DNS cutover/provider reconnect and a guaranteed RTO are not claimed by the isolated test.
