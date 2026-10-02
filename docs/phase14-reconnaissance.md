# Phase 14 reconnaissance — authoritative optimization map

**PHASE 14 RECONNAISSANCE: PASS (bounded preparation, with explicit UNKNOWNs).** No implementation, migration, deployment, automation enablement, canary, customer contact or recovery drill was performed. Evidence is a point-in-time snapshot, not permanent runtime state.

| Safety/release fact | Result |
|---|---|
| Production, local main, origin/main, live GitHub main | `4bc1beec112c55b161c3025529733d0f0b1213b3` |
| API | 1.11.0; core/PDF/Omada/control-plane/connector health 200 |
| Executable production code changed | **NO** |
| Protected records / mutations | **123 / 0**; fresh GET comparison: no missing IDs, version changes or Test spoof |
| Real customer sends / Books writes | **0 / 0** |
| Root Test writes / runner automatic writes | false / 0 |
| REAL_CANARY_ALLOWED / real auto writes | **FALSE / OFF** |
| Persistent Codex development worker | **OFF**; six masks and absent authorization |
| Full 811-test release regression | **NOT RUN**; documentation/metadata validation only |

Capture window starts 2026-10-02T02:25Z (October 1 Toronto). Provider checks were GET-only except the GitHub App authentication-token exchange; no business provider mutation was requested. Normal pre-existing observers/backups continued on their existing schedule. Static inspections did not import/start the production API. Source pin/helper hashes matched existing receipts. Fresh safety evidence: [protected check](phase14-evidence/protected-check.json), [runtime](phase14-evidence/runtime.json), [external](phase14-evidence/external.json).

Read this file and [implementation order](phase14-implementation-plan.md) first. Drill down into [runtime/authority/overlaps](phase14-runtime-inventory.md), [state/database review](phase14-state-inventory.md), [code/flags/tests/docs](phase14-code-and-documentation-inventory.md). New-session entry point: [Codex onboarding](OPTIBRAIN_CODEX_ONBOARDING.md). All findings below are recommendations for a separate full Phase 14 session.

## Important current findings

1. **Mail observation still rereads content before deduplication.** Actual hourly runs used 32–33 GETs, not the older one-search-only 24/day estimate. Current latest extrapolation is 792/day for this observer, excluding receipt collection and operator requests.
2. **Basic health 200 hides operational degradation.** CRM Leads delta checkpoint is failed (`authentication_failed`, last success September 30), and native-watch local health is `configuration_drift`. Fresh watch readback matches token/destination/Lead events but provider expiry is one hour later than configured. Local verified binding also differs from current config. Do not auto-resume or rewrite that evidence.
3. **Backup retention is deliberately bypassed.** 31 plaintext backups + 35 staged ciphertext generations consume ~16.7 GiB. A hold-aware retention plan offers much greater disk benefit than DB consolidation.
4. **Runtime complexity includes in-process work.** Recovery 5 s, health 30 s, delta loop 5 s, hourly drift and native-watch 300 s are not visible in the five application timers. Earlier “no internal background scheduler” wording is corrected by source/runtime evidence.
5. **Several obvious optimizations are already complete.** Three GitHub business schedules disabled/source cron removed; receipt unchanged-window 7 → 1 Mail GET; operations 22 → 9 CRM GET; lifecycle 240 → 120 scheduled CRM GET/day with 304 display snapshots. Do not spend Phase 14 rediscovering or implementing these again.

These are operational/maintainability findings under intact universal denial, not evidence of a new critical security regression. No emergency containment was necessary.

## Current complexity and resource before-state

