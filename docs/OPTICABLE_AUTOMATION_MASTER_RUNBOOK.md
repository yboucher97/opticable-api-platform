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

## Independent monitoring revalidation and recovery development — 2026-11-12 Toronto

The approved rollout was already complete. Reverification at 2026-11-13T01:41Z
confirmed the exact four installed artifacts from candidate
`b5dcf192e16d034fbe4f508f13b2b17168b17841`; no repeat installation was needed.
NEW remains `vps-f8e9b20e`, production `ec9a8e85095b57faf21212000652912e08093da4`,
API PID981189 with zero restarts. API, PDF, Omada and Caddy are active;
their liveness reads passed. All45 flags remain closed and all76 protected settings
match the prechange checkpoint. The existing resource timer ran queue/resource/local
projection successfully at01:01,01:17 and01:33UTC; no new scheduler or alert route.
The complete installed hashes/modes/owners and live audit are in
`/var/lib/optibrain/monitoring-self-healing-20261112/reverification-20261113/production-audit.json`.

Recovery generation `20261112T221338Z` was rehashed:
plaintext SHA256 `4c595da695fabdbc579aa32876dd7533031fb78f738627a627d9c21aad283494`,
ciphertext SHA256 `5f7ef5a1993e5addf44bf757afe379b365bc1f9fa41af0e1e9feb0516b0bba6a`.
The retained authenticated complete R2 readback and isolated10-store restore proof
are intact. This revalidation did not repeat a remote download or private AGE
decryption. Monitoring preimages were independently reverified. Existing OLD fence,
credentials, owner approvals and notification budgets were untouched.

PR159 remains draft at `e74b4413019db9cdec99bc30266ce307a1d78d10`, branch
`feature/connection-watchdog-20261112`. All14 tests passed again, including main
dispatch through configured retries at the HTTP boundary. It remains offline/manual;
do not install a duplicate watchdog. Prior exact-head CI43312673936 passed.

Additional development fix `2d0725945467674a52e03a0d1ace7cf20ac12e69` on local branch
`fix/recovery-readback-evidence-20261113` corrects a discovered readiness defect:
local backup age alone previously allowed an off-host OK label. The candidate now
consumes the existing trusted retention receipt and binds generation, object key,
plaintext/ciphertext hashes, preparation metadata, isolated restore and original
verification time. Missing/malformed/unbound proof is UNKNOWN, stale proof needs
action, and a fresh resource sample cannot refresh old proof. It adds no remote
read, cache or state store. Its collect-path integration test checks real dispatch
into this projection. This follow-up is DEVELOPMENT ONLY; the approved installed
sampler bytes remain unchanged. Actual retained production proof passes the new
projection in an unprivileged shadow read.

Before the fix,33tests reproduced25failing assertions with zero errors. Afterward,
95focused tests/27subtests passed; the full fake-provider suite passed2020tests/
1947subtests with zero failures/errors/skips/network attempts. Contracts checked
273documents/98configuration sources; syntax and whitespace passed. Logs:
`/home/ubuntu/optibrain-development/readback-regression-before-20261113.log`,
`reverification-targeted-after-20261113.log` and `reverification-full-regression-20261113.log`
in that same directory. A verification command initially probed Omada `/health`
and received the expected containment403; the documented `/api/health` returned200.
No service repair was required. Local commit identity was supplied per command
after Git refused an unset identity; global Git settings were not changed.

The fresh isolated demonstration is
`/home/ubuntu/optibrain-development/recovery-demonstration-20261113/result.json`.
Broken fixture `2b1a5a658ad25704b3f96d61e10ed4ab98b15d07` rolled back to
`2f5eab874986f944446be2fce455cf3b85d93b37`; final code SHA256
`1e992949a22a6e3f8f8efb1594ef95c8dba044fb5830c18866b8080d7f2e6101`,
health and journal integrity passed, and newer business rows1->2 survived without
any database restore. Fixture R2/encryption are explicitly SIMULATED; actual
production recovery evidence above is separate. The verified diagnostic-defect
workflow again failed before/passed after and automatically prepared local branch
`repair/verified-defect-e0600ea806b8d928`, commit
`c678cedf75b4a52992d7ab10287580896b2c0d62`, and a draft PR request. It was not
published as a duplicate of existing issue98 work. The new off-host defect's
symptom/cause/action/tests/outcome are in the same isolated ActionEvidence journal
under `operations-diagnosis`; learning integrity passed and business reuse is OFF.

