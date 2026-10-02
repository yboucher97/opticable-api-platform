# Phase 14 recovery procedure and evidence limits

Use the current master runbook, release receipt, state contracts and root backup policies. These procedures improve readiness; they do not constitute a new live recovery proof.

## Provider reconnect

First read current credential binding, cache ownership/mode, saved checkpoint, independent provider health and latest immutable intent/ack/readback. Distinguish specific 401 from forbidden scope 403, throttling and network failures. Reconcile a newer shared token before invalidating only a rejected token. Probe the exact saved cursor with GET-only provider access; never move it forward merely to remove a failed status. For native watch, compare token/destination/events/options and normalized exact expiry; adopt verified provider truth locally only when all other fields match and no unresolved intent exists. Rotation/new credentials/channel renewal are separate explicitly authorized actions, not status cosmetics.

If credentials truly need replacement, use the owner-approved OAuth/account setup on a trusted session, retain the previous binding only as protected evidence, verify minimum required scopes through reads, quarantine old write/approval authority and resume only read observation at its saved cursor. Never log refresh/access tokens. Connector/core OAuth domains are separate; reconnection must not reactivate contained business writers or native Forms integration.

## New-OS rebuild

1. Record incident start, current source SHA, release/rollback receipts, root safety policies and off-host locked claim namespace. Freeze writers and preserve current journals; do not replay old state.
2. On an isolated replacement, create least-privilege API/PDF/Omada/proxy identities and root-owned deployment/helper paths. Apply firewall/loopback/systemd containment. Keep all six development units masked and persistent authorization absent before boot.
3. Obtain the exact independently verified R2 ciphertext and manifest. Verify ciphertext SHA against independent readback/owner evidence. Owner decrypts with offline AGE identity; identity never reaches the VPS/chat. Verify plaintext SHA and archive readability in the owner's trusted boundary.
4. Restore to isolated staging with traversal/link/member/schema checks. Online-restore all five active and three historical DBs, protected baselines/registries/crosswalks/claims/config/source. Check every SQLite integrity result and preserve ownership/modes. Expire old execution/canary/approval authority; no restored timestamp grants a new effect.
5. Provision the exact source and immutable dependencies as root-reviewed data. Existing frozen `requirements.txt` permits validated dependency reuse; changed requirements need a new isolated tested environment. Do not run retired `install.sh` or Phase 6 loaders. Install the canonical reviewed root gate and current sandbox units/helpers.
6. Boot isolated contained services. Verify fail-closed auth, root kill, no real/Test write family, protected IDs, state-loss/off-host duplicate fences, local health/readiness and backup. Provider reconnect uses reads first. Verify native Forms remain owner-disabled separately; supported API does not expose that native setting.
7. Cut over only under an explicit incident/manual scope after reviewable evidence. Keep old host read-only for rollback and avoid two schedulers or effect executors. No background writer is enabled to test liveness.

## DNS/TLS cutover and rollback

Record existing DNS/TLS/Access application/origin policies and TTLs through read-only API/state inspection. Prepare exact target IP/origin, issuer/audience/allowlist and Caddy config; validate syntax before reload. Confirm isolated HTTP/TLS and authenticated owner routing without public writer reachability. Lower TTL only if justified by the authorized cutover scope. Perform the single reviewed record/origin change, verify propagation, certificate chain, Access denial for unauthenticated requests and authenticated source identity. Revert exact DNS/origin config on regression; keep journals/claims intact. A successful local restore is not DNS/TLS failover proof.

## RTO measurement

Use UTC timestamps for incident_start, replacement_ready, verified_restore, contained_boot, provider_reads_ready, dns_cutover_start, authenticated_owner_ready and rollback_complete if applicable. Report elapsed wall time and blocked/owner-key/provider/DNS intervals separately. Store exact source/archive hashes, test receipts, safety state and limitations. `ops/phase14/recovery_timeline.py` validates and calculates supplied milestones; it does not fabricate a drill or restart services. Guaranteed RTO is not claimed.

Proven from Phase 13: immutable encrypted upload and downloaded-byte hashes, owner offline decryption/plaintext hash/archive readability, isolated eight-DB/config/source/mask restore and restored app boot. NOT FULLY PROVEN: complete replacement production OS, every live provider reconnect, DNS/TLS cutover and guaranteed RTO. Phase 14 did not rerun the completed recovery drill or move the AGE identity online.
