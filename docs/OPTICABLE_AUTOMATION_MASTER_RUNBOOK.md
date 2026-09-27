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
- Phase 2B is complete and the installed release is known good as of 2026-09-27.
  The human-validated helper self-test, latest-backup verification and isolated
  restore all pass; the restore checked 640 files, 675 metadata entries, one
  database, three critical configs and source extraction. All three service
  health endpoints returned HTTP 200; both backup timers were active/enabled;
  queue status reported 112 completed runs and disk use was about 14%. A fresh
  optibrain-identity check reconfirmed self-test, health, scheduler, latest
  checksum/archive, queue and capacity. Installed release SHA-256 values are
  helper `b6313a79357afed164d3d7bfd363dd14403b3c8853927c721370e1e94df17244`,
  updater `8f1f2fdecb8603f94f746532ecfa2b90a26f9ee4e57b3d6e70e74509e166dfe6`,
  restore verifier `58f9e2305329326c5dfdbb88af4d1535f33fda3f9fb6d03163212b7929fc7db6`.
  The installed runbook release digest is
  `cdab559d264fb7a17c469fd10953827a98a24ac4a926939db1055522a6dfc085`.
  The source recovery ref is `recovery/phase2b-production-known-good`;
  `recovery/phase2b-restore-compat` identifies the installed code baseline.
  Recheck health, both timers, installed hashes, `visudo -c`, latest checksum,
  audit and restore evidence before changing root artifacts. This updated
  source runbook is not yet installed in the root-owned location; its new pin
  needs a separately reviewed C-class sync.
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
- The Phase 2B audit-directory and runbook-metadata incidents were fail-closed
  installation-precondition mismatches, not reasons to relax helper validation.
  The helper requires `/var/log/optibrain` to be root:root 0700 and its audit
  file to be root:root 0600, regular, single-linked and non-symlinked. The
  runbook sync requires `/opt` root:root 0755, the checkout optibrain:optibrain
  0755, `docs` optibrain:optibrain 0775, destination runbook root:root 0644,
  staged candidate/pin optibrain:optibrain 0440, and root pin root:root 0440.
  Diagnose with `stat -c '%n %a %U:%G'` on these fixed paths and inspect the
  root audit; repair only the specific mismatched metadata through an approved
  root procedure, then rerun self-test/sync and health checks. Never bypass
  metadata checks, follow a symlink, edit arbitrary destinations, or restore
  broad sudo. The former on-disk metadata values and exact repair commands for
  these two incidents were not captured in this repository; do not invent them
  as historical evidence. Preserve the runbook's versioned old copy before any
  future sync and roll back only to its verified exact bytes if validation fails.
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
Phase 3 execution/control inventory, A–D operation classes, concrete gaps and
human resume gates are in `docs/OPTIBRAIN_PHASE3_EXECUTION_CONTROL.md`.
The Phase 3 application-only release `e5143d35ca1664a8b4faeda40f0f15a80fe7673d`
is deployed through validated main and the restricted deploy identity. It
makes event acceptance and matching queued-run creation one SQLite transaction
and adds authenticated, aggregate execution health for stale queued/running
work. It does not automatically replay a run or change root privileges,
Phase 1/2A timers or lifecycle schedules. Pre/post recovery refs are
`recovery/pre-phase3-deploy-4010398` and
`recovery/post-phase3-app-deploy-e5143d3`. The four application-file diff
matches the approved `883b081` checkpoint exactly; the application-only commit
was separately approved because the original checkpoint also changed this
root-owned runbook source. Production still has runbook digest
`cdab559d264fb7a17c469fd10953827a98a24ac4a926939db1055522a6dfc085`.
After deployment, all three health endpoints, helper self-test, both backup
timers and latest-backup verification passed. A naturally scheduled event
returned HTTP 200 and completed; queue status rose from 112 to 113 with no
queued/running runs. The new execution-health endpoint returned 401 without
the protected API key. An authenticated response and live duplicate drill
remain unverified from this operator identity.
This source runbook update is not root-synced. A future reviewed C-class
procedure must resolve the conflict between constrained runbook sync and the
deploy script's whole-checkout reset before installing a new runbook pin.