Issue98 remains open: expired/absent Native watch,17retained local failures
(10unacknowledged),8Cloudflare dead letters, stale disabled delta observation and
unclassified review. Main queue has no current backlog. No watch recreation,
historical replay or dead-letter purge was performed. Bounded non-production
playbooks, locks/cooldowns/circuits, health verification, deduplicated incidents,
learning, defect branch preparation and the independent GitHub/R2 rollback contract
remain development capabilities in draftPR160. Production activation, the new
sampler fix and any guarded-release/root-runtime roster change need their own
applicable approval. Do not weaken the installed legacy timer gate.

Rollback remains exact monitoring files only: compare installed hashes for newer
edits; restore prior queue-metrics.py and phase14-runtime-snapshot.py from the
verified `monitoring-prechange.tar.gz`; move only readiness.conf out of the existing
resource service drop-in directory and daemon-reload. current_readiness.py may
remain inert. Preserve the base resource unit/fallback/timer, all business records,
credentials, approvals, notification/learning/action journals and existing recovery
checkpoints. No API restart, VM snapshot or older database restoration is part of
this rollback. Development changes have no installed production effect.

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


## Autonomous recovery integration — 2026-11-13 UTC

NEW vps-f8e9b20e remains production ec9a8e85095b57faf21212000652912e08093da4,
API PID981189/zero restarts. The only installed correction is
/usr/local/lib/optibrain/current_readiness.py, root:root0755, SHA256
`dc842c0ba4ee696f24cd65a6f51d47fe91e5d734003497a8d07f8a6bf543c921`.
Its tested source is local2d0725945467674a52e03a0d1ace7cf20ac12e69 / GitHub
`e7772f40acf609c4cf9feb0f23e990f88dac451f`. No other development file was installed.
Preimage SHA256 `4b4585f92b227966c26409539ced02544e9b2e896b313679ac3c5204c0321487`
is verified in `monitoring-correction-prechange.tar.gz`. All45 consequential flags
stay OFF; all76 protected settings, three other monitoring artifacts and production
pins are unchanged. OLD forced read-only status independently confirmed FROZEN,
fenced=true, all three application services inactive. No API restart, new job,
writer, security-policy change, watch recreation or historical/DLQ replay occurred.

Private execution evidence:
`/var/lib/optibrain/autonomous-recovery-integration-20261113`.
The existing timer invoked the correction successfully at03:53UTC. Missing latest
backup proof correctly changed the off-host result to UNKNOWN. The existing routine
recovery verification subsequently produced generation20261113T023658Z's proof;
no second backup/verification scheduler was created. Its archive rehash passed,
plaintext SHA256 `fe445293e5022df2a814f3fa9e7878f22dbbe286e07d2588f414e4342e268c01`,
ciphertext SHA256 `aef442ba13a1940dcbe757ca90bd684a288dc0202f2c8c0e5c030236e8cf2ef8`,
R2 object `backups/2026/11/13/20261113T023658Z.tar.gz.age`,423135047bytes.
Retained authenticated complete readback and isolated10-store restore PASS:
6788files/8482metadata entries; sourceec9a8e8 and fresh conversion authority OFF.
Preinstall checkpoint221338Z remains recorded. No owner private AGE identity was
copied, generated or decrypted; readback is not proof of owner-key availability or
full VPS disaster recovery.

Current main is be8cdfe2b36b562ba9e2a57484d8a3d2e8c92caa, one intake-hold commit
behind production. PR159's seven additions are disjoint from production/PR160.
Its exact offline/manual utility and later documentation reconciliation were
integrated locally; no collector/state/cache/timer/notification replacement.
PR159 documentation head `ccf5cb2559f319b4d7cb98857890047cb56693ff` passed CI43363362307;
its14 CLI tests retain the configured retry execution-path regressions. PR160 now
also runs these tests in its main validation workflow. It retains the exact
production recovery base; integration into main needs separate reviewed treatment
of that intake-hold prerequisite. Neither application PR is merged/deployed.

