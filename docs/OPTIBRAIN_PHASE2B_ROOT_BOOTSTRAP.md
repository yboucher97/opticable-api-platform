# Phase 2B consolidated root bootstrap proposal

Status: corrected recovery package for a partially installed bootstrap. The
first updater attempt failed closed with `invalid_digest_artifact`; production
remained healthy, both backup timers remained active/enabled, sudoers remained
valid, and the previous helper remained installed. This package corrects the
admin helper pin encoding and gives the current-state repair procedure below.

The purpose of this package is a single human-root bootstrap for routine,
allowlisted OptiBrain administration and the reviewed helper update path. Verify
all installation artifact hashes with `ops/admin/ROOT_BOOTSTRAP_SHA256SUMS`
and compare the checkout to the separately supplied reviewed checkpoint before
running any root command.

## Privilege architecture

The proposed sudoers drop-in grants NOPASSWD only to two root-owned absolute
executables: the no-argument digest-pinned updater and the admin helper. The
admin helper can receive arguments because its own parser accepts only exact
operations and fixed service names, bounded log counts, or no arguments. It has
no command execution, arbitrary path, arbitrary systemd, file editing, shell,
interpreter, or environment-setting operation. `NOSETENV` blocks sudo environment
injection; both Python executables use `/usr/bin/python3 -I`; the helper then
clears and rebuilds its environment before dispatch. Every subprocess uses an
absolute executable, fixed argument vector, `shell=False`, and a second internal
command allowlist.

The updater authorizes only one helper source digest, compiled into the reviewed
updater, and also requires that digest to match both the root-owned helper pin
and the staged checksum. It validates the helper's policy markers and syntax,
keeps exact previous bytes, atomically installs the captured authorized bytes,
verifies the result and runs bounded self-test. A post-install failure restores
and verifies the previous bytes. Changing the root pin or staged checksum alone
cannot authorize a new helper. A future helper release requires a human to
review its source and install a separately reviewed updater build whose literal
release digest matches that helper. No routine helper operation can edit either
pin or the updater. A generated SHA by itself is never authorization.

This is a strong release gate, not a proof that arbitrary new Python is safe.
Every future updater/helper change requires human source review and a new
checkpoint. The automatic AST/policy checks catch malformed or plainly
out-of-policy code; the exact digest allowlist is the hard acceptance gate.

## Admin operations and later-phase privilege inventory

| Class | Allowed or planned operation | Scope / condition |
|---|---|---|
| A — safe autonomous | `health`, service/timer status, scheduler status, capacity, queue counts, bounded redacted logs, `verify-latest`, `restore-verify-latest`, helper self-test | Read-only fixed endpoints, services, database, archive, log units and restore workspace. No arbitrary paths or log query filters. |
| A — safe autonomous | `backup` | Fixed root-owned script/config; only when the reviewed seven-generation retention policy is intact and at least two retention slots remain. A fixed root-owned nonblocking lock serializes admin-triggered runs; it refuses when the check is uncertain, another admin run is active, or retention headroom is low. |
| B — strict validation | `upload` | Starts only the installed Phase 2A upload unit. Existing create-only remote generation behavior and authenticated read-back remain; no bucket-policy or public-access operation exists. |
| B — strict validation | `service-restart`, `service-reload` | Only the three named OptiBrain production services; fixed timeout. No arbitrary unit, start/stop/enable/disable/mask or unit editing. |
| B — strict validation | `sync-master-runbook` | Exact canonical source and destination, separate root digest pin, fixed source/destination ownership/modes, versioned old copy, same-filesystem atomic publish and post-write hash check. Future source digest still requires human root authorization. |
| B — strict validation | deployment and rollback | Existing dedicated GitHub/restricted-SSH deployment path only: validates an exact commit is an ancestor of `origin/main`, tests before switch, health-gates, and restores prior code on failure. This sudo helper does not gain deployment commands or Git execution. |
| B — strict validation | Phase 3–9 queue recovery, scheduler reconciliation, provider sync, event replay, bounded self-healing and alerts | Implement later as separately named operations only after idempotency, schema, fixed targets, retry limits, authorization scopes and failure drills pass. No general SQL, provider CLI or scheduler command is granted now. |
| C — human approval | New helper/updater release, digest pin change, sudoers/unit changes, new service target, database/schema migration, canonical-data conflict resolution, connector scope/write changes, non-routine production restart, deployment of an unapproved commit, retention-policy change, destructive restore/rollback | Requires reviewed intent, pre-change recovery, tests, validation, post-change recovery and an explicit approval record. |
| D — human custody / never autonomous | AGE private identity, interactive OAuth/MFA/CAPTCHA/security-key flow, one-time human-only provider credential, credential rotation without verified replacement, Zoho Books mutation, public R2 access, broad sudo/shell, arbitrary root file changes | Offline private-key custody remains on the human recovery machine. Some actions are permanently forbidden by policy, not merely deferred. |

No permission is added for reviewed unit installation/update, ownership repair,
firewall/SSH/users, arbitrary root-file access, database mutation, provider
write API, or direct deployment. Those require a future narrowly scoped design
and separate review. Existing distro authenticated sudo-group membership is
outside this NOPASSWD transition and is not modified here; the proposal adds no
passwordless general sudo.

