# OptiBrain Phase 4 engineering and recovery record

Date: **2026-09-28 UTC**.

Status: **candidate validated; production gates blocked by existing privilege
boundaries**. Production was not migrated, restarted, deployed or promoted to
main during this engineering campaign.

## Baseline and isolated environment

- Exact immutable baseline: `10e2d1feac9e724ee7d78ba3333a6242fde82898`.
- Production HEAD, local `origin/main` and live remote main matched that commit
  at the start. The Phase 3 completion recovery tag dereferenced to it.
- Preserved recovery tag: `recovery/post-phase3-completion-v1-20260927`.
- Branch: `hardening/phase4-durable-events-v1`.
- Isolated worktree: `/var/tmp/optibrain-phase4-durable-events-v1`.
- Private evidence: `/var/tmp/optibrain-phase4-artifacts` (0700).
- Production checkout: `/opt/opticable-api-platform`; implementation was never
  written into it.
- Candidate API: 1.9.0. Baseline production API: 1.8.0.
- Expected baseline DB: `/var/lib/opticable-workflow-api/output/automation/automation.db`.
  Direct access is protected; the actual production DB was not read or changed.

The final annotated tag `recovery/phase4-candidate-v2-20260928` stores the exact
candidate SHA, merge base, cumulative binary diff SHA-256, changed-file inventory,
test results and drill evidence. Its target is the final candidate; its annotation
is the release manifest, generated after the final commit to avoid a self-referential
commit hash. A local copy is `release-evidence.json` in the private evidence
directory. Resolve with `git rev-parse <tag>^{}` and inspect with `git show <tag>`.
The first candidate tag remains preserved; V2 supersedes it after the exact
time-window review. No development candidate was deployed. Databases from the
superseded candidate are not an upgrade source for this release: the final
production path starts with the immutable Phase 3 V1 database and validates
the complete final V2 definition.

The protected untracked file remains:
`ops/backup/optibrain-cloudflare-auth-diagnostic.sh`.
Its initial SHA-256 is
`7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000`;
mode 0750, owner/group `optibrain:optibrain`. It was only inspected by hash/stat
and remains outside all staged files. The root-owned recovery runbook was not edited.

## Architecture and migration decisions

See [Phase 4 architecture](OPTIBRAIN_PHASE4_ARCHITECTURE.md) for schema, provider
contracts, API routes, concurrency invariants, security and limitations.

V1 → V2 adds an immutable event ledger and separate mutable processing state,
database-enforced dedupe and routing guards, explicit replay lineage, leased
sync checkpoints and bounded daily accounting. It retains the established
Phase 3 execution tables and write-safety semantics.

Migration uses one explicit transaction. It preserves critical legacy rows,
marks historical events routed, seeds route guards, checks foreign keys and
sets `user_version=2` last. Partial/malformed legacy data rolls back the event
migration. Incomplete V2 schemas fail startup rather than being silently repaired.
Legacy sensitive history is not rewritten; a new redacted envelope copy is used.
Sensitive unresolved execution inputs block migration for review.

Webhook intake commits before asynchronous processing. Provider GETs happen
outside write transactions. Checkpoint commits include the entire accepted
page and never skip an undurable event. Replay checks the source execution
family and preserves route guards; it cannot repeat an ambiguous external write.

## Changed-file inventory

All paths below are relative to the repository. The annotated release manifest
also contains the exact mechanically generated inventory.

