# Phase15 final report

AUDIT EVIDENCE. **PHASE15: PASS** — clean reconstruction succeeds without historical conversations, original builder memory or the OVH snapshot. The current root release/closure receipts bind the exact merged source, deployment time and final live checks. This self-containing Git report references those SHA fields; the generated full report at `/home/optibrain/phase15-evidence/PHASE15_FINAL_REPORT.md` includes their literal final values.

## Release and invariants

| Field | Result |
|---|---|
| Final production SHA / local main / remote main | Same exact release SHA: `/var/lib/optibrain/phase15/closure.json` → `production_sha/local_main/remote_main`; current deployed receipt `/var/lib/optibrain/releases/current.json` |
| API |1.12.0; source/version/registration/receipt matched |
| Protected records / mutations |123/123 unchanged,0 protected mutations; before/after GET-only comparison |
| Real customer sends / Books writes |0 /0 |
| Real automatic writes / REAL_CANARY_ALLOWED |OFF /FALSE |
| Persistent Codex worker |OFF; six retired units masked/inactive |

## GOLDEN RECOVERY BASELINE

Git tag `recovery/phase14-complete-pre-phase15-20261002` → `5332da6da8dc6db72bc21914868d81171a99b470`. Local golden `/var/backups/optibrain/optibrain-backup-20261002T123816Z.tar.gz`, SHA256 `ff91b86f3a4f9491158c7e7bcd067ca9cb06bb29b6a424d22dc0c9d31c82d7ba`. R2 `backups/2026/10/02/20261002T123816Z.tar.gz.age`, SHA256 `36960a90e9d3348266485d08bd0be4d737cf6654ff123a2541a89f856375e84c`,279401970B; independently verified/held. OVH snapshot `OPTIBRAIN-GOLDEN-PHASE14-PRE-PHASE15-20261002`: **CONFIRMED**, never destructively restored. Clean rebuild **PASS**. Infrastructure supplement/complete-history golden bundle remain held; latest exact-source bundle is included in post-release app backup.

## AUTHORITATIVE DOCUMENTATION

Ten primary current documents: [onboarding](OPTIBRAIN_CODEX_ONBOARDING.md), [architecture](OPTIBRAIN_ARCHITECTURE_BLUEPRINT.md), [master runbook](OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md), [operator](OPTIBRAIN_OPERATOR_GUIDE.md), [deployment](OPTIBRAIN_DEPLOYMENT_GUIDE.md), [recovery](OPTIBRAIN_RECOVERY_GUIDE.md), [configuration](OPTIBRAIN_CONFIGURATION_INVENTORY.md), [runtime/health](OPTIBRAIN_RUNTIME_CONTRACT.md), [state/identity](OPTIBRAIN_STATE_CONTRACT.md), [index](OPTIBRAIN_DOCUMENTATION_INDEX.md). Supporting current security control and two machine registers add precise coverage without competing deployment procedures.

Every140 documents/README/docs JSON classified: AUTHORITATIVE CURRENT11, RECOVERY1, SECURITY / CONTROL1, AUDIT EVIDENCE70, HISTORICAL48, SUPERSEDED9, OBSOLETE0, UNKNOWN0. Conflicting current instructions0. History is preserved with purpose/superseder and clear precedence; exact original archives/JSON retain their content.

## CONFIGURATION

Configuration sources identified70; secret references59, no values. Undocumented P0/P1 config0; secrets committed/logged0. Sources cover code/env/root policy/registries/state, units/drop-ins/helpers/proxy/host infrastructure, Cloudflare/GitHub/Zoho/OVH provider settings, backup/recovery/feature flags. Systemd EnvironmentFiles/last recovery override and conjunctive root kill precedence explicit.

Owner-held dependencies: offline AGE device/identity; OVH, Cloudflare, GitHub, Zoho owner/admin/MFA; native Forms UI; domain registrar ownership/billing. Registrar identity detail remains documented P2. OVH architecture **BOTH**, `ovh-ca`, `vps-214ba8cd.vps.ovh.ca`, service41299869, `os-bhs6`, VPS-2 2027. Direct credential references in root API env; gateway bindings in connector; core non-GET denial versus gateway explicit human confirm/reason/audit documented. Infrastructure mutations0.

