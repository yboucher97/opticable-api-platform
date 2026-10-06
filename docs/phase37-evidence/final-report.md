# Phase 37 — Business Manager and continuous optimization control center

AUDIT EVIDENCE. **PHASE 37: PASS.** This report records production verification, honest coverage limits and the stopping point. It grants no execution authority.

**Production SHA:** `205b217546372dfd37850da7721d9bba61a0746a`

**API:** 1.28.0

**Snapshot:** 2026-10-06T01:46:04.690346+00:00 (October 5, 2026 21:46 America/Toronto)

**Implementation:** [PR 131](https://github.com/yboucher97/opticable-api-platform/pull/131); reviewed exact head `209ce502a932215a2bea0bafd8959f27407b1c2e`, PR CI 37400039130 and production main CI 37400136845 passed. Exact-SHA canonical deployment and current-release verification passed.

The manager consolidates existing source, Optimization Proposal, Business Priority and asset stores. Durable event references, crosswalks, owner feedback, briefs and learning live in the existing protected/recoverable `phase12-autonomy.db`. No parallel proposal/priority store, second orchestrator, new timer, persistent development worker or provider writer was created.

## Business Manager

[Owner Manager](https://optibrain.opticable.ca/v1/operator/manager) · [machine JSON](https://optibrain.opticable.ca/v1/operator/manager?format=json) · [contract](../OPTIBRAIN_MANAGER_CONTRACT.md) · [schema](../optibrain-manager.schema.json). Existing Cloudflare Access owner authentication is required.

| Section | Current behavior |
|---|---|
| Today | At most 5 high-value current actions with evidence and detail links; genuine Forms receipts are separate from TEST. |
| Sales | 3 high-attention conversations, 8 draft-ready contexts; 4 persisted reply proposals; Apollo/Claude ownership preserved. |
| Acquisition | 291 retained signals, 119 organizations, 18 current-trigger prospects, 11 shadow-prospecting-ready; legitimate weak prospects retained. |
| Customers | 42 observed native CRM Accounts; paying-customer count UNKNOWN. Existing relationships are separate from cold prospects. |
| Recurring | 23 Books profiles, 19 active; service/profile linkage incomplete. Billing profiles never become invented service relationships. |
| Marketing/content | Shared content/assets/hook evidence, 8-channel repurposing briefs and review-only queue; Holo optional. |
| Website/SEO | Search Console/GA4 evidence, existing landing previews and bounded local copy/FAQ/link/creative drafts. New drafts need selected repository branch/build mapping. |
| Ads | 4 campaign proposals plus cleanup and measurement; proposed FR camera pilot CAD 420/28 days, owner maximum CAD 500; no mutation. |
| Finance | Dated Books/CRM observation, Estimate/Invoice/recurring context where deterministic; current aggregate STALE, margin UNKNOWN. |
| System | Separate authentication/data health, source clocks, actual receipts, authority state and meaningful blockers. |
| Owner actions | Feedback, useful current dependencies, upcoming authority review and trigger-conditioned deferrals. |

GET reads bounded local stores/caches and makes no provider/model calls. Stable schema 1 provides top priorities, counts, health and detail IDs. Limits: Today 5; proposals/priorities/events 50 each; no raw provider universe returned. Search/filter supports bounded query, domain and status. The concise cached brief covers changes, Sales, Acquisition, Customers, Marketing/SEO/Ads, prepared proposals, blockers and 3–5 priorities.

## Current snapshot

| Population | Observed value |
|---|---:|
| Genuine acknowledged native Forms inquiries | 2 |
| Diagnostic TEST submissions | 7 |
| Sales high-attention conversations | 3 |
| Draft-ready conversation contexts | 8 |
| Acquisition organizations / retained signals | 119 / 291 |
| Current-trigger prospects / repeat buyers | 18 / 26 |
| Shadow-prospecting-ready | 11 |
| Organizations needing contacts / domains | 107 / 64 |
| Unknown identity collisions | 68 |
| Observed native CRM Accounts | 42 |
| Paying customers | UNKNOWN |
| Observed native open Deals | 1; older projection, value UNKNOWN |
| Shared Optimization Proposals | 31 |
| Shared Business Priorities | 44 |
| Shared structured assets | 24 |
| Manager events / exact relationship links | 249 / 396 |
| Stored daily briefs / learning | 2 / 0 |

Inquiry counts cover retained immutable acknowledged Forms receipts, not today's new inquiries, every CRM Lead or website visitor. The older Business snapshot observed 13 native Leads; the current full genuine-Lead population is UNKNOWN. The 1 open Deal in that snapshot is 129 days old. 42 CRM Accounts are not asserted to be 42 paying customers. No causal optimization performance or current margin is inferred.

Prepared work is concrete and reviewable in existing proposal detail views: 4 reply drafts, 8 outreach previews, 3 sequence proposals, 4 campaigns, 2 landing pages, 6 new local website editorial drafts, 1 content feedback proposal and 1 customer expansion proposal, plus Ads cleanup/measurement. The Phase 32 content pack remains available; no automatic publication or email sending occurs. The machine report includes every prepared proposal ID and its authenticated preview URL.

## Source health

Authentication success is not data health. Original observed_at, cache age, freshness/confidence and newer-data expectation remain visible. Stale evidence degrades proposal confidence/refresh state rather than acquiring the latest scheduler timestamp.

| State | Sources at report snapshot |
|---|---|
| GREEN | crm, mail, forms, ga4, search_console, google_ads, windsor_keyword_planner, apollo, cloudflare, github, seao, montreal_permit, quebec_permit, company_announcement, website, ai_website, apollo_roles, lovo, montoni, prospect_enrichment, saq_gc |
| STALE | books, windsor |
| PARTIAL | linkedin_organic, laval_permit, competitors, facebook_organic, instagram, permits, registry |
| BLOCKED required source | None at this snapshot; profitability remains a blocked capability. |
| INTENTIONALLY OPTIONAL | workdrive, sign, gbp, holo, ahrefs, clay, semrush |
| OWNER DEFERRED | Google Basic/native keyword_planner; fresh Windsor keyword economics is independently GREEN. |

Optional native GBP profile read lacks `business.manage` OAuth scope. This creates a useful optional action only when native profile verification is desired; it does not block Manager. No new provider, purchase, client or browser-automation dependency was introduced.

Completeness: Sales/Customers/Website-SEO/Content GREEN for stated known coverage; Ads GREEN — WAITING NATURAL DATA; Holo GREEN — INTENTIONALLY OPTIONAL; Acquisition/Finance/Recurring PARTIAL; Profitability BLOCKED. There are no invented completion percentages.

## Autonomy

| Level | What operates |
|---|---|
| Runs unattended | Existing scheduled Forms/service/internal/customer observers and scoped workflows; Sales/Ads preparation; Manager refresh/brief/preview hook; existing normal backup/upload services with receipts. |
| Automatically ingests | Acknowledged Forms/native CRM evidence and existing bounded provider caches; changed IDs/versions produce event references. |
| Automatically analyzes | Deterministic source/authority/freshness, Sales/Ads/acquisition projections, explainable priorities and exact identity links. |
| Automatically prepares | Unsent reply/outreach/customer/sequence proposals, Ads/landing/measurement previews, local website copy/FAQ/links, creative/repurposing briefs and daily brief. |
| Executes with existing authority | Only the original 12 internal / 4 customer scopes under unchanged cutoffs, expiries and effect/replay protections. Release staging neither reset effects nor renewed authority. |
| Owner approval required | Website/Form/GBP/content changes, Ads CREATE_PAUSED/activation, outreach graduation and major operational changes, each with separate exact execution authority. |
| Not authorized | New Ads/outreach/financial mutation, conversion export, English real automation, persistent development worker and financial/legal/destructive automation. |

Unattended receipts at 01:40 and 01:46 UTC prove the Manager hook ran: at most 3 changed local drafts per invocation, 3 reused on the second invocation, no new provider reads, model calls or provider writes. 1 day/7 day operational totals cover retained observed invocations since Phase 37; missing historical execution is not reconstructed from configuration. Apollo/Claude sends are never attributed to OptiBrain.

## Optimization and learning

| Domain | Shared proposals |
|---|---:|
| Website | 8 |
| Forms | 0 — no verified defect warranting a new proposal |
| Ads | 6 |
| Sales/outreach/sequence | 15 |
| Content | 1 |
| Customer expansion | 1 |
| Measured proposals | 0 |
| Learning records | 0 |

The control center shows why, evidence, dated confidence, actual preview, expected benefit, risk, owner action, status and measurement plan. Local APPROVE/REJECT/REQUEST_REVISION and WAIT/NOT_RELEVANT/NEVER preserve version-bound intent. Priority HIGHER/LOWER feedback persists. Approval never grants provider authority, and changed revisions cannot inherit approval. Identical semantic rejected evidence is not immediately reproposed; NEVER survives automatic revisions.

Execution/result schema supports authority, executor, receipt/provider state, measurement start, SUCCESS/NEUTRAL/REGRESSION/INSUFFICIENT_DATA/BLOCKED and evidence. Results require an execution receipt, baseline/post windows, guardrails and limitations. No execution outcome was manufactured in this phase. Fact classes and universal autonomy origins distinguish provider/public facts, user confirmation, deterministic derivation, model inference, estimate and UNKNOWN. Collision handling uses exact provider IDs/crosswalks; uncertain identities remain unresolved.

Website preparation currently yields actual local editorial artifacts; existing Phase 32/33 repository previews remain independently reviewable. New drafts are not claimed as built website branches. Form intelligence knows published identities, embeds, callbacks/attribution, recipient, writer status and telemetry; complete required-field/design/abandonment coverage remains UNKNOWN. Verified gaps can prepare a local mapping/callback/migration draft, but no production Form replacement was performed. Creative/Holo briefs preserve intended audience, service, hook, channel, proof and CTA; no unsupported/private Holo API or automatic publication.

## Top owner priorities

1. Refresh the stale Business/Books observation before using Finance stocks as current.
2. Review protected backup/archive staging growth with controlled housekeeping; retain Golden and evidence.
3. Review the Collège de Maisonneuve tender closing October 7 at 10:00 America/Toronto.
4. Coordinate high-priority meeting/reply drafts through existing Apollo/Claude ownership and verify any manual response first.
5. Review FR camera landing/measurement/pilot previews and evidence-backed website drafts.

## Owner actions

**Blocking selected capability/graduation:** Fresh Finance observation; exact unmatched reply/employer/collision/suppression/manual-contact verification; supported repository branch/build or native Form draft mapping; deterministic job cost allocation for profitability. These are scoped gaps, not a requirement to add unrestricted authority or another provider.

**Upcoming:** Review authority by October 25. Internal expires November 1 at 22:09:41 UTC; customer authority expires November 2 at 02:46:02.366351 UTC. Manager automatically surfaces the review from October 18. Neither expiry was renewed.

**Deferred:** Google Basic only when native fresh Planner economics becomes a material quantitative dependency; AI vendor hosting/legal proof before provider-specific public AI claims. **Optional:** native GBP scope/configuration read and Holo/manual brief handoff. **Waiting natural event:** genuine eligible paid attribution and qualified outcomes, with conversion exports OFF. FR/EN native Form setup/tests are complete; no retest or obsolete setup action remains.

## Finance observation

Books remains financial truth. The aggregate is STALE as of 2026-10-05T19:42:43.989030+00:00. Historical observed October gross invoicing CAD 2787.00, outstanding CAD 5373.94 and overdue CAD 287.44 are dated stocks, not asserted current values or recognized profit. 23 recurring billing profiles include 19 active; normalized observed net billing CAD 1037.50/month and CAD 12450/year is PARTIAL and not a guaranteed forecast. Native service/profile links observed 0; linkage remains UNKNOWN. No fake margin is shown and no financial mutation is enabled.

## System and authority health

| Component | Status |
|---|---|
| API | GREEN — API 1.28.0 exact production source verified |
| database | GREEN — five active checks and eight isolated restore integrity checks passed |
| forms | GREEN — immutable acknowledged native FR/EN intake and success telemetry; detailed design/abandonment UNKNOWN |
| mail | GREEN — existing authenticated observation; five exact reply bodies unresolved |
| CRM | GREEN — native canonical identity reads; selected historical lineage/collision coverage PARTIAL |
| Books | STALE — aggregate Business/Finance observation dated 2026-10-05T19:42:43.989030Z; native Books remains truth |
| GA4 | GREEN — authentication and recent observed events assessed separately |
| Search Console | GREEN — dated native evidence and website opportunities available |
| Ads | GREEN — read/intelligence/preparation; campaigns unlaunched; mutation authority ABSENT |
| Apollo | GREEN — bounded cached research/conversation context; private/manual activity coverage PARTIAL |
| backups | GREEN — generation 20261006T014111Z local/isolated/encrypted readback verified; retained staging growth requires attention |
| schedulers | GREEN — existing bounded internal/customer observers resumed; new Manager unattended receipts verified; no new timer |
| authority | ACTIVE 12 internal / 4 customer original scopes; Ads/outreach ABSENT; exports OFF; English DISABLED; worker OFF |

Internal/customer authority ACTIVE under original 12/4 scopes. Ads/outreach ABSENT; financial writer ABSENT; conversion exports DISABLED/OFF; publication requires separate owner/executor authority; English real automation DISABLED; persistent worker OFF. Original cutoff and claim/effect state stayed unchanged.

## Cost and efficiency

Manager refresh adds 0 provider reads/writes and 0 model calls. Each cycle considers at most 10 opportunities and prepares at most 3 changed local drafts; semantic hashes/cache versions avoid duplicate preparation. Existing Apollo domain TTL/read budgets and Ads refresh cadence remain bounded. Latest observed Apollo reads/credits 0 does not mean total account use or invoices cost 0.

The retained 7 day usage projection includes 201 TEST-job metric receipts; their provider counters are 0. This has limited instrumentation coverage. Uninstrumented provider usage, subscriptions, invoices and model costs are UNKNOWN. Repeated unchanged runs reuse caches; no whole-universe model reconsideration, new LLM worker or endless loop was added.

## Safety

| Invariant | Verification |
|---|---|
| Protected records | 123 / 123 unchanged; seven native GETs, missing 0, modified 0, TEST spoof 0. |
| New financial mutation authority | 0 |
| New Ads mutation authority | 0 |
| New outreach mutation authority | 0 |
| Conversion exports | OFF |
| Persistent development worker | OFF |
| English real automation | DISABLED |
| Unauthorized sends | 0 |
| Authority renewal/effect reset | 0 / 0 |
| CRM/Books/Forms/suppression/replay | Canonical ownership, immutable receipts, existing protected and replay controls preserved. |

## Testing and release

Focused Manager tests: 29. Focused existing integration checks: 86, with final collision/Form-context targeted checks also passing. A–N cover genuine inquiry/event context, high Apollo reply/draft, website and Ads proposals, customer expansion, stale-source degradation, exact collision, durable rejection, intent-only approval, authority deadline, unknown margin, empty brief, provider failure isolation and unchanged-cache reuse.

Final complete fake-provider regression: **1559 tests, 1292 subtests; failures 0, errors 0, skips 0, network attempts 0**. Initial timestamp-only rejection and stale architecture-version failures were fixed before the final gate. Documentation/config/bootstrap contracts passed 225 documents and 261 current links at implementation close; the finalized evidence passes 225 documents and 262 current links. Evidence-only documentation is separately validated after finalization. No expensive local full regression was repeated after the final executable gate.

PR 131 and exact production main CI passed. Canonical root release staged/resumed existing authority without broadening it. Unauthenticated operator origin returns 401; public endpoint redirects 302 through Access. No owner JWT was forged. Live native Forms/customer writes or Ads/outreach graduation were not used as tests.

## Recovery

**Generation:** `20261006T014111Z`

**Source/API:** `205b217546372dfd37850da7721d9bba61a0746a` / 1.28.0

**Archive SHA256:** `df2f94787dd0516b400cc8fcb8b6844f180e7de06d05f46ceb715289589e8541`

**Encrypted R2:** `backups/2026/10/06/20261006T014111Z.tar.gz.age`

**Encrypted SHA256:** `fcf38157b7720ec6135356bde82c3995234cd7423ca49d37c8b08832fda6336f`

**R2 verification:** download_hash_verified at 2026-10-06T01:43:33.052435+00:00.

All eight restored databases passed integrity checks: automation.db, lifecycle-events.db, phase9-intake.before-permission-fix.db, form-receipts-stage.db, phase10-service-events.db, `phase12-autonomy.db`, phase9-form-receipts.db and phase9-intake.db. Exact source HEAD was present in the restored bundle. Manager durable tables were verified: briefs 1, events 246, feedback 0, learning 0, links 393, receipts 7, optimization_records 97 and optimization_reviews 0.

Restore used a prepared isolated filesystem target. No application service boot, OS/DNS cutover or provider call is claimed. Fresh internal/customer authority OFF; Ads/outreach ABSENT; conversion exports OFF; reconstructed timers MASKED; persistent worker OFF. Populated feedback has focused backup/restore coverage; results use the same backed-up SQLite store. Restored records reflect the backup cutoff: 28 proposals, 41 priorities, 21 assets; later normal bounded preparation remains in the live DB/subsequent scheduled backups.

The manual admin backup refused its existing retention-headroom check; the existing reviewed backup service succeeded with preservation enabled. No prior archive was removed. Encrypted upload was downloaded and hash-verified. The owner-held private AGE identity was not used; no new offline decryption is claimed. Golden plaintext SHA256 `ff91b86f3a4f9491158c7e7bcd067ca9cb06bb29b6a424d22dc0c9d31c82d7ba` is unchanged.

Private verification receipts remain in `/var/lib/optibrain/phase37/release`; final public-safe reports contain aggregates and proposal references, not raw provider message bodies or credentials. Final evidence documentation records this executable release and its recovery; later evidence-only commits do not change production executable source.

## Final verdict

1. **Can the owner use OptiBrain as the primary control center?** Yes for daily intelligence, attention, proposals and owner decisions; retain the explicit partial/stale labels

2. **What still needs another platform?** Fresh Books state/full financial transaction context, unmatched Apollo/Mail threads and private/manual Claude history, native Forms design/abandonment, optional GBP configuration; native execution remains in providers

3. **What actually runs unattended?** Existing Forms/service/internal/customer observers and scoped workflows; scheduled Sales/Ads preparation and Manager refresh/brief/preview preparation; normal backup/upload timers have prior execution receipts

4. **What is automatically prepared?** Sales reply/outreach/customer/sequence proposals, Ads campaign/landing/measurement previews, local website copy/FAQ/link drafts and creative/repurposing briefs, daily brief

5. **Which production actions need owner approval?** Website/Form/GBP/content production changes, Ads CREATE_PAUSED/activation, outreach graduation, communication scope expansion; finance/legal/destructive human-controlled

6. **What remains genuinely missing?** Reliable fresh consolidated Finance/job costs, complete identity/manual-thread coverage, native Form design/performance coverage, supported branch/build/provider draft automation across every website/Form, measured executed optimization results

7. **Which proposals are worth approving first?** Current high-priority reply drafts after Apollo/manual-contact verification; FR camera landing and measurement previews; evidence-backed existing service-page improvements. Ads approval is intent only

8. **Where is the biggest Lead opportunity?** Convert verified project/permit/tender intelligence into exact supported contacts: 119 organizations, 107 need contacts, 64 need domains, 68 collisions unknown, 11 shadow-prospecting-ready; FR camera pilot is the next bounded paid experiment, not proven ROI

9. **Where is the biggest operational weakness?** Incomplete/stale business-finance data and relationship lineage; current root observation attention is explicit. Backup staging growth needs controlled housekeeping

10. **What should graduate next?** Selected supported website preview and sealed Ads CREATE_PAUSED; separately approve spending/stop and a small outreach batch only after current collision/suppression checks

11. **Is continuous optimization ready?** Yes for controlled observation, automatic preparation, owner review and future measurement; unrestricted execution remains prohibited

12. **Recommended post-Phase 37 order?** Close controllable freshness/thread/identity and cost-lineage partials → Approve selected concrete previews → Complete branch/build/provider draft preparation → Owner chooses bounded Ads pilot and spend-stop authorization → Graduate separately sealed outreach batch → Extend worthwhile preparation coverage → Measure qualified outcomes in matched windows → Graduate only proven low-risk automatic actions.

Separate future graduations: Ads CREATE_PAUSED; limited-batch outreach; selected Website/Form production; Content publication; customer communication expansion; English automation review. None was executed.

**Stopped after Phase 37. No new phase, Ads activation, new outreach, financial writes or mass publication.**
