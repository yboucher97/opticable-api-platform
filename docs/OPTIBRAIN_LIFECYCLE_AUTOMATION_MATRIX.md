# Lifecycle automation matrix

AUTHORITATIVE CURRENT, API 1.14.0. CRM is the cockpit; Today surfaces attention. [Scope](OPTIBRAIN_REAL_AUTOMATION_SCOPE.md) determines eligibility and actual activation. [Finance](OPTIBRAIN_FINANCE_INTEGRATION_CONTRACT.md) determines transaction relationships; [communications](OPTIBRAIN_CUSTOMER_COMMUNICATION_CONTRACT.md) defines individual send gates.

| Step | Current responsibility |
|---|---|
| Approved new intake, normalization, dedupe, attribution, service interest | AUTOMATIC, exact identity and post-cutoff lineage; ambiguous/protected matches HUMAN |
| Lead owner, Next_Followup_At, one internal Task/Today | AUTOMATIC; owner5062683000000339001, next weekday10:00 Toronto |
| Qualification | HUMAN in CRM UI: Pre-Qualified; API/workflow changes do not authorize conversion |
| Native Lead conversion, Account/Contact reuse/create, Deal/context | HUMAN → AUTOMATIC; no protected association; reused parent content preserved |
| Service Location preparation | AUTOMATIC with complete structured address/native Account link; safe capitalization/designator/unit/postal variations reuse; ambiguous spelling/buildings HUMAN |
| Design, scope, pricing, Estimate create/send | HUMAN, native Finance related list on Deal |
| Estimate sent/status observation, deterministic Deal projection | AUTOMATIC, Books GET + native transaction/Account/Deal/site reconciliation |
| Quote follow-up | AUTOMATIC internal attention; graduated `customer.quote.reminder` may send only with all independent gates. Two reminders maximum; acceptance/decline/reply/opt-out/closure/suppression/bounce/supersession stop. |
| Acceptance | AUTOMATIC observation of real Books acceptance; unlinked/mismatched records HUMAN |
| Services/WorkDrive/Installation skeleton | AUTOMATIC after acceptance when deterministic; existing durable Service reused across Deals without overwriting original Deal; minimal folder reuse and unscheduled visit. Ambiguous scope HUMAN. |
| Contract preparation | AUTOMATIC local validated context only; Sign API license unavailable |
| Contract send | HUMAN — DEFERRED PROVIDER LICENSE; Today shows SEND CONTRACT |
| Scheduling/technician/access decisions, field work | HUMAN |
| Appointment confirmation/reminder | AUTOMATIC only for independently graduated family after verified human schedule; updated native revision supersedes previous, one reminder at 24h |
| Blocked/return visit | HUMAN status/reason → AUTOMATIC attention; verified return visit creates one new unscheduled Installation with the same Services, preserving visit history |
| Installation completion → Services/internal billing/support eligibility | HUMAN → AUTOMATIC, native owner UI proof/notes; `crm.service.activate` updates newly owned Services/dates only. Active reference Services stay read-only. |
| Completion/thank-you message | AUTOMATIC only for graduated eligible completed visit; no review/marketing campaign |
| Invoice creation/send, payments, credits/refunds/banking | HUMAN / Books; automatic financial writes DISABLED |
| Invoice/balance/due/payment observation | AUTOMATIC read-only; overdue internal attention, paid observation closes owned billing Tasks only after all linked invoices are satisfied |
| Support routing | AUTOMATIC context/Today preparation where deterministic; urgency/site/service selection HUMAN when ambiguous. Case-creation helper unarmed without a proven support producer. |
| Review/maintenance/renewal eligibility | AUTOMATIC internal projection requiring human scope review; customer messages DISABLED |

Internal verification bound: 20 new Leads, 12 effects/160 reads per cycle. Customer send ceilings: 10 per family, 4 per cycle. Families may remain READY while waiting for genuine eligible work; synthetic records are never called real. TEST exclusion uses native filters and root lineage. Generic Other Services require an exact verified business label; an ambiguous existing system requires owner selection. No additional business module or financial system is introduced.

## Recurring lifecycle and measurement

| Activity | Authority |
|---|---|
| Books recurring invoices and amount/frequency/cancellation | HUMAN / BOOKS |
| Recurring billing, generated Invoice/payment-state observations | AUTOMATIC GET ONLY |
| Renewal/contract review, annual price review, maintenance, retention | AUTOMATIC internal Today attention when supported by explicit data |
| Review eligibility and upsell signals | AUTOMATIC attention; pursue/send HUMAN |
| Service cancellation decision | HUMAN; automatic lifecycle attention cleanup, no Books cancellation |
| Acquisition/Finance lineage, source/campaign/invoiced-value reports | AUTOMATIC GET ONLY |
| Advertising conversion upload | DISABLED; destination/consent/provider gates pending |
| Ad spend/bids/targeting; prices, schedules, financial transactions | HUMAN |

See [recurring](OPTIBRAIN_RECURRING_SERVICE_CONTRACT.md) and [attribution](OPTIBRAIN_MARKETING_ATTRIBUTION_CONTRACT.md). Existing12 internal and4 Mail scopes/cutoffs/counters remain unchanged.
