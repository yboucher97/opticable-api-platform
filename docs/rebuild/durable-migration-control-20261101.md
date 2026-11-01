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