| Metric | Observed baseline / definition |
|---|---|
| CPU | 4 vCPU; load 0.14/0.12/0.04; vmstat second interval 97% idle, 2% user, 1% system, 0% I/O wait. Short idle sample, not peak capacity test |
| RAM | 8,127,705,088 B total; 1,243,897,856 B used, 6,883,807,232 B available; swap 2.15 GB total/~22 MB used |
| Root disk | 76,887,154,688 B filesystem; 32,738,205,696 B used, 44,132,171,776 B available, 43% |
| Running processes | 157 `/proc` PIDs at 02:30:05 UTC host capture, including manual tools |
| Application services | 3 resident + 5 oneshot definitions; Caddy is 1 shared proxy; 8 application service definitions total |
| Application timers | 5 active; 3 retired development timers masked |
| GitHub schedules | 1 active cron workflow in main/connector repos; 3 disabled business workflow definitions; 1 orphan metadata entry without file |
| Cloudflare schedules | 1 cron across 10 inspected account scripts; 2 queues and 1 durable Workflow |
| SQLite stores | 5 active, 3 historical root stores; active files 12,881,920 B; all 8 quick-check OK |
| Other state | 20 logical active/supporting state/control families; 1425 captured files, 345 JSON files mostly historical/recovery; sizes in appendix |
| Root services | 3 configured application oneshots; 0 continuous root application daemons at capture; manual administrative helpers retained |
| Listening ports | 3 origins; 6 application/proxy TCP ports; 10 distinct host TCP ports / 12 TCP sockets; 3 UDP port numbers / 4 UDP sockets |
| Feature gates | 23 behavioral gates (18 env modes/switches + 3 root JSON + 2 PDF); 16 workflow enabled values and separate safety bindings |
| Backup sizes | `/var/backups/optibrain` ~8.44 GB; `/var/lib/optibrain/phase2a` ~9.51 GB; 31 plaintext/35 ciphertext generations |
| Diagnostic journal | 81.4 MB; existing persistent cap 512 MB/90 d; application logfile~68 KB |

Exact resource output is in [resources](phase14-evidence/resources.json). Values are sampled during normal live operation; timers can add metrics/backup files while inventory runs. Exact resource capture numbers take precedence over rounded prose. More detailed unit/port counts and exclusions are in the runtime map.

## Provider call hotspots

Calls are transport counts, not vendor billable-credit measurements. “Per day” below extrapolates cadence and excludes manual audit calls, retries, changed/new records and interactive traffic unless specified. R2 operations and auth/JWKS exchanges are not fully included in current ProviderUsage instrumentation; scheduled-background drift/native checks have no dedicated usage scope. Counts are therefore a reason to improve accounting, not a billing guarantee.