## Fixed command and data policy

The helper's command wrapper rejects anything except exact combinations for
`systemctl` status/restart/reload and the fixed Phase 2A upload unit, fixed `df`
paths, checksum verification of a validated archive name, the fixed backup
script, a fixed restore-drill interpreter/script, and fixed `journalctl` units
with 1–200 lines. The parser rejects extra arguments, shell metacharacters,
traversal, service substitution and environment-like arguments before execution.
The helper never accepts file names from its caller. Backup verification,
restore verification, queue inspection and runbook synchronization derive all
paths internally and reject unsafe file types/ownership. Logs are capped at
200 entries and 64 KiB and redact common credential assignments, bearer tokens
and private-key blocks; redaction is defense in depth, not a guarantee that
arbitrary application log text contains no personal or confidential information.

Runbook synchronization uses only
`/var/tmp/optibrain-admin-update/incoming/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md`
and `/opt/opticable-api-platform/docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md`.
The staged source and sidecar must be optibrain-owned mode 0440; the separate
root pin must be root-owned mode 0440. It validates UTF-8, NUL exclusion, fixed
heading, source/destination and staging ownership/modes, records and verifies a
unique previous copy, then publishes captured bytes from root-only storage by
same-filesystem atomic replacement and verifies the final digest. It cannot
edit a caller-selected file. The operation is not run during bootstrap.

The updater's helper self-test runs without a shell, with a minimal environment,
eight-second timeout and resource limits. Its directory and input checks reject
symlinks, unsafe ownership/modes, hard links, path swaps and file changes during
read. The captured bytes—not a second mutable pathname lookup—are installed.

## Root installation artifacts and hashes

`ops/admin/ROOT_BOOTSTRAP_SHA256SUMS` is a standard `sha256sum` manifest: each
line is `<digest><two spaces><repository-relative filename>` and is consumed
only by `sha256sum -c`. Authorization pins consumed by Python parsers contain
only 64 lowercase hexadecimal characters and one newline. In particular,
`optibrain-admin.sha256` is used as both staged candidate digest and root
authorization pin; `master-runbook.sha256` is the staged runbook digest and root
pin. Neither may use `sha256sum` filename syntax. `optibrain-admin-update.sha256`
is a raw source digest sidecar with no runtime parser or authorization consumer;
the bootstrap manifest verifies its file bytes and reviewers can compare it to
the updater source. Backup archive `.sha256` sidecars remain standard `sha256sum` records,
because their consumer is `sha256sum -c`.

The root-installed/staged source artifacts are:

| Source | Root destination / purpose |
|---|---|
| `ops/admin/optibrain-admin-update.py` | `/usr/local/sbin/optibrain-admin-update` |
| `ops/admin/optibrain-admin.py` | Staged candidate, then installed transactionally at `/usr/local/sbin/optibrain-admin` by the updater |
| `ops/admin/optibrain-admin.sha256` | Raw candidate checksum and root pin `/etc/optibrain/admin-helper.sha256` |
| `ops/admin/optibrain-admin-update.sudoers` | `/etc/sudoers.d/90-optibrain-admin` |
| `ops/backup/optibrain-restore-drill.py` | `/usr/local/lib/optibrain-backup/optibrain-restore-drill.py` |
| `docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md` | Fixed staged runbook source |
| `ops/admin/master-runbook.sha256` | Raw staged checksum and root authorization pin `/etc/optibrain/master-runbook.sha256` |

Digest consumer inventory: `optibrain-admin-update.py::_parse_digest` consumes
`candidate.sha256` and `/etc/optibrain/admin-helper.sha256` as strict raw
lowercase pins. `optibrain-admin.py::sync_master_runbook` consumes the staged
`master-runbook.sha256` and `/etc/optibrain/master-runbook.sha256` with the same
strict raw syntax. `sha256sum -c` consumes `ROOT_BOOTSTRAP_SHA256SUMS` and backup
archive sidecars in standard manifest syntax. `restore-verify-latest` parses
exactly one standard sha256sum record with an absolute filename equal byte for
byte to the selected archive path; basename-only records and alternate paths
are rejected. The updater's `.sha256` review sidecar is raw and has no runtime
consumer. This separation is tested so the formats cannot silently converge
again.

No AGE identity, provider credential, or other secret is an installation
artifact. The restore script is installed root-only because the helper invokes
it with a fixed archive path and digest; the script is not separately granted in
sudoers.

## Repair procedure for the partially installed production state

This applies when the updater, sudoers drop-in and Phase 1/2A timers are
already installed, the old helper remains active, and the audit contains
`invalid_digest_artifact`. Do not repeat first-install directory creation,
sudoers replacement, updater installation, restore-verifier installation, or
sudoers backup steps. The helper authorization pin must be corrected, and the
runbook authorization pin must be refreshed because this recovery note is also
being added to the canonical master runbook. Both are raw digest files. No root
executable, sudoers file, timer, provider state, backup, or previous sudoers
backup needs replacement. In particular, the installed updater already uses
the strict raw parser and has the expected digest below.

First run this read-only preflight. Stop if any result differs from the known
healthy state or expected hash. The old helper hash is from its recorded
reviewed installation (`1083218`); the updater hash is the current package
source hash. The `grep` must show the failed attempt's fixed audit code.

