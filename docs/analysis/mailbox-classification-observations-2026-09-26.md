# Mailbox classification observations — 2026-09-26

Mode: read-only mailbox analysis. No messages moved or deleted. No Zoho Books writes.

## High-confidence routing patterns observed

### 1) Direct client / quote intake
Observed an inbound message to `soumissions@opticable.ca` with subject `209 rue Anna app.3/intercom en trouble`, attachment present, followed by a reply from `soumissions@opticable.ca` confirming receipt of a purchase order and that scheduling would follow.

Classification implications:
- recipient `soumissions@opticable.ca` is a strong FR sales/service-intake signal, but intent still overrides address;
- purchase-order language should promote the thread from lead/quote into accepted-work / scheduling state;
- attachments should be linked to the related CRM/Service context;
- next action should be scheduling when the customer has already issued a PO.

### 2) Partner / subcontract opportunities
Observed a Field Nation message to `admin@opticable.ca` with subject `New Work: Mirabel QC J7J 0A1, Sep 25 4:00pm`.
Extractable structured fields included:
- source/platform: Field Nation
- status: Available
- location: Mirabel, QC J7J 0A1
- schedule: Friday, Sep 25 @ 4:00 PM
- work type: Networking
- work-order ID: 20033349
- pay: $65 first hour, then $50/hour
- scope: replace network switch and test connectivity
- required tools/materials

Classification implications:
- Field Nation belongs in the partner/subcontract-opportunity pipeline, not generic admin;
- exact source work-order ID is an idempotency key;
- create one open next-action per available work order, never duplicate;
- urgency is schedule-driven;
- extract pay/rate separately from client revenue fields;
- when `partners@opticable.ca` becomes the advertised partner address, both `partners@` and known partner-platform senders should converge on the same route.

### 3) Provider / SaaS administration
Observed messages to `admin@opticable.ca` including:
- Anthropic receipt
- OpenAI API usage-limit notice
- Centre Hi-Fi order confirmation

Classification implications:
- `admin@` should not map to one folder blindly; classify into provider account, purchasing/receipt, system notice, security, or action-required;
- receipts/orders can be observed and indexed without creating unnecessary todos;
- account/security/billing changes can create a next action only when human action is actually needed.

### 4) Supplier receipts / bills
Observed an Anthropic paid receipt with an attachment sent to `admin@opticable.ca`.

Classification implications:
- supplier financial documents may arrive on `admin@` even after `factures@` is introduced;
- classification should detect invoice/receipt semantics independent of recipient alias;
- route to supplier-invoice/business-record observation;
- extract supplier, document number, amount, paid/unpaid state, due date when available;
- Zoho Books remains strictly read-only.

### 5) Legacy Opti-Plex usage
Observed a PayPal receipt addressed to `yboucher@opti-plex.ca` and other correspondence where the old address appears in recipients/CC.

Classification implications:
- `@opti-plex.ca` is still actively used;
- do not disable old aliases;
- distinguish provider-account usage from ordinary historical correspondence;
- when a provider/service account still targets an Opti-Plex address, create a migration candidate toward `admin@opticable.ca`;
- do not create migration tasks for every incidental CC occurrence.

### 6) Delivery failures
Observed a mailer-daemon permanent failure for an outbound sales email.

Classification implications:
- outbound delivery failure should create/update a sales-data-quality task;
- related CRM lead/contact should be marked for email verification rather than silently left in follow-up cadence;
- duplicate bounces on the same address should collapse into one open action.

### 7) Existing client support / operational changes
Observed an existing-client thread about a tenant phone-number change and support coordination.

Classification implications:
- identify existing Account/Contact/Service Location first;
- classify as data change/support context rather than new lead;
- next action can be `done` when acknowledged and no further work is required;
- avoid generating unnecessary new Deals.

### 8) Systems / telemetry
Observed automated timelapse daily health reporting from/to `logs@opticable.ca`.

Classification implications:
- system health mail should route to Systems/Monitoring;
- only create a task when thresholds indicate failure, missing data, or degraded state;
- healthy periodic reports should be summarized, not surfaced as todos.

## Proposed decision order
1. Identify business/entity context (Opticable vs Hopla Jeux vs other).
2. Detect explicit system/provider/partner fingerprints.
3. Detect financial-document semantics.
4. Detect existing-client support/project context.
5. Detect lead/quote/sales context.
6. Detect delivery failure/security/urgent exception.
7. Determine `actionable` vs informational.
8. If actionable, derive one canonical next action with owner, due date, waiting-on state and source message/thread ID.
9. Only after classification passes confidence threshold should automatic filing/task creation occur.

## Confidence policy recommendation
- >= 0.95: automatic classify + file; task creation allowed if deterministic.
- 0.80–0.95: classify + propose task; no external send.
- < 0.80: leave in place and surface for review.

## No-touch rules
- Never delete email automatically.
- Never disable aliases automatically.
- Never write to Zoho Books.
- Never create duplicate CRM/open tasks for the same source thread/work-order/document.
- Never convert an existing support/project thread into a new lead solely because it arrived at a sales alias.
