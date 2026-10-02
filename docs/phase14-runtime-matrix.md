> SUPERSEDED — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_RUNTIME_CONTRACT.md).

# Phase 14 runtime matrix

Current contract; deployed SHA comes from the schema-1 root release receipt. [Reconnaissance runtime](phase14-runtime-inventory.md) remains the immutable before-state. No business writer, canary or development worker was enabled.

| Component | Identity | State / responsibility | Decision |
|---|---|---|---|
| Workflow API | opticable-workflow-api | Resident FastAPI and bounded observers | KEEP, canonical |
| PDF service | opticable-password-pdf | Resident local/supporting health; provider writers denied | KEEP, contained |
| Omada service | opticable-omada-site | Resident health; consequential public routes denied | KEEP, contained |
| Caddy | caddy | TLS, routing and legacy containment | KEEP, canonical |
| Receipt collector | API UID | Five-minute receipt/connector observation | KEEP |
| Service observer | API UID | Hourly five-module projection and occurrences | KEEP |
| TEST runner | root | Reconcile before kill; bounded Test scheduling, currently writes OFF | ROOT TEMPORARILY ACCEPTABLE |
| Backup | root | Online SQLite/private config snapshot | ROOT REQUIRED |
| R2 uploader | root, empty capability set | Private plaintext/public AGE recipient/recovery secret boundary | ROOT TEMPORARILY ACCEPTABLE |
| Six development service/timer units | retired | MASKED / INACTIVE; authorization absent | KEEP MASKED |
| Manual Codex | owner + full sudo | Explicit engineering sessions | PRESERVED |

Three resident app services + Caddy, five oneshot jobs, five timers before/after. No scheduler consolidation removed a distinct recovery or observation responsibility. TEST runner now has only DAC_OVERRIDE, DAC_READ_SEARCH, FOWNER, CHOWN and SYS_PTRACE capabilities; kernel/control-group/device/SUID protections; mutation-control and runner env mounted read-only. These capabilities support private evidence, API process/credential reads and owner-preserving cache writes. It cannot safely become unprivileged without replacing root-only ownership/claims with a new broker. Uploader already has empty capabilities; giving a weaker UID plaintext/claim credentials would widen the secret boundary, so separation is deferred. Backup identity unchanged.

| Timer / scheduler | Cadence | Purpose / current status |
|---|---|---|
| optibrain-backup | Daily 02:30 UTC + jitter | Root snapshot; preserve holds |
| optibrain-phase2a-upload | Daily 03:00 UTC + jitter | Immutable encrypted upload + readback |
| opticable-phase9-intake-receipts | Every five minutes | Read-only receipt collection |
| opticable-phase10-service-events | Hourly | Five conditional CRM reads; daily deletion audit |
| opticable-phase12-test-runner | Every 30 min + jitter | Reconciliation with writes OFF; readiness sampler after run |
| Core delta | Every 300 seconds | Saved-cursor CRM read; current auth latch repaired |
| Native watch | Every 300 seconds | Independent binding/expiry read verification |
| Desired drift | Hourly | Read-only metadata/desired-state audit |
| GitHub health monitor | Every 15 minutes | One active scheduled workflow; three business workflows remain disabled |
| Cloudflare control plane | One 15-minute cron, two queues, one durable Workflow | Authenticated observation delivery; no business authority |

Root sampler writes redacted `/run/optibrain-readiness/status.json`; max age 90 min. It checks timer results/staleness, local/off-host backup age (36 h), disk 80/90%, staging 15/25 GiB, DB 128/512 MiB and logs 128/512 MiB. Core journal queues are checked per readiness request. Exact read-only conflict acknowledgements require root proof, matching deployed source and matching retained workflow/step/error; original failures remain visible in drill-down. Provider-call budgets warn only on repeated recent excess; no repeated identical incident comments. Sample absence/corruption is UNKNOWN, never a write grant. Remote queue depth remains UNKNOWN until measured separately.

## Feature-gate ownership

The root owner controls safety policy, source-pinned registration and runtime env. Workflow enabled settings select orchestration only. Behavioral gates remain 23 and root workflow definitions 16 (8 enabled/8 disabled); none was removed merely to reduce the number. The exact gate/default/scope table below is preserved from the reviewed before-state and remains applicable. PDF/WorkDrive config gates remain false as defense in depth despite retired mutation bodies. Global/root denial overrides every family or enabled workflow setting.

