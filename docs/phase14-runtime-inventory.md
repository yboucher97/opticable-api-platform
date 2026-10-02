# Phase 14 runtime and execution inventory

**READ-ONLY reconnaissance. Source/production/main: `4bc1beec112c55b161c3025529733d0f0b1213b3`; API 1.11.0.** Capture window: 2026-10-02 UTC / 2026-10-01 America/Toronto. This is a before-state, not implementation or permission to activate writers.

Evidence: [systemd](phase14-evidence/systemd.json), [sockets/Caddy](phase14-evidence/routes.json), [external schedulers](phase14-evidence/external.json), [runtime settings](phase14-evidence/runtime.json), [additional checks](phase14-evidence/extra.json), [source routes/commands](phase14-evidence/source-map.json). Provider contents and credential values are excluded. Static route discovery includes declarations in optional modules; registration and reachability matter more than decorator presence.

## Services, processes and privileges

| Component | Classification | Actual identity/state | Responsibility / root assessment |
|---|---|---|---|
| `opticable-workflow-api.service` | CANONICAL | `opticable-workflow-api`, active; PID 282992 at capture | FastAPI, operator views, event kernel and four background execution/observation threads. Unprivileged and sandboxed. |
| `opticable-password-pdf.service` | SUPPORTING | `opticable-password-pdf`, active; PID 271561 | Local PDF service; CRM and WorkDrive disabled and writer methods intrinsically retired. Public job/results fenced. Review eventual demand before retirement. |
| `opticable-omada-site.service` | SUPPORTING | `opticable-omada-site`, active; PID 270987 | Public health-only surface; job creation blocked. No foreground/webhook job at capture. Retain until its recovery/health dependencies are reviewed. |
| `caddy.service` | CANONICAL | `caddy`, active; PID 777 | TLS and proxy/containment guards; not root. |
| `caddy-api.service` | LEGACY | `caddy`, disabled/inactive | Superseded duplicate proxy definition; ARCHIVE candidate after verifying no recovery references. |
| `opticable-phase9-intake-receipts.service` | CANONICAL | API UID, oneshot, last result success | Local receipt collection/matching; 300 s timeout. Service is disabled as a boot unit but its timer is enabled; **not dead**. |
| `opticable-phase10-service-events.service` | CANONICAL | API UID, oneshot, last result success | Test service projection/occurrences; 300 s timeout. |
| `opticable-phase12-test-runner.service` | CANONICAL | root, oneshot, last result success | Reconciliation and bounded Test action scheduling; 180 s timeout. **ROOT TEMPORARILY ACCEPTABLE**: exact root-owned manifests, off-host claims, acknowledgment journals and protected policy. Candidate for separating unprivileged observation from a narrow privileged boundary; do not give the API UID root policy/claim ownership. |
| `optibrain-backup.service` | CANONICAL | default root, oneshot, last result success | **ROOT REQUIRED** for protected configs/credentials/state and metadata. Bounded DAC/ownership/identity-switch capabilities support a read-only Git probe. Installed root-owned helper; 45 m. |
| `optibrain-phase2a-upload.service` | CANONICAL | root, oneshot, last result success | **ROOT TEMPORARILY ACCEPTABLE**: private archive, public AGE recipient, restricted R2 credential and private upload state. Encryption/network phase could eventually use a dedicated UID with narrowly staged inputs, without widening secret or deletion access; 46 m. |
| `optibrain-agent-{dispatch,status,usage}.{service,timer}` | DISABLED | six masks, inactive | Persistent development runtime retired/quarantined; authorization file absent. Keep masks. |
| Interactive Codex CLI/app-server and code-mode host | SUPPORTING | operator UID 1001 | Manual workspace processes, not the retired persistent development worker. Manual sudo/root authority remains untouched. |
| Other host services/socket units | SUPPORTING | OS infrastructure; full list in evidence | SSH, resolver/network, journald/syslog, firewall/fail 2 ban, OS updates, systemd/user IPC and disk services. Not application automation. Not-found/inactive historical OS units are DISABLED, not optimization targets. |

There are **3 resident application services, 5 application oneshots, and 1 active shared proxy**. Three configured OptiBrain jobs use root; none is a continuously running root application daemon. Masked development definitions do not add active root authority. Manual `optibrain-admin`, `optibrain-admin-update` and the installed exact-SHA deploy gate require root to manage protected configuration/service state; keep them as administrative boundaries. Their historical backups are not running services.

## Timers and in-process scheduling

