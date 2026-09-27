# OptiBrain Phase 3 executor release candidate — review only

Status: C-class application/schema candidate. Do not deploy without a separate
human approval, an online SQLite recovery copy, verified Phase 1 archive and a
reviewed validated-main application-only commit. Production remains at
`e5143d35ca1664a8b4faeda40f0f15a80fe7673d` during preparation. Neither
GitHub nor Cloudflare schedule changes belong to this release.

## Why the schema is needed

`automation_runs` already stores state and timestamps, but has no worker,
attempt token or lease to arbitrate two processes. `automation_run_claims`
holds exactly those fields, keyed by run ID. `automation_run_steps` already
records each attempt and its durable `started` marker, so the redundant
`action_started` claim flag has been removed. Two additive step columns store
the deterministic logical action SHA-256 and an optional provider operation
ID. The run's existing `context_json` stores the immutable queued workflow
definition until execution, avoiding a third snapshot table.

The old `automation_run_steps.error` is free text and has no classification or
recovery decision. `automation_run_failures` provides append-only attempt and
terminal history: run ID, step ID, attempt token, fixed category, restricted
reason code, timestamp, allowlisted non-secret diagnostic JSON, terminal
state, redrive-permitted flag and human-required flag. It deliberately does
not reference a claim row, because a definitely-never-started claim can be
deleted and replaced while history must survive. No event or run row is
deleted by the migration.

Forward migration is `PRAGMA user_version` 0 to 1 under `BEGIN IMMEDIATE`.
It adds the two nullable step columns, the two tables and fixed indexes,
checks required columns and commits the version last. A repeated startup is
safe. A future/unknown version fails closed. The earlier undeployed prototype
used one terminal failure row per run; if such a local database is found, the
old table is renamed to `automation_run_failures_legacy`, its rows copied to
the new history table, and the legacy table retained. That conversion is also
inside the migration transaction. A fixture forces a mid-migration conflict
and proves that both column additions and version change roll back.

## Executor and idempotency contract

Event and matching queued runs commit together. Each new queued run stores
its workflow-definition snapshot. The current executor claims the run in a
SQLite `BEGIN IMMEDIATE` transaction before any step. A second worker cannot
claim or execute it. An action marker and logical key commit before its
handler call. Completion, failure evidence and terminal transitions require
the same unexpired attempt token; a stale worker cannot record success. The
logical key hashes run ID, workflow ID/version, step ID/action, target ID when
provided (otherwise a canonical input fingerprint), and canonical resolved
inputs. It stays constant across worker attempts. Only the digest is stored
and exposed to a handler as `context.execution.action_identity`.

`event.emit` uses this key as the child event's default idempotency key. A
provider handler may return a validated `provider_operation_id` for durable
step evidence. Provider-native idempotency/reconciliation is not assumed for
adapters that do not explicitly support it. They remain single-attempt and
ambiguous responses enter `human_action_required`; no generic write replay
or redrive is enabled. Only `core.noop`, `core.set`, and the reviewed read-only
`windsor.read`/`windsor.list_actions` paths are registered retry-safe. An
adapter cannot acquire retry permission merely through workflow YAML.

The bounded retry matrix is:

| Observed failure | Proven retry-safe action | Unproven external write |
|---|---|---|
| 429, 408, temporary 5xx, connect/read timeout | Retry at most configured 1–5 attempts, capped exponential delay and valid `Retry-After`; exhaust to `dead_letter`. | `human_action_required`, no retry. |
| 401/403 | `human_action_required`, no token refresh. | Same. |
| Other 4xx / validation | `failed`, no retry. | Same. |
| Unknown transport/result | `dead_letter`, no retry. | `human_action_required`, no retry. |
| Invalid or overlong `Retry-After` | `human_action_required`, no early retry. | Same. |

During an in-process retry wait, the worker renews its lease after bounded
sleep intervals. If renewal fails, it stops; recovery handles the stale
claim. A process death before the first action marker can be requeued. A
process death after any marker, even after a recorded failure, is isolated as
`human_action_required` until action-specific reconciliation is proved.
This conservative rule may require human attention for a safe read; it does
not risk replaying a provider write. A bounded background recovery scan runs
while the API is up. Three consecutive scan exceptions stop that scanner and
log human action required; no restart loop is introduced. Old queued rows
without an immutable definition snapshot are visible as stale work but are
not replayed automatically.

Read-only execution health adds completed count, recent failure-record count
and oldest claim age to the existing queue/stale-lease aggregate. Authenticated
`failed-work` and per-run `failures` inspection expose category, reason,
attempt and fixed diagnostic fields without raw exception text or payloads.
There is no mutation/redrive endpoint.

## Production release and recovery plan

