# Phase 2B digest-pinned admin updater: root bootstrap review package

Status: prepared for human-root review only. Nothing in this package has been
installed on the VPS. No production service, provider, backup, sudoers file, or
root-owned source file was changed while preparing it.

Source checkpoint is recorded in the progress journal. Review the exact commit
and verify `ops/admin/ROOT_BOOTSTRAP_SHA256SUMS` before running any root command.
The root-installed source digests at this checkpoint are listed in
`ops/admin/ROOT_BOOTSTRAP_SHA256SUMS`: helper candidate
`1b1e21b1b7aa32e1f777d1afdacb96a3cb0d1ddc5b2a5a770c7c529c2b3b0b27`, helper SHA authorization artifact
`ba1aac55a48c20fa3cf60ea1dddbceaa64ce82bd21b7acaf0566e6a2d1ece21f`, updater
`ba66f904ba08020fa5f3d2663463feba3d520362dd183e1f60997294df2c9a7b`, and sudoers drop-in
`556deefc0ccd84675ebbff5895df3c59982b9ad6df2a3b7d63a343b9130d2e40`.
The staged candidate checksum is not itself authorization: root must separately
install its exact digest into the root-only authorization file after reviewing
the candidate source.

## Trust and update transaction

The fixed, root-installed updater is `/usr/local/sbin/optibrain-admin-update`.
It accepts no arguments and only updates `/usr/local/sbin/optibrain-admin`.
It cannot update itself, sudoers, units, other files, or arbitrary paths. It
invokes only the fixed installed helper with `--self-test`, using an argument
array, `shell=False`, a minimal environment and an eight-second timeout.

The workflow stages two optibrain-owned mode-0440 files under
`/var/tmp/optibrain-admin-update/incoming/`: `candidate.py` and
`candidate.sha256`. The human-root approval step installs a separate copy of the
reviewed SHA-256 artifact as `/etc/optibrain/admin-helper.sha256`, root:root
0440. The updater independently opens all fixed inputs with `O_NOFOLLOW`,
checks the fixed parent paths, owner/group/mode/link count/size and stable file
metadata, calculates SHA-256 itself, and requires both the workflow checksum
and root-owned authorization pin to equal that digest.

After reading and authorizing the candidate bytes, the updater never reopens the
mutable candidate. It syntax/policy-checks the captured bytes, preserves the
current helper as a unique root-only backup, writes the exact captured bytes to
a same-directory temporary file, fsyncs, atomically replaces the helper, checks
the installed digest, and runs the bounded self-test. On any post-install
validation failure, it atomically restores the captured previous bytes and
verifies their hash. Backups are unique and are not deleted or overwritten.
Audit records contain only timestamp, sanitized actor, fixed operation,
updater version, result and non-sensitive failure code; no candidate content or
secret values are logged.

Static policy validation rejects malformed code, dynamic `eval`/`exec`/compile,
`os.system`/`os.popen`/exec/spawn functions, unapproved subprocess APIs, dynamic
command arrays, shell execution, missing helper-policy markers and a non-fixed
Python shebang. The SHA pin remains the authorization boundary: human root must
review the precise candidate and digest before installing the authorization
artifact.

## Root-owned master runbook synchronization

The candidate admin helper includes one separate fixed operation,
`sync-master-runbook`, for the existing root-owned repository runbook. It accepts
no path or additional argument. A workflow stages the document and checksum in
the same fixed incoming directory; root separately authorizes the SHA in
`/etc/optibrain/master-runbook.sha256`. The operation validates both hashes,
UTF-8 and the required document heading, opens the exact repository directory
component-by-component with `O_NOFOLLOW`, verifies the expected directory
owners/modes and current root-owned target, saves a versioned root-only copy,
then atomically replaces only
`/opt/opticable-api-platform/docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md`.
It records only the fixed operation in admin audit. It does not accept arbitrary
file editing parameters. A root administrator invokes this operation directly
from a root session; this bootstrap deliberately grants NOPASSWD only to the
updater, not to the general admin helper.

## Sudo policy

The proposed rule is exact and takes no arguments:

```sudoers
optibrain ALL=(root:root) NOPASSWD: /usr/local/sbin/optibrain-admin-update ""
```

Install it at `/etc/sudoers.d/90-optibrain-admin`, atomically replacing the
previous helper NOPASSWD rule after first preserving that rule in the protected
recovery directory. `""` requires an empty argument list. Do not add `ALL`, a
shell, `env`, an interpreter, a wildcard, `systemctl`, or a file utility to the
NOPASSWD rule. The existing authenticated sudo-group policy and the separate
forced-command deployment identity are not modified by this bootstrap; verify
that `optibrain` has only the updater in its NOPASSWD entries after installation.

## Files and root installation procedure

From the exact reviewed checkout on the VPS, as the human root administrator:

```bash
cd /opt/opticable-api-platform
git rev-parse HEAD
sha256sum -c ops/admin/ROOT_BOOTSTRAP_SHA256SUMS
visudo -cf ops/admin/optibrain-admin-update.sudoers
```

Compare HEAD and all reported hashes with the reviewed checkpoint before
continuing. The commands below create only fixed staging/recovery locations,
stage the reviewed candidate, install the reviewed updater and replace one
sudoers drop-in. They do not install or expose secrets.

