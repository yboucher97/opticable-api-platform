# Opticable Automation Master Runbook

Last updated: 2026-09-27
Authority: Git history + this runbook + machine-readable production state.
Rule: never store secret values in Git. Record only locations, scopes, IDs that are safe to retain, and recovery procedures.

## Canonical architecture
ChatGPT is the operator interface. optibrain.opticable.ca is the primary control plane. connect.opticable.ca is manual-disabled standby only.
Core execution lives in this repository and on the production VPS. Provider APIs are executors/data sources; business logic stays versioned here.

## Production infrastructure
- VPS host: vps-214ba8cd.vps.ovh.ca
- Public OptiBrain hostname: optibrain.opticable.ca
- IPv4: 148.113.249.7
- OS: Ubuntu 24.04
- Install root: /opt/opticable-api-platform
- Workflow API env: /etc/opticable-workflow-api.env
- GitHub App private key: /etc/optibrain/github-app.pem
- Zoho OAuth store: /var/lib/opticable-api-platform/shared/zoho-oauth.json
- Old VPS must not be modified until replacement is fully proven.

## Production services
- opticable-workflow-api.service
- opticable-password-pdf.service
- opticable-omada-site.service
- Public health: https://optibrain.opticable.ca/v1/system/health
- PDF health: https://optibrain.opticable.ca/pdf/health
- Omada health: https://optibrain.opticable.ca/omada/api/health

## Verified providers
- Zoho: local OAuth, 96 configured / 96 granted scopes, connected.
- Google: local OAuth, 30 scopes, Workspace/Admin + GA4/GTM/Search Console services configured.
- Windsor: connected and live-read verified.
- OVHcloud: signed API connected and live-read verified.
- Cloudflare: token active; opticable.ca zone read verified.
- GitHub: GitHub App auth, App ID 5077440, Installation ID 164914980; live repo read verified.
- Apollo: connected; credit-consuming endpoints disabled by OPTIBRAIN_ALLOW_APOLLO_CREDIT_CONSUMPTION=false.
- OpenAI: live end-to-end generation verified with gpt-5.6-luna.
- Anthropic: live end-to-end generation verified with workspace header support.
- Gemini: intentionally not configured yet.

## Safety gates
No automatic spending increases, purchases, ad-budget increases, payments, refunds, destructive production deletion, domain transfer, or credential rotation without explicit owner approval.
Normal reversible CRUD, monitoring, enrichment, classification, retries, logging, and idempotent reconciliation may be automated within provider limits.

## Deployment
Validation workflow: .github/workflows/validate-api-platform.yml
API deployment workflow: .github/workflows/deploy-api-platform.yml
Durable control plane deployment: .github/workflows/deploy-control-plane.yml

Production deployment status as of 2026-09-25:
- GitHub Actions deployment secrets are bootstrapped from the VPS using the GitHub App; secret values are never stored in Git or printed.
- Deploy API Platform is production-verified through restricted SSH and public health verification.
- Deploy Durable Control Plane is production-verified on Cloudflare.
- Worker URL: https://opticable-control-plane.yboucher.workers.dev
- Queues: opticable-business-events and opticable-business-events-dlq.
- Every control-plane deployment now verifies Worker health, submits an authenticated smoke event, and confirms the matching OptiBrain automation run completes. Verified event: control-plane-smoke-36185862240-1.

## Durable control plane
Cloudflare Worker path: apps/control-plane-worker
Responsibilities: authenticated event intake, queue buffering, dead-letter handling, idempotent workflow execution, correlation/causation propagation, delivery to the core automation API.
Queues: opticable-business-events and opticable-business-events-dlq.
Core event target: POST /v1/automation/events.

## Automatic production health monitoring
Workflow: .github/workflows/monitor-production-health.yml
Cadence: every 15 minutes plus manual dispatch.
Checks: workflow API, password PDF service, Omada service, durable Cloudflare control plane.
Failure behavior: open one GitHub incident issue and add subsequent failure observations as comments.
Recovery behavior: comment on and close the incident automatically.
The three VPS-backed endpoints were independently verified HTTP 200 from OPX001 on 2026-09-25; control-plane deployments also perform an authenticated end-to-end event smoke test.

## Recovery rules
1. Inspect current health before changing anything.
2. Preserve working state before risky changes.
3. Use branch -> validation -> PR -> merge for code changes.
4. Verify service/API health after deployment.
5. On failure, roll back to the last known-good commit instead of layering ad-hoc fixes.
6. Record each material failure, root cause, and successful repair in this runbook or Git history.
7. Never expose API keys, OAuth refresh tokens, private keys, passwords, or full secret files in chat or Git.

## Important resolved failures
- Phase 2B `restore-verify-latest` exposed a second checksum-format integration
  defect after the digest-pinned helper was installed. Phase 1 writes a standard
  sha256sum record whose filename is the absolute archive path. The helper's
  restore path correctly constrained the archive command target but its local
  parser accepted only the basename, so it rejected the sidecar before invoking
  the isolated restore verifier. `sha256sum -c` and the archive itself were
  valid. The compatibility repair parses exactly one lowercase digest, two
  spaces, the exact already-selected absolute archive path and one newline;
  basename-only records and any other path remain rejected. The verifier still
  checks the archive bytes against the parsed digest. No historical archive or
  sidecar should be rewritten. This is a C-class helper/updater release; see
  `docs/OPTIBRAIN_PHASE2B_ROOT_BOOTSTRAP.md` for preflight, install and rollback.
