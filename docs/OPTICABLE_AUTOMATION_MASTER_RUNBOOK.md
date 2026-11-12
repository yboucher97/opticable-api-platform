# Opticable Automation Master Runbook

AUTHORITATIVE CURRENT. API `1.34.1`. This is the operating contract; [onboarding](OPTIBRAIN_CODEX_ONBOARDING.md) establishes precedence. [Operator](OPTIBRAIN_OPERATOR_GUIDE.md), [deployment](OPTIBRAIN_DEPLOYMENT_GUIDE.md) and [recovery](OPTIBRAIN_RECOVERY_GUIDE.md) are the only current procedures for those tasks. Historical phase instructions cannot override them.

## Standing safety state

Current NEW-host verification (2026-11-12): all 45 consequential runtime flag checks are OFF. Existing protection of the 123 records remains in force; this resource mission did not repeat provider-by-provider record parity. Safe hold-v1 receipt ingestion and the existing GET-only receipt collector remain active. Customer communications, financial/paid writes, broad business execution and uncertain historical replay stay disabled. The persistent development worker remains OFF, with retired units masked. Root kill, fail-closed authentication, exact ownership, immutable execution evidence and independent off-host claims remain mandatory. Current root policies and measured service state govern authority; older scope descriptions do not enable anything.

The current manual mission defines engineering scope. Workflow enabled state, an old approval, a successful API response or credential scope never grants provider-write authority. No current document authorizes a real canary or customer action. [Safety controls](OPTIBRAIN-SAFETY-INVARIANTS.md) apply to every host.

## Inspect and operate

Owner home: **https://optibrain.opticable.ca/v1/operator/today**. Use the owner’s Access login. Business cards lead into sales/follow-ups/quote review/projects/maintenance/approvals/exceptions. Technical health is `/v1/operator/system-health`. Private/no-store responses and source timestamps remain mandatory.

```bash
curl -fsS http://127.0.0.1:8100/v1/system/health
sudo optibrain-admin scheduler  # backup/upload pair only
sudo systemctl list-timers --all optibrain-backup.timer optibrain-phase2a-upload.timer opticable-phase9-intake-receipts.timer opticable-phase10-service-events.timer opticable-phase12-test-runner.timer opticable-lifecycle-internal.timer --no-pager
sudo optibrain-admin capacity
sudo optibrain-admin verify-latest
sudo cat /run/optibrain-readiness/status.json
sudo cat /run/optibrain-readiness/queue-depth.json
sudo cat /var/lib/optibrain/releases/current.json
sudo cat /etc/optibrain/mutation-control.json
```

[Runtime](OPTIBRAIN_RUNTIME_CONTRACT.md) lists services/timers, locks and ports. [State](OPTIBRAIN_STATE_CONTRACT.md) lists five active DBs, three archives and root registries. The root read-only inspector in onboarding privately authenticates readiness and independently compares protected record versions; it logs no credential/customer values.

API liveness, business attention, provider reads, backup freshness, auth/safety and infrastructure are separate readiness dimensions. Missing samples remain UNKNOWN. The GET-only queue sampler observes active/dead-letter backlog without consuming messages. Dead-letter backlog requires engineering reconciliation; **never replay/purge it to make health green**. Diagnostic log rotation does not prune business evidence.

## Changes and incidents

Use one focused validation path; full fake-provider regression once at the final executable release candidate, then exact-head PR/main CI. Deploy through the installed root-owned guarded gate only. The deployment guide specifies authorization receipt, immutable dependencies, rollback backup and independent post-release checks. Root-approved runbook digest repinning must preserve the previous digest; changing prose does not silently repin installed trust.

For process failure restart only the affected contained service after checking state. For code regression roll back code/config/venv, preserving journals and credential rotations. For state loss/full host loss follow recovery; never restore old journals into an active writer or restore a VM snapshot as an ordinary deploy rollback.

Provider reconnect starts with read observations, token binding, saved cursors, native notification verification and immutable effect evidence. Distinguish 401 from 403/throttle/outage; do not replace a token or move a cursor just to clear a status. Native-channel renewal and credential rotation need their own exact incident scope. No automatic failover enables the connector’s writers.

## Backup stewardship

