# Fresh-VM rebuild and migration readiness

**FRESH VM REBUILD READINESS: PARTIAL.** The canonical manifest and fail-closed bootstrap/restore/verification toolchain are implemented. Eight recovery stores and all 6,277 manifest file hashes passed bounded component verification. A disposable fresh Ubuntu VPS drill remains required before treating full-host reconstruction as proved. There is no new VPS or production migration in this mission. Foundation remains complete.

## Current host

| Item | Verified observation |
|---|---|
| OS / kernel | Ubuntu 24.04.5 LTS / 6.8.0-142-generic |
| CPU / RAM | 4 vCPUs / 7.57 GiB RAM, 2 GiB swap |
| Disk / free | 72 GiB root disk / about 1.3 GiB free, 99% used |
| Storage risk | CRITICAL; inode use 7%; no retention/deletion decision made |
| Worktrees / backup area | 54 worktrees / 27.4 GiB local backup area |
| Identity | `vps-214ba8cd`, x86_64, America/Toronto |

Full read-only [host inventory](current-host-inventory.md) and [machine manifest](current-host-manifest.json) include users/groups, sudo metadata, package/runtime versions, mounts/disk layout, repository/worktrees, services/timers, hashes, config/credential paths, staging/cache/log locations and DNS assumptions. Large test data stayed in RAM; no images or full mail exports were downloaded.

## Rebuild

The exact first replacement command, after trusted packet transfer, is:

```bash
sudo bash /recovery/toolchain/ops/rebuild/bootstrap.sh restore --manifest /recovery/toolchain/docs/rebuild/current-host-manifest.json --catalog /recovery/catalog.json --archive /recovery/recovery.tar.gz --generation latest-verified --migration
```

Idempotency, safe rerun, failure containment and interrupted final sync are covered by private fixtures/fake adapters. Exact application source comes from a verified Git bundle or the exact public repository SHA. Python dependencies and npm lock builds are regenerated; Node 22.23.3 is hash-pinned. Named identities/permissions, 44 reviewed definitions/helper files, timer masks, firewall/SSH, private Caddy and controlled journald retention are automated. The current production host is refused before OS adapters execute.

The replacement-only backup adapter fixes recursive selection of a nested business `manifest.json`; both original-source and installed-byte hashes are reviewed. It installs under `/usr/local/lib/optibrain-backup`; today's production helper remains untouched.

See [bootstrap](bootstrap.md), [architecture](architecture.md) and [restore](restore.md). `/var/lib/optibrain-data` works on a single root disk. A future separately mounted 250–300 GB volume uses `--data-root /srv/optibrain-data`; canonical service paths bind to owned verified generations. No current live path is moved. WorkDrive/object-storage interfaces preserve off-host document/archive ownership without building a new document subsystem.

## Recovery and knowledge portability

| Item | Verified recovery snapshot |
|---|---|
| Live API / executable | 1.34.1 / `be8cdfe2b36b562ba9e2a57484d8a3d2e8c92caa` |
| Fetched origin/main | `be8cdfe2b36b562ba9e2a57484d8a3d2e8c92caa` at verification; tooling will be a separate reviewed Git identity |
| Latest verified generation | `20261007T030438Z`; independent encrypted download-hash verified |
| Stores | 8/8 integrity/FK/schema/table counts/row and ID hashes PASS; five active, three historical |
| Decision Cards / proposals | 34 proposal identities / 76 revisions; exact derived Card source and action evidence preserved |
| Priorities | 51 persisted identities / 286 revisions; current /run active projection is regenerable, not mislabeled as all 51 active |
| Owner corrections / events | 3 OWNER fact-correction events; 547 Manager events; feedback 0 |
| Audit | Phase12 116 envelopes / 603 events, plus all other store evidence; exact chain verification PASS |
| Learning Records | 0 honestly verified; future nonzero count/hash/IDs covered by dynamic table comparison and fixtures |
| Preview / relationships | 109 preview observations, webhook/history and CRM/Books links included |

The [snapshot catalog](recovery-catalog.json) records every table, schema and primary-key/full-row digests. [Knowledge summary](knowledge-summary.json) is generation-specific; live counts may grow. Todos, business history/events, owner corrections, source-health, proposal history, evidence bundles, customer lifecycle and future document/email tables/files remain in their existing stores/root evidence. Immutable R2 effect claims and edge Worker/KV state remain external and require newer-than-backup reconciliation. No accumulated learning is expected to be lost when these gates pass.

API health, release receipt, production checkout and fetched main were rechecked against current values; assumptions supplied in the mission were not used as proof. The selected archive has a matching local plaintext/hash and an independently verified ciphertext. Its own `offline_restore_verified` flag is false: prior owner decryption evidence for an older golden generation is not represented as decryption of this one.

## Secrets and provider identities