Development branch `feature/recovery-integration-20261113`, core implementation
`aba5851d2c19673dd08aea418f2c6807451b145e`, evidence hardening
`826ede983c124017149ad7d8af27e3b172eb22ff`:
- Every attempted local repair independently verifies even after an execution
  exception. Unavailable verification finishes FAILED, preserves evidence/learning
  and raises a persistent hold. Another operation cannot bypass that hold.
- Cause classification remains distinct from proof. Credential warnings no longer
  imply401/403; recurrence cannot count missing service IDs. Local preconditions,
  dead-owner/exclusive-lock proof, errors, tests and outcomes remain in ActionEvidence.
- Fatal rollback incidents stop subsequent deployment/repair attempts in the same
  journal. Existing-format escalation output is deduplicated; actual Mail delivery
  still requires the existing owner-only budget/ledger. No new alert stream or
  falsely claimed notification was created.
- Independent supervisor requires current-data integrity evidence as well as code
  and HTTP health, verifies code again after probes, and binds an exact relevant
  code/config checkpoint. Recovered health may support change-associated recovery;
  an unverified cause remains UNPROVEN. Data corruption stops/escalates even when
  old code is healthy; no older database is restored.
- A new regression resumes interrupted rollback in a fresh Python process without
  importing the main API. Existing transient retry, dead/live worker locks,
  interrupted-effect reconciliation, bounded failures and one-rollback tests remain
  canonical. All fault injection uses private unprivileged fixtures.
- Existing recurring software incidents now drive paired regression, branch and
  draft PR-request preparation with operation binding, exact verified GitHub base
  branch/SHA, idempotency and failure review. It still requires a reviewed diagnostic
  patch/test; it is not an unrestricted code generator or auto-push/merge/deploy.
- Readiness now labels stale disabled delta observations explicitly, retains source
  timestamps and preserves real failed checkpoints. Claimed work without historical
  failures cannot be labelled CLEAR. These API diagnostics are development only.

The proposed catalog is `ops/phase14/production_repair_catalog.json`: exactly three
playbooks (refresh-local-readiness, restart-contained-support, exact-approved-release-rollback).
Every permission is DISABLED. Each binds exact actions/services/preconditions,
one attempt, cooldown,45/90/180second timeout, success checks, rollback/escalation,
maximum7day grant expiry, immutable audit and prohibit conditions. Canonical digest
`634263b8e57909c8fd6b1d7a0e47dda7991232f77e7cafc54a7d74b3f08dc938`;
file SHA256 `7cde890aaeb4005d78d5d14b5eae7ab699c2d730a7aafdbc567781e9eb5ef930`.
The validator has no executor; enabled bits alone cannot supply root-verified owner
approval/runtime pins. Automatic rollback cannot target the catalog or its validator.

Validation:115focused tests/27subtests and full2040tests/1947subtests PASS,
zero failures/errors/skips/network attempts, plus14 offline CLI tests. Final CI
commit/run receipts are recorded separately to avoid a self-referential source SHA.
An initial new delta fixture used invalid status 'success'; it was corrected to
'idle', without changing production schema. Integrating two README/runbook files
exposed missing document-register entries; both are now audit evidence. Contracts
cover275documents/98configuration sources. Original failed logs are preserved.

Issue98 remains open: exact channel5062683202609281 returned authenticated204 at
03:59UTC;17historical local failures (7pre-existing reviewed displays,10unacknowledged),
17unclassified review items, main queue0/DLQ8. Delta source remains stale because
its bundled executor stays OFF; fresh readiness never fabricates a fresh delta.
Separate `native-watch-owner-decision.json` is NOT APPROVED. It binds one exact
POST/plan/expiry/current source and retains the old ambiguous intent. Private hold
receiver200/ready; public event-health403 prevents complete receiver verification.
Do not change Access policy or treat this proposal as execution authority.

Monitoring-only rollback (root, compare exact current hash first; no daemon-reload
or application restart is needed for this single Python-file correction):

