# PR133 blocker recovery

AUDIT EVIDENCE — CURRENT RELEASE/RECOVERY TRUTH. **PARTIAL**: the release, closed-policy service health, matching recovery and G004 are verified. G001 still requires natural collection evidence. **RED 1; PARTIAL-CONTROLLABLE 0.** No new foundation phase is required.

This report supersedes only the current-release metadata of the historical [Phase37 report](../phase37-evidence/final-report.md). Its historical bytes and all release receipts remain preserved. The [machine-readable report](final-report.json) records the same effective truth. The canonical production authority remains `/var/lib/optibrain/releases/current.json`.

## Root cause

`opticable-lifecycle-internal.service` invocation `c74e4e47eb7e42b3a073c97834a1daba` failed under production SHA `205b217546372dfd37850da7721d9bba61a0746a`, API **1.28.0**. This predates PR133 deployment.

At **15:01:36.911085 UTC**, the existing `--stop both` workflow wrote the canonical schema-1 OFF mutation policy. Its internal stop closes authority before disabling the timer. A timer invocation started during that interval; systemd's start log is **15:01:36.936640 UTC**. The runner rejected the valid OFF policy before initializing its lock, state, journal or provider work. This is an existing OFF-state handling defect triggered by release shutdown, not a Business/Marketing collection failure or malformed cache.

The original journal contains only `Internal lifecycle stopped: ValueError`: the installed launcher deliberately suppresses the message and traceback. An offline reproduction with the captured policy and fake provider reconstructs:

```text
real_internal.py:138, Engine.__init__ -> lc.read_policy()
lifecycle_control.py:95, read_policy
ValueError: Lifecycle requires strict scoped mutation policy
```

Classes: **A** existing production handling defect; **C** intentional closed authority state; **F** release shutdown/timer race. Installed immutable runtime/source pins identify the baseline. The installed launcher and policy parser hashes match production 205b217, PR133 candidate c22d409 and merged d07c022. PR133 changes only an observation error description in the caller; it does not fix this rejection.

Root-private evidence, complete systemd properties, exact/bounded journals, policy before-images, hashes and offline reproduction are retained under `/var/lib/optibrain/pr133-release-recovery` and `/home/optibrain/pr133-release-recovery-evidence`.

## Fix and release

PR133 already fixes the failing path: **NO**. Additional hotfix: **YES**.

