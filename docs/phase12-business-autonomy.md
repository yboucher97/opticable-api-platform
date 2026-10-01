# Phase 12 business autonomy foundation — 2026-10-01

This is **application workflow autonomy**, not a self-running Codex development
worker. The latter remains disabled. Production defaults keep Phase 12 automatic
mutations off; no timer or broad real-record executor is installed. This first
boundary governs new Phase 12 actions and does not silently change legacy
workflow handlers. Existing CRM exact-call grants, outbound approval controls,
protected baselines and Books write denial still apply beneath it.

## Current action inventory and policy

The actual automation registry includes read-only CRM observation/reconciliation,
mailbox observation, Books observation, lead qualification, provider reads,
AI generation, and event emission. Mutating handlers include CRM lead upsert,
promotion, Task/Meeting/quote Task creation, mail draft and approved send/reply,
Zoho Sign contract send, generic provider requests and Windsor supported actions.
Phase 8–11 one-shot guarded operations additionally cover CRM relationships,
Deals, project onboarding, work-order scheduling/completion, Cases, Services,
local folders/documents and lifecycle events. Deletion, merging, bulk writes,
Books/financial writes, provider configuration and infrastructure changes have
no Phase 12 automatic executor. The generic legacy provider request paths retain
their own existing permission and retry controls; migrating each to this central
business policy is future work.

| Tier | Phase 12 examples | Mission default |
| --- | --- | --- |
| R0 | CRM/provider read, observation | Automatic even with the write switch off |
| R1 | Test Lab internal event, folder, Task create | Test Lab automatic only with exact ownership and flag |
| R2 | Test Lab Task update, accepted Deal onboarding, project/work/service update, draft | Test Lab automatic only on explicit per-action allowlist |
| R3 | Send, conversion, merge; deletion, bulk, Books, finance, security/config | Test Lab consequential action requires exact human approval; forbidden categories are denied |

Protected baseline IDs are always read-only. Unknown ownership defers. Real
records cannot be mutated through the Phase 12 boundary, even when a real-action
flag is set. Confidence is HIGH only for exact registered provider IDs, live
`OPTIBRAIN TEST` marker evidence, material provider state and a payload-bound
request key. A score cannot override the protected fence. A Test Lab action
requires `OPTIBRAIN_BUSINESS_AUTO_WRITES=1` and an exact Test flag such as
`OPTIBRAIN_AUTO_TEST_TASK=1`; all default to off. No real-action environment
flag is honored in this mission.

`workflow/automation/business_autonomy.py` records action type, target,
ownership, tier, confidence, decision/reason, payload SHA-256, provider, expected
version, attempts, result and reconciliation in a durable SQLite journal. It
stores only a small safe effect summary, never email bodies or credentials.
The action ID derives from a stable request key; reusing that key with a changed
payload fails. CRM transport still requires the exact Test Lab grant and its
own before/after provider readback. The action dispatcher checks fresh target
ownership, `Modified_Time` and material state immediately before a write.

Approval issuance requires an authenticated operator and a Test Lab R3 proposal;
it binds one action, target, exact payload hash, human actor and expiry no longer
than one hour. Claiming it atomically consumes the opportunity to execute.
The approved dispatcher revalidates target state, then requires exact provider
readback. A stale state stops before transport. An uncertain provider outcome
enters RECONCILE and is never blindly retried. Replaying a consumed approval is
denied. No Phase 12 approved-send execution endpoint is exposed in production;
the queued controlled Test Lab send is only a proposal and was **not sent**.

The read-only authenticated routes are `/v1/operator/phase12/autonomy`,
`/approvals` and `/exceptions`; approval issuance uses authenticated,
same-origin `POST /v1/operator/phase12/approvals`. All routes deny unauthenticated
access. Successful actions stay out of the exception queue. Business times
display in America/Toronto; durable instants use timezone-aware UTC.

## Provider-backed Test Lab proof

The one-shot `ops/phase12/test_lab_autonomy.py` used registered Test Lab Task
`5062683000007908026`. Automatic `Not Started → In Progress` was read back.
Another exact update committed in Zoho, then deliberately lost its acknowledgement:
the journal entered RECONCILE and an exact read proved `Completed` without a
retry. A proposal based on the older `In Progress` state became STALE and made
no provider call. Replaying the first action made no duplicate write.

A fresh registered accepted Test Deal `5062683000007943001` automatically
onboarded project `OB-J-E785F334807F`, one work order
`5062683000007915018`, one Service `5062683000007938014` and a deterministic
local folder. Exact Deal→Account→Contact→site and Service/Work Order links were
read back. Replaying onboarding created no duplicate project, work order,
Service or folder. This is synthetic Test Lab work, not physical installation.

Protected Task and Deal shadows were denied before transport. Books write was
denied. Turning off the business write switch deferred a Test Task update while
an R0 read still succeeded. A TEST_ONLY controlled email-send proposal entered
APPROVAL_REQUIRED, with no send executor or provider call. Unit tests prove
payload/target/actor/expiry binding, one-use consumption, approved exact-readback
execution, and stale approval suppression. Provider-backed approved sending is
not claimed. Evidence is in `ops/phase12/TEST_LAB_EVIDENCE.json` and the
root-only `/var/lib/optibrain/phase12/test-lab/evidence.json`.

## Retry, recovery and limits

Reads may use bounded retries under the existing automation engine. Internal
idempotent actions may be repeated by replay key. CRM creates/updates and sends
are journaled before transport; an interrupted or ambiguous response requires
read-only provider reconciliation first. The Phase 12 dashboard counts actual
mutating successes, pending approvals, denials and unresolved exceptions. There
is no Phase 12 periodic executor yet; the existing application intake and
lifecycle timers are separate. This avoids unattended CRM writes until the
central boundary has covered more legacy handlers and a controlled canary has
been authorized. No real customer write, send, Task, Books or financial action
was performed for this mission.