Canonical durable secret inventory: 17 paths with named owner/group/mode, consumer, recovery source and rotation notes. **Secrets printed: 0.** Existing local root-only plaintext recovery archives contain credentials; existing off-host recovery is AGE-encrypted for the owner-held identity. This local plaintext exception is recorded honestly and is not changed without a separate retention/storage decision. The private decryption identity stays on the owner's trusted device.

GitHub App OptiBrain Production (`5077440`, installation `164914980`, `/etc/optibrain/github-app.pem`) is preserved. Eleven required source-host reads PASS: GitHub, Cloudflare account/Workers, Builds, Zoho CRM/Books/Mail/Forms/WorkDrive, GA4, GSC and zero-credit Apollo. Google Ads remains deferred under the existing owner Basic-access boundary; optional paid/model-generating probes are omitted. Successful source-host reads do not substitute for replacement read gates. Portable OAuth refresh bindings avoid unnecessary reauthorization; failed host-bound binding is OWNER ACTION REQUIRED. See [secret paths](secrets-manifest.md) and [provider read results](provider-read-results.json).

## Safe restore

| Authority | Restored state |
|---|---|
| customer authority | OFF |
| customer timer | OFF |
| books writes | OFF |
| ads execution | OFF |
| outreach | OFF |
| conversion uploads | OFF |
| website production | OFF |
| persistent development worker | OFF |
| internal observation until validation | OFF |

Historical queued jobs and approvals are retained without a replay grant. Root OFF policy, final env overrides and masked business/observation services/timers prevent boot-triggered stale execution. Original restored business audits stay unchanged; bootstrap emits canonical Action Evidence into its separate hash-chained sidecar. Failed local/provider/backup/storage checks keep owner-cutover readiness NO and contain only the replacement.

## Migration and rollback

Private validation uses loopback Caddy plus SSH tunneling before DNS. Final delta is a fresh verified online recovery after source writers, observers **and intake** are frozen; target immutable-history superset and all-store checks precede switching proven bind mounts. The shared operation lock and pending-generation receipt permit interrupted sync readback/rerun without deleting either generation.

Prepared cutover binds exact old/new hosts, SHA, generation, approvals, DNS record/TTL/proxy state and rollback. Current `optibrain.opticable.ca` A origin is `148.113.249.7`, proxied, TTL1 = Cloudflare automatic. No DNS change occurred. Public TLS, owner Access login and native Forms setting readback remain later owner/cutover checks. Freeze/reconcile both hosts on rollback: inbound events after cutover can diverge even with writers OFF. Retain the old VPS intact/frozen for about 14 days, review after 7; no automatic termination. See [migration](migration.md), [cutover](cutover.md) and [rollback](rollback.md).

## Performance

Current measured API health median 1.822 ms, maximum 42.661 ms across five samples. Provider-free copied-state Manager render: 6168.839 ms; authenticated owner HTTP latency remains unmeasured because no owner Access session was available. Source CPU/RAM/disk and last job/provider samples are in the [baseline](performance-baseline.json). No stress test or costly collector was run. Target `baseline` and `compare` report actual better/similar/worse numbers (±15% similar band); new-host comparison has not run.

## Owner effort and Control Center

Normally three owner checkpoints: provide the VPS/IP and SSH/root access; authorize offline decryption and private trusted packet transfer; review and approve the concrete cutover/rollback report. Failed portable provider bindings may need extra consent/MFA. Everything in the target install/restore/verification is automated after the packet is supplied.

Recovery status model: **YES** ([result schema](result.schema.json), [Control Center contract](control-center.md)). Owner Control Center: **NOT BUILT IN THIS MISSION**. Last full rebuild drill: null, rather than a fabricated successful VPS test. The [future disposable drill](drill.md) defines installation, verification, rerun/failure checks and separately authorized destruction.

## Tests and safety

Final candidate: **96 focused tests / 100 subtests and 1,953 full tests / 1,851 subtests PASS**, with zero failures, errors, skips or network attempts. Exact-head CI is recorded in [machine report](final-report.json). The mount-isolated RAM backup shell fixture passed including a nested business manifest. Full regression fits RAM fixtures despite critical root storage; a heavyweight VM/container drill was skipped. Syntax, manifest schema, reviewed hashes, dry-run planning and documentation contracts are also checked.

Intermediate defects were fixed before release: structured failure fields, completed-marker reset, partial final-sync readback, nested backup manifest selection, and pre-package canonical audit loading. The old shell fixture initially copied live root state to RAM because it lacked a root-path override; it was stopped before archive creation and then rerun in a private mount namespace. No business/recovery source data changed.

**Safety counters:** DNS changes 0; production migration 0; destructive DB operations 0; customer writes 0; provider business mutations 0; business/recovery data deletions 0; production service/config changes 0. **Unexpected auth-cache writes: 1** — an initial Google read probe refreshed its live access-token cache. Refresh credentials and provider authorization were preserved; all subsequent OAuth/cache probes used private copies. This exception is not mislabeled as zero unexpected writes.