```bash
sudo /usr/bin/python3 -I -B - <<'ROLLBACK'
from pathlib import Path
import hashlib,json,os,tarfile,tempfile,subprocess
base=Path('/var/lib/optibrain/autonomous-recovery-integration-20261113')
m=json.loads((base/'monitoring-manifest.json').read_text());p=Path(m['target'])
assert hashlib.sha256(p.read_bytes()).hexdigest()==m['installed_sha256']
with tarfile.open(base/'monitoring-correction-prechange.tar.gz') as t:
    data=t.extractfile(str(p).lstrip('/')).read()
assert hashlib.sha256(data).hexdigest()==m['before_sha256']
fd,name=tempfile.mkstemp(dir=p.parent)
with os.fdopen(fd,'wb') as f:
    f.write(data);f.flush();os.fsync(f.fileno())
os.chmod(name,0o755);os.chown(name,0,0);os.replace(name,p)
assert hashlib.sha256(p.read_bytes()).hexdigest()==m['before_sha256']
subprocess.run(['/usr/bin/python3','-I','-B','/usr/local/lib/optibrain/phase14-runtime-snapshot.py','--current-services'],check=True)
ROLLBACK
```

Preserve the existing resource unit/drop-in/timer, all business databases, journals,
credentials, approvals and newer edits. New production repair/supervisor/catalog
activation and application release/root-runtime pin changes require separate approval.
The native proposal additionally requires verified receiver access and fresh exact
owner authorization. No optional integration blocks continuing isolated development.


## Consolidated release and controlled self-improvement v2 — 2026-11-13

Production remains ec9a8e85095b57faf21212000652912e08093da4; this task installs
nothing. All45 consequential flags,76 protected settings, monitoringdc842c0b and
OLD fencing remain authoritative. Branch `release/production-integration-v2-20261113`
starts at exact production and consolidates31reviewed PR159/160 paths in
`4e68dc4`. Production-only intake/hold and mutation boundaries are preserved.
Prior PR headsccf5cb2/515facb remain unmerged evidence, not alternative deployments.

Actual v2 implementation `5de0592` and `0cf13ba` extends the existing controller:
- Registered zero-cost diagnostic generation consumes recurring failure/source
  evidence and existing immutable repair history. No input patch or regression is
  needed for its supported future-timestamp defect. Unknown rules fail for review.
- It generates one pure diagnostic function and three positive/negative regression
  cases. Function signature/imports/dispatch/retry/authorization code outside that
  function are preserved. Unrelated files and side effects are rejected.
- Generated code runs under per-child Landlock filesystem restrictions, seccomp
  network/ptrace restrictions, no-new-privileges and existing CPU/memory/file/time
  limits. Source is read-only; only private scratch is writable. Subprocess network,
  outside reads and source edits were actually denied in tests. No host policy was
  changed. Unsupported kernels fail closed; no namespace policy was relaxed.
- Paired failing-before/passing-after proof plus all14retained diagnostic tests is
  mandatory. Two global attempts/day,4000proposal-token-equivalent bound, zero
  additional model/API cost and immutable per-incident identity apply. Successful
  verified recipes are reused with fresh proof; failed attempts remain learning.
- This is narrow registered source synthesis authored in the existing approved
  coding environment, not a general LLM patch agent. Arbitrary model-driven edits,
  self-modification, automatic push/merge/deploy and production execution remain OFF.

Real demonstration:
`/home/ubuntu/optibrain-development/v2-generation-demonstration-20261113/result.json`.
Two actual future-date failures were reproduced against GitHub-verified515facb.
The system generated source/tests and branch`repair/verified-defect-a76ae98a4fd60a15`,
commit`63dbde6e69cf17cd3db49563f4b6602c128b14de`, with a draft PR request. Its scoped
fix is consolidated as`833c0eb`; it is not published as a competing release PR.
No external paid inference call or new credential/token cache was used.

Independent recovery now atomically writes approved modes, fsyncs bytes and parent
renames, checks exact modes/ownership/link count, and stops on visible-but-unverified
durability. A real hard-exit during rollback resumes from the existing journal,
verifies old code and preserves newer business rows. Backup streaming has a180second
budget and rejects no-progress streams. Failed artifacts never become recovery proof.
Existing OAuth401refresh,403stop,transient/backoff,ambiguous-effect,circuit and failed
rollback tests remain canonical; no parallel recovery framework was created.