| Origin | Classification | Cadence | Actual current behavior |
|---|---|---|---|
| `optibrain-backup.timer` | CANONICAL | 02:30 UTC daily, ≤15 m jitter, persistent | Installed helper uses `--preserve-existing`; configured 7-generation pruning is bypassed. |
| `optibrain-phase2a-upload.timer` | CANONICAL | 03:00 UTC daily, ≤15 m jitter, persistent | Encrypt, create-only upload, independent download/hash verification; no remote deletion. |
| `opticable-phase9-intake-receipts.timer` | CANONICAL | boot + 2 m, then every 5 m | Mail, complete bounded pending-Lead matching, authenticated connector export; local evidence only. |
| `opticable-phase10-service-events.timer` | CANONICAL | boot + 10 m, hourly | Five conditional CRM module reads; daily full inventory; stable Test service events. |
| `opticable-phase12-test-runner.timer` | CANONICAL | : 00/: 30, ≤120 s jitter | Reconcile before kill; ≤4 due actions/≤2 theoretical writes. Writes currently OFF. |
| API `automation-recovery` thread | CANONICAL | 5 s healthy / 30 s after error; stop after 3 consecutive errors | Recover/route pending core work; hourly terminal-claim/event metadata maintenance. This is **not** Codex development automation. |
| API `automation-health-watchdog` | SUPPORTING | 30 s | Local DB/worker health; emit audit only on meaningful changes. No normal external provider polling. |
| API `automation-delta-sync` | CANONICAL | loop 5 s; configured CRM Leads job 300 s | Checkpoint is `failed`, `authentication_failed`; last success 2026-09-30T23:29:02Z. Failed checkpoint is skipped; currently no incremental Lead polling. No resume performed. |
| `DesiredDriftObserver` on delta thread | SUPPORTING | hourly | Three desired-state documents; about 16 CRM metadata/watch GETs per complete scan. Field reads already cached per module within each document. Runs even while Lead checkpoint is failed. |
| API `NativeNotificationWorker` | SUPPORTING | 300 s | Exact CRM watch GET and local verification/status journal. Automatic provider renewal remains forbidden by universal transport. Current local binding mismatch/`configuration_drift`; latest observations `degraded`. |

Sources: `workflow/api.py:610`, `automation/sync_runtime.py`, `desired_drift.py`, `native_notifications.py`. Earlier wording that there was “no internal background scheduler” is incomplete. There are no OptiBrain entries in root/operator/API crontabs or inspected `/etc/cron.*`; the application threads above are active scheduling surfaces.

## Sockets, ports and Caddy

| Binding | Classification | Exposure/purpose |
|---|---|---|
| `127.0.0.1:8100` TCP | CANONICAL | Core API origin |
| `127.0.0.1:8000` TCP | SUPPORTING | PDF origin |
| `127.0.0.1:3210` TCP | SUPPORTING | Omada origin |
| `127.0.0.1:2019` TCP | SUPPORTING | Caddy administration, loopback only |
| `*:80`, `*:443` TCP; `*:443` UDP | CANONICAL | Caddy HTTP/TLS/HTTP 3 |
| `0.0.0.0:22`, `[::]:22` TCP | SUPPORTING | SSH / forced-command deployment |
| `127.0.0.53:53`, `127.0.0.54:53` TCP/UDP | SUPPORTING | OS resolver |
| Host-interface `:68` UDP | SUPPORTING | DHCP |
| `127.0.0.1:33587`, `:39651` TCP at capture | SUPPORTING | Interactive Codex session sockets; ephemeral |
| OS systemd/user/IPC UNIX sockets | SUPPORTING | 27 systemd socket rows and additional process IPC in evidence; none is an OptiBrain application socket-activation unit |

Counts: **3 application origins; 6 application/proxy TCP port numbers; 10 distinct host TCP ports / 12 TCP listener rows; 3 UDP port numbers / 4 UDP rows**. Total distinct numeric TCP/UDP ports is 11. Counts include manual Codex sockets and OS services; future comparisons must use the same definition.

`/etc/caddy/Caddyfile` imports only `conf.d/*.caddy`. Active `opticable-api-platform.caddy` routes `optibrain.opticable.ca`: `/pdf/*` strips prefix →8000; `/omada/*` →3210; `/workflow/*` and default →8100. Root aliases redirect 308 where not preempted. Before proxying, legacy job POST aliases and job-result paths return 403; all `/omada` routes except `/omada/api/health` return 403. `.caddy.pre-optibrain-host` is a LEGACY inactive backup because it does not match the import glob. Preserve matcher order. Application intrinsic fences and operator JWT/shared-key checks remain independent protection.