- Phase 2B bootstrap first updater attempt failed closed with audit code
  `invalid_digest_artifact`. The candidate's actual SHA-256 matched the
  updater's compiled approval exactly (`30aad73bb2b56a110e38348cce5babefb1816b7f1ffd7cd37449a51a0f1527c4`);
  the defect was artifact encoding: `optibrain-admin.sha256` had been generated
  as a `sha256sum` line (`<digest><two spaces><filename>`), while the updater
  correctly accepts only a raw lowercase digest and optional final newline.
  No helper replacement occurred; production stayed healthy, both backup
  timers stayed enabled/active, sudoers validated, and the old helper remained
  installed. Authorization pins consumed by Python must be raw 64-hex plus
  newline. `ROOT_BOOTSTRAP_SHA256SUMS` and backup archive sidecars consumed by
  `sha256sum -c` remain standard manifest lines. Repair details and preflight
  checks are in `docs/OPTIBRAIN_PHASE2B_ROOT_BOOTSTRAP.md`; do not repeat the
  first-install sudoers/updater/timer steps for this partial state.
- OpenAI 401 invalid_api_key: replaced invalid key; next failure showed billing_not_active; billing was activated; live test then returned OPTIBRAIN_OPENAI_OK.
- Anthropic 400 missing anthropic-workspace-id: added ANTHROPIC_WORKSPACE_ID support, header injection, installer preservation, regression test; live test then succeeded.
- GitHub static token dependence: replaced with GitHub App installation-token authentication while preserving read-only deploy key for checkout.
- Apollo cost risk: provider connected but credit-consuming endpoints remain disabled by default.
- VPS remote automation from OPX001: dedicated public key authorized on VPS, but Windows OpenSSH inside Remote Desktop Commander currently exits 255 even for local config operations; do not interpret this as VPS key rejection.

- Workflow context templating first CI attempt failed because the regular expression matched a literal "\\s" instead of whitespace; tests caught that templates stayed unresolved and missing references did not fail. Fixed by switching to an escape-safe whitespace character class. Second CI run passed all automation-kernel and control-plane checks. Dynamic templates now support event payloads and prior-step outputs, preserve native types for exact references, and fail durably when a reference is missing.

## Additional resolved production failures
- GitHub Actions originally lacked VPS and control-plane secrets. A one-command VPS bootstrap now uses the existing GitHub App and stored provider credentials to publish the required encrypted repository secrets and create a restricted deploy key.
- Control-plane CORE_API_URL pointed to non-resolving api01.opticable.ca; corrected to https://optibrain.opticable.ca.
- Wrangler 4.141 rejected `queues list --json`; queue reconciliation now uses the Cloudflare Queues REST API.
- Root deployment hit Git dubious-ownership protection; the exact production checkout is explicitly registered as a safe directory after root/install-path validation.
- Manual recovery of deploy/bootstrap-deploy-user.sh made the production tree dirty; deployment now self-heals only that known bootstrap artifact while continuing to refuse all other tracked modifications.
- Deployment cleanup referenced a function-local stage_dir after scope exit; stage_dir lifetime was corrected. API deployment then passed the full restricted-SSH deploy and public-health verification.

- Provider inventory returned HTTP 500 under health monitoring. Inventory was made failure-isolated so one provider status/property failure cannot take down the endpoint.
- The CI bootstrap had created /etc/optibrain as root-only (0700), making the GitHub App key invisible to the workflow service after restart. Fixed permanently by using root:opticable-workflow-api mode 0750 for the directory and root:opticable-workflow-api mode 0640 for github-app.pem; every deployment now repairs these permissions before service restart.
- After deployment, the full production health monitor passed, skipped incident creation, and automatically executed the recovery/close path for the existing incident.

## Current autonomy priorities
1. Build provider-specific declarative reconcilers and real event workflows.
2. Add provider credential/token expiry monitoring, retry/DLQ monitoring, and drift reconciliation.
3. Add deterministic UI fallback only for functions that have no adequate API.
4. Expand business-event sources (website/forms/email/CRM) into the durable control plane.
5. Keep this runbook and config/automation/production-state.yaml current after material changes.


## OptiBrain recovery hardening — 2026-09-27

Phase 1 is deployed: root-only local archive with checksum, per-file manifest,
consistent SQLite snapshot/integrity verification, seven-generation retention,
and hardened daily systemd timer. Complete implementation, resolved namespace/
Git-trust/setgid failures, and restore procedures are maintained in
`docs/OPTIBRAIN_PHASE1_LOCAL_BACKUP.md` (incorporated here by reference).
Runtime workflow version remains 1.7.0; no application deployment was performed.