## Remaining proof

A fresh VPS must prove package/systemd/mount/full durable promotion and contained OS boot end to end, new-host provider identities, fresh encrypted backup, public TLS/Access at cutover and measured RTO. Owner-device decryption of the selected encrypted generation still needs its own receipt. These are explicit operational validation dependencies; another foundation phase is unnecessary.

## Final questions

| # | Question | Answer |
|---|---|---|
| 1 | Can an empty supported Ubuntu VPS be rebuilt automatically? | Implemented for Ubuntu 24.04 amd64 after the trusted recovery packet is supplied; complete fresh-VPS behavior remains unproven until the disposable drill. |
| 2 | How many owner actions are still required? | Three normal checkpoints: VPS/access, offline decryption/packet transfer, final cutover approval. Failed portable provider bindings may require additional consent. |
| 3 | Can the exact OptiBrain code version be restored? | Yes; verified bundle/public Git checkout is pinned to the recovery SHA and API identity, separate from reviewed tooling identity. |
| 4 | Can all durable databases be restored? | Eight actual recovery stores passed streamed restore checks; discovery and all-table snapshots support a changed future count rather than hardcoding eight. |
| 5 | Are Decision Cards and priorities preserved? | Yes in component proof: exact proposal/priority revisions and evidence are preserved; Decision Cards derive from exact source. Active /run projections require controlled regeneration/reconciliation. |
| 6 | Are Action Evidence / audit history preserved? | Yes; exact row/ID/schema digests and canonical per-action hash chains pass. Bootstrap writes its own separate canonical sidecar. |
| 7 | Are current and future Learning Records preserved? | Current count is honestly zero. All-table comparison and nonzero fixtures prove future Learning Records are included automatically. |
| 8 | Are provider identities recoverable without exposing secrets? | Paths, named permissions, encrypted recovery and portable OAuth bindings are defined; 11 required source-host reads pass. New-host reads and owner decryption remain required. |
| 9 | Does restored OptiBrain start with consequential writers OFF? | Yes by policies, final env overrides and masks; component fixtures verify closure. Full OS boot still requires a drill. |
| 10 | Are stale jobs prevented from executing? | Queued state is retained as history; all business/observation scheduler services/timers and persistent workers remain masked. No replay grant is generated. |
| 11 | Is Caddy/reverse proxy reproducible? | Reviewed source and hashes, private loopback configuration and validation are automated. Public TLS/Access testing belongs to later cutover. |
| 12 | Are systemd services/timers reproducible? | Yes; 44 reviewed definition/helper files plus safety overrides are installed and hash/syntax checked. Only apps and verified backup pair may start. |
| 13 | Are backups automatically configured? | Yes on the target, including current AGE/R2/upload/readback and preserve-existing policy; a fresh encrypted target backup is a mandatory readiness gate. |
| 14 | Can migration be validated before DNS cutover? | Yes via loopback Caddy and SSH tunnel, exact-state checks and provider GETs; no DNS mutation adapter exists here. |
| 15 | Can we roll back to the old VPS? | Prepared exact DNS before-state/host/generation rollback; freeze both hosts and reconcile any new intake/effects before switching back. Traffic rollback is not tested today. |
| 16 | Can the old VPS remain a fallback? | Yes; retain intact/frozen, starting recommendation 14 days with review after 7. No automatic termination. |
| 17 | Can a future data volume be mounted cleanly? | Yes; choose --data-root /srv/optibrain-data on a separately provisioned mounted disk. Existing paths use owned-generation bind mounts; no live paths moved today. |
| 18 | Will moving to a new VPS lose any accumulated learning? | No expected loss when exact snapshot verification and final immutable-history sync pass; readiness fails closed on loss. No actual migration has happened. |
| 19 | Is another foundation phase required? | No. Existing universal evidence, learning, authorization and recovery architecture are reused. |
| 20 | Once a new VPS is purchased, what exact first command should the owner run? | sudo bash /recovery/toolchain/ops/rebuild/bootstrap.sh restore --manifest /recovery/toolchain/docs/rebuild/current-host-manifest.json --catalog /recovery/catalog.json --archive /recovery/recovery.tar.gz --generation latest-verified --migration (after the trusted private recovery packet is transferred as described in bootstrap.md). |

## Tooling release boundary

This change adds non-runtime rebuild tooling/docs and tests; application API/code and current production recovery remain unchanged. Existing successful main validation triggers an API deployment workflow, so the tooling acquisition pin uses the CI-verified PR revision. This mission does not merge through an uncontrolled production deployment. A later controlled merge must retain current authority and distinguish tooling publication from an application deployment.

Sanitized [mission Action Evidence](mission-action-evidence.json) preserves technical rationale/readbacks and explicitly labels the historical auth-cache exception. Future target operations record canonical envelopes before adapters execute.
