# OptiBrain Phase 3 execution and control inventory

Status: IN PROGRESS, source-only review; production remains on the known-good
Phase 2B release. Baseline: `recovery/phase2b-production-known-good`.

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
| Stuck jobs and reboot recovery | systemd restarts the example API unit; backup timers use `Persistent=true`; audit/run records survive process exit. A new authenticated `GET /v1/automation/execution-health` returns aggregate counts and flags queued work older than 15 minutes or running work older than one hour. | No proved production unit restart policy, startup scan, heartbeat, worker liveness, replay gate or crash-recovery drill. Snapshot flags require diagnosis before any resume. |
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
commit needs the existing approval/deployment path. Exact resume: review the
final source diff and tests, validate current production health and both backup
timers, preserve a pre-deploy recovery point, deploy only the approved main
commit through the restricted workflow, run an end-to-end idempotency/crash
drill, recheck health/latest backup/restore evidence, and record a post-deploy
recovery point. No root helper/updater or sudoers replacement is part of this
source change.

`HUMAN_ACTION_REQUIRED`: duplicate GitHub/Cloudflare lifecycle scheduling
requires an owner decision before any trigger is disabled. Exact resume:
compare live schedules and equivalent event payloads, choose the canonical
owner, define a shared business idempotency key, stage a reversible handoff,
verify no missed or doubled run, then disable only the superseded trigger under
review. Phase 3 transaction work can proceed independently.

## Acceptance still outstanding

Phase 3 is not complete. Before completion, prove a durable claim/lease and
recovery state machine, safe handling of ambiguous provider results, finite
retry/backoff and rate-limit behavior, dead-letter visibility and controlled
redrive, stale-job and liveness alerts, reboot recovery, dependency-outage and
poison-event drills, and human escalation. A passing unit suite or a healthy
endpoint alone cannot establish those properties.