## GitHub and Cloudflare

| Scheduler/workflow | Classification | Live/source status and authority |
|---|---|---|
| Monitor OptiBrain Production Health | SUPPORTING | Active `*/15 * * * *`; four public health GETs **plus** authenticated core provider inventory and GitHub incident-issue lookups/writes. Roughly 480 core/Worker HTTP GETs/day and ≥96 GitHub issue-list calls/day; normal inventory does not validate live auth against providers. |
| Validate API Platform | CANONICAL | PR/main path-filtered + manual; Python full kernel suite, worker tests/check, Omada build. |
| Deploy API Platform | CANONICAL | Successful Validate workflow_run/main → forced SSH command → root exact-SHA gate; a merged docs-only change outside filters does not automatically deploy. |
| Deploy Durable Control Plane | CANONICAL | Successful exact-main validation prerequisite; separate Worker target and receipt. |
| Customer Lifecycle Owner Digest / Mailbox Poll / Schedule Customer Lifecycle | DISABLED | All `disabled_manually`; all three cron definitions removed. Dispatch definitions preserved for history. No reenable. |
| Validate Autonomous Core | LEGACY | Provider metadata says active; no current workflow file. No present scheduling source, not proof of a running worker. Review metadata retirement only. |
| AI connector deploy/validate/routing-test workflows | CANONICAL / SUPPORTING | Three active metadata entries; current default-branch files fetched and contain **no cron**. Separate repository/release target. |
| `opticable-control-plane` cron | CANONICAL | Only live Cloudflare schedule among ten inspected account scripts: `*/15 * * * *`. Toronto semantic slots: Mail hourly, Sign 07:15–21:15 at odd hours (8/day), Books 07:15 (1/day). No digest producers. |
| `opticable-business-events` queue + `opticable-business-workflow` | CANONICAL | Queue → deterministic Workflow instance → authenticated core event POST; max batch 10, retries 5; workflow transient retries 8; permanent 4xx not retried. Queue publication is local orchestration, not business-write authorization. |
| `opticable-business-events-dlq` | SUPPORTING | No consumer; retain failed evidence, never drain during reconnaissance. |
| `opticable-ai-connector` / OAuth KV | SUPPORTING | Provider reads, receipt export, OAuth; non-GET/HEAD Zoho/business writes contained before OAuth. No schedule. |
| `opticable-website` | SUPPORTING | Public website/forms entry point; outside core scheduler ownership. No schedule. Native Forms Add/Update/Upsert disabled by Phase 13 owner attestation; no new admin-state certainty claimed. |
| `opticable-camplan`, `opticable-plan2` | UNKNOWN | D1/R2-bound adjacent apps; no cron. Actual owner use and external callers were not established. Do not remove from binding names alone. |
| `opticable-website-{design-preview,performance-preview,preview}`, `website-test` | UNKNOWN | No cron; preview names are removal-review candidates, not proof of disuse. Some share D1 namespaces; current usage/retention/recovery dependencies unknown. |
| `hoplajeux-reservation-email` | SUPPORTING | Separate account application with email binding, outside OptiBrain scope; no cron. Do not change. |

Live provider pagination reports 8 main-repo workflow metadata entries (7 current files plus orphan), 3 connector workflows, 10 Cloudflare scripts, 1 Cloudflare cron, 2 business queues, 1 durable Workflow. Cloudflare queue depth was not read/claimed; instance status sample is bounded, not backlog depth. GitHub scheduled-workflow count 1 is scoped to the two OptiBrain repositories, not all repositories owned by the account.

## Execution authority map

Universal rule: root `/etc/optibrain/mutation-control.json` has `test_writes_enabled=false`, `real_canary_allowed=false`; only `crm.task.create` is an admissible family when all separate gates are deliberately satisfied. Current admissible provider transport is therefore **zero**. Central policy coverage is 1/1 potentially admissible family; 22 other audited families remain forbidden/disabled. Test flags, HTTP acceptance, queued events and approvals cannot override universal/lower fences. Kill does not suppress read reconciliation or evidence.

