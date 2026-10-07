# Current host inventory

AUDIT EVIDENCE — READ ONLY. Captured 2026-10-07T04:03:42.176288+00:00. Canonical complete metadata: [current-host-manifest.json](current-host-manifest.json). Values of secret files were not documented.

Ubuntu "24.04", x86_64; kernel `6.8.0-142-generic`; host `vps-214ba8cd`; timezone `America/Toronto`. Four virtual CPU cores; 8,127,705,088 bytes RAM; 2 GiB swap. Root disk: 72 GiB, 99% used; initial free 1,374,199,808 bytes. Critical storage risk: YES. Inodes: 7% used. No retention cleanup was performed.

Verified production source and refreshed HTTPS `origin/main`: `be8cdfe2b36b562ba9e2a57484d8a3d2e8c92caa`, API `1.34.1`. SSH Git authentication failed; public HTTPS fetch succeeded. The matching release receipt and independently read-back recovery are `20261007T030438Z`. Git submodules: none. Source checkout `/opt/opticable-api-platform`; immutable releases `/opt/optibrain-releases`; recovery history `/var/lib/optibrain/recovery-source/current.bundle`. Untracked venvs/builds are regenerable runtime files, not canonical Git source.

Worktrees: 54; do not restore them. Largest controlled directories: `/var/backups/optibrain` ~28 GiB; `/var/lib/optibrain` ~16 GiB including ~15 GiB encrypted upload spool; `/home/optibrain` ~9.6 GiB; immutable releases ~4.5 GiB; `/var/tmp` and `/tmp` ~1.7 GiB each. Backup staging/retained generations total: `29393039360	/var/backups/optibrain`. Exact directory/mount/disk/df measurements are in the manifest.

Python 3.12.3; Node 22.23.3; npm 12.2.0; Git 2.43.0; Caddy 2.6.2. Installed package versions, users/groups, named service identities, sudo file hashes, every environment key name and configuration owner/mode/hash are in the machine inventory. Codex tooling is development-only; its worker/authorization is OFF and personal caches/credentials are not rebuild inputs.

## Services

| Unit | Class | Runtime | Restore | Purpose / authority |
|---|---|---|---|---|
| `caddy-api.service` | RETIRED / MASKED | inactive / disabled | CONTAINED | Caddy; NO AUTHORITY |
| `caddy.service` | ACTIVE REQUIRED | active / enabled | CONTAINED | Caddy; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `fail2ban.service` | ACTIVE REQUIRED | active / enabled | CONTAINED | Fail2Ban Service; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `optibrain-agent-dispatch.service` | RETIRED / MASKED | inactive / masked | MASKED | optibrain-agent-dispatch.service; NO AUTHORITY |
| `optibrain-agent-status.service` | RETIRED / MASKED | inactive / masked | MASKED | optibrain-agent-status.service; NO AUTHORITY |
| `optibrain-agent-usage.service` | RETIRED / MASKED | inactive / masked | MASKED | optibrain-agent-usage.service; NO AUTHORITY |
| `optibrain-backup.service` | ONESHOT | inactive / static | CONTAINED | OptiBrain local backup; BACKUP ONLY |
| `optibrain-phase2a-upload.service` | ONESHOT | inactive / static | CONTAINED | OptiBrain encrypted off-host Phase 2A backup; BACKUP ONLY |
| `opticable-customer-communications.service` | ONESHOT | inactive / static | MASKED | OptiBrain individually scoped operational customer emails; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `opticable-lifecycle-internal.service` | ONESHOT | inactive / static | MASKED | OptiBrain individually scoped new-record internal lifecycle; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `opticable-omada-site.service` | ACTIVE REQUIRED | active / enabled | CONTAINED | Omada Site Creator; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `opticable-password-pdf.service` | ACTIVE REQUIRED | active / enabled | CONTAINED | Password PDF Generator API; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `opticable-phase10-service-events.service` | ONESHOT | inactive / static | CONTAINED | Reconcile OptiBrain service lifecycle evidence from read-only Zoho CRM; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `opticable-phase12-test-runner.service` | ONESHOT | inactive / disabled | MASKED | OptiBrain bounded TEST_ONLY business action runner; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `opticable-phase9-intake-receipts.service` | ONESHOT | inactive / disabled | CONTAINED | Collect OptiBrain lead intake receipts from Zoho Forms Mail and public connector; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `opticable-workflow-api.service` | ACTIVE REQUIRED | active / enabled | CONTAINED | Site And Password Workflow; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `ssh.service` | ACTIVE REQUIRED | active / disabled | CONTAINED | OpenBSD Secure Shell server; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `ufw.service` | ONESHOT | active / enabled | CONTAINED | Uncomplicated firewall; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |
| `ssh.socket` | ACTIVE REQUIRED | active / enabled | CONTAINED | OpenBSD Secure Shell server socket; ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS |

