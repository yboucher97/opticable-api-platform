# OptiBrain Codex onboarding

Start here. **This snapshot is Phase 14 preparation, not implementation or authority to activate automation.** Production/current main: `4bc1beec112c55b161c3025529733d0f0b1213b3`; API 1.11.0; Phase 13 COMPLETE/PASS. Revalidate current state before changing anything. Read the current user instruction as the mission scope.

## Minimum reading and authority

1. [Safety invariants](OPTIBRAIN-SAFETY-INVARIANTS.md) and [master runbook](OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md).
2. [Phase 13 closure](phase13-final-closure.md), with `/var/lib/optibrain/phase13-closure/final-receipt.json` and current `/var/lib/optibrain/phase13-remediation/deployment.json` for actual final/deployed SHA.
3. [Phase 14 reconnaissance](phase14-reconnaissance.md) and [implementation order](phase14-implementation-plan.md).

Use [runtime/authority](phase14-runtime-inventory.md), [state/DB](phase14-state-inventory.md), [flags/code/tests/docs](phase14-code-and-documentation-inventory.md), [control matrix](phase13-control-matrix.md) and [timer matrix](phase13-timer-matrix.md) for a relevant drill-down. Recovery-only tasks also use [local backup](OPTIBRAIN_PHASE1_LOCAL_BACKUP.md), [encrypted off-host recovery](OPTIBRAIN_PHASE2A_OFFHOST_RECOVERY.md), [root bootstrap](OPTIBRAIN_PHASE2B_ROOT_BOOTSTRAP.md), [forward recovery](OPTIBRAIN_PHASE6_GATE_G_RECOVERY.md) and [owner procedure](phase13-owner-manual-actions.md). Do not reconstruct 13 phases before doing ordinary work; older phase docs are historical evidence, not present authority.

Live root policy/config and independently validated runtime receipts are operational truth. Repository defaults, filenames, old roadmap statements and `production-state.yaml` are not current deploy proof. An enabled workflow/approved item does not overrule provider transport denial. The master runbook digest is root-authorized; a casual doc edit must not silently repin that contract.

## Architecture

OptiBrain is the Opticable owner/operator's event and business-observation platform. One Linux core hosts FastAPI (`apps/workflow-api/workflow`) and SQLite journals. Cloudflare durable control plane schedules/queues safe observation events into the authenticated core. A separate AI connector handles provider reads/OAuth/intake receipt export. Existing owner HTML views are implemented in Python renderers, with Cloudflare Access JWT verification and private/no-store responses.

Core event intake normalizes, deduplicates, routes and journals work. Providers execute only through independent gateway/control fences. Central BusinessJournal holds action proposals, risk/ownership/approvals/schedules and immutable effect evidence. Root runner reconciles Test effects before deciding whether killed work can proceed. Current real business writes are forbidden. Adjacent PDF and Omada services remain running but provider mutators/legacy public job paths are contained.

Important code: `automation/mutation_control.py`, `crm_write_boundary.py`, `business_autonomy.py`, `remote_effects.py`, `test_lab_boundary.py`, `events.py`, `store.py`, `zoho_gateway.py`, `zoho_oauth.py`, `phase7_registration.py`, `operator_access.py`; read/projection code `sales_queue.py`, `sales_operator_view.py`, `phase9_form_receipts.py`, `customer_lifecycle.py`, `service_inventory.py`, `operations.py`. Shared display state never authorizes a mutation.

## Host/services/timers

Production checkout `/opt/opticable-api-platform` (detached release); main checkout `/home/optibrain/phase10-lifecycle`; this recon checkout `/home/optibrain/phase14-recon`, branch `phase14/reconnaissance-20261001`. Work in an isolated branch/worktree. Existing installed `.venv` and preserved baseline/diagnostic untracked files are intentional; do not clean production.

Three service UIDs run core 8100, PDF 8000, Omada 3210 on loopback. Caddy runs as `caddy`, serves `optibrain.opticable.ca`, strips `/pdf`, `/omada`, `/workflow` prefixes, fences legacy routes 403 before proxy. Admin 2019 is loopback. SSH 22 is separate. Current installed unit/drop-in config takes precedence over repository examples.

Five legitimate timers: local backup 02:30 UTC daily; encrypted upload 03:00 UTC daily; receipts every 5 m; service events hourly; Test runner : 00/: 30. Root jobs: backup/uploader/runner. Collectors use API UID, per-job locks and 300 s timeouts. Root runner 180 s; backup 45 m/upload 46 m. All last results successful at recon.

API also starts recovery 5 s (30 s after errors), health 30 s, delta loop 5 s/configured Leads 300 s, hourly desired drift, native-watch 300 s. **Current delta checkpoint failed authentication and is not polling**; native local binding/expiry drift exists. Do not confuse these with the masked Codex development worker. Six `optibrain-agent-{dispatch,status,usage}.{service,timer}` units remain MASKED; authorization absent. Manual Codex and sudo remain available.

Only one GitHub cron remains: 15 m health. Three GitHub business workflows disabled/source cron removed; orphan Validate Autonomous Core metadata has no file. One CF cron `*/15` generates Toronto-hour Mail, 8 daytime Sign observations/day and daily Books. CF events queue → durable Workflow → core event endpoint. DLQ has no consumer; do not drain.

## Providers and data