```bash
cd /opt/opticable-api-platform
curl --fail --silent --show-error https://optibrain.opticable.ca/v1/system/health
curl --fail --silent --show-error https://optibrain.opticable.ca/pdf/health
curl --fail --silent --show-error https://optibrain.opticable.ca/omada/api/health
sudo systemctl is-active optibrain-backup.timer optibrain-phase2a-upload.timer
sudo systemctl is-enabled optibrain-backup.timer optibrain-phase2a-upload.timer
sudo sha256sum /usr/local/sbin/optibrain-admin-update /usr/local/sbin/optibrain-admin
test "$(sudo sha256sum /usr/local/sbin/optibrain-admin-update | cut -d' ' -f1)" = 3594770351bd2a96cda822a4242587cb265894906255cfc61f28a7fff1a54086
test "$(sudo sha256sum /usr/local/sbin/optibrain-admin | cut -d' ' -f1)" = a35734a52d9c64adfc0bb9b242f117aad099c85d5cbc0aac248e422ebe25367c
test "$(sudo cat /etc/optibrain/master-runbook.sha256)" = 5faf0494de038468267932dd6515eb685b49688799fb2259e827829f51fc0c2d
sudo visudo -c
sudo grep -F 'invalid_digest_artifact' /var/lib/optibrain/admin-update/update-audit.jsonl
sha256sum -c ops/admin/ROOT_BOOTSTRAP_SHA256SUMS
```

The expected health responses are HTTP 200 (JSON bodies vary); both timers
must report `active` and `enabled`; sudoers validation must succeed; and the
audit query must find the failure. Then stage only the reviewed candidate and
runbook with their digest files and replace the two root authorization pins.
The helper's runbook synchronization creates and verifies its own versioned
previous copy before publishing the recovery note. The immutable
pre-consolidated sudoers backup made during the original install remains in
place. Do not change it.

```bash
sudo install -o optibrain -g optibrain -m 0440 ops/admin/optibrain-admin.py /var/tmp/optibrain-admin-update/incoming/candidate.py
sudo install -o optibrain -g optibrain -m 0440 ops/admin/optibrain-admin.sha256 /var/tmp/optibrain-admin-update/incoming/candidate.sha256
sudo install -o optibrain -g optibrain -m 0440 docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md /var/tmp/optibrain-admin-update/incoming/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md
sudo install -o optibrain -g optibrain -m 0440 ops/admin/master-runbook.sha256 /var/tmp/optibrain-admin-update/incoming/master-runbook.sha256
sudo install -o root -g root -m 0440 ops/admin/optibrain-admin.sha256 /etc/optibrain/admin-helper.sha256
sudo install -o root -g root -m 0440 ops/admin/master-runbook.sha256 /etc/optibrain/master-runbook.sha256
test "$(sudo sha256sum /var/tmp/optibrain-admin-update/incoming/candidate.py | cut -d' ' -f1)" = "$(cat ops/admin/optibrain-admin.sha256)"
test "$(sudo sha256sum /var/tmp/optibrain-admin-update/incoming/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md | cut -d' ' -f1)" = "$(cat ops/admin/master-runbook.sha256)"
test "$(sudo stat -c '%s' /etc/optibrain/admin-helper.sha256)" = 65
test "$(sudo cat /etc/optibrain/admin-helper.sha256)" = 30aad73bb2b56a110e38348cce5babefb1816b7f1ffd7cd37449a51a0f1527c4
test "$(sudo cat /etc/optibrain/master-runbook.sha256)" = 23b5dbdcc886a19cba35c57c5a9be51ce64090b2ed0e370b39f7289753c9439e
sudo sha256sum /var/tmp/optibrain-admin-update/incoming/candidate.py /var/tmp/optibrain-admin-update/incoming/candidate.sha256 /etc/optibrain/admin-helper.sha256
sudo -k
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin-update
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin sync-master-runbook
```

Expected updater output is one line of the form:
`OptiBrain admin helper updated and self-test passed; sha256=30aad73bb2b56a110e38348cce5babefb1816b7f1ffd7cd37449a51a0f1527c4; preserved_previous=/var/lib/optibrain/admin-update/previous/optibrain-admin-<UTC timestamp>-<old digest prefix>.py`.
The previous helper must remain in that exact printed backup path; its expected
name ends with `-a35734a52d9c64ad.py`.

After success, validate the new helper and installed bytes:

```bash
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin --self-test
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin health
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin scheduler
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin verify-latest
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin restore-verify-latest
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin queue-status
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin capacity
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin logs opticable-workflow-api.service 50
sudo sha256sum /usr/local/sbin/optibrain-admin-update /usr/local/sbin/optibrain-admin
sudo visudo -c
sudo systemctl is-active optibrain-backup.timer optibrain-phase2a-upload.timer
sudo systemctl is-enabled optibrain-backup.timer optibrain-phase2a-upload.timer
curl --fail --silent --show-error https://optibrain.opticable.ca/v1/system/health
curl --fail --silent --show-error https://optibrain.opticable.ca/pdf/health
curl --fail --silent --show-error https://optibrain.opticable.ca/omada/api/health
```

