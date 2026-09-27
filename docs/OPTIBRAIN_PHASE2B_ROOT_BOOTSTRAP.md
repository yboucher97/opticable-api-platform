# Phase 2B consolidated root bootstrap proposal

Status: review package only. Nothing here has been installed. No production
service, timer, sudoers file, backup, provider, or root-owned file was changed.
Baseline: `a67dc9b3d1da55c4ee0b22296464271af02f4221`, recovery ref
`recovery/phase2b-root-bootstrap-55f07e8`.

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

`ops/admin/ROOT_BOOTSTRAP_SHA256SUMS` lists the SHA-256 for each artifact below.
It also verifies the checksum sidecars themselves. The root-installed/staged
source artifacts are:

| Source | Root destination / purpose |
|---|---|
| `ops/admin/optibrain-admin-update.py` | `/usr/local/sbin/optibrain-admin-update` |
| `ops/admin/optibrain-admin.py` | Staged candidate, then installed transactionally at `/usr/local/sbin/optibrain-admin` by the updater |
| `ops/admin/optibrain-admin.sha256` | Candidate checksum and root pin `/etc/optibrain/admin-helper.sha256` |
| `ops/admin/optibrain-admin-update.sudoers` | `/etc/sudoers.d/90-optibrain-admin` |
| `ops/backup/optibrain-restore-drill.py` | `/usr/local/lib/optibrain-backup/optibrain-restore-drill.py` |
| `docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md` | Fixed staged runbook source |
| `ops/admin/master-runbook.sha256` | Staged checksum and root authorization pin `/etc/optibrain/master-runbook.sha256` |

No AGE identity, provider credential, or other secret is an installation
artifact. The restore script is installed root-only because the helper invokes
it with a fixed archive path and digest; the script is not separately granted in
sudoers.

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
if sudo -n /usr/bin/id >/dev/null 2>&1; then echo 'FAIL: arbitrary sudo allowed'; exit 1; else echo 'PASS: arbitrary sudo denied'; fi
if sudo -n /bin/sh -c id >/dev/null 2>&1; then echo 'FAIL: shell sudo allowed'; exit 1; else echo 'PASS: shell sudo denied'; fi
if sudo -n /usr/local/sbin/optibrain-admin service-restart ssh.service >/dev/null 2>&1; then echo 'FAIL: unapproved service accepted'; exit 1; else echo 'PASS: unapproved service denied'; fi
if sudo -n /usr/local/sbin/optibrain-admin logs ../../etc/shadow 10 >/dev/null 2>&1; then echo 'FAIL: arbitrary log path accepted'; exit 1; else echo 'PASS: arbitrary log path denied'; fi
if sudo -n /usr/local/sbin/optibrain-admin -- /bin/sh -c id >/dev/null 2>&1; then echo 'FAIL: helper subcommand escape accepted'; exit 1; else echo 'PASS: helper subcommand escape denied'; fi
if sudo -n /usr/local/sbin/optibrain-admin-update /etc/shadow >/dev/null 2>&1; then echo 'FAIL: updater arguments accepted'; exit 1; else echo 'PASS: updater arguments denied'; fi
if sudo -n /usr/bin/env PYTHONPATH=/tmp /usr/local/sbin/optibrain-admin health >/dev/null 2>&1; then echo 'FAIL: sudo environment injection accepted'; exit 1; else echo 'PASS: sudo environment injection denied'; fi
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