| Provider/origin | Calls/run | Rough calls/day | Evidence / savings rank |
|---|---:|---:|---|
| CRM native watch verification | nominal 1 GET each 300 s | ~288 | Exact watch read in native worker; token/expiry/status mismatch currently preserved. **MEDIUM** duplicate/frequency/reuse opportunity after verification contract is repaired |
| CRM desired-state drift | ~16 GET per hourly complete scan | ~384 | Governance 4 field-module reads + 10 metadata resources; additive Lead document 1 + watch 1. Per-document field batching already exists. **MEDIUM** plan cache/identical Lead/watch read reuse; keep actual drift detection |
| CRM service collector | 5 GET, observed mean 2.42 s |120 | Five samples 25 GET; 304 reduces returned records, not calls. **MEDIUM** share display snapshots across operator requests; scheduled calls need deletion/completeness guarantees |
| CRM Leads delta | configured 1 per 300 s, plus downstream hydration per change | **0 currently**; ~288 if safely restored | Failed auth checkpoint is skipped. Recovery is operational reliability work, not a call-saving proposal. Do not silently resume |
| CRM pending Forms match |0 if none pending; 1–5 complete inventory pages if pending |0 now; 288–1440 if unresolved repeatedly | Current unmatched count 0; 1 form still needs email/identity review. **HIGH conditional** retry/backoff/incremental candidate strategy with exact completeness proof |
| CRM operator lifecycle/recurring |5 per page load each |5×loads | Same builder; both routes repeat full five-module reads. **HIGH** cross-view/request display projection reuse |
| CRM operations / project detail |9 for current three-project Lab projection; 0 live operations |9×Lab loads | Phase 13 already 22 → 9. Detail still rebuilds all projects. **MEDIUM** target only exact registered project dependencies |
| CRM admin full metadata inventory |1 + 6×modules + 9 + optional details; default~106 before detail reads; max 120 |On demand only | Bounded collector over 16 modules; not scheduled native-watch cost. **LOW** unless frequent operator/admin use is measured |
| Mail general hourly observer |32–33 observed; latest 33 =search 1 + 32 content reads |~792 at latest unchanged workload | Three runs 98 GET, ~8.63 s mean, over 20-call soft budget. Content read before event dedupe. **HIGH** known-message cache/checkpoint with overlap/daily audit; preserve missed-delivery detection |
| Mail authenticated Forms collector |1 unchanged search; 3 extra reads/new message or daily revalidation |~294 with current two-message daily audit |38 sampled runs 44 Mail GET; latest 1 Mail + 1 connector GET, ~1.16 s. Phase 13 reduction complete. **LOW** for current window; do not disable daily reauthentication |
| Mail operator controlled lead |0 without prior approved outbound; otherwise 2 + P + 3C |Workload-dependent | Sent details/header + P search pages + candidate details/header/content; repeated immutable Sent evidence is cache candidate. **MEDIUM**, fresh inbox/version preconditions remain separate |
| Forms native API |0 scheduled in current core path |0 direct Forms calls | Collection uses authenticated Mail notifications, not Forms bulk API. Native integration admin state is owner-attested; no submission was made |
| Cloudflare connector receipt export |1–20 GET pages/run, current 1 |~288 at current one-page export | Five-minute collector starts cursor at beginning each run; KV known receipts replay locally. **MEDIUM/HIGH as volume grows** server checkpoint/version contract without dropping older receipts |
| CF queue/Workflow/core delivery |33 semantic events/day (24 Mail + 8 Sign + 1 finance), plus retries |~33 successful core event POSTs/day | Orchestration HTTP, distinct from provider business writes. Cron invoked 96/day; most slots empty. **LOW** no measured need to alter 96 slot invocations |
| GitHub health |5 core/Worker HTTP reads + GH issue search 1/run |~480 HTTP reads + ≥96 GH API reads | Authenticated provider inventory is local presence, not live credential validation. **LOW** cadence savings; **HIGH observability** stale/auth/backup/deploy contract |
| GitHub/CF technical API |No other established routine business polling |On demand / release | GH installation token memory-cache; technical workflows operate separately. No generic service-UID mutation authority |
| Zoho Sign |1 request-list GET per scheduled observation |8 | Daytime odd-hour schedule; sample 1 GET. **LOW** |
| Zoho Books finance observer |3 invoice-status GETs (overdue/draft/sent) |3 | Daily 07:15 Toronto; read-only. **LOW**; no finance writes |
| R2 backup |~4 successful storage calls (HEAD, PUT, HEAD, GET) |~4 plus reconciliation/retry | Daily encrypted upload/readback; not Zoho/CF REST metric. **LOW**; never skip independent hash verification to save calls |
| OAuth |Shared core Zoho cache/refresh lock; 1 refresh in38 receipt runs |Typically token-lifetime-driven, not 288/day | Phase 13 interprocess refresh proof already complete. **LOW** current savings. Google memory/file cache has different lock/log handling; audit before reuse |
| Google / WorkDrive / Projects / OVH / Windsor / Apollo / AI providers |No configured scheduled business calls found in current paths |0 established scheduled, manual use unknown | Available authenticated adapters are not proof of routine calls. Apollo credit consumptionOFF; Gemini unconfigured; PDF/WorkDrive writers retired. Do not trigger providers merely to benchmark them |

Current nominal scheduled CRM baseline is roughly **792 GET/day** (native 288 + drift 384 + service 120), excluding failed delta, incoming webhook-triggered hydration and interactive requests. Current Mail extrapolation is roughly **1086/day** (792 general observer + 294 receipts), not 318/day: the earlier estimate omitted content retrieval. These are source/sample extrapolations, not a24-hour measured total.

## Operator endpoint profile

Routes below are under `/v1/operator/`; operator Access JWT/issuer/audience/allowlist applies before data reads. A cold/rotated Access JWKS read is separate from the business provider counts. Current views use private/no-store browser headers; any later cache should remain server-side, scope-specific, time-stamped and unable to authorize writes.

