# OptiBrain Phase 6 Gate F — identity-aware approval control plane

Status: isolated engineering validation PASS on exact candidate `5921473c06470aafae2003607b0a8c85c25f0caf` (84 focused tests / 90 subtests; 556 full-regression tests / 495 subtests; zero failures/errors/skips). Operator routes and outbound sends remain unregistered/disabled. Live identity/mailbox/readiness and send acknowledgement proofs remain separate prerequisites. This document does not authorize production enablement, customer sends, environment changes, or main-branch promotion.

Gate E evidence baseline: `d365d9e862280b7322a7b25b3e7adf2f3a535255`.
Production/main/recovery baseline remains `52f11d4fc14d8582c03837e0317f849efe8aa3d7` until a later reviewed deployment gate.

## Purpose

Gate F establishes the authenticated human control plane needed to issue and inspect the single-use outbound approvals proven in Gate E. The existing shared `X-API-Key` and control-plane Bearer secret authenticate possession of service secrets but do not identify a human operator, so they are not sufficient authority for outbound approval issuance.

## Identity boundary

Use a dedicated Cloudflare Access protected operator surface. The origin must validate the signed `Cf-Access-Jwt-Assertion` against the configured Access team issuer, application AUD, signature, expiry, `nbf`, and token type before using any identity claim.

Authoritative human identity is server-derived from the verified token. Prefer the stable Access `sub` as the principal identity and retain the verified `email` only as display/audit context. Never accept `actor`, `email`, `sub`, or authorization claims from request JSON, workflow events, AI output, query parameters, or forwarded application headers that are not cryptographically verified.

Current Cloudflare reference:
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/application-token/

## Required operator routes

Gate F implementation may add a narrow operator API/UI, but it must remain unregistered/unreachable from automation events.

Required logical operations:

1. `GET approval candidate`
   - Read-only.
   - Hydrates the authoritative source from Zoho/immutable event evidence.
   - Shows exact sender, recipient, action type, source identity/version, subject, body, mailbox, expiry, and all blocking conditions.
   - Never creates an approval.

2. `POST issue approval`
   - Requires a valid identity-based Access JWT.
   - Server derives actor as `human:<verified Access sub>`; verified email is optional display evidence, not caller authority.
   - Rehydrates the authoritative source immediately before issuance.
   - Rejects stale source versions, opt-out/unknown consent, converted/inactive Leads, changed recipient, changed content, unapproved aliases, missing reply identity, or unknown language prerequisites.
   - Calls `OutboundApprovalLedger.issue` only with server-derived bindings.
   - No send occurs.

3. `GET approval`
   - Read-only status/inspection.
   - Must not return credentials or hidden provider error bodies.
   - Raw message body may be shown only from the authoritative source under authenticated human access; it must not be copied into approval ledger evidence.

4. `POST consume/send`
   - Gate F may implement registration/routing for later enablement, but live policy stays disabled by default.
   - Must not accept boolean-only approval.
   - Must require the exact durable approval ID and rehydrate/revalidate source/contactability/content again immediately before consumption.
   - Workflow/provider retry count is exactly one.
   - `OPTIBRAIN_OUTBOUND_SENDS=phase6-sales-v1` remains absent until a separate enablement/canary approval.

## Authorization

Authentication alone is insufficient. Gate F must include an explicit operator allow policy. Minimum safe v1:

- Access policy itself restricts the application to the reviewed Opticable operator identity/identities.
- Application verifies `sub` and `email` are present for issuance operations; service-token/non-identity Access tokens are rejected for human approval issuance.
- Optional application-side allowlist binds permitted Access `sub` values or verified email domains/addresses. Prefer stable `sub` allowlisting if operationally manageable.
- Read-only inspection may be granted separately from approval issuance in a future expansion; v1 may use one owner/operator role.

## CSRF and browser safety

If issuance is exposed to a browser:

- accept only same-origin POSTs;
- require JSON content type;
- reject cross-site `Origin`/`Referer` mismatches where present;
- do not expose approval mutation via GET;
- return `Cache-Control: no-store`;
- use strict CSP and no third-party scripts on the approval page;
- never place approval content, Access JWTs, source text, recipient addresses, or approval IDs in analytics URLs/referrers.

Cloudflare Access provides authentication but does not remove the need for application-level request integrity and exact binding.

## Authoritative revalidation

Immediately before issuance and again immediately before consumption, Gate F must resolve the authoritative source rather than trusting browser/workflow payloads.