Phase 2A: private R2 bucket `optibrain-recovery-prod` exists; r2.dev disabled and
no custom domains. Dedicated single-bucket object-write token was provisioned
through the account token API, policy read back, and unrelated-bucket access
verified denied. Credential custody: `/etc/optibrain/r2-uploader.env` root-only.
Public AGE recipient only: `/etc/optibrain/age-recipient`. No private identity was
created, read or placed on the VPS. Ubuntu age installed; packaged boto3 used.

The first encrypted generation passed complete remote GET/hash verification.
Uploader serializes executions, persists exact ciphertext for retries, conditionally
creates objects, refuses conflicts/non-404 errors, and records durable intent and
results. No remote deletion or retention automation. State and audit live in
`/var/lib/optibrain/phase2a/`; latest details are in
`docs/OPTIBRAIN_AUTONOMOUS_PROGRESS.md`. Phase 2A timer has since been installed, enabled and active after human offline
decryption/hash verification and an isolated archive/SQLite/config restore drill.
A booted replacement host, provider failover and immutable vault remain untested.
See `docs/OPTIBRAIN_PHASE2A_OFFHOST_RECOVERY.md` for exact recovery steps.

Package installation's needrestart restarted the password-PDF service; its public
health passed immediately. No application migration, Zoho mutation, firewall/SSH/
sudo policy change, or credential rotation occurred. Temporary overnight sudo was
used only for authorized inspection, backup infrastructure and root-owned records.
The old root-access blocker is resolved. Full approved Phases 2B–12 details were
not located in this checkout; recover that program before advancing beyond 2A.


### Phase 2A completion update — 2026-09-27

Human-attested separate-Windows-machine AGE decryption passed for generation
`20260927T021414Z`; encrypted and plaintext SHA-256 matched the server's verified
values. The identity stayed offline. A private-network isolated restore drill
verified all file hashes, restored SQLite integrity, extracted release source,
and replayed critical config ownership/modes in staging. It reported four legacy
Chromium manifest omissions, still protected by the independently verified whole
archive hash, and two transient WAL/SHM metadata entries; Phase 1 v1.0.1 corrects
future inventories.

The hardened Phase 2A service was installed as root-owned runtime code and passed
manual execution; generation `20260927T025414Z` uploaded and downloaded with full
hash verification. The daily Phase 2A timer is enabled/active. Phase 1 daily local
timer remains enabled/active. No remote deletion or retention task is configured.
Application runtime remains version 1.7.0. Current tests, references, service
state and remaining approved roadmap boundary are in the progress journal.


Current daily Phase 2A schedule uses `/usr/local/lib/optibrain-backup/`, a root:root
0750 runtime bundle. It avoids executing the optibrain-owned checkout from a root
unit with an empty capability set. Updates must install reviewed wrapper, uploader
and Phase 1 verifier into this bundle, validate the installed unit and manually
run it before enabling/sustaining the timer. Do not broaden checkout permissions
or add DAC-bypass capabilities.


The off-host unit only orders after Phase 1 (`After=`; no `Requires=`), preventing
an extra local generation that would shorten seven-generation retention. The
uploader rejects archives outside its 36-hour freshness window (with five minutes
of tolerated clock skew). A missed local run fails closed and is visible through
systemd/audit state. Latest code passed nine uploader fixture tests and a second
manual end-to-end hash verification without writing duplicate objects.

## Phase 6 closure and Phase 7 backup timer repair — 2026-09-29

Phase 6 Gate G closed at production/main
`0ade0ec02eeea5b503dc8eba8bea9c982cbf9240`, API 1.11.0, Schema V2.
External business-action flags remain disabled; no customer send, CRM/Books
mutation, Lead conversion or financial action was enabled by the release.
Direct rollback to the old Phase 5 code is unsafe for queued legacy CRM work;
use the validated corrected-code forward-recovery procedure in
`docs/OPTIBRAIN_PHASE6_GATE_G_RECOVERY.md`.

The local backup timer was held inactive during preserve-all Phase 6 recovery
work. Its first scheduled-service attempt failed before archive creation:
explicit `User=root`/`Group=root` combined with the sandbox prevented the
script's read-only `runuser -u optibrain` Git probe from changing UID. An
isolated systemd probe reproduced the failure with explicit `User=root` and
passed without those redundant declarations. The installed root-owned drop-in
`/etc/systemd/system/optibrain-backup.service.d/identity-switch.conf` clears
them and bounds capabilities to `CHOWN`, `DAC_OVERRIDE`, `DAC_READ_SEARCH`,
`FOWNER`, `SETGID` and `SETUID`. `NoNewPrivileges`, `RestrictSUIDSGID`,
`ProtectHome`, `ProtectSystem=strict`, private devices/tmp, and the root-only
runtime script remain. The preserve-existing override remains active, so
automatic runs do not prune prior recovery generations.

The repaired systemd service created generation `20260929T181245Z` from the
Phase 6 SHA. Archive SHA-256 `bdd07483af02b3effe1eafd01c1c6d17a62e23bb4846a041b02cbfeaa2b7f0ec`
passed its sidecar check. Isolated extraction verified manifest DB hash,
SQLite integrity, Schema V2, and workflow/audit/dedupe/journal tables. The
off-host service encrypted it, uploaded it, then downloaded and verified hashes
for the ciphertext and receipt; `generation_verified` was recorded. All 11
earlier local archives remained present, with about 55 GB free. The local timer
is enabled/active again, next due 2026-09-30 around 02:43 UTC. The source unit
and backup fixture regression have been updated on the Phase 7 branch; the
running application checkout has not changed.

