# Controlled customer communications

AUTHORITATIVE CURRENT. API 1.14.0 adds four individually gated Mail families. Their production state is **READY / ARMED** when the root policy and timer are enabled; absence of a naturally eligible customer effect does not disable them. [Scope](OPTIBRAIN_REAL_AUTOMATION_SCOPE.md) defines new-record eligibility. CRM remains the business cockpit; Books owns financial truth. No financial write or marketing authority is granted.

| Family | Trigger and cadence | Stop conditions |
|---|---|---|
| `customer.quote.reminder` | Native Finance Estimate sent/viewed; first reminder after 3 Toronto business days, second at least 5 business days after the actual first. Maximum two, then owner attention. Weekdays are used; holidays are not inferred. | Accepted/declined/expired Estimate, closed Deal, reply, owner suppression/completed follow-up Task, opt-out, bounce, newer Estimate or uncertain prior effect. |
| `customer.appointment.confirmation` | Owner enters/confirms a complete future Toronto schedule. Send once per native schedule revision; a changed revision sends an updated appointment. | Cancelled/incomplete schedule, wrong associations, missing human provenance, reply/suppression/delivery issue or existing effect. |
| `customer.appointment.reminder` | Current confirmation independently verified; one reminder in the final 24 elapsed hours before that schedule. | Same appointment stops; an old revision cannot remind for a superseded schedule. |
| `customer.completion.message` | Independently verified owner completion, completion notes, native site/service relationships and no outstanding return visit. Once per visit. | Incomplete work, return visit, ambiguous context, reply/suppression/delivery issue or prior effect. |

Qualification, technical scope, pricing, Estimate creation/send, scheduling, field work and Invoice creation/send remain human. Contract context is prepared automatically; **SEND CONTRACT** remains human while Sign API licensing is restricted. SMS, calls, collections, negotiation, review/marketing campaigns and real Sign sends are not authorized by these families.

The root adapter freshly reads Contact → Account, Deal → Account/Contact/Site, Site → Account and, for visits, native Service/Installation joins plus immutable visit lineage. Finance reminders additionally require independent integrated-CRM and Books transaction/customer reconciliation and a native sent timestamp. Missing associations are human attention; names never replace IDs. Protected historical associations and TEST recipients are ineligible for real sends.

Language must come from an explicit native preference, Finance locale, verified intake language or owner selection. Names do not determine language. French and English templates have the same operational meaning, one recipient and no CC/BCC; they expose no internal IDs or debug/evidence details. TEST sends use only `yboucher@opticable.ca` and subjects beginning `[OPTIBRAIN TEST]`. A labelled TEST status equivalent or accelerated clock can prove a family without creating a financial transaction; neither may authorize a real reminder.

Before every POST, the pinned planner is rerun against fresh native eligibility and suppression facts. A READY plan grants no authority. The separate root policy, passed-family checkpoint, exact source/recipient/template hash, short-lived authorization and fresh create-only R2 claim must all agree. A provider acknowledgement is followed by independent Sent message/header/content reads. This proves the one provider send, not successful recipient delivery. Incoming reply/delivery-failure observations suppress later automation and surface human attention.

Mail has no relied-upon provider idempotency key. Each effect permits one POST. A timeout, lost acknowledgement, existing claim or state loss permits GET reconciliation only; zero matches never grants a retry. More than one effect or changed recipient/content holds the affected family for engineering review. State and claims must never be cleared to resend.

Initial verification ceilings are **10 attempted real messages per family and 4 per cycle**. Counting attempts prevents an uncertain send from freeing capacity. Increasing a ceiling currently requires evidence review, a reviewed code change and a recorded scoped policy amendment; it is not an automatic rollout. Exact expiry lives in the root policy. Review authorizations before expiry and preserve original cutoffs, state and claims on renewal; expired authority fails closed.

**Stop all automatic customer sends while preserving internal automation:**

```bash
sudo /usr/bin/python3 -I /usr/local/lib/optibrain/customer_runner.py --stop
```

Authority: `/etc/optibrain/customer-communication-control.json`. Private evidence: `/var/lib/optibrain/customer-communications` (root-only sources, authorizations, effects, suppression and holds), append-only lifecycle tables in `phase12-autonomy.db`, and R2 `business-effects/v1/`. `/run/optibrain-readiness/customer-communications.json` is display only. Restore starts with both customer and internal writers OFF; reconcile effects newer than the backup before any scoped resumption.