| View / path | Provider calls | DB reads / N+ 1 | Likely latency | Cache / batch opportunity |
|---|---|---|---|---|
| Sales queue `phase8/sales-queue` |Live 3 CRM lists, optionally controlled detail+ Mail; Lab 5 CRM lists + Mail per registered scenario |Lab per-Lead intake/timeline/verified-Test reads; real queue mostly provider projection |Serial CRM lists, optional Mail, per-Lab chronology; incomplete inventories fail closed |One complete request inventory; bulk local traces; scoped bounded display cache. Keep 100-row complete-list bound and no Test leakage |
| Lead detail `phase8/sales-view/{lead_id}` |3 CRM GET (Lead, exact-email uniqueness search, fresh full Lead), Mail formula above |Prior outbound/history 2 logical queries; substring/JSON evidence scans |Serial identity/version rehydration and candidate MailN+ 1 |Cache immutable Sent body/header evidence; retain fresh Lead uniqueness/version and inbox check before action. Current detail is controlled-Lead-only, not a general CRM detail page |
| Attribution `phase9/source-trace/{lead_id}` |1 Lead + 3 per opportunity feedback chain |Two intake/feedback queries + provider timeline + Test ownership read |Repeated Deal/Contact/Account GETs and local joins |Request batch unique related IDs; unify receipt timeline by immutable source namespace. Current trace is registered Test scope |
| Receipts `phase9/intake-receipts` |0 |2 list queries plus schema initialization; no providerN+ 1 |Local listing/sort, HTML; small currently |Read-only getter after init, time index, eventual paginated view; no provider refresh just to render |
| Lifecycle `phase10/customer-lifecycle` |5 CRM module lists |No DB required by builder; registry for Lab |Five sequential reads, full projection |Reuse existing display snapshots with age/complete/scope; daily deletion detection retained |
| Recurring `phase10/recurring-services` |Same 5 CRM reads again |No DB by current builder |Rebuilds full lifecycle just to render recurring slice |Share lifecycle display model; Services/Service_Locations canonical, verified revenue only |
| Operations `phase11/operations` |Live 0; Lab 9 module batches at current registry size |Root projection/crosswalk/document files; no SQLite query requirement |Nine serial batches + file/hash checks |Already request-batched. Cache display only; avoid querying unregistered IDs |
| Project detail `phase11/project/{project_id}` |Same 9 for all Lab projects before selecting 1 |Same files; not target-filtered |All-project rebuild |Bounded requested-ID subset for one project; preserve crosswalk/hash/ownership completeness |
| Autonomy `phase12/autonomy` |0 |7 logical SQL queries incl aggregates; repeated schema checks possible |Sort/summary against small journal; JWT on cold auth |Single journal snapshot for navigation/counters; measured indexes; preserve fresh approval/action state |
| Approvals `phase12/approvals` |GET 0; approval POST may fresh-read exact evidence elsewhere |Same 7 queries/full dashboard model |Duplicated autonomy projection |Same display snapshot; never cache approval consume or relax actor/payload/expiry binding |
| Exceptions `phase12/exceptions` |0 |Same 7 queries; state grouping/filter |Repeated same dashboard; stale/deferred mixed with actionable failure |Shared read model, explicit resolution ownership and no-op suppression with audit transitions |
| Health `/health`, `/v1/system/health`, execution-health/alerts |Basic 0; provider inventory normal 0 external provider calls |Execution/alerts aggregate core state; watchdog repeatedly checks local DB |Local health aggregate scans; presence can mask failed sync/auth |Expose distinct liveness/readiness/freshness without heavy full-provider polling; reuse watchdog sample |

DB counts are code-derived logical queries, not profiler timings. No synthetic operator identity, new approval, customer send or all-page provider benchmark was used. Existing Phase 13 exact provider proof remains authoritative for operations 22 → 9; current counter durations provide timer/Mail latency evidence.

## Lightweight operator-home concept — design only

Default landing page should be **“Today”**: one owner-facing attention list, ordered by business urgency and then system blockers. Each item has customer/project context when verified, next human action, reason, due time, confidence/freshness and a link to existing detail/evidence. Keep a compact “Automation paused / Read-only” status and last successful backup/collection indicators. Unknown or Test-only facts cannot be presented as real revenue/work.

