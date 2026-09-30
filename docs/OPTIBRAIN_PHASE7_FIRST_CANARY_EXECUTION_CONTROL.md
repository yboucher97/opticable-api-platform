# Phase 7 first Lead canary execution control

Status: controls-only production preparation as of 2026-09-30. This document
does not authorize a Zoho mutation or customer send. Production and remote main
are `d2ca75d588665112d1d62329abfda23dd92d533f`, API 1.11.0. The
root-owned Phase 7 manifest has `business_actions_enabled: false`; the Lead
create, CRM patch, and outbound approval pins are all absent. Operator review
and issuance routes exist, while their consume callbacks remain unavailable.

The new Lead-create control permits one `POST /crm/v8/Leads` with exactly six
reviewed fields, one record, `trigger: []`, and `skip_feature_execution` for
cadences. Zoho's [insert contract](https://www.zoho.com/crm/developer/docs/api/v8/insert-records.html)
documents that cadences otherwise run by default. The immutable request hash is
bound to a human-issued, one-hour-maximum approval. The approval audit stores
hashes/IDs and timestamps, not the email address or raw Lead fields. A durable
`consuming` then `dispatching` marker precedes any provider call. A crash,
timeout, malformed acknowledgement, missing provider ID, incomplete readback or
Search indexing lag is manual reconciliation, never an automatic second POST.
The read-only reconciliation helper may identify a possible created record,
but cannot reopen a spent approval or infer that an unrelated concurrent user
created it.