[PR134](https://github.com/yboucher97/opticable-api-platform/pull/134), patch `a7c14be5319a3cc511474f4301dba719621fedba`, makes the verified launcher return `DISABLED` with zero reads/effects for the documented OFF policy, before importing lifecycle/provider code. The transport authority check is unchanged. Runtime trust failures and policies outside the recognized closed contract still fail closed.

The hotfix passed [exact-head CI](https://github.com/yboucher97/opticable-api-platform/actions/runs/37486661153) and merged as **`0d320d5a98575f5fed62f794342881ef613433b4`**. [Exact merged-main CI](https://github.com/yboucher97/opticable-api-platform/actions/runs/37486868312) passed; its tree equals the tested patch. Focused, release-preservation and post37 checks: **66 tests / 58 subtests**. Full network-blocked regression: **1,634 tests / 1,339 subtests**, zero failures/errors/skips/network attempts. Documentation contracts passed.

A fresh exact-SHA authorization was generated through [deployment guide step 5](../OPTIBRAIN_DEPLOYMENT_GUIDE.md) in the user-authorized manual root session. The old expired authorization is preserved. After failure evidence, reproduction, tested next executable, idle/closed prerequisites and fresh local/off-host rollback verification, only the internal systemd failed latch was cleared. This neither executed a job nor changed authority. The existing guarded gate then deployed the approved hotfix merge SHA. **API 1.29.0 is live.** Both runtime manifests and the reviewed sampler come from that same SHA; the preserving helper's `--activate` was not used.

## Service, timers and authority

Before: **FAILED**. After: **INACTIVE/DEAD following successful controlled CLOSED-policy execution**. Installed dry-run and one actual systemd invocation returned `DISABLED`, zero reads and zero effects. Successful invocation `1e524b129084472b906d3162cd9a902f` completed at approximately **15:27:16 UTC**; its exact journal is retained. Systemd unloaded the inactive unit afterward, so current properties no longer retain invocation timestamps; journal completion proof remains available.

Both existing scoped timers remain **INACTIVE/DISABLED**. Cadence is unchanged. Both authority families remain **CLOSED**. Original policies, 12 internal/4 customer scopes, cutoffs and expiries are retained in the immutable pre-deployment snapshot. Internal/customer effect inventories remain **2 / 12**, unchanged. No source-pin update or capability grants execution authority.

The Manager view is readable locally and correctly reports **STALE**, retaining its **14:56:23 UTC** projection. Anonymous Manager/automation reads return 401; the legacy writer route returns 403. No owner token was fabricated or interactive owner login claimed.

## G001 / G002 / G003

| Gap | Current classification | Evidence and limit |
|---|---|---|
| G001 | **RED — WAITING NATURAL VERIFICATION** | Fixes are deployed and regression proves fair reserved Marketing/recurring budgets, explicit states/source dates, last-good retention, partial coverage and classified errors. The normal lifecycle requires enabled internal authority before observation. A disabled execution proves service containment, not natural Business/Marketing collection. |
| G002 | **GREEN — RESOLVED** | Deployed source equals the tested tree. Missing Deals/module yields UNKNOWN/HOLD; explicit complete present empty lists establish verified empty; positive collisions remain; partial/failed/stale inputs never establish negative clearance. No claim of a naturally empty provider inventory is made. |
| G003 | **GREEN — RESOLVED** | Installed sampler SHA256 `31e2c36ea7a5ce1af0c6246529ba8c1fcde12a84ea17f78a1074ff6a43917f29` matches the release. RUNNING, COMPLETED_SUCCESS, FAILED, TIMED_OUT, NEVER_RUN, STALE_COMPLETION and UNKNOWN are tested. RUNNING plus exit=0 remains RUNNING. The live sampler expects five timers while scoped authority is closed and reports their health OK. |

## Matching recovery and G004

Generation **`20261006T152813Z`** matches production SHA `0d320d5a98575f5fed62f794342881ef613433b4` and API **1.29.0**. Local archive `/var/backups/optibrain/optibrain-backup-20261006T152813Z.tar.gz`, SHA256 **`7907b9a6887f78944a97b1c53f9cf37b486cda25202348a28581c3fa5d6b6d9e`**.

Encrypted R2 object `backups/2026/10/06/20261006T152813Z.tar.gz.age`, ciphertext SHA256 **`c2afec6310b7eea4610479ec395810a89d9aae5d73b8ee0370552ca3d64e3eb9`**, independently downloaded and hash-verified at **15:31:18 UTC**. The owner private AGE identity was not used. Ciphertext verification and isolated plaintext restore are separate proofs; owner offline decryption was not performed.

Isolated prepared-target restore passed: **1,876 files, eight SQLite stores, 16 masks**, retained Manager/Optimization tables and unchanged effect inventories. Restored internal/customer/conversion authority is **OFF**, with configured conversion destinations retained. Exact source was cloned from the verified complete-history bundle. This proves archive/state restoration; no replacement OS/service boot or DNS cutover was performed.

**G004 CLOSED / GREEN**: one matching production/API/recovery/gap/authority aggregate is current; old Phase37 report metadata is superseded while historical receipts remain intact. **Golden UNCHANGED**: both Golden archive and receipt hashes rechecked. No archive was pruned.

## Safety and owner action

Protected records **123/123 unchanged**, independently checked before and after deployment. CRM writes **0**; Books writes **0**; Ads writes **0**; outreach sends **0**; conversion uploads **0**; authority renewals **0**; effect resets **0**. Five live databases pass integrity checks. Persistent development worker remains OFF; English real automation remains disabled; financial/Ads/outreach authority remains absent/OFF.

Only remaining owner action for these gaps: explicitly authorize repinning/resuming the original unexpired internal scopes and its existing timer under the established contract, then retain natural collection evidence for G001. This includes no authority renewal or customer-family reopening. Release approval is already complete.

Lifecycle-truth `2a90b6c83c578abd6d5bd1eb886f9758d83a024a` and preview-control-plane `75c6a2b69dcbfc28ccb4eebcedae020c1f4d1738` remain unchanged/read only, with no merge, rebase or cherry-pick. Consider lifecycle-truth separately after remaining natural verification and a new authorized integration task. **Another foundation phase: NO.**

An inherited backup growth alert remains visible; retention remediation is outside G001–G004 and no historical recovery evidence was deleted to change it.
