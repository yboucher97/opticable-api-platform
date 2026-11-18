# Command-center authentication and session recovery

This candidate repairs the existing command center based on installed source
`3c2a777ddcf04a2d002bc2a0aafeff0cb0551555`. It does not deploy itself, merge its
dependency PRs, or change Cloudflare, DNS, public tracking or business authority.

## Authentication return

Only a `GET /` with `Sec-Fetch-Mode: navigate` and `Sec-Fetch-Dest: document` can
pass the cross-site navigation check. A signed, unexpired Access human JWT for
the configured issuer, audience and exact owner is still required. Other paths,
cross-site API requests/mutations, ambiguous headers and embedded destinations
remain rejected. Host, HTTPS, Origin, CSRF, CSP and no-store/noindex checks remain.
Fetch Metadata is a request-context check, never an identity credential.

## Session behavior

The origin returns identity/session/absolute expiration metadata, never an Access
token. `session.js` keeps CSRF and session metadata in memory. It serializes
requests with rotation, uses an exclusive Web Lock across tabs, refreshes shared
CSRF metadata inside that lock, and deduplicates renewal. Exact-file downloads
use the same read queue; an owner-requested attachment is a transient Blob, not
an offline application cache. Rotation consumes the predecessor atomically at
the server. No old-cookie grace period is introduced.

Origin renewal occurs only near origin expiry when a later identity/absolute
ceiling permits an extension. A response that does not advance expiry suppresses
further rotation for that identity expiry. Without Web Locks, rotation is disabled
and the bounded sign-in flow is used at expiry. Failed consequential requests are
never replayed; the owner is told to check recorded status before another submit.

AJAX uses `X-Requested-With: XMLHttpRequest`, credentials on the same origin,
no-store and manual redirect handling. Expired identity requires a top-level
same-origin return. A two-minute URL attempt marker bounds automatic navigation;
an unsuccessful return leaves a manual Continue button. Only the section enum
and attempt time are query parameters; private records/credentials are not put
in storage or history state. The existing selected fragment is retained where
possible, with a section-only fallback if an identity provider drops it. A usable
verified return removes the marker. Pending decisions are never auto-submitted.

Visibility, focus and page restoration reconcile the actual cookie/session before
reading data. Hidden timers pause; private views are cleared on pagehide and on
session loss. Same-origin BroadcastChannel messages contain only a logout signal.

## Workday access and limits

### Logout and cookie scope

The logout response clears only cache/storage with `Clear-Site-Data` and expires
only `__Host-optibrain` explicitly. The origin session and current JWT hash are
still invalidated before the browser follows the unchanged application-domain
`/cdn-cgi/access/logout` URL. Clearing the registered domain's cookies here would
erase Access's cookie before that handoff, and could erase unrelated website
analytics, advertising and consent cookies. Those cookies must remain untouched
by the application's logout response.

Cloudflare documents the Access logout endpoint as revoking the user's session
across Access applications, including global SSO; app-domain versus team-domain
logout determines which domain's browser cookie is deleted. This repair retains
that existing meaning. It does not promise that other Access apps stay signed in,
log out the Google account itself, or make subsequent provider login silent.
Provider propagation and actual owner logout require separate live acceptance.

The existing loopback browser fixture supports `COMMAND_LOGOUT_ONLY=1`. It runs
the real production-mode application with a synthetic signing key/audience over
loopback, intercepting all browser requests before any public network access.
Synthetic Access/SSO and marketing cookies test the handoff, targeted deletion,
origin-token invalidation, fresh login and unrelated cookie continuity. Its
provider/global-revocation behavior is a model, not Cloudflare acceptance.

Browser prerequisites already available on the NEW VPS are the existing
`business-browser-tools-20261114`, `business-browser-cache` and
`business-browser-libs-20261114` directories under the development workspace.
Reuse them; do not download dependencies to work around an incorrect cache path.

Cookie scope reference: [W3C Clear-Site-Data](https://www.w3.org/TR/clear-site-data/#clear-cookies).

Keep the existing origin maximum of 20 minutes and eight-hour ceiling within an
origin renewal chain; sessions never outlive the currently verified Access JWT.
Fifteen-minute application tokens do not inherently require Google login every
15 minutes: a valid eligible global SSO session can issue replacement application
tokens. Actual organization-wide SSO duration is not known from the available GET
and is not changed. Eight-hour usability is modeled offline and needs real-owner
provider rollover/idle acceptance; it is not a verified production result.

Binding-cookie disablement is a separate security decision. Short tokens, Google
authentication, MFA if enabled, origin sessions and CSRF do not replace binding's
stolen-bearer replay protection. This source candidate grants no such approval.

Official behavior references:

- [Cloudflare session precedence, renewal and AJAX](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/)
- [Binding-cookie incompatibilities](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/#binding-cookie)
- [Fetch Metadata navigation and isolation](https://web.dev/articles/fetch-metadata)

## Validation and production gates

Run the existing `ops/business_autopilot/test_*.py` suite; it includes the
dependency-free Node session tests. Run `ops/phase6/validate.py --suite full` from
a checkout with full history; recovery tests require historical objects.

The explicit loopback fixture at
`ops/business_autopilot/browser_fixtures/auth_candidate.py` uses the existing
Playwright/axe installation, temporary synthetic data and a distinct issuer/key.
It runs the existing responsive/approval suite plus authentication scenarios.
Its mock SSO uses separate document navigations because Playwright interception
does not re-run the mock identity handler for every redirect hop. It proves real
Chromium Fetch Metadata, cookie and session-client behavior, not real Google or
Cloudflare acceptance. Fixture HTTP controls do not exist in the application
factory/production entrypoint, and fixture code is excluded from runtime staging.

Two separate exact owner approvals are required:

1. Install only the pinned runtime/manifest and corresponding installation receipt;
   restart only the command-center service. Keep Cloudflare and tracking unchanged.
2. After installation verification and a new live READY, run a newly authorized,
   bounded app-only authentication test with mandatory exact Access restoration.
   A proposed 25-minute window permits testing a real 15-minute token rollover.
   The old five-minute authorization and READY are consumed and cannot be reused.

Neither approval makes binding-cookie disablement permanent. Restore binding ON
and app/policy one-hour settings after the test even if it succeeds.

Use the reviewed target-only lifecycle: `systemctl --job-mode=ignore-dependencies
stop optibrain-command-center.service` and the corresponding target-only `start`.
First verify the current forward/reverse unit dependencies and all existing PIDs.
A plain stop can propagate through the Tunnel's `Requires=` dependency; no Tunnel
restart or service-unit change is included in the code-only approval. Place the
checkpoint next to the runtime on the same verified mount, not in `/var/lib`.

Rollback stops only the command center with that target-only procedure, restores the exact previous immutable
runtime/manifest and installation receipt, then restarts that service. Preserve
the current database, newer journal entries, files, credentials, backups and
all Cloudflare resources. Reload open owner tabs after code rollback. No schema
migration or database restore is needed; rollback restores the previous code's
known access limitations rather than promising remote availability.
