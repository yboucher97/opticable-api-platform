# OptiBrain autonomous resume journal

Roadmap version: OptiBrain approved Phase 2B–12 roadmap, 2026-09-27.
Current phase: Phase 2B autonomous privileged operator.
Status: IN PROGRESS. Phase 2A complete; Phase 2B implementation is starting.
The earlier human-action boundary below is superseded by the roadmap supplied
in this session. Rediscover live state before relying on historical entries.

- Running production baseline / last known good SHA: `936e75a` (Phase 1).
  Working checkout: `hardening/phase2a-resume`; resolve its checkpoint SHA with
  `git rev-parse HEAD`. No service restart/deployment accompanied this commit.
- Latest verified-phase recovery reference: `heads/recovery/post-phase1-936e75a`.
  Parser-only checkpoint baseline: `recovery/pre-phase2a-parser-936e75a`.
- Historical Phase 1 baseline below is retained from the original checkpoint.
  Current local generation: `20260927T025414Z`; verified SHA sidecar and archive.
- Current off-host generation: `20260927T025414Z`, full encrypted GET/hash verified.
  The human independently decrypted and hash-matched `20260927T021414Z`.
- Both Phase 1 local and Phase 2A off-host timers are enabled/active. Latest manual
  local and off-host services completed successfully; see final verification below.
- Production workflow API: HTTP 200, status=ok, version=1.7.0; PDF/Omada health
  also pass. Sudo and credentials are available under the temporary authorization.
- Completed migrations: none this session.
- Provider mutations: none this session. Previous bootstrap may have created
  `optibrain-recovery-prod` before failing its list parser; do not assume absent
  or repeat creation without an authenticated read.
- Services changed: none this session.
- Checkpoint commit initially failed because this shell has no Git author
  identity; retry uses command-scoped `OptiBrain Automation <optibrain@localhost>`
  without changing global configuration.
- Existing Phase 2A files were untracked on arrival. Bootstrap and health tests
  are included in the parser checkpoint; all other pre-existing Phase 2A
  discovery/auth scripts, uploader/config/units, two documents and uploader test
  intentionally remain uncommitted work in progress. Preserve them; they are
  not production-approved.
- Findings: bootstrap expects `result` to be an array; Cloudflare documents
  `result.buckets`. Listing errors are also lost through process substitution.
  Master runbook remains stale at 2026-09-25. No AGENTS.md found in checkout or
  ancestor paths. Runbook's `config/automation/production-state.yaml` is absent.
  Updating the root-owned master runbook failed with permission denied; merge
  this checkpoint and the Phase 1 record into it when privileged access returns.
  `/var/lib/optibrain` is absent, so no existing machine-state location was updated.
- Uploader review concerns: AGE randomness prevents retry comparison against
  newly encrypted bytes; remote metadata alone is not a download/hash drill;
  failed HEAD must not be treated as definite absence; mutation intent and
  crash-safe upload checkpoints are missing. Resolve before activation.
- Fix: bootstrap now validates `result.buckets` and fails closed for malformed
  listings; listing failures propagate before creation. Regression fixtures pass
  for populated/empty buckets, invalid/error responses, and HTTP failure.
  Health regression and non-root uploader policy tests pass; shell syntax and
  diff whitespace checks pass. Root uploader functional test was not run.
- Public production health also returned HTTP 200. No protected archive contents
  or credential values were read. No provider writes, migrations, service
  changes, off-host uploads, or timer activation occurred.
- Discovery script still uses the obsolete list shape and needs the same fix
  before it is used to conclude the target is absent.

## Original checkpoint next operation (completed)

Local parser repair was checkpointed on `hardening/phase2a-resume`; it is not a
completed phase or deployment. Once privileged execution is available, verify
the current local archive and production, create
the pre-phase recovery reference, and run authenticated read-only bucket and
privacy discovery. Inspect credential presence without printing values. Record
durable intent before any provider mutation and result immediately afterward.
Do not enable uploader timer until dedicated bucket scope, encryption, upload,
download/hash verification, and safe retention are proven.

## Historical human boundary (resolved)

At the original checkpoint this shell ran as `optibrain` (uid 1001), with no noninteractive sudo access.
Root-only backups and bootstrap credentials cannot be inspected; root service
installation cannot proceed. Operator must provide an approved privileged
execution session. Do not paste passwords or secrets into Codex. Any dashboard
credential requirement must be established after authenticated discovery.

Resume instruction: Read this journal and the master runbook, rediscover Git and
live state, then resume Phase 2A from the exact next safe operation above.

