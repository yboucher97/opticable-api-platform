# Owner business intelligence

AUTHORITATIVE CURRENT. One [Business Overview](https://optibrain.opticable.ca/v1/operator/business), linked from Today, covers Sales, Revenue, Recurring, Operations, Marketing and Attention. CRM remains the operating cockpit; Books remains financial truth. This read-only report grants no decisions or writes. [Measurement](OPTIBRAIN_MEASUREMENT_CONTRACT.md) defines lineage proof; [attribution](OPTIBRAIN_MARKETING_ATTRIBUTION_CONTRACT.md) defines acquisition/privacy.

## Metric meanings

| Measure | Source and basis / truth |
|---|---|
| New Leads; qualified from those Leads | Native CRM creation date in selected Toronto period; current native qualified/converted state. PROVEN population, not qualification-event timing/cohort conversion rate. |
| Open pipeline | Current CRM Deals by actual stage; count, native currency/Amount, age and next action. Missing Amount/currency is explicitly missing, never zero. No probability, forecast, win rate or sales-cycle estimate from incomplete history. |
| Estimates | Books creation/issue date and current status; native CRM Finance association. Accepted-or-invoiced count includes explicit accepted/invoiced status, not an inferred historical acceptance timestamp. |
| Invoiced value | Gross issued non-draft/non-void Invoice total by native currency and issue date. DERIVED DETERMINISTICALLY; includes tax, not recognized/net revenue. Credits/writeoffs/refunds are not silently netted. |
| Paid Invoice value | Gross value of Invoices currently paid with zero balance, grouped by Invoice issue date. Not cash received during that period. |
| Recorded customer payments | Native Books customer-payment date and paid/success status; `bcy_amount` in independently observed organization base currency. Refund amount separate where observed. Not inferred from Invoice balance, not bank settlement or net cashflow. |
| Outstanding / overdue | Current complete observed issued Invoice balances; overdue requires due date before current Toronto day and positive balance. Snapshot stock across all issue dates, not a period flow. |
| Recurring net monthly / annualized value | Active native Books profiles; before-tax subtotal divided by repeat interval for months/years. Future-start and unsupported frequencies withheld. PARTIAL business recurring revenue until Service/Site/acquisition links are complete; no guaranteed future revenue or new acquisition conversion per bill. |
| Customer value | Observed complete bounded Books Invoice population by native customer/Account, currency and current payment state; selected-period value separate. No predictive lifetime value or records predating available provider history claimed. |
| Service revenue | Exact Deal/Site/Service category where one proven family exists; otherwise UNALLOCATED. Never arbitrarily split mixed-service revenue. |
| Marketing | Source/medium/campaign from recorded acquisition and deterministic Finance relationships; FULLY ATTRIBUTED requires complete proof, partial/unattributed shown. No spend-derived ROAS without matched source/currency/period. Historical observed Ads spend is in the measurement receipt, not silently combined with unattributed revenue. |
| Profitability | NOT CURRENTLY MEASURABLE; gross margin disabled.242 observed expense rows have no customer allocation; labour, vendor/item costs and complete native job allocation remain unproven. Revenue is shown without invented profit. |
| Operations | Native non-test Cases and Installation statuses; existing Today carries scheduling, missing access, return visits, billing and recurring attention. No separate task universe. |

## Periods, access and performance

Timezone America/Toronto; Today/week/month/quarter/year are to date, last month is complete, custom inclusive dates support up to3660 days. Native date-only Books fields stay dates; offset CRM timestamps convert to Toronto before grouping. Stock metrics remain current and are labeled. Future-dated payments are excluded from default to-date periods. CSV exports these same metric/basis/period/source timestamps and neutralizes spreadsheet formulas. TEST diagnostics remain separate; owner overview excludes TEST lineage by default.

Independent human Access JWT required before reading cache or parsing reporting range. Missing/stale projection503, invalid range422, private/no-store, escaped HTML, frame denial. Never forge an owner JWT to test production. Root-only hourly native cache is schema3, rebuildable/non-authoritative. Minimized `/run/optibrain-readiness/business.json` is root:opticable-workflow-api0640; no emails, addresses, raw URLs, click IDs, credential values or provider effect authority. API only calculates from this file: zero provider reads per report. At most900 seconds since last runner display refresh; actual hourly source timestamp remains visible. Read failure expires the view; it cannot falsely refresh stale native facts.

The existing internal runner's total160-read bound is preserved. Current complete collection adds4 optional GETs (organization currency, payments and two expense pages), approximately150 reads including existing preflight, at most hourly; intervening cycles reuse the native cache. Optional unavailable collections are UNKNOWN, never zero. Pagination/IDs/currencies must be complete; conflicting finance relations are withheld. No new DB, warehouse, writer, timer, CRM module or field exists. Stop with the existing internal kill; customer-send kill remains independent.

## Real verification and remaining limits

Fresh Books invoice/payment listings reconciled three report periods (this month, last month, year),120 Invoices and109 payments. Six Invoice/Estimate detail samples and two payment detail samples matched independently; native organization currencyCAD. Three reports calculated in0.41 seconds; minimized projection135170 bytes. Before release, this-year gross invoicedCAD61872.20, paid Invoice valueCAD56498.26, recorded paymentsCAD55910.03; outstandingCAD5373.94, overdueCAD287.44. These are different accounting measures.19 active annual profiles normalize to before-tax monthlyCAD1037.50 / annualCAD12450; their23 profile→Service links remain unproven. Current one real Deal has no Amount, so pipeline value is unknown. All real marketing acquisition remains unattributed. Do not “repair” protected history to improve these measures.

Root verification receipts `/var/lib/optibrain/phase22-23/business-{receipt,validation}.json`, private native source/projection and [Phase23 checkpoint](PHASE23_CHECKPOINT.md) support these observations. Future natural events require provider/effect reconciliation; tests are not claimed as genuine new business.
