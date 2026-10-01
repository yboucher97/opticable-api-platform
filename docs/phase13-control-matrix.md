# Phase 13 authoritative mutation/control matrix

Current disposition after P0 remediation, 2026-10-01. Read [the final report](phase13-remediation-final-report.md). Inventory includes dynamic/direct provider transports, create/update/convert/merge and POST/PUT/PATCH/DELETE, not just conveniently named executors. Native Forms is a separate external producer. Raw call sites remain in phase13-evidence/mutation-call-sites.json and Git history.

## Current control coverage

23 code executor families were found. At audit three families contained a central executor (3/23 =13.0%); that was not universal policy coverage. **Now only ONE provider-write family is admissible and it is central (1/1 =100%). The other22 families have no active business-write authority and are disabled/forbidden at transport.** Test root and runner kills remain OFF. This denominator measures executor families, not test coverage, call volume or real readiness. Native Forms is outside it and needs MANUAL-01.

All Zoho non-GET operations require the universal root control and one-use central context before OAuth and recheck before HTTP. Only exact registered TEST_ONLY `crm.task.create` is admitted, with root fresh locked off-host claim, attempted immutable journal evidence, exact client/body/path/action, fresh target and independent lower CRM/Test ownership fence. Lower legacy grants cannot override this. Missing/corrupt/untrusted controls deny. Books, Mail/Sign/drafts, real targets and every other action class are forbidden. GET executable/action/Creator/traversal/query-embedded/method-override paths are blocked. No automatic mutation retry or standby failover.

| # | Family | Current authority / central classification | Provider reconciliation / future requirement |
|---|---|---|---|
|1|crm_leads normalize/upsert/Task|FORBIDDEN; legacy guard retained, MUST MIGRATE before real use|New central exact ownership/fresh state/effect contract|
|2|Phase7 update canary|FORBIDDEN; SAFE LEGACY GUARD retained, no transport|Pinned one-use evidence not real authority|
|3|Phase7 new Lead create|FORBIDDEN; SAFE LEGACY GUARD retained|Provider state-loss-safe create claim/reconciliation required|
|4|Forms fallback enrichment|DISABLED +FORBIDDEN; MUST MIGRATE|Existing exact receipt/timeline/identity/version/replay guard is not universal policy; root OFF|
|5|Phase8 seed/transitions/relationships|FORBIDDEN; legacy Test guards retained|Manual historical evidence readable; no new legacy effect|
|6|Phase8 manual Task artifact|FORBIDDEN; legacy guard retained|Use only admitted central Task if separately technically authorized|
|7|Phase9 adoption/intake/outcome scripts|FORBIDDEN; legacy Test guards retained|Source namespace/immutable receipt claim required before reuse|
|8|Phase10 Services/Sites/Deals writes|FORBIDDEN; legacy guards retained|Each step centralized before future use|
|9|Phase11 Work Order/Case/Service/relations|FORBIDDEN; legacy guards retained|Partial-step recovery/compensation required|
|10|Phase12 exact Lead follow-up Task|CENTRALIZED; TEST_ONLY ONLY; root killfalse and runner auto0|Locked R2 conditional claim; exact action marker/target/hash; readback/result; empty-local-journal recovery proven|
|11|Phase12 accepted-Deal onboarding|FORBIDDEN despite central proposal/executor code|Multi-step transport/recovery not admitted; MUST MIGRATE before real use|
|12|CRM field/schema mutators|UNUSED /DEPRECATE in runtime; FORBIDDEN|Technical mission administration separate explicit root authority|
|13|CRM workflow/webform/watch adapters|FORBIDDEN in runtime; narrow watch rotation completed as root administration|Provider current credential/expiry verified; renewal not generic business authority|
|14|Public connector intake create/update|FORBIDDEN before OAuth; MUST MIGRATE if reopened|Former first-match/latest-field/KV-after-effect design unsafe; public ingestion suspended|
|15|Generic connector Zoho/Books/MCP write|FORBIDDEN before OAuth|Caller confirm/Books boolean never sufficient|
|16|PDF CRM password-field writer|RETIRED at source +configOFF; UNUSED /DEPRECATE|Direct mutation raises before transport|
|17|Mail draft/email analysis/digest|DISABLED +FORBIDDEN|Thread/draft ambiguity needs central effect recovery before any reuse|
|18|Legacy outbound send/reply|FORBIDDEN; legacy exact guards retained|No general send/reply/forward/draft authority|
|19|Phase12 approved Test Mail|FORBIDDEN at universal transport, approval machinery retained|Kill before one-use consume; exact actor/target/payload/expiry/state; real human flow unproven|
|20|Sign contract send|DISABLED +FORBIDDEN|Shared-key/approved_to_send boolean not human approval|
|21|WorkDrive folders/upload/move; core/PDF|RETIRED direct mutators +FORBIDDEN|Keep local documents; future provider ownership/hash/recovery contract|
|22|Omada/core legacy password/site jobs|RETIRED routes403; Omada health-only|No infrastructure jobs, sessions/uploads/run queues opened|
|23|Generic Google/Zoho/CF/GH/OVH/Apollo runtime mutators|FORBIDDEN; CF/GH technical administration root one-use only|Service UID cannot mint technical authority; no unattended business grant|

