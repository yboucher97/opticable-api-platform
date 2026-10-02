# Canonical recovery guide

RECOVERY — CURRENT SPECIALIZED GUIDE. Begin with [onboarding](OPTIBRAIN_CODEX_ONBOARDING.md); [configuration](OPTIBRAIN_CONFIGURATION_INVENTORY.md) identifies every owner/secret boundary. Recovery starts with writers and schedulers OFF. Preserve provider-effect claims, journals and newer credential rotations. Never infer permission to execute from an old approval, backup, snapshot or successful health response.

## Golden recovery layers

| Layer | Verified reference / role |
|---|---|
| Git | `recovery/phase14-complete-pre-phase15-20261002` → `5332da6da8dc6db72bc21914868d81171a99b470` |
| Local application/state | `/var/backups/optibrain/optibrain-backup-20261002T123816Z.tar.gz`; plaintext SHA256 `ff91b86f3a4f9491158c7e7bcd067ca9cb06bb29b6a424d22dc0c9d31c82d7ba`; eight online SQLite stores |
| Encrypted R2 | bucket `optibrain-recovery-prod`, key `backups/2026/10/02/20261002T123816Z.tar.gz.age`; ciphertext SHA256 `36960a90e9d3348266485d08bd0be4d737cf6654ff123a2541a89f856375e84c`, 279401970B; independent downloaded-byte match PASS; indefinite golden hold |
| Infrastructure supplement/history bundle | `/var/backups/optibrain/phase15-infrastructure-20261002T123816Z/`; `golden-source.bundle`, `infrastructure.tar.gz`; encrypted R2 sibling suffix `.infrastructure.tar.gz.age` and `.evidence.tar.gz.age`; independently read back. Supplement is optional recovery evidence, not a replacement-OS dependency. |
| OVH snapshot | **Owner CONFIRMED** `OPTIBRAIN-GOLDEN-PHASE14-PRE-PHASE15-20261002`; supersedes preflight’s earlier PENDING OWNER observation. Fast whole-VM rollback insurance. No destructive restore was tested. |
| Clean reconstruction | Fresh Ubuntu users/packages/venvs/units + golden state restored and isolated API boot tested; [evidence](phase15-rebuild-evidence.md) gives measured scope/limits |

Golden receipt: `/var/lib/optibrain/phase15-preflight-evidence/golden-state-receipt.json`; Phase15 evidence: `/var/lib/optibrain/phase15`. Treat owner snapshot confirmation as authoritative; do not waste incident work repeating completed preflight. Hold golden files/objects, complete-history bundles and immutable R2 `business-effects/v1/` independently of local retention.

## Full VPS loss / fresh replacement — ENGINEER, PROVIDER ADMIN and RECOVERY-ONLY

1. Acquire a **new** Ubuntu24.04 LTS amd64 host under OVH owner/admin authority; record incident/replacement UTC times and exact VPS identity. Keep old host/snapshot intact. Do not reinstall or restore over production as a drill.
2. Secure the base OS: patch supported packages, key-only SSH, named engineering account/sudo, firewall TCP22/80/443, application ports loopback, no public DB/admin ports. Obtain host-specific network/storage configuration from OVH; do not blindly copy old netplan/fstab/SSH private identity. Keep provider egress blocked during state restore/contained boot. The drill used fresh debootstrap Ubuntu userland with separate PID/mount/network namespaces; an actual replacement also needs its own kernel/firewall/systemd PID1.
3. Restore the repository from GitHub or verify/clone `golden-source.bundle` on a trusted staging device (`git bundle verify /recovery/golden-source.bundle`, `git clone /recovery/golden-source.bundle /opt/opticable-api-platform`). Check out the exact reviewed recovery source, normally latest validated main; golden tag is the fallback. A source archive is also embedded in the app backup. Never fetch-and-run unreviewed root installers. Give Git metadata to the engineering account; reviewed code/dependency trees are immutable to service users.
4. Install prerequisites while no restored application is running. Supported baseline: Ubuntu24.04, Python3.12, systemd255, SQLite3, Git, AGE1.1+, Caddy2.6+, Node22 LTS with bundled npm. Use Ubuntu packages: `python3 python3-venv python3-pip python3-boto3 git sqlite3 age caddy curl ca-certificates openssl iproute2 systemd systemd-sysv sudo rsync tar xz-utils logrotate openssh-server util-linux`. Production also uses qemu-guest-agent/ufw; a namespace drill does not need guest hardware. Capture package versions. No broad/minor OS pin is required; frozen Python requirements/npm lock and exact reviewed source are required.

   Node reproducible tested artifact: `https://nodejs.org/dist/v22.23.3/node-v22.23.3-linux-x64.tar.xz`, SHA256 `df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de`. Verify against official SHASUMS256.txt before extracting to `/usr/local` with `--strip-components=1 --no-same-owner`; keep that tree root-owned. Preserving the tarball's numeric owner can give a local engineering user control of root helper parents; bootstrap rejects it. Other supported Node22 patch releases need validation. Node20+/future upgrades are not silently accepted as the tested contract.