A staged independent capsule reuses the existing operational inventory/hash pin
pattern:188Python files,2420497bytes, mainAPI excluded. Source0cf13bab21142641900c013ba49e578cf69c9002;
external manifest digest`bf40ab9729ef2b341bccba25679c35a76e455d7fdc662572464b6ab790811b6f`.
It imports the existing supervisor in a fresh process without the API; tampering is
rejected before code import. Artifact:
`/home/ubuntu/optibrain-development/v2-independent-runtime-20261113`.
This is unprivileged staging only. A production installation still requires separately
reviewed root ownership, an external runtime pin and a production execution adapter;
the current supervisor deliberately refuses production scope. Existing installed
root operational readers/pins are unchanged.

All3disabled repair proposals now have real isolated execution/failure exercises:
readiness uses the existing derived writer and restores only a bad derived preimage;
PDF/Omada use bounded one-shot fixture processes with persistent state, duplicate
operation claims and cooldown; rollback delegates to the existing Git/process/SQLite
supervisor. Timeout ambiguity stops other attempts. Real systemctl/provider operations
are never invoked by these exercises. Standing preflight additionally requires a
separate exact operation_id authorization. The catalog remains permissions_enabled=false
with all grants disabled. Low-risk refresh/support semantics are ready for standing
review; production adapter/runtime evidence is still required. Exact release rollback
remains development-only pending that installation and per-release approval.

Incident98 classification now distinguishes expired capability/unresolved history,
retained DLQ review from active stalled delivery, and public edge-check denial from
origin outage. ACTION REQUIRED remains for retained dead letters and current403.
Native still returns authenticated204,17historical failures/10unacknowledged and
17unclassified reviews remain;main queue0/DLQ8. Delta remains stale with its bundled
executorOFF. Public health and receiver returned Cloudflare403 from NEW with no
proxy variables; reason/policy intent remain unproven. No Access change, native
recreation, acknowledgement, queue replay or purge is authorized. The smallest
Native decision remains one exact POST into verified hold, but public receiver proof
is incomplete; revalidate its existing plan/expiry before any owner approval.

Validation:full2061tests/1947subtests,zero failures/errors/skips/network attempts;
118focused tests/27subtests and14utility testsPASS. Python syntax338files,
JSON126files,contracts275documents/98sources and deployment shell validationPASS.
Initial mode-sensitive fixtures failed12assertions plus1error; they now explicitly
install their declared0644 mode. Protection was not relaxed. Failed logs and later
125/118focused and2057/2060/2061full successes are retained. Exact-head final CI
and release SHA are in the final completion receipt, avoiding a self-reference.

Recovery dependency check13:23UTC:existing encrypted R2object generation023658Z
HEAD423135047bytes verified and local plaintext rehash matchedfe445293e5...268c01;
retained full ciphertext readbackaef442ba13...8cf2ef8 and10store restorePASS remain.
Offline owner AGE availability has been requested and is UNVERIFIED without the
owner's local attestation. Never copy its private identity to this VPS. Application
code/config rollback is distinct from host reconstruction, provider reconciliation
and offline-key disaster recovery. No full-VPS restoration or new key-custody proof
is claimed. Existing R2 backup/restore schedules and all live collectors remain intact.

No application deployment, production pin/grant change or monitoring reinstall is
part of this task. Development rollback is source-only; installed monitoring retains
its separately verified prior monitoring-correction preimage. Never overwrite newer
business databases, notification ledgers, approvals or immutable incident history.

## Production recovery foundation — passive only, 2026-11-13

The protected existing capsule0cf13bab21142641900c013ba49e578cf69c9002 is installed on
NEW with its original manifestbf40ab9729ef2b341bccba25679c35a76e455d7fdc662572464b6ab790811b6f.
It contains188Python files. System-Python dependency closure381files/12772825bytes,
copied from existing installed packages without downloads, is independently pinned
asfa1fa6c7c3d0a7d6c519a3b258bf8d7c3e447b74cbdd0da95605b11f2725433c.
Installation integration sourcebf9016b;576protected static files, including one
unscheduled capability-free nobody verification service and one drop-in on the
existing resource timer. No new schedule or notification sender exists. Complete
file hashes, preimages, failures, fixes and rollback receipts are kept under
`/var/lib/optibrain/recovery-foundation-20261113`.