Repeat the negative privilege checks in the post-install section below. The
updater itself should still have its expected digest; the helper should now
match `30aad73bb2b56a110e38348cce5babefb1816b7f1ffd7cd37449a51a0f1527c4`.
The runbook command should print
`master runbook synchronized: sha256=23b5dbdcc886a19cba35c57c5a9be51ce64090b2ed0e370b39f7289753c9439e`.
Verify the installed helper is `30aad73bb2b56a110e38348cce5babefb1816b7f1ffd7cd37449a51a0f1527c4`, the updater remains `3594770351bd2a96cda822a4242587cb265894906255cfc61f28a7fff1a54086`, and the runbook pin equals the runbook hash. Record the exact new
`/var/lib/optibrain/admin-update/previous/master-runbook-*-5faf0494de038468.md`
recovery path created by sync. Keep the updater's printed previous-helper path
and verify its hash is the preflight value
`a35734a52d9c64adfc0bb9b242f117aad099c85d5cbc0aac248e422ebe25367c`.
No backup, upload, service restart, or timer action is part of this repair.

If post-update validation fails, preserve both new recovery records and restore
the old helper from the exact path printed by the updater. Publish it atomically
and check its known hash:

```bash
sudo install -o root -g root -m 0750 /var/lib/optibrain/admin-update/previous/<exact-printed-helper-backup>.py /usr/local/sbin/.optibrain-admin.rollback
sudo mv -fT /usr/local/sbin/.optibrain-admin.rollback /usr/local/sbin/optibrain-admin
test "$(sudo sha256sum /usr/local/sbin/optibrain-admin | cut -d' ' -f1)" = a35734a52d9c64adfc0bb9b242f117aad099c85d5cbc0aac248e422ebe25367c
```

If the runbook sync succeeded but must be rolled back, verify the exact backup
file recorded after sync against the old runbook hash before atomically
publishing it back:

```bash
RUNBOOK_BACKUP='/var/lib/optibrain/admin-update/previous/<exact-recorded-master-runbook-backup>.md'
test "$(sudo sha256sum "$RUNBOOK_BACKUP" | cut -d' ' -f1)" = 5faf0494de038468267932dd6515eb685b49688799fb2259e827829f51fc0c2d
sudo install -o root -g root -m 0644 "$RUNBOOK_BACKUP" /opt/opticable-api-platform/docs/.OPTICABLE_AUTOMATION_MASTER_RUNBOOK.rollback
sudo mv -fT /opt/opticable-api-platform/docs/.OPTICABLE_AUTOMATION_MASTER_RUNBOOK.rollback /opt/opticable-api-platform/docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md
printf '%s\n' 5faf0494de038468267932dd6515eb685b49688799fb2259e827829f51fc0c2d > /tmp/optibrain-master-runbook.rollback.sha256
sudo install -o root -g root -m 0440 /tmp/optibrain-master-runbook.rollback.sha256 /etc/optibrain/master-runbook.sha256
sudo install -o optibrain -g optibrain -m 0440 /tmp/optibrain-master-runbook.rollback.sha256 /var/tmp/optibrain-admin-update/incoming/master-runbook.sha256
rm /tmp/optibrain-master-runbook.rollback.sha256
```

Leave the helper authorization pin and all backup generations in place for
review. The runbook pin is restored to the digest matching the prior document.
The sudoers drop-in and its immutable
`90-optibrain-admin.pre-consolidated` backup are not touched by this repair.

## C-class restore-sidecar compatibility release

The later `restore-verify-latest` failure was caused by a parser mismatch. Phase
1 writes standard sha256sum records using the absolute archive path; the helper
accepted only the basename. The corrected helper accepts one exact record bound
to the archive selected by `_latest_archive()`: 64 lowercase hex characters,
two spaces, that exact absolute path, and one final newline. It rejects
basename-only records, alternate paths, extra records, malformed spacing and
uppercase digests. The isolated verifier independently checks the archive
contents against the digest. Existing archives and sidecars stay immutable.
The reviewed helper SHA-256 is
`b6313a79357afed164d3d7bfd363dd14403b3c8853927c721370e1e94df17244`; its
reviewed updater SHA-256 is
`8f1f2fdecb8603f94f746532ecfa2b90a26f9ee4e57b3d6e70e74509e166dfe6`.

The approved helper release changes its digest, so the installed updater must
also be replaced with the separately reviewed updater containing the new
`APPROVED_HELPER_SHA256`. This is a human-root C-class transition. No production
change was made while preparing this package. The exact reviewed helper and
updater hashes are recorded in the checkpoint report and bootstrap manifest.

The preflight below is for the post-digest-fix partial state: helper
`30aad73bb2b56a110e38348cce5babefb1816b7f1ffd7cd37449a51a0f1527c4`, updater
`3594770351bd2a96cda822a4242587cb265894906255cfc61f28a7fff1a54086`, and
restore verifier
`58f9e2305329326c5dfdbb88af4d1535f33fda3f9fb6d03163212b7929fc7db6`. Confirm
the current helper health, scheduler, archive verification, timer state,
sudoers and archive checksum. `restore-verify-latest` is expected to fail on
this old helper until this release is installed.

