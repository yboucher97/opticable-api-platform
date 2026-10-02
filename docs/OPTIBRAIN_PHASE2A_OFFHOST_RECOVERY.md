> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# Phase 2A encrypted off-host recovery

## Current Phase 13 owner-key recovery proof

**MANUAL-02 CLOSED — PASS; owner-held AGE identity decryption PROVEN.** Exact generation `20261001T202728Z`; ciphertext SHA-256 `801cf07d3b16930e676d39c8640defb856a25bd03debeb881afa2719baa5148f`; public recipient SHA-256 `d3593cf7f443701fe9d863b6fa2b7ba7ff17ed216f6a6f463e1333589cd8a96f`; plaintext SHA-256 `9b37c94a4cb5be5f2bac6907bfcf17754e6fda10f5a464b1360f6b72c7a4be84`. Owner used the existing identity on the trusted Windows recovery computer; AGE exit0 and `tar -tzf` exit0. No private identity was copied to VPS/GitHub/Cloudflare/Codex/ChatGPT or rotated/replaced/regenerated.

Fresh exact off-host streamed GET/hash plus retained root manifest/ciphertext/plaintext/configured public fingerprint independently match these values. Ciphertext integrity, owner-key decryption, plaintext integrity and archive readability PROVEN. Isolated server-side restore and restored actual-service-user API boot PROVEN from existing Phase13 remediation/P1 evidence (eight DBs, six masks, fresh dependencies, no provider network). Full replacement production host/OS NOT FULLY PROVEN; DNS/TLS disaster cutover NOT PROVEN; guaranteed RTO NOT CLAIMED. Provider reconnect/live failover remain future maturity work. See [final closure and evidence limits](phase13-final-closure.md). Historical sections below retain earlier-generation provenance.


Status (2026-09-27): human offline decryption/hash and isolated staging restore
passed. Hardened manual upload passed. `optibrain-phase2a-upload.timer` is installed,
enabled and active; Phase 1 local timer remains enabled and active. See the progress
journal for live generation and service verification.

## Implementation and recovery custody

- Private R2 bucket: `optibrain-recovery-prod`; authenticated discovery found
  r2.dev disabled and zero custom domains. No public access was configured.
- `/etc/optibrain/age-recipient`: public recipient only. The matching private AGE
  identity must remain offline with the human, never on this VPS or in Git.
- `/etc/optibrain/r2-uploader.env`: root:root 0600 AWS shared-credential format.
  Account token `optibrain-recovery-uploader` has exactly one policy:
  Workers R2 Storage Bucket Item Write on this bucket in default jurisdiction.
  Target list passed; an unrelated bucket list was denied HTTP 403.
- Bootstrap token `/etc/optibrain/cloudflare-test-token` is used only for discovery
  and provisioning. The routine uploader reads only its dedicated credentials.
- `/etc/optibrain/phase2a.conf`: root-owned non-secret account ID configuration.
- Ubuntu `age` and `/usr/bin/python3` with packaged `python3-boto3` are required.
  AWS CLI is not used (no candidate in the configured Ubuntu repositories).

`ops/backup/optibrain-r2-credential.py` creates a dedicated credential once, only
following recorded intent and verified recovery. It refuses an existing local
credential or same-name provider token. Ambiguous POST outcomes require read-only
reconciliation, never blind retries or automatic rotation. A protected bootstrap
response is retained if processing fails and removed after successful storage.
Cloudflare supports API creation and S3-key derivation; the former dashboard-only
claim was incorrect. Reference: https://developers.cloudflare.com/r2/api/tokens/

## Upload transaction

Run `sudo bash ops/backup/optibrain-phase2a-upload.sh` for a manual drill. The
uploader verifies the newest local generation's checksum and manifest/SQLite
integrity, encrypts using AGE, and retains the exact ciphertext across retries.
A durable preparation checkpoint precedes remote writes. Concurrent invocations
are locked out. Conditional PUT (`If-None-Match: *`) prevents replacement; only
HTTP 404 means absent. All other read failures stop writes. Existing ciphertext
must match its hash and length. GET streams all remote bytes for SHA-256 checking,
then repeats verification for the JSON sidecar before marking success.