## Overnight resume — 2026-09-27: privileged discovery

- Temporary `sudo -n true` succeeded. Earlier root-access boundary is resolved;
  no sudo policy or other security controls were changed.
- Pre-change reference: `recovery/pre-phase2a-overnight-9f9d801`.
- Read-only discovery confirms bootstrap account token active, target R2 bucket
  already exists, and bucket-list access works. No bucket creation was necessary.
- Latest local archive remains `optibrain-backup-20260926T232858Z.tar.gz`
  (269147506 bytes); external checksum and full non-destructive archive/SQLite
  verification both passed. Backup timer enabled/active, service result success.
- Public and local workflow health HTTP 200, status ok, version 1.7.0.
- Public recipient exists, root-owned 0644. Dedicated uploader credentials and
  phase2a configuration are absent; age and aws executables are absent.
- Discovery parser repaired to validate `result.buckets` and propagate failure;
  production health now exits unsuccessfully when unhealthy.
- Current Cloudflare documentation supports API creation of R2 credentials and
  derivation of S3 keys; the prior blanket dashboard-only assertion is incorrect.
  Read-only token-management capability and bucket privacy checks are in progress.
  Source: https://developers.cloudflare.com/r2/api/tokens/
- No provider writes, service restarts, migrations, uploads or timer activation.
- Full Phases 2B–12 approved program is not present in searched repository docs,
  config (absent), or ops paths; only its title exists in this journal.

### Intent: Phase 2A dependencies and dedicated credential

Recovery verified above; pre-change reference `recovery/pre-phase2a-overnight-9f9d801`.
Bucket privacy verified by authenticated GET: managed public access disabled,
custom-domain count zero. Bootstrap policy explicitly grants Account API Tokens
Read and Write. No named `optibrain-recovery-uploader` token exists.
Proceed with trusted Ubuntu package installation of age/awscli and one dedicated
account token with only Workers R2 Storage Bucket Item Write on the single
`optibrain-recovery-prod` default-jurisdiction bucket. This implements the
approved least-privilege backup design; existing credentials will not be changed.
Credential is stored root-only, never displayed. On ambiguous creation failure,
stop and reconcile by token name; never blindly retry creation. Rollback is to
leave uploader disabled and revoke only the new token if required after review.
No bucket deletion or retention changes are authorized by this operation.

### Completed: dedicated R2 credential

Created `optibrain-recovery-uploader` through the account token API and read back
its exact policy: one allow policy, Workers R2 Storage Bucket Item Write only,
single default-jurisdiction recovery bucket. Credentials saved to
`/etc/optibrain/r2-uploader.env`, root-only 0600. Protected intermediate creation
response removed after successful validation and durable credential write.
No existing token changed. No credential value entered Git or logs.
Initial apt install found stale package indexes; refreshed indexes successfully.

### Dependency adjustment

Ubuntu repositories have no awscli candidate even after index refresh; no packages
were installed by the failed attempts. Ubuntu's python3-boto3 1.34.46 is already
installed. Use that packaged S3 SDK and install age only. Uploader repair will
preserve encrypted bytes across retries, serialize execution, fail closed on
non-404 reads, use conditional creation, and verify downloaded bytes before
recording success. Keep scheduling disabled pending offline recovery validation.

### Completed: encryption dependency

Installed Ubuntu age 1.1.1-1ubuntu0.24.04.3 successfully. Existing packaged boto3
will supply S3 access; awscli remains absent. Package-manager needrestart restarted
`opticable-password-pdf.service`; public PDF health was checked immediately.
Uploader rewritten around durable ciphertext preparation, conditional PUT,
serialized execution, bounded SDK retries, and independent full download hashing.
No upload or scheduling yet; regression validation precedes activation.

### Validation and intent: first encrypted recovery upload

- Six uploader regressions passed: ambiguous completed PUT reuses ciphertext,
  denied HEAD prevents upload, downloaded corruption prevents success, changed
  source refuses overwrite, conditional creation header, corrupt local checksum.
  An initial AGE-header byte-count error was caught and fixed before live use.
- Discovery parser fixtures pass; existing bootstrap parser and health tests pass.
- Dedicated credential can list the empty target bucket; unrelated-bucket list
  returns HTTP 403. Root-owned phase2a.conf created with account ID only.