## CLEAN REBUILD

Environment: fresh debootstrap Ubuntu24.04 amd64 userland, new apt/Python/Node/npm installs, separate filesystem and mount/PID/network/IPC namespaces. Blank/fresh enough **YES** for application/OS-userland reconstruction. Repository-only bootstrap **PASS**; prerequisites **PASS**; named identities/directories **PASS**; configuration **PASS**; golden state restore **PASS**; eight DB integrity checks **PASS**; safety defaults **PASS**. No source/dependency/unit assumption was inherited from the live installation. Current source + approved app archive suffice; no snapshot/infrastructure tar/private AGE identity needed.

## ISOLATED APPLICATION BOOT

API boot/version/health **PASS**,1.12.0. Auth fail-closed **PASS** with actual configured/missing-key HTTP checks. Real writers, Mail, Books, Sign **OFF**; TEST runner **OFF initially**, legacy/dev mutators disabled. Five timers + TEST service + six retired units masked. API process has no provider credentials, loopback only/no route, guard external attempts0; provider mutation attempts0, OVH mutation attempts0. PDF/Omada fresh support health/containment **PASS**;13 application unit definitions and Caddy syntax **PASS**. HTTP200 proves liveness/rendering, not full provider/business readiness.

## FRESH CODEX / ENGINEER ONBOARDING

16 scored topics,10 carrying safety-critical boundaries. Initial14 correct/1 incomplete/0 incorrect/1 ambiguous; final16 correct/0 incomplete/0 incorrect/0 ambiguous. Safety-critical incorrect answers0; original OVH ambiguity closed. Initial understanding3m43s, affected recheck2m11s; total5m54s. Verdict **PASS**. Test subject received only onboarding/repository, no prior conversation or phase history. [Validation](phase15-onboarding-validation.md) records grading/source/runtime comparison and limitations.

## OPERATOR GUIDE

Today workflow **PASS**; OK/DEGRADED/ACTION REQUIRED/UNKNOWN interpretation **PASS**; emergency stop **PASS**; local/off-host backup verification **PASS**; current SHA lookup **PASS**; owner/engineer/provider-admin/recovery boundaries **PASS**; OVH/snapshot guidance **PASS**. No first-line data deletion, queue purge or unverified retry instruction.

## DEPLOYMENT

Canonical path: `sudo /usr/local/sbin/opticable-api-deploy-root EXACT_SHA`, exact PR-head/main CI and root receipt. Historical deployment entry points superseded/contained; nine superseded documents explicitly routed to current procedures. Release receipt **PASS**; rollback **PASS**, preserving active journals/newer credentials/independent claims. Later rollback uses forward revert + same gate; application restore, whole-VM snapshot and fresh rebuild are distinct.

## RECOVERY

Fresh-host procedure **PASS**; golden off-host backup **PASS**; current off-host generation/hash in closure/upload receipts. Owner AGE **DOCUMENTED**, private identity offline. Writers-off restore **PASS**; provider reconciliation-before-writers **PASS** as enforced/documented recovery invariant; actual-loss provider reconnect is not claimed tested. New-OS userland rebuild **PROVEN**; new kernel/OVH provisioning/systemd PID1 **DOCUMENTED**. OVH snapshot role **DOCUMENTED**. DNS/TLS cutover **DOCUMENTED**; provider reconnect **DOCUMENTED**.

RPO **ASSUMPTION**: daily verified online archive plus normally30–45min upload delay; outage extends it, use independently verified latest generation. RTO **MEASURED COMPONENTS**: preparation/restore/rebind25.995s (restore25.485s), API checks6.569s, supporting boots5.937s, final regression39.137s. Full traffic/provider-ready RTO **UNKNOWN**; owner decryption/MFA/provisioning/download/DNS delays excluded. No guaranteed RTO fabricated.

## RUNTIME CONTRACT

Four long-running services: core API, PDF, Omada, Caddy. Five timer/oneshot pairs: backup, upload, receipt observer, service observer, bounded TEST reconciliation/readiness. Root services3: backup/upload/TEST runner. Canonical timers5. Listeners: public TCP22/80/443, Caddy UDP443 capability (no firewall opened), loopback8100/8000/3210/2019 and resolved53, internal DHCP68, transient manual Codex loopback brokers. Unexplained listeners0; retired worker remains absent. Input/output/provider authority/dependencies/locks/timeouts/restarts/kills/recovery role specified.

