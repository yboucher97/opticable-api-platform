> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# Phase 11 operations foundation — 2026-10-01

The manually initiated Test Lab uses existing Zoho CRM Accounts, Contacts,
Deals, Service Locations, Services, Installations and Cases. The CRM `Projects`
module rejects CRM API access, so one small OptiBrain project crosswalk ties a
source Deal and site to work orders, installed Services, tickets, documents and
Tasks. It does not create a second customer or service model. The crosswalk
stores immutable `OB-C`, `OB-P`, `OB-S`, `OB-J`, `OB-WO`, `OB-T`, `OB-SV` and
`OB-TK` IDs separately from provider IDs; a provider migration can update the
mapping without renaming the OptiBrain object. Earlier Phase 7 `OB-*` references
were provisional and are not asserted to identify this different Test Lab lead.

The authenticated read-only operator routes are
`/v1/operator/phase11/operations?scope=lab` and
`/v1/operator/phase11/project/{project_id}`. Live scope contains no unverified
real project, and Test Lab records never appear there. The detail view links to
the existing Phase 9 source trace and reads every registered CRM object fresh.
Each project has at most one primary next action. All instants are timezone
aware and display in `America/Toronto`; CRM date-only Task deadlines are
Montreal business dates. These routes never write to a provider.

The Test Lab reused the Phase 9 source-attributed warehouse Account, Contact
and Deal plus its Phase 10 site. It created one Camera Installation Service,
two Zoho Installations (initial and repair), one Zoho Case and one Deal-linked
document Task. The same initial work order progressed Requested → Scheduled →
In Progress → Completed; the camera Service gained a verified synthetic
installation date, and the source Deal moved to Closed Won. The Case opened,
created a repair work order, then closed after that work completed. The
remaining open document Task is the current primary action. These are staged
synthetic states; they do not assert that field work occurred. Exact IDs and
evidence are in `ops/phase11/TEST_LAB_REGISTRY.json` and the root-only
`/var/lib/optibrain/phase11/test-lab/registry.json`.

Two harmless text documents use `YYYY-MM-DD_PROJECTID_DocumentType.ext`; the
local deterministic tree is customer ID / site ID / project ID with Quote,
Plans, Photos, Work Orders, Service Reports and Closeout folders. File SHA-256,
category and path are registered. Processing the project twice kept the same
folder and provider objects. WorkDrive OAuth is configured, but the bounded
read-only team discovery returned no usable team folder for an isolated Lab
root. Provider folder creation is deferred; no real customer folder was used.

The one-shot root Test Lab script journals a provider mutation before transport,
uses the existing protected-record boundary, and reads back the exact result.
The original 99-record protected baseline and 12 Service/12 Service Location
sidecar remain read-only. A new root-only Cases snapshot captured zero existing
Cases before the first Case write. Installation and Case creates require visible
TEST markers and owned relationships; the created IDs are registered. No real
customer record, Mail, Books or finance object was changed.

Operational events are created in the controlled mutation path and keyed to
their evidence. Project, work-order, service and ticket terminal events are
once per object. A test exposed that Zoho `Modified_Time` changes on unrelated
edits; a replay briefly added one duplicate completion event. The old ledger
was archived as `registry-before-event-replay-repair.json`, the duplicate was
removed from the active ledger with a repair record, and two further provider
replays added zero events. A future outside-OptiBrain edit is not yet observed
automatically; the current event automation covers the controlled write path.

Five protected Service records were sampled read-only. Each linked to a real
Service Location and customer Account; none had an installed date, Service
stage, source Deal or primary Contact. Existing relationship and service type
are useful, but project/work history is incomplete. Future real operations need
only customer, site, contact, source opportunity, work scope/status and planned
time initially; installation completion and service history can be recorded as
the work progresses. Protected records were not retrofitted.

No Codex worker, autonomous task queue or new timer was installed. The existing
production API, backups, receipt collector and Phase 10 lifecycle timer remain
normal application services. WorkDrive provider folders, calendar dispatch and
automatic inbox-to-project routing are deferred optional integrations.

## Guarded accepted Deal onboarding closure

The manually invoked `ops/phase11/onboard_test_deal.py` accepts only a registered
`OPTIBRAIN TEST` Deal at `Contracts Signed` with an owned Account, linked Contact,
nonempty service scope, and exactly one owned site for that Account and Contact.
Missing or ambiguous relationships fail closed. A real protected Deal cannot pass
the CRM write firewall. This is a reusable one-shot onboarding operation, not a
timer or permission for real accepted Deals. Future real onboarding needs explicit
authorization and a separately reviewed real-record write boundary.

The operation records an immutable `OB-J` project crosswalk to the source Deal,
creates one pending Service relationship and one requested Installation work order,
and creates the six-category deterministic local document root. Each CRM mutation
is journaled before transport and checked by exact provider readback. Replaying
onboarding reuses the same project, site, Service, work order, folder, document and
events. An ambiguous provider acknowledgement stops for reconciliation. The
first work order can be scheduled only at an aware future Montreal time with a
bounded duration and a clearly marked test assignment. Overlapping active work
for the same assignee is rejected. The provider `Scheduled_Date` and
`Assigned_To` fields are the schedule source; the local project holds duration.

The closure scenario used new Test Deal `5062683000007918009` and reused the
registered Test Lab warehouse Account, Contact and site. Project
`OB-J-3C80B6CE886D` created one work order `5062683000007920012`, one pending
Service `5062683000007911007`, and two synthetic hash-checked documents. The
work order moved Requested → Scheduled → In Progress → Completed, then the
Service became Active and the Deal Closed Won. This is simulated completion;
no field work or revenue is asserted. The operator queue and project detail
read fresh Zoho state and show assignment, schedule, scope, canonical IDs,
provider IDs, document root and installed-service handoff. All business times
display in America/Toronto.

The one-shot reconciliation compares meaningful provider fields instead of
`Modified_Time`. A guarded direct provider assignment edit outside onboarding
produced one `WORK_ORDER_ASSIGNMENT_CHANGED` event; a second reconciliation
produced zero. Broader automatic observation of arbitrary outside edits is not
installed. The Test Lab event ledger has 11 unique closure events, and all nine
CRM writes in this mission were read back. Exact evidence is in
`ops/phase11/CLOSURE_TEST_LAB.json` and the root-only
`/var/lib/optibrain/phase11/test-lab/closure-evidence.json`.

The one protected historical Deal sampled read-only was at `Quote Accepted` with
Account and Contact links but no service scope or site evidence. It is not ready
for this onboarding rule. The minimum future real handoff requires accepted
stage, Account, linked Contact, unambiguous site, and concrete service scope;
schedule and responsibility can be set after project creation. WorkDrive team
discovery returned HTTP 415 in the one bounded attempt, so the isolated local
folder remains the document destination. Calendar and inbox routing remain
optional. All Test Lab objects stay excluded from the live operations queue.