5. Create the explicit fresh-target marker only on the replacement: `sudo install -m0600 /dev/null /etc/optibrain-rebuild-target`. From the reviewed repository run:

   ```bash
   sudo python3 ops/phase15/bootstrap.py --target-root / --mode check
   sudo python3 ops/phase15/bootstrap.py --target-root / --mode prepare
   sudo python3 ops/phase15/bootstrap.py --target-root / --mode verify
   ```

   PREPARE creates named service users/groups/directories/modes (including root-only admin audit directory and the /usr/bin/node adapter for the official /usr/local Node installation), reviewed units/helpers/proxy, fresh universal OFF policy and a final recovery EnvironmentFile. It never starts anything; all five timers, TEST service and six retired units are masked. It refuses existing production control/journals/releases and never overwrites their state. CHECK reports missing prerequisites, does not install packages. For a disposable OS root use its explicit canonical absolute `--target-root`; never point it at a live host by convenience. A failed/partial prepare requires inspecting the isolated target; no force-overwrite mode exists.
6. The reviewed checkout and its Git metadata belong to engineering: `sudo chown -R optibrain:optibrain /opt/opticable-api-platform` before creating app venv links. This is required because the fixed backup helper invokes Git as `optibrain`; a root-owned clone fails Git's ownership check. Service users cannot edit the checkout. Prepare fresh root-owned immutable application environments outside that checkout, using the exact chosen source requirements:

   ```bash
   sudo python3 -m venv /opt/optibrain-releases/RECOVERY_SHA/venv
   sudo /opt/optibrain-releases/RECOVERY_SHA/venv/bin/python -m pip install -r apps/workflow-api/requirements.txt
   sudo python3 -m venv /opt/optibrain-releases/RECOVERY_SHA/pdf-venv
   sudo /opt/optibrain-releases/RECOVERY_SHA/pdf-venv/bin/python -m pip install -r apps/password-pdf-service/requirements.txt
   ```

   Replace `RECOVERY_SHA` with the actual exact SHA. Link each app `.venv` to its new environment; do not reuse the old machine’s venv as the clean proof. Rebuild Omada from `package-lock.json`: `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci --ignore-scripts`, then `npm run build`. Node/npm must be on PATH. Browser/Electron binaries are not required for contained HTTP health; provider/browser execution stays retired. Build the Worker using its lock/CI only if edge reconstruction is required; VPS loss does not erase Cloudflare’s running Worker/queues/KV.