- Intent: encrypt verified local generation 20260926T232858Z using existing public
  recipient, PUT only encrypted object and non-secret manifest with conditional
  creation, then GET/hash both. Local source and encrypted spool are retained.
  No remote retention/deletion, no schedule enablement. Runtime recovery remains
  Phase 1 archive and pre-phase Git reference. Offline decryption remains human-only.

### Completed: first encrypted off-host verification

Generation `20260926T232858Z` encrypted and conditionally uploaded successfully.
Full downloaded-byte SHA-256 and length matched for both encrypted archive and
JSON manifest. State: `/var/lib/optibrain/phase2a/state.json`; durable mutation
log: `/var/lib/optibrain/phase2a/audit.jsonl`; prepared ciphertext retained under
`/var/lib/optibrain/phase2a/20260926T232858Z/` for retry/recovery.
Object: `backups/2026/09/26/20260926T232858Z.tar.gz.age` (plus `.json`).
Offline restore remains unverified. No schedule enabled, no data deleted.

### Completed: live retry and documentation checkpoint

Second live uploader invocation downloaded/hashed both existing objects and
recorded success without any PUT. The durable audit confirms no overwrite.
Master runbook now incorporates Phase 1 and records Phase 2A live state; stale
claims about root access and mandatory dashboard credential creation superseded.
Uploader regression coverage and recovery procedure are repository-backed.
Package-manager-triggered PDF restart passed health. No uploader unit is installed.

### Intent: post-change recovery generation

Checkpoint reviewed non-secret recovery source/docs/tests on the existing branch,
then run the existing Phase 1 backup service to capture that commit and protected
credential/configuration state. Existing archive remains verified and retained;
there are fewer than seven generations, so retention will delete nothing.
Upload/download-hash the new generation with the tested uploader, then record
production health, exact next operation and recovery reference before stopping at
the human-only offline decryption boundary.

### Completed: post-change local backup

Implementation checkpoint: `f7ad1c2`. Phase 1 service completed successfully
(exit 0), producing `optibrain-backup-20260927T021414Z.tar.gz` (269206822 bytes),
including committed source and updated protected configuration. Original archive
retained. Workflow/PDF/Omada services active and public health checks pass.
Next operation (authorized above): uploader independently verifies this new local
archive, encrypts/uploads it and verifies full remote downloads.

### Completed: post-change off-host recovery copy

Generation `20260927T021414Z` passed local checksum and full archive verification,
AGE encryption, conditional object/manifest creation, and full downloaded-byte
hash verification for both remote objects. File security verified: archive and
checksum root:root 0600, backup directory root:root 0700. Timer is not installed
(`LoadState=not-found`, inactive). The first remote generation is also retained.

## Superseded handoff before offline evidence arrived

Historical status before the user supplied offline recovery evidence; the offline
recovery and Phase 2A activation are completed in entries below.

1. Human: use the matching offline identity on a separate trusted recovery machine
   to decrypt generation `20260927T021414Z`, verify plaintext SHA-256, and perform
   the isolated Phase 1 restore validation described in
   `docs/OPTIBRAIN_PHASE2A_OFFHOST_RECOVERY.md`. Return non-secret results only.
   Never place the identity on this VPS or send it to Codex.
2. Resume: read this journal/runbook, verify live health, protected backup state,
   and dedicated token scope. Record offline evidence. Then validate/install and
   manually test the hardened upload service before timer activation. Retention
   remains non-destructive; monitor retained spool and remote storage growth.
3. Recover the full approved Phases 2B–12 program from the operator before those
   phases; its title alone is recorded in this checkout. Do not invent its scope.

Runtime: workflow 1.7.0, unchanged application deployment; local backup timer
active/enabled. Implementation source checkpoint `f7ad1c2` is included in the new
local/off-host generation. Final journal-only checkpoint follows this entry.
Pre-change recovery: `recovery/pre-phase2a-overnight-9f9d801`.
Final recovery reference: `recovery/post-phase2a-offhost-20260927` (resolve SHA).
No remote Git push/PR or application deployment was performed.

Preserved pre-existing untracked file:
`ops/backup/optibrain-cloudflare-auth-diagnostic.sh` (not reviewed/deployed).
All other reviewed Phase 2A implementation, tests and docs are committed.

No Zoho mutations, financial actions, private AGE-key operations, remote data
removal, firewall/SSH/auth/sudo policy changes, or production credential rotations.
The dedicated recovery credential is new and bucket-restricted; production token
is unchanged. This temporary sudo authorization has not been made permanent.

### Independent checksum evidence and final health

Latest verified remote object:
`backups/2026/09/27/20260927T025414Z.tar.gz.age`