The following paragraph is a historical pre-canary snapshot and is superseded
by the controlled live-canary record below. Phase 7 canary preparation is described in
`docs/OPTIBRAIN_PHASE7_CANARY_CONTROL.md`. Do not enable a broad CRM write flag
or outbound send flag for the first live canary. Require exact human-approved
record/action/content packages and single-use controls before either external
action. The provisional folder/relationship plan performs no provider mutation.
The Phase 7 branch also has an unregistered one-use CRM approval ledger and an
exact human review package generator. The unregistered authenticated operator
preview/issuance and one-record CRM executor use a distinct canary opt-in and
manual-on-ambiguity state. The current complete inherited regression is 656
tests / 706 subtests, zero failures/errors/skips; the final branch SHA needs
GitHub validation. No live canary Lead
has been created. A controlled external mailbox must be verified before a
customer-email canary can be proposed, and the outbound resolver's human-only
language binding is now bound to an authenticated human's exact review package.
The backup service's sandboxed identity-switch repair was verified by a real
timer-dispatched run, generation 20260929T184240Z. Local checksum, isolated
Schema V2 restore, encrypted off-host upload and downloaded hash all passed;
all 12 previous local generations were preserved. Both normal timers are active.

## Phase 7 controlled live canaries — 2026-09-29

Production/main `d2ca75d588665112d1d62329abfda23dd92d533f` stayed on API
1.11.0. Evidence is under
`/var/lib/optibrain/phase7/20260929-phase7-first-canary-sourcepin-200300/`.
Only the controlled test Lead `5062683000007880001` and recipient
`hckyan97@gmail.com` were used. Books, conversions, and real-customer actions
remained zero. Unrestricted external-action flags were disabled after each
single-use attempt.

Canary 2 issued one exact CRM patch for `Normalized_Email` and
`Next_Followup_At` (hash
`55e7169f6a6a9daa7b961d99f035facdadc5bff7e3dd5298305bef2c26451d77`).
Zoho applied both values, but returned the follow-up instant as `-04:00`
rather than `+00:00`; the production executor's raw string comparison left
approval `025ab8e57e6d4efdbb78ed53b5d191fe` terminal manual. Never retry
it. Read-only field-hash snapshots prove no unrelated business field changed.
The isolated narrow fix normalizes the readback instant before exact hash
verification; 11 focused executor tests pass. Deploy it through a future
guarded release before another CRM canary, and do not edit production source.

Canary 3 sent exactly one approved test email from `yboucher@opticable.ca`
to the controlled address. Approval `70e297032183447282587e943605e744`
was consumed; Zoho Mail message `1790714949014155100` was verified by direct
read-only Sent metadata/content retrieval. The first broad Sent search missed
it, so do not treat a missing search hit as permission to resend. Body hash:
`49f9cfa5838fbcb1d1c1d0d5aa2d439016d940d8dc3ca7e56479de60a9f19609`.

The existing AI website form posts to `connect.opticable.ca/public/lead`.
One controlled submission returned `updated_lead`, and Zoho readback showed
the same Lead plus source/inquiry attribution. Fresh exact-email search still
returned one Lead. The Zoho native Lead notification reached OptiBrain; Lead
observe, read-only reconcile, and sales-draft runs completed. Reconcile stayed
in `observe` and drafting stayed in `observe`; the decision was normal
priority, `draft_reply`, with the preserved follow-up instant. Internal
client/contact/company/site/project references and six local test-only folders
were generated; these are not provider IDs or production document folders.
The automation database remained Schema V2 with no queued/running/failed run.

## Manual mission control and Montreal business time — 2026-09-30

The persistent autonomous engineering worker is retired. Its dispatch,
status-email and usage-email services/timers are stopped and disabled. Original
controller state, queue, checkpoints, logs and code remain in place; a root-only
historical archive and manifest are under
`/var/lib/optibrain/autonomous-worker-retired-20260930T205928Z/`.
The worker must not be restarted automatically. Manually started Codex missions
retain full `NOPASSWD: ALL` sudo/root access. Production API, website, monitoring,
local backup and encrypted off-host backup remain on.

`America/Toronto` is the OptiBrain business/display timezone, including Montreal
EST/EDT transitions. The VPS timezone was set with `timedatectl`; system clock,
NTP and UTC RTC were not manually offset. Store aware instants (normally UTC),
compare them semantically, and display business dates/times in Montreal time
with offset/zone when ambiguous. Existing backup and off-host timers are pinned
to 02:30 and 03:00 **UTC** respectively; this preserves their previous instants
after the host timezone change. Phase 6 sales due dates and mail digest dates
already use Toronto business time. The legacy Phase 5 task due date and meeting
request timezone validation were repaired on the CRM-offset release branch.