Local `/var/backups/optibrain` contains online SQLite/state/config/source archives. `/var/lib/optibrain/phase2a` records public-recipient encryption, create-only R2 upload and independently downloaded byte hashes. Preserve every golden/recovery/audit hold and locked `business-effects/v1/` claim. Root retention tooling is dry-run first, local only: seven newest plaintext generations plus holds; two recent verified ciphertexts plus owner/golden holds. Failed/ambiguous uploads are retained. No R2 deletion is authorized. See recovery for exact golden references and offline AGE custody.


## Permanent resource and learning stewardship — 2026-11-12

Current NEW host vps-f8e9b20e, production SHA ec9a8e85095b57faf21212000652912e08093da4. Migration is COMPLETE. Keep all 45 consequential automation flags OFF and existing owner/DNS authority unchanged.

Permanent operational procedure: `/var/lib/optibrain/resource-management/MASTER_RESOURCE_RUNBOOK.txt`; owner result `/home/optibrain/optibrain-resource-learning-optimization-20261112.txt`. Owner-readable aggregate view: `/var/lib/optibrain-resource-view/daily-summary.txt`. Resource sample runs every 15 minutes, daily/weekly local reports and weekly isolated nine-store restore plus full encrypted R2 readback. Background backup/upload/restore work shares a lock and measured memory controls; core services unchanged.

Disk target60 GiB, warning50/critical35/emergency25. Preserve all unique journals, learning/owner corrections, event identities and offsite claims. Only three proven redundant verification extractions were removed after local byte equivalence and independent R2 complete-object verification; exact proofs remain in resource-management. Fourteen expanded recovery directories remain held for a separately reviewed retention decision. No R2 expiration or business data pruning is enabled. Live bind source `/var/lib/optibrain-data/generations/20261111T201316Z` is operational state, NEVER cache.

The migration notification allowance remains32/32. Separate 30-day owner-only operational email proposal (maximum2/day,6/week,30 total with24h incident cooldown) remains DISABLED pending explicit authorization. Daily/weekly local reports require no email authority. Existing outcome-based learning tests and guarded approvals remain mandatory; empty learning coverage is UNKNOWN quality.

Rollback only the new resource unit files, tmpfiles lock rule and two `zzz-resource-protection.conf` background drop-ins; daemon-reload restores prior backup/upload controls. Preserve all newer business DBs and recovery evidence. Exact rollback commands, pre-change verified configuration checkpoint, errors/fixes and tests are in the permanent resource runbook.


## Current autonomous operations authority — 2026-11-12

Current operating procedure: `/var/lib/optibrain/autonomous-operations/MASTER_AUTONOMOUS_OPERATIONS_RUNBOOK.txt`. Full owner status: `/home/optibrain/optibrain-autonomous-operations-20261112.txt`; owner aggregate view `/var/lib/optibrain-resource-view/operations-status.txt`. This section supersedes the earlier same-day pending A/B/C states.

Owner expressly approved and A retired only14 verified expanded recovery directories, reclaiming22,453,850,112 bytes, with every plaintext archive/ciphertext/R2 object preserved. B now keeps3 verified FUTURE plaintext generations and2 ciphertexts, plus all preapproval and exceptional holds; independent full R2 GET and isolated9-store restore are mandatory. No remote expiration or other historical pruning is authorized.

C is ACTIVE only for its recorded30-day owner-only trial:2/24h,6/7d,30 total with reserved CRITICAL slots and24h incident cooldown; one initial daily digest was genuinely delivered and independently confirmed in the received mailbox. Migration32/32 ledger remains unchanged. No customer recipient or unlimited/perpetual allowance exists. Daily/weekly local summaries persist beyond trial; ongoing bounded notification proposal requires new approval.

Five-minute bounded known-service repair,15-minute supported OAuth verification/renewal, daily read-only capabilities and hourly source-pinned native business observations are scheduled. Existing Service Lab read-only observer restored. Native business collection is now COMPLETE after measured safe cache warming:50 GETs, zero writes. The hourly observer permits160 calls/run and2000/day only while the verified included ZohoOne quota binding is fresh; stale/unknown plan falls back to400/day. Source timestamps and daily counters remain authoritative. All45 consequential flags remain OFF; no financial/customer/historical replay workflow was armed. Routine read-only work was enabled independently of absent/expired bundled writer authority. No new root/SSH/sudo endpoint, permission expansion, paid service, DNS change or OLD reactivation. OLD fence confirmed using existing read-only forced status only.