For Lead-backed approval:
- exact Lead ID;
- current `Modified_Time` canonicalized to UTC;
- `Converted__s is False`;
- active reviewed Lead status;
- `Email_Opt_Out is False`;
- exactly one valid customer recipient;
- exact reviewed/approved sender alias;
- exact subject/content reconstructed from the reviewed draft/template evidence;
- language prerequisite resolved to reviewed `fr` or `en`;
- if message-bound, exact immutable event hash and Internet Message-ID prerequisites.

Any source drift between display and issuance must force the operator to review a fresh candidate. Any source drift between issuance and consumption must block before provider send. A cross-provider change after the final CRM/source read but during the mail POST cannot be made atomic; this limitation must remain explicit.

## Draft/source binding

Gate E permits source types `lead`, `message`, and `draft`. Gate F must define how each is hydrated:

- `lead`: authoritative Zoho Lead + deterministic Phase 6 template/decision evidence;
- `message`: immutable event-ledger message identity/content hash + authoritative mailbox/read evidence;
- `draft`: only after a live-safe read contract proves how a Zoho draft is addressed/read and its exact subject/content/recipient/sender can be verified. Do not infer draft content from an ID alone.

Until draft readback is proven, Gate F should prefer Lead/message-backed approvals rather than trusting an opaque provider draft ID.

## Mailbox/provider read-only verification

Before any send canary, perform read-only verification of:

- mailbox account identity;
- sender aliases authorized for that account;
- scopes needed for mailbox/draft/message inspection;
- message Internet Message-ID availability for reply binding;
- Gate E documented request paths;
- provider acknowledgement shape using non-send/read evidence where possible.

Do not claim live send acknowledgement verification without an actual explicitly approved send canary.

## Registration and routing

Gate E's new outbound action currently has no production startup registration. Gate F must review registration separately.

If registered for deployment:
- import/register `lifecycle.mail_send_approved_v2` only after tests prove default observe/no-policy behavior;
- new workflow route must use `max_attempts: 1`;
- no active workflow may call the disabled legacy boolean handler;
- audit local/custom/queued workflow definitions read-only for legacy routes before production promotion;
- action registration does not itself authorize enabling `OPTIBRAIN_OUTBOUND_SENDS`.

## Canary policy

Default Gate F validation performs zero customer sends.

Any real send canary requires a separate explicit human decision after the exact candidate is displayed. The approval must bind the exact recipient, sender, subject, content, source and expiry. Prefer an explicitly reviewed Opticable-controlled external test mailbox rather than a customer. Do not substitute a self-addressed internal-domain recipient if the production action deliberately blocks internal recipients; the canary should exercise the real customer-domain safety path without involving a customer.

One send maximum. Never retry automatically. If provider result is ambiguous, stop in `manual`/`consuming` and investigate; do not reissue or resend just to make the test pass.

## Gate F implementation tests

At minimum cover:

- missing Access JWT rejected;
- invalid signature/issuer/AUD/expiry rejected;
- service-token/non-identity token rejected for issuance;
- request JSON cannot override human actor;
- authenticated-but-unauthorized human rejected;
- authorized human actor derived only from verified token;
- source changed between preview and issue rejected;
- opt-out/contactability/source/version drift rejected;
- content/recipient/sender changed after approval rejected at consumption boundary;
- operator preview and issuance perform no mail mutation;
- approval issuance is not registered as an automation action;
- outbound send registration, if added, defaults to observe with zero provider calls;
- registration workflow has exactly one attempt;
- legacy boolean route remains disabled/unavailable;
- Access/auth failure does not leak source/customer data;
- approval audit contains verified principal IDs/hashes but no JWT/token/raw secret;
- full inherited suite remains clean.

## Gate F exit criteria

Gate F is complete only when:

1. identity-aware human issuance/inspection is implemented and tested;
2. authoritative source/contactability/content revalidation is implemented and tested;
3. mailbox/provider read-only contract is verified;
4. registration/routing is reviewed and one-attempt/default-observe;
5. legacy bypass remains disabled;
6. production/main/recovery/protected files remain unchanged during engineering;
7. no live customer send occurs unless separately and explicitly approved;
8. engineering evidence records exact SHAs/test counts/limitations;
9. remaining Gate G deployment/backup/recovery/promotion work is explicit.

Gate F engineering is not production enablement. Gate G remains the separate deployment/recovery/promotion gate.