| Area | Files |
|---|---|
| Repository hygiene | `.gitignore` (Python cache artifacts only). |
| API | `apps/workflow-api/workflow/api.py`. |
| Existing automation | `workflow/automation/models.py`, `store.py`, `engine.py`, `health_monitor.py` under `apps/workflow-api`. |
| Event platform | `workflow/automation/event_schema.py`, `events.py`, `event_api.py`, `event_body_limit.py` under `apps/workflow-api`. |
| Provider intake / sync | `workflow/automation/webhooks.py`, `delta_sync.py`, `google_delta.py`, `sync_runtime.py` under `apps/workflow-api`. |
| Configuration examples | `apps/workflow-api/config/automation/webhooks.example.yaml`, `delta-sync.example.yaml`; all disabled. |
| Phase 4 tests | `apps/workflow-api/tests/test_phase4_events.py`, `test_phase4_webhooks.py`, `test_phase4_delta.py`, `test_phase4_ops.py`. |
| Migration fixtures | `apps/workflow-api/tests/_phase4_fixtures.py`, `fixtures/phase3-v1-schema.sql`. |
| Existing test adaptations | `apps/workflow-api/tests/test_automation_kernel.py`, `test_execution_control.py`; schema expectations/crash injection only. |
| Operations | `ops/phase4/run_tests.py`, `migrate_db.py`, `isolated_drill.py`, `production_campaign.py`. |
| Documentation | `docs/OPTIBRAIN_PHASE4_ARCHITECTURE.md`, `OPTIBRAIN_PHASE4_ENGINEERING_RECORD.md`. |

No provider mutation implementation, sudoers file, production secret, installed
root helper, root runbook or protected diagnostic was changed.

## Validation commands and exact results

Commands ran from the isolated worktree with a distinct disposable output root
for each invocation. Python was
`/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python`.
The counted runner records both unittest methods and subtests; every final
result below has zero failures/errors/skips.

| Scope | Command (after Python executable) | Result |
|---|---|---|
| Baseline, independently counted archive | `/var/tmp/optibrain-phase4-artifacts/immutable-baseline-source/ops/phase4/run_tests.py` | 139 tests + 99 subtests, passed (6.002s). Only the standalone counted runner was copied into the archive; product/test source is the exact baseline. |
| Phase 4 focused | `ops/phase4/run_tests.py --pattern 'test_phase4*.py'` | 107 tests + 100 subtests, passed (10.361s). |
| Ledger / migration / precision | `ops/phase4/run_tests.py --pattern test_phase4_events.py` | 50 tests + 7 subtests, passed (4.865s). |
| Recovery / production safeguards | `ops/phase4/run_tests.py --pattern test_phase4_ops.py` | 10 tests + 4 subtests, passed (3.341s). |
| Webhook focused | `ops/phase4/run_tests.py --pattern test_phase4_webhooks.py` | 21 tests + 61 subtests, passed. |
| Execution controls | `ops/phase4/run_tests.py --pattern test_execution_control.py` | 28 tests + 9 subtests, passed (1.900s). |
| Zoho mutation safety | `ops/phase4/run_tests.py --pattern test_zoho_gateway.py` | 8 tests, passed (0.055s). |
| Inspection boundaries | `ops/phase4/run_tests.py --pattern test_inspection_boundaries.py` | 6 tests + 36 subtests, passed (0.468s). |
| Phase 3 completion / watchdog / redrive | `ops/phase4/run_tests.py --pattern test_phase3_completion.py` | 10 tests, passed (0.446s). |
| Phase 3 API controls | `ops/phase4/run_tests.py --pattern test_phase3_api_controls.py` | 5 tests, passed (0.323s). |
| Conservative retries | `ops/phase4/run_tests.py --pattern test_retry_control.py` | 5 tests, passed (0.001s). |
| External provider controls | `ops/phase4/run_tests.py --pattern test_core_external_providers.py` | 4 tests, passed (0.002s). |
| Entire workflow API | `ops/phase4/run_tests.py` | **246 tests + 199 subtests, passed (16.202s)**. |
| Existing privileged-helper tests | `python3 -m unittest discover -s tests/ops -v` | 37 tests, passed (1.756s). |
| Existing backup / restore / off-host tests | `python3 -m unittest discover -s tests -p 'test_optibrain*.py' -v` | 11 tests, passed (0.091s). |