Initial system-Python dependency failure and service-context privilege-drop failures
were detected, then all changed supervisor components were restored. The final child
is started unprivileged by systemd rather than inheriting privilege changes from the
resource service. Actual resource-service execution, separate runtime verification,
main-API-unavailable process-local simulation and restricted-operation rejection
pass. The main API was never stopped. Runtime code, vendor files and service pins
are root-owned; application imports run without capabilities and with network denial.
Passive status cannot execute application restart, repair, rollback or deployment.

PR161 remains exactb0b94f118a22e0dfcbee8d3f729f67d618cf99da, not merged/deployed.
Full2061test baseline and exact-head3jobCI are reverified. Preflight identifies two
pre-existing tracked documentation overlays, preserved in release161-preimages.tar.gz
SHA256ba0779aa174342fe5b7e8d9bf3825101225cb522fbf544efdbc9ce7fee89d126.
The actual master document ise35a269f...82226d; Git baseline isd66c9322...9c4f1,
candidate iscec6eaab...f3ca4. No reset or trust-pin update was performed. Existing gate
requires clean tracked files and exact main push/workflow_dispatch CI; PR CI alone
does not satisfy it. A reviewed read-only validator bridge is staged in development
and leaves existing operational reader pins unchanged. Main promotion, exact overlay
reconciliation, root helper installation, release environment and release/config pins
remain part of the separate exact release approval, never inferred from credentials.

New readiness adapter/entrypoint are isolated development only. The fixed command is
`/usr/bin/python3 -I -B /usr/local/lib/optibrain/phase14-runtime-snapshot.py --current-services`.
Exact operation/grant/service/source/checkpoint binding,1attempt/45seconds/900seconds,
global lock, immutable existing phase12journal claim, audit interruption hold,
independent output/clock/source checks, timer-race stop and exact-derived-preimage
recovery are implemented. No production grant or installed caller exists. Original
PDF/Omada and application rollback grants remain disabled.

Generationv2.3 adds two public-evidence defect classes to the existing narrow
diagnostic workflow: malformed status/object evidence and contradictory origin/
public health classification. Two real isolated reproductions against authenticated
GitHub sourceb0b94f1 produced branchrepair/verified-defect-974b056d725edefc,
commit1263ae433690c0f85a1bff86ba879c34c072b690. Six paired regressions and retained
utility/readiness tests pass. The outcome is appended to the existing demonstration
learning database; one-hour development scope was renewed explicitly within this
session's isolated-work authority. The two-attempt/day budget was preserved.
Current live malformed/conflicting evidence is not claimed. Root/security/grant/
recovery-control paths remain ineligible; generated classification cannot change its
policy-authority=false field. No general agent, model call, merge or deployment.

Native authenticatedGET23:01UTC still204/absent. A diagnostic child initially omitted
the existing API supplementary groups; correcting that local test context restored
the read, without a credential or permission change. It was not a provider outage.
Historical17failures,10unacknowledged,17unclassified reviews and8Cloudflare dead
letters remain. Public health/receiver403 remains distinct from healthy origin;
delta execution staysOFF and source evidence stale. Short-interval growth warnings
are measured independently of negative long-term trend. Existing samples show backup/
spool/history growth and later development/runtime staging; attribution is bounded
by overlapping category estimates. No warning, evidence or queue was suppressed.

Current R2HEAD and local archive rehash pass; retained complete readback/10store restore
proof remains valid. Owner offline AGE availability is still unverified. The exact
offline-only procedure is in the recovery guide. Application rollback, service
recovery and full host/data disaster recovery remain distinct approval boundaries.
Final regression counts, development/PR commits and installed file identities are
recorded in the completion receipt and protected operational master appendices.
The staged guarded-release helper additionally checks exact candidate code,
configuration hashes and environment link before rollback. Unknown/newer edits or
an incomplete candidate checkpoint stop recovery and persist an owner-review hold;
failed rollback health verification also holds subsequent releases. A real isolated
newer-credential/configuration file is preserved in the regression. This helper
improvement is not installed and does not change PR161's application source.
