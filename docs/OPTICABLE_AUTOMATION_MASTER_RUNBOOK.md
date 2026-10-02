# Opticable Automation Master Runbook

Current operating contract for Phase 14, API 1.12.0. Last updated 2026-10-02 America/Toronto. Read [Codex onboarding](OPTIBRAIN_CODEX_ONBOARDING.md) for orientation and [the documentation index](README.md) for historical/audit references. The previous runbook is preserved byte-for-byte in [Phase 13 history](history/phase13-OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md).

## Authority and non-negotiable state

The current user mission defines engineering authority. Root-private live policy and independently checked receipts define operational state. A branch, old phase guide, enabled workflow or issued approval is never business-write authority.

Protected baseline: 123 records, unchanged. Protected mutations/customer sends/Books writes: 0. Real automatic writes OFF; TEST automatic writes OFF; REAL_CANARY_ALLOWED FALSE. Native Forms CRM Add/Update/Upsert DISABLED under the Phase 13 owner-UI closure; fallback enrichment OFF. Connector, Omada, PDF/WorkDrive, legacy Mail/Sign remain contained. Books POST/PUT/PATCH/DELETE denied. Auth fail-closed; universal kill, immutable journal and off-host duplicate protection mandatory. Owner AGE identity remains offline. Persistent Codex development worker OFF; six retired units MASKED/INACTIVE. Manual Codex sudo/root preserved.

Forbidden: protected data changes/deletes, Lead conversion, customer email/SMS/calls, invoices/payments/credits/Books changes, broad real business automation, real canary or retired development worker activation. A future limited canary needs a new manually initiated mission; never begin it from a recommendation.

## Canonical services and daily owner view

[Runtime matrix](phase14-runtime-matrix.md) defines three app services, Caddy, five timers and external schedules. [State matrix](phase14-state-store-matrix.md) defines five active DBs, three archived historical stores and root registries/claims. Owner Today: `https://approvals.opticable.ca/v1/operator/today`. It contains read-only attention, dated sources and links into existing views. Test/historical/resolved action evidence is separated from REAL CURRENT urgency. Technical status is `/v1/operator/system-health`; do not put OAuth or scheduler internals into business cards.

```bash
curl -fsS http://127.0.0.1:8100/v1/system/health
sudo optibrain-admin scheduler
sudo optibrain-admin capacity
sudo optibrain-admin verify-latest
sudo cat /run/optibrain-readiness/status.json
sudo cat /var/lib/optibrain/releases/current.json
```

The authenticated `/v1/system/readiness` endpoint is provider-free. It exposes API/auth, provider read observations, delta, native watch, queue/exceptions, timers, backups, off-host proof, disk/DB/log growth, safety and deployment. UNKNOWN is not a fabricated green result. Remote queue depth is presently unmeasured. Alert on ACTION REQUIRED; repeated budget or capacity excess is WARNING, single rollout/unknown facts are INFO. Existing GitHub health incidents are updated only when their failure set changes.

## Provider reconciliation

Inspect current credential binding, successful reads, saved cursors and immutable evidence before rotation. Never print environments or credentials. Root-owned installed `phase14` tooling supports a probe and an explicitly committed local observer reconciliation. Leads previously stayed failed after an auth error because failed checkpoints do not auto-resume. Phase 14 proved the same cursor readable, cleared that one failed revision without moving the cursor and allowed the read worker to resume. No provider mutation was used.

The native watch's requested local expiry differed from readback by one hour; rotation readback had omitted exact expiry verification. Existing token/destination/events matched. Phase 14 adopted the provider's exact UTC expiry locally and appended new verification evidence. The provider-side normalization mechanism and original expired/revoked-token cause are not proven. No new credential/channel or rotation was needed. Watch renewal is not authorized by a green status or this procedure.

## Backup and retention

Online backup snapshots all five active and three historical DBs plus current root configuration/source/masks. Backup remains root-required and uses a destination lock. The uploader uses AGE's public recipient, immutable create-only R2 objects and full downloaded-byte hash verification. Owner-held private identity stays offline. Owner proof generation `20261001T202728Z` is held indefinitely.

Use [retention policy](phase14-retention-policy.md). The installed local tool defaults to dry run; it keeps all exact recovery/audit holds, seven newest plaintext generations, two recent verified ciphertext generations and the owner ciphertext. Failed/uncertain upload state never becomes disposable. No R2 deletion is implemented. Verify the concrete deterministic report and dependencies before `--execute`; execution replans/hashes every candidate under the uploader lock. Do not automatically prune immutable receipts/actions/provider reconciliation evidence.

```bash
sudo python3 /usr/local/lib/optibrain/phase14-retention.py --output /var/lib/optibrain/phase14/retention/dry-run.json
# After inspecting that exact report and confirming its recovery/hold evidence:
sudo python3 /usr/local/lib/optibrain/phase14-retention.py --execute /var/lib/optibrain/phase14/retention/dry-run.json --output /var/lib/optibrain/phase14/retention/execution.json
```

## Release and rollback

[Deployment README](../deploy/README.md) is the sole application release procedure. Validate focused changes, then one complete local release regression and exact-head CI. Merge only validated work. Root-review an exact-SHA authorization with tests/CI/verified rollback archive and immutable dependency environment. The installed `/usr/local/sbin/opticable-api-deploy-root SHA` is canonical. No checkout install script is release authority. A new-OS rebuild uses [recovery](phase14-recovery-runbook.md); old installers deliberately refuse execution.

The gate pins candidate source/version with all execution pins cleared, restarts only the API, checks service/timer/DB health and closed safety, and writes schema-1 receipts under `/var/lib/optibrain/releases`. The compatibility pointer `/var/lib/optibrain/phase13-remediation/deployment.json` uses the same format. On failure it restores previous code/environment/registration/venv, retains journals and emits rollback evidence. Do not restore old databases as an ordinary code rollback. Native-watch verification and failed-delta reconciliation require separate read-only inspection after restart.

Root authorization for this runbook's digest comes from the manually initiated Phase 14 mission. Preserve the previous root digest and source before explicit repinning; do not silently repin on routine document edits. Never update admin/helper policy or owner recovery material from an unreviewed mutable checkout.

## Recovery evidence limits

[Phase 13 closure](phase13-final-closure.md) proves owner offline decryption/hash/archive readability and prior isolated source/config/eight-DB/mask/application restore. Full replacement OS, live provider reconnect, DNS/TLS cutover and guaranteed RTO remain unproven. Phase 14 improves procedures/tooling without claiming another recovery drill. Recovery always starts with writers OFF, dev units masked, preserved claims/journals and expired old execution/approval authority.

Owner entry: https://optibrain.opticable.ca/v1/operator/today. The existing Cloudflare Access app now protects the operator prefix on this proxied hostname with its unchanged audience, owner/service policies and IdPs; API owner JWT/allowlist checks remain independent. The origin IP and zone TLS setting are unchanged. Source/Access/DNS routing receipts are retained in private Phase14 evidence. Approval POST origin remains its historical root constraint; this read-only home does not extend mutation authority.
