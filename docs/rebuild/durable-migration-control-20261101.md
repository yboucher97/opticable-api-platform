# Existing VPS migration: durable operator control

This supplement depends on PR #147 `439027baaafcdfb9a87fdfb424b84f6593f31dea` and
PR #153 `ec9a8e85095b57faf21212000652912e08093da4`. It does not replace their capture,
restore, final-sync, intake-hold or provider action contracts. Do not merge/deploy
through the main branch workflow.

The installed NEW profile is **observer-only**: `execution_enabled=false`, no
consequential stage adapters, no maintenance approvals and no source write SSH
capability. It is not an armed, complete production-cutover executor. Provider
Historical Forms retention was explicitly waived by the owner; bounded live submission closure still requires its scoped approval. An exact frozen package, reviewed
stage adapters and persistent source reboot fence/conditional rollback must be
bound and verified before timed maintenance. Approval alone cannot arm this draft.

The existing `/var/lib/optibrain-rebuild/actions.db` holds control stages, attempts,
alert intents and canonical hash-chain evidence. No second business event database
is introduced. Readbacks bind run, hosts, inputs, outputs, timestamp and evidence;
exit status alone never completes a stage. Interrupted provider actions reconcile
read-only, including after approval expiry. Only pinned idempotent local steps may
retry, at most three times. Original effect intent starts the hold clock, including
a delayed readback after restart.

The source SSH key is restricted by source IP, forced command and `restrict`.
Only `status` and a bounded, validated `publish-report` to two fixed owner report files are accepted. Both host keys are pinned; arbitrary SSH commands are
denied. No OLD business service/configuration can be changed by this capability.

The root operator Mail transport is separate from business/customer transport
execution. The owner's November 1 request explicitly authorizes technical alerts
only to `yboucher@opticable.ca`, from that same verified Zoho account. No CC/BCC,
attachments, variable recipients or generic Mail mutations. Each incident has one
durable intent and an exact canonical owner-instruction approval. A lost send ACK
never causes another POST. Delivery requires an exact received-message readback in
the owner Inbox or the existing owner OptiBrain folder, not merely a Sent copy.

Systemd restarts the isolated runner after failure. The independent watchdog checks
source and target health, target's 45 OFF flags, authoritative DNS, queue settings,
backlog age/retention, backup services and encrypted archive readback evidence. It
sends deduplicated owner alerts and seals changed control evidence/code with AGE
using the existing create-only R2 uploader and a separate full GET hash readback.
No full business backups are created on OLD. Same-host services cannot detect or
notify while the entire NEW host is down; this limitation must remain explicit.
At 45/60 minutes the watchdog records/escalates the hold deadline; it never blindly
resumes delivery or overwrites NEW data. Stage-specific rollback must be approved
and verified before any future execution profile can be armed.

Focused tests (on NEW, using installed PR147 shared primitives):

```
PYTHONPATH=/opt/optibrain-rebuild-toolchain/migration-20261027/ops/rebuild \
/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -B \
/home/ubuntu/optibrain-autonomous-20261101/tests/test_durable_migration.py
```

An actual observer SIGKILL/systemd restart preserved the run/checkpoint and made
zero maintenance attempts. Do not interpret this as a test of an in-progress
production freeze, deployment, DNS mutation or full-host reboot.

## Executor completion (review required; no live maintenance authorization)

Version 2 binds thirteen concrete adapters in `migration_adapters.py`, using the
existing PR147 final-sync engine, October 28 RAM capture/identity scripts, PR153
NEW-only release and native CRM reconciler. `migration_authority.py` records eight
independent decisions from an actual private owner-message artifact. It cannot
manufacture consent. Arming/health fields are outside the immutable action
binding; changing code, identities, scopes, stage commands or deployment artifacts
invalidates approvals.

The OLD forced key accepts exactly `execute`, then requires a short-lived Ed25519
signed JSON request, exact source/target/package, and an unexpired owner scope for
freeze/capture/rollback. It grants neither a shell nor access to internal CLI
commands. Fixed report publication remains on the separate monitoring key.
Persistent systemd conditions on all seventeen writer/service/timer units reference
one root-only disk marker. Installation leaves that marker absent. Approval creates
it before stopping writers; reboot and disconnect retain it. Unit conditions are
verified through D-Bus, because older systemd prints `Conditions=[unprintable]`.

Before NEW intake release, a monotonic no-return marker is persisted on OLD.
Before that boundary, conditional rollback may restore the captured OLD units only
with original DNS AND Worker version/settings, queue/Forms held, actual private OLD
health, and explicit compensation permissions. After release intent, changed or
uncertain DNS/Worker, or any NEW data: keep OLD fenced, preserve NEW and reconcile.
Neither timer expiry nor SSH failure automatically reverses DNS or starts OLD.
An independent OLD timer checks the fence and uses the existing canonical owner-only
Zoho notifier when NEW disappears or the maintenance deadline is reached.

Transfers resume only after OLD verifies the existing destination prefix hash.
Final recovery is AGE-encrypted and uploaded create-only with full encrypted GET
hash verification, followed by complete archive/SQLite/audit catalog and owner/OAuth
identity validation. No historical backup is deleted. The existing 48GiB capacity
gate is rechecked before final sync; refusal is preferable to deleting evidence.
The root-owned Worker runtime is frozen and catalogued, and deployment stays a
single audited transport with GET-only ambiguous-outcome reconciliation.

Native Forms settings have no authenticated settings-admin transport in this
session. The Forms stage therefore verifies an actual owner UI action and the exact
maintenance pages; it never fabricates retention or a provider API. Historical
Forms retention is waived. Owner must close both exact public forms with the
reviewed bilingual message before source freeze, then reopen them only after NEW
hold intake and the explicitly safe receipt observer are verified. These UI actions
remain separately approved, evidenced human steps. They are not automated by this
executor. No TEST_ONLY submission or uncertain historical replay is authorized.

Fixture validation covers all thirteen stages, interruption/lost ACK after every
stage, checkpoint reopen, independent decisions/expiry, capacity and notification
failures, real Ed25519 verification/forgery rejection, forced-command denial, partial
transfer prefix validation and nine SQLite stores. Real maintenance/provider-write
branches remain unexecuted until exact owner approvals. WINDOW_READY requires the
pinned fixture evidence, effective OLD fence and current read-only window checks;
it is not evidence of a completed cutover or a real OLD reboot test.