Current fragmentation: sales vs controlled lead view; intake receipts vs source trace vs sales attribution; lifecycle vs recurring services; operations vs project; autonomy vs approvals vs exceptions all rebuild related models independently. Phase labels/provider IDs/raw audit rows dominate navigation. There is no common owner/resolve/reconcile contract across exceptions.

Attention established by current local evidence: **1 form needs CRM/email identity review; 10 historical core runs require human reconciliation; 5 stale + 1 deferred action records and 1 scheduled exception exist; failed Lead delta/native-binding drift need technical investigation; backup retention is growing**. These are counts from retained evidence, not six real customer tasks. No live business queue was freshly rendered to certify particular customers or current revenue/due dates; show scope and date and deduplicate known historical/Test exceptions. Never translate old Test succeeded actions into “automatic real work today.”

Retain sales queue/lead, customer lifecycle/recurring, operations/project as business drill-downs; receipts/attribution as source evidence; approvals/exceptions as guarded action review; autonomy as explanation of what was considered/performed. Put ports, provider scopes, scheduler lease IDs, cron, source hashes, raw audit tables, backup object keys and DB modes in an **Operations/technical drill-down**, with a concise business-impact status on Today. Technical signals should name the practical consequence (for example, “New Lead changes may not be observed”) instead of displaying raw provider mechanics.

Use the existing models/state; do not introduce another business DB, automation engine, monitoring platform or financial aggregation. The home must remain useful with automationOFF. No UI was built.

## Observability inventory

| Signal | Current source / duplication | Missing high-value signal / recommended bounded improvement |
|---|---|---|
| API/downstream health |Provider-free core/PDF/Omada/CF health; GH every 15 m |Version/health 200 is not exact runtime SHA or functioning business observer. Bind health summary to deployment/helper receipt and independent loop freshness |
| Provider auth |Core/connector OAuth presence, manual verified GETs, provider errors |Presence (`connected`) is not usable credential. Show last successful safe read/error category/age; no high-rate full provider inventory polling |
| Delta/native health |Sync checkpoint + native verifier + core watchdog |Failed checkpoint can persist while loop thread appears healthy; native binding/expiry mismatch hidden by general health. Include both and their last-good age in owner technical status |
| Timer health |systemctl result/last trigger; job metrics/journals |Unified stale/deadline signal for all 5 timers, not just unit active status |
| Backup success |Private archive/hash/manifest + systemd result |Verified-generation age + hold/retention reason + remaining disk runway; scheduled success must identify a usable generation |
| Off-host success |phase2a `state.json`, independent download hash, audit |Last verified upload age, same-generation plaintext/ciphertext/readability hold and expected<=36h freshness surfaced centrally |
| Disk/DB |Admin capacity; quick-check/backup integrity, journald cap |No established growth/rate/threshold notification for backup cache/app log; five-store health not in standard public liveness |
| Queue/exceptions |Core execution/event health, local journal; CF queues/Workflow state separate |CF queue/DLQ depth/oldest age unknown; HTTP acceptance can mask downstream failure. Existing GitHub issue channel can report qualified stale/no-progress states after design |
| Deployment SHA |Git, root deployment receipt, source-pinned manifest, helper hashes, CI |One redacted effective runtime receipt with drift status. `.venv` currently points to 852e5f7 dependency bundle intentionally reused for docs/P1-compatible release; do not call it deployed codeSHA |
| Provider usage |Per-job/core workflow counters, 30 d/10k cap, budgets |Operator reads, background delta/drift/native checks, R2/auth/JWKS and connector platform reads not comprehensively scoped. Include counters/latency without payloads/secrets/URLs |

Local 30 s watchdog and external 15 m GitHub checks protect different failure domains; merge presentation, not indiscriminately disable one. Health workflow **does** write GitHub incident issues on failure/recovery; this mission did not invoke it, send messages or create issues. No new monitoring platform is needed.

## Recovery maturity remaining — prior drill reused

