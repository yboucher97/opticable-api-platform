# OptiBrain Hardening Phase 1: Local Backup and Recovery

Status: Phase 1 finalized on 2026-09-26. Phase 2A advanced on 2026-09-27;
see the autonomous progress journal. Root-owned runbook synchronization is now complete.

The master runbook now incorporates this Phase 1 record by reference. Historical
Phase 2 prerequisite notes below describe the original Phase 1 checkpoint; consult
the current progress journal and Phase 2A document for live status.

## Objective

Provide a hardened, local, root-only recovery backup for the OptiBrain production
checkout, persistent service state, consistent automation SQLite data, operational
configuration, and recovery metadata. Validate archives non-destructively and retain
seven valid generations by default. Phase 1 does not transfer backups off-host.

## Architecture

- `optibrain-backup.service` runs the backup script as `root` with `ProtectHome=true`,
  `ProtectSystem=strict`, `RestrictSUIDSGID=true`, `NoNewPrivileges=true`, private
  devices/tmp, and only `/var/backups/optibrain` writable.
- `optibrain-backup.timer` runs persistently once daily at 02:30 UTC with a 15-minute
  randomized delay.
- The script creates a private staging tree, archives the Git release, copies state
  and configuration, performs a SQLite online backup plus integrity check, writes a
  manifest with SHA-256 checksums and source metadata, creates a gzip archive and
  sidecar checksum, then verifies the archive before retention cleanup.
- Generic content extraction uses `tar --no-same-owner --no-same-permissions`. Original
  uid/gid, mode (including setgid), type, and mtime are preserved in `manifest.json`
  for an operator-led restore.
- Git trust is command-scoped to the exact checkout with
  `-c safe.directory=/opt/opticable-api-platform`; `safe.directory=*` is forbidden.
- Logs go to stderr and journald; no manually-created logfile is required.

## Phase 1 files

- `ops/backup/optibrain-backup.sh` — backup, verification, retention, metadata, and
  safe staging implementation.
- `ops/backup/optibrain-backup.service` — hardened root systemd service.
- `ops/backup/optibrain-backup.timer` — persistent daily schedule.
- `ops/backup/optibrain-backup.conf.example` — non-secret installation configuration.
- `tests/test_optibrain_backup.sh` — fixture, ownership, Git trust, SQLite, setgid,
  archive, checksum, manifest, and systemd-policy regression tests.
- `docs/OPTIBRAIN_PHASE1_LOCAL_BACKUP.md` — this complete Phase 1 record.

## Installation

Run as root on the production host after reviewing the files:

    sudo install -d -m 0700 -o root -g root /etc/optibrain /var/backups/optibrain
    sudo install -m 0640 -o root -g root ops/backup/optibrain-backup.conf.example /etc/optibrain/backup.conf
    sudo install -m 0750 -o root -g root ops/backup/optibrain-backup.sh /opt/opticable-api-platform/ops/backup/optibrain-backup.sh
    sudo install -m 0644 -o root -g root ops/backup/optibrain-backup.service /etc/systemd/system/optibrain-backup.service
    sudo install -m 0644 -o root -g root ops/backup/optibrain-backup.timer /etc/systemd/system/optibrain-backup.timer
    sudo systemctl daemon-reload
    sudo systemd-analyze verify /etc/systemd/system/optibrain-backup.service /etc/systemd/system/optibrain-backup.timer

The configuration contains paths and retention only; it must not contain secret values.

## Schedule and retention

- Timer: `OnCalendar=*-*-* 02:30:00 UTC`, `Persistent=true`,
  `RandomizedDelaySec=15m`.
- Retention: seven archive generations by default, configurable with
  `OPTIBRAIN_BACKUP_RETENTION`. Deletion is skipped if it could leave only an invalid
  backup. Archives and `.sha256` sidecars are root-owned mode `0600`; the destination
  directory is root-owned mode `0700`.

## Verification

    sudo sha256sum -c /var/backups/optibrain/optibrain-backup-YYYYMMDDTHHMMSSZ.tar.gz.sha256
    sudo /opt/opticable-api-platform/ops/backup/optibrain-backup.sh --verify /var/backups/optibrain/optibrain-backup-YYYYMMDDTHHMMSSZ.tar.gz
    sudo journalctl -u optibrain-backup.service --no-pager

`--verify` checks archive paths, manifest format, file sizes, SHA-256 values, and
SQLite integrity without restoring over production.

## Restore procedure

1. Preserve the failed host and select a checksum-verified generation.
2. Run `sha256sum -c` and `--verify` on a separate recovery directory or replacement
   host. Never extract over production paths.
3. Extract into staging. Recover source from `source/`, configuration and units from
   `system/`, persistent state from `state/`, and the consistent database from
   `database/automation.db`.
4. Review `manifest.json` `source_metadata`; restore ownership, permissions, setgid,
   and timestamps as root only after content and paths are approved.