Before approval issuance and again immediately before dispatch, the control
searches exact email in Leads and Contacts and cross-checks a complete current
record inventory. A bounded scan of more than 2,000 rows per module stops for
human review. This cross-check is needed because Zoho [warns that Search can
return HTTP 204 immediately after a write while its index catches up](https://www.zoho.com/crm/developer/docs/api/v8/search-records.html).
The latest read-only check at `2026-09-29T19:41:07Z` found zero exact matches,
after scanning 10 Leads and 45 Contacts. It is evidence for preparation only;
it expires after five minutes and must be repeated at approval and dispatch.

The registered operator surface defaults to absent. It requires a root-owned
non-writable manifest at `/etc/optibrain/phase7-canary-registration.json`, a
root-verified checked-out Git SHA matching the manifest and registration
environment, exact SHA-256 pins for every canary runtime source file, API
1.11.0, an exact HTTPS origin, and a verified Cloudflare Access
human allowlist. In controls-only mode it installs review/issuance routes but
no consume callback. Enabling a business callback additionally requires an
issued exact approval, matching single-use approval ID and per-action mode.
Lead creation, Lead patch and outbound email have independent pins. No YAML
workflow gains an automatic create or send action. Books and finance remain
blocked by the shared gateway; no Account, Contact, Deal or conversion writer
is included.

The first controls-only staging of `84270ac316c7a3e7d91c5e205d0a1a2fefa138c4`
passed branch CI, fresh baseline backup/restore/off-host checks and initial
application health. Enabling registration then exposed a deployment-identity
defect: the unprivileged API service cannot traverse production Git metadata,
so `git rev-parse HEAD` in registration startup exited 128. The prior API
environment was restored atomically and the staged code returned to healthy
1.11.0 with registration absent; production Git remained at that staged SHA,
while remote main remained at the previous Phase 7 SHA. There were no business
provider calls or DB/schema changes. This correction replaces service-user Git
access with root-reviewed per-file source hashes in the protected manifest.
The root deployment campaign still verifies Git SHA/ancestry before staging.
The corrected `d2ca75d` release completed staging and is the current
controls-only production/remote-main release.

Live read-only mailbox verification found Zoho Mail account
`1083319000000008002` enabled, not outbound-blocked, and
`yboucher@opticable.ca` confirmed and active as a send-from identity. No email
was sent. The live Lead and Contact Search calls returned HTTP 204, and the
complete list cross-check above found no exact recipient match. The current
Leads field metadata confirmed all six proposed API names and the `Not
Contacted` picklist value. These observations do not substitute for fresh
checks at authorization time.

The proposed exact create body is:

```json
{"data":[{"Company":"Opticable Internal Canary","Email":"hckyan97@gmail.com","Email_Opt_Out":false,"First_Name":"OptiBrain","Last_Name":"Phase 7 Canary","Lead_Status":"Not Contacted"}],"skip_feature_execution":[{"name":"cadences"}],"trigger":[]}
```

Its policy request hash is
`6f5ba00b3b8721c69838e4c43a684ada1a367a6b7972fb857d90ecb137e3c499`.
This is a proposal hash, not an issued approval. An approval ID and expiration
are minted only through an authenticated human issuance after a fresh dedupe
check on the deployed exact-SHA control. A successful create must return a
numeric provider ID, hydrate exact field values and show exactly that one
email-matched Lead and no matching Contact. Only then can a new, independent
Lead patch proposal be built from its actual ID/version/before-values. A new
email proposal must bind the actual Lead ID/version, verified sender/recipient,
exact subject/body hashes and a separate approval. Creating the Lead grants
neither patch nor send permission.

The proposed English email is the shipped bounded template: From
`yboucher@opticable.ca`, To `hckyan97@gmail.com`, Subject `Your inquiry with
Opticable`; body: `Hello,\n\nThank you for your inquiry. Could you share your
requirements, the site address, and your preferred timeline?\n\nThe
Opticable team`. No send route is enabled by this document.

Recovery preserves current Schema V2 and uses corrected-code forward recovery.
After a create with an uncertain response, perform only read-only reconciliation;
never blindly retry or delete a possible record. A CRM patch reversal requires
fresh read and a new human approval. A sent email cannot be unsent; its approval
must be fenced and the provider message ID retained.

## Exact first live-canary authorization package

**Proposed first action:** create exactly one controlled test Lead in the real
Zoho CRM tenant. The record does not yet exist; the exact six reviewed values
and request body appear above. The recipient address must be confirmed as a
mailbox controlled by the approving operator before any live use. The create
request suppresses workflows and cadences. No relationship object, folder,
Lead patch, email, Books object, or financial record is changed by this action.

**Exact record/data:** one new `Leads` record with `First_Name=OptiBrain`,
`Last_Name=Phase 7 Canary`, `Company=Opticable Internal Canary`,
`Email=hckyan97@gmail.com`, `Lead_Status=Not Contacted`, and
`Email_Opt_Out=false`. The CRM Lead ID is assigned by Zoho on success. The
policy request hash above binds the exact JSON body. Internal client/contact/
company/site/project references and six folder paths may be computed only
after the returned Lead ID is verified; they remain provisional and make no
provider writes.

**Exact draft for a later, separately authorized send:** From
`yboucher@opticable.ca`; To `hckyan97@gmail.com`; Subject
`Your inquiry with Opticable`; body:

```text
Hello,

Thank you for your inquiry. Could you share your requirements, the site address, and your preferred timeline?

The Opticable team
```

This message is **not** authorized by approval of the Lead create. Its source
Lead ID/version, opt-out state, verified recipient, language, exact subject and
body hashes, and independent single-use outbound approval must be established
after the Lead is created. A real customer Lead must likewise be selected and
reviewed separately before any customer-facing mutation or send.

**Approval and dedupe:** an authenticated Cloudflare Access human must approve
this exact body and confirm control of the target mailbox. Recheck exact email
in Leads and Contacts through Search and a complete bounded inventory within
five minutes of approval and again before dispatch. Mint one approval expiring
within one hour, pin only its ID and this request hash in the root-owned release
manifest, and enable only the single-use Lead-create callback for the execution
window. The broad CRM and outbound flags stay absent. Claim `consuming` and
`dispatching` durably before the sole POST. A lost response cannot be retried.

**Success evidence:** one successful POST, a numeric Zoho Lead ID, exact
readback of the six fields, one matching Lead and zero matching Contacts after
index reconciliation, one durable approval/audit ledger trail and no duplicate
POST. Later CRM and outbound actions require their own journal evidence.
Preserve the provider response ID, source version, request hash, dedupe proof,
approval actor/expiry, and backup generation in the restricted audit package.
The follow-on planner may then report provisional IDs, folders, qualification
score, next action and follow-up draft without external writes.

**Stop and recovery:** stop on duplicate/ambiguous identity, stale or incomplete
inventory, unverified mailbox control, field/consent drift, missing/expired
approval, extra queued write, unexpected provider trigger, backup failure, or
health regression. Immediately remove the one-action execution pin after the
attempt. On timeout or ambiguous acknowledgement, retain the durable fence and
reconcile by read-only email/ID searches; do not POST again or delete a possible
record. On a confirmed but unwanted Lead, propose a separately reviewed
correction or deletion with fresh authorization. Preserve Schema V2 and use the
documented corrected-code forward-recovery path for an application failure.