Native Zoho Forms can create/update CRM without passing through either core or connector. Available supported API/scopes cannot prove native integration deactivation; exact owner UI steps are MANUAL-01, BLOCKS P0 CLOSURE. Do not label this producer OFF until provider owner readback exists.

## Independent lower and evidence controls

Protected IDs override TEST_ONLY flags, root registry entries and name markers. Protected-ID spoof is denied before provider auth/transport. Cross-record target relationships are freshly checked. The admitted Task must link an exact registered nonprotected Lead and stable action marker/payload hash. The fresh R2 claim is consumed once, an existing/uncertain claim only permits read-only reconciliation, and a locked duplicate returns reconciliation-only even when R2 reports ObjectLockedByBucketPolicy. Journal/run context precedes attempted/transport; immutable envelope and append-only hash chain permit reconstruction. Legacy histories remain incomplete.

Mail POST/PUT/PATCH/DELETE and Books/Sign operations were tested with intercepted transport: all denied before OAuth/HTTP. No real send or financial test. The old R3 Test script cannot expose a general send endpoint or override root kill. Unset shared-key auth503, wrong401, URL key400; operator Access validates JWT/issuer/audience/allowed identity. Real human interactive approval remains a future gate, not evidence inferred from local fixtures.

## Historical call-site detail

The following preserves the original audit classifications and describes the former protections; **current authority is the table above**. Keeping this detail prevents mistakenly treating a central proposal as a migrated legacy executor. Historical 'enabled' entries are not authorization.