- Ciphertext SHA-256: `4e75906e0791d192ab296eea1f1a8e814c59fe7c081cf488c1341ed7a2cb89ed`
- Plaintext archive SHA-256: `c802d153a261e28f86440c718cddd06dfc1b7f19e157d72c058c7eaaede16792`
- Remote verification completed: 2026-09-27T02:16:26Z.
- Final public workflow/PDF/Omada responses successful; backup service result
  success, exit 0; local backup timer active. No atomic operation remains running.

## Human recovery evidence received — 2026-09-27

Human reports a fresh R2 download on a separate Windows recovery machine for
`20260927T021414Z`, object `backups/2026/09/27/20260927T021414Z.tar.gz.age`.
AGE v1.3.1 successfully decrypted it with the offline human-held identity.
- Encrypted SHA-256: `4e75906e0791d192ab296eea1f1a8e814c59fe7c081cf488c1341ed7a2cb89ed`
- Recovered plaintext SHA-256: `c802d153a261e28f86440c718cddd06dfc1b7f19e157d72c058c7eaaede16792`
- OFFLINE AGE DECRYPTION: PASS (human-attested).
- SOURCE SHA-256 MATCH: PASS (human-attested).
The private identity remains only on the human-controlled Windows machine; it
was not copied to VPS, Git, Cloudflare, Codex or ChatGPT. No private key is needed
for the remaining local archive validation: SHA-256 equality ties the local
archive to the independently recovered plaintext. An isolated extraction,
manifest/file checks, SQLite integrity, source export and ownership/configuration
recovery validation will supplement this evidence. This is not a claim that a
replacement production host or live provider failover has been tested.

### Intent: isolated archive recovery validation

Live workflow health is ok/1.7.0; Phase 1 timer active with a successful additional
scheduled generation `20260927T023955Z`. Pre-activation recovery reference:
`recovery/pre-phase2a-activation-d69e02b`. Validate the exact human-verified local
archive SHA-256, safely extract into root-only temporary staging in a private
network namespace, verify every manifest file and SQLite copy, extract source,
and exercise critical configuration ownership/mode restoration in staging only.
No recovered service or provider call will execute. Temporary extracted copies
are cleaned up; all existing backup generations are preserved. Non-secret result
is retained under `/var/lib/optibrain/restore-drills/`.

### Validation finding (before activation)

All existing Phase 1/2A fixtures and unit syntax checks pass. Fixed Phase 1 test
isolation to explicitly avoid loading installed production backup.conf during
fixture creation. Current R2 privacy and dedicated scope read-back pass.
Isolated drill stopped because the historical manifest does not cover every
archive file. Investigation found the Phase 1 generator excludes every file named
manifest.json instead of only its own root manifest. No archive or production
state was changed. Compare actual omitted paths before choosing a compatibility
rule; the independent whole-archive SHA-256 remains a verified integrity anchor.

### Intent: correct future manifest coverage

The four omitted entries are Chromium runtime dependency manifests, not missing
archive members. Their bytes remain covered by the human-verified archive hash.
Apply a minimal Phase 1 fix: exclude only the top-level generated manifest, bump
backup script version to 1.0.1, and add a nested-manifest fixture assertion.
Rollback is the pre-activation Git reference; no existing archive will be edited.
The isolated validator will allow only this precisely identified legacy 1.0.0
omission and report its count; new-format coverage must be complete. No runtime
cache exclusions are introduced. Existing recoverable data remains unchanged.

Further drill finding: historical source metadata lists two transient SQLite
WAL/SHM paths intentionally excluded from the archive. The consistent online
SQLite snapshot is the recovery artifact; stale WAL/SHM must not be restored.
Future metadata generation now matches these existing exclusions. Legacy drill
reports both omitted transient entries explicitly; missing durable files still
fail validation. The repeated drill failures affected only disposable staging.

### Completed: isolated restore and activation gates

Network-isolated drill passed for human-verified generation `20260927T021414Z`:
636 manifest file checks, 675 metadata entries validated, one SQLite database
restored/integrity-checked, versioned source extracted, three critical config
files restored with verified uid/gid/mode/content. Four legacy Chromium manifests
are protected by the independently verified whole-archive hash; two transient
SQLite metadata entries are intentionally omitted. No service was started from
restored state. Result: `/var/lib/optibrain/restore-drills/20260927T021414Z-result.json`.

Phase 1 v1.0.1 fixture passes with nested manifest coverage, transient-sidecar
metadata exclusion and installed-config isolation. Two new extraction-safety tests
pass. Existing six uploader cases, bucket parsers, health cases and all four
systemd units validate. No private identity was accessed.