```bash
cd /opt/opticable-api-platform
git rev-parse HEAD
sha256sum -c ops/admin/ROOT_BOOTSTRAP_SHA256SUMS
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin --self-test
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin health
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin scheduler
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin verify-latest
if sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin restore-verify-latest; then echo 'Unexpected: prior restore parser passed'; else echo 'Expected: prior restore parser rejects absolute sidecar filename'; fi
sudo systemctl is-active optibrain-backup.timer optibrain-phase2a-upload.timer
sudo systemctl is-enabled optibrain-backup.timer optibrain-phase2a-upload.timer
sudo visudo -c
sudo sha256sum /usr/local/sbin/optibrain-admin /usr/local/sbin/optibrain-admin-update /usr/local/lib/optibrain-backup/optibrain-restore-drill.py
sudo sha256sum -c /var/backups/optibrain/optibrain-backup-20260927T130636Z.tar.gz.sha256
test "$(sudo cat /etc/optibrain/admin-helper.sha256)" = 30aad73bb2b56a110e38348cce5babefb1816b7f1ffd7cd37449a51a0f1527c4
test "$(sudo cat /etc/optibrain/master-runbook.sha256)" = 23b5dbdcc886a19cba35c57c5a9be51ce64090b2ed0e370b39f7289753c9439e
```

If the production latest archive is no longer
`optibrain-backup-20260927T130636Z.tar.gz`, run the installed `verify-latest`
operation as above and use its currently selected archive for the direct
`sha256sum -c` check. Do not alter any archive or sidecar. Stop if preflight
health, timers, hashes, checksum or sudoers validity differ from the expected
state.

Before installing, recheck the checkpoint SHA and manifest. Record the exact
old updater backup path; do not overwrite an existing recovery generation.
Stage the reviewed helper and runbook files, save the old updater under its
digest-derived recovery name, then install the new updater and authorization
pins. The existing sudoers rule already names the same updater path and needs
no change.

```bash
git rev-parse HEAD
sha256sum -c ops/admin/ROOT_BOOTSTRAP_SHA256SUMS
test "$(sha256sum ops/admin/optibrain-admin.py | cut -d' ' -f1)" = "$(cat ops/admin/optibrain-admin.sha256)"
test "$(sha256sum ops/admin/optibrain-admin-update.py | cut -d' ' -f1)" = "$(cat ops/admin/optibrain-admin-update.sha256)"
test "$(sha256sum docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md | cut -d' ' -f1)" = "$(cat ops/admin/master-runbook.sha256)"
visudo -cf ops/admin/optibrain-admin-update.sudoers
sudo test ! -e /var/lib/optibrain/admin-update/previous/optibrain-admin-update-3594770351bd2a96.py
sudo test ! -L /var/lib/optibrain/admin-update/previous/optibrain-admin-update-3594770351bd2a96.py
sudo install -o optibrain -g optibrain -m 0440 ops/admin/optibrain-admin.py /var/tmp/optibrain-admin-update/incoming/candidate.py
sudo install -o optibrain -g optibrain -m 0440 ops/admin/optibrain-admin.sha256 /var/tmp/optibrain-admin-update/incoming/candidate.sha256
sudo install -o optibrain -g optibrain -m 0440 docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md /var/tmp/optibrain-admin-update/incoming/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md
sudo install -o optibrain -g optibrain -m 0440 ops/admin/master-runbook.sha256 /var/tmp/optibrain-admin-update/incoming/master-runbook.sha256
sudo install -o root -g root -m 0750 /usr/local/sbin/optibrain-admin-update /var/lib/optibrain/admin-update/previous/optibrain-admin-update-3594770351bd2a96.py
sudo install -o root -g root -m 0750 ops/admin/optibrain-admin-update.py /usr/local/sbin/optibrain-admin-update
sudo install -o root -g root -m 0440 ops/admin/optibrain-admin.sha256 /etc/optibrain/admin-helper.sha256
sudo install -o root -g root -m 0440 ops/admin/master-runbook.sha256 /etc/optibrain/master-runbook.sha256
test "$(sudo sha256sum /usr/local/sbin/optibrain-admin-update | cut -d' ' -f1)" = "$(cat ops/admin/optibrain-admin-update.sha256)"
sudo sha256sum /var/tmp/optibrain-admin-update/incoming/candidate.py /etc/optibrain/admin-helper.sha256
sudo -k
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin-update
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin sync-master-runbook
```

Expected updater success reports the new helper hash, self-test passed, and a
preserved previous-helper path whose suffix is
`-30aad73bb2b56a11.py`. Expected runbook sync output is the SHA-256 in the
updated `master-runbook.sha256`, currently
`master runbook synchronized: sha256=cdab559d264fb7a17c469fd10953827a98a24ac4a926939db1055522a6dfc085`.

Post-install validation:

