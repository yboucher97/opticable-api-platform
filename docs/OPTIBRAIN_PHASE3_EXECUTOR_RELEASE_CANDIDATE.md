# OptiBrain Phase 3 executor release candidate — review only

**V2 status (2026-09-27):** The V1 application candidate below failed independent
C-class review and must not be deployed. The V2 application candidate and its
review evidence are recorded in the V2 section at the end of this document.
Only V2 may be submitted for a new independent C-class review. Production
remains `e5143d35ca1664a8b4faeda40f0f15a80fe7673d`.

Status: C-class application/schema candidate. Do not deploy without a separate
human approval, an online SQLite recovery copy, verified Phase 1 archive and a
reviewed validated-main application-only commit. Production remains at
`e5143d35ca1664a8b4faeda40f0f15a80fe7673d` during preparation. Neither
GitHub nor Cloudflare schedule changes belong to this release.

The isolated application candidate is
`5cb0f666ceea4298602e8f1821bc316d683d806a`, based directly on that
production commit. Its 11 changed paths are all under `apps/workflow-api/`.
The application diff has SHA-256
`ca198bbb4a2a14db464e8aacd1a4b1e6b13b20e84076f05583260f38f58c7343`
both in this source review checkout and in the isolated application checkout.
The source/documentation checkpoint before this release-index update is
`845b9889952ff965e8e4bd94f3e51e6a58278453`.

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

Both the source checkpoint and isolated application candidate passed workflow
pytest (108 tests, 21 subtests), CI-style unittest discovery (94 tests),
ops/admin adversarial (37 tests),
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

## Release Candidate V2 — source review package, not deployed

The independent result for V1 (`5cb0f666ceea4298602e8f1821bc316d683d806a`;
application diff SHA-256
`ca198bbb4a2a14db464e8aacd1a4b1e6b13b20e84076f05583260f38f58c7343`)
was `OPTIBRAIN_PHASE3_C_REVIEW_FAIL`. It found two correctness defects:
unknown `user_version` was rejected only after baseline schema creation, and
`on_error: continue` could turn exhausted safe retry or permanent failure into
`partial`. Direct tests were also missing for three crash boundaries. A prior
Phase 2A uploader test invocation used the workflow virtual environment,
which lacks `botocore`.

The clean application-only V2 commit is
`f20f48c46065d0715bda39986a5109459601d5b6`, directly based on known-good
production `e5143d35ca1664a8b4faeda40f0f15a80fe7673d`. Its application
diff SHA-256 is
`ab26a60b8b7f6a175dba0370494aa2934d9ab1d34e24004ab98791e05709aa76`.
It changes the same 11 application paths as V1, under `apps/workflow-api/` only.
This source package carries the same application bytes plus this documentation
and the progress journal; the documentation is not part of the application
deployment diff. There is **no schema change relative to V1**: the additive
SQLite migration remains `user_version` 0 to 1, with the same claims and
append-only failures tables and the same two nullable step columns.

### V2 behavior and precedence

`AutomationStore._connect` reads `PRAGMA user_version` before WAL configuration
or any schema statement. A version outside `{0,1}` closes the connection and
raises. Version 0 runs the existing baseline and transactional migration.
Version 1 checks its additive schema and indexes; a complete version 1 returns
without migration DDL, while a missing additive object follows the existing
repeat-safe repair path. No downgrade of a future version is attempted.
Tests compare version, every `sqlite_master` table/index/trigger entry, data,
and the database-file SHA-256 before and after rejection of empty and populated
version-2 fixtures. All comparisons are equal. Version-0 initialization and
version-1 reopening also pass.

Execution-control classification overrides `on_error: continue`:
exhausted retry-safe work is `dead_letter`; permanent/validation failure is
`failed`; authentication or ambiguous external-write failure is
`human_action_required`. These states cannot be changed later by the ordinary
completion path. The DSL still accepts `on_error: continue`, but the present
engine has no separately classified non-terminal failure eligible for it.
Successful multistep execution with the setting remains valid. A future
continuable failure class needs its own safety proof and review; V2 does not
invent one.

For the final successful step, the step result, run `completed` state,
finished timestamp, context, and audit records commit in one SQLite
transaction. A crash immediately after that commit therefore leaves an
authoritative completed run. Intermediate completed steps followed by a crash
remain protected by the existing marker-based human-review rule; V2 does not
replay them or make a provider write twice.

### Crash and restart matrix

