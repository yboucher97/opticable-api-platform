# Migration intake hold — prepared October 28, 2026

This proposal separates durable intake from execution. It is inactive by default,
creates no database or schema, and does not grant production cutover authority.
Production remains API 1.34.1 at be8cdfe2b36b562ba9e2a57484d8a3d2e8c92caa.
PR #147 remains an unmerged migration toolchain, separate from this application change.

## Actual inbound paths and maintenance behavior

| Source | Receiver and current configuration | Authentication / deduplication | Retry, retention and hold |
|---|---|---|---|
| Control-plane HTTP | Worker `opticable-control-plane`, POST `/v1/events` -> queue `opticable-business-events` (31c6f7026fe142d8959a09613b87c5dd) | `CONTROL_PLANE_API_KEY` Bearer; existing original event/idempotency IDs | Queue send awaited before 202. Caller must retain an original ID; proposed hold policy rejects an omitted ID. |
| Scheduled observers | Same Worker, cron `*/15 * * * *`; mailbox hourly, Sign on configured two-hour daytime slots, finance daily | Deterministic schedule event IDs and idempotency keys | Queue retains 86400 seconds; delivery can pause independently while producers keep enqueueing. No pause performed. |
| Current queue consumer | Worker -> durable `opticable-business-workflow` -> canonical API POST `/v1/automation/events` | Workflow ID derived deterministically from event ID; API key; ledger dedupe | Current consumer ACKs after Workflow creation, not after API capture. Five queue retries then existing DLQ. Workflow uses eight exponential retries starting at five seconds, 30-second step timeout. Most 4xx permanent, except 408/429. |
| Proposed queue hold | Same queue and same API/ledger, direct capture from the existing consumer only when `CORE_INTAKE_HOLD_REQUIRED=true` | Original message identity; exact committed receipt including received ID, durable/hold flags and no run IDs | ACK only after validated SQLite capture. Lost ACK retries original ID and returns duplicate. Errors retry into the existing DLQ; no Workflow is created in hold mode. No consumer change deployed. |
| Existing in-flight Workflows | Canonical POST `/v1/automation/events` | Same API key and original event ID | Drain all nonterminal statuses before source freeze. Do not assume a queue pause stops Workflows. Actual Workflow terminal retention is not exposed in the inspected live binding; do not infer a default or use it as the maintenance buffer. |
| Native CRM notification | POST `https://optibrain.opticable.ca/v1/automation/webhooks/phase5-crm-leads`; channel 5062683202609281 absent, configured expiry October 7 | Existing native token reference `OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL`, exact channel, allowed event types, five-minute timestamp window; no independent signature claim | Exact retry cadence is unverified. Do not rely on delayed native retry. Recreate only after the NEW hold receiver is reachable. Fresh six-day expiry, existing Leads.create/Leads.edit only. |
| Website AI/main connector | `https://connect.opticable.ca/public/lead`, Worker `opticable-ai-connector` | Origin allowlist, consent, rate limit, stable inquiry/request hash receipt | Deployed code stores a KV receipt before success, action `would_create_lead`; no CRM mutation in this live path. KV TTL 180 days. Ten exported receipts already observed locally at October 28 checkpoint. Client retry behavior is unverified; stable inquiry ID is required for dedupe. Independent of the VPS during maintenance. |
| French/English website Zoho Forms | Public `/fr/contact/` and `/en/contact/` embed separate native Zoho Forms; provider Mail notifications -> five-minute VPS collector `ops/phase9/collect_form_receipts.py` | Authenticated provider mail origin and Internet message ID; immutable existing `phase9-form-receipts.db` | Provider records/Mail remain remote while collector is stopped. Collector uses cursor plus two-day overlap, daily full scan, seven-day default and 30-day safety bound. Native mapping/dedupe/retry and English end-to-end submission remain unverified. No synthetic submission or Forms setting change performed. |
| Typed lifecycle ingress | POST `/v1/lifecycle/leads`, `/emails`, `/meetings` | Existing API-key checks and derived stable idempotency identities | Proposed hold captures in the same ledger and returns 202 after commit. Existing caller retry cadence is not asserted. |
| Password/site/Omada callbacks | Public `/v1/site-and-password/*`, legacy aliases, `/pdf/webhooks/zoho/wifi-pdfs`, `/omada/*` execution paths | Live Caddy and API retire these mutation routes with 403 | These are rejected execution surfaces, not active acknowledged intake. Internal PDF/Omada services bind loopback; no new public callback or executor is enabled. Preserve their existing job files/configurations in final recovery. |
| Other configured webhooks | Only `phase5-crm-leads` is currently configured. Code also supports GitHub, Cloudflare, Google push and signed relay | Existing provider-specific signature/token/channel/body/freshness verification retained | No extra endpoint enabled. Hypothetical external senders are not declared verified. |

Live routing and Worker source evidence were read without any test submission.
Native Forms provider-side mapping/deduplication is not fixed or reconfigured by this migration.
The retired execution endpoints must remain denied rather than being repurposed as receipts.

## Explicit runtime configuration

Keep all 15 existing migration safety flags OFF, including
`OPTICABLE_AUTOMATION_ENABLED=false` and `OPTIBRAIN_CRM_DRIFT_ENABLED=false`.
Select `OPTIBRAIN_INTAKE_MODE=hold-v1` only after a separate exact release approval.
Unknown mode strings or missing/unsafe execution flags refuse startup.
Defaults remain `disabled`; no existing deployed service is reconfigured by this PR.