The earlier Phase 7 readiness branch is historical only and must not be merged
or used to recreate Lead `5062683000007880001`. The CRM follow-up readback fix
on `phase7/live-crm-offset-reconciliation` compares equivalent UTC and Montreal
instants and fails closed on naive/malformed timestamps. The prior terminal
manual approval remains terminal; neither the Lead update nor test email should
be repeated. The guarded CRM-offset release moved production/main to
`3da4e9798a0cbd5ba4005fc8bda359eb5e483b23`; the release and its recovered
first staging failure are recorded in
`/var/lib/optibrain/phase7/20260930-crm-offset-release/RELEASE_RESULT.md`.

## Phase 8 controlled Lead sales view — 2026-09-30

The authenticated, read-only HTML view is
`GET /v1/operator/phase8/sales-view/5062683000007880001` at
`optibrain.opticable.ca`. It uses the existing verified human Cloudflare Access
identity boundary and is limited to the known controlled Lead. Each request
performs a bounded Lead GET, exact-email dedupe search, and same-version full
Lead GET. Local workflow history is opened SQLite read-only. It makes no CRM or
Mail write and has no send control.

The view distinguishes CRM fields from unconfirmed AI-site form details in the
Lead description, shows a bounded discovery/priority/quote recommendation,
missing site and scope details, one next action, the provider-owned follow-up,
an unsent draft preview, and exact-version workflow evidence. A matching
consumed outbound approval is shown as a prior send with its provider message
ID; the view tells the operator to check the inbox before further outreach.
An old workflow
review is not presented as current-version evidence when the CRM version
changes. Operator times use `America/Toronto`; durable instants remain aware/UTC.
Overdue follow-ups remain visible and are not silently moved forward. This
view proves one controlled Lead scenario; it does not prove a pipeline scan,
live Mail draft, automated follow-up task, or quote creation.

## Phase 8 inbox-aware follow-up — 2026-09-30

The same authenticated sales view now reads the known Sent message directly
from Zoho Mail and performs a bounded exact-sender search for inbound messages,
including Spam and Trash. A reply is linked only when its headers reference the
known outbound Internet Message-ID. Unlinked incoming mail, incomplete search,
or conflicting identity is shown as ambiguous and suppresses outreach advice.
At the Sep 30, 2026 6:08 PM EDT read, the controlled mailbox had no matching
inbound reply after message
`1790714949014155100`; the live state is WAIT until the existing CRM deadline,
Oct 1, 2026 at 5:00 PM EDT. No follow-up draft is shown while waiting.

The sent message's Zoho `sentDateInGMT` disagrees with its Date header and
receipt timestamp; the latter two agree within seconds and anchor the displayed
instant. All business times are displayed in `America/Toronto`. A due/overdue
recommendation also checks the last send, reply state, Lead status, and recent
CRM modification. Reply excerpts and labelled facts are advisory and require
operator verification before any CRM update or quote. This route performs GETs
and read-only local audit queries; it has no send or provider-write control.

## Phase 8 bounded sales queue — 2026-09-30

The same authenticated operator surface exposes
`GET /v1/operator/phase8/sales-queue`. It reads at most 15 recently modified
CRM Leads, 100 Contacts and 100 Accounts, plus the existing exact-identity
controlled Lead and Mail view when that Lead is in the sample. It labels the
result as a validation sample and marks list completeness. The route has no
write method. The persistent autonomous worker remains disabled.

The queue distinguishes verified CRM data from suggested name/company matches.
It never treats a suggested Contact or Account as a linked provider record.
Exact-email duplicate counts are authoritative only when the bounded Lead read
is complete. Unknown Lead status, unverified Mail history, and record age alone
cannot establish neglect or justify outreach. Quote review requires an open
Lead and recorded service, site, scope and timeline; contact details alone do
not qualify. The controlled Lead uses fresh thread-linked Mail evidence and
preserves its existing WAIT state. Other inbox states are explicitly NOT
CHECKED. Operator times use America/Toronto; internal comparisons use aware
instants. The queue never sends or creates provider drafts.

One manually invoked, root-only `ops/phase8/create_test_artifacts.py` may
create the authorized controlled test Task and unsent Mail draft. It checks
the exact controlled Lead, one exact email identity, known outbound message,
no linked reply, future CRM deadline, and prior equivalent artifacts first.
The Task transport grant is single-use and permits only one trigger-free
`Tasks` POST for Lead `5062683000007880001`; the production service has
no Phase 8 test Task flag. A root-owned attempt marker is persisted before
each write. After an ambiguous acknowledgement, only read-only reconciliation
is permitted; there is no automatic retry. Zoho Task `Due_Date` is a date,
so the exact 5:00 PM EDT follow-up remains on the Lead and is stated in the
test draft. The Mail payload uses `mode=draft`, the exact approved sender and
recipient, and readback must confirm the Drafts folder, address, subject and
content hash. The test draft must never be sent.

The first controlled Task POST was rejected with HTTP 400 `INVALID_DATA` on
`Who_Id`; an exact-subject read showed zero Tasks and no draft had been made.
Zoho's Tasks API associates a Lead through `What_Id: {"id": lead_id}` and
`$se_module: "Leads"`. The Phase 8 test boundary and the dormant Phase 6 Task
adapter now use this documented relation. The rejected attempt remains in the
root-owned artifact journal. A corrected attempt requires that explicit
rejection state, a fresh zero-match search, and a new exact payload hash; an
ambiguous outcome still blocks any retry.