| Boundary | Expected and fixture-observed state |
|---|---|
| Before claim commit | Claim and run transition roll back; queued run remains. |
| After claim, before marker | Valid lease stays claimed; after expiry, requeues. |
| After marker, before handler | After expiry, `human_action_required`; no handler replay. |
| During handler | After expiry, `human_action_required`; no blind replay. |
| Provider response before local result commit | Durable `started` marker remains; after expiry, `human_action_required` with `lease_expired_after_action` evidence; no replay. |
| Immediately after final successful result commit | `completed` remains committed; no requeue, duplicate action, or escalation. |
| Restart during valid lease | Still claimed; another worker cannot claim; recovery does nothing. |
| Restart after lease expiry | Marker-free claim requeues; marked claim escalates. |
| Expired never-started claim | Requeues only after expiry. |
| Expired started claim | `human_action_required`; marker and digest remain. |
| Stale worker late result | Token/expiry fence rejects commit. |
| Competing workers | One claimant and one handler invocation. |
| Interrupted migration | Added columns/version roll back together. |
| Duplicate source event | One logical event and queued run. |
| Duplicate logical action | Stable action digest and completed-step guard prevent local duplicate. |

These are fixture observations, not a live reboot or provider-outage drill.
An ambiguous provider write remains single-attempt without provider-native
idempotency or deterministic reconciliation. No generic redrive was added.

### V2 validation and rollback

Workflow pytest passed **118 tests and 25 subtests**; CI-style unittest
passed **104/104**. Admin adversarial tests passed **37/37**; restore tests
**2/2**. The Phase 1 backup fixture, Phase 2A bucket and R2 fixtures, Python
compilation, artifact manifest, sudoers parse, and diff whitespace check
passed. The Phase 2A uploader suite passed **9/9** using its documented
`/usr/bin/python3` environment with Ubuntu-packaged `boto3`/`botocore`
1.34.46; no production package or dependency manifest was changed. The first
parallel workflow pytest/unittest run contended on their shared fixture
database, so the complete suites were rerun sequentially and both passed.

The rollback target remains
`e5143d35ca1664a8b4faeda40f0f15a80fe7673d`. Any later authorized
deployment still requires a verified current backup, an online SQLite recovery
copy, exact candidate and count checks, authenticated inspection, and separate
human C-class approval. Code rollback may leave the additive version-1 schema;
claimed, dead-letter, and ambiguous runs require inspection. Never redrive an
uncertain external write automatically.

The review lesson is to test the *absence of mutation* on a rejected schema,
to keep safety terminal states above workflow DSL convenience, and to test
the transaction boundary between handler response and durable completion.
An exception alone is insufficient evidence of fail-closed startup.

Remaining Phase 3 work is separately reviewed: provider-native write
idempotency/reconciliation, controlled redrive, worker and scheduler liveness,
queue growth/escalation, live reboot and provider-outage drills, authenticated
production execution-control validation, and the root-owned published-runbook
architecture. Phase 4 event dedupe remains separate from action idempotency.
The V2 version guard, stable local action digest, and transaction boundaries
do not materially constrain later webhook-first event ingestion, provider
event/account identity, delta sync, bounded polling, safe replay, or usage/cost
accounting. V2 makes no Phase 4 implementation or provider API calls.

## Release Candidate V3 — source review package, not deployed

The second independent C-class review returned
`OPTIBRAIN_PHASE3_C_REVIEW_V2_FAIL`. Four reproduced blockers were: mixed-width
SQLite TEXT lease comparisons requeued a valid lease and renewed an expired
one; HTTP 200 HTML could complete an unconfirmed Windsor write; missing
server-side inspection key allowed anonymous inspection; and failure history
materialized all 1,000 step results despite `limit=1`. V3 fixes only these
four boundaries and their equivalent paths. V2 remains undeployed.

The immutable application candidate is
`d61510d0d2ba3b6db182daea864705baeb9fcc61`, directly parented by
production `e5143d35ca1664a8b4faeda40f0f15a80fe7673d`. Its 12 changed
paths are all under `apps/workflow-api/`; application diff SHA-256 is
`0512288dd2afae81127965bb13d3f97296c2c5ddb35d1deef147497519760f9e`.
Relative to failed V2, only `test_execution_control.py`,
`test_inspection_boundaries.py`, `test_windsor_provider.py`, `api.py`,
`engine.py`, `store.py`, and `windsor_api.py` changed. This source package
also updates this release record and the progress journal; those files are
not in the deployable application diff.

### Lease clock and final V1 schema

The unreleased `automation_run_claims.claimed_at` and `lease_expires_at`
columns are now SQLite `INTEGER` UTC epoch microseconds. The conversion uses
integer day/second/microsecond arithmetic; no float is used for durable
ordering. Claim insertion, action start, renewal, result and terminal fences,
expiry recovery, and execution-health expired-lease counts all use the same
integer clock. ISO-8601 remains human-readable evidence for run/step/failure
timestamps. **At equality, `now >= lease_expires_at` means expired.** A
version-1 database with incompatible TEXT claim columns is rejected, not
silently used. Because no Phase 3 schema was deployed, the production path
remains one additive V0 → final V1 migration; no artificial V1 → V2 step exists.