1. Human C-class preflight: confirm the exact production SHA `e5143d3`, three
   health endpoints, both backup timers active/enabled, helper self-test,
   `verify-latest`, queue state, disk capacity, service logs, installed
   helper/updater hashes and sudoers validity. Record the known untracked
   Cloudflare diagnostic script without touching it. Verify the latest
   archive/sidecar and an isolated restore result. Do not alter seven-generation
   retention or either timer.
2. Resolve the database path under root custody from the service environment
   without printing credentials. Record `PRAGMA user_version`, schema/table
   shape, integrity check and current counts. Require version 0 (or a
   specifically reviewed compatible state). Create a timestamped SQLite
   online-backup copy in a root-owned recovery directory, including checksum,
   owner/mode and a tested open/integrity check. Preserve it outside the
   seven-generation Phase 1 rotation. Record the current Git recovery ref
   `recovery/post-phase3-app-deploy-e5143d3` and create a deployment-specific
   pre-change ref.
3. Review the app-only diff against this source checkpoint and require CI
   validation on main. Use only the existing restricted validated-main deploy
   identity. The app-only commit must contain no root runbook, helper, updater,
   sudoers, unit, backup-policy or schedule change. The service restart runs
   the additive migration. No direct shell reset or ad hoc root SQL is part
   of the deployment path.
4. After deployment, verify production SHA and version 1; schema columns,
   integrity and preserved event/run counts; all three health endpoints;
   both timers; helper self-test; latest archive; read-only execution-health;
   failed-work/failure-history authorization; queue/claim age; a safe internal
   duplicate-event and transaction smoke using the existing credential-custody
   path; bounded logs; and no unexpected provider writes or schedule changes.
   Exercise a safe queued/restart fixture before any live crash drill. Record
   a post-change recovery ref and the results in progress/runbook.

If service startup or migration fails, the existing deployment wrapper can
reset code to `e5143d3` and restart after its health check. This is a **code
rollback**, not a destructive schema downgrade: that version ignores the
additive tables/columns and `user_version=1`. Preserve the online database
copy. New `claimed`, `dead_letter` or `human_action_required` rows are not
automatically replayed by old code; inspect them and reconcile external
effects before any manual state change. If database restoration is actually
required, freeze intake under separate C approval, preserve the failed DB and
WAL as evidence, restore the exact verified online copy through the reviewed
recovery procedure, then verify SQLite integrity, backup/restore capability,
timers and health. Do not drop the new tables or rewrite historical backups as
an automatic rollback step.

## Separate root-owned runbook ownership correction

The current helper publishes into the tracked checkout path
`docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md`, while restricted deployment
uses `git reset --hard` on that entire checkout. A post-sync root-owned
tracked file becomes dirty or is replaced by the reset. This is the exact
recurring ownership conflict. The durable design is:

- Keep the Git document as **source** only. Its digest and a reviewed raw pin
  remain versioned review artifacts.
- Publish the reviewed bytes to a fixed out-of-checkout path such as
  `/usr/local/share/optibrain/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md`,
  root:root 0644 under a root:root 0755 directory. Keep the separate
  root-owned authorization pin and versioned root recovery copies.
- Make a separately reviewed C-class helper release that changes only the
  fixed destination/path validation/backup location as needed. The updater's
  compiled approved-helper SHA and corresponding raw authorization artifacts
  must be regenerated. Preserve exact no-follow, owner/mode, same-filesystem
  atomic publish, post-write hash and rollback checks. Keep the fixed sudoers
  command unchanged; no general root route or argument is added.
- At a human-root migration window, back up the installed tracked runbook and
  pin, create and seed the fixed published path with the known-good bytes,
  install the reviewed helper/updater pins through the existing restricted
  transition, then run the constrained `sync-master-runbook` against the
  reviewed source and new root pin. Verify both published and Git source
  hashes, helper self-test, deployment cleanliness and rollback. A future
  restricted Git reset can then update source without changing the published
  root-owned document. Do not perform this migration as part of the Phase 3
  application/schema release.

Until that C-class correction is separately approved and installed, the
published runbook remains the known-good installed SHA-256
`cdab559d264fb7a17c469fd10953827a98a24ac4a926939db1055522a6dfc085`.
The updated Git source and pin must not be interpreted as installed root state.

## Candidate validation evidence

The source checkpoint passed workflow pytest (108 tests, 21 subtests), the
CI-style unittest discovery (94 tests), ops/admin adversarial (37 tests),
restore-drill (2 tests), the Phase 1 backup fixture, Phase 2A uploader
(9 tests), Phase 2A bucket/R2 fixtures, Python compilation, sudoers parse,
artifact manifest verification and `git diff --check`. Focused fixtures
exercise two-worker races, crash before/after the action marker, expired and
stale leases, duplicate event/action identities, restart while queued/claimed,
429/503/timeout retries, `Retry-After`, permanent and auth failures, ambiguous
writes, poison attempt exhaustion, provider operation ID persistence and
transactional migration rollback. These are fixture results, not a production
schema or reboot drill. Run the complete suite again on the final app-only
candidate before C-class approval.