Zoho CRM/Service_Locations/Services are canonical business facts, with exact Test ownership and protected baselines. Mail supplies authenticated Forms receipts and controlled reply evidence; Forms native CRM Add/Update/Upsert was disabled by owner-admin confirmation. Do not submit forms or invent supported API proof for native settings. Sign and Books are observers only; Books writes 0. WorkDrive/Projects and PDF provider mutation paths retired/forbidden. Core Zoho refresh credentials/shared access cache have different roles; cache is interprocess-locked.

Google admin, GH App, Cloudflare, OVH, Windsor, Apollo and AI adapters exist; configured does not mean live-auth-verified or scheduled. Apollo creditsOFF; Gemini unconfigured. Connector OAuth/KV is a separate trust domain; do not merge/move secrets. Public health “connected” is generally credential presence, not a successful provider request.

Five active DBs under `/var/lib/opticable-workflow-api/output/automation`: `automation.db` (WAL, core), `phase9-form-receipts.db`, `phase9-intake.db`, `phase10-service-events.db`, `phase12-autonomy.db` (others DELETE). Five active + three historical root DBs are online-backed-up. Root `/etc/optibrain` policy/source/Test/protected/projection files and `/var/lib/optibrain/phase*/test-lab` registries/journals protect ownership and state-loss recovery. Local Phase 11 documents remain canonical. Preserve crosswalk IDs; replacement provider IDs must not regenerate business identity.

## Non-negotiable safety

- Protected 123 records read-only; `test_writes_enabled=false`; runner `OPTIBRAIN_BUSINESS_AUTO_WRITES=0`; `real_canary_allowed=false` (REAL_CANARY_ALLOWED FALSE).
- Only exact central `crm.task.create` is a potentially admissible Test family, currently killed; all other 22 audited business families forbidden/disabled. Per-family TestTask flag 1 does not enable it.
- Kill/ownership/source/payload/actor/expiry/version checks and root locked off-host claim must all pass; reconcile before retry. Unknown/ambiguous effects never blindly resend.
- No real canary, customer sends/drafts/replies, Books writes, provider scope changes or real automation activation without a separate exact owner-authorized mission and all applicable gates.
- No persistent development worker, stale queue/DLQ replay, old campaign/installer execution or casual source-pin/master-runbook changes.
- Do not print env/credential/OAuth/cache contents, copy the owner's AGE private identity, move secrets or expand service-UID policy/claim access. Some historical diagnostics may contain sensitive error detail; retain private evidence and summarize fixed categories.

## Deployment and recovery

Canonical core release: exact commit/PR validation →merge →exact-main successful validation →deploy workflow/forced SSH command →installed static root gate and unexpired root-reviewed authorization →prepared root-owned dependency bundle + verified backup →source/env/manifest pins →restart →health/kill checks →root receipt →public version check. Source `deploy/manual-guarded-release.py` matches current installed helper; old repository bootstrap/phase root scripts need review before use. Worker and connector deploy separately. Do not equate main CI with deployment success or venv directory name with application SHA.

Rollback restores prior Git/env/manifest/dependency pointer and healthy core; it does not restore an old DB/replay create work. Keep exact recovery tags/receipts/helpers. Normal backups use online SQLite snapshots; root configs/state and retired immutable development archive included. Ciphertext cache is excluded to avoid recursive archives; last upload state included. Local plaintext/AGE caches currently preserve all generations; do not prune without hold resolution.

Phase 13 owner-key recovery proof generation **20261001T202728Z** is held. Owner AGE private identity stays offline on trusted Windows machine. Isolated restore/boot passed with writersOFF; new-OS production replacement/DNS-TLS/provider reconnect/RTO remain later maturity work. A replacement boot starts with writer timers/dev unitsOFF and provider/off-host/local effect reconciliation first. Do not redo the drill for a read-only audit.

## Useful read-only commands

```bash
git -C /opt/opticable-api-platform rev-parse HEAD
git -C /home/optibrain/phase10-lifecycle status --short --branch
systemctl list-timers --all --no-pager
systemctl show opticable-workflow-api.service -p User -p MainPID -p ActiveState -p DropInPaths
sudo ss -lntup
curl --fail --silent http://127.0.0.1:8100/health
df -h /
free -h
sudo cat /etc/optibrain/mutation-control.json
sudo cat /var/lib/optibrain/phase13-remediation/deployment.json
```

DB inspection uses SQLite URI `mode=ro` +`PRAGMA query_only=ON`; schema/COUNT/EXPLAIN only unless the mission needs specific business facts. Do not run migration, VACUUM or restore as discovery. Authenticated reads obtain existing credentials locally without printing them or manufacturing operator identity. `optibrain-admin` has read/status and write/recovery subcommands: inspect its contract before choosing one; backup/upload/restore/timer restart are not harmless status probes.

Current release regression: `ops/phase6/validate.py --suite full`, 811 tests + 745 subtests passed in prior evidence; do not rerun for doc-only changes. Related executable work needs meaningful changed-area/safety checks and release validation, including worker tests/check and Omada containment where applicable. Never remove safety tests to speed a pass.

## Phase 14 priorities

First account for real hot reads/operational freshness; general Mail current 33 calls/run (~792/day) is the major measured read target. Receipt 7 → 1 and operations 22 → 9 already completed. Retention hold/dry-run precedes any cleanup of~16.7 GiB local archives/cache. Shared lifecycle/recurring/project displays and Today home are useful; five active DBs/root privilege redesign are later contract work. Use the implementation plan's impact/risk/effort/dependencies. Implement only the new user's authorized scope, then stop.
