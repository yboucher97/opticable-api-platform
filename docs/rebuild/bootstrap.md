# One-command replacement bootstrap

RECOVERY — CURRENT SPECIALIZED GUIDE. Use a new Ubuntu 24.04 amd64 VPS with Python 3, key-based administrative SSH, internet access, and at least 8 GiB free for installation, restore and a backup verification peak. The planner raises that minimum for larger recovery archives. A 250–300 GB data volume is optional; if provided, mount it at `/srv/optibrain-data` before running bootstrap. The bootstrap does not mount an unknown device or format a disk.

Prepare a private recovery packet on the owner's trusted device: selected verified recovery/catalog plus the reviewed toolchain checkout. AGE's private identity remains on that device. Transfer the packet to root-owned `/recovery` with mode 0700; recovery archive and catalog must be root-owned 0600. Keep the existing provisioning admin's SSH key available. No production host key is copied.

The exact repository-equivalent first command on the replacement is:

```bash
sudo bash /recovery/toolchain/ops/rebuild/bootstrap.sh restore --manifest /recovery/toolchain/docs/rebuild/current-host-manifest.json --catalog /recovery/catalog.json --archive /recovery/recovery.tar.gz --generation latest-verified --migration
```

The manifest/toolchain path and every parent must be owned by root and unwritable by group/others; mutation commands reject an untrusted manifest path. The packet's toolchain must be the exact reviewed PR/release, not an arbitrary working tree. Alternatively, [launch.sh](../../ops/rebuild/launch.sh) obtains a SHA- and archive-hash-pinned toolchain from GitHub using Python before Git exists. Verify the launch script hash on the owner device, then run `sudo bash /recovery/launch.sh EXACT_TOOLCHAIN_SHA EXACT_CODELOAD_ARCHIVE_SHA256 restore --catalog /recovery/catalog.json --archive /recovery/recovery.tar.gz --generation latest-verified --migration`. The final release acquisition receipt supplies actual hashes. No unaudited package installation occurs before the canonical Python audit is available.

That one invocation claims an empty replacement, creates denial policies/masks, installs required packages and pinned Node 22.23.3, creates named users/groups/directories, stages and validates recovery, installs exact application source/dependencies, restores permissions, installs reviewed units/helpers/log retention, mounts verified durable state, resets release/approval pins, validates private Caddy and firewall/SSH, boots contained services, checks knowledge/audits/providers and verifies a fresh encrypted off-host backup. It ends with `/var/lib/optibrain-rebuild/result.json` and a concise status. It cannot change DNS or enable customer automation.

Re-running the same command verifies a completed target without replaying restore. Interrupted steps retain evidence and staging; matching complete stages are reused. Unexpected partial staging or changed managed content fails closed with its specific blocker. No force/overwrite option exists. A different generation uses [final synchronization](migration.md), not a casual restore rerun.

The current VPS is intentionally refused before host adapters execute, even if someone creates a fresh-target marker. Read-only inspection/planning is safe here:

```bash
sudo python3 -B ops/rebuild/cli.py inspect --output /PRIVATE/host-inventory.json
python3 -B ops/rebuild/cli.py plan --catalog docs/rebuild/recovery-catalog.json
```

Codex/npm caches, old virtual environments and historical worktrees are not restored. The persistent development worker is OFF. The source is retrieved from the selected verified Git bundle or exact public repository SHA; frozen Python requirements and npm lock are rebuilt, rather than copying old interpreter environments.

Owner interactions are normally three checkpoints: supply the new VPS/access, decrypt and transfer the recovery packet using the offline identity, and approve the final cutover report. Provider consent/MFA is needed only if a portable binding fails its read test. Native Forms writer settings and Cloudflare Access behavior retain their owner/provider boundaries.
