# Phase 7 first Lead canary execution control

Status: branch engineering. This document does not authorize a Zoho mutation or
customer send. The deployed application remains `e55ea3f9afe24ca254f4e60bf7a8ea0cc9ffb841`
until a separately guarded release of this change.

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
non-writable manifest at `/etc/optibrain/phase7-canary-registration.json`, an
exact checked-out Git SHA matching both that manifest and the registration
environment, API 1.11.0, an exact HTTPS origin, and a verified Cloudflare Access
human allowlist. In controls-only mode it installs review/issuance routes but
no consume callback. Enabling a business callback additionally requires an
issued exact approval, matching single-use approval ID and per-action mode.
Lead creation, Lead patch and outbound email have independent pins. No YAML
workflow gains an automatic create or send action. Books and finance remain
blocked by the shared gateway; no Account, Contact, Deal or conversion writer
is included.

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