7. Recover secrets through protected backup or explicit owner/provider channels. Owner decrypts R2 on an **offline/trusted owner device**: first verify ciphertext hash/size, then `age -d -i /OWNER_OFFLINE_PATH/identity.txt -o /TRUSTED_PRIVATE_PATH/recovery.tar.gz /TRUSTED_PRIVATE_PATH/recovery.tar.gz.age`; verify plaintext SHA/archive. Transfer only the verified plaintext archive through an approved encrypted channel into root-only staging. Never copy the private AGE identity to the VPS, chat, Git, logs or an automated worker. Provider MFA/ownership/secret reentry is a documented manual dependency, not a bootstrap secret.
8. Restore approved app state to the prepared target, with provider networking blocked and all services off:

   ```bash
   sudo install -d -m0700 /recovery/staging
   sudo python3 ops/phase15/restore.py --archive /recovery/optibrain-backup-20261002T123816Z.tar.gz --sha256 ff91b86f3a4f9491158c7e7bcd067ca9cb06bb29b6a424d22dc0c9d31c82d7ba --target-root / --workspace /recovery/staging
   sudo python3 ops/phase15/bootstrap.py --target-root / --mode verify
   ```

   The restore validates archive traversal/member/file hashes/format/all eight DBs before writing. It restores explicit app/root state/config paths, maps ownership by **name**, preserves fresh safety override/masks and excludes old execution authorizations, SSH identities, live-unit enablement and expendable browser cache. Core online `database/automation.db` replaces WAL/SHM. Golden version baseline has a documented normalization into `/etc/optibrain/protected-runtime-versions.json`. It refuses a second restore/replay into the target. Archive-bearing temporary staging is removed; root-only aggregate receipts remain. Do not manually extract a backup over a live `/`.
9. Validate permissions and eight DB integrity results, exact source, unit syntax (`systemd-analyze verify`), Caddy syntax (`caddy validate --config /etc/caddy/Caddyfile`), recovery override and masks. Rebind the root registration’s candidate SHA/source hashes using reviewed release tooling; leave `business_actions_enabled:false` and every execution approval pin null. Use `sudo python3 ops/phase15/rebind_registration.py --target-root / --sha RECOVERY_SHA` on the marked recovery target (replace the placeholder with its exact checkout SHA). It clears all execution pins and updates only the exact-release env SHA. New source pins must be reviewed, not copied blindly from the old release. Schema constructors/additive setup are tested on isolated copies; preserve durable journals rather than recreating them.
10. Boot contained app/support services with recovery override and provider egress blocked. Never enable timers to test liveness. Confirm version/health, unauthorized API/owner denial, no writer families, no dev worker. The reusable [isolated boot probe](../ops/phase15/isolated_boot.py) uses only an ephemeral local key, no provider credentials; run it inside the documented offline namespace rather than against production. Read-only Today/system-health rendering is validated using synthetic identity/provider fixtures; no production owner impersonation.
11. Reconcile provider effects **newer than backup** through reads before any writer. Preserve/query locked R2 claims/results; inspect ambiguous intent/readback/action and consumed approvals, receipt/checkpoint/native watch identity and current credential binding. Do not replay queued business actions, reset journals, auto-convert identities, blindly retry Mail/Sign or move cursors. Provider truth and independent claims override stale local state. All real writers remain OFF; any future TEST/real activation needs an exact explicit mission.
12. Verify fail-closed auth, root kill/canary false, protected123 unchanged, source pins and all containment surfaces. Use owner Access login, not a forged JWT. Confirm native Forms integrations remain disabled through the owner/admin UI; supported APIs cannot prove that setting. Rotation/reconnect starts with minimum-scope GETs; distinguish 401/403/throttle/outage.
13. Verify local health/readiness, all DB checks and a contained local backup; restore R2 scoped credentials/public recipient and prove **independent downloaded-byte hash** of a new generation. Keep golden holds and create-only claims. Re-enable only backup/upload timers when their recovery prerequisites pass. Leave business/TEST timers and internal automation off until reconciliation and incident scope explicitly permit read observers.
14. Validate current off-host recovery and owner decryptability without uploading the private identity. Restore external access/settings only when required; Cloudflare/GitHub secret metadata cannot recover secret values without the owner.
15. Prepare DNS/TLS/proxy/Access cutover: retain exact old record/IP/TTL/Access audience/issuer/policies and source receipt. Validate contained new origin TLS/route denial and human auth before routing traffic. Change only the reviewed origin/DNS target under incident authority; verify propagation, certificate chain, public health, Access login and origin denial. Roll back exact DNS/origin on regression; keep writers off and avoid two schedulers. This production cutover is **DOCUMENTED**, not proved by the isolated drill.
16. Reconstruct OVH direct references via protected env/owner reissue, gateway secret bindings through its owner if lost; use GET identity before any infrastructure action. Correct VPS/service/region matters more than copying old IPs. OVH API outage need not stop local restore; use owner Manager/support.
17. Only later consider approved observers/writers. Removing `99-rebuild-safety.conf` or unmasking schedules is an explicit recovery milestone after evidence, never an automatic install step. Real automation/canary remain OFF after Phase15.