Exact fixtures cover expiry `05.500000` versus now `05.000000` (not expired),
expiry `05.000000` versus now `05.100000` (expired), exact equality, one
microsecond before/after, renewal, completion fencing, recovery, and
execution-health counts. The V2 reproductions changed from early requeue 1 to
0 and late renewal `True` to `False`. Existing crash, stale-token, competing
worker, duplicate-event, and migration tests remain green. Version-2 future
schema fixtures retain their pre-initialization schema/data/file hashes.

### Windsor write confirmation

The [Windsor Connectors API documentation](https://windsor.ai/api-documentation/)
shows a successful action returning a JSON object with a nonempty `result`
string. V3 requires a JSON media type, parsed object, that documented result
shape, and no obvious error/partial-success envelope before recording a
Windsor write as successful. Other result shapes require later provider-specific
proof. HTTP status alone is insufficient. Unconfirmable responses raise a
fixed-message `WindsorWriteUnconfirmedError`; the engine records restricted
`ambiguous_external` evidence and `human_action_required`. It stores neither
HTML nor raw provider response text, does not retry, and does not redrive.
Safe read registration is unchanged. Fixtures cover valid success, HTML,
malformed JSON, empty body, wrong shape/media type, error/failed/partial
envelopes, read timeout, and connection uncertainty. Every ambiguous write
uses exactly one provider call even with five workflow attempts configured.

### Inspection authentication and bounds

All `/v1/automation/` GET inspection routes share a fail-closed inspection
guard. If the configured server key is absent, empty, or whitespace-only, the
route returns 503 before any store lookup; no key value is disclosed. With a
configured key, missing or wrong client credentials return 401 and a correct
key retains existing endpoint behavior. Production deployment preflight must
verify only the *presence* of the server-side inspection key through the
approved credential-custody path; never print, rotate, or export it for this
check. The current production service returns 401 anonymously.

Failure-history existence now uses `SELECT 1 FROM automation_runs WHERE
run_id=? LIMIT 1`; it never calls `get_run` or parses workflow snapshots and
step results. The history query retains its `ORDER BY id DESC LIMIT ?` and
100-row server cap. `failed_work` first selects at most 100 terminal runs in
a CTE before joining step/failure evidence. A fixture with 1,001 large step
results and `limit=1` verifies that `get_run` is not invoked, one failure row
is returned, and excessive/invalid limits are rejected.

### V3 crash/restart matrix and validation

| Boundary | V3 fixture result |
|---|---|
| 1. Before claim commit | Queued run and claim transition roll back. |
| 2. Claimed before marker | Valid claim remains held; marker-free expiry requeues. |
| 3. Marker before handler | Expiry escalates for human reconciliation. |
| 4. During handler | Expiry escalates; no blind replay. |
| 5. Response before local result | Started marker remains; expiry escalates. |
| 6. After final result commit | Completed run remains authoritative. |
| 7. Restart during valid lease | No claim theft, including exact-second edge. |
| 8. Restart after expiry | Marker-free requeue; marked claim escalates. |
| 9. Expired never-started claim | Requeues at or after exact expiry only. |
| 10. Expired started claim | Human action required at or after exact expiry only. |
| 11. Stale worker late commit | Wrong/expired attempt rejected; equality is expired. |
| 12. Competing workers | One claimant and one handler invocation. |
| 13. Interrupted migration | Additions and version roll back on existing V0 fixture. |
| 14. Duplicate source event | One event/run for the deployed event ID/key semantics. |
| 15. Duplicate logical action | Local digest/completed-step guard blocks local duplicate. |

Workflow pytest: **128 passed, 75 subtests**; CI-style unittest: **114/114**.
Admin adversarial: **37/37**; restore: **2/2**; Phase 2A uploader: **9/9**
with `/usr/bin/python3` and Ubuntu boto3/botocore 1.34.46. Phase 1 backup,
Phase 2A bucket/R2 fixtures, compilation, shell syntax, source sudoers parse,
artifact-byte checks, and diff whitespace checks passed. These are isolated
fixtures, not a live reboot or provider outage drill.

Terminal runs retain their claim rows. Recovery filters terminal statuses, so
retained rows neither requeue nor replay work; one row per terminal run can
accumulate indefinitely. Review retention/cleanup separately in Phase 3,
without broadening V3. Code rollback to `e5143d3` read the final V1 additive
schema and preserved V0 fixture counts/statuses. It does not automatically
redrive claimed or ambiguous work; inspect such work before any manual action.
The local action digest is execution evidence, not provider-native write
idempotency. Event dedupe is a separate mechanism.

Remaining Phase 3 work: provider-native write reconciliation/idempotency,
controlled redrive, worker and scheduler heartbeat/liveness, queue growth and
stale-work alerting, escalation, live reboot and controlled outage drills,
authenticated production validation, terminal-claim retention, and separate
root-runbook publication design. V3 adds no Phase 4 implementation and does
not materially block native event IDs, durable webhook-first ingestion,
deterministic dedupe, delta sync, bounded polling, correlation/causation IDs,
event replay/signatures/ordering, or usage accounting.

**Not deployed. A new independent C-class review and separate human deployment
authorization are required.**