| Gate | Default / current | Purpose and scope | Disposition |
|---|---|---|---|
| `OPTICABLE_AUTOMATION_ENABLED` | true / effective true (unset in API env) | Start event/recovery/health/delta threads; not business mutation authority; used | KEEP FUNCTIONAL |
| `OPTICABLE_CONNECT_STANDBY_ENABLED` | false / false | Manual connector standby selection; no automatic mutation failover; used | KEEP SAFETY |
| `OPTIBRAIN_ALLOW_APOLLO_CREDIT_CONSUMPTION` | false / false | Prevent paid enrichment consumption; used | KEEP SAFETY |
| `OPTIBRAIN_CRM_DRIFT_ENABLED` | unset → off /`true` | Hourly drift and 300 s native-watch observation; no provider mutation grant; used | KEEP FUNCTIONAL |
| `OPTIBRAIN_BUSINESS_AUTO_WRITES` | off / API unset; runner `0` | Conjunctive central Test automation gate; real remains forbidden; used | KEEP SAFETY |
| `OPTIBRAIN_AUTO_TEST_TASK` | off / API unset; runner `1` | Select exact central TestTask family **only when global/root gates also allow**; used | KEEP SAFETY |
| `OPTIBRAIN_AUTO_TEST_PROJECT` | off / runner `0` | Test onboarding class; universal transport forbids it; used | KEEP SAFETY |
| `OPTIBRAIN_AUTO_TEST_INTERNAL` | off / runner `0` | Test internal action family; currently off; used | KEEP SAFETY |
| `OPTIBRAIN_CRM_LEAD_WRITES` | unset → deny / unset | Exact legacy policy-version gate; transport forbidden; still read | KEEP SAFETY until legacy writer retirement |
| `OPTIBRAIN_CRM_CANARY` | unset → deny / unset | Exact legacy single-canary mode; not TEST_ONLY qualification; still read | KEEP SAFETY until executor retirement |
| `OPTIBRAIN_LEAD_CREATE_CANARY` | unset → deny / unset | Exact create-canary mode; no current create transport; still read | KEEP SAFETY until executor retirement |
| `OPTIBRAIN_OUTBOUND_SENDS` | unset → deny / unset | Version-bound outbound mode; real/Mail writes universally forbidden; still read | KEEP SAFETY |
| `OPTIBRAIN_SALES_DRAFTS` | unset → deny / unset | Legacy provider draft mode; local display drafts do not need this; still read | REMOVE CANDIDATE only after retiring provider-draft executor; preserve deny behavior |
| `OPTIBRAIN_PHASE8_TEST_LAB` | unset → deny / unset in API/runner env files | Legacy root exact Test mode; manual tools may set within process; still read | KEEP SAFETY, TEST_ONLY |
| `OPTIBRAIN_PHASE8_TEST_TASK` | unset → deny / unset in API/runner env files | Exact lower TestTask grant, internally established only by reviewed code; still read | KEEP SAFETY, TEST_ONLY |
| `OPTIBRAIN_PHASE9_FORM_ENRICHMENT` | unset → deny / collector `off`; API unset | Legacy form enrichment writer; central transport forbids it; used | KEEP SAFETY until writer retirement |
| `OPTIBRAIN_SKIP_LIVE_CONFIG` | off / not configured for live backup | Isolated backup test override; could omit protected config if misused; used by tests | KEEP SAFETY; TEST_ONLY use |
| `OPTIBRAIN_SKIP_LIVE_STATE` | off / not configured for live backup | Isolated backup test override; could omit recovery state; used by tests | KEEP SAFETY; TEST_ONLY use |
| root `test_writes_enabled` | missing/corrupt → deny / false | Universal root transport kill; used | KEEP SAFETY, TEST_ONLY |
| root `real_canary_allowed` (`REAL_CANARY_ALLOWED`) | missing/corrupt → deny / false | No real business transport; used; not an env flag | KEEP SAFETY |
| registration `business_actions_enabled` | absent/false → deny / false | Source-pinned optional executor registration; used | KEEP SAFETY |
| PDF brand `crm.enabled` | parser true if omitted / false | Retired CRM password writer; source stub still denies regardless; used | REMOVE CANDIDATE as provider feature after pipeline contract retirement; keep false meanwhile |
| PDF brand `workdrive.enabled` | required config / false | Retired document upload/move feature; source guards remain; used | REMOVE CANDIDATE after pipeline/recovery review |


Fresh Cloudflare GET inventory confirms `*/15 * * * *`, two queues and one durable Workflow. GitHub confirms the single scheduled health monitor and all three business workflows `disabled_manually`. They serve different host/edge delivery and public-health responsibilities; no schedule was removed or reactivated.

Owner routing was revalidated at final closure: legacy Access app `admin.opticable.ca/*` had no public DNS; the canonical Today URL is now `https://optibrain.opticable.ca/v1/operator/today`. The same application/audience/policies/IdPs protect the exact operator prefix. Only the existing optibrain A-record proxy state changed; its origin IP and all other DNS records/settings remain untouched. Edge login redirects and origin 401 denials are independently checked; public health and legacy 403 containment remain healthy. The historical domain is retained.
