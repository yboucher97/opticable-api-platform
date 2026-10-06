# Commercial event precedence

`workflow/automation/lifecycle_truth.py` is the deterministic contract. `lifecycle_projection.py` adapts existing observations. No provider client, model call, scheduler or execution authority is involved.

## Source facts

Every fact identifies an exact `{system, entity_type, entity_id}` commercial context, event ID/type, source, truth class, identity confidence, evidence confidence, `event_at`, `source_at`, `observed_at`, proof and optional structured detail. Company names are labels, never join keys. Internal priorities, tasks, proposals and cached derived recommendations have zero authority as business-event facts.

`event_at` is an actual occurrence; `source_at` is a source version/status/assertion date; `observed_at` is collection time. Unknown occurrence time stays null. A refreshed collection never moves an old event forward. Owner current-state assertions use `source_at` and `time_basis=ASSERTION_AT`, without inventing occurrence time.

Authority is fact-specific:

| Source | Facts it can establish | Important limit |
|---|---|---|
| Books | Estimate existence/native state, invoice existence/status/payment | `sent` status becomes `QUOTE_SENT_RECORDED`; actual send requires recognized native system-email history. |
| Mail / Apollo | Exact-object/thread sends and inbound messages | Reply flags, fuzzy names, unrelated later sends and empty searches are insufficient. |
| CRM | Native inquiry, qualification, Deal and work stages | A Deal/Task stage does not prove a Mail send or financial payment. |
| Forms | Native inquiry | Does not establish that nobody responded later. |
| Public notice/feed | Exact tender publication/status/deadline evidence | Does not prove eligibility or the owner's submission history. |
| Owner | Explicit current-state assertion on an exact reviewed object | Local provenance only; provider records remain unchanged. |

Invalid identity, insufficient confidence, unsupported authority and future timestamps cannot establish state. Equal-time contradictory acceptance/decline facts require verification. For usable facts, event time takes precedence, then fact authority, the source version for that occurrence and compatible progression. Source time is a clearly identified fallback for current source state, never a renamed collection date. `evidence_observed_at` retains collection freshness for equivalent current facts and ranking ties without changing `last_event_at`.

## State and action precedence

Preparation → sent → accepted work → scheduled/in-progress work → completion/invoice/payment suppresses earlier preparation requirements. A later re-observation of an old draft does not reopen sent or billed work. An explicit revision request can open a revision cycle before delivery. Declined/expired work does not acquire a new sales follow-up absent a separate explicit reactivation context/policy.

Inbound replies supersede waiting; a proven response supersedes the earlier reply requirement. Replies after delivery/payment still require processing when current, without reopening quote preparation. An owner “quote sent” assertion with unknown send time does not silently declare an already observed reply answered: uncertain order produces verification.

Native Books draft status alone proves neither incomplete quote content nor absence of an external send. It produces verification. Explicit structured evidence of an incomplete draft can produce `FINISH_QUOTE`. A ready/revised quote produces review of that ready/revised object, not repeat drafting.

Contexts remain per estimate/project. A shared customer ID cannot merge separate quotes. Explicit predecessor/revision relationships and exact invoice→estimate relations can supersede an earlier object. Ambiguous one-to-many links stay separate. Exact invoice existence can suppress old quote work even when historical occurrence time is unavailable; no invoice send, payment or work completion is invented.

Recognized events include inquiry, qualification, requested/drafted/ready/sent/revised/accepted/declined/expired quotes, inbound/revision requests, responses/follow-ups, work progression, invoice/payment, commitments, tenders, waiting, deferral and dormant/reactivation facts. Domain rules remain responsible for unsupported next steps; recognized history alone does not create work due today.

## Completeness and preservation

Negative reply conclusions require exact-context complete **inbound and outbound** history through the decision time. An inbound-only `search_complete` flag is insufficient. Downstream progression checks likewise require scoped completeness. Missing/partial/stale collections remain unknown, not empty.

The existing Manager journal stores immutable `BUSINESS_FACT` evidence alongside its existing tables. Source observation refresh alone does not create another business fact. Current state is recomputed; source facts and old priorities remain available. Collection coverage remains separate from event chronology. The existing 160-read budget and last-good observation preservation are unchanged.