```bash
sudo install -d -o root -g root -m 0700 /var/lib/optibrain/admin-update
sudo install -d -o root -g root -m 0700 /var/lib/optibrain/admin-update/previous
sudo install -d -o root -g root -m 0750 /var/tmp/optibrain-admin-update
sudo install -d -o root -g optibrain -m 0730 /var/tmp/optibrain-admin-update/incoming
sudo install -o optibrain -g optibrain -m 0440 ops/admin/optibrain-admin.py /var/tmp/optibrain-admin-update/incoming/candidate.py
sudo install -o optibrain -g optibrain -m 0440 ops/admin/optibrain-admin.sha256 /var/tmp/optibrain-admin-update/incoming/candidate.sha256
sudo install -o root -g root -m 0440 ops/admin/optibrain-admin.sha256 /etc/optibrain/admin-helper.sha256
sudo install -o root -g root -m 0750 ops/admin/optibrain-admin-update.py /usr/local/sbin/optibrain-admin-update
sudo test ! -e /var/lib/optibrain/admin-update/previous/90-optibrain-admin.pre-update
sudo install -o root -g root -m 0600 /etc/sudoers.d/90-optibrain-admin /var/lib/optibrain/admin-update/previous/90-optibrain-admin.pre-update
sudo install -o root -g root -m 0440 ops/admin/optibrain-admin-update.sudoers /etc/sudoers.d/90-optibrain-admin.tmp
sudo visudo -cf /etc/sudoers.d/90-optibrain-admin.tmp
sudo mv -fT /etc/sudoers.d/90-optibrain-admin.tmp /etc/sudoers.d/90-optibrain-admin
sudo visudo -c
```

The proposed sudoers source is validated before replacement. If the full policy
validation fails after replacement, restore the preserved file immediately with
the rollback procedure below; do not leave a malformed sudoers include.

## Validation after installation

Return to the `optibrain` account and clear any cached password authorization
before checking the non-interactive boundary:

```bash
sudo -k
sudo -n -l
sudo -n /usr/local/sbin/optibrain-admin-update
sudo -k
if sudo -n /usr/bin/id >/dev/null 2>&1; then echo 'FAIL: arbitrary sudo allowed'; exit 1; else echo 'PASS: arbitrary sudo denied'; fi
if sudo -n /bin/sh -c id >/dev/null 2>&1; then echo 'FAIL: shell sudo allowed'; exit 1; else echo 'PASS: shell sudo denied'; fi
if sudo -n /usr/local/sbin/optibrain-admin-update /etc/shadow >/dev/null 2>&1; then echo 'FAIL: updater arguments allowed'; exit 1; else echo 'PASS: updater arguments denied'; fi
if sudo -n /usr/local/sbin/optibrain-admin --self-test >/dev/null 2>&1; then echo 'FAIL: admin helper has NOPASSWD'; exit 1; else echo 'PASS: only updater has NOPASSWD'; fi
```

As root, verify installed modes and hashes without displaying file contents:

```bash
stat -c '%n %a %U:%G' /usr/local/sbin/optibrain-admin-update /usr/local/sbin/optibrain-admin /etc/sudoers.d/90-optibrain-admin
sha256sum /usr/local/sbin/optibrain-admin-update /usr/local/sbin/optibrain-admin
/usr/local/sbin/optibrain-admin --self-test
visudo -c
```

The updater itself prints the installed digest and exact preserved-helper backup
path on success. Root must retain that output in the non-secret change record.
The updater's audit is at `/var/lib/optibrain/admin-update/update-audit.jsonl`
(root-only, mode 0600).

## Rollback

A failed candidate self-test automatically restores the prior helper bytes and
verifies the prior digest. If the sudoers replacement fails validation, as root
restore the previous fixed drop-in and revalidate:

```bash
sudo install -o root -g root -m 0440 /var/lib/optibrain/admin-update/previous/90-optibrain-admin.pre-update /etc/sudoers.d/90-optibrain-admin
sudo visudo -c
```

If an installed helper later needs manual rollback, use the exact
`preserved_previous` filename printed by the successful updater (never a glob):

```bash
sudo install -o root -g root -m 0750 /var/lib/optibrain/admin-update/previous/<exact-preserved-helper-filename> /usr/local/sbin/optibrain-admin
sudo sha256sum /usr/local/sbin/optibrain-admin
```

The first preserved helper predates the new `--self-test` command, so verify its
hash against the captured backup rather than invoking its self-test. Keep the
updater NOPASSWD rule in place; do not restore broad or helper-wide NOPASSWD.

## Tests and limits

The rootless adversarial suite covers a wrong root digest, changed candidate
before update, candidate replacement after the authorized bytes are captured,
symlink input, unsafe owner, arbitrary path and argument injection, malformed
Python, dynamic/shell execution policy, failed self-test with verified rollback,
exact installed hash, fixed sudo escape policy, and an unrelated-file sentinel.
The sudoers artifact is parsed with `visudo -cf`; the proposed helper candidate
passes the updater's static policy validation. All tests run without root.

This package is prepared, not installed. It intentionally does not restore
routine root access to the admin helper because the approved rule permits only
the updater to receive NOPASSWD. The fixed helper's privileged routines will
need a separately reviewed invocation design before Phase 2B can be declared
complete. The updater, its candidate pin and its sudoers rule remain root
bootstrap artifacts requiring human review. No provider state, production
behavior, existing backup, timer, service, or active sudoers file was changed.