```bash
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin --self-test
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin health
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin scheduler
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin verify-latest
sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin restore-verify-latest
sudo sha256sum /usr/local/sbin/optibrain-admin /usr/local/sbin/optibrain-admin-update /usr/local/lib/optibrain-backup/optibrain-restore-drill.py
test "$(sudo sha256sum /usr/local/sbin/optibrain-admin | cut -d' ' -f1)" = b6313a79357afed164d3d7bfd363dd14403b3c8853927c721370e1e94df17244
test "$(sudo sha256sum /usr/local/sbin/optibrain-admin-update | cut -d' ' -f1)" = 8f1f2fdecb8603f94f746532ecfa2b90a26f9ee4e57b3d6e70e74509e166dfe6
test "$(sudo sha256sum /usr/local/lib/optibrain-backup/optibrain-restore-drill.py | cut -d' ' -f1)" = 58f9e2305329326c5dfdbb88af4d1535f33fda3f9fb6d03163212b7929fc7db6
test "$(sha256sum docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md | cut -d' ' -f1)" = "$(sudo cat /etc/optibrain/master-runbook.sha256)"
sudo visudo -c
sudo systemctl is-active optibrain-backup.timer optibrain-phase2a-upload.timer
sudo systemctl is-enabled optibrain-backup.timer optibrain-phase2a-upload.timer
curl --fail --silent --show-error https://optibrain.opticable.ca/v1/system/health
curl --fail --silent --show-error https://optibrain.opticable.ca/pdf/health
curl --fail --silent --show-error https://optibrain.opticable.ca/omada/api/health
```

Run all negative privilege tests in the post-install validation section above.
The helper and updater must match their reviewed hashes; the restore verifier
must retain hash
`58f9e2305329326c5dfdbb88af4d1535f33fda3f9fb6d03163212b7929fc7db6`.

Rollback: the updater restores the exact previous helper automatically if its
transaction fails. For a later failed validation, substitute the exact
`preserved_previous` helper path printed by the updater and run:

```bash
HELPER_BACKUP='/var/lib/optibrain/admin-update/previous/<exact-printed-helper-backup>.py'
UPDATER_BACKUP='/var/lib/optibrain/admin-update/previous/optibrain-admin-update-3594770351bd2a96.py'
test "$(sudo sha256sum "$HELPER_BACKUP" | cut -d' ' -f1)" = 30aad73bb2b56a110e38348cce5babefb1816b7f1ffd7cd37449a51a0f1527c4
test "$(sudo sha256sum "$UPDATER_BACKUP" | cut -d' ' -f1)" = 3594770351bd2a96cda822a4242587cb265894906255cfc61f28a7fff1a54086
sudo install -o root -g root -m 0750 "$HELPER_BACKUP" /usr/local/sbin/.optibrain-admin.rollback
sudo mv -fT /usr/local/sbin/.optibrain-admin.rollback /usr/local/sbin/optibrain-admin
sudo install -o root -g root -m 0750 "$UPDATER_BACKUP" /usr/local/sbin/.optibrain-admin-update.rollback
sudo mv -fT /usr/local/sbin/.optibrain-admin-update.rollback /usr/local/sbin/optibrain-admin-update
printf '%s\n' 30aad73bb2b56a110e38348cce5babefb1816b7f1ffd7cd37449a51a0f1527c4 > /tmp/optibrain-helper.rollback.sha256
sudo install -o root -g root -m 0440 /tmp/optibrain-helper.rollback.sha256 /etc/optibrain/admin-helper.sha256
sudo install -o optibrain -g optibrain -m 0440 /tmp/optibrain-helper.rollback.sha256 /var/tmp/optibrain-admin-update/incoming/candidate.sha256
```

If runbook sync succeeded, use the exact previous-copy path created by that
sync, verify its old digest, restore the document, and reset both runbook pins:

```bash
RUNBOOK_BACKUP='/var/lib/optibrain/admin-update/previous/<exact-master-runbook-backup-ending-23b5dbdcc886a19c>.md'
test "$(sudo sha256sum "$RUNBOOK_BACKUP" | cut -d' ' -f1)" = 23b5dbdcc886a19cba35c57c5a9be51ce64090b2ed0e370b39f7289753c9439e
sudo install -o root -g root -m 0644 "$RUNBOOK_BACKUP" /opt/opticable-api-platform/docs/.OPTICABLE_AUTOMATION_MASTER_RUNBOOK.rollback
sudo mv -fT /opt/opticable-api-platform/docs/.OPTICABLE_AUTOMATION_MASTER_RUNBOOK.rollback /opt/opticable-api-platform/docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md
printf '%s\n' 23b5dbdcc886a19cba35c57c5a9be51ce64090b2ed0e370b39f7289753c9439e > /tmp/optibrain-runbook.rollback.sha256
sudo install -o root -g root -m 0440 /tmp/optibrain-runbook.rollback.sha256 /etc/optibrain/master-runbook.sha256
sudo install -o optibrain -g optibrain -m 0440 /tmp/optibrain-runbook.rollback.sha256 /var/tmp/optibrain-admin-update/incoming/master-runbook.sha256
```

Retain both temporary rollback pin files for inspection and keep all recovery
generations and the pre-consolidated sudoers backup. Do not change sudoers
during rollback; its command paths are unchanged.

## Exact one-time human-root installation procedure

Run only from the reviewed committed checkout and compare `git rev-parse HEAD`
with the checkpoint in the review record. The artifact manifest must pass before
installation. The extra check confirms the runbook pin describes exactly the
staged document.

```bash
cd /opt/opticable-api-platform
git rev-parse HEAD
sha256sum -c ops/admin/ROOT_BOOTSTRAP_SHA256SUMS
test "$(sha256sum docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md | cut -d' ' -f1)" = "$(cat ops/admin/master-runbook.sha256)"
visudo -cf ops/admin/optibrain-admin-update.sudoers
```

