# Shared data and intelligence architecture

AUTHORITATIVE CURRENT. This contract joins existing models conceptually; it performs no data migration. [State contracts](OPTIBRAIN_STATE_CONTRACT.md) retain their canonical writers, store inventory, immutable evidence and restore order.

## Layers and provenance

| Layer | Content and boundary |
|---|---|
| Raw/source evidence | Provider IDs, source/version, observed time, hash and access-controlled raw reference. Immutable receipts/journals remain unchanged. |
| Normalized entities | Deterministic IDs/aliases and documented joins; native identity and confidence are separate. CRM/Books remain canonical. |
| Derived insights | Explicit transformation/version/input references, confidence, sample and missingness. Native facts are never overwritten by conclusions. |
| Opportunities | Existing market, trigger, prospect and sales models with current/historical value, fit, urgency and uncertainty. Research stays upstream of CRM. |
| Optimization proposals | Shared versioned recommendation, preview, approval class and frozen measurement plan. |
| Execution | Existing guarded action/approval/effect journals, independent authority, exact target and readback. |
| Results/learning | Measured evidence/sample/window/guardrails; interpretation and follow-up retain provenance. |

Each evidence reference includes provider/source, observed_at, freshness or valid_until, confidence, truth class and limitations. Distinguish NATIVE_MEASURED, DERIVED_DETERMINISTIC, ESTIMATED, INFERRED and UNKNOWN. Retrieval time does not make an old native fact fresh. Null missing metrics remain UNKNOWN; zero requires an observed zero and valid population/window.

## Entity references and relationships

Use `{system, entity_type, entity_id}` references, plus canonical aliases/domain/address only where independently supported. No similar-name-only merge, language-to-Québec inference, generated email or private contact data in public views.

| Entity family | Existing source / intended relationship |
|---|---|
| Company, Person, Lead, Contact, Account | Existing CRM and upstream research identity/contact models; known native ID links, employer/domain proof and collision confidence |
| Deal, Service Location, Service | CRM-native relations and service model; no inferred protected customer/Deal links |
| Estimate, Invoice, Recurring profile | Books financial facts plus proven CRM/Service lineage; READ only, no inferred margin/revenue attribution |
| Website page, Search query, Keyword | Existing site inventory, Search Console/GA4 and cached economics; language/geography/window/provider limitations |
| Market Opportunity, Trigger, Prospect | Existing acquisition/trigger/prospect models, evidence versions, actor types and current/historical actionability |
| Campaign, Ad, Creative | Provider-native read facts or clearly identified draft references; no campaign execution from research |
| Form, Content asset, Review | Published/draft object identity, version, language, mapping/rights/privacy/source and performance references |
| Optimization Proposal, Business Priority | Versioned cross-domain envelope linking the above and existing action/result history |

One project may link owner/developer/GC/electrician/property-manager actors separately. Company identity, domain, current role/contact and collision confidence remain separate. A proposal may reference several entities without merging their raw facts.

## Message and creative intelligence

The shared schema includes an `optibrain.optimization_asset` record for HOOK, HEADLINE, CTA, KEYWORD, AUDIENCE, PAIN_POINT, PROOF_POINT, CREATIVE_CONCEPT, ARTICLE_IDEA, GBP_POST, SOCIAL_POST, EMAIL_ANGLE, VIDEO_CONCEPT and IMAGE. Link each to service, ICP, geography, evidence, channel, proposal and measured performance.

Store provider, brief/prompt reference, draft/asset reference, language, rights/source status, intended usage and illustrative status. OpenAI image generation, Holo and other providers may be supported later; no Holo integration is installed now. Actual draft/asset is required at preview readiness; a suggestion alone is not a finished creative preview. Unsupported customers/results/photos/proof points must never be generated as facts.

Use access-controlled references for briefs or performance containing private data. Website/Form/Ads/contact data do not cross PII/consent boundaries merely because the intelligence layers share a contract. Never add names/emails/phones/message bodies to GA4 or URLs to correlate a proposal.
