# Shared next-action contract

`derive(events, context, now, coverage, followup, owner)` returns current state, commercial milestone, latest authoritative event, actual last-event time (possibly null), next action, actionability, reason code, confidence, response/follow-up state, waiting reason, deadline and source health. The result is `DERIVED_DETERMINISTICALLY` with execution authorization false. It is never persisted as provider/source truth.

## Gates

| Gate | Meaning | Today eligibility |
|---|---|---|
| ACTIONABLE_NOW | Explicit current work with sufficient evidence | Current evidence and no unresolved dependency/blocker |
| VERIFY_FIRST | The verification itself is the action | Only a supported imminent/overdue deadline or commitment makes it urgent |
| WAITING | No current action; customer/provider/time/natural event/policy wait | Excluded |
| BLOCKED | An unresolved prerequisite remains | Excluded |
| OPTIONAL | Useful discovery/prepared review without a current obligation | Excluded |
| NO_ACTION | Completed/closed/downstream state | Excluded |

`eligible_today` and `priority_order` serve Manager, its morning brief and current Sales priority projections. Fewer than five is valid. Imminent hard tender deadlines precede general importance; supported commitment dates follow. Confidence, freshness of evidence for the same current fact, known customer risk, verified business value, supported recurring potential and verified effort can break ties. Unknown economics remain neutral. Waiting, supersession, stale source readiness and dependencies are gates rather than opaque score additions. Collection freshness never changes event chronology.

The priority projection preserves the original recommendation, exposes its supersession/replacement, and uses current facts for title/action/reason. Waiting/closed priorities become visibly `SUPERSEDED`. A new legitimate verification can appear as `CURRENT_DERIVED_ACTION`, without presenting the old reply preview as current. Website/Ads/content optimization proposals retain their independent domains. Prepared optimization work is not automatically due today.

## Follow-up and response checks

No default follow-up date is invented. An authoritative exact-context due date must have a current assignment after the actual send; a superseded older task cannot mature a newer send. An explicit documented calendar-delay rule may supply a due date. Existing scoped weekday rules must supply their already-computed aware deadline, not be converted to calendar days.

The existing `customer.quote.reminder` policy uses three Toronto business days for the first reminder and five after the first for a second, with native send proof and exact eligible CRM/Books relationships. This remediation does not broaden that policy. Noveco's empty Deal linkage and unknown actual send time do not establish applicability or a due date. Its result is `FOLLOWUP_POLICY_UNKNOWN`, not “no rule exists anywhere.”

A future date produces no action. A matured date with incomplete later-response history produces `VERIFY_REPLY_STATUS`, not a send instruction. Exact inbound messages produce process/review actions only after checking later responses. Low-confidence free-text intent does not automatically accept/decline/revise commercial state. Apollo ownership converts prospective manual outreach into ownership review; existing send ownership controls remain authoritative.

Day-only promises carry a date precision and a sorting bound, not a fabricated appointment time. Known dayparts can provide a not-before boundary. Support-TI's Tuesday PM commitment remains waiting during the morning.

## Integration

Manager refresh retains source facts in the existing journal; authenticated Manager reads recompute against those facts and current caches. Morning actions show current state, why actionable, latest evidence, last event date and confidence. Details expose waiting/follow-up/completeness metadata without turning every historical item into a task.

Sales conversations use the same derivation, retain response incompleteness, suppress obsolete drafts and reconcile exact `SALES_REPLY` aliases. Sales estimate intelligence uses the same contract; existing estimates without a Deal remain visible to the commercial state projection. Today consumes the actionability gate for shared Sales priorities. The read-only replay CLI applies the same derivation and ranking to overnight/current evidence.

Existing operational planners, provider send authorization and scoped weekday cadence remain intact. This is a shared commercial attention contract, not a replacement for every service workflow. No broad/full-Mail collection, new provider write, database, timer or model dependency was added.