Stop for manual inspection if any “must not exist” check fails. Do not overwrite
unknown files or an existing recovery copy.

```bash
# Existing targets and recovery destination must be absent; inspect everything
# before writing any staged/root-owned artifact.
sudo namei -l /var/lib/optibrain/admin-update/previous /var/tmp/optibrain-admin-update/incoming /etc/optibrain /usr/local/lib/optibrain-backup /etc/sudoers.d/90-optibrain-admin
sudo stat -c '%n %a %U:%G' /var/lib/optibrain /etc/optibrain /usr/local/lib/optibrain-backup /etc/sudoers.d/90-optibrain-admin
sudo test -f /etc/sudoers.d/90-optibrain-admin
sudo test ! -L /etc/sudoers.d/90-optibrain-admin
sudo visudo -cf /etc/sudoers.d/90-optibrain-admin
sudo test ! -e /var/tmp/optibrain-admin-update/incoming/candidate.py
sudo test ! -L /var/tmp/optibrain-admin-update/incoming/candidate.py
sudo test ! -e /var/tmp/optibrain-admin-update/incoming/candidate.sha256
sudo test ! -L /var/tmp/optibrain-admin-update/incoming/candidate.sha256
sudo test ! -e /var/tmp/optibrain-admin-update/incoming/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md
sudo test ! -L /var/tmp/optibrain-admin-update/incoming/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md
sudo test ! -e /var/tmp/optibrain-admin-update/incoming/master-runbook.sha256
sudo test ! -L /var/tmp/optibrain-admin-update/incoming/master-runbook.sha256
sudo test ! -e /etc/optibrain/admin-helper.sha256
sudo test ! -L /etc/optibrain/admin-helper.sha256
sudo test ! -e /etc/optibrain/master-runbook.sha256
sudo test ! -L /etc/optibrain/master-runbook.sha256
sudo test ! -e /usr/local/sbin/optibrain-admin-update
sudo test ! -L /usr/local/sbin/optibrain-admin-update
sudo test ! -e /usr/local/lib/optibrain-backup/optibrain-restore-drill.py
sudo test ! -L /usr/local/lib/optibrain-backup/optibrain-restore-drill.py
sudo test ! -e /etc/sudoers.d/90-optibrain-admin.tmp
sudo test ! -L /etc/sudoers.d/90-optibrain-admin.tmp
sudo test ! -e /var/lib/optibrain/admin-update/previous/90-optibrain-admin.pre-consolidated
sudo test ! -L /var/lib/optibrain/admin-update/previous/90-optibrain-admin.pre-consolidated

# Preserve/prepare private fixed directories. install -d does not remove content.
sudo install -d -o root -g root -m 0700 /var/lib/optibrain/admin-update
sudo install -d -o root -g root -m 0700 /var/lib/optibrain/admin-update/previous
sudo install -d -o root -g root -m 0750 /var/tmp/optibrain-admin-update
sudo install -d -o root -g optibrain -m 0730 /var/tmp/optibrain-admin-update/incoming

# Stage the exact reviewed source and its separate workflow/root authorization pins.
sudo install -o optibrain -g optibrain -m 0440 ops/admin/optibrain-admin.py /var/tmp/optibrain-admin-update/incoming/candidate.py
sudo install -o optibrain -g optibrain -m 0440 ops/admin/optibrain-admin.sha256 /var/tmp/optibrain-admin-update/incoming/candidate.sha256
sudo install -o optibrain -g optibrain -m 0440 docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md /var/tmp/optibrain-admin-update/incoming/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md
sudo install -o optibrain -g optibrain -m 0440 ops/admin/master-runbook.sha256 /var/tmp/optibrain-admin-update/incoming/master-runbook.sha256
sudo install -o root -g root -m 0440 ops/admin/optibrain-admin.sha256 /etc/optibrain/admin-helper.sha256
sudo install -o root -g root -m 0440 ops/admin/master-runbook.sha256 /etc/optibrain/master-runbook.sha256
sudo install -o root -g root -m 0750 ops/admin/optibrain-admin-update.py /usr/local/sbin/optibrain-admin-update
sudo install -o root -g root -m 0750 ops/backup/optibrain-restore-drill.py /usr/local/lib/optibrain-backup/optibrain-restore-drill.py
sudo install -o root -g root -m 0600 /etc/sudoers.d/90-optibrain-admin /var/lib/optibrain/admin-update/previous/90-optibrain-admin.pre-consolidated
sudo install -o root -g root -m 0440 ops/admin/optibrain-admin-update.sudoers /etc/sudoers.d/90-optibrain-admin.tmp
sudo visudo -cf /etc/sudoers.d/90-optibrain-admin.tmp
sudo mv -fT /etc/sudoers.d/90-optibrain-admin.tmp /etc/sudoers.d/90-optibrain-admin
sudo visudo -c
```

Only after full sudoers validation, return to `optibrain`, clear cached sudo
credentials, and run the approved digest-pinned helper update. This is the first
operation that changes the installed helper. It preserves the prior helper and
automatically rolls back if any verification gate fails.

```bash
sudo -k
sudo -n /usr/local/sbin/optibrain-admin-update
```