Exact checkpoints, holds, commands, scope differences96 VPS Zoho versus292 ChatGPT, pending provider consent, quota tests, failure fixes, current recovery proofs and configuration-only rollback are in the current operational runbook. Never restore an old notification ledger into an active sender or older business DB state as a normal rollback.

Privileged maintenance readers and the owner Mail sender load only the verified root-owned184-file package under isolated Python. The daily Sign native status read is active; queue DLQ inspection used nonleasing peek only, preserving all8 messages. Existing bound-portal Projects read works without additional OAuth scope.


## Current universal platform access — 2026-11-12

Current procedure: `/var/lib/optibrain/universal-platform-access/MASTER_UNIVERSAL_PLATFORM_RUNBOOK.txt`; full owner matrix/report: `/home/optibrain/optibrain-universal-platform-access-20261112.txt`; aggregate view: `/var/lib/optibrain-resource-view/platform-summary.txt`.

Native Google Ads reporting is now verified and collected daily with GA4, Search Console and Cloudflare HTTP analytics. Ads customer6808491878 is CAD/Toronto; GA4property530093120 is USD and530619880 is CAD. GSCsiteOwner, sitemap reads and homepage URL Inspection passed. Current GTM listing returns no accessible accounts. Read success grants no write authority. Windsor credentials/account discovery work, but actual data are blocked by the Free1-account allowance versus12 connected; HTTP200 warning zeroes are excluded, never learned as real results. No paid upgrade or disconnection occurred.

Daily API-user collector runs01:45UTC before backups with fixed read-only endpoints,16-call/8MiB bounds, resource deferral and pinned existing code. Existing acquisition snapshots/timeseries/facts retain provenance, immutable corrections and timezone/currency. Three namespace-specific deletion guards prevent older pruning of new platform history; no live prune ran. Four internal content drafts are DRAFT_ONLY. Qualified-lead cost/ROAS remainUNKNOWN without exact campaign/outcome linkage.

Daily capability audit now checks a bounded no-PII raw Cloudflare security sample; grouped dataset remains separately authz-denied. Current source failure/staleness monitoring uses existing C limits. All45 consequential flags, Books approval, source SHA, production authority/DNS and OLD fence remain unchanged. Public publishing, paid inference/ad changes and conversion uploads remain disabled. One disabled owner authorization packet covers proposed scopes/app approvals/asset bindings and draft content policy; it grants no current execution authority. Exact tests, preimages, verified checkpoint, recovery and configuration-only rollback are in the current procedure.

## Issue 98 and connection-watchdog review — 2026-11-12 — DEVELOPMENT ONLY

Current authoritative production remains NEW vps-f8e9b20e at ec9a8e85095b57faf21212000652912e08093da4. API PID981189 has not restarted. Executable candidate b5dcf192e16d034fbe4f508f13b2b17168b17841 is isolated on fix/issue98-native-queue-readiness-20261112. No candidate was installed, pushed, merged or deployed; no timer was added or reactivated. Production root runbook authorization digest stays unchanged; the digest beside this candidate describes this candidate prose only.

Live evidence: native CRM channel5062683202609281 GET returned204/no subscription. Last verified expiry was2026-10-07T20:38:19Z; an Oct6 renewal ended MANUAL/ValueError without verified readback and remains unresolved. Do not clear that intent, replay it or reopen the disabled kernel. Local queue:3483completed,17failed from Oct2–6,17human-review rows;0queued/running/claimed. Seven exact EventConflict runs already have an independently read-proven acknowledgement; loss of the runtime projection prevents that acknowledgement appearing. Preserve all originals, including the remaining10 unacknowledged failures. Fresh Cloudflare reads:main backlog0;DLQ8/4105bytes. These are distinct queues and no message was leased, acknowledged, purged or replayed.

Confirmed monitoring defect: /run/optibrain-readiness/status.json is absent and queue-depth.json is stale because both helpers were ExecStartPost dependencies of the intentionally masked phase12 TEST runner. Do not unmask the runner. The legacy helper also expects that retired timer, old staging-size ceilings and a phase13 source receipt(be8cdfe2) instead of current NEW registration(ec9a8e8).

