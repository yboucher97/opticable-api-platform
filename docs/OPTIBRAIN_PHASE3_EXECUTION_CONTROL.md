# OptiBrain Phase 3 execution and control inventory

Status: IN PROGRESS. The approved application-only release `e5143d3` is in
production and Phase 2B remains known good. Claim/lease work below is source
only and not deployed. Baseline: `recovery/phase2b-production-known-good`.

## Existing implementation and precise gaps

| Area | Present in reviewed source | Phase 3 gap or verification needed |
|---|---|---|
| Kernel and jobs | `AutomationEngine` executes registered actions; SQLite WAL stores events, definitions, runs, steps and audit. Legacy site/PDF jobs use `JobStore` JSON files and daemon threads. | Core execution remains synchronous in the API request; legacy worker threads have no startup replay. Do not replace either path until behavior and side effects are inventoried. |
| Schedulers and triggers | Phase 1/2A systemd timers are persistent. Cloudflare Worker has a 15-minute cron; GitHub lifecycle, mailbox and digest workflows also schedule events. Zoho and control-plane webhooks exist. | GitHub and Cloudflare can request the same business work with different keys; choose one owner and prove handoff before disabling any trigger (Phase 4 dependency). |
| Queue and DLQ | Cloudflare Queue buffers authenticated events, retries delivery up to five times and sends exhausted messages to its DLQ. Cloudflare Workflow delivery has eight exponential retries and a 30-second timeout. | No proven DLQ inspection/redrive procedure or poison-event drill; core SQLite queued/running work has no claim lease or DLQ. |
| Idempotency and duplicate events | Event ID and idempotency key are unique in SQLite; Cloudflare Workflow uses event ID as instance ID; correlation, causation and depth are retained. | Different scheduler keys do not dedupe equivalent business work. Provider action idempotency and ambiguous-response reconciliation are not uniformly proved. |
| Ingest crash window | Previously the event committed before matching runs were separately inserted. | The Phase 3 source change commits the event and all matching queued runs in one `BEGIN IMMEDIATE` transaction, without a schema change. It prevents an accepted event with only some or no runs. A crash after commit can still strand a queued run; no automatic replay is enabled. |
| Retries, backoff and rate limits | Workflow step attempts are capped at five with configurable fixed delay up to 30 seconds. Cloudflare delivery uses exponential backoff. API clients set timeouts. | Core retries catch every exception, lack transient/permanent classification, jitter, `Retry-After` handling and operation-specific idempotency proofs. Retrying a write after an ambiguous response can duplicate an external action. |
| Concurrency and locks | SQLite writer serialization and a process-local `RLock` protect store writes; GitHub scheduler has a concurrency group; admin manual backup has a fixed nonblocking lock. | No core run claim/lease, per-entity lock or cross-scheduler lock. Neither SQLite locking nor event uniqueness proves exactly-once external effects. |
| Stuck jobs and reboot recovery | systemd restarts the example API unit; backup timers use `Persistent=true`; audit/run records survive process exit. The deployed authenticated `GET /v1/automation/execution-health` returns aggregate counts and flags queued work older than 15 minutes or running work older than one hour. | No proved production unit restart policy, startup scan, heartbeat, worker liveness, replay gate or crash-recovery drill. Snapshot flags require diagnosis before any resume. |
| Dependencies and outages | Public API/PDF/Omada and Worker health checks run every 15 minutes via GitHub, with a deduplicated incident issue. Provider inventory checks configured/connected status; adapters isolate APIs. | Endpoint HTTP 200 does not prove scheduler/worker liveness, queue age, provider API availability, token expiry, rate limits or upstream outage duration. No circuit breaker or bounded repair controller is established. |
| Backup and capacity | Admin helper checks both timers, latest archive, full isolated restore and disk capacity; Phase 1/2A tests and recovery records exist. | Scheduled backup freshness, off-host success, restore evidence age, seven-generation headroom and disk trend are not part of one automated alert check. Do not change timers or retention to add this. |
| Alerts and audit | GitHub monitor opens/comments/closes one health issue. Core audit captures workflow and selected provider actions; root helper/updater audit is fixed and protected. | No severity/escalation policy for DLQ, stale runs, backup age or credentials. The monitor checks endpoints, not the execution backlog. Audit does not prove an external provider write was idempotent. |
| Human boundary | Phase 2B fixed helper and updater have exact-path sudo rules and reviewed digest pins. Existing deployment uses validated main commits and restricted SSH. | No generic queue repair, root shell, arbitrary service, provider write, AGE identity, Zoho Books write, destructive restore or broad sudo route may be added. Ambiguous external effects must enter `HUMAN_ACTION_REQUIRED`. |