### Intent: manual hardened service activation

Install only the already-validated off-host service/timer unit files, reload
systemd, and manually start the upload service. Its existing dependency creates
and verifies a fresh Phase 1 snapshot first. Three local generations currently
exist, so the seven-generation retention threshold is not reached; no backups
will be deleted. Verify upload/download hashes and hardened service result before
enabling scheduling. Rollback: stop/disable only the new upload timer/service,
restore pre-activation code if required, and retain all recovery data and Phase 1
scheduling. Production API behavior and application services are unchanged.

### Completed mutation: unit installation

Source checkpoint `56112e8`. Off-host service and timer installed root:root 0644;
systemd daemon reload and installed-unit verification passed. Manual hardened
service was queued successfully. Scheduling remains disabled pending its result.

### Hardened service failure and repair intent

Manual dependency created/verified generation `20260927T025210Z` successfully;
four local archives now exist, none deleted. Uploader exited 126 before any upload:
checkout shell script is owned by optibrain mode 0750, so root with an empty
CapabilityBoundingSet cannot read it. Preserve capability and permission controls.
Install a root:root 0750 runtime directory `/usr/local/lib/optibrain-backup` with
root-owned uploader wrapper/Python module and Phase 1 verifier, then point only
the off-host unit there. This avoids running writable checkout code under the
hardened scheduler. Do not expand modes or restore DAC-bypass capabilities.
Retry once after unit validation; preserve all existing archives/remote objects.

### Completed mutation: hardened runtime deployment

Root-owned runtime bundle installed with directory/files mode 0750, no capability
or source-file permission expansion. Off-host unit now executes that bundle;
installed-unit validation and daemon reload passed. Second manual run queued.

### Completed: manual hardened off-host service

After the checkout-permission failure, the root-owned runtime bundle ran the
hardened service successfully with its original empty capability set. Its Phase 1
dependency created and verified local generation `20260927T025414Z`; all four
existing backups remain present. Encrypted generation `20260927T025414Z` then
passed conditional upload and full downloaded-byte hash verification for both
archive and JSON sidecar. Service result success/exit 0 at 2026-09-27 02:55:55Z.
The earlier 126 failure preceded all provider writes; no duplicate or partial
object resulted. No service privilege or file mode was expanded.

### Intent: enable Phase 2A schedule

Recovery references: pre-activation `recovery/pre-phase2a-activation-d69e02b`;
latest encrypted generations `20260927T021414Z` (human decryption + isolated
restore) and `20260927T025414Z` (manual hardened service + remote read-back).
Phase 1 timer is enabled/active. All Phase 2A fixture tests and installed systemd
unit validation pass. Enable only the validated upload timer. Verify active and
enabled state without stopping or modifying Phase 1 scheduling.

### Completed: Phase 2A scheduled activation

`optibrain-phase2a-upload.timer` enabled and active. Phase 1 local timer remains
enabled and active. This daily 03:00 UTC timer runs the manual-tested root-owned
hardened service. No retention deletion is configured in Phase 2A; local Phase 1
policy remains seven valid generations. Next scheduled off-host run will create a
new local Phase 1 generation as a service dependency, then upload/verify it.


### Completed: final regression and live-state verification

- Six encrypted uploader tests passed: retry after ambiguous PUT uses the same
  ciphertext, denied HEAD prevents writes, downloaded corruption blocks success,
  source changes refuse overwrite, create-only header, and bad local checksum.
- Bucket-list tests passed for bootstrap and discovery parsers, including malformed
  and failed responses. Health failure tests passed. Restore extraction safety
  tests passed (traversal, absolute paths, symlinks and wrong source checksum).
- Root-run Phase 1 backup fixture passed, including nested manifest checksums and
  transient SQLite sidecar metadata exclusion. All four installed systemd units
  validated. Private-network restore drill passed as recorded above.
- Phase 2A daily timer installed/enabled/active. Phase 1 timer remains enabled and
  active; latest local backup service succeeded. Hardened Phase 2A manual service
  succeeded and the remote archive and JSON were both downloaded and hash verified.
- Production workflow API HTTP 200/status ok/version 1.7.0; PDF and Omada endpoints
  also passed after package restart. No application release or migration occurred.
- Implementation commits: `f7ad1c2`, `56112e8`; schedule cadence fix is `d1ceff7`.
  The final journal commit follows; recovery refs will point to that final SHA.

