# OptiBrain owner/operator guide

AUTHORITATIVE CURRENT, API 1.16.0. Work mainly in Zoho CRM and review [Today](https://optibrain.opticable.ca/v1/operator/today) using your normal owner login. OptiBrain organizes eligible new work and may send four individually proven operational email families. Broad automation, marketing and financial writes remain OFF. Actual family state is shown by root policy/readiness; READY can mean waiting for naturally eligible work.

## Daily workflow — OWNER SAFE

Review new Leads, due follow-ups and quote-ready items, then accepted work, contracts, installations, billing and support. Each card explains the reason, next action and dated source; open its CRM link before acting. Viewing a card does not send anything. A human qualification/schedule/completion change in CRM can trigger its separately authorized family. TEST_ONLY and historical evidence are excluded from current business attention.

Approvals are exact, scoped records, not a general automation switch. An approval can remain visible while transport is disabled. Inspect an exception’s evidence and ownership before requesting a retry. Do not approve, replay or recreate an action merely because a prior response is missing. A provider action may already have happened.

## Interpret health

| State | Meaning and owner response |
|---|---|
| OK | That specific check passed recently. It does not prove every provider or workflow is ready. |
| DEGRADED | Safe service may continue; a stale read, capacity warning or bounded observation needs review. Check freshness and ask an engineer if persistent. |
| ACTION REQUIRED | A failed/stalled checkpoint, dead-letter delivery, backup or safety check needs investigation. Stop consequential work until its evidence is reconciled. |
| UNKNOWN | Evidence is absent/stale or the provider cannot expose it. Treat it as unverified; do not assume success or enable a writer. |

The former soft log-growth warning counted system-journal retention as application growth. Application diagnostic logs now rotate at 5 MiB × 5 files; journald is capped at 512 MiB/90 days. Separate thresholds and free-disk checks bound risk. Immutable action/receipt/claim evidence is retained separately.

Remote queue depth is read from Cloudflare’s approximate GET metrics. The retained historical backlog was classified during lifecycle validation; read the latest sampler for current counts. A queue count does not prove content/effects or authorize replay. Never purge or replay a retained item without independent effect reconciliation.

## Emergency checks — OWNER SAFE with shell access

```bash
sudo cat /etc/optibrain/mutation-control.json
sudo cat /etc/optibrain/customer-communication-control.json
sudo cat /var/lib/optibrain/releases/current.json
curl -fsS http://127.0.0.1:8100/v1/system/health
sudo optibrain-admin scheduler  # backup/upload pair only
sudo systemctl list-timers --all optibrain-backup.timer optibrain-phase2a-upload.timer opticable-phase9-intake-receipts.timer opticable-phase10-service-events.timer opticable-phase12-test-runner.timer opticable-lifecycle-internal.timer opticable-customer-communications.timer --no-pager
sudo optibrain-admin verify-latest
sudo cat /var/lib/optibrain/phase2a/state.json
sudo cat /run/optibrain-readiness/status.json
sudo cat /run/optibrain-readiness/queue-depth.json
```

The central policy must show `test_writes_enabled:false` and `real_canary_allowed:false`; broad/legacy writers and the development worker stay OFF. Individually approved internal scopes and a separate customer-send policy may be active. The receipt proves the deployed release; live root policies/readiness prove current activation. Backup `state.json` must show `download_hash_verified`, a recent `verified_at` and no newer upload failure. Local verify checks archive and DB integrity. Open Today → system health/exceptions to inspect attention.

Stop **all automatic customer email** while keeping new intake and internal work running:

```bash
sudo /usr/bin/python3 -I /usr/local/lib/optibrain/customer_runner.py --stop
```

Emergency stop of application automation, retaining backup/upload:

```bash
sudo /usr/bin/python3 -I /usr/local/lib/optibrain/customer_runner.py --stop
sudo /usr/bin/python3 -I /usr/local/lib/optibrain/lifecycle_runner.py --stop
sudo systemctl stop opticable-phase9-intake-receipts.timer opticable-phase10-service-events.timer opticable-phase12-test-runner.timer
sudo systemctl stop opticable-phase9-intake-receipts.service opticable-phase10-service-events.service opticable-phase12-test-runner.service opticable-workflow-api.service
```

This stops host intake/reconciliation and the API’s internal workers; Today will be unavailable. Edge delivery can accumulate errors while the API is down. Leave backup/upload timers running. Do not restart schedulers or replay messages until engineering checks state and provider evidence. Stopping a timer alone does not stop an already running job. Never delete DBs or queue messages as first-line recovery.

## Responsibility boundaries

| Role | Actions |
|---|---|
| OWNER SAFE | Read Today, CRM facts, health, release/backup receipts; invoke the emergency stop above. |
| ENGINEER / CODEX | Diagnose logs/auth/state, verify DBs/versions, reviewed deploy/code rollback, isolated rebuild and reconciliation within the manual mission. |
| PROVIDER ADMIN | Account login/MFA, minimum-scope secret rotation, owner-only Forms settings, DNS/Access and OVH account/billing actions. |
| RECOVERY-ONLY | Offline AGE decryption, restore staging, replacement-host cutover or explicitly authorized VM snapshot restore. |

Production VPS is `vps-214ba8cd.vps.ovh.ca`, OVH Canada (`ovh-ca`), service `41299869`, `os-bhs6`. Confirm the name/service in OVH Manager before any incident action. The owner-confirmed snapshot `OPTIBRAIN-GOLDEN-PHASE14-PRE-PHASE15-20261002` is fast whole-VM rollback insurance. Use it only for an authorized host incident after writers can be kept OFF; its old journals may lag provider effects. A clean rebuild is safer after compromise or uncertainty about the old OS. Do not overwrite production or reinstall it as a health check. Follow [recovery](OPTIBRAIN_RECOVERY_GUIDE.md).

## Organized new work in CRM

New eligible inquiries appear as Leads with identity, service interest, attribution, next follow-up and one internal Task. Review in CRM. Selecting **Pre-Qualified in the CRM UI** is the human qualification trigger; OptiBrain may natively convert and prepare the Deal/relationships. Ambiguous or protected historical matches need human attention. Choose the Deal’s **Service Location** in CRM when address information is insufficient. Design, scope, pricing and Finance Estimate create/send are HUMAN. Create/send from the Deal’s native Finance related list to retain associations. Books remains financial truth; never also create a native CRM Quote/Invoice.

OptiBrain observes sent/accepted Finance Estimates and prepares Services, simple WorkDrive folders, contract context and an unscheduled Installation. Existing installed Services are reused; a new visit does not create another Service. Send contracts manually while Sign API licensing is restricted.

For an eligible sent Estimate, the graduated quote family can send a first reminder after three business days and a second at least five business days later; it then asks you to follow up. Acceptance, decline, closure, replies, opt-out, bounce, a newer Estimate or suppression stops reminders. Completing the related internal follow-up Task suppresses that Estimate's automatic follow-up. Unknown language/recipient/associations require human attention. See the [communication contract](OPTIBRAIN_CUSTOMER_COMMUNICATION_CONTRACT.md) for precise gates.

Select the Installation date/time, technician and access instructions in CRM. A verified schedule can trigger one confirmation and one reminder; changing the schedule produces an updated appointment. Check Toronto time before confirming. For blocked work or a return visit, enter the actual reason in Instructions Notes. A return visit creates an unscheduled follow-up visit linked to the same Services and preserves the original history.

Record completion in CRM UI with Completion Notes and relevant evidence. OptiBrain activates newly owned Services, records visit context and prepares billing/support attention; an eligible completion message may follow. Create/send the Invoice yourself from Zoho Finance. Books payment observation clears owned attention only when all linked invoices are satisfied; overdue invoices surface internal attention without collection messages. Support requests with unclear site, Service or urgency require your decision. See the [matrix](OPTIBRAIN_LIFECYCLE_AUTOMATION_MATRIX.md).

**OWNER SAFE internal stop:** `sudo /usr/bin/python3 -I /usr/local/lib/optibrain/lifecycle_runner.py --stop` closes internal scoped writes and disables its timer, preserving data/API/backups. Customer email has its separate stop above; invoke both for a full action stop. Engineering reconciles HOLD before any retry; never delete journals or repost a timed-out action. Inspect both scoped timers and `/run/optibrain-readiness/{lifecycle,customer-communications}.json`. Ask engineering to review authorizations at least seven days before their recorded expiry; renewal preserves original eligibility and evidence. Marketing, automatic pricing/scheduling and financial writes remain OFF.

## Recurring service and marketing attention

Open **Recurring** or **Marketing Sources** from Today. Recurring attention includes renewal, maintenance, annual price review and billing-link gaps. An overdue Invoice never cancels the Service. Review/upsell signals prepare human attention; customer review sends stay OFF. Books alone changes recurring billing. If you end a Service, separately review its Books billing as a human action.

Marketing Sources shows Leads through accepted Estimates and observed invoiced value by acquisition source/campaign. TEST activity is excluded. UNATTRIBUTED means no verified acquisition relationship; do not guess or repair protected history. Paid Invoice value is not a cash-receipt or profitability report. ROAS is unavailable until verified spend and lineage exist. In new Finance transactions use the native Account and Deal associations; no manual ID copying or new custom financial fields is required. [Recurring contract](OPTIBRAIN_RECURRING_SERVICE_CONTRACT.md) and [attribution contract](OPTIBRAIN_MARKETING_ATTRIBUTION_CONTRACT.md) explain evidence limits and owner provider setup.

## Business Overview — OWNER SAFE

Open [Business Overview](https://optibrain.opticable.ca/v1/operator/business) from Today. Choose this month/last month/year or a custom Toronto date range; export the same figures as CSV. Review Sales/pipeline, invoiced value, recorded payments, outstanding/overdue, recurring billing, customer value and marketing. Missing pipeline value is unknown. Paid Invoice value and recorded customer payments are different measures; gross invoiced value includes tax. Stock balances/pipeline are current, even with a past period selected. Recurring values are before-tax normalized active Books billing; incomplete Service links stay PARTIAL. UNALLOCATED/UNATTRIBUTED means evidence is missing. Profitability remains COST DATA INCOMPLETE, and ROAS is unavailable without matched spend/source data. Use CRM/Books for action and Today for work priorities. No report changes pricing, billing, scheduling or advertising. [Reporting contract](OPTIBRAIN_BUSINESS_INTELLIGENCE_CONTRACT.md) defines every metric.

For new business, open the **Deal → Zoho Finance → New Estimate** and verify its Account/Deal before sending. Create its Invoice from the accepted Estimate or the same Deal's Finance list. Set one physical Service Location on the Deal. This preserves native associations without copying IDs. Business Overview's expandable Finance linkage batch identifies missing historical relationships; select existing business records with engineering, or leave them unlinked. Never edit protected history to improve a chart.

Measurement PARTIAL identifies Forms/analytics gaps. Conversion READY means native destinations and validation-only testing passed; uploads remain OFF while waiting for an independently eligible natural event. READY is not ACTIVE and does not prove real attribution. Engineering can stop only conversion export with the reviewed release's `ops/phase24_25/conversion_runner.py --stop`; Lead intake, customer email, operations and Finance observation continue. Owner setup is batched in [provider actions](phase25-owner-actions.md); do not paste credentials into chat.

## Apollo coexistence and Today Sales

Read [sales intelligence contract](OPTIBRAIN_SALES_INTELLIGENCE_CONTRACT.md) and [current Claude/Apollo flow](CURRENT_CLAUDE_APOLLO_FLOW.md). `/v1/operator/sales` adds coordinated reply/Lead/Deal/Estimate/customer attention and up to five additive public project reviews. Existing Apollo outreach stays under Claude/Apollo; new OptiBrain prospecting is SHADOW ONLY, with no sends/enrollments/CRM bulk promotion. Exact collision and suppression holds never grant contact clearance. Local owner feedback does not alter Apollo suppression. No takeover/migration is authorized.

## Acquisition intelligence — research only

[Acquisition](https://optibrain.opticable.ca/v1/operator/acquisition) combines search, company/project signals, competitors, SEO/content and future paid research into a handful of owner actions. Read the [acquisition contract](OPTIBRAIN_ACQUISITION_INTELLIGENCE_CONTRACT.md), [market policy](OPTIBRAIN_MARKET_OPPORTUNITY_CONTRACT.md) and [sources](OPTIBRAIN_MARKETING_DATA_SOURCES.md). Raw research stays outside CRM; Claude/Apollo keeps outreach. Priorities are market-based, with unknown demand/CPC/ROI labeled. Existing pages are improved before duplicate pages are proposed; new-page candidates need owner expertise and demand validation. No content publication, campaign change, cold send or conversion upload is enabled by this view.

## Measurement and research confidence (API1.20.0)

Business and Acquisition show GA4 authentication, collection date and coverage separately. A missing fresh row does not mean no visitors. Acquisition shows query sample/window, geographic scope and confidence. Sparse commercial evidence can justify a small improvement/research step without proving demand or ROI. Sales receives only current, resolved trigger reviews; unresolved permit actors remain in Acquisition. Apollo-owned follow-up continues in Apollo. Google outcome uploads remain READY BUT OFF.

The two Forms need one hidden acquisition-context field/notification inclusion before native FR/EN attribution parity can be claimed. English remains excluded from real automation. Use [Forms intake](OPTIBRAIN_FORMS_INTAKE_CONTRACT.md) and the [remaining provider action](r1-owner-actions.md); website prefill and fixture success do not prove provider delivery.
