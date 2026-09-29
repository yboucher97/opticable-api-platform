# OptiBrain Phase 7 — controlled single-Lead canary preparation

Status: engineering preparation only. No real CRM mutation or customer send is
authorized by this document. Production Phase 6 remains at
`0ade0ec02eeea5b503dc8eba8bea9c982cbf9240`, API 1.11.0, with external
business-action flags absent.

## Exact one-Lead workflow

1. An operator selects one existing numeric Zoho Lead ID. The read-only resolver
   fetches that Lead and searches Leads by email. Zoho Search may return fuzzy
   results and may lag recent writes; the resolver filters exact email, requires
   a complete first/only page, and refuses zero or multiple exact matches.
   Search uniqueness covers Leads by email only. Contact/Account/Deal matching,
   phone identity, and any ambiguous relationship remain human review items.
   [Zoho CRM V8 Search Records](https://www.zoho.com/crm/developer/docs/api/v8/search-records.html).
2. `phase7_canary.build_canary_plan` binds that read-only evidence to the exact
   Lead `Modified_Time`. The existing Phase 6 decision policy supplies bounded
   qualification priority, next action, follow-up and contactability. AI hints
   may affect an advisory priority/action only within the policy; they cannot
   authorize provider writes or customer sends.
3. Internal client, contact, optional company, site and project references are
   deterministic provisional references. They are **not** Zoho object IDs.
   Existing numeric CRM relationship IDs are carried through only if supplied
   by an authoritative reviewed record. There is no Account/Contact/Deal create
   or update route in this canary planner.
4. A six-folder structure is generated under `leads/<numeric-id>/<project-ref>`.
   These are proposed paths only. Actual local/Drive/CRM folder creation is a
   separate mutation gate with its own identity, idempotency, ownership and
   recovery proof. No folder is created by the planner.
5. The proposed CRM patch is exactly the existing Phase 6 Lead allowlist:
   `Normalized_Email`, `Normalized_Phone`, `Next_Followup_At`, and safe empty
   `Service_Types` fill. The package for a live canary must show **each exact
   before/after value** privately to the human approver and bind the reviewed
   Lead version and patch hash. Production remains observe-only until a
   single-record, single-use approval boundary is implemented and validated.
   A broad Phase 6 write flag alone would expose other queued Leads and is not
   acceptable for this first live mutation.
6. Follow-up text is a draft candidate only. Existing Phase 6 outbound approval
   binds exact source/version, recipient, sender, subject/content hashes,
   mailbox, human actor and expiry. The outbound action remains unregistered and
   `OPTIBRAIN_OUTBOUND_SENDS` remains absent. A live send needs a separately
   authorized one-attempt registration/feature gate and exact human approval.
   Response loss is permanently manual, never an automatic resend.

## Required authorization package before any live action

Record the real Lead ID, exact current source version, verified customer
recipient, consent/opt-out, existing relationship IDs, duplicate-search results,
provisional internal references, exact proposed CRM before/after fields, exact
message subject/body/from/to, approval actor/expiry, policy version and content
hashes. Show personal data only in an access-controlled human review surface;
persist hashes/IDs in the audit record, not raw body or phone/email values.

List the one permitted CRM operation and one permitted Mail operation separately.
Each needs a one-use release approval. Success requires exact provider readback,
one matching journal operation, healthy queues, unchanged unrelated records,
and zero Books/financial/conversion operations. Stop on stale source, duplicate
identity, opt-out, wrong mailbox, missing language, provider ambiguity, approval
drift, extra queued write, unexpected external action, unhealthy backup, or
health regression. Preserve the journal and require human reconciliation after
an ambiguous result; never blindly retry.

Recovery uses the verified Phase 6 corrected-code forward-recovery procedure and
current Schema V2 backup. A customer email cannot be unsent; the stop/recovery
plan can only prevent a second send and preserve exact evidence. A successful
CRM Lead patch may be reverted only after fresh read/review and a new explicit
approval; do not automatically write old values over newer customer changes.

## Current engineering boundary

`phase7_canary` is not registered in production startup or any workflow. Its
identity resolver performs GETs only. Its plan does not issue a durable approval
or call a provider writer. Synthetic tests block Python sockets, prove exact
version and duplicate refusals, and inspect redacted evidence. The first live
read-only Lead review requires selection of a real Lead ID. A real CRM mutation
and outbound email remain separate later approvals after their exact packages
and single-use live boundary are implemented, tested and deployed safely.