### Roadmap boundary

The checked-in authoritative master runbook prioritizes provider adapters but does
not define the numbered approved Phases 2B–12 or their gates. The architecture note
lists potential future adapters, not an approved phase plan. Do not infer or execute
provider mutations from that unordered list. Resume once the operator supplies the
approved remaining phase plan; no credentials or other artifacts are needed.


Latest scheduled-service manual generation details (20260927T025414Z):
- Encrypted SHA-256: `ab5deb2f200207ba412c4e739a32b9fd8ef3ac612e4529adc323f724eaff4a40`
- Source archive SHA-256: `f88d17767f26a2c89961e13752aa6cd7e81f2ef547d3a3257f98de4cccb4d997`
- Service result: success; fully downloaded object and sidecar hashes passed.
- Timer next scheduled run at first inspection: 2026-09-28 03:04:13 UTC; after
  the final unit reload its live next run is 2026-09-28 03:12:35 UTC.

### Schedule review: preserve Phase 1 retention cadence

Final review found the Phase 2A unit's `Requires=optibrain-backup.service` would
create a second local generation each day, shortening Phase 1's seven-generation
window. Keep ordering (`After=`) so concurrent runs serialize, but do not start a
second backup. Upload the newest independently scheduled Phase 1 generation and
fail closed when it is older than 36 hours or over five minutes in the future.
This preserves daily local cadence and catches missed backup runs. Existing
archives and retention settings are unchanged. Validate the age boundaries and
unit behavior before sustaining the timer.

### Intent: preserve seven-generation local window

Pre-mutation recovery: existing local archive `20260927T025414Z`, encrypted remote
copy, and ref `recovery/pre-phase2a-activation-d69e02b`. Deploy the tested 36-hour
freshness guard and remove the service's dependency that forced a second daily
local generation. Keep After ordering and the Phase 1 timer unchanged. Update the
root-owned runtime copy and installed unit, reload, verify unit/timer state, then
run one idempotent verification of the latest generation (remote objects already
exist; conflicts remain fail-closed). Existing archive count/retention is untouched.


### Completed: retention-safe schedule and fresh rerun

Removed the service's Phase 1 backup requirement while preserving `After=` ordering.
The uploader now refuses local generations older than 36 hours or more than five
minutes ahead of UTC. Nine uploader tests pass, including all three freshness
boundaries. Static and installed unit verification pass; the installed unit keeps
its empty capability set and strict filesystem protections. Phase 1 remains the
only daily local timer, preserving its seven-generation cadence.

Five local backup generations remain present; no existing backup was deleted.
After installing this exact runtime code, the manual hardened service succeeded
again at 2026-09-27 12:06:26 UTC. It validated existing generation `20260927T025414Z`
and streamed/hashed the existing remote archive and manifest. Audit shows no PUT;
no new local or remote generation was created. Both timers remain active. Current
production HTTP health remains good; no jobs remain in progress.


## Superseded boundary

The prior request for an approved Phase 2B–12 roadmap is resolved: the complete
approved roadmap was supplied on 2026-09-27. Resume at Phase 2B below.

## Approved roadmap resume — live baseline and Phase 2B intent (2026-09-27)

- Checkout HEAD `1bae01c`; pre-existing untracked diagnostic script preserved.
- Recovery branch `recovery/pre-phase2b-1bae01c` records the last-known-good code.
- Production workflow API, PDF and Omada endpoints returned HTTP 200; all three
  corresponding services are active. API version is 1.7.0.
- Phase 1 `optibrain-backup.timer` and Phase 2A `optibrain-phase2a-upload.timer`
  are enabled and active. Latest local archive `20260927T025414Z` passed sidecar
  checksum verification. Off-host encrypted generation remains verified by
  separate download/hash, human offline decrypt/hash, and isolated restore.
  Disk has 63 GiB free (14% used).
- `sudo -n true`, `visudo -c`, and `sudo -ll` succeeded. The legacy
  `/etc/sudoers.d/optibrain-overnight` grants `NOPASSWD: ALL`; the ordinary
  authenticated sudo-group rule and separate deploy rule also exist. Phase 2B
  will replace only that broad drop-in after the fixed helper and exact-path
  authorization have passed tests. Preserve base sudoers and deploy policy.
- Mutation intent: install a root-owned fixed-operation operator, add its exact
  path NOPASSWD rule, test routine operations and escape rejections, then remove
  only the old broad overnight rule. Audit entries must contain no secrets.
  Rollback is to restore the captured drop-in only if necessary, then immediately
  re-establish the fixed helper policy; never leave broad sudo as steady state.
