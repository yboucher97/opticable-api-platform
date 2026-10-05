# Continuous optimization integration

AUTHORITATIVE CURRENT. This contract defines the shared foundation for later domain phases. **Implemented now: versioned record contracts and a machine-readable schema.** No optimization manager, proposal database migration, endpoint, scheduler, execution adapter or new production authority is installed by this foundation.

The common path is:

`source evidence → normalized entities → derived insights → opportunities → proposals → preview/test → owner review → authorized execution → measurement → results/learning`.

Native facts, estimates and conclusions remain distinguishable. Missing data stays UNKNOWN. A useful opportunity may be retained with weak evidence while execution remains blocked. Existing acquisition/prospect/trigger history and canonical CRM/Books entities remain intact.

## Shared contracts and reuse

Use the [proposal contract](OPTIBRAIN_OPTIMIZATION_PROPOSAL_CONTRACT.md), [authority classes](OPTIBRAIN_AUTHORITY_CLASSES.md), [data architecture](OPTIBRAIN_DATA_INTELLIGENCE_ARCHITECTURE.md) and [business priority contract](OPTIBRAIN_BUSINESS_PRIORITY_CONTRACT.md). The [schema](optibrain-optimization.schema.json) defines proposal, priority and message/creative asset interchange records. It does not execute or approve anything.

Existing `business_autonomy.py` actions, payload hashes, one-use approvals and execution journals remain the execution mechanism; the new proposal envelope references them rather than replacing them. Existing Today attention, acquisition recommendations, trigger reviews, content plans and sales observations remain domain inputs. A proposal ID must not be used as an alternate CRM entity or an unguarded provider idempotency key.

Future persistence should extend the existing research/action journal patterns only when a concrete domain needs it. Preserve an append-only revision, approval, execution and outcome history. Do not introduce a separate warehouse, duplicate approval mechanism or global writer flag merely to implement this contract.

## Preview first

Customer-facing changes normally follow observation, a grounded proposal, a concrete copy/preview, tests, owner review, exact-revision approval and guarded deployment. Preparation authority is separate from publication authority.

| Domain | Reviewable preparation | Production boundary |
|---|---|---|
| Website/SEO/content | Branch, exact diff, supported preview such as testopti, build/link/canonical/hreflang/schema checks, rollback SHA | Owner-approved publication of the exact revision |
| Images/creative | Actual draft asset, visual brief, provider/rights and illustrative status | Owner-approved asset replacement/publication |
| Forms | Supported draft/copy, fields/mapping, attribution/callback, intake tests and migration/rollback plan | Owner approval before switching the production form/embed |
| Ads | Complete campaign/ad/keyword/negative/geography/budget proposal, landing page and measurement plan | Separate Ads execution authorization; none exists now |
| CRM | Proposed field/configuration diff, integration impact and rollback | Exact owner approval; research is not mass-promoted |
| GBP | Grounded profile/post/review-response draft | Owner publication decision; no automatic posting |
| Sales/outreach | Prospect/contact evidence, collision/suppression, why-now, hook and draft sequence | Separate family authority; Claude/Apollo ownership is preserved |

Zoho Forms has no established supported public administration endpoint for these configuration operations in the current integration. Prepare exact manual owner steps when a setting is UI-only; do not silently make browser automation a recurring runtime dependency. Alternative supported form platforms may be evaluated in a separately scoped proposal. No Holo adapter is implemented here.

## Outcomes and learning

An executable proposal defines its baseline, metric, window, minimum usable sample, guardrails and SUCCESS/NEUTRAL/REGRESSION/INSUFFICIENT_DATA criteria before deployment. See the proposal contract. Review results against the frozen plan; retain null/unknown and sample limitations. Diagnostic TEST activity cannot establish customer, qualified Lead, revenue or Ads outcomes.

Learning references the exact proposal revision, execution, evidence and result. Later proposals may query previous outcomes, including regressions and insufficient samples. They must not turn an unmeasured suggestion or repeated model assertion into native evidence.

## Bounded operation and owner visibility

Future collection uses scheduled deterministic reads, incremental IDs, freshness/cache windows and source-specific budgets. Analysis is triggered and bounded by provider/model calls, records, elapsed time and cost. Retry memory prevents repeating the same failed enrichment. No persistent Codex development/research loop is permitted.

Reuse `/business`, `/acquisition`, `/sales`, Today and health. Future projections should show Today, what changed, priorities, concrete previews ready for review, automatic actions completed, blockers and results being measured. Expose real execution evidence, not configuration-only claims. Record invocation origin and effect class separately: unattended/manual/unknown versus TEST_ONLY/natural business effect/none/unknown. Claude/Apollo sends must not be attributed to OptiBrain.

## Roadmap integration gates

Phase33 produces read-only Ads intelligence and complete **draft** proposals using cached economics with source/geography/language/window/currency/limitations. Google Basic remains owner-deferred; Semrush/Ahrefs optional. Phase34 contributes conversation evidence and private sales/sequence drafts with collisions and suppression. Phase37 composes existing domain priorities/proposals/results into an owner manager view. All use this same evidence, preview, approval, execution, measurement and learning contract.

After those domain capabilities, a final optimization-engine mission still needs concrete proposal persistence and revision tests, supported preview/execution adapters, exact-target approval integration, authority/recovery/effect-fencing validation, reliable outcome/sampling attribution, bounded analysis budgets and owner review. Completing those phases alone does not activate an autonomous writer. Any later bounded production autonomy requires explicit scope approval and fresh provider-backed safety proof.
