# Business priority and Todo representation

AUTHORITATIVE CURRENT. Shared format: `schema=1`, `type=optibrain.business_priority` in the [schema](optibrain-optimization.schema.json). This defines future owner-view interchange; it installs no separate Todo database, dashboard or priority worker. Reuse existing Today attention and domain recommendations.

Every item records a stable priority ID, domain, target/entity/proposal references, WHAT, WHY, business impact, urgency/due time, confidence/data quality, structured evidence, dependency/blocker, actor, whether OptiBrain can prepare it, whether exact owner approval is required, status, created/updated time and next action. UNKNOWN remains visible.

## Explainable prioritization

Use HIGH/MEDIUM/LOW/WATCH with separate reason entries. Each factor preserves its value/unit/basis, evidence and uncertainty: revenue opportunity, probability, urgency, customer impact, cost, effort, risk, data confidence, recurring potential, strategic value and dependency. Do not invent monetary estimates, probabilities, percentages or a single opaque AI score.

Deterministic presentation order should first expose safety/intake blockers and imminent authorized deadlines, then high-impact ready owner decisions, then valuable research/preparation with missing proof, and finally watch/history. Show dependency and suppression holds rather than hiding valuable prospects. Service/geography fit and potential opportunity quality must not substitute for execution confidence.

## Owner experience

Today and `/business` compose cross-domain owner priorities; `/acquisition` retains research/coverage/source detail; `/sales` retains strict resolved/collision/suppression admission. Future manager views link to the same item/proposal rather than copying mutable tasks across dashboards.

Each item answers: what should happen, why, impact, urgency, evidence/confidence, who or what acts, what OptiBrain can prepare now, and what exact production approval is required. Ready proposals link to actual previews/tests/rollback and measurement plans. Completed automatic actions link to real execution receipts and distinguish UNATTENDED/MANUAL/UNKNOWN origin from TEST_ONLY/NATURAL_BUSINESS_EFFECT/NONE/UNKNOWN effects.

Do not label a retained historical exception active without current failure evidence. Use CURRENT_ISSUE, HISTORICAL_EXCEPTION, ACCEPTED_LIMITATION, EXPECTED_DISABLED or UNKNOWN when appropriate. Empty eligible queues are not failures; scheduled starts without successful queue processing are not healthy.

Future priority items cannot override root kill switches, scope expiry, protected ownership, provider permission, suppression or approval. Closed/rejected items and learning remain queryable for later decisions. No new scheduler, public endpoint, cold send or financial action is enabled by this contract.