The supplied Phase 3 report described 153 tests + 99 subtests. Direct discovery
at the exact provided baseline found 139 workflow test methods. All 139 remain
in the full suite; the additional 107 Phase 4 methods account for 246. The
existing regression portion contributes 99 subtests. Counts are reported from
executed commands rather than assumed from the earlier report.

Final logs are `sealed-full-tests.log`, `sealed-focused-tests.log`,
`final2-events-tests.log`, `sealed-ops-tests.log`,
`checked-webhook-tests.log`, `counted-baseline-tests.log`,
`execution-focused-tests.log`, `zoho-focused-tests.log`,
`inspection-focused-tests.log`, `release-ops-tests.log` and
`release-safety-tests.log`, plus the named additional focused logs in the
private evidence directory.

Reproduce safely with an isolated database/output root, never the live output:

```bash
cd /var/tmp/optibrain-phase4-durable-events-v1
PHASE4_PY=/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python
SITE_WORKFLOW_OUTPUT_ROOT=$(mktemp -d /var/tmp/phase4-test-output.XXXXXXXX)
export SITE_WORKFLOW_OUTPUT_ROOT
"$PHASE4_PY" ops/phase4/run_tests.py --pattern 'test_phase4*.py'
"$PHASE4_PY" ops/phase4/run_tests.py
python3 -m unittest discover -s tests/ops -v
python3 -m unittest discover -s tests -p 'test_optibrain*.py' -v
git diff --check
"$PHASE4_PY" -m compileall -q apps/workflow-api/workflow ops/phase4
```

`git diff --check` and compilation passed. New source was inspected for
TODO/FIXME, credentials, arbitrary-payload logging, auth boundaries, migration
DDL, production paths and changed-file scope. There is no configured Python
linter in this checkout. Known secret literals in tests are disposable fixtures;
examples store environment names, never credential values.

## Isolated failure drills

The V1 fixture schema was exported from the exact baseline's initialized
database. A populated fixture was then generated using baseline code and ten
safe internal smoke runs: 20 events, 1 workflow, 10 runs, 20 steps, 10 claims,
0 failures, 60 audit rows. It is not a production backup.

Final drill command:

```bash
SITE_WORKFLOW_OUTPUT_ROOT=/var/tmp/optibrain-phase4-artifacts/sealed-drill-output \
/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python ops/phase4/isolated_drill.py \
  --source-db /var/tmp/optibrain-phase4-artifacts/populated-v1.db \
  --workspace /var/tmp/optibrain-phase4-artifacts/sealed-populated-drill
```

Result: **PASS**. Temporary API port: 45607. Internal smoke run:
`c92fd277198343478dba15b469ba821c`; event:
`1a4dedcce744469f984059c25aef4fbb`.

Verified: exact legacy counts and row hashes preserved; V1 → V2; integrity and
foreign keys; WAL; source unchanged; V1 rollback snapshot; candidate API startup;
authenticated inspection and fail-closed access; core.set/event.emit smoke;
forced API kill/restart; restarted recovery worker; dedupe across restart;
V2 backup/isolated restore; ambiguous external handler dispatched exactly once,
then `human_action_required`; recovery/replay did not repeat it.
The migrated disposable copy disables restored workflows and loads only the
frozen internal smoke definition after legacy-row verification. A restored DB
with unresolved execution is refused before any API launches. The live deployment
preflight separately rejects additional, wildcard or external smoke routes.

Automated drills additionally cover thread and six-process duplicate ingestion,
startup migration races, WAL reader concurrency, routing/replay races, action
markers and lease fencing, transaction interruption, webhook duplicate/invalid/
stale/malformed/oversized/slow deliveries, provider timeout/429/500, corrupt
records, pagination interruption, cursor expiry, notification arrival during
page fetch, stale commit/failure reports, poison quarantine and eligible release.
Provider transport responses are simulated; no real provider write was used.