Exact Type/user/group/ExecStart/workdir/EnvironmentFiles/dependencies/restart/health/definition hashes are recorded per unit in JSON. Reviewed installed files/drop-ins live under `ops/rebuild/reviewed/systemd`; legacy Caddy API is optional/disabled. API/PDF/Omada/Caddy are required; root lifecycle/customer/TEST and observation services are scheduled jobs, not automatic restore authority.

## Timers

| Unit | Cadence | Enabled/runtime | Related service | Restore | Last / next |
|---|---|---|---|---|---|
| `optibrain-agent-dispatch.timer` | NOT APPLICABLE | masked / inactive |  | MASKED |  /  |
| `optibrain-agent-status.timer` | NOT APPLICABLE | masked / inactive |  | MASKED |  /  |
| `optibrain-agent-usage.timer` | NOT APPLICABLE | masked / inactive |  | MASKED |  /  |
| `optibrain-backup.timer` | { OnCalendar=*-*-* 02:30:00 UTC ; next_elapse=Wed 2026-10-07 22:30:00 EDT } | enabled / active | optibrain-backup.service | MASKED | Tue 2026-10-06 22:43:37 EDT / Wed 2026-10-07 22:33:23 EDT |
| `optibrain-phase2a-upload.timer` | { OnCalendar=*-*-* 03:00:00 UTC ; next_elapse=Wed 2026-10-07 23:00:00 EDT } | enabled / active | optibrain-phase2a-upload.service | MASKED | Tue 2026-10-06 23:00:13 EDT / Wed 2026-10-07 23:09:03 EDT |
| `opticable-customer-communications.timer` | { OnBootUSec=3min ; next_elapse=0 } | disabled / inactive | opticable-customer-communications.service | MASKED |  /  |
| `opticable-lifecycle-internal.timer` | { OnBootUSec=5min ; next_elapse=5min } | enabled / active | opticable-lifecycle-internal.service | MASKED | Tue 2026-10-06 23:58:27 EDT /  |
| `opticable-phase10-service-events.timer` | { OnBootUSec=10min ; next_elapse=10min } | enabled / active | opticable-phase10-service-events.service | MASKED | Tue 2026-10-06 23:45:25 EDT /  |
| `opticable-phase12-test-runner.timer` | { OnCalendar=*-*-* *:00/30:00 ; next_elapse=Wed 2026-10-07 00:30:00 EDT } | enabled / active | opticable-phase12-test-runner.service | MASKED | Wed 2026-10-07 00:01:56 EDT / Wed 2026-10-07 00:31:33 EDT |
| `opticable-phase9-intake-receipts.timer` | { OnBootUSec=2min ; next_elapse=2min } | enabled / active | opticable-phase9-intake-receipts.service | MASKED | Wed 2026-10-07 00:00:57 EDT /  |

The complete 23-host-timer listing, including OS maintenance schedules, is preserved in the manifest. Business/customer/internal schedules start masked; only backup/upload may resume after target validation.

## Databases