Repeated standalone provider validation processes exhausted Zoho's OAuth
refresh rate briefly after artifact creation. An authentication refresh
failure is now surfaced as provider unavailable (HTTP 503 on the sales queue)
instead of a misleading Lead-evidence conflict (HTTP 409). No automatic
write retry or provider replay is added. Reuse long-lived service clients
and keep manual provider checks bounded.

## Phase 8 protected Test Lab and operating queue — 2026-09-30

The protected pre-mission CRM ID inventory and the nine synthetic Test Lab
scenarios are recorded in `ops/phase8/PROTECTED_PREEXISTING_RECORDS.json`,
`ops/phase8/TEST_LAB_REGISTRY.json`, and `docs/phase8-test-lab.md`. Root-owned
live state and provider reconciliation evidence are under
`/var/lib/optibrain/phase8/test-lab/`. Pre-existing records, including the
original controlled Lead, remain read-only. The root-only, single-call Test Lab
CRM boundary rejects protected IDs and relationships before transport. It
allows only registered Test Lab targets and clearly marked creations. Production
has no Test Lab write flag.

The authenticated sales queue's default scope excludes marked Test Lab Leads;
`?scope=lab` displays only provider-backed Test Lab IDs. Zoho gained
`OptiBrain_Test`, `Scope`, and `Project_Timeline` fields after checking that
they did not already exist. Use `OptiBrain_Test is not true` to exclude
synthetic records from real sales, marketing, and revenue reports. The queue
uses CRM/Task data and exact thread-bound Zoho Mail evidence for explainable
priority, quote readiness, missed follow-ups, relationship suggestions, and
unsent context-aware drafts. It displays business times in America/Toronto.
The Test Lab verified quote-ready→needs-information→quote-ready and
neglected→not-neglected→neglected transitions through readback of owned CRM
records. Two controlled outbound messages exist in Sent. The reply-path Lead
`5062683000007906010` received one provider-backed TEST_ONLY reply from the
verified `info@opticable.ca` alias on September 30 at 8:20 PM EDT. Zoho Inbox
message `1790814018711152600` has `In-Reply-To` and `References` matching
outbound `1790811285655138300`. The queue shows REPLIED — NEEDS RESPONSE,
new scope and timing from the reply, a contextual unsent draft, and no generic
chase. Reply-reported scope still requires human review before a quote. The
alias and primary sender share one mailbox; cross-provider delivery was not
tested. Evidence and IDs are in the Test Lab registry and
`docs/phase8-test-lab.md`. The persistent autonomous development worker
remains disabled.

## Phase 9 intake foundation — 2026-09-30

The active AI evaluation page posts to `connect.opticable.ca/public/lead`;
the main contact page embeds a Zoho Form. The connector already has canonical
`Inquiry_ID` replay protection and CRM first/latest attribution fields.
Phase 9 adds an immutable, provider-reconciled Test Lab intake/feedback ledger,
root-journaled public-route validation, a protected operator source trace, and
first/latest source context in the existing sales queue. Details and current
limitations are in `docs/phase9-intake-foundation.md`. The pre-existing CRM
baseline stays read-only; provider mutation is limited to OptiBrain-owned
TEST_ONLY records. No autonomous development dispatch or ad conversion export
is enabled.

Five provider-backed Phase 9 Test Lab intakes now include a new AI-site Lead,
same-identity AI and main-origin returns, explicit manual CRM intake, and
unknown-source intake. The three public submissions reused Lead
`5062683000007898003`; exact replay reused its event ID without another Lead.
Zoho preserved first traffic/source fields and updated latest touch. Synthetic
qualification, quote readiness, and Contact→Account→Deal links are audited in
the immutable internal feedback ledger. The Deal has no amount or Books entry.
`OptiBrain_Test=true` is present on all registered Test Lab Leads, Contacts,
Accounts, and Deals; native Zoho reports must filter this flag. One initial
public create failed on Zoho's datetime format and reconciled to zero records;
the connector fix was deployed. Zoho Search indexing lag required bounded list
readback for a subsequent successful create. Source-record IDs are now scoped
to their intake source. The main site's embedded Zoho Form mapping and fully
automatic event delivery to OptiBrain remained future Phase 9 work at this
checkpoint.

## Phase 9 active form and automatic receipt evidence — 2026-09-30

The main site's French contact page embeds Zoho Form
`i6pIlfoGOFER0OCZ4oUH_KMxVWRZKC9Of8vbyNAjR0g`; English embeds
`5kpuPyq6HG3cmmNAHG_2cFprnp16uoMzojC7Fxq42xo`. One controlled browser
submission through the French form produced authenticated Zoho Forms Mail
notification `1790820040661162800` and Lead `5062683000007935001`.
The native form-to-CRM mapping omitted Email and source/touch fields. The
read-only receipt collector records the original omission and matches a
unique CRM candidate by name, company, phone and creation time. It does not
patch real customer records. Only this registered TEST_ONLY Lead was repaired
under the protected-record firewall. Correct the native Zoho Forms mapping
before treating future form Leads as fully attributed or email-deduped.