## Defects found and unsuccessful approaches

1. Initial regressions expected V1/future V2 and patched the old UUID call site.
   Fixtures now explicitly construct legacy state, future-version tests use V3,
   and crash injection targets the new insertion point. Safety assertions were
   preserved. An accidental broad test-count replacement was corrected before
   final validation.
2. An extra recovery return key broke the established contract. It was removed;
   event recovery is integrated without changing that response.
3. Replay could insert an internal run before finding a later unsafe match.
   Routing now preflights all new matches before inserting any run.
4. Low-level Phase 3 runs could lack a route guard. Routing now discovers those
   runs before creating a route, preserving replay fencing.
5. Queue recovery reconstructed only old event fields. It now loads the full
   immutable envelope, preserving provider/account/subject/evidence on restart.
6. Redaction alone could pass a replacement marker into an external action.
   Sensitive payloads now quarantine before routing; sensitive unresolved legacy
   inputs refuse migration. Provider-content conflicts remain strict even through
   the internal ingestion compatibility path.
7. An expired sync worker could record a late failure. Both success and failure
   commits now fence lease expiry and revision. Push generations prevent lost
   notifications while a page is fetched.
8. Polling initially shared the recovery thread. The separate delta worker
   preserves execution recovery liveness during network/OAuth waits and exposes
   its own heartbeat/thread failures.
9. Root umask and root-only parent traversal prevented service-user drills.
   New service staging uses a dedicated hierarchy; existing root permissions
   remain unchanged. SQLite inspection/snapshots run as the service user to
   preserve WAL/SHM ownership.
10. The deployment driver used unsupported restore-verifier flags. It now uses
    the existing positional interface, validates its returned archive hash, and
    has explicit coverage of that contract.
11. The new deadline test patched the shared monotonic clock and exhausted its
    fixture in asyncio. Patching the module's clock reference fixed the test;
    focused, broader Phase 4 and full suites then passed.
12. Google push hints shared the delta resource-change event type. They now use
    explicit notification types, with a test proving a resource-change workflow
    receives only the fetched change record.
13. A final boundary test proved SQLite Julian-day comparison merged timestamps
    100 microseconds apart. Receipt timestamps now have a fixed-width UTC
    constraint; range comparisons preserve microseconds and use the receipt
    index. Legacy copies normalize their instant while original rows remain
    exact. The regression first failed on the old comparison, then passed after
    the product fix and migration/restore reruns.
14. Restored databases can contain pending runs or custom wildcard workflows.
    The drill now rejects unresolved execution before API startup and uses only
    the frozen internal workflow in its disposable copy. Live smoke preflight
    inspects both root and child routing before sending the smoke event. Failed
    CLI result categories are retained in the bounded root-only operation log.

Independent self-review examined unique-index scope, insert races, replay
preflight, cursor commits, expired leases, retained evidence, timezone handling,
provider authentication, payload redaction, bounded queries, migration startup,
cleanup and execution safety. All discovered candidate defects were fixed and
relevant tests rerun. The privileged production driver has not been executed
against production; its plan/parser/credential boundary/CLI contracts are tested.

## Production gate evidence and remaining boundary

The service and all three public APIs answered HTTP 200. Fixed queue inspection
reported 159 completed runs and no unresolved work. Backup/upload timers were
active and enabled. No failed systemd units were present.

The current account can invoke only fixed passwordless admin entrypoints.
`sudo -n true` required a password; the protected service environment/database
and root backup state were unreadable. Fixed `backup` and
`restore-verify-latest` operations returned generic failure. Their internal
root audit was unavailable, so no unverified cause is asserted.

Fixed `verify-latest` verified the existing archive generation
`20260928T000825Z`. Existing uploader logs show that same Phase 3 generation
was encrypted and download-hash verified. This is historical evidence, not a
fresh Phase 4 backup, production migration drill or postdeployment verification.