## Incident routing

| Scenario | Safe first action / recovery boundary |
|---|---|
| Application process failure | Inspect service result/logs and policy; restart only affected contained service. Check health/auth/source; preserve DBs. |
| Bad deployment | Guarded code/config/venv rollback; preserve journals, claims and rotated credentials. Ordinary gate requires forward ancestry; later rollback needs reviewed incident staging. |
| Database corruption | Stop affected writers/observers; preserve corrupt copy + WAL/SHM for evidence; restore verified online copy in isolation, integrity-check and reconcile newer effects. Never delete DB as first step. |
| VPS loss/full host replacement | Follow deterministic steps above; Git bundle + approved backup suffice without snapshot. |
| Credential loss/rotation | Owner/provider minimum-scope reconnect; preserve binding/old reference as protected evidence, verify reads, clear old execution authority. No secret output. |
| Cloudflare/R2 access loss | Owner MFA/ownership recovery; preserve local archive and off-host claims. Do not create a replacement namespace to bypass missing claims. Fail closed on uncertain effects. |
| Provider API outage / Zoho unavailable | Keep safe read-only API available, mark freshness/readiness; backoff, preserve cursor/evidence. No writes/fallback automation to “repair.” |
| DNS/TLS failure | Compare DNS/proxy/cert/Access source of truth; validate origin first, exact reviewed routing repair. No application DB restore implied. |
| GitHub unavailable | Verify/clone complete-history bundle or embedded exact source archive; no new CI-less ordinary deployment authority. Recovery source review under incident scope remains required. |
| OVH API unavailable | Continue local contained recovery; owner Manager/support can inspect. Do not infer host loss or perform destructive requests. |
| OVH host incident | Owner/admin verifies exact VPS; acquire clean replacement or separately authorize snapshot rollback, always writers-off and newer-effect reconciliation. |

## Snapshot role

The pre-Phase15 snapshot is **FAST WHOLE-VM ROLLBACK INSURANCE**, useful for an authorized OS/filesystem/dependency incident when its integrity is trusted and writers can be disabled before traffic. Clean rebuild is safer after compromise, unknown host state or a new supported OS. Snapshot restore reverts credentials/journals/scheduler state while providers and R2 claims remain newer. Isolate the restored VM, force fresh OFF policy/masks/recovery env, quarantine old approvals and reconcile before traffic/observers. Validate source/DB/auth/backup/TLS then owner cutover. Never test a destructive production snapshot restore in this mission.

## RPO / RTO and key custody

RPO **ASSUMPTION**: scheduled daily online archives, normally off-host within30–45min of the backup; choose the latest independently verified generation. Worst successful schedule interval is about24h plus upload delay; outage/failure can increase it. Exact golden restore point is `20261002T123816Z`; it is not a guarantee of current provider-state RPO. Independent effect claims reconcile provider effects newer than a local generation; they do not recover missing receipt chronology. Timers/readback freshness must be inspected.

RTO **MEASURED** components and full isolated drill elapsed appear in rebuild evidence; fresh package installation + restore + contained boot were actually run. Full traffic/owner/provider-ready RTO is **UNKNOWN**; no guaranteed restoration time. An incident plan may estimate hours after host/key/credentials are available, but owner MFA/decryption, provisioning, provider outages and DNS/TLS delays are independent manual/external intervals. The drill is Ubuntu userland reconstruction, not destructive production failover or a new kernel/OVH provisioning test.

Owner verifies identity locally with `age-keygen -y /OWNER_OFFLINE_PATH/identity.txt` and compares only the public recipient/hash with `/etc/optibrain/age-recipient`; never display the identity. Existing owner decryption/plaintext/archive proof is already PASS. Safe receipts contain archive/ciphertext hashes, sizes, generation, DB results and timestamps, **no secrets**. Never regenerate/replace the identity simply to run a drill.