| Origin/family | Reads | Local writes | Provider access | Real / TEST_ONLY authority | Central coverage / kill |
|---|---|---|---|---|---|
| Public `/health`, `/v1/system/health`, service health | Config/in-memory state | None ordinarily | None | None / none | Provider-free; not affected by write kill |
| Authenticated `/v1/system/providers`, OAuth status | Config/credential-presence files | None for normal status | No normal live auth probe | None / none | Presence is not provider validity |
| Operator sales/detail/source/lifecycle/operations GETs | Fresh CRM/Mail + local evidence | Some getters call idempotent schema initialization; no business effect | GET only | Real reads / Test scoped views | No mutation authority; fresh mutation preconditions never use display caches |
| Operator autonomy/approvals/exceptions GETs | BusinessJournal | Idempotent schema setup possible | None | No provider authority | Shared journal/state is preserved under kill |
| Operator approval/consume/create-review POSTs | JWT, exact fresh target/payload/version, ledgers | Issue/consume evidence where allowed | Legacy CRM/Mail transport forbidden | Real 0 / central TestTask only in separate root runner, currently 0 | Same-origin + JWT + one-use gates; source-pinned registration; kill before transport/consume where required |
| `/v1/automation/events`, lifecycle intake/email/smoke POSTs | Payload, workflow definitions | Immutable event/dedupe/routes/runs/audit | Enabled observers may GET; forbidden writers deny | Real 0 / Test transport 0 now | Event intake is not business-write authorization |
| `/v1/automation/webhooks/{endpoint_name}` | Configured exact source-secret verification | Native event/origin/dedupe evidence | Downstream GET observers | Real 0 / Test 0 now | Credential authentication plus universal transport; watch delivery and delta fallback are distinct protections |
| Desired-state validate/plan/drift/apply, generic provider APIs | Auth/config/review document | Plan/audit/intent | GET; runtime consequential writes denied; technical GH/CF admin requires root one-use context | Real 0 / business Test 0 | Root technical administration separate from business authority; no general runtime grant |
| Replay/redrive/backfill/claim-cleanup endpoints | Core state, unsafe-effect eligibility | Bounded replay/maintenance/audit | Resumed observer GETs only under current fences | Real 0 / Test 0 now | Reconciliation/attempt/claim fences; do not invoke during this mission |
| Legacy PDF/Omada/site-password HTTP jobs/results | Config/jobs if reachable internally | Potential local jobs only; public routes 403 and core intrinsic gates | Business writers retired/forbidden | Real 0 / Test 0 | Preserve Caddy plus intrinsic fences; standalone adjacent code is not authorization |
| OAuth start/callback (core/connector) | Signed state + provider authorization code | Credential/token stores | Authentication exchange | Business authority 0 | OAuth acquisition is not permission to mutate; do not rotate/reconnect in this mission |
| Five systemd jobs | As timer table | Receipt/events/journal/backup/cache | CRM/Mail GET, R2 storage transport | Protected 0, real 0; TestTask potential currently killed | Root kill + runner kill; read reconciliation before denial |
| API recovery/delta/drift/native/watchdog threads | DB/checkpoints/provider metadata | Queue/health/verification/audit/cache | GET; renewal attempts denied | Real 0 / Test 0 | Preserve rehydration/dedupe; failed delta not restarted; no automatic mutation retries |
| CF cron/queue/manual event ingress | Slot/config/event | Queue/Workflow state | Core authenticated HTTP; downstream observers GET | Real 0 / Test 0 | Core universal policy is authority, Worker acceptance is not |
| GitHub CI/deploy/manual dispatch/health | Source/CI/health/auth | CI artifacts, technical deployment receipts, GitHub incident issues | GH/CF/SSH technical actions | No business authority | Exact validated main + root authorization + preserved kills; scheduled health has issue-write permission |
| Manual `ops/phase8`–`phase12` Test tools; phase4–7 campaign tools | Root registry/protected evidence/exact provider reads | Test/legacy attempt journals | Historical mutator code retained but forbidden transport | Real 0 / TestTask only centrally, currently 0 | Lower legacy grants cannot bypass central root transport. Do not execute old campaigns. |
| Manual backup/admin/deploy/recovery commands | Protected config/releases/archives | Technical state/services only under command contract | R2/GH/CF technical access | Business authority 0 | Keep static installed source/root validation; manual sudo remains available |

The source appendix lists 92 Python route declarations and 43 Python manual entry points, including optional/unregistered declarations. Dynamic Phase 12 route factory creates three routes from one declaration. Also inspect shell manual helpers under `deploy/`, `ops/backup/` and adjacent `install.sh`/`update.sh`; these are manual technical entry points, not extra enabled schedulers. FastAPI framework `/docs`, `/redoc` and `/openapi.json` are read/introspection surfaces. Node adjacent endpoints and connector REST/MCP are separately contained surfaces; they do not add an admissible business executor.

## Overlap decisions — recommendations only