Phase 13 remains COMPLETE/PASS: isolated restore and exact restored API boot with writersOFF; owner-held AGE identity decrypt/hash/readability proof for generation 20261001T202728Z; independent off-host hash consistency. Do not redo these to mark recon complete.

| Priority | Remaining work | Completion evidence for a later authorized mission |
|---|---|---|
| P1 |Retention/hold policy and disk growth signal |Dry-run candidate/hold index, retained independently verified generations, owner-proof and rollback holds; restore/readability evidence preserved before eventual pruning |
| P1 |Provider reconnect procedure/current observer evidence |Non-secret credential custody/scopes/callback/channel checklist; stop writers by default; exact provider-safe readback and delta/window recovery review. No reconnect/rotation/replay performed here |
| P2 |New-OS/replacement-host rebuild |Clean OS/package/service/secret-mount/bootstrap test with writer timers disabled; current root helper/Caddy/auth pins, no retired development runtime restoration |
| P2 |DNS/TLS cutover rehearsal |Explicit isolated replacement endpoint/certificate/Access/loopback/firewall checks and rollback window; no DNS or TLS change during recon |
| P2 |RTO measurement |Measure from host-loss declaration through restore/provider auth/readiness to validated operator reads; report components and uncertainty rather than promise an unmeasured RTO |
| P3 |Replacement-host readiness / spare capacity |Document provider allocation/network/dependencies and optional prepared host strategy after rebuild/cutover requirements. No new host purchased/provisioned |

## Release/deployment path

Actual current core path: **commit → PR → Validate API Platform on exact PR head → merge → successful exact-main validation → Deploy API Platform workflow_run → SSH forced `deploy <40hexSHA>` → installed `/usr/local/sbin/opticable-api-deploy-root` → root-reviewed unexpired exact authorization + main/CI/backup/root-owned prepared venv → Git/source manifest/env pins → restart core → local health/kill verification → `/var/lib/optibrain/phase13-remediation/deployment.json` → public health/version check**. On candidate failure, installed helper restores previous Git, env, source manifest and dependency pointer, restarts and records rollback. It does not blindly restore an old DB or resume business queues.

Cloudflare control-plane uses a separate deploy workflow after exact-main validation and a separate Worker version/secret-binding contract. Connector release is a different repository/workflow; native provider Forms configuration is owner-admin authority. A core commit is not proof that every Worker changed.

Duplicate paths: repository old `production-root-command.sh`, phase6 loader/gates, phase-specific `/usr/local/lib/optibrain/*reconcile*`, before-image root wrappers and manual stage scripts. Current installed root helper matches `deploy/manual-guarded-release.py` and uses its own independent policy; bootstrap/deploy README still contain old phase-path assumptions. Canonicalize on the existing installed exact-SHA root gate, then repair bootstrap/docs to reproduce it before archiving old paths. Keep separate core/Worker/connector target receipts. Never run an obsolete installer to “synchronize” live authority during recon.

This preparation is retained on an isolated documentation branch. No PR, merge, CI workflow dispatch, service restart or deployment was needed. Ordinary new docs are outside current deployment path filters; no master-runbook digest/policy was repinned.

[Validation receipt](phase14-evidence/validation.json): evidence JSON parsing and local links passed; file-register completeness and protected-record comparison passed; actual credential-value and private-key scans found no matches; production tracked files, main SHA, configuration/helper hashes, write kills and development-worker masks remained unchanged. Only these consistency/read-only checks were run. The prior 811-test release result was retained without rerunning it.

## Coverage and explicit limits

All 24 requested work areas are mapped across these documents and evidence, including the no-full-regression constraint and optional documentation deliverables. UNKNOWNs: preview/adjacent Worker actual use, remote KV/D1/R2 sizes/retention and queue depth, full provider-native admin configuration beyond Phase 13 owner evidence, per-test time distribution, peak host utilization, replacement-host/RTO maturity. Read-only evidence is sufficient to rank changes, not to certify deletion or activation. No secret material was moved.

Required next step is a separately initiated implementation session using [Phase 14 order/quick wins/do-not-touch rules](phase14-implementation-plan.md). **STOP: no full Phase 14 implementation was started.**