The approved Phase 2B–12 roadmap in the progress journal already assigns
scheduler ownership to Phase 4, provider normalization to Phase 5, durable
delivery drills to Phase 7, operational telemetry to Phase 8, escalation to
Phase 9 and chaos/reboot certification to Phase 12. Phase 3 should establish
core transaction and execution state first, without recreating Cloudflare
Queues or prematurely changing the existing schedulers.

## Operation classification and concrete gap order

| Class | Proposed operation | Gate and next evidence |
|---|---|---|
| A | Read event/run/step/audit state; inspect queued/running age, public health, timer state, archive checksum, disk and provider status. | The new aggregate execution-health snapshot has fixed 15-minute/one-hour thresholds, requires the existing API key and emits no event payload or secret. It performs no replay or service action. |
| A | Atomically persist an accepted event and its matching queued runs. | Implemented in source without schema change; failure injection, cross-connection duplicate race and existing workflow regression must pass. Deployment remains a separately reviewed action. |
| B | Claim a queued run, execute a proven idempotent action, verify result, audit it, use bounded retry/cooldown and escalate after exhaustion. | Requires durable lease/heartbeat, per-action transient-error policy, outbox or equivalent external idempotency, poison-job/DLQ drills and post-action checks. No automatic replay of existing `running` runs. |
| B | Observe backup freshness, timer/worker/scheduler liveness, queue depth and disk thresholds; open one deduplicated alert. | Fixed thresholds, no secret-bearing logs, tested false-positive handling and escalation; no blind restart. |
| C | Deploy this Phase 3 API change from a reviewed commit; change schema, systemd unit, scheduler ownership, helper/updater, sudoers, target service, provider write scope or ambiguous run recovery. | Human review/approval, current-health check, known-good backup/ref, restricted deployment, targeted/full regression and post-change restore/health evidence. |
| D | Read AGE private identity, perform interactive credential custody, make Zoho Books mutations, expose R2 publicly, grant arbitrary sudo/root shell or automate destructive restore. | Never autonomous under this program. |

`HUMAN_ACTION_REQUIRED`: a production release of the reviewed Phase 3 API
commit was completed as approved application-only commit `e5143d3`. The live
authenticated execution-health and event/duplicate smoke still need an
approved credential-custody path; do not expose the API key in chat or logs.
The root-owned runbook sync is a separate C-class boundary, not part of the
application deploy. The future claim-table schema migration and executor
integration require separate review before production use.

`HUMAN_ACTION_REQUIRED`: duplicate GitHub/Cloudflare lifecycle scheduling
remains intentionally unchanged. OptiBrain is the long-term canonical business
scheduler. Exact resume: select one workflow, compare live schedules and
payloads, verify a shared business idempotency key, stage a reversible handoff,
prove no missed or doubled run, then disable only that superseded trigger under
review. Phase 3 reliability work proceeds independently; no key is invented
solely to unblock this phase.

## Acceptance still outstanding

### Claim/lease source prototype (not deployed)

`automation_run_claims` is a new SQLite table keyed by run ID with worker
identity, unique attempt token, claim time, lease expiry and a durable
`action_started` flag. `claim_run` uses `BEGIN IMMEDIATE`; only a queued run
without a claim can transition to `claimed`. `begin_claimed_action` checks the
attempt token and unexpired lease in the same transaction that writes a
pre-handler step marker and moves the run to `running`. A stale token cannot
start an action. Lease renewal is bounded to 5–300 seconds. Completion is
token-fenced and refuses to clear `human_action_required` or finalize a run
with an unfinished action marker.

On expiry, a claim that is still `claimed` with no action marker can be
atomically requeued. A run with a started action becomes
`human_action_required`, retaining claim/step/audit evidence; no provider write
is replayed. The recovery scan is bounded to 100 claims and idempotent on
repeat. This deliberately treats even a pure-core started action as ambiguous
until the engine and action taxonomy are integrated. The current production
engine still executes synchronously and does not call these primitives.
This table addition is a C-class schema migration; it is not in the deployed
application commit. Before integration, add a worker heartbeat, action-specific
idempotency and transient/permanent failure classification, a durable terminal
reason, and restart/outage drills. Do not deploy the prototype as self-healing.

Phase 3 is not complete. Before completion, prove a durable claim/lease and
recovery state machine, safe handling of ambiguous provider results, finite
retry/backoff and rate-limit behavior, dead-letter visibility and controlled
redrive, stale-job and liveness alerts, reboot recovery, dependency-outage and
poison-event drills, and human escalation. A passing unit suite or a healthy
endpoint alone cannot establish those properties.
