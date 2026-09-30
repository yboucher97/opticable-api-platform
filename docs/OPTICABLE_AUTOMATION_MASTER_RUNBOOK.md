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
be repeated. The production/main SHA remains `d2ca75d` until a guarded release
is completed and verified.