Objects: `backups/YYYY/MM/DD/YYYYMMDDTHHMMSSZ.tar.gz.age` and matching `.json`.
Root-only state, audit log, and per-generation spool live under
`/var/lib/optibrain/phase2a/`. `state.json` records the last verified generation;
`last-failure.json`, when present, records the latest failure (it may predate a
later success; compare timestamps). `audit.jsonl` records durable intent/outcome.
A network crash after PUT can be retried using the preserved ciphertext. If spool
and remote differ, stop and investigate; do not overwrite or delete either copy.

SDK retries use standard exponential backoff with four total attempts and bounded
network timeouts. The wrapper has a 45-minute overall timeout. Archives above
4 GiB are rejected before encryption/upload; multipart support is not implemented.
No remote retention or local spool deletion is automated. Monitor disk and R2
usage before long-running scheduling. The object-write token is not an immutable
vault against a compromised uploader; separate immutable custody is still needed.

## Human offline recovery drill — completed gate

1. Obtain the latest verified encrypted object and matching JSON manifest using
   authorized R2 access on a separate trusted recovery machine. Use the exact
   object key and hashes recorded in the progress journal/root-only state.
2. Verify downloaded ciphertext SHA-256 against `encrypted_sha256` in the
   manifest and separately recorded verification evidence.
3. On that separate machine only, decrypt with the offline human-held identity:
   `age --decrypt --identity /offline/path/identity.txt --output recovery.tar.gz downloaded.tar.gz.age`.
4. Verify `recovery.tar.gz` SHA-256 equals `source_sha256` in the manifest.
   Run `optibrain-backup.sh --verify recovery.tar.gz` on an isolated Linux recovery
   machine with the Phase 1 verifier's dependencies. Preserve root-only modes.
5. Extract only into isolated staging. Validate SQLite, source, service config,
   ownership metadata and necessary provider state using the Phase 1 restore
   procedure. Do not start services that send production events during the drill.
6. Record only date, generation, checksum/integrity result, and recovery findings.
   Never send the identity, plaintext archive, or secret contents to Codex/chat.

This evidence was recorded. Unit validation, runtime deployment, successful
manual service execution and timer activation are complete. Local Phase 1 backup
scheduling remains enabled. Phase 2A recovery is validated at archive/decryption
level; a booted replacement host, provider failover and immutable vault have not
been tested. No remote retention deletion is configured.

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

## Isolated archive validation completed — 2026-09-27

`ops/backup/optibrain-restore-drill.py` validated the exact local plaintext archive
whose SHA-256 matched the human's independently decrypted copy. It ran under a
transient systemd unit with `PrivateNetwork=yes`, `ProtectSystem=strict`, private
tmp, and only `/var/lib/optibrain` writable. Result: PASS (636 file checks, 675
metadata entries, restored SQLite integrity, extracted versioned source, and
three critical config uid/gid/mode/content restores). Credential-bearing staging
was removed after validation; only a non-secret report remains.

The drill identified two legacy v1.0.0 inventory defects: four Chromium dependency
manifests lack individual manifest hashes (covered by whole-archive SHA-256), and
two intentionally excluded SQLite WAL/SHM files remained listed in metadata.
Phase 1 v1.0.1 corrects both for future generations; no old archive was modified.
The validator recognizes and counts only these exact legacy omissions.

Combined human offline decrypt/hash evidence and isolated archive restore checks
satisfy the Phase 2A recovery gate. This does not establish a booted replacement
host, provider failover, or an immutable off-host vault. Per-generation remote
manifests remain immutable and their automatic `offline_restore_verified=false`
field is not rewritten; the human evidence and isolated report are separate.

The most recent manual hardened service run (generation `20260927T025414Z`)
completed successfully. Its encrypted object hash is
`ab5deb2f200207ba412c4e739a32b9fd8ef3ac612e4529adc323f724eaff4a40`; local
source archive hash is `f88d17767f26a2c89961e13752aa6cd7e81f2ef547d3a3257f98de4cccb4d997`.
Both object and JSON sidecar were downloaded and hash-checked. The daily service
timer is now enabled and active; Phase 1's timer is still enabled and active.


The Phase 2A timer no longer forces a duplicate local backup. `After=` preserves
ordering with an in-progress Phase 1 run; the uploader selects the newest daily
local generation and stops if it is older than 36 hours or more than five minutes
in the future. This preserves Phase 1's seven-generation retention cadence while
surfacing missed local backup runs. The updated service passed a second manual run
and verified existing remote bytes without another PUT.