Blocked gates: fresh production backup/isolated archive restore, actual restored
production DB migration drill, authenticated live execution/event gates, schema
migration/deployment, production smoke, fresh postdeployment backup/restore and
its encrypted off-host verification. Production remains at the exact baseline.

## Prepared deployment and startup procedure

`ops/phase4/production_campaign.py` provides one commit-pinned human-authenticated
entrypoint for the remaining gates. It uses structured fixed argv, literal
environment parsing, the existing backup/restore/uploader services and normal
service operations. It does not install privileges, read a private AGE identity,
change provider scopes, edit the protected file or alter the root runbook.

In order, it verifies baseline/main/clean checkout/health/capacity; creates a
fresh backup; checks archive SHA and the existing verifier; restores it in
isolation; migrates the actual restored DB and runs startup/restart/internal
smoke/ambiguity drills; creates the predeployment tag; rechecks production and
stops the service; rejects work that arrived before stop; freezes a consistent
V1 snapshot; fast-forwards production; runs the tested migration with row/hash
verification; starts the service and uses a bounded readiness loop; checks
authenticated health and safe smoke/dedupe/ledger evidence; creates/verifies/
restores a fresh V2 backup; verifies encrypted off-host download evidence for
that exact generation; checks final health/protected file/failed units; promotes
remote main by normal fast-forward push; creates/pushes final recovery tags.

Root records: `/var/lib/optibrain/phase4/<generation>/result.json` and
`operations.log`. New service-owned staging:
`/var/lib/optibrain-phase4-staging/<generation>/`. Existing root-only recovery
directories keep their permissions. Any failing gate stops promotion and
preserves evidence. The driver does not improvise database repairs or overwrite
the live database from a snapshot.

Recovery tags created only after applicable production verification:

- `recovery/pre-phase4-durable-events-v1-YYYYMMDD` → immutable Phase 3 baseline.
- `recovery/post-phase4-durable-events-v1-YYYYMMDD` → deployed candidate.

These production tags do not exist as claimed completion evidence in this
campaign. The candidate tag is the validated development recovery point.

## Rollback and restore

There is no V2 → V1 down migration. Never start baseline code against a V2 DB:
its unknown-version guard will refuse it. Preserve failed-state evidence before
any recovery. Stop ingress/service, retain the V2 database and consistent SQLite
snapshot (including WAL state through the backup API), then validate the frozen
pre-migration V1 snapshot or verified predeployment archive in isolation.

Rollback requires paired source and database recovery: the exact baseline source
plus a verified V1 DB, correct service ownership/private modes and integrity/row
checks before startup. Do not wipe/reinitialize the DB, delete unresolved work,
reset main forcibly, or copy a live WAL database as a standalone file. The driver
keeps the frozen V1 snapshot and archive identity in its recovery record but does
not perform an automatic destructive rollback. Reconcile events accepted after
the snapshot before selecting a production restore point.

The isolated drill already exercises V1 snapshot rollback and V2 backup/restore.
Actual production recovery requires authenticated root access and the recorded
generation. Existing AGE/R2 protections remain. A fresh encrypted-object hash
verification is feasible on the VPS through the existing uploader; offline
decryption requires the existing human-held identity outside the VPS and is not
claimed by this candidate campaign.

## Remaining provider and operational work

- Activate only explicitly provisioned webhook channels/secrets and delta jobs;
  OAuth/browser consent and subscription renewal remain operator responsibilities.
- Native Gmail OIDC push, CRM delta adapters, multi-account OAuth management and
  provider-specific ordered entity reconciliation are future integrations.
- AI cost values are omitted until reliable pricing/usage metadata is available;
  current counters are operational accounting, not an invoice.
- Core immutable evidence grows with event volume. Add a reviewed archive/retention
  policy before deleting reconciliation evidence; transient accounting is bounded.
- Root production gates must execute successfully before declaring Phase 4 complete.