| # | Executor / module / action / caller | Phase 12 coverage / classification | Lower protection | Idempotency / reconciliation | Current real authority |
|---|---|---|---|---|---|
| 1 | crm_leads.write_once; Leads normalization PUT and internal Tasks POST; enabled CRM reconcile workflow | SAFE LEGACY GUARD; migrate before real autonomy | Exact ContextVar call grant, policy flag, field allowlist, version header | Core step evidence/readback; deterministic Task subject | OFF; OPTIBRAIN_CRM_LEAD_WRITES absent |
| 2 | phase7_crm_executor.execute_approved_canary; one Leads PUT; operator canary consume | SAFE LEGACY GUARD | Pinned durable approval, exact target/version/hash, single-call firewall | One-use ledger, exact readback, ambiguous quarantine | OFF; canary policy/approval pins absent |
| 3 | phase7_lead_create.execute_approved_create; Leads POST; operator create consume | SAFE LEGACY GUARD | Exact new-identity preflight, approval/policy pins, trigger/cadence suppression | Durable single-use create ledger; provider proof | OFF; create policy/pin absent |
| 4 | phase9_form_enrichment.enrich_form_leads; Leads PUT; five-minute collector | MUST MIGRATE BEFORE REAL AUTONOMY | Protected manifest, exact authenticated receipt/timeline/name/company/phone, empty-or-equal fields, unique email, version | Pre-attempt append journal, exact readback; uncertain attempts not resent | WAS enabled for real post-baseline Leads; Phase 13 set OFF |
| 5 | Phase 8 seed/transitions/relations scripts; Leads/Contacts/Accounts/Deals create/update | SAFE LEGACY GUARD; manual Test-only | Root Test flag; registry/manifest hashes; markers; exact relationships; reviewed_test_lab_call | Per-script root evidence; variable local journals; no universal runner | No real grant |
| 6 | Phase 8 create_test_artifacts; exact follow-up Task POST | SAFE LEGACY GUARD; manual Test-only | Separate hardcoded Lead and payload grant | Deterministic subject/readback and root evidence | No real grant |
| 7 | Phase 9 intake/adoption/outcome scripts; Lead/related records PUT/POST | SAFE LEGACY GUARD; manual Test-only | Root exact Test ownership fence and prior IDs | Multiple phase registries/journals; provider readbacks | No real grant; public connector calls now blocked |
| 8 | Phase 10 test_lab_lifecycle.write; Deals/Services/Sites and relationship facts | SAFE LEGACY GUARD; manual Test-only | Root Test fence and service baseline | Attempt key/hash, readback, local lifecycle evidence | No real grant |
| 9 | Phase 11 test_lab_operations.write; Services/Installations/Cases/Deals/Tasks create/update | SAFE LEGACY GUARD; manual Test-only | Root owned target/references, version precondition, trigger/cadence suppression | Attempt before transport, acknowledged ID, exact field readback; no blind retry | No real grant |
| 10 | Phase 12 runner task executor; Tasks POST linked to exact Lead | CENTRALIZED | Fresh provider ownership/version/state plus root legacy Test writer/fence | Central action/request key, scheduled envelope, root operation ID, exact readback | TEST_ONLY enabled; real denied |
| 11 | Phase 12 onboarding executor; accepted Test Deal → project/Service/Installations/local folders | CENTRALIZED for this executor; manual operations remain family 9 | Central fresh ownership plus root multi-record relationship fence | Central proposal and root step journal; partial operations need reconciliation | Test project flag OFF; real denied |
| 12 | CRM field reconciler; POST/PATCH/DELETE /settings/fields; desired-state apply | UNUSED / DEPRECATE for general mutations; FORBIDDEN under current gateway | Gateway requires authority; generic workflow action blocks CRM; no general schema grant | Desired-state plans, audit; no usable general record-write authority | OFF/denied |
| 13 | CRM workflow/webform metadata and watch adapters; settings POST/PATCH/DELETE | UNUSED / DEPRECATE or narrowly reviewed administration | Generic CRM firewall; no broad administrative grant | Plan/evidence tools; active watch expiry needs controlled renewal | General writes denied |
| 14 | Public connector crmCreate/crmUpdate/routeCanonicalInquiry; Leads/Contacts/Deals | MUST MIGRATE BEFORE REAL AUTONOMY | Previously Origin/consent only, first search match; now unconditional non-GET/HEAD transport guard | Previously KV receipt after effect, no pre-transport claim; latest-field replay not immutable history | ALL provider writes contained |
| 15 | Generic connector Zoho POST/PUT/PATCH/DELETE; internal REST and MCP tools | FORBIDDEN until bounded redesign | Former boolean confirm/books_human_approved; now unconditional pre-OAuth write denial | Audit KV only; no central effect reconciliation contract | ALL provider writes contained |
| 16 | PDF ZohoCrmClient.update_generated_password_fields; configured Fiches_Techniques PUT | MUST MIGRATE / DEPRECATE | Direct httpx.put, no CRM manifest/firewall; configuration and public entrypoints now disabled | HTTP-only success test; no per-record acknowledgment proof or version fence | CRM enabled changed true → false |
| 17 | lifecycle Mail draft writers: mail_drafts.save_mail_draft, email analysis, digest; sales_drafts | MUST MIGRATE BEFORE REAL AUTONOMY | Gateway reason/confirm; sales draft policy absent; root workflow override disables analysis/digest | Variable draft/thread evidence; legacy ambiguity not a central approval | Analysis/digest disabled; sales draft observe-only |
| 18 | outbound_mail.send and lifecycle_mailbox.send_approved_reply; Mail messages POST/reply | SAFE LEGACY GUARD or blocked legacy path | Exact outbound/Phase 7 grant; disabled approved-reply workflow | One-use legacy approval, threading/preflight; no unrestricted send action | OFF; policies absent, disabled workflow |
| 19 | Phase 12 approved_test_mail; Mail messages POST | CENTRALIZED controlled R3 Test path | Fixed mailbox and controlled Test identity, payload/approval/freshness binding | One-use approval; provider sent-message readback; ambiguous stays reconciliation | Manual Test-only; no general HTTP send route |
| 20 | lifecycle_phase2.send_contract; Sign template createdocument POST | MUST MIGRATE BEFORE REAL AUTONOMY | Previously caller approved_to_send boolean, shared API credential | Core audit only; not authenticated exact human approval | Root workflow override now disabled |
| 21 | Core/PDF WorkDrive upload, folder create/move/archive; direct HTTP | MUST MIGRATE BEFORE REAL AUTONOMY | Shared OAuth; path/folder handling; no business policy | Filename/archive conventions; no central approval or universal effect ledger | PDF WorkDrive false; external legacy core jobs blocked |
| 22 | Omada runPlan / API runs start / core site-password jobs | MUST MIGRATE BEFORE REAL AUTONOMY | Public /api/runs/start lacked auth; webhook token only covered some routes | In-memory queue/report + persisted plans; no central infrastructure approval | External non-health and job-create aliases blocked |
| 23 | Generic Zoho/Google/provider administration actions and desired-state apply | MUST MIGRATE / FORBIDDEN for consequential unattended changes | API key, reason/confirm, service/path allowlists; CRM/Books gateway independently blocks | Core operation audit; variable provider evidence | No scheduled general mutator found; privileged legacy/manual capability remains |


Do not reopen forbidden executors by flags alone. New real action classes require exact owner authorization and every gate in the final report. Phase14 has not begun.
