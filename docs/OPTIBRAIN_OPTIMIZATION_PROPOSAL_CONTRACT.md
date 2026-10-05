# Optimization proposal record

AUTHORITATIVE CURRENT. Canonical format: `schema=1`, `type=optibrain.optimization_proposal`; [machine schema](optibrain-optimization.schema.json). Phase33 implements minimal shared immutable revision/review persistence in the existing research database. Domain details are hashed sidecars to this envelope. This is not the full optimization engine. Existing action/approval/effect journals remain the future execution boundary; local reviews cannot grant a writer.

## Identity and content

`proposal_id` is stable across revisions; `revision` increases when evidence, target, recommendation, preview or measurement plan changes. IDs are opaque and contain no PII. Record `created_at`/`updated_at` in UTC. Target references identify system, entity type and native/derived identity; URLs/files are scoped and sanitized.

Required proposal content: proposal type, target system/object, evidence references, business problem, why now (including NONE CURRENT), recommended change, expected benefit with basis, risk, independent confidence/data quality, affected files/records, owner action, authority class and status. Optional context includes preview location, approver/time, execution reference, deployed time, measurement start/end, result/learning and rollback reference. Null means unknown/not yet applicable, never zero or implied approval.

Supported target systems include WEBSITE, SEO, CONTENT, IMAGE_CREATIVE, ZOHO_FORM, CRM_CONFIGURATION, GBP, GOOGLE_ADS, OUTREACH, SALES_PROCESS and OTHER_SUPPORTED. OTHER_SUPPORTED must name its supported adapter and limitations; it is not a wildcard transport permission.

Evidence records preserve provider, source reference, observed time, freshness/expiry, confidence, native/derived/estimated/inferred/unknown truth class and limitations. Store private raw data by access-controlled reference. Do not put tokens, contact PII, raw message bodies or fake attribution in public proposal views.

## Lifecycle and revision safety

| Stage | Valid next stages / meaning |
|---|---|
| DISCOVERED | RESEARCHING, PROPOSED, BLOCKED, REJECTED |
| RESEARCHING | PROPOSED, BLOCKED, REJECTED |
| PROPOSED | PREPARING_PREVIEW, OWNER_REVIEW, BLOCKED, REJECTED |
| PREPARING_PREVIEW | PREVIEW_READY, BLOCKED, REJECTED |
| PREVIEW_READY | OWNER_REVIEW, BLOCKED, REJECTED |
| OWNER_REVIEW | APPROVED, REJECTED, RESEARCHING, BLOCKED |
| APPROVED | EXECUTING only after independent current authority; BLOCKED/REJECTED on invalidation |
| EXECUTING | DEPLOYED after independent readback; BLOCKED on uncertain outcome |
| DEPLOYED | MEASURING; BLOCKED on a guardrail/verification issue |
| MEASURING | SUCCESS, NEUTRAL, REGRESSION, INSUFFICIENT_DATA |
| BLOCKED | Resume the recorded prior safe stage after documented resolution; reapprove changed revision |
| Terminal results | Retain history; create a linked new revision/proposal for another experiment |

No stage transition grants authority. Approved target/revision/payload hash, approver, expiry and exact action must link to the existing guarded approval mechanism. Changed recommendation/targets/evidence/preview/plan invalidates approval. Ambiguous transport outcome is reconciled before retry; it is never reset to allow another effect. Do not automatically roll back provider writes on an inconclusive result.

CLASS A deterministic maintenance may omit owner review only under an existing specific authorization; CLASS B preparation may stop at PREVIEW_READY. CLASS C production changes require a concrete preview, approval and rollback plan. CLASS D stays human-controlled. This foundation creates none of those execution grants.

## Measurement contract

Every executable optimization defines before APPROVED/EXECUTING:

- Metric and business relevance, provider/source, unit, cohort/geography/language, numerator/denominator where relevant.
- Baseline value/status, sample and observed window. Unknown baseline is explicit and needs a collection plan, not a fabricated target.
- Measurement window or duration, minimum sample, attribution limits and TEST exclusion policy.
- Guardrail metric(s), threshold and stop/review behavior.
- Predeclared SUCCESS, NEUTRAL, REGRESSION and INSUFFICIENT_DATA rules.

Deployment fills actual measurement start/end without changing the original decision criteria. Results preserve observed values/sample/window, result evidence, guardrail outcomes, interpretation and known limitations. Learning states what to keep/change/research next. A camera CTA may improve clicks while qualified-Lead evidence remains insufficient: record those independently; aggregate result can remain INSUFFICIENT_DATA. Never substitute page views for qualified business performance.

## Execution and recovery

Execution references the existing action ID, payload hash, approval, exact deployed SHA/provider object, immutable effect/readback receipt and rollback. Separate invocation origin (UNATTENDED/MANUAL/UNKNOWN) from effect class (TEST_ONLY/NATURAL_BUSINESS_EFFECT/NONE/UNKNOWN). A scheduled test remains TEST, not a natural business effect.

Fresh recovery follows the [recovery authority contract](OPTIBRAIN_RECOVERY_AUTHORITY_CONTRACT.md). Restored APPROVED/DEPLOYED records cannot rearm a writer, restore stale approval validity or replay an effect. Ordinary deployment preserves authorized lifecycle scopes/expiry/claims; new recovery retains writers OFF. Provider capability, configured destination and proposal approval are distinct from execution authorization.

Examples and schema validation are format proof only. They are not provider-backed execution, customer results or continuous autonomous operation.

## Ads completion operations

[Pilot readiness](OPTIBRAIN_ADS_PILOT_READINESS_CONTRACT.md) binds complete campaign details into the existing immutable revision hash. CREATE_PAUSED/OWNER_ACTIVATE are future domain operations within EXECUTING/DEPLOYED; they do not add incompatible proposal states. Local REVIEWED or fixture APPROVED never grants transport. Exact approval/expiry/account/spec, off-host idempotency, readback and unknown-effect hold precede any future provider operation.