## Exact post-install validation

```bash
sudo -k
sudo -n -l
sudo -n /usr/local/sbin/optibrain-admin --self-test
sudo -n /usr/local/sbin/optibrain-admin health
sudo -n /usr/local/sbin/optibrain-admin scheduler
sudo -n /usr/local/sbin/optibrain-admin verify-latest
sudo -n /usr/local/sbin/optibrain-admin restore-verify-latest
sudo -n /usr/local/sbin/optibrain-admin queue-status
sudo -n /usr/local/sbin/optibrain-admin capacity
sudo -n /usr/local/sbin/optibrain-admin logs opticable-workflow-api.service 50
if sudo -u optibrain /usr/bin/sudo -n /usr/bin/id >/dev/null 2>&1; then echo 'FAIL: arbitrary sudo allowed'; exit 1; else echo 'PASS: arbitrary sudo denied'; fi
if sudo -u optibrain /usr/bin/sudo -n /bin/sh -c id >/dev/null 2>&1; then echo 'FAIL: shell sudo allowed'; exit 1; else echo 'PASS: shell sudo denied'; fi
if sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin service-restart ssh.service >/dev/null 2>&1; then echo 'FAIL: unapproved service accepted'; exit 1; else echo 'PASS: unapproved service denied'; fi
if sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin logs ../../etc/shadow 10 >/dev/null 2>&1; then echo 'FAIL: arbitrary log path accepted'; exit 1; else echo 'PASS: arbitrary log path denied'; fi
if sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin -- /bin/sh -c id >/dev/null 2>&1; then echo 'FAIL: helper subcommand escape accepted'; exit 1; else echo 'PASS: helper subcommand escape denied'; fi
if sudo -u optibrain /usr/bin/sudo -n /usr/local/sbin/optibrain-admin-update /etc/shadow >/dev/null 2>&1; then echo 'FAIL: updater arguments accepted'; exit 1; else echo 'PASS: updater arguments denied'; fi
if sudo -u optibrain /usr/bin/sudo -n /usr/bin/env PYTHONPATH=/tmp /usr/local/sbin/optibrain-admin health >/dev/null 2>&1; then echo 'FAIL: sudo environment injection accepted'; exit 1; else echo 'PASS: sudo environment injection denied'; fi
sudo stat -c '%n %a %U:%G' /usr/local/sbin/optibrain-admin-update /usr/local/sbin/optibrain-admin /usr/local/lib/optibrain-backup/optibrain-restore-drill.py /etc/sudoers.d/90-optibrain-admin
sudo sha256sum /usr/local/sbin/optibrain-admin-update /usr/local/sbin/optibrain-admin /usr/local/lib/optibrain-backup/optibrain-restore-drill.py
sudo visudo -c
```

Do not run `backup` or `upload` as an installation smoke test: both are approved
mutations and should follow the normal recovery-intent journal protocol. Existing
Phase 1 and Phase 2A timers must remain enabled and active. The root helper does
not enable, disable, or edit either timer.

## Rollback

If the updater rejects or fails self-test, it restores the exact previous helper
bytes and verifies their hash automatically. Do not retry with a changed pin.
If sudoers validation fails after replacement, restore the protected previous
fixed drop-in as root and validate immediately:

```bash
sudo install -o root -g root -m 0440 /var/lib/optibrain/admin-update/previous/90-optibrain-admin.pre-consolidated /etc/sudoers.d/90-optibrain-admin
sudo visudo -c
```

For a later emergency helper rollback, use the exact backup filename printed by
the updater (never a glob); verify the hash against the recorded pre-update
value. The original helper predates the new self-test, so do not run its
self-test. If the updater itself is defective, restore its pre-bootstrap copy
from a separately reviewed root recovery artifact or reinstall the exact
manifest-verified source from this checkpoint in a human root session. The
updater is never authorized to update itself.

## Validation, status and remaining limits

Rootless ops/admin adversarial tests cover digest mismatch, candidate mutation
and replacement after authorization, symlinks, unsafe ownership, argument/path
injection, static helper policy markers, malformed code, forbidden shell and
interpreter commands, failed self-test and verified rollback, audit secrecy,
helper parser escapes, environment injection, service substitution, bounded
logs/redaction, backup retention policy, runbook source symlink/owner checks,
AGE identity invocation, attempts at arbitrary `/etc` writes, backup-protection
disabling and R2-public changes. `visudo -cf`, helper self-test, syntax/hash
checks and the full workflow API regression suite run without root. The canonical
suite command is `cd apps/workflow-api && .venv/bin/python -m pytest -q tests`;
it passed 75 tests and 18 subtests in the current environment without installing
dependencies.
no dependency installation is needed.

This package has not been root-installed or exercised against root-owned runtime
paths. The production backup helper refuses manual backup when it cannot prove
the fixed seven-generation retention policy has at least two spare slots, so it
will not intentionally trigger retention deletion. Log redaction is pattern
based; authorized operators can still see non-secret personal/confidential log
content. The updater allowlist intentionally makes future helper releases a
human-reviewed root action. Existing password-authenticated sudo group access is
not removed or broadened. No deployment, restart, backup, upload, restore drill,
provider write, timer change, service change, R2 policy change, or AGE identity
operation occurred while preparing this review package.
