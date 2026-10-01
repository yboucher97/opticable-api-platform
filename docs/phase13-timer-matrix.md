# Phase 13 authoritative timer matrix

Current state 2026-10-01, America/Toronto. Five legitimate OptiBrain application timers remain ACTIVE. Six persistent Codex development units remain MASKED/inactive. Recovered execution queues were never resumed. Last execution timestamps/results are independently captured in the final mission receipt; this table is the configuration contract.

| Timer /scheduler | Purpose /cadence | User /reads /providers | Writes /authority | Lock /timeout | Failure /retry |
|---|---|---|---|---|---|
|optibrain-backup.timer|Local backup; daily02:30UTC +≤15m; persistent (EDT22:30/EST21:30 previous day)|root; source/config/root+application state, online8SQLite snapshots|Local private archive/hash only; no business provider mutation|systemd unit serialization; no shared CLI flock; unit timeoutinfinity|set-Eeuo-pipefail; integrity failure aborts; next generation retry. Fresh remediation backup/drill succeeded|
|optibrain-phase2a-upload.timer|Encrypted off-host backup; daily03:00UTC +≤15m; persistent|root; verified generation, offline public recipient, private R2 credential|Encrypted R2 object/cache/state only|Root flock; wrapper45m/unit46m|36h freshness bound; resumable upload/readback/hash; failure state/journal then bounded next-run retry|
|opticable-phase9-intake-receipts.timer|Boot+2m then every5m, accuracy30s|API UID; connector KV, Mail seven-day notifications and CRM matching|Local immutable receipts/matching/OAuthcache; provider enrichmentOFF/forbidden|systemd serialization; SQLitetransactions; no shared CLI flock; timeoutinfinity|Incomplete reads fail; replay dedupe, no repeated uncertain CRM effect; fresh completed run reports enrichmentnull|
|opticable-phase10-service-events.timer|Boot+10m then every30m, accuracy1m|API UID; CRM Accounts/Contacts/Deals/Services/Service_Locations|Local Test service projection/events/OAuthcache; no CRM mutations|systemd serialization/SQLite; timeoutinfinity|Fail on incomplete ownership/read; stable occurrence events, later read retry|
|opticable-phase12-test-runner.timer|:00/:30 each hour +≤120s; persistent|root; Test registry/protected manifests/actions and exact CRM/R2 readback|Local journal/rootack; only exact central TestTask can transport, currently BOTHrootkillfalse and autoenv0; project/internal0; realforbidden|RootO_NOFOLLOWflock; ≤4actions/≤2writes;180s|Reconcile BEFORE kill; existing/uncertain off-host claim never resend; ambiguous becomes exception; final run success/no writes|
|Cloudflare opticable-control-plane cron|*/15UTC; semantic Toronto Mail/hour/Books/digest calendar|Worker; env/KV; core safe read observers|Queue/workflow/local events; mutating core workflows disabled/forbidden|Queuebatch10/retries5; workflowretries8/exponential5s/step30s|Queue86400s retention, DLQ no consumer; failure retry cannot bypass core universal fence|
|GitHub Monitor Production Health|*/15UTC; scheduling delays possible|Runner; core/PDF/Omada/provider reads|Health artifacts/monitoring only|CI timeout/concurrency|No guaranteed cron interval or unified business/backup alert surface|
|GitHub Schedule Customer Lifecycle|DISABLED_MANUALLY; sourcecron removed|No scheduled invocation|No business authority|Retained workflow_dispatch definition for history; runtime downstream writers forbidden|Historical failed dispatch retained as evidence; do not reenable|
|GitHub Customer Lifecycle Mailbox Poll|DISABLED_MANUALLY; sourcecron removed|No scheduled invocation|No business authority|Historical5m/HTTP30s|Duplicate retired; no recovered queue resumed|
|GitHub Customer Lifecycle Owner Digest|DISABLED_MANUALLY; sourcecron removed|No scheduled invocation|Draft workflow disabled/provider draft forbidden|Historical5m/HTTP30s|HTTP acceptance historically did not prove effect; no reenable|

## Development autonomy retirement

`optibrain-agent-dispatch`, `optibrain-agent-status` and `optibrain-agent-usage`, both service/timer forms, are MASKED to /dev/null and inactive. Originals archived under `/var/lib/optibrain/phase13-remediation/retired-development-units`. Authorization file `/etc/optibrain/authorize-persistent-codex-development` absent. No root/operator cron/controller/status/usage process can silently restart these units. Intentional authorized root can rewrite infrastructure; this is not a security boundary against root. Interactive Codex CLI/app-server is the manual workspace, not persistent development automation.

`Validate Autonomous Core` remains orphaned GitHub workflow metadata without a current workflow file; not evidence of a running worker. Ordinary OS timers and adjacent apps are outside the application timer count.

## Overlap, recovery and limits

Cloudflare is now the canonical business observer scheduler. Three duplicate GitHub business cron schedules were disabled at provider and source; GitHub health monitoring retained. No legitimate application timer was disabled. Test runner performs read reconciliation while all writes are killed.

Remaining P1/P2: explicit read/backup timeouts and local interprocess backup lock, stable incremental receipts/cache/batched CRM reads, bounded journal/archive/cache retention, unified failure owner/alerting. Receipt collector repeatedly rereads known Mail; service/operator views scan CRM, operations has N+1 reads. On disaster restore, keep all writer timers and development units OFF until root state and off-host/provider effects reconcile; never resume a stale pending create from a zero attempt counter. Exact restored API boot was tested without external network/provider writes.