## STATE CONTRACT

Active DBs5: automation, form receipts, intake, service events, autonomy/actions. Historical DBs3 backed/read-only. Other critical stores: protected/Test registries and identity crosswalk, root action/ownership/reconciliation evidence, immutable R2 effect claims, credential bindings, release/backup/upload/hold receipts and current Git bundle. Ambiguous ownership0. Rebuildable: display snapshots, metadata/cache, runtime samples, diagnostics/browser cache. Non-rebuildable critical: received chronology/action/approval/claim/ownership lineage; provider truth alone cannot recover it. Entity/provider/internal identities and restore ordering explicit.

## OBSERVABILITY

Soft log-growth warning **RESOLVED / BOUNDED**. Cause: retained system journal counted with app diagnostics and inappropriate128MiB combined threshold; sparse apparent lengths differed from disk consumption. App diagnostics now5×5MiB; journal512MiB/90d/2GiB keep-free, measured allocated blocks separately. App log71068B, active DB14295040B, local staging≈11.6GB; growth signalOK.14m10s observation had0 logical-byte growth; last24h16890 journal entries/2066868 message bytes. Allocation is stepwise; no linear capacity guarantee inferred. Disk80%/90% and separate growth warn/action thresholds documented. Audit/action/claim evidence not deleted.

Queue UNKNOWN **RESOLVED** through bounded GET metrics. Two independent observations: active0, DLQ129/67716B, unchanged; no consume/ack/replay/purge. DLQ now meaningful ACTION REQUIRED, retained P2 delivery investigation. Readiness model **PASS**, separates API/business/provider/backup/operator/safety/infrastructure evidence and freshness.

## REPOSITORY / DOCUMENT HYGIENE

23 clean merged obsolete local worktrees removed;25 retained, including production/main/current branch, dirty/unique history and Git-refused safe removals. Branches deleted0, history rewritten0; complete-history bundles retained. Historical evidence preserved **YES**. Transient evidence separated **PASS**: raw private logs/staging outside Git and application backup recursion; durable aggregate receipts root-only/backed. No production git-clean.

## TESTING

Focused22 tests/14 subtests; document/path/bootstrap dry-run coverage140 docs/70 configs/59 secret refs; no UNKNOWN. Actual clean reconstruction/eight-store restore/API-support boot/unit-proxy/rebuilt backup validation **PASS**. Fresh onboarding **PASS**. Final authoritative regression865 tests/760 subtests,0 failures/errors/skips/network attempts. Exact merged-release CI is bound in the root release/closure receipts. Initial drill/probe/fixture failures are recorded as closed defects in [rebuild evidence](phase15-rebuild-evidence.md); no final failure is hidden or skipped.

## CLEAN-ROOM CHALLENGE

Could OptiBrain be safely rebuilt without historical chats? **YES**. Without OVH snapshot dependency? **YES**. Verdict **PASS**. Undocumented P0 dependencies0; undocumented P1 dependencies0. Remaining P2/P3 are explicit human/provider/failover proof limits, not hidden application reconstruction requirements. [Rebuild evidence](phase15-rebuild-evidence.md) lists every discovered dependency and its fix.

## PHASE15 OUTCOME / REMAINING WORK

Rebuildability **STRONG**; documentation **STRONG**; onboarding **STRONG**; recovery **ACCEPTABLE** (contained recovery proved, real cutover/new VM not tested); operator usability **STRONG**; deployment reproducibility **STRONG**; configuration clarity **STRONG**.

P1: **NONE**. P2: investigate129 retained dead-letter deliveries without blind replay; owner record of registrar identity; separately authorized replacement-VM/DNS/TLS/provider reconnect drill if stronger full-incident RTO evidence is desired. P3: optional integrations DEFERRED — NON-CRITICAL; retain dirty/unmerged historical worktrees for deliberate later review.

**NEXT RECOMMENDED MANUAL MISSION:3 — next business-workflow development phase**, beginning with bounded delivery/exception reconciliation before considering a real canary. Do not automatically start it. Phase15 stops here; real automation/canary stay OFF.
