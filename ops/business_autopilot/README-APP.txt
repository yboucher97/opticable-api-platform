OptiBrain secure command center V1 — candidate, not a public deployment

This is a responsive adapter over the existing Review backend, AcquisitionStore,
action_evidence approval journal, business projections and storage budgets. It
adds no business database, provider writer, scheduler or agent framework.
The eight routes are Overview, Sales/projects, Marketing/SEO, Content/campaigns,
Review, Files/reports, System/storage and Settings. Packages paginate ten at a
time; artifact search paginates twelve. All91 originals and16 packages remain.
The top five review decisions and verified business/weekly projections are reused.
Unavailable attribution, project linkage and administrative functions stay explicit.

Authentication boundary
Every HTTP route,asset,JSON response and unknown route requires a signed human
Access JWT and the exact canonical HTTPS Host. Existing operator_access.py checks
RS256,kid,issuer,audience,exp,iat,nbf,type and human identity; the application
also rejects an expired primary token without leeway. Unknown users and service
tokens fail closed. Forwarding headers and claimed owner emails are never trusted.
No raw proxy,provider/admin or WebSocket transport is exposed. WebSockets are
unconditionally denied until a future separately reviewed implementation.

Google SSO through the existing identity provider is proposed for the already
verified owner info@opticable.ca. The other existing owner alias,service token and
all team/customer identities receive no new grant. Future viewer/reviewer roles
are implemented but have no bindings in the proposed production configuration.
The new app uses a separate Access audience; the current admin Access app remains.

Application sessions use a Secure,HttpOnly,SameSite=Strict,__Host- cookie,20-minute
maximum session and eight-hour absolute renewal bound,further limited by the
current primary JWT expiry. Every request still verifies the Access identity.
POSTs require exact Origin,bounded JSON and CSRF for renewal/logout/editorial
decisions. Login is an exact-origin POST after verified primary authentication.
Logout deletes the origin session and browser state and redirects to Cloudflare's
application logout. No username/password file or daily VPS sign-in is required
in the approved production flow. A pinned approved installation receipt permits
the same runtime to restart; it grants no provider-effect authority.

No business records,tokens or approval responses go to localStorage,sessionStorage,
IndexedDB,Cache API or a service worker. The web manifest supports standalone
installation where the browser permits it; offline operation is intentionally
unavailable. Installation prompts depend on browser/platform. Responses carry
no-store/private,noindex,nofollow,nosniff,CSP,self-only scripts and no framing.
Downloads are authenticated,hash-verified attachments; source text renders as
textContent. HTML/SVG content is never executed as an artifact preview.

Editorial separation
Review.validate_decision reuses exact existing payload/version/scope checks.
Production decisions call Review.decision with the authenticated human actor,
append immutable existing-journal evidence and authorize no external action.
Staging validates choices but records nothing. No package-wide approval exists.
The five existing customer-send proposals are available through a read-only
inspector showing exact recipient,subject,body,payload SHA,source artifact and
immutable receipt. Payload hashes are rechecked before display. No new proposal
is created and no send/external execution control is exposed.
No send,publish,spend,financial,production or general-settings write endpoint exists.
Existing45 consequential flags and all generation/deletion restrictions remain.

Staging and evidence
Only an isolated loopback HTTPS process on localhost8877 is started. The existing
localhost8876 process,credentials,expiry and trusted13-file runtime are unchanged.
Staging uses a distinct synthetic issuer,audience,email and public test key.
Those fixtures cannot authenticate to Cloudflare or any production audience.
No real owner JWT is manufactured. Staging has ProtectSystem=strict,no capabilities,
NoNewPrivileges,a read-only source bind,256MiB/30%CPU limits and egress limited to
localhost. No production DB clone or second app database is made for the preview.
Synthetic temporary journals are used only for tests.

Evidence family: /var/lib/optibrain/command-center-v1-20261114/ . It contains
Cloudflare/DNS/route/plan read receipts,registry preimages,test/CI proofs,screenshots,
the pinned official cloudflared binary and source/recovery artifacts. Private
staging keys/auth fixtures remain root-only and outside Git and owner reports.
The preview is time-limited and unavailable remotely before approved routing.
Its local certificate is pinned for tests,not a public CA certificate.

Exact proposed rollout
command_center_rollout.json is the reviewable zero-cost policy,not permission.
command_center_deploy.py only validates/seals that exact policy and renders the
two provider-returned ID slots; it has no provider mutation transport. Actual
source/config/binary/policy hashes must be checked against the owner-approved
package before administration. If configuration,identity,capacity,price or existing
resources drift,stop and revise the package; never overwrite an existing object.