GitHub and Cloudflare lifecycle schedules overlap and remain unchanged.
OptiBrain is the long-term canonical owner for business scheduling, but migrate
one workflow at a time only after verifying shared idempotency identity and a
rollback path. No schedule was added or disabled for this Phase 3 release.

The subsequent Phase 3 claim/lease and retry prototypes are source-only and
not in production. They add a proposed SQLite claim table, fenced pre-action
markers, conservative human escalation for expired started work, bounded retry
decisions and a read-only failed-work view. A second proposed table records
fixed failure categories and safe reason codes atomically with terminal/audit
state. Completion now rejects expired leases even before recovery scans; an
expired started action records ambiguous external state for human review.
Both proposed tables are C-class schema migrations, and the engine does not
yet use these primitives. Do not assume automatic crash replay, dead-letter
redrive or provider-write retries exist in production. See
`docs/OPTIBRAIN_PHASE3_EXECUTION_CONTROL.md` for the exact safety boundary.

1. Build provider-specific declarative reconcilers and real event workflows.
2. Add provider credential/token expiry monitoring, retry/DLQ monitoring, and drift reconciliation.
3. Add deterministic UI fallback only for functions that have no adequate API.
4. Expand business-event sources (website/forms/email/CRM) into the durable control plane.
5. Keep this runbook and config/automation/production-state.yaml current after material changes.

## Phase 2B incident recovery lessons

The digest-format failure was an authorization-artifact encoding defect:
`sha256sum -c ops/admin/ROOT_BOOTSTRAP_SHA256SUMS` correctly consumes manifest
records, while the updater consumes only a raw lowercase digest. The audit code
was `invalid_digest_artifact`; the candidate bytes already matched the compiled
helper digest. The corrective action was to regenerate only the raw helper pin,
verify it against the reviewed candidate and compiled updater literal, then
rerun the fixed updater. Its own transaction preserves/restores exact previous
helper bytes on failure. Do not repeat first-install sudoers, timer or updater
steps after this partial-state failure.

The audit-directory and runbook-metadata gates failed closed when on-disk
preconditions did not match the helper policy. Diagnosis is a fixed-path
`stat -c '%n %a %U:%G'` and root-audit inspection, followed by a reviewed
repair of only the mismatched ownership/mode and a repeat self-test or
`sync-master-runbook`. The audit file must remain root:root 0600 in a root:root
0700 directory. For runbook sync, keep the source/pin staged optibrain:optibrain
0440, root pin root:root 0440 and destination root:root 0644; verify the
canonical directory chain and exact digest. The sync preserves the previous
runbook under `/var/lib/optibrain/admin-update/previous/`; use that verified
copy for rollback, then recheck its root pin, metadata and helper health. The
exact former bad metadata values and historical repair shell commands are not
preserved in Git, so no more specific claim is made.

The restore-sidecar failure was a second parser/producer mismatch: Phase 1
generated `sha256sum "${archive}" >"${archive}.sha256"` with an absolute path,
and `sha256sum -c` passed, but the old helper accepted only a basename. The
reviewed helper now accepts one strict record whose path equals the archive it
already selected, checks the digest and passes it to the isolated verifier.
Historical archives and sidecars were not rewritten. The helper release
required a matching digest-pinned updater; both old root binaries were
preserved. If this release must be rolled back, verify the exact prior helper,
updater and root pin together from the recorded copies, then run self-test,
`verify-latest`, isolated restore on a fresh generation where appropriate,
health and both timer checks. Keep the broad sudoers backup offline.

These incidents establish a release rule: test the producer and parser together
with actual production-shaped artifacts; verify path, owner, mode and pin
preconditions before attempting a privileged transaction; treat a fail-closed
audit code as recovery evidence; and never rewrite immutable backups to make
a new parser pass. Exact installation and rollback command sequences remain in
`docs/OPTIBRAIN_PHASE2B_ROOT_BOOTSTRAP.md`.



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
