# PHASE 13 INDEPENDENT AUDIT

**PASS WITH REQUIRED REMEDIATION — audit COMPLETE. Overall readiness C: NOT READY — MATERIAL ARCHITECTURAL REMEDIATION REQUIRED.**

Manual mission, 2026-10-01, America/Toronto. The question has a qualified answer: OptiBrain has coherent business foundations and strong narrow Test controls, but individual phases left independent provider writers, duplicate schedulers and recovery assumptions outside the claimed boundary. Critical exposed paths were contained. General real-business autonomy is not safe to authorize today.

| Required state | Independently observed result |
|---|---|
| Production SHA | ee7629f7e7954e1ee782c6481d4aaef37349d10f |
| Local main / remote main | Same SHA; remote checked directly, not just origin tracking ref |
| API | 1.11.0; local/public health readable |
| Persistent Codex development worker | OFF; six inactive units (five disabled, usage service static); absent root authorization-file condition added |
| Real automatic writes | OptiBrain-owned scheduled real mutators OFF/contained. **ISSUE for a universal provider guarantee:** native Forms CRM ingestion remains an independent producer whose current configuration is not fully proven |
| Protected mutations during audit | 0; 123 protected provider IDs resolved and no Modified_Time changed during independent start/end reads |
| Real customer sends / Books writes during audit | 0 / 0 |
| Test provider record mutations initiated by audit | 0; existing Lab reused for reads; observed runner runs wrote0 |
| Infrastructure changes | Explicit safety/configuration/backup and connector deployment changes listed below |