| A / B | Decision | Why / acceptance for later change |
|---|---|---|
| CF business cron / three GitHub business cron definitions | KEEP A; B DISABLED already | Preserve CF ownership and disabled metadata/source. Do not claim a new Phase 14 saving. |
| General Mail observer / Forms notification collector | KEEP A AND B; MERGE shared read efficiency only | Different semantics: general inbox vs authenticated immutable Forms delivery and complete matching. Share cache/checkpoint mechanics without discarding either evidence contract. |
| Hourly Mail body fetch / downstream event dedupe | MERGE read dedupe earlier | Content is retrieved before child-event duplicate detection. Known unchanged messages can avoid repeat body reads after completeness/authentication proof. |
| Native watch / CRM delta fallback | KEEP A AND B | Native delivery lacks universal loss guarantee; independent delta checkpoint prevents silent notification loss. Delta currently failed; investigate before any resume. |
| Native watch verification 300 s / hourly desired-state watch read | MERGE duplicated status reads or stagger reuse | Root verification/reconciliation evidence must remain fresh enough; no automatic renewal authority added. |
| Lifecycle operator / recurring-services operator / hourly collector | MERGE shared display projection | Same five-module model; display cache with scope/time/completeness only. Keep daily full deletion checks and fresh action reads. |
| Operations list / project detail | MERGE projection builder, bounded target filtering | Detail currently reads all three registered Lab projects; batching already improved 22 → 9. Do not undo exact owned-ID validation. |
| Phase 9 intake events / provider receipts / connector KV | MERGE identity/view contract; keep provenance stores initially | Different evidence boundaries; not interchangeable duplicates. Preserve source namespace, immutable IDs and attempt history. |
| Core watchdog / GitHub HTTP health | KEEP A AND B; MERGE operator alert presentation | Local execution safety and external availability detect different failures. Add stale timer/backup/auth/deploy signals to existing channels. |
| Local archive / AGE cache / off-host locked archive | KEEP A AND B; retention policy | Restore source, staged ciphertext and independent disaster copy. Retention can bound local duplicates without removing evidence holds or remote locks. |
| Current root release gate / phase-specific installed reconcilers/loaders | KEEP A; DEPRECATE B after recovery review | One exact-SHA current gate; old helpers embed stale prerequisites. Preserve hashes/tags/recovery records before archive. |
| Core OAuth gateway / PDF direct clients / connector OAuth | KEEP core and connector trust domains; DEPRECATE dormant PDF mutations | Core already shares secure access cache/interprocess lock. Connector has separate credential/scope/recovery ownership. Do not collapse authentication boundaries for code neatness. |
| Archived development runtime / manual Codex | DISABLED runtime; KEEP manual Codex | Preserve retirement archive/masks; do not treat manual session processes as enabled development worker. |

## Configuration sources and precedence

Observed: repository `workflow/config.py` defaults; deployed environment files; lexically ordered systemd drop-ins; root workflow directory override; root policy/source-pin/approval JSON; PDF brand JSON; Caddy imports; Cloudflare vars/secret bindings; GitHub workflow secrets/permissions; provider-native Forms/watch state. `production-state.yaml` contains September 25 observations and an old deploy SHA/version; **HISTORICAL**, not runtime truth.

Current safety precedence is conjunctive: root universal denial → exact ownership/protected manifest → central immutable claim/journal → lower provider fence → family flag/approval. A permissive lower value cannot overrule denial. Ordinary configuration flows defaults → effective service environment → explicit root selected config/manifest; systemd drop-ins select paths/ExecStart, and later EnvironmentFiles may replace earlier values. The API process retains startup values until restart; the collectors load different env files, and the root runner does not inherit all API configuration by default.

Duplicated values: API keys/endpoints between GH/CF/core; CRM mailbox/organization identities in Worker/defaults/provider code; Test registries in repository, root phase paths and `/etc`; source SHA across env, manifest, Git and deployment receipts; timer behavior in repo vs installed units; backup retention 7 vs installed preserve-existing; WorkDrive/PDF settings between env and JSON. Native watch expiry is currently **19:38:19 UTC in file/process vs20:38:19 UTC at provider on October 7**, with matching token/destination/events. Explain this drift rather than quietly replacing configuration.

Recommended model: one documented non-secret deployment manifest selects immutable release/defaults and explicit per-service env paths; effective env supplies functional settings; root-owned policy/allowlists only restrict authority; provider state is readback evidence, never a policy override. Technical deployment pins and safety state remain independent. Define per-field precedence, reject contradictory safety values, expose a redacted effective-config/source report. Do not move secrets or merge the connector/core credential domains.