The candidate reconnects the EXISTING queue sampler and runtime projection to optibrain-resource-sample.service via an uninstalled drop-in. It uses the same15-minute timer, resource measurements, daily integrity proof, native credential-health file, current required service roster, exact45 process flags and current registration. No additional OAuth cache, provider gateway, credential refresh, notification allowance, daemon or timer. The queue GET transport has two attempts at most,5second/request timeout,1MiB response ceiling,no redirects; auth errors fail once and long/HTTP-date Retry-After defers. It never reads queue bodies. Native/Queue diagnostics retain ACTION REQUIRED and distinguish missing watch/retained history/current delivery. Unknown active backlog age is DEGRADED. New readiness diagnostics require the normal guarded API release and its own approved restart; the monitoring-only installation can be reviewed separately without restarting the API.

PR159 at c55b1d9ee7a152a46bf7945ad6a02a2bc55348ea was reviewed, not installed or altered. Its10tests pass, yet an actual main-loop reproduction made1attempt with3configured because main calls probe instead of probe_with_retry. Its example OPTICABLE_CORE_API_KEY is absent on this VPS; the application uses SITE_WORKFLOW_API_KEY. Its GitHub /user and static Zoho-token probes do not match existing renewable App/native clients. HTTP200 transport is not readiness/real-reporting proof; invalid/future freshness and stale-success exit semantics also need CLI coverage. Existing root capability baseline, same-user15-minute refresh, resource transition audit and bounded owner-mail ledger already cover the useful registry/freshness/alert responsibilities. Do not install another checker to duplicate them. The tested retry and current-job projection gaps are addressed in existing components.

Validation:35 focused baseline cases; final81 focused cases pass, including29new regressions. PR15910existing offline tests pass separately, illustrating the uncovered CLI gap. Changed Python compiles; git diff --check and systemd-analyze verify pass. Read-only shadow projection of actual VPS data yields9healthy infrastructure/refresh signals, retains Native watch ACTION REQUIRED, distinguishes local current delivery OK from10unacknowledged historical failures, and retains Cloudflare DLQ ACTION REQUIRED. No fake green, provider write, paid call or notification send.

Private evidence and verified preimages: /var/lib/optibrain/issue98-development-20261112. configuration-before.tar.gz and affected-code-before.tar.gz were fully read/verified. Existing recovery point20261112T195422Z local archive was rehashed against its verified proof; retained authenticated R2 download/hash and isolated10-store restoration PASS. Offline private AGE decryption was not repeated. No historical DB was restored.

Focused command from the isolated checkout:
PYTHONPATH=apps/workflow-api:apps/workflow-api/tests /opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -m unittest test_issue98_readiness test_phase14_readiness test_phase5_hardening.NotificationHardeningTests test_native_channel_recreation test_phase14_observer_resolution test_phase15_rebuild test_phase14_today -q

Production changes remain approval-gated. Proposed monitor-only scope: replace the reviewed queue-metrics.py and phase14-runtime-snapshot.py, install current_readiness.py under the same root-owned protected library, and install ONLY the readiness.conf drop-in on the existing resource service. Preserve verified preimages; validate exact reviewed hashes, ownership, service sandbox and current baseline before daemon-reload. Let the existing timer invoke it; no API/PDF/Omada restart and no flag/provider/security-policy change. Do not execute code from a user-writable checkout as a privileged scheduled job.

Rollback is configuration/code only: compare for newer changes, restore ONLY the two existing helper preimages from affected-code-before.tar.gz, rename ONLY the new readiness.conf drop-in out of the service.d directory, and daemon-reload. The new projection helper can remain inert. Keep runtime audit, all current business DBs, credentials, notification ledgers and every receipt. Do not restore the entire configuration archive, old DBs, migration gates or a VM image. Native watch recreation is a separate exact owner-approved provider configuration operation; existing read-only recreation tooling never authorizes itself. DLQ review remains read-only; no uncertain replay.

## Approved monitoring rollout and recovery development — 2026-11-12

