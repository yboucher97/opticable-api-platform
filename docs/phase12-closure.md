> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# Phase 12 closure: central follow-up policy and scheduled Test Lab runner

The selected legacy executor is `lifecycle.crm_create_followup_task`. It was
previously hard-blocked. The engine handler now accepts only an exact Lead ID
and can **only propose** a Task. The proposal reads Zoho, requires an open
follow-up obligation, classifies ownership against the protected baseline and
registered Test Lab marker, then stores an immutable due-window action. A
protected target is denied before enqueue. Only the fixed root-owned scheduled
runner can write the Task, after the Phase 12 risk policy decides AUTO_EXECUTE
and the existing single-call Test Lab CRM firewall grants the exact payload.
The API handler cannot call the provider writer directly.

| Executor class | Current guard | Central policy | Priority |
| --- | --- | --- | --- |
| Follow-up Task create | Proposal-only; exact TEST marker; CRM grant | Yes | Migrated |
| Test Deal→Project | Phase 11 root Test grant, Phase 12 one-shot wrapper | Yes for Phase 12 wrapper | Existing guard; later route migration |
| Lead upsert/create and form enrichment | Phase 6/7 exact grant and Phase 9 exact receipt | No | High before real autonomy |
| Lead conversion, merge, deletion, bulk | Blocked or approval-only | Dry-run R3/deny | Keep disabled |
| Work orders, Cases, Services, Deals | Root Test Lab grant, exact readback | Not universally | Later migration |
| Lifecycle/quote Tasks, Meeting | Legacy blocked or bounded Test Lab helper | Not universally | Later migration |
| Draft/send/reply | Existing draft and outbound approval guards | New controlled R3 proof only | High before real send autonomy |
| Books/finance | Read-only gateway | Hard deny | Forbidden |
| Folder/documents | Deterministic local Test Lab manifest | Partial | Optional |
| Generic provider actions/Sign/Windsor | Existing separate permission gates | No | Review before activation |

The application runner accepts only stored follow-up Task actions. It polls an
indexed due table (four actions maximum), allows two provider attempts at most
per run, and has a 30-minute systemd cadence. A root-owned `flock` prevents
overlap and releases after a crash. systemd bounds runtime to three minutes.
No Codex/OpenAI invocation, arbitrary command input, full CRM scan or real
write flag exists. The runner uses root only because the existing Test Lab CRM
grant is root-only; the service is fixed-purpose and uses strict filesystem
write paths. The API service and operator routes cannot invoke its writer.

An action is journaled before transport with its source trigger, expected CRM
version/state, exact Task effect and run ID. A prior attempted/ambiguous
provider create is reconciled from a previously verified Test Lab operation;
unknown outcomes remain exceptions and are never retried blindly. Replaying a
successful scheduled action makes zero new Tasks. Turning off
`OPTIBRAIN_BUSINESS_AUTO_WRITES` leaves due proposals pending while reads and
decisions continue. The timer environment enables only Test Lab Task actions;
real CRM and real send flags remain off. The autonomy page shows last run,
last success, actions, writes, exceptions and duration in Montreal time.

The controlled R3 Mail test uses sender `yboucher@opticable.ca`, recipient
`hckyan97+obp8wait@gmail.com`, and registered Test Lead
`5062683000007915001`. The explicit manual mission authorizes one such Test
send. The root-only proof records that authorization basis and issues a
30-minute, one-use approval bound to exact sender, recipient, subject, body
SHA-256, Lead version, action and payload hash. This is a mission-authorized
Test Lab approval, **not a simulated Cloudflare login**; the operator HTTP
approval route remains authenticated. No general approved-send endpoint is
exposed. Sent-folder readback must prove the provider ID and body hash before
the journal can become succeeded. Ambiguous outcomes stop for read-only
reconciliation. A separate fixture proves stale approval cannot send.

The first synthetic due-Lead create was rejected by Zoho with HTTP 400 because
the datetime contained fractional seconds. An exact-email search found zero
created Leads; the rejected attempt remains documented. The accepted v2
submission uses a second-precision Montreal timestamp. No blind retry occurred.
