# Opticable automation master runbook

AUTHORITATIVE CURRENT. API `1.12.0`. This is the operating contract; [onboarding](OPTIBRAIN_CODEX_ONBOARDING.md) establishes precedence. [Operator](OPTIBRAIN_OPERATOR_GUIDE.md), [deployment](OPTIBRAIN_DEPLOYMENT_GUIDE.md) and [recovery](OPTIBRAIN_RECOVERY_GUIDE.md) are the only current procedures for those tasks. Historical phase instructions cannot override them.

## Standing safety state

123 protected records READ ONLY; protected mutations/customer sends/Books writes 0. Real and TEST automatic business writes OFF. `REAL_CANARY_ALLOWED=false`. Persistent development worker OFF; six retired units masked/inactive. Native French/English Forms CRM integrations DISABLED under owner-admin confirmation; supported APIs cannot read that native setting. Fallback enrichment OFF. Connector/Omada/PDF/WorkDrive/legacy Mail/Sign contained; Books write transport denied. Root kill, fail-closed auth, exact ownership, immutable execution evidence, state-loss/stale-journal reconciliation and independent off-host claims are mandatory.

The current manual mission defines engineering scope. Workflow enabled state, an old approval, a successful API response or credential scope never grants provider-write authority. No current document authorizes a real canary or customer action. [Safety controls](OPTIBRAIN-SAFETY-INVARIANTS.md) apply to every host.

## Inspect and operate

Owner home: **https://optibrain.opticable.ca/v1/operator/today**. Use the owner’s Access login. Business cards lead into sales/follow-ups/quote review/projects/maintenance/approvals/exceptions. Technical health is `/v1/operator/system-health`. Private/no-store responses and source timestamps remain mandatory.

```bash
curl -fsS http://127.0.0.1:8100/v1/system/health
sudo optibrain-admin scheduler  # backup/upload pair only
sudo systemctl list-timers --all optibrain-backup.timer optibrain-phase2a-upload.timer opticable-phase9-intake-receipts.timer opticable-phase10-service-events.timer opticable-phase12-test-runner.timer --no-pager
sudo optibrain-admin capacity
sudo optibrain-admin verify-latest
sudo cat /run/optibrain-readiness/status.json
sudo cat /run/optibrain-readiness/queue-depth.json
sudo cat /var/lib/optibrain/releases/current.json
sudo cat /etc/optibrain/mutation-control.json
```

[Runtime](OPTIBRAIN_RUNTIME_CONTRACT.md) lists services/timers, locks and ports. [State](OPTIBRAIN_STATE_CONTRACT.md) lists five active DBs, three archives and root registries. The root read-only inspector in onboarding privately authenticates readiness and independently compares protected record versions; it logs no credential/customer values.

API liveness, business attention, provider reads, backup freshness, auth/safety and infrastructure are separate readiness dimensions. Missing samples remain UNKNOWN. The GET-only queue sampler observes active/dead-letter backlog without consuming messages. Dead-letter backlog requires engineering reconciliation; **never replay/purge it to make health green**. Diagnostic log rotation does not prune business evidence.

## Changes and incidents

Use one focused validation path; full fake-provider regression once at the final executable release candidate, then exact-head PR/main CI. Deploy through the installed root-owned guarded gate only. The deployment guide specifies authorization receipt, immutable dependencies, rollback backup and independent post-release checks. Root-approved runbook digest repinning must preserve the previous digest; changing prose does not silently repin installed trust.

For process failure restart only the affected contained service after checking state. For code regression roll back code/config/venv, preserving journals and credential rotations. For state loss/full host loss follow recovery; never restore old journals into an active writer or restore a VM snapshot as an ordinary deploy rollback.

Provider reconnect starts with read observations, token binding, saved cursors, native notification verification and immutable effect evidence. Distinguish 401 from 403/throttle/outage; do not replace a token or move a cursor just to clear a status. Native-channel renewal and credential rotation need their own exact incident scope. No automatic failover enables the connector’s writers.

## Backup stewardship

Local `/var/backups/optibrain` contains online SQLite/state/config/source archives. `/var/lib/optibrain/phase2a` records public-recipient encryption, create-only R2 upload and independently downloaded byte hashes. Preserve every golden/recovery/audit hold and locked `business-effects/v1/` claim. Root retention tooling is dry-run first, local only: seven newest plaintext generations plus holds; two recent verified ciphertexts plus owner/golden holds. Failed/ambiguous uploads are retained. No R2 deletion is authorized. See recovery for exact golden references and offline AGE custody.