5. Restore credential-bearing files only as root, validate SQLite and application
   health on the recovery host, then start only the affected service there.
6. Record archive, recovered SHA, operator, validation results, and missing external
   provider state. This archive does not restore provider-side data.

## Security model and secret handling

**LOCAL BACKUP CONTAINS SENSITIVE CREDENTIAL MATERIAL.** The recovery archive can
contain sensitive credential material, including Zoho OAuth recovery state. Local
archives must remain root-only: directory `0700`, archive/checksum `0600`, owned by
`root:root`. Secret values, OAuth files, generated recovery state, archives, and
`/etc` secret contents must never enter Git or chat. The repository records only paths,
metadata, policy, and recovery instructions.

Future off-host backups **must be encrypted before leaving the VPS**. The recovery /
decryption key must be outside the failure domains of the VPS, normal OptiBrain
execution, and autonomous Codex/agent execution. Off-host backup and key management
are explicitly not implemented in Phase 1.

The archive currently includes substantial reproducible Playwright/Chromium runtime
data under Omada state. Do not remove it during Phase 1. Future work must first classify
state into (A) irreplaceable recovery state and (B) reproducible dependencies/cache/
runtime, then prove restore behavior before excluding (B) to reduce size and transfer
cost.

## Failure record and permanent fixes

1. **226/NAMESPACE from logfile path.** The service listed
   `/var/log/optibrain-backup.log` in `ReadWritePaths`, but the file did not exist.
   Permanent fix: remove the manually-created logfile dependency; emit stderr and use
   journald/systemd-native logging. The service retains no logfile path.
2. **Git dubious ownership.** Backup ran as root while the checkout belonged to
   `optibrain`, and `ProtectHome=true` prevented relying on root `~/.gitconfig`.
   Permanent fix: every backup Git operation uses command-scoped narrow
   `-c safe.directory=/opt/opticable-api-platform` (substituted for fixture paths).
   `safe.directory=*` is never used.
3. **setgid staging failure.** `cp -a` attempted to recreate source directory mode
   `2770`/setgid, which `RestrictSUIDSGID=true` correctly prevented.
   Permanent fix: extract safely without same-owner/same-permissions and preserve the
   original recovery metadata in `manifest.json`. `RestrictSUIDSGID` remains enabled.

## Commands and approaches that worked

- `bash -n ops/backup/optibrain-backup.sh tests/test_optibrain_backup.sh`.
- The Phase 1 fixture creates a non-root-owned checkout with global Git configuration
  unavailable, runs the backup, validates the sidecar SHA-256, runs `--verify`, checks
  SQLite, checks the preserved `2770` source metadata, and confirms staging does not
  recreate setgid mode.
- `systemd-analyze verify` validates the service and timer.
- Production backup: `/var/backups/optibrain/optibrain-backup-20260926T232858Z.tar.gz`.
  External SHA256: OK. Built-in non-destructive restore verification: PASSED.
- Backup security verified: directory `0700 root:root`, archive `0600 root:root`,
  checksum `0600 root:root`, and no leftover staging directories.
- `optibrain-backup.timer` is enabled and active; next scheduled execution confirmed.
- `opticable-workflow-api` is active; `/health` is status `ok`; production version is
  `1.7.0`.

## Commands and approaches that failed

- Initial systemd start failed with `226/NAMESPACE` because the nonexistent logfile
  was listed as writable.
- Initial root Git operations failed with Git's dubious-ownership rejection under
  `ProtectHome=true`.
- Initial `cp -a` staging failed when it attempted to recreate source setgid metadata
  under `RestrictSUIDSGID=true`.

## Execution and repository record

- Pre-change SHA: `6dc4858c8cf3b5a0ec292a67123e958fd7cbfb67`.
- Pre-change recovery reference: `recovery/pre-phase1-6dc4858c`.
- Production validation is complete as recorded above; no production backup archive is
  modified by repository finalization.
- No providers, Zoho Books, OAuth configuration, or OAuth credentials were modified.
- Phase 1 commit must contain only the listed source, documentation, and tests. No
  archive, secret, OAuth file, environment secret, or generated recovery state may be
  committed.

## Remaining Phase 1 risks

Independent off-host durability, encryption/key custody, separate-host restore drill,
off-host monitoring, and provider-side state recovery remain unresolved by design.
The local archive is a high-value credential-bearing artifact and depends on strict
root-only permissions. Reproducible Omada runtime data still increases archive size.

## Phase 2 prerequisites (not started)

- Define and approve an encrypted off-host backup design.
- Place the recovery/decryption key outside the VPS, OptiBrain runtime, and autonomous
  agent failure domains.
- Complete and document a separate-host restore drill before excluding reproducible
  runtime/cache data.
- Classify irreplaceable state versus reproducible dependencies/cache/runtime.
- Add independent destination monitoring and alerting.

The master runbook synchronization was completed on 2026-09-27, preserving its
existing content and incorporating this record by reference.
