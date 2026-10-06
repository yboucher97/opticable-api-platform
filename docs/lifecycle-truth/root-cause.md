# Noveco root cause

The October 6 overnight report ranked finishing Noveco's quote-package review first despite its own fresh Books reads reporting all three estimates as `sent`. The owner subsequently confirmed the quotes were already sent. This was not a missing-company exception. There was no shared commercial-object lifecycle or actionability gate between observations and recommendations.

## What was actually available

| Evidence | Business/source date | What it proves |
|---|---|---|
| October 2 office inquiry, native Mail message `1790969038980162800` | October 2; collected October 6 | Four requested service categories, including AV and six access positions. An old request does not establish unfinished work today. |
| Business projection `/run/optibrain-readiness/business.json` | Observed October 5, 20:41:33 UTC | Three **draft** estimates. The projection stayed unchanged through the October 6 inspection; its SHA-256 matched the overnight copy. |
| Fresh native Books details `noveco-estimate-{0,1,2}.json` | Collected October 6, 05:46 UTC | The same exact three native objects now have `status=sent`. This is authoritative estimate status, not independently proven email delivery or an actual send timestamp. |
| Owner's current correction | Recorded for this replay October 6, 13:09:42 UTC | High-confidence `OWNER_VERIFIED_FACT`: the quotes were sent. Actual occurrence time remains unknown. |
| Bounded Noveco Mail searches | October 6, 05:45 UTC | A company-text query found the known inquiry; an address OR query returned empty despite that inquiry. Empty results cannot establish no later response or no send. |

| Estimate | Native Books ID | Old draft source version, October 5 EDT | New sent source version, October 5 EDT |
|---|---|---|---|
| EST-1132 | 3643985000002330018 | 15:31:26 | 17:14:03 |
| EST-1133 | 3643985000002330031 | 15:42:35 | 17:13:39 |
| EST-1134 | 3643985000002330043 | 15:40:00 | 17:22:58 |

The modified timestamps above are **source versions**, not send timestamps. The existing native send-history interpreter already rejects status-only send inference. No native send-history or exact outgoing estimate-message proof was available in the inspected artifacts.

CRM had Account `5062683000007980011` and Contact `5062683000007990011`; Books used customer `3643985000002330001`. The estimates' `zcrm_potential_id` was empty. These native relationships identify the customer and individual estimates; they do not prove every requested service was quoted, delivered or accepted. No fourth AV quote or outstanding revision is inferred from a missing record or a quantity comparison.

## Why the old action survived

The standalone overnight narrative combined the old inquiry, estimated value and a possible scope mismatch into a due-today review. It explicitly acknowledged the fresh sent statuses, yet still assigned rank 1, first-hour time and a follow-up draft without a proven outstanding revision or applicable due follow-up. Thus fresh collection alone did not correct the action.

The product projections had an additional gap: the business snapshot still contained older draft versions. Sales only included estimates associated with a retained CRM Deal; the conversation reader followed saved Apollo reply contacts. Noveco was outside those paths. The old code had no all-estimate commercial state projection, no authoritative-event reconciliation and no explicit today actionability gate.

Inspection of all **46 latest priority records and 33 latest proposals** found no persisted Noveco priority/proposal. The wrong rank was in the overnight owner-brief artifact. It would be incorrect to claim a particular SQL priority row generated that recommendation. Local reproduction instead establishes the stale native versions, the missing Sales projection linkage, the actual report's rank and the regression error shape. The neutral prepared-then-sent fixture demonstrates the generic state correction.

No authoritative exact-context CRM/internal Task due date was retained for the Noveco estimates. Task history and complete CRM activity were not collected in the available bounded artifacts, so this audit does not infer that no such Task exists. Optimization Proposals and Business Priorities were inspected as recommendations, never accepted as proof that a business action remained outstanding. The owner brief was a historical standalone snapshot and remains unchanged.

Root cause classification: **multiple** — stale projection; missing event/linkage in shared projections; lifecycle model gap; missing fact-specific precedence and recency reconciliation; priority/actionability gap; derived recommendation surviving newer evidence. No evidence establishes an arithmetic timestamp-sort bug or a hard-coded “CRM always wins” rule in the old code.

## Reproduction and preserved evidence

Private source report: `/home/optibrain/optibrain-overnight-intelligence-20261006.md`. Matching artifacts: `/home/optibrain/worktrees/optibrain-final-night-preview-integration/overnight-intelligence/evidence/` and `morning-top5.md`, `sales-attention.md`, `reply-drafts.md`. Current read-only cache/journal exports and hashes: `/tmp/optibrain-lifecycle-current-20261006/`.

[Annotated evidence](current-evidence.json) contains native IDs, dates, provenance and limitations, without raw email bodies or addresses. [Replay](revalidation.json) records the shared engine output. Reproduce with:

```sh
/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python ops/lifecycle_truth/revalidate.py --directory /tmp/optibrain-lifecycle-current-20261006 --audit docs/lifecycle-truth/current-evidence.json --output /tmp/lifecycle-replay.json
```

The replay writes only an isolated temporary copy of the existing journal architecture. Production caches, provider records, historical reports and runtime journals were not changed.
