# OptiBrain autonomous resume journal

Roadmap version: OPTIBRAIN AUTONOMOUS OVERNIGHT PROGRAM, 2026-09-27, Phases 2A–12.
Current phase: 2A. Current subphase: offline recovery validation.
Status: HUMAN_ACTION_REQUIRED for the offline AGE decryption/restore drill.
Temporary sudo works. Read the newest overnight sections below; the original
checkpoint record is retained as history, not current live state.

- Running production baseline / last known good SHA: `936e75a` (Phase 1).
  Working checkout: `hardening/phase2a-resume`; resolve its checkpoint SHA with
  `git rev-parse HEAD`. No service restart/deployment accompanied this commit.
- Latest verified-phase recovery reference: `heads/recovery/post-phase1-936e75a`.
  Parser-only checkpoint baseline: `recovery/pre-phase2a-parser-936e75a`.
- Local backup: last documented verified archive is
  `/var/backups/optibrain/optibrain-backup-20260926T232858Z.tar.gz`.
  This session cannot independently verify it: directory is root-only and
  `sudo -n true` reports a password is required.
- Off-host backup: none verified; remote bucket existence and credential presence
  remain unknown to this session.
- Production health: local HTTP 200, status=ok, version=1.7.0; workflow service
  active. Backup timer enabled/active; last backup service result=success,
  exit=0 at 2026-09-26 23:29:59 UTC. Off-host timer not installed.
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

## Exact next safe operation

Local parser repair is checkpointed on `hardening/phase2a-resume`; it is not a
completed phase or deployment. Once privileged execution is available, verify
the current local archive and production, create
the pre-phase recovery reference, and run authenticated read-only bucket and
privacy discovery. Inspect credential presence without printing values. Record
durable intent before any provider mutation and result immediately afterward.
Do not enable uploader timer until dedicated bucket scope, encryption, upload,
download/hash verification, and safe retention are proven.

## Human boundary

This shell runs as `optibrain` (uid 1001), with no noninteractive sudo access.
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

## Current handoff — authoritative next operation

Status: HUMAN_ACTION_REQUIRED only for the offline AGE recovery drill. Phase 2A
is not declared complete. Root access and credential provisioning are resolved.

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
`backups/2026/09/27/20260927T021414Z.tar.gz.age`

- Ciphertext SHA-256: `4e75906e0791d192ab296eea1f1a8e814c59fe7c081cf488c1341ed7a2cb89ed`
- Plaintext archive SHA-256: `c802d153a261e28f86440c718cddd06dfc1b7f19e157d72c058c7eaaede16792`
- Remote verification completed: 2026-09-27T02:16:26Z.
- Final public workflow/PDF/Omada responses successful; backup service result
  success, exit 0; local backup timer active. No atomic operation remains running.
