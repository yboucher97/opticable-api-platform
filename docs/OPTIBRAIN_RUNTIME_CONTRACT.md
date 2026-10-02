# Runtime, network and health contract

AUTHORITATIVE CURRENT. Units/proxy reconstruction source: [ops/phase15](../ops/phase15/). [Configuration](OPTIBRAIN_CONFIGURATION_INVENTORY.md) defines precedence; [state](OPTIBRAIN_STATE_CONTRACT.md) defines stores. Four long-running services, five application timer/oneshot pairs. Six retired engineering units masked/inactive. Current services/timers are read from systemd, not inferred from Git.

## Services

| Unit; user | Purpose / input → output / providers / authority | Dependencies; lock; timeout/restart; kill behavior; recovery importance |
|---|---|---|
| `opticable-workflow-api`; matching unprivileged user | FastAPI, authenticated intake/operator views and bounded internal observers; env/definitions/DBs → immutable events/read projections; Zoho/Cloudflare/GitHub/OVH reads; real writes denied | Python venv, root policies/registries/shared OAuth; SQLite leases/CAS/idempotency + credential lock; Restart=always, 5s; recovery env disables internal automation; core boot/DB integrity required |
| `opticable-password-pdf`; matching user | Contained PDF support health/local generation; brand/env → local files; provider/WorkDrive/CRM writer pipeline denied | Separate PDF venv/brand/assets/shared OAuth; local job files, retired provider paths; Restart=always 5s; brand CRM/WorkDrive false plus source denial/proxy containment; preserve support config/assets |
| `opticable-omada-site`; matching user | Contained Omada HTTP support/health; env/dist/data → local read responses; public provision/run endpoints removed/denied | Node 22, locked npm deps/compiled dist; browser execution is retired, no required live browser install; TimeoutStopSec=20s, Restart=always 5s; source/proxy denial; restore support state but browser cache expendable |
| `caddy`; caddy | TLS/proxy and legacy-route denial; Caddyfile → loopback routing; ACME/edge TLS | Ubuntu package and current file; process admin listener, no business lock; notify service, stop5s, reload validated config; keep consequential route deny matchers; TLS state optional supplement or new certificate before cutover |
| `opticable-phase9-intake-receipts`; API user | Mail/connector GET receipts → receipt/intake chronology; fallback OFF | API env + export key + separate receipt DB; `phase9-receipts.lock`; oneshot300s, no automatic restart; root fallback + universal transport kill; preserve receipt identities and cursor |
| `opticable-phase10-service-events`; API user | CRM GET lifecycle/service snapshots → durable occurrences/rebuildable display cache | API env + service store; `phase10-service-events.lock`; oneshot300s, no restart; provider transport kill remains independent; restore occurrences before observer resume |
| `opticable-phase12-test-runner`; root | Reconcile retained exact TEST evidence/claims, then optional central Task family; currently 0 writes; local readiness post-hooks | API code, root registries/runner env, action DB + R2 claims; `/var/lib/optibrain/phase12/runner.lock`; oneshot180s, bounded4 actions/2 possible writes, no restart; global/root family gates OFF, real forbidden; recovery masks entire service, reconcile before any future grant |
| `optibrain-backup`; default root | Read source/private config/state → online consistent eight-DB archive/hash/manifest | Current root-installed backup script; `/var/backups/optibrain/.backup.lock`; oneshot45min, no restart; preserve-existing retention/holds; essential independent local generation |
| `optibrain-phase2a-upload`; root | Public-recipient AGE + immutable R2 upload + full downloaded-byte hash; no business provider writes/deletes | Latest archive/checksum, AGE recipient, AWS INI, Python boto3, fixed R2 policy; `/var/lib/optibrain/phase2a/lock`; oneshot46min, no restart; no private AGE identity, no R2 deletion; essential off-host recovery |

API hardening: no new privileges, private tmp/home, strict system filesystem, writable app/shared state only, empty capabilities, Unix/IPv4/IPv6 only. Root backup/uploader/runner have bounded capabilities/private filesystem restrictions; manual engineering sudo remains available. Exact reconstructed definitions include installed safety/hardening fragments. Auxiliary root-installed helpers are reviewed code and never execute mutable checkout authority to update themselves.

## Timers and external schedules

| Timer | Schedule / output freshness | Current versus rebuild |
|---|---|---|
| `optibrain-backup.timer` | 02:30 UTC daily + ≤15min random delay, persistent; local archive | Active production; masked replacement until contained backup verification |
| `optibrain-phase2a-upload.timer` | 03:00 UTC daily + ≤15min delay, persistent; verified R2 generation | Active production; masked replacement until credentials/readback/holds verified |
| `opticable-phase9-intake-receipts.timer` | boot2min then every5min ±30s; receipt reads | Active production; masked replacement until saved-cursor/receipt reconciliation |
| `opticable-phase10-service-events.timer` | boot10min then hourly ±1min; CRM service reads | Active production; masked replacement until integrity/reconciliation |
| `opticable-phase12-test-runner.timer` | every30min + ≤120s delay, persistent; reconciliation/readiness | Active production with TEST writes OFF; masked replacement (service also masked) |

