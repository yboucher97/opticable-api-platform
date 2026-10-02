> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# OptiBrain Phase 7 — controlled single-Lead canary preparation

Status: engineering preparation only. No real CRM mutation or customer send is
authorized by this document. Production Phase 6 remains at
`0ade0ec02eeea5b503dc8eba8bea9c982cbf9240`, API 1.11.0, with external
business-action flags absent.

Current branch validation: 656 inherited tests / 706 subtests with zero
failures, errors or skips after the unregistered CRM executor, operator
approval surface and outbound canary pin were added. The prior pushed branch
commit passed both GitHub checks; the final SHA requires its own GitHub
validation.

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
   deterministic provisional references stable across later versions of the
   same Lead. They are **not** Zoho object IDs.
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
   The unregistered `phase7_crm_approval` ledger now persists a one-hour maximum
   human approval bound to Lead ID/version, plan hash and patch hash. It marks
   `consuming` durably before any future provider call and cannot be reused
   after restart, ambiguity, manual outcome or verified consumption. A consumed
   record requires a provider operation ID and exact verified patch hash. It does
   **not** authenticate the human or grant CRM transport authority on its own.
   `operator_phase7_api` derives the actor from verified Cloudflare Access and
   rehydrates before issuance; it remains unregistered in production. Its
   consume endpoint defaults to unavailable. The unregistered
   `phase7_crm_executor` rehydrates, claims durably, obtains an exact one-record
   transport grant under `OPTIBRAIN_CRM_CANARY=phase7-single-canary-v1`, sends
   at most one Lead PUT, requires exact readback, and records ambiguous outcomes
   as manual. A separate durable `dispatching` marker prevents a second grant
   even if a caller tries to enter the transport scope again. The broad Phase 6
   write flag is neither needed nor accepted as a substitute for this canary
   flag. No Account, Contact, Deal, Books, conversion or customer send path is
   present in this executor.
6. Follow-up text is a draft candidate only. Existing Phase 6 outbound approval
   binds exact source/version, recipient, sender, subject/content hashes,
   mailbox, human actor and expiry. The outbound action remains unregistered and
   `OPTIBRAIN_OUTBOUND_SENDS` remains absent. A live send needs a separately
   authorized one-attempt registration/feature gate and exact human approval.
   Response loss is permanently manual, never an automatic resend.
   Phase 7 engineering adds a distinct outbound canary mode:
   `OPTIBRAIN_OUTBOUND_SENDS=phase7-single-canary-v1` plus the exact lowercase
   32-hex `OPTIBRAIN_OUTBOUND_CANARY_APPROVAL_ID`. That mode observes/refuses any
   other approval ID and rechecks the pin before the provider call. Neither
   variable is set in production, and the action remains unregistered there.
   The unregistered Phase 7 operator API now issues an existing durable outbound
   approval from the exact review package under verified Access identity. Its
   consume route rehydrates the Lead, resolves the human-reviewed `fr`/`en`
   template by the stored hashes, and defaults to unavailable without an
   explicitly installed callback. This avoids treating AI language as send
   authority. The existing Phase 6 source resolver remains unchanged for its
   separate event-backed path.

## Required authorization package before any live action

Record the real Lead ID, exact current source version, verified customer
recipient, consent/opt-out, existing relationship IDs, duplicate-search results,
provisional internal references, exact proposed CRM before/after fields, exact
message subject/body/from/to, approval actor/expiry, policy version and content
hashes. Show personal data only in an access-controlled human review surface;
persist hashes/IDs in the audit record, not raw body or phone/email values.
`build_review_package` produces the exact human-visible CRM before/after values
and email subject/body, and a separate redacted audit receipt. It refuses
   source snapshot drift, opted-out/internal recipients and unowned senders. If
the Lead lacks a trusted `fr`/`en` language, an authenticated human must choose
one explicitly for the package; AI language hints are discarded. A language
conflicting with a trusted Lead value is refused. The Phase 7 operator route
binds that selection to the exact package and stored outbound approval; the
   callback/action remain unavailable in production until a separate deployment
and first-send authorization gate.

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
or call a provider writer. The operator API, CRM ledger and executor are also
unregistered; `OPTIBRAIN_CRM_CANARY` is absent in production. Synthetic tests
prove exact version and duplicate refusals, Access-derived issuance, single-use
approval/restart/concurrency, disabled-policy zero calls, exact one-record
transport, ambiguity/manual state, and redacted evidence. The first live
read-only Lead review requires selection of a real Lead ID. A real CRM mutation
and outbound email remain separate later approvals after their exact packages
and single-use live transport boundary are validated on the final candidate and
deployed safely. The first real outbound mailbox must be verified as controlled
by the operator, outside Opticable's blocked internal domains; do not guess or
send to an unverified external address.

The repaired scheduled backup service completed a timer-dispatched generation
`20260929T184240Z` using the preserved sandbox. Local archive SHA-256 is
`4478b55626141a9ad5fe221a37cbca880ad597c1e4febb1e713cc8e1d9c0995c`;
an isolated copy of its automation DB passed manifest hash, SQLite integrity and
Schema V2 checks. Encrypted off-host upload and downloaded ciphertext hash
verification passed. All 12 previous local generations were preserved, giving
13 generations and about 55 GB free. Both normal backup/upload timers remain
enabled and active; the temporary timer proof unit was removed.