- No Phase 2B sudo/service mutation has yet occurred. Next operation: implement
  the helper and adversarial tests, validate installed files and sudo syntax,
  then switch authorization and verify the old arbitrary sudo probe is denied.

### Phase 2B — constrained sudo policy active; post-change recovery verified

`/etc/sudoers.d/90-optibrain-admin` contains only the exact helper path and was
validated with `visudo -cf` before installation; `visudo -c` passed with both
rules present. The old broad file was moved out of sudoers.d into root-only
recovery storage, not deleted. Arbitrary `/usr/bin/id` and bare `sudo -n true`
are now denied; health/scheduler/service-status through the helper succeed.
Public health remains HTTP 200 for all three services, and both backup timers
remain enabled and active. This demonstrates the least-privilege boundary, while
several roadmap operations (reviewed unit installation, deployment/rollback,
permission repair, restore drills and bounded log access) still need assessment
or implementation; do not mark Phase 2B complete until these are addressed.

Post-change recovery intent: run the fixed helper's local backup operation, then
verify archive/checksum/SQLite integrity, then invoke its fixed off-host
verification operation for that unique generation. This creates no provider
credential or permission change and cannot overwrite a remote generation because
the uploader is create-only. If either step fails, preserve all old recovery
generations and diagnose before continuing. Record resulting generation, hashes,
service health and recovery refs immediately afterward.

Post-change recovery completed: helper backup created local generation
`20260927T130636Z`; checksum and full archive/SQLite verification passed. The
helper's off-host operation completed successfully, which runs the installed
Phase 2A uploader's full downloaded-object verification path. Its unique remote
generation was create-only; no previous R2 generation was replaced or removed.
The helper does not yet expose its protected state/hash metadata, so this record
does not invent an encrypted digest. Health endpoints remain HTTP 200; both
timers remain active/enabled; disk has 62 GiB free (14% used). Arbitrary sudo
remains denied after the off-host run.

Phase 2B foundation gate evidence: arbitrary root execution rejected; routine
health, scheduler, backup, archive verification, upload/remote verification,
capacity, service status and queue count work non-interactively. The broader
requested command catalog remains incomplete: reviewed unit deployment/update,
controlled application deployment/rollback, controlled permission repair,
isolated restore drills, and redacted OptiBrain log/audit inspection need a
reviewed extension. The current exact-path rule intentionally has no mechanism
for installing a new root-owned helper version from the optibrain-writable
checkout. Do not restore broad sudo to work around this. First design and
validate a root-trusted update path (e.g., separately reviewed, digest-pinned
package/update mechanism), preserving the exact allowlist boundary. Until then
Phase 2B is NOT COMPLETE and Phase 3 production implementation must not begin.

Recovery refs: pre-change `recovery/pre-phase2b-1bae01c`; current code checkpoint
is `recovery/post-phase2b-foundation-6cc37a9` (HEAD at this checkpoint).
The root-only copy of the old broad rule remains at
`/var/lib/optibrain/admin-recovery/optibrain-overnight.pre-phase2b`; it is recovery
evidence only and must never be restored as steady state.

### Current stop boundary and exact resume operation

The master runbook is root:root mode 0644. Updating it failed under the narrowed
sudo policy, and the installed admin helper has no reviewed-file installation or
root-owned documentation operation. Do not restore broad sudo. A trusted,
reviewed helper update/deployment path is required before adding more root-owned
operations. Exact next operation: install a root-owned, digest-verified helper
release/update mechanism with explicit allowlisted operations for reviewed unit
install/update, deploy/rollback integration, permission repair, isolated restore,
redacted logs/audit inspection, and approved root-owned runbook updates; validate
its escape boundary, then update the root-owned master runbook, complete Phase 2B
gates and only then proceed to Phase 3. Existing prod remains healthy and old
backups are preserved. The original broad-rule recovery file is offline from the
sudoers include path and must not be restored as the solution.

### Phase 2B implementation and pre-install review

A fixed Python operator has been implemented at `ops/admin/optibrain-admin.py`.
The initial command surface is health, scheduler/timer status, capacity, backup,
latest local archive/checksum verification, off-host service execution and
verification, read-only queue counts, and restart/status for exactly the three
OptiBrain-owned API services. It accepts no arbitrary paths, commands, or unit
names. Raw logs and credentials are never returned. Every non-help invocation
writes durable start/result audit entries. Escape tests reject shell execution,
path arguments, service injection, unrelated units and backup arguments.