| Path | Purpose | Bytes | Schema version | Integrity/FK |
|---|---|---|---|---|
| `/var/lib/optibrain/phase10/test-lab/lifecycle-events.db` | Historical TEST lifecycle evidence | 12288 | 0 | ok / PASS |
| `/var/lib/optibrain/phase9/closure/phase9-intake.before-permission-fix.db` | Historical intake compatibility evidence | 28672 | 0 | ok / PASS |
| `/var/lib/optibrain/phase9/mission2/form-receipts-stage.db` | Historical staged receipt evidence | 53248 | 0 | ok / PASS |
| `/var/lib/opticable-workflow-api/output/automation/automation.db` | Core event/run/checkpoint/idempotency/audit journal | 26632192 | 2 | ok / PASS |
| `/var/lib/opticable-workflow-api/output/automation/phase10-service-events.db` | Durable service occurrence and completion chronology | 245760 | 0 | ok / PASS |
| `/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db` | Action Evidence, Manager, decisions, priorities, proposals, relationships, learning and preview state | 145797120 | 0 | ok / PASS |
| `/var/lib/opticable-workflow-api/output/automation/phase9-form-receipts.db` | Immutable Forms/Mail/connector receipt chronology | 1708032 | 0 | ok / PASS |
| `/var/lib/opticable-workflow-api/output/automation/phase9-intake.db` | Canonical intake/link/return/owner feedback chronology | 28672 | 0 | ok / PASS |

Eight actual stores: five active and three historical. Each uses online SQLite backup, verified staging restore and named ownership. Encryption is AGE off-host; local state/archive files rely on current filesystem isolation and root-only access, with no claim of full-disk encryption. Integrity: `PRAGMA integrity_check`; foreign keys: `PRAGMA foreign_key_check`. All table/schema/count/ID/row references and chain results are in the catalog.

## Filesystem and operational boundaries

| Class | Paths / recovery behavior |
|---|---|
| DURABLE | Five application state roots, all discovered DBs, immutable root lineage/evidence/crosswalks/baselines/customer state; preserve |
| SECRET | Three application env files, provider PEM/tokens/OAuth credentials and R2 key configuration; protected encrypted recovery |
| SYSTEM CONFIG | Reviewed systemd definitions/drop-ins/helpers, Caddy, firewall, named users and controlled journal policy |
| REGENERABLE | `/run/optibrain-readiness`, display projections, interpreter/build outputs; reconstruct safely |
| CACHE | browser/npm/pip/Codex caches and access-token caches; no bulk restore |
| TEMPORARY | `/tmp`, `/var/tmp`, WAL/SHM and locks; no restore |
| ARCHIVE | Retained local recovery/spool/raw historical logs; existing off-host retention/holds stay authoritative |

SSH is key-only, public TCP22, PermitRootLogin=no on production; replacement provisioning admin access is retained before any later named-admin tightening. Do not copy old SSH host private keys or root sudo grants. Current firewall denies incoming except TCP22/80/443; API8100/PDF8000/Omada3210 are loopback. Fail2ban is enabled.

Caddy config `/etc/caddy/conf.d/opticable-api-platform.caddy`; journal policy `/etc/systemd/journald.conf.d/30-optibrain-retention.conf` (512M persistent,128M runtime,2G keep-free,90d maximum). Raw old journal/access logs are not durable business audit. Structured action/effect history is indefinite and preserved. Backup helpers under `/usr/local/lib/optibrain-backup`, admin/deploy helpers under `/usr/local/sbin`, local archives `/var/backups/optibrain`, encrypted spool `/var/lib/optibrain/phase2a`.

Cloudflare account `81d07d311d1b51e5e04b451d1f254850`; running Workers/connector KV/queues are external state. DNS readback is in [cutover](cutover.md). Existing Access policies and complete public TLS failover remain future cutover checks. GitHub App identity and provider recovery limits are in [secrets](secrets-manifest.md). Large business files stay in WorkDrive; no full mail/document export was created.