The owner approved ONLY the previously reviewed three samplers and one existing-resource-service drop-in. Exact code commit b5dcf192e16d034fbe4f508f13b2b17168b17841 was checked against its frozen manifest, installed atomically, and invoked by the EXISTING timer at21:37:17–19UTC and again21:53:02–05UTC. Queue and runtime observations are fresh;all9infrastructure signalsOK. API/PDF/Omada remained healthy;API PID981189 and production sourceec9a8e85095b57faf21212000652912e08093da4 unchanged.45flags and76protected configurations unchanged. No API restart, new timer, credential/security/migration gate change, watch recreation, queue replay or new notification route. The resource service measured about18MiB peak RAM and under1CPU-second on the second observed run.

Installed root identities SHA256:
- /usr/local/lib/optibrain/queue-metrics.py — 471f4ff7d1d20439cb7155fe2cf84ff851cbc493dff09c44cdb718afb4149a7b
- /usr/local/lib/optibrain/phase14-runtime-snapshot.py — 8d2fbe43d0ee3b21de45aee2d3935936fe0a25ccb4a23a7a93c52f51d4989219
- /usr/local/lib/optibrain/current_readiness.py — 4b4585f92b227966c26409539ced02544e9b2e896b313679ac3c5204c0321487
- /etc/systemd/system/optibrain-resource-sample.service.d/readiness.conf — a0998f0929ff55ea9697df45f2985e3126770abbb8b3962708cd07c6cfc30617

Issue98 is NOT fully resolved:absent expired CRM watch remainsACTION REQUIRED;local17historical failures remain intact(7read-proven display acknowledgements now project,10unacknowledged);Cloudflare main0/DLQ8 remain;disabled delta observer produces a stale checkpoint. These are not cleared by repairing telemetry. Never unmask the bundled TEST runner or replay history to clear readiness.

PR159 is corrected on its existing GitHub branch feature/connection-watchdog-20261112 at e74b4413019db9cdec99bc30266ce307a1d78d10. Main dispatches probe_with_retry. Four CLI regressions test actual main->HTTP boundary;two fail against original source;all14pass. Exact-head GitHub offline-unit-tests completed success,run43312673936. It remains draft/offline/manual and is NOT installed;existing native Ads/GA4/GSC/Cloudflare collection and credential refresh remain canonical.

DEVELOPMENT ONLY:feature/operational-recovery-20261112 contains operational_recovery.py,release_recovery.py,defect_development.py and a fail-closed future release-gate hook. Core code commit1032adfd50bc526a25b9f1dd30ca99251d2b0c1b;verification hardening/test-clock commitdea7289591668931dbb8efff82d39d8f7b2e44d5. No new module, release gate or repair coordinator was installed in production. Existing root operational repair continues unchanged.

Non-production repair consumes the existing operations observation instead of collecting again. Deterministic cause classes remain CLASSIFICATION_ONLY;recurrence never grants authority. Exact opt-in unprivileged workspace,1day maximum grant,operation binding,flock,2attempts/hour,>=60second cooldown,3global attempts/6hours,postrepair readback and permanent ambiguous-effect hold are enforced. The two real playbooks rebuild only fixed derived/status.json while retaining any preimage,and retire only a fixed development read-job lock after dead-owner plus independent flock proof. No unrestricted shell or production path. Failed recovery creates a deduplicated local incident in existing immutable ActionEvidence;learning includes symptoms,cause class,action/tests/outcome/provenance and is NOT promoted as business success. Manager receipts are TEST_ONLY;production manager_learning stays unchanged.

Release recovery requires authenticated exact GitHub last-known-good source,hash-verified consistent archive,complete bounded authenticated AGE ciphertext readback,and isolated source/SQLite restoration. The contract binds exact code/config targets/hashes/modes,fresh independent checkpoint digest,old-code/new-schema compatibility and an expiring owner-approved one-rollback playbook. Routine database/security/credential restoration is forbidden. Existing SigV4 client is reused;no new credential store. Private AGE decryption is a separate owner dependency and is never inferred from upload/readback. Future manual-release-gate source now refuses changes without a private external verified recovery contract;installation would additionally require approved root-runtime pin updates. Existing installed gate and its legacy timer expectations were not changed in this mission.