The connector now exports immutable public-intake acknowledgements through a
dedicated read-only credential. A five-minute `opticable-phase9-intake-receipts`
timer polls that export and authenticated Zoho Forms Mail into
`phase9-form-receipts.db`; no Codex process or CRM write runs in this timer.
The authenticated `/v1/operator/phase9/intake-receipts` route shows provider
receipts, missing CRM fields and duplicate-review states. Source trace and the
Phase 8 Lab queue combine this chronology with the original feedback ledger.
Replay of the same provider identity is idempotent; conflicting evidence fails
closed. Store evidence as aware UTC instants and display Montreal time.

The Form-created Test Lead returned via the actual AI connector under inquiry
`bf53b28c-9e39-4507-ab60-a534665df473`: the same Lead was updated, first
source stayed `zoho_form`, latest source became `phase9_ai_return_test`, and
campaign `opticable_phase9_form_to_ai_test` was retained. A separate controlled
alias with the same test phone yielded `possible_duplicate` under inquiry
`cf2597db-2ab7-4c67-b0e2-1cb65fc666a3`; no Lead was merged or changed.
Exact IDs and journals are in `ops/phase9/TEST_LAB_REGISTRY.json` and
`/var/lib/optibrain/phase9/mission2/`.

Zoho public filtered views `Opticable Live Leads` and `Opticable Live
Opportunities` exclude `OptiBrain_Test=true`. Zoho did not persist attempted
criteria changes to built-in default views; those still include test rows and
must not be used for unfiltered business counts. The Test Lab Deal amount is
null. Email-to-CRM automatic intake and ad conversion export remain unverified.
The 99-record protected pre-existing CRM baseline remains read-only; autonomous
Codex dispatch remains disabled.

## Phase 9 active-form normalization — 2026-10-01

The French Form's historical Lead `5062683000007935001` was created by
`zoho_forms` at 2026-09-30 22:00:40 EDT with null Email and source/touch fields.
Zoho's CRM timeline shows the first field update at 22:27:13 EDT from the
historical guarded TEST_ONLY repair. This locates the defect in the native
Forms-to-CRM create mapping. Current Forms OAuth grants read access only; no
supported authenticated integration-admin write path was available.

The five-minute receipt collector now has a release-gated fallback for **new**
Form Leads after `/etc/optibrain/phase9-form-enrichment.env` go-live. It first
records authenticated provider Mail evidence and an immutable `OB-I-*` receipt.
It then requires one exact CRM match, a `zoho_forms` creation-only timeline,
unchanged provider version, no existing exact email in Leads/Contacts, and the
hash-pinned 99-record protected baseline before one trigger-free Lead PUT.
It fills only missing Email/source/touch/inquiry fields; TEST_ONLY submissions
also receive the canonical marker. An append-only ATTEMPTED journal precedes
transport; a lost acknowledgement is read back and never blindly retried.
Ambiguous evidence remains read-only for review. The old Form-created Lead is
before the go-live fence and will not be patched again. See
`docs/phase9-intake-foundation.md` for the exact field and evidence contract.

No customer email, Books write, autonomous Codex dispatch, or unrestricted
provider writer is enabled by this collector. Durable instants remain aware;
operator views display America/Toronto. Native Zoho Forms mapping should still
be corrected later through a supported Forms admin path when available; its
current omission is not silently treated as resolved.

One closure browser submission on 2026-10-01 produced Zoho Forms Mail
`1790856101554162800`, receipt `OB-I-0BF42F3190C4B699D4DFC4CA`, and
new TEST_ONLY Lead `5062683000007940001`. Browser detachment after the click
was reconciled through Mail, CRM and the ledger; the form was **not** resubmitted.
The Lead initially lacked Email/source. The collector made one guarded PUT,
read back Email `hckyan97+obp9closure1@gmail.com`, `zoho_form` first/latest
source, the receipt inquiry ID and TEST_ONLY marker, and journaled VERIFIED.
Its first feedback-ledger write failed because `phase9-intake.db` was root-owned;
the DB was preserved, assigned to `opticable-workflow-api` mode 0600, and
the next collector run recorded `LEAD_CREATED` without another CRM write.
Maintain this DB ownership on rebuilds. The controlled AI return inquiry
`d6aa615a-4004-4650-b341-c070c61b4e84` updated the same Lead and produced
event `OB-I-55B46DF5A6629BFF0464E68F`; first source stayed `zoho_form`,
latest source became `phase9_ai_return_test`, and campaign became
`opticable_phase9_closure_return_test`. Both provider receipts replay to their
original immutable events. Root evidence is retained under
`/var/lib/optibrain/phase9/closure/`.

During closure validation, short-lived root inspection processes and the
five-minute collector exhausted Zoho's token-refresh rate limit because each
new process refreshed independently. The collector was paused while this was
fixed. `ZohoOAuthManager` now uses a protected cross-process lock and persists
an expiry-aware access token separately from the refresh credential; normal
collector runs reuse that token until its safe refresh window. The cache and
lock live in the existing service-writable automation directory as
`zoho-access-cache.json` and `zoho-access-cache.lock`, owned by the API service
identity and mode 0600. The original refresh credential remains in its
restricted shared file. Keep these files accessible to
`opticable-workflow-api`; do not run frequent standalone refresh
probes. The receipt timer must be re-enabled only after one successful
collector run and API/provider readback following Zoho's cooldown.