Queue metrics post-hook is GET-only and writes a redacted `/run/optibrain-readiness/queue-depth.json`; the local sampler writes `status.json`. It uses the existing runner cycle, no additional timer. Recovery masks keep these jobs off initially; manual local verification is separate from starting an executor.

Cloudflare `opticable-control-plane`: cron `*/15 * * * *`, producer/consumer `opticable-business-events`, DLQ `opticable-business-events-dlq`, durable `opticable-business-workflow`; observation delivery only. Connector `opticable-ai-connector` has separate OAuth/KV/export. GitHub health monitor every15min; Customer Lifecycle Owner Digest, Mailbox Poll and Schedule Customer Lifecycle remain `disabled_manually`. No redundant scheduler or hidden persistent development worker is needed for operation. OS apt/logrotate/sysstat/fstrim/backup housekeeping timers are OS responsibilities, not business authority.

## Every intentional listener

| Listener | Classification | Purpose |
|---|---|---|
| TCP22 IPv4/IPv6 | PUBLIC REQUIRED | Hardened SSH; owner/admin keys only |
| TCP80/443 IPv4/IPv6 | PUBLIC REQUIRED | Caddy redirect/TLS and reverse proxy |
| UDP443 | PUBLIC REQUIRED capability | Caddy HTTP/3 listener; host firewall may deny UDP (no extra rule opened) |
| TCP127.0.0.1:8100 | LOOPBACK / PROXY ONLY | Core API |
| TCP127.0.0.1:8000 | LOOPBACK / PROXY ONLY | PDF support |
| TCP127.0.0.1:3210 | LOOPBACK / PROXY ONLY | Omada support |
| TCP127.0.0.1:2019 | LOOPBACK | Caddy admin; never publish |
| TCP/UDP127.0.0.53/54:53 | LOOPBACK | Ubuntu systemd-resolved stub |
| UDP interface:68 | INTERNAL | Ubuntu DHCP client; not a public business service |
| Transient TCP127.0.0.1:ephemeral owned by `codex` | LOOPBACK / INTERNAL | Active manual editor/session broker. PIDs/cgroup are recorded in host evidence; not an optibrain-agent daemon. Ports vary and disappear with session. |

No unexplained listener. Public firewall permits TCP22/80/443; app ports remain loopback. The rebuild test has loopback only, no external interface/default route, separate mount/PID/network namespaces; no application can reach a provider or host API. No production firewall/DNS change is needed for the proof.

## What health proves

| Dimension | Evidence and limits |
|---|---|
| API health | HTTP200/version = responsive process; not provider/business readiness |
| Business readiness | Today’s dated source/attention + immutable action/exception scopes; no write grant |
| Provider readiness | Last CRM/Mail GET status/age, delta cursor and native binding readback; native Forms remains owner-UI evidence |
| Backup readiness | Archive/checksum freshness; verify-latest validates files/DBs. Off-host requires independent downloaded-byte hash, not PUT success |
| Operator attention | Owner-authenticated Today/system-health; current real attention separate from Test/historical/resolved |
| Automation safety | Trusted root kill, disabled real/Test/legacy modes, exact registration pins, masks; live inspector rather than receipt alone |
| Infrastructure readiness | systemd results/freshness, disk/DB/storage/log bounds, Caddy route/auth denial, exact OVH identity; queue metric is approximate and cannot prove message semantics |

Runtime samples older than90min are UNKNOWN. Timer deadlines: backup/upload48h, receipts15min, services150min, runner90min. Local/off-host backup readiness uses36h. Disk warn80%, action90%. Staging warn15GiB/action25GiB; active DBs128/512MiB; app diagnostic logs64/128MiB; system journal576/640MiB allows active-file overhead above its512MiB cap. Application rotates5×5MiB, journal max90d. Business evidence is not log retention.

Queue backlog: DLQ>0 or active message age>30min = ACTION REQUIRED; active count>100 = DEGRADED; fresh empty/within-bound active queues = OK; absent/malformed/stale sample = UNKNOWN. Sampling never pulls/acknowledges/replays messages. Source: [Cloudflare GET queue metrics](https://developers.cloudflare.com/api/resources/queues/methods/get_metrics/). First observed DLQ129 is retained delivery work, not a Phase15 provider mutation.