Optional storage bounds:

- `OPTIBRAIN_INTAKE_MAX_RECEIPTS=10000` (all quarantined rows count toward capacity).
- `OPTIBRAIN_INTAKE_MAX_DATABASE_BYTES=536870912` (existing DB pages plus WAL).
- `OPTIBRAIN_INTAKE_MINIMUM_FREE_BYTES=12884901888` (12 GiB).

The authenticated existing `/v1/automation/event-health` includes hold count, oldest
receipt, DB/WAL bytes, disk reserve, capacity and `automatic_release=false`.
Capacity failure returns retryable 503 and rolls back the complete capture; it never
prunes evidence. Existing body size bounds also cover typed lifecycle intake.

Each accepted event commits in existing `automation.db` under BEGIN IMMEDIATE,
`synchronous=FULL`, with immutable envelope/dedupe and a quarantine history/audit
entry in the same transaction. Receipt identity conflicts return 409. Bad signatures
are rejected before capture. No provider call, routing or run creation occurs.
Existing ambiguous states are not rewritten when a duplicate is observed.

Held events use existing quarantine, reason `migration_intake_hold`, so enabling a
kernel later cannot silently release them. Intake mode blocks replay, desired-state
apply, redrive and all other non-receiver mutation HTTP routes. No recovery, delta,
native notification, health/maintenance worker is started while the kernel is OFF.
Release of held events requires separately reviewed existing event replay controls;
this PR performs no release. The 10 old DLQ bodies and TEST Forms ATTEMPTED entry
are separate preserved uncertainties and never included in blanket replay.

## CRM configuration proposal and historical manual state

The actual source journal has a MANUAL native renewal dated October 6, intended
expiry October 12. Planning against an empty journal would miss this blocker.
The read-only default of `ops/phase5/recreate_expired_notification.py` uses the real
journal, requires current channel absence, proves the old configuration's expiry
is past, retains the old MANUAL row and binds its exact digest.

After separate root-private owner approval, it permits only this expired native
configuration to be superseded using the existing Desired State controller.
Every old effect and audit row remains. A newer unresolved intent blocks the operation.
It creates one exact channel with the unchanged endpoint/token references, fresh
reviewed expiry and Leads.create/Leads.edit. No CRM customer record endpoint is allowed.
The existing root technical transport gets an exact, owner-approved, one-use native
configuration scope; runtime/API identities cannot obtain it. Both CRM boundary and
universal transport checks verify the same grant before OAuth and immediately before
transport. Canonical OAuth files are not changed; temporary refresh copies are used.

The tool requires a marked NEW host, exact deployed candidate SHA, all safety flags
OFF, canonical DB, fresh root0600 approval (maximum one hour), exact plan/prior-state
hashes and authenticated public/private receiver health. It records a universal
Action Evidence envelope before POST, then performs read-after-write comparison.
A timeout or inconsistent readback becomes MANUAL_NO_RETRY. Never repeat the POST to
reconcile an uncertain result. Keep receiving into hold until an independently
approved exact subscription disable/expiry; never discard already captured notifications.

## Final synchronization and release boundaries

Reuse the verified October 28 freeze/capture/transfer/seal/final-sync artifacts.
Restore and compare the frozen be8cdfe source generation before installing this new
application revision: the PR #147 engine intentionally refuses mixed source SHAs.
Use all nine stores plus header-based discovery, every table/schema/row/id digest,
audit chains, Decision Cards/priorities/owner corrections/Learning Records, credentials,
Google/owner allowlists, dedupe keys, pending states, leases and external watermarks.

Stop source timers only after explicit maintenance approval. Let running oneshot
collectors finish; do not kill one in a provider call. Verify no new ATTEMPTED or
unresolved action beyond the exact known quarantine set before closing API intake.
Keep source authoritative until that verified freeze. Refresh cursors and inventory
inside the approved window, rather than using the online proof archive for final-sync.

Application release and Cloudflare Worker release require separate exact approvals;
this PR does not merge either itself or #147, deploy, activate hold, pause queues or
change DNS. The current generic manual release gate is main-only and assumes active
production observer timers; it must not be casually invoked on the isolated target.
An explicitly reviewed NEW-only release procedure is required. Keep the corrected
owner allowlist, rebind the enlarged source hash set, and verify Google identity
bindings before/after that release. No kernel activation is needed or authorized.

Only after final private parity and approved target hold release may owner-approved
DNS routing and the exact Worker hold policy be applied. CRM recreation follows a
reachable hold receiver. Resume queue delivery only after readback proves hold mode,
capacity and unchanged consumer/DLQ settings. Maintain a 60-minute abort/review budget,
well below the live 24-hour queue retention; the previous 20–45 minute estimate is
not an end-to-end timing guarantee.

Before NEW receives anything, rollback restores the exact old routing and recorded
OLD service/timer state under approval. After NEW captures any receipt, hold both
sides, preserve encrypted NEW evidence and reconcile every new event/receipt ID and
provider effect before OLD resumes. No stale database overwrite or DNS-only rollback.

Platform references (configuration facts above come from live code/readbacks):
[Cloudflare pause behavior](https://developers.cloudflare.com/queues/configuration/pause-purge/),
[Workflows API and retention](https://developers.cloudflare.com/workflows/build/workers-api/),
[Zoho native notification schema and expiry](https://www.zoho.com/crm/developer/docs/api/v8/notifications/enable.html).