## Phase 10 customer lifecycle foundation — 2026-10-01

The manually initiated Phase 10 mission added five narrowly scoped Deal facts
for installation, last service, maintenance due, renewal and recurring cadence.
The authenticated `/v1/operator/phase10/customer-lifecycle` view reads bounded
Accounts, Contacts and Deals. `scope=live` excludes `OptiBrain_Test=true`;
`scope=lab` requires the registered test IDs and visible marker. It displays
Montreal business dates, one next action and its provider-backed reason. No
customer write or outreach route was enabled.

Seven new TEST_ONLY Account→Contact→Deal chains and the existing Phase 9 chain
proved active project, completed cabling cross-sell, camera maintenance,
recurring service, renewal, dormancy, camera expansion and no-action behavior.
Zoho readback proved dormant and maintenance flags clear after new service or
future dates; moving a synthetic renewal into its 45-day window raised renewal
review. The synthetic dates were restored where needed so the Lab queue retains
the positive examples. Root evidence and the one-attempt operation journal live
under `/var/lib/optibrain/phase10/test-lab/`; the replay-stable lifecycle event
ledger added 19 events once and zero on a second sync. The protected 99-record
baseline remains unchanged. A sparse real historical Deal was evaluated
read-only and correctly remained `INSUFFICIENT DATA` for installed-service
history. See `docs/phase10-lifecycle-foundation.md` for exact decision rules.

The recurring section does not claim booked revenue or financial totals.
OptiBrain's live lifecycle counts exclude Test Lab data. Existing filtered Zoho
Lead/Deal operational views exclude tests; native Account/Contact default views
still display them and must not be used as real customer counts. Creating native
filtered Account/Contact views is the next test-exclusion gap. No autonomous
Codex dispatch, customer email, protected-record mutation or Books write was
introduced.

## Phase 10 service inventory extension — 2026-10-01

The manually initiated second Phase 10 mission reused native Zoho
`Service_Locations` and `Services` for Account→site→service→source Deal evidence.
Before Test Lab writes, 12 existing Services and 12 Service Locations were
captured in `/var/lib/optibrain/phase10/service-protected-baseline.json` and
pinned into the existing Test Lab registry. The original 99-record baseline
remains unchanged. Only registered TEST_ONLY service/site IDs can be changed;
all existing service records are read-only. Eight marked Test sites and ten
marked Test services now exercise one-time installation, maintenance, managed
Wi-Fi, PTP, VoIP, AI loss prevention, camera expansion, dormancy and a temporary
jobsite service. Exact IDs are in `ops/phase10/TEST_LAB_REGISTRY.json`.

The authenticated `/v1/operator/phase10/recurring-services` route reads fresh
Zoho Service and Service Location records. The lifecycle route uses those facts
with Deal context for a single action per Account. Explicit active contracts
and cadence/amount yield synthetic Lab MRR/ARR; no Books or real company
financial values are inferred. `scope=live` excludes Test Lab records and
leaves incomplete protected service history unknown. Operator dates use
America/Toronto. The application-owned 30-minute
`opticable-phase10-service-events.timer` reconciles read-only Test Lab Service
state into a local replay-safe event ledger; it does not invoke Codex or write
to Zoho. Native Zoho Account/Contact `All` defaults still contain Lab records;
do not use their unfiltered counts as business metrics. See
`docs/phase10-lifecycle-foundation.md` for the service model and evidence rules.

## Phase 11 operations foundation — 2026-10-01

The manually initiated Phase 11 mission reused Zoho Account, Contact, Deal,
Service Location and Service identity. CRM `Projects` is not supported by the
CRM API, so a small root-owned Test Lab crosswalk persists `OB-*` customer,
contact, site, project, work-order, ticket, service and task references. The
authenticated `/v1/operator/phase11/operations?scope=lab` and project detail
route read owned CRM records fresh and show one next action. Live scope does
not include Test Lab data or invent projects from sparse historical records.

One TEST_ONLY source-attributed warehouse chain progressed through a camera
installation, completed work order, installed Service, support Case, repair
work order and resolution. A Deal-linked document Task now drives the next
action. The six-category local folder tree and two synthetic text documents
are deterministic and hash-checked; WorkDrive folder creation is deferred
because the bounded team lookup found no isolated Lab destination. The root
Test Lab journal and immutable provider IDs are under
`/var/lib/optibrain/phase11/test-lab/`; the repository registry is
`ops/phase11/TEST_LAB_REGISTRY.json`. The Cases protected snapshot was taken
before its first write. Original 99 protected records and 12 Service/12 Site
snapshots remain read-only. A terminal-event replay defect was fixed and its
pre-repair ledger preserved; subsequent replays added zero events. No Codex
worker or new timer was installed. See `docs/phase11-operations-foundation.md`
for model, evidence and limitations.
