# OptiBrain owner/operator guide

AUTHORITATIVE CURRENT. Begin at [Today](https://optibrain.opticable.ca/v1/operator/today) using your normal owner login. OptiBrain currently observes and organizes work; real automatic writes and customer sends are OFF.

## Daily workflow — OWNER SAFE

Review sales attention and due follow-ups first, then quote-ready items, projects/install work, maintenance/renewals and approvals/exceptions. Each card explains the reason, next action and dated source; open its detail link before acting. Confirm facts in CRM and use your normal business tools for any manual customer action. Today does not send messages or execute cards automatically. TEST_ONLY and historical evidence are separated from real current attention.

Approvals are exact, scoped records, not a general automation switch. An approval can remain visible while transport is disabled. Inspect an exception’s evidence and ownership before requesting a retry. Do not approve, replay or recreate an action merely because a prior response is missing. A provider action may already have happened.

## Interpret health

| State | Meaning and owner response |
|---|---|
| OK | That specific check passed recently. It does not prove every provider or workflow is ready. |
| DEGRADED | Safe service may continue; a stale read, capacity warning or bounded observation needs review. Check freshness and ask an engineer if persistent. |
| ACTION REQUIRED | A failed/stalled checkpoint, dead-letter delivery, backup or safety check needs investigation. Stop consequential work until its evidence is reconciled. |
| UNKNOWN | Evidence is absent/stale or the provider cannot expose it. Treat it as unverified; do not assume success or enable a writer. |

The former soft log-growth warning counted system-journal retention as application growth. Application diagnostic logs now rotate at 5 MiB × 5 files; journald is capped at 512 MiB/90 days. Separate thresholds and free-disk checks bound risk. Immutable action/receipt/claim evidence is retained separately.

Remote queue depth is now read from Cloudflare’s approximate GET metrics. The first observation found active backlog 0 and dead-letter backlog 129. Those retained failures require engineering inspection before replay; Phase 15 did not consume, purge or replay them. Queue count alone does not identify when or why each delivery failed.

## Emergency checks — OWNER SAFE with shell access

```bash
sudo cat /etc/optibrain/mutation-control.json
sudo cat /var/lib/optibrain/releases/current.json
curl -fsS http://127.0.0.1:8100/v1/system/health
sudo optibrain-admin scheduler  # backup/upload pair only
sudo systemctl list-timers --all optibrain-backup.timer optibrain-phase2a-upload.timer opticable-phase9-intake-receipts.timer opticable-phase10-service-events.timer opticable-phase12-test-runner.timer --no-pager
sudo optibrain-admin verify-latest
sudo cat /var/lib/optibrain/phase2a/state.json
sudo cat /run/optibrain-readiness/status.json
sudo cat /run/optibrain-readiness/queue-depth.json
```

The policy must show `test_writes_enabled:false` and `real_canary_allowed:false`; the receipt must show automatic writers and development worker false. The receipt is deployment evidence: the authenticated inspector in onboarding checks live process/policy state. `state.json` must show `download_hash_verified`, a recent `verified_at` and no newer upload failure; this is stronger than “upload succeeded.” Local verify checks the archive and DBs. Open Today → system health/exceptions to inspect attention.

Emergency stop of application automation, retaining backup/upload:

```bash
sudo systemctl stop opticable-phase9-intake-receipts.timer opticable-phase10-service-events.timer opticable-phase12-test-runner.timer
sudo systemctl stop opticable-phase9-intake-receipts.service opticable-phase10-service-events.service opticable-phase12-test-runner.service opticable-workflow-api.service
```

This stops host intake/reconciliation and the API’s internal workers; Today will be unavailable. Edge delivery can accumulate errors while the API is down. Leave backup/upload timers running. Do not restart schedulers or replay messages until engineering checks state and provider evidence. Stopping a timer alone does not stop an already running job. Never delete DBs or queue messages as first-line recovery.

## Responsibility boundaries

| Role | Actions |
|---|---|
| OWNER SAFE | Read Today, CRM facts, health, release/backup receipts; invoke the emergency stop above. |
| ENGINEER / CODEX | Diagnose logs/auth/state, verify DBs/versions, reviewed deploy/code rollback, isolated rebuild and reconciliation within the manual mission. |
| PROVIDER ADMIN | Account login/MFA, minimum-scope secret rotation, owner-only Forms settings, DNS/Access and OVH account/billing actions. |
| RECOVERY-ONLY | Offline AGE decryption, restore staging, replacement-host cutover or explicitly authorized VM snapshot restore. |

Production VPS is `vps-214ba8cd.vps.ovh.ca`, OVH Canada (`ovh-ca`), service `41299869`, `os-bhs6`. Confirm the name/service in OVH Manager before any incident action. The owner-confirmed snapshot `OPTIBRAIN-GOLDEN-PHASE14-PRE-PHASE15-20261002` is fast whole-VM rollback insurance. Use it only for an authorized host incident after writers can be kept OFF; its old journals may lag provider effects. A clean rebuild is safer after compromise or uncertainty about the old OS. Do not overwrite production or reinstall it as a health check. Follow [recovery](OPTIBRAIN_RECOVERY_GUIDE.md).