The plan creates one separate Access app with its inline Google-only owner policy,
one NEW-host tunnel,one proxied app CNAME,one exact-host cache bypass and one
exact-host HTTP-to-HTTPS redirect. Zone-wide Always Use HTTPS was observed OFF;
do not alter that global setting. The two hostname-only rules protect this app
without changing existing sites. Existing Page Rules/origin-cache-control reads
were unavailable; the explicit app-only cache bypass is required.
No existing Worker route covers app.opticable.ca and none is changed.

Create and verify Access protection first,with no app DNS/public route. Before
DNS,verify policy/IDP/audience readback,no bypass/service policy,origin unauthorized
denial,local TLS trust and cloudflared access.required=true. Use a pre-DNS edge
probe where available; if protection cannot be established,stop before routing.
Only then start the exact guarded origin/tunnel and add the single app CNAME.
Verify an independent client receives HTTPS/Access challenge and no unauthenticated
data; verify real owner Google login,renewal/logout,mobile routes and core health.
No preview token,key or test audience may appear in the resolved production config.

Origin installation: root-owned /usr/local/share/optibrain-command-center-v1,
root-owned config/TLS under /etc/optibrain/command-center/,and an exact pinned
INSTALLED_APPROVED receipt at /etc/optibrain/command-center-rollout.json. The
receipt records config/manifest/source/policy hashes,owner approval,installation
time and the authorization window during which installation occurred. Do not
self-create it before approval or treat an old approval as new rollout authority.
Source manifest checks reject changed,extra,symlinked or writable members.

Production kernel write boundary
optibrain-command-center.service MUST use the enforced AppArmor profile in
optibrain-command-center.apparmor. SQLite DELETE journaling needs the canonical
automation parent writable in its mount namespace; AppArmor admits only the exact
existing phase12-autonomy.db and its -journal,-wal,-shm paths. All other current
and future sibling writes are denied. No monitor access change is installed.
This prevents the broad-parent/future-sibling defect in rejected approval B.
The launcher refuses production without that exact enforced profile. The profile
was kernel-tested against a synthetic journal: commit succeeds; a new sibling
and an existing writable marker both fail. Production data was not used for that
write test. A source/config/profile mismatch must prevent service startup.

cloudflared runs under a separate dynamic OS identity with a systemd-loaded
tunnel credential,not the app user's credential access. It binds no public
listener; its optional metrics bind localhost20277 only. Origin binds TLS only
on127.0.0.1:8877. The tunnel checks the new audience and verified origin TLS,
forces canonical Host and ends with a404 catch-all. Core ports8876/8100/databases
remain private. Proposed production origin certificates must be issued for app
with a separately pinned CA; the short-lived staging certificate is not reused.
The tunnel's ingress config and public origin CA also use systemd LoadCredential,
so its dynamic identity needs no access to the app's private config directory.
Production app config,origin TLS key and installation receipt are root:service0640
under a root:service0750 directory; tunnel secret/config stay root-only0600 and
are exposed only in the tunnel service's private credential mount. No team or
general filesystem permission is inferred from these scoped service identities.
Monitor origin certificate expiry and rotate through the existing operator/recovery
procedure before expiry; do not disable certificate verification to repair it.

Rollback — code/config/routing only,never journals or newer credentials
1. Capture the created-object IDs and current values. Delete only the new app
   CNAME if its ID/type/name/target still match the approved installation receipt.
   If it drifted,stop the new origin/tunnel first and retain Access protection.
2. Stop/disable only optibrain-command-tunnel and optibrain-command-center. Do
   not restart or alter Caddy,core API,existing observers,timers or OLD VPS.
3. Keep Access protection until the public route is confirmed absent. Then remove
   only this mission's new tunnel/Access app and two exact rules by recorded IDs.
   Remove a newly created ruleset only if it still contains only our exact rule;
   preserve any newer rules. Leave the existing admin Access app untouched.
4. Revert only this app's installed code/config/profile using exact preimages;
   preserve the journal,all artifacts,review history,backups and newer TLS/auth
   credentials as evidence. Restore45-OFF/76-setting/core-health proof.

For current staging rollback only:
sudo systemctl stop optibrain-command-center-preview.service
This transient unit creates no timer or persistent public configuration. Stop
it without deleting any screenshot,test,recovery or private-key evidence.

Recovery continues to use the existing Git/R2/passive systems. A recovered app
starts stopped,with no route; revalidate source,Access,identities,keys and current
owner authorization before exposing it. Never restore an old DB to roll back UI.
Retention A stays deferred and monitor B rejected; no storage deletion is enabled.