The core main/production revision was preserved. The independent connector has its own repository and was emergency-fixed/merged/deployed at aa1e084b06184df73847639700a8e540bd433293, PRs [30](https://github.com/yboucher97/opticable-ai-connector/pull/30), [31](https://github.com/yboucher97/opticable-ai-connector/pull/31) and [32](https://github.com/yboucher97/opticable-ai-connector/pull/32). Its deployment CI succeeded and downloaded provider code contains the unconditional mutation and executable-read guards. This is not the core production SHA.

## Executive verdict and domain scores

| Domain | Score | Material reason |
|---|---|---|
| Architecture | NEEDS WORK | Multiple independent execution authorities; business and infrastructure/admin surfaces mixed |
| Security | NEEDS WORK | Public legacy Omada/job routes and connector mutation bypass found and contained; API key found in historical URL logs |
| Data integrity | ACCEPTABLE within current scope | Protected IDs/versions and Lab relationships intact; no universal content-hash/historical audit guarantee |
| CRM safety | NEEDS WORK | Narrow Python fence strong; connector, native Forms and PDF did not universally share it |
| Identity | ACCEPTABLE for sampled Lab chains | Unique persistent crosswalk; provider-neutral/unified-ID claim needs revision |
| Sales | ACCEPTABLE read-only | Existing scenarios resolve; live project facts insufficient; no silent write from recommendations |
| Attribution | NEEDS WORK | Test continuity confirmed; source uniqueness/replay and connector return semantics fragmented |
| Lifecycle | ACCEPTABLE projection; real use BLOCKED by data | Recurring/dormancy/MRR safety works in Lab; real dates/revenue remain unknown |
| Operations | NEEDS WORK | Three provider-backed Lab chains; real projection intentionally empty |
| Autonomy | BLOCKED for real business | Only narrow Test dispatcher central; human approval/kill/recovery contract incomplete |
| Recovery | NEEDS WORK | Scope defect fixed and isolated restore passed; fresh off-host decrypt/full host boot unproven |
| Backups | ACCEPTABLE after fix, with required proof | Verified local archive/eight DBs and independent R2 ciphertext hash; retention/key proof outstanding |
| Monitoring | NEEDS WORK | Multiple journals/health surfaces; delayed GitHub schedules, failed dispatch/deploy and no unified action/backup alert ownership |
| Performance | NEEDS WORK | Repeated Mail receipt retrieval, duplicate schedulers, full scans/N+1 and no bounded retention |
| Documentation | NEEDS WORK | Earlier safety/runner/recovery statements contradicted deployment; critical override now supplied |
| Maintainability | NEEDS WORK | Many phase scripts, root helpers/registries, stale branches and 36 full-regression failures |
| Real-data readiness | BLOCKED for automation | Live sales/lifecycle facts incomplete; no verified real operational projects |

## Critical findings — 2 found, 0 left uncontained

**P13-C01 — independent public/generic connector bypassed protected CRM and financial policy.** Deployed connector code matched a separate source lineage. Public lead intake accepted forgable Origin/consent, selected the first CRM search result, then updated an existing Lead or Contact and could create a Deal linked to an existing Account. No protected manifest, Phase 12 authority, exact ambiguity rejection or pre-transport receipt claim applied. Generic Books writes accepted books_human_approved=true instead of an authenticated approval. Impact: credible unauthorized protected record overwrite and consequential financial mutation through the connector. Action: unconditional non-GET/HEAD Zoho denial before OAuth/transport, 30 zero-transport denial cases, complete 23-test connector suite, emergency content deployment, exact initial readback, PR merge and successful normal deployment with final guard readback. Remaining risk: public connector CRM intake is unavailable; native Forms and provider workflows require separate review before any reopening. No live malicious/financial mutation probe was used. HTTP GET is not itself a read-only guarantee: Zoho CRM functions and Creator custom APIs can execute business logic. The final guard also blocks unaudited service aliases, executable/action paths, encoded/query/traversal paths and method-override headers before OAuth. [Zoho function documentation](https://www.zoho.com/crm/developer/docs/functions/serverless.html) confirms executable GET support. No provider function was invoked. The read-extension merge initially had one HEAD test-expectation failure; it was corrected, all23 tests passed, and final deployment was independently checked.

**P13-C02 — externally exposed Omada infrastructure execution lacked authentication.** Source and public UI proved /api/runs/start, upload/validate/session and job routes did not universally call the webhook auth guard. Persistent browser/session tooling makes unauthenticated run capability consequential, regardless of whether a particular plan currently has valid provider login. Impact: unauthorized network operations and resource exhaustion/job disclosure. Action: ordered Caddy route containment on both configured hosts; all external non-health Omada routes now403; legacy core creation aliases separately contained. Remaining risk: underlying local service still needs authentication/approval/bounds before reopening. No infrastructure job was started to demonstrate the defect.

## High findings — 9

| Finding | Evidence / impact | Action taken | Remaining requirement |
|---|---|---|---|
| P13-H01 Real fallback enrichment active | Effective phase9-form-enrichment.env enabled real new Leads; central kill/policy absent | Set OFF; successful collector now reports enrichment null | Central ownership/authorization migration before real enrichment |
| P13-H02 Legacy Mail drafts and Sign sends outside central policy | Enabled analysis/digest and contract-send; 59 successful historical email_reply_drafted audit entries; Sign accepted approved_to_send boolean | Root workflow override disables all three; API reloaded | Retire or centrally migrate; authenticated exact approval for Sign; historical drafts are not real sends |
| P13-H03 Development worker retirement could be reversed by legacy units | Disabled units/code/authority remain installed; no independent retirement condition | Absent root authorization-file condition on all six service/timer units | Archive/remove legacy infrastructure later; intentional root changes remain possible |
| P13-H04 PDF CRM/WorkDrive and unauthenticated job result paths | Actual JSON had both enabled; direct httpx CRM writer, no protection/version fence; status routes unauthenticated | Both provider flags false; public PDF and all core job-result aliases403 | Validate per-record acknowledgments, authenticated storage and canonical ownership; configured Fiches_Techniques read failed |
| P13-H05 Backup omitted safety-critical root state and timers | Original 1.0.1 archive omitted /var/lib/optibrain, documents, runner/helpers and timer/drop-in recovery; only main DB online-snapshotted | Installed 1.0.2 scope correction; every additional application .db online-snapshotted; fresh archive, isolated restore and encrypted upload passed | Keep corrected helper through deploy/restore; retention and fresh decrypt proof remain |
| P13-H06 Legacy core site/password/Omada jobs could still cause provider/infrastructure writes | API-key authenticated jobs call WorkDrive/Omada outside business policy/real flags | External creation/webhook aliases403, including /workflow aliases; empty-payload denials verified | Centralize/retire legacy execution; internal endpoints are not a real auto-write grant |
| P13-H07 Universal real autonomy contract incomplete | Only 3/23 executor families have central executors; approved dispatch lacks Policy kill input; unscheduled envelope/transition/provider response evidence incomplete; native Forms independent | Real autonomy remains disabled; affected bypasses contained | P0 central coverage, state-loss-safe provider reconciliation, exact human authorization and complete evidence |
| P13-H08 Fresh off-host disaster recovery unproven | R2 hash independently passes, offline identity unavailable by design; prior human attestation not treated as current proof; no replacement-host boot proof | Local isolated restore independently performed; scope fixed; explicit writers-OFF recovery rule | Owner-custody fresh AGE decrypt and full recovery validation; no promised RTO |
| P13-H09 Current API key persisted in historical access journal | Credential-literal scan found SITE_WORKFLOW_API_KEY in uvicorn access journal, consistent with URL-key OAuth flow; scan emitted names only | Disabled raw uvicorn access logging via root override; service/business audit journals retained | Controlled cross-client key rotation, remove URL credentials, preserve private incident evidence. CRM channel credential also needs rotation after inventory-filter exposure |

H01–H06 are fixed or contained. H07/H08 remain prerequisites for real autonomy; H09 is contained against further access logging but rotation remains required. No unsafe real function was enabled to close a finding.

## Medium findings

1. ID generator hashes provider IDs to 48-bit suffixes; raw Lead IDs coexist with operational canonical IDs. Current uniqueness passes; provider-independence and migration claims need revision.
2. Services/Service_Locations are canonical operational structures, but Deal recurrence/date facts and legacy technical-sheet/site/password models remain parallel; recurring display can retain both representations.
3. Three Mail schedulers overlap: Cloudflare, combined GitHub lifecycle and separate GitHub mailbox-poll; separate GitHub owner digest also duplicates daily dispatch. They have different source identities and repeatedly scan Mail. Disabled digest workflows also make old scheduler completion expectations stale.
4. Receipt collector retrieves details/content/header for every known Form message every five minutes; current two messages imply about2,016 Mail GETs/day before other observers. Operator/lifecycle full scans and operations N+1 reads are additional cost.
5. preserve-existing bypasses nominal seven-generation pruning; encrypted cache and ledgers accumulate. Initial local archives approximately5.8GB, encrypted cache7.1GB; disk36% used, no immediate exhaustion.
6. Root runner imports owner-writable checkout/venv code; root JSON registries have atomic replacement without a common inter-script lock. API/PDF/Omada service sandboxing is weaker than timer sandboxing.
7. Full API regression: 783 tests, 36 failures, 0 errors/network attempts. Failures concern old Phase4 resume/permissions, Phase5 campaigns and one Phase6 GateG expectation. Current selected safety tests pass171/171. Latest main deployment workflow failed although guarded production independently matched main; monitoring success alone is insufficient.
8. Exception state/resolution is fragmented across Phase12, core run failures and phase journals. Historical stale/denied fixtures persist; no unified operator acknowledgement/closure contract.
9. Generic shared-key authentication fails open when key absent; production key is set. Fixture-heavy tests do not establish real human approval. Query credentials and broad provider administrative capabilities need separation from business operators.
10. Source IDs have competing uniqueness scopes; connector inquiry_id/source receipt identities and local globally-unique inquiry_id can collide across channels. Connector receipts were persisted after provider effects and concurrent repeat/search visibility were unsafe before containment.
11. Native integration settings/trigger behavior, off-host immutability and reproducible Omada dist provenance remain incompletely evidenced. These are explicit unknowns, not assumed successes.
12. One-use local journals prevent ordinary replay but cannot alone prevent duplicate effects after restoring a generation predating a provider commit. Reconciliation must span that backup gap before any real canary.

## Low / informational findings

Native CRM views can show Test records; sampled OptiBrain live projections did not mix registered synthetic metrics. Native-view metadata for nine affected modules was independently retrieved. General All Leads, All Contacts, All Accounts, All Deals, All Services-, All Service Locations, All Installations, All Tasks and All Cases views can display synthetic records. Opticable Live Leads and Opticable Live Opportunities also exist; their full native criteria were not independently certified by this metadata-only sample. This is possible cosmetic leakage, not proven OptiBrain metric contamination. Five project documents are0644 under root0700 ancestry, so not publicly readable. Legacy artifact timestamps are naive/local and old docs say Montreal despite current America/Toronto semantics. Many preview workers, stale branches, release scripts and old staging DBs remain. The api01 virtual host did not resolve publicly. UDP443 is listened on but not UFW-allowed. WorkDrive/Desk/Gmail/Calendar/ad-platform/native-UI extensions are DEFER — NON-CRITICAL.

## Deployed component inventory

The complete component/source-of-truth map is [the blueprint](OPTIBRAIN_ARCHITECTURE_BLUEPRINT.md). API/PDF/Omada are active localhost services behind Caddy; Python3.12.3, Node22.23.3. Root environment files and OAuth state are private. Five application timers, one Cloudflare scheduler and four GitHub cron workflows are active; development dispatcher/status/usage units are retired. Five workflow SQLite stores plus three historical/staging DB snapshots were recovered. Root registries/journals/documents are safety state, not caches. Integrations include CRM/Mail/Sign/Books reads, connector KV, Cloudflare queue/workflow, GitHub App, legacy WorkDrive/Omada and configured Google/admin/AI/external-provider clients. Optional integrations were not expanded.

Operator routes span Phase8 sales queue/detail, Phase9 source trace/receipts, Phase10 lifecycle/recurring, Phase11 operations/project, Phase12 autonomy/approvals/exceptions and older canary review/consume paths. Twenty-four anonymous/forged GET cases were denied. There is no general Phase12 send execution route. Root authorization and the policy matrix remain separate from API availability.

## Mutation control and data model

See [control matrix](phase13-control-matrix.md): 23 explicitly defined executor families, 3 central; remaining families split safe legacy guards, mandatory migration, blocked/deprecated and forbidden. The only currently enabled scheduled CRM writer is centralized Test follow-up. Mail drafts, send/reply primitives, Sign template sends, WorkDrive folder/document operations and generic provider administration were included. Books denial was tested before transport, not by attempting a real invoice.

Source-of-truth/relationship ownership is documented for all requested concepts in the blueprint. Canonical integrity: **PASS for the current15 crosswalk entries; ISSUE for universal provider-neutral generation/migration claims**. Provider crosswalk: **PASS sampled3 Lab chains**. Test isolation: **PASS sampled OptiBrain sales/lifecycle/recurring/operations/source views; native-provider cosmetic leakage remains**. Real sales has11 rows with11 missing critical facts; real lifecycle41 Accounts has no verified active recurring/actionable date evidence; real MRR/ARR null; Lab MRR840/ARR10,080. Real operations intentionally returns no projects.

## Independent phase validation

| Phase | Classification | What independent evidence confirms / revises |
|---|---|---|
| 6 | PARTIALLY CONFIRMED; whole-system claim needs revision | Core CRM/financial transport fence and hardening exist. Independent connector/PDF/infrastructure bypasses and backup omissions contradict universal safety/recovery |
| 7 | PARTIALLY CONFIRMED | Durable exact canary controls, expired/disabled real policy pins and current record readability are credible. Live authenticated human approval and complete disaster recovery are not proved by fixture success |
| 8 | PARTIALLY CONFIRMED | Provider-backed sales scenarios, waiting/replied/due/duplicate/quote previews and current Lab separation confirmed. Real data incomplete; individual controlled views do not prove a complete real sales engine |
| 9 | CLAIM NEEDS REVISION | Existing cross-source attribution chain, immutable local receipts and guarded enrichment proof confirmed. Public connector mutation, replay/ambiguity boundaries and real enrichment authority were outside central guarantees |
| 10 | PARTIALLY CONFIRMED | Services/Sites, recurrence normalization, dormancy suppression, unknown real revenue and Lab-only totals confirmed. Real service dates/revenue readiness and parallel Deal model remain blocked/debt |
| 11 | PARTIALLY CONFIRMED | Three Lab project chains, accepted Deal/customer/site links, work/service/ticket/repair trace, document hashes and terminal-event stability confirmed. Live operations discovery is intentionally empty; IDs are provider-derived |
| 12 | PARTIALLY CONFIRMED | Bounded Test runner, exact ownership, lock, one-use approval, stale/replay denial and ambiguity handling confirmed. Boundary is not universal; approved kill, full evidence and real human/data/recovery gates remain incomplete |

No replacement percentages are invented; percentages from prior reports are not used in the verdict.

## Autonomy and kill-switch verdict

Real automation safe today: **NO**. Exact blockers are H07/H08/H09 and P0 action-specific data/ownership gates. Policy.from_environment does not grant real writes; real targets are denied even with Test flags enabled. Protected IDs override a forged Test marker/registration. Runner fresh reads and lower root fence prevent a scheduled Test envelope resolving to a protected real target. Current Test runner is limited to four due proposals/two writes/180seconds; observed audit runs wrote0.

Automatic-dispatch kill checks passed and reconciliation/reads/backups remain independent. Approved-dispatch policy and legacy/external producer coverage are incomplete. Do not call the kill switch universal. The root CLI-controlled R3 Test Mail action is consumed; no general real send endpoint is enabled. Real canary conditions and all three candidate assessments are in [the backlog](phase14-optimization-backlog.md).

## Recovery and disaster tabletop

Local backup: **PASS after scope fix**. Off-host delivery/ciphertext integrity: **PASS**. Fresh off-host decryption: **ISSUE / UNPROVEN**. Isolated plaintext restore: **PASS**; eight databases, all checked hashes, source/config metadata. Master runbook: **critical correction supplied; full host recovery remains unproven**. Nominal daily RPO; RTO unknown, likely manual hours plus provider/key reauthorization, not a measured guarantee. Final local generation20261001T185502Z restored1,279 files,1,460 metadata entries and8 DBs. All five sampled final safety-control files exactly match archived contents; R2 ciphertext SHA256 2c84855727e40371a6563a72384db7cac3b52c25092b7f119688c3c3dbba9404 independently matched. See [closure evidence](phase13-evidence/completion.json).

| Scenario | Detection / containment | Recovery / source of truth | Maximum likely loss / uncertainty |
|---|---|---|---|
| A VPS lost | External health failure; leave writer/development units OFF on replacement | Offline decrypt corrected R2 generation; restore code/config/registries/DBs; independently reconcile CRM/Mail/GitHub/Cloudflare | Local evidence/docs/approvals since last daily backup; real business facts remain in providers; key and boot proof required |
| B CRM token revoked | Provider authentication failures, timer journals/exceptions | Suspend attempts, retain ambiguity evidence; owner reauthorizes canonical OAuth, prove reads before writes | Read freshness/downtime; no automatic mutation replay |
| C Zoho unavailable | HTTP/error journals, execution health | Reads may use explicitly configured standby; mutations never fail over after transport; preserve pending/ambiguous work | Delayed intake/read/reconciliation; outcomes after transport unknown until provider returns |
| D Local ledger corrupted | SQLite integrity/startup error or missing state | Stop affected writer; isolate corruption; restore last good online snapshot; reconcile provider effects in backup gap | Up to one backup interval of local evidence; blind restore/resume can duplicate effects |
| E Deployment broken | Health/release exact-SHA check, systemd failure | Reviewed rollback SHA and root controls; preserve registries and containment; use installed recovery helper versions | Availability interruption; latest generic deployment failure proves tooling is not uniformly reliable |
| F Timer creates exceptions | Runner counters/exception views, journal failure | Kill mutations while reconciliation remains active; bound batch, triage exact target/source; do not enable real flags | Operator backlog/local state growth; no protected writes under current fence |
| G Ambiguous provider write | Journal attempted/reconcile, transport/ack/readback mismatch | Read exact provider target/request identity; resolve effect once; no resend until outcome proved | Unknown single effect, not safely measurable from local state alone |
| H Accidental Test leakage | Compare live/Lab IDs/totals, inspect native views/exports | Pause affected metric/export/action, read-only classify, repair filter under later authorization | Read/metric credibility; native UI presence differs from contamination; exports remain disabled |

Restore is non-destructive: no production file/database was overwritten by the drill, no restored service was started and no offline private key was requested or copied onto the VPS.

## Security, efficiency and coverage

SSH key-only/root login disabled, UFW22/80/443TCP, internal services localhost, TLS health readable. Operator JWT signature/issuer/audience/allowed human checks are configured consistently; actual human browser approval is still unproven. Environment/OAuth/root state are private. Current credential literals absent in scanned Git history/shell history; current API key was found in private access journal and future raw access logging disabled. An audit filter also exposed the CRM channel credential in tool output; saved evidence was redacted without reproducing it. Historical/rotated secrets were not exhaustively certified absent.

No runtime provider text→shell path found; parameterized SQL/static schema identifiers, escaped operator HTML and safe project filenames reviewed. Current document hashes and root ancestry passed. Unbounded upload/job queues, broad administration privileges and legacy HTTP-only provider-success interpretation remain containment/remediation subjects.

Provider rate risk is **MEDIUM**, not a measured present quota outage. Existing usage/journal counters and bounded scans support repeated-read waste; no broad performance benchmark or intrusive scan was performed. State/backup growth has no proven sustainable retention. Local OAuth cache coordination is better than old per-job clients. Monitoring spans journals/API/GitHub rather than one accountable operational view.

Missing tests prioritized: production connector→central receipt/ownership/replay concurrency; native Forms protected update denial; lost-journal provider-commit recovery; live human JWT issuance/consume; universal approved-path kill; root registry concurrent writes; malformed/ambiguous provider acknowledgments across every legacy client; full replacement-host restore with timers OFF. Existing tests cover exact CRM grants, protected spoof, Books/method/path denial, one-use/stale approval, runner lock/batch/kill, DST, Lab exclusion, lifecycle unknown/MRR suppression and terminal-event replay. Fixtures do not replace provider-backed proof.

## Every Phase 13 change

1. /etc/optibrain/phase9-form-enrichment.env: policy OFF; receipt/reconciliation timer retained.
2. /etc/optibrain/phase13-observe-workflows and workflow API root drop-in: disabled email-analysis, digest and contract-send; retained read observers; restarted API.
3. Six development service/timer drop-ins: absent root authorization-file condition; no development unit enabled/started.
4. Connector source: unconditional provider write guard plus bounded read-service/path/override guard and zero-transport tests; initial commit f309bc55ac5b48cb717897f4704bdb6805176d67, final test correction ed9c49155da5eead442a2a951d94816eca5daa71; PRs30–32, final merge/deploy ataa1e084b06184df73847639700a8e540bd433293. Existing binding identities preserved; deployment annotations changed. Standard deployment generated/replayed an isolated .invalid dry-run receipt, not a CRM record.
5. PDF brand_settings.json: crm.enabled and workdrive.enabled false; service restarted.
6. Caddy ordered route guards: external Omada non-health, unauthenticated job-result aliases and legacy provider job-create aliases blocked. Validation and public route checks passed. All three public service health routes remain200.
7. Installed backup helper1.0.2 / audit-branch source: corrected root/timer/helper/document coverage and online snapshots; excluded encrypted cache recursion. New archive/drill/encrypted upload/readback performed without production restore.
8. Workflow API uvicorn root override: --no-access-log to prevent further URL credential logging. System/service errors and business audit stores retained.
9. Authoritative blueprint, matrices, sanitized evidence, backlog, master-runbook critical override and root recovery copies. No cleanup/deletion, new business feature, Test Lab expansion, real canary or Phase14 implementation.

## Authoritative artifacts and stop decision

- Architecture/source-of-record/canonical model: [OPTIBRAIN_ARCHITECTURE_BLUEPRINT.md](OPTIBRAIN_ARCHITECTURE_BLUEPRINT.md).
- Mutation/control matrix: [phase13-control-matrix.md](phase13-control-matrix.md).
- Timer matrix: [phase13-timer-matrix.md](phase13-timer-matrix.md).
- P0/P1/P2/P3, deprecations and real-canary gate: [phase14-optimization-backlog.md](phase14-optimization-backlog.md).
- Sanitized evidence: docs/phase13-evidence; private detailed reads under /home/optibrain/phase13-evidence and root /var/lib/optibrain/phase13.
- Updated recovery-critical master reference: [OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md](OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md); core deployed historical copy remains at its audited SHA.

**Phase13 status: COMPLETE as an independent audit, with required remediation. Recommended next manual mission: Phase13 remediation, not Phase14 optimization yet.** Objective: close P0 universal mutation/ownership/approval/reconciliation and recovery/credential gates while keeping real/protected mutations0. Why: critical bypasses are contained, but architectural readiness C cannot be resolved by cosmetic/performance cleanup. Expected real mutations0; protected mutations0. Human authorization required: YES, through a new manually initiated instruction. STOP; no next mission begun.

## Audit coverage index

| Requested area | Independent evidence / outcome |
|---|---|
| 1 Deployed system | Live Git/remote SHA, process/unit/env/listener/state inventory; root helpers and connector separately identified |
| 2 Worker retirement | Services/timers/crons/processes checked; six absent-authorization conditions added |
| 3 Application timers | Five systemd timers plus provider/GitHub schedules mapped with actual users/timeouts/failures |
| 4 Architecture map | Maintainable Mermaid and deployed component table |
| 5 Data model | All requested concepts/source-of-truth/relationships in blueprint |
| 6 Canonical IDs | Fifteen entries/three chains sampled; uniqueness passes, independence claim revised |
| 7 Protection | Original99 + service/site24; hashes/readability/no overlap/current versions verified; spoof denied |
| 8 Test isolation | Live/Lab sales/lifecycle/recurring/operations/source views and native view metadata; exports disabled |
| 9 CRM mutators | AST/dynamic/direct-HTTP/provider-source searches; control families and concrete files enumerated |
| 10 Central coverage | Explicit23-family denominator,3 central; scheduled CRM1/1 central; native Forms separate |
| 11 Mail | Draft/send/reply/generic paths, historical drafts, restricted R3 evidence reviewed; no audit send |
| 12 Finance | Books/synced modules denied before OAuth; connector boolean bypass contained; no real financial test |
| 13 Intake | Public AI/main-site/Form→Mail/CRM→collector/identity/queue traced; current connector ingestion blocked |
| 14 Form fallback | Exact receipt/creation/uniqueness/version/replay controls reviewed; real flag disabled; native mapping deferred |
| 15 Dedupe | Exact/new/possible/ambiguous/replay/return branches; connector first-match flaw; no merge authority |
| 16 Sales | Existing provider Lab queue states and live missing-data readback; recommendations nonexecuting |
| 17 Attribution | Existing Phase9 Lead→Contact→Deal first source plus three cross-source intake events verified |
| 18 Lifecycle | Recurring suppression, unknown real revenue, one-time normalization and Lab totals confirmed |
| 19 Services | Services/Service_Locations canonical; Deal/technical-sheet parallel models documented |
| 20 Operations | Accepted Deal→work→Service→Case→repair chain; current statuses/provider links checked |
| 21 Documents | Five hashes/path ancestry/permissions pass; LOCAL FOR NOW; no migration |
| 22 Events | Distinct ledgers inventoried; duplicate terminal fix verified; historical lifecycle store redundant |
| 23 Journal | Fields/state/envelopes/response retention limits and credential-literal scans reviewed |
| 24 Approval | One-use/expiry/hash/target/actor/version checks; actual human flow unproven |
| 25 Exceptions | No-op suppression present; persistent stale/denied/resolution fragmentation documented |
| 26 Runner | Live timer/lock/root scope/bounds/timeout/flags/journal; writes0 observed; ownership denial tested |
| 27 Kill | Automatic dispatch and reconciliation independence pass; approved/legacy universal gaps explicit |
| 28 Flags | Effective environment and code references inventoried; Test1 vs realOFF distinguished |
| 29 Auth | Actual Access app audience/issuer, anonymous/forged24 denials, legacy route gaps contained |
| 30 Permissions | Effective ancestry/owners of code/env/state/backups/docs/units checked; no needless chmod |
| 31 Secrets | Current literal Git/history/file/journal scan; URL-key leak contained; filter error disclosed/redacted |
| 32 Network | ss/UFW/Caddy/SSH/TLS HTTP; no intrusive external scan |
| 33 Injection | Shell/SQL/HTML/path/provider input code reviewed; root-safe document and action boundaries |
| 34 State | Five active and historical stores, schemas/integrity/concurrency/recovery/growth inventoried |
| 35 Backups | Original scope defect, timers/retention/local integrity/offhost object independently audited |
| 36 Restore | Isolated installed drill repeated on corrected archive; eight DBs/hashes/source/config pass; decrypt unproven |
| 37 Recovery docs | Critical master override and root copies; no promised full-host boot/RTO |
| 38 Disasters | A–H tabletop above, with containment/source/loss limits |
| 39 Deployment | CI/main/faileddeploy/guarded release pins/source hashes/rollback evidence reviewed |
| 40 Git hygiene | Local/remote refs/worktrees/tags/dirty diagnostic inventoried; no deletion; dangerous old branches listed |
| 41 Dead systems | Worker/legacy mutators/release helpers/preview/staging stores backlog; no cleanup scope expansion |
| 42 Performance | Bounded repeated scans, N+1, overlap, locks and growth reviewed; no speculative optimization |
| 43 Zoho usage | Read-call estimates and cache/refresh behavior, current journals; no unnecessary quota stress |
| 44 Errors | Central no-blind-retry/ambiguous behavior vs legacy HTTP-only/swallowed/read fallback limits reviewed |
| 45 Timezone | Toronto business/display and semantic UTC checks/DST tests; legacy naive artifacts noted |
| 46 Tests | Critical-property mapping;171 focused pass;783 full/36 failures retained; missing-production tests prioritized |
| 47 Provider evidence | Registered IDs resolve, cross-source chain/current operations/docs sampled; no recreated Labs |
| 48 Real readiness | Sales/data-quality, lifecycle unknowns, empty operations and no authorization classified |
| 49 Three canaries | All disabled; action-specific readiness/gates in backlog |
| 50 Operator UX | Many endpoints/exception surfaces; consolidation deferred |
| 51 Doc drift | Central/universal safety, runner installation, backup scope and ID claim contradictions identified |
| 52 Severity | Two critical, nine high, medium/low distinctions with containment/open risk |
| 53 Fix policy | Only bounded safety/recovery containment plus evidence/docs changes; explicit list |
| 54 Revalidation | Protected123/currentflags/operator denial/runner0/Books denial/worker retirement/backup readback |
| 55 Targeted testing | Direct transport-denial harness, connector23, safety171; one comprehensive783 justified by audit confidence |
| 56 Blueprint | Authoritative deployed architecture document created |
| 57 Record matrix | Complete source-of-truth table in blueprint |
| 58 Control matrix | All23 families and central/lower/approval/reconcile/real authority dimensions |
| 59 Timer matrix | Canonical matrix with real unit properties and external schedules |
| 60 Phase14 backlog | P0–P3 prioritized, no Phase14 mission begun |
| 61 Deprecation | Worker/code/branches/staging/preview/flags retirement list |
| 62 Canary gate | Exact one-action owner authorization and all safety/recovery prerequisites defined |
| 63 Domain scores | Independent qualitative scores above; no prior percentages |
| 64 Readiness | C; no real canary enabled |
| 65 Completion | Evidence/maps/paths/boundaries/recovery samples/P0 known/artifacts; no uncontained critical issue concealed |