The independent supervisor executes only in a granted development workspace,not production. Real isolated Git/process/SQLite tests reject or roll back broken code,detect a later failed candidate,resume interrupted exact rollback,block unknown/newer edits,and stop/create an incident after failed rollback. Newer business rows survive. Permanent demonstration:/home/ubuntu/optibrain-development/recovery-demonstration-20261112/result.json;known-good fixture2b4f8f5dd01c84ef4c570676c0d67f09baa4fd2f,broken27686e2d082013f70be9d16921123ebcd311f36d,final code hash1e992949a22a6e3f8f8efb1594ef95c8dba044fb5830c18866b8080d7f2e6101 and1->2business rows preserved. Its tiny R2/encryption transport is explicitly SIMULATED;it is separate from actual production R2/restore proofs.

Verified-defect preparation requires clean source matching authenticated GitHub commit/tree,reviewed regression code,failing-before/passing-after results,zero skips/network attempts,bounded child resources,no-new-privileges and a fixed diagnostic-file allowlist. It cannot modify its own safety/recovery modules,financial/security files or production. It creates an isolated branch/commit and DRAFT PR request;no automatic push/merge/deploy. Python-level network blocking is not claimed as a hostile-code OS namespace sandbox. A real issue98 claimed-work regression against GitHub-verified ec9a8e8 failed before/passed after and prepared local repair/verified-defect-e0600ea806b8d928,commit0a71738d68031ec22e3b6224989b75d4b8f74aea. Do not publish a duplicate PR when existing issue98/recovery work already covers it.

Validation:103targeted cases passed before final hardening;the final FULL fake-provider suite passed2013tests/1920subtests with0failures/errors/skips/network attempts. The first full run exposed7dated conversion-test errors;only fixtures were fixed with a deterministic October clock,and a new assertion proves expired conversion authority still blocks. No conversion transport,financial flag or production expiry requirement was changed. Logs preserve initial errors and final success. Documentation/rebuild contracts(273documents/98sources),Python compilation,systemd verification and exact source hashes pass.

Private rollout/checkpoint/evidence:/var/lib/optibrain/monitoring-self-healing-20261112. Before installation monitoring-prechange.tar.gz was verified,plus existing encrypted recovery generation20261112T195422Z hash/complete readback/isolated10-store proof. Exact monitoring rollback:compare current hashes against rollout-baseline.json;restore ONLY prior queue-metrics.py and phase14-runtime-snapshot.py from monitoring-prechange.tar.gz;rename only the new readiness.conf out of service.d;daemon-reload. current_readiness.py may remain inert. Keep resource sampler/base unit/fallback,all business DBs,credentials,audit/learning and prior recovery evidence. New development code rollback is source-only;it has no installed production effect.

Example isolated exercise (unprivileged,NEW authority untouched):
/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -I -B ops/phase14/development_recovery_exercise.py --workspace /home/ubuntu/optibrain-development/NEW-UNUSED-EXPERIMENT --base-source /home/ubuntu/optibrain-development/verified-defect-baseline-20261112 --github-identity /home/ubuntu/optibrain-development/verified-github-base-20261112.json

Future session:first verify productionec9a8e8/current process flags,read this latest section and rollout-validation.json,then inspect exact GitHub draft heads and final full-regression evidence. Do not repeat completed monitoring rollout or install a duplicate watchdog. New production repair/supervisor activation,Native watch recreation and any consequential/customer/financial action still require applicable approval. Root runbook authorization digest remains unchanged;this candidate's adjacent digest covers development documentation only.

Final development hardening:6e63ddc9f5a318aa35810a5625f0b5476fbaf780 verifies workspace directory ownership and rejects group/world-write access before any development grant or repair. Its adversarial regression passes. The final full suite passes2014tests/1920subtests,0failures/errors/skips/network attempts;the earlier2013PASS log is retained separately. Production monitoring remains the exact approved b5dc artifacts;this hardening is development only.

Recovery-control protection is explicit in bcf3472515982e77a73ea348ae6eb0129565710b:automatic rollback contracts reject the release gate,coordinator,supervisor and defect-preparation modules themselves. This prevents recovery from undoing its own safeguards. A dedicated adversarial regression and the final full suite pass2015tests/1920subtests with0failures/errors/skips/network attempts. Earlier2013/2014passing logs and the initial dated-fixture failures remain evidence,not reset history. Fresh actual production recovery point20261112T221338Z passed complete encrypted R2 readback and isolated10-store restoration;all four approved installed monitoring identities were found and hash-verified in its archive. Offline private AGE decryption was not performed.