Before installation, Phase 2A checksum/state evidence and production health were
revalidated as recorded above. No system configuration has changed yet. Next:
review implementation and test outcome; install root-owned helper; validate helper
operations with the still-authorized session; add exact-path sudo rule and verify
it; remove broad overnight rule; prove non-helper `sudo -n` is denied and fixed
commands still work. Then commit the completed policy switch and test results.

### Phase 2B helper live validation — before sudo authorization switch

Helper installed at `/usr/local/sbin/optibrain-admin`, root:root 0750. Its
SHA-256 exactly matches reviewed source commit `1083218`:
`a35734a52d9c64adfc0bb9b242f117aad099c85d5cbc0aac248e422ebe25367c`.
Root-only audit directory is `/var/log/optibrain`; original broad sudoers file
is preserved root:root 0600 at `/var/lib/optibrain/admin-recovery/optibrain-overnight.pre-phase2b`.

Live helper checks passed: public health endpoints (3 x HTTP 200), both timer
states, disk capacity, read-only automation-run counts (109 completed), latest
local checksum plus full archive verification, and API service status. The
shell-injection-shaped operation was rejected (exit 2); its args were not logged.
No service was restarted, no new backup was created, and no R2 operation occurred.
Intent immediately before sudo-policy switch: install an exact-path NOPASSWD
rule for this helper, verify syntax and access, then move the broad overnight
file out of sudoers.d and prove arbitrary non-helper root execution is denied.

Local post-policy-change recovery point completed through the constrained helper:
generation `20260927T130636Z`, checksum sidecar and full archive/SQLite verification
passed. Original five prior generations remain. No retention deletion occurred.
Next atomic operation is one Phase 2A uploader run for this new unique generation;
conditional create prevents replacement, and the uploader will GET/hash both
objects. This is the approved backup operation, not a repeat of an existing
provider mutation. If conflict or verification failure occurs, stop without
changing existing objects.

### Read-only Phase 3/4 inventory while privileged updates are unavailable

Live state was rechecked: production health endpoints return HTTP 200, both
backup timers remain active/enabled, the admin queue-count reports 109 completed
runs, and arbitrary root commands remain denied. `sudo -n -l` shows the ordinary
authenticated all-command rule plus NOPASSWD for only `/usr/local/sbin/optibrain-admin`;
the separate API deploy wrapper is installed for a different identity and is not
an admin-helper update channel. No existing authorized root update route was
found.

Phase 3 evidence from `workflow/automation/store.py`, `engine.py`, models and
`tests/test_automation_kernel.py`: SQLite WAL persistence exists for events,
workflow definitions, runs, step attempts and audit. Event ID and optional
idempotency key are unique; correlation, causation and depth are retained. Run
and step statuses and bounded per-step attempts exist. Six kernel tests pass.
Gaps: ingest commits/deduplicates the event before independently creating runs,
so a process crash between those operations can permanently suppress work;
execution is synchronous in the API process; run/step transitions are not a
claim/lease protocol; a crash can strand `running`; there is no stale recovery,
core-engine DLQ/replay, execution timeout, retry classification or jitter.
Retries catch all exceptions and use fixed `backoff_seconds` (maximum five
attempts, maximum 30 seconds). Existing Cloudflare Queues/Workflows provide
durable delivery, exponential delivery retries and a DLQ for the control-plane
boundary, but do not repair the core SQLite crash gap. Do not replace this with a
second queue until Phase 2B closes and the transaction/recovery design is tested.

Phase 4 scheduling inventory found daily Phase 1 local backup and Phase 2A
off-host systemd timers; GitHub scheduled workflows for lifecycle dispatch,
mailbox polling, owner digest and production monitoring; and a Cloudflare Worker
15-minute cron that enqueues mailbox, Sign, finance and digest events. The GitHub
schedule dispatcher and Worker cron both run every 15 minutes and can request
overlapping lifecycle work. Mailbox polling and daily digest also have separate
GitHub workflows. Event keys differ across those paths, so event-level
idempotency alone does not prove cross-scheduler deduplication. No scheduler was
disabled or modified; Phase 4 must assign ownership and migrate/verify before
removing any trigger.

Validation in this inventory: `apps/workflow-api/.venv/bin/python -m unittest
tests.test_automation_kernel -v` passed 6/6. Control-plane worker dependencies
are not installed in this checkout, so no worker dry-run was attempted. This is
read-only inventory, not completion of Phases 3 or 4.
