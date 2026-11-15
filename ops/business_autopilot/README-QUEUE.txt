OptiBrain review queue and unique storage accounting — NEW vps-f8e9b20e

The existing authenticated loopback owner review now derives packages on GET.
It writes no files,registry rows,status transitions or approvals. Existing hashes
and exact individual editorial/external approval scopes remain unchanged.
Default /review/ shows at most ten ranked packages,the five most valuable pending
decisions,a short completed-work summary and existing status-check opportunities.
All artifacts remain searchable at /review/?view=items and all packages at
/review/?view=all. /review/?package=ID expands one package; /review/queue.json is
the same authenticated read-only projection. No package-wide approval exists.

Ranking and classification
Exact native IDs group a response with its unpriced outline and a quotation
with its alternative FR/EN follow-ups. Names/emails never link separate customers.
Campaign service identity groups social,article,FAQ/video/media variants without
mixing their approval scopes. Camera/AI,lead follow-up,quotes and attribution
receive explicit business-priority weights. Source observation dates,not new
registration timestamps,govern freshness. Missing evidence remains UNKNOWN.
Priority is a local heuristic;no revenue/conversion lift is invented.
Older same-logical-path revisions are presentation-superseded only when a newer
registration exists. Equal-time variants remain variants. High text similarity
within one campaign/language/channel is a POTENTIAL_DUPLICATE label,never a merge
or deletion rule. Private customer text is excluded from similarity grouping.
Reports/planning/history receive a low-priority reference label. Every original
stays reachable,including reviewed,rejected,commented or superseded material.
Source age and reply status remain visible;an old source cannot establish a
current sales emergency. External sends,publishing,spend and release stay OFF.

Paused daily work
The existing worker still refreshes its bounded latest-cycle projection and
performs authorized cached analysis/planning under unchanged admission caps.
Zero-output completion now reuses existing immutable action_evidence and
ManagerStore receipts instead of creating empty run-*.json files. Repeated same
evidence/day/runtime returns CACHED without a new file. Nonempty manifests retain
their original immutable file receipts. No content is generated to fill the queue.

Storage accounting
storage_accounting.py performs read-only lstat allocated-block accounting with
one global (device,inode) set,including directory blocks. It excludes same-device
bind aliases from /proc/self/mountinfo,foreign filesystems and symlink targets.
Hardlinks are charged once;cross-category aliases and logical/apparent byte counts
are reported separately. Deleted-open files are measured separately. The df gap
is reported as filesystem metadata/live-scan variance;it is never called cache.
Categories are additive only in the unique-accounting report. Independent du
family totals overlap and must not be added to those categories.
Development bytecode may be proposed only with verified ownership,single-link
identity,matching cache header,retained exact source,and no active workspace.
Seven-day minimum applies. These proposals are outside the deployed lifecycle
allowlist and grant no cleanup authority. Logs,backups,source,recovery,active
tests,customer material and unresolved evidence remain protected.

Two separate future owner decisions — BOTH DISABLED
A: Disposable retention policy. Exact existing policy and cleanup-code hashes,
source/quarantine paths,holds and irreversible deletion risks are recorded in
approval-A-retention-policy.json. No current eligible files means no immediate
approval is needed. Policy approval alone grants no filesystem-access change.
B: Monitor filesystem access. The previous proposed drop-in exposes the whole
automation parent and freezes only a snapshot of child paths. It is broader than
required for read-only work and leaves future sibling paths writable. Recommendation:
reject/defer that exact proposal as written. Its exact hash,path and the generator
source hash are recorded in approval-B-monitor-access.json. This decision cannot
authorize disposal. Both permissions would be prerequisites for future automatic
cleanup under the current root/SQLite implementation;neither is enabled here.
Read-only review,classifications and current business planning need no expansion.
Do not install the old combined packet or silently treat either decision as
approval of the other. A future least-privilege access design needs its own exact
reviewed file and hash before it can be considered for installation.

Private runtime upgrade/recovery
Trusted source admin_review_queue.py checkpoints only review.py,private_preview.py,
runner.py and manifest.json before replacement. It preserves storage/lifecycle
code,policy,owner identity/expiry and all business data. Only the existing private
review process is relaunched under its original unprivileged UID;no API,website,
timer,permission or consequential flag changes. Actual restore is tested on
synthetic isolated files while preserving a newer-business-data marker.
Evidence family /var/lib/optibrain/review-queue-20261114 contains exact hashes,
pre-queue-runtime.tar.gz,source/test/CI records,unique accounting and two disabled
approval decisions. Existing whole-state backups cover it on the normal cadence.
To roll back the private UI/worker correction using trusted root administration:
sudo python3 /var/lib/optibrain/review-queue-20261114/admin_review_queue.py --ledger /var/lib/optibrain/review-queue-20261114 --rollback
This restores only exact checkpointed code/manifest and relaunches private review.
It never restores an old database or owner credential and grants no new access.
The prior storage rollback must refuse a newer runtime;use this latest exact
checkpoint before considering earlier recovery. Full-host R2/offline AGE recovery
remains separate and unchanged.

Business execution V1.3 — 2026-11-14 Toronto
The same owner view now displays verified operational context and weekly measured
performance. It reads one existing-journal snapshot,platform:business_execution_v13,
with exact source IDs and source-read timestamps. Existing source read budgets
are unchanged. The four additional bounded marketing comparison reads were
one-time authorized reads saved in AcquisitionStore; ordinary cycles only reuse
them when their effective periods match. They install no new provider polling.
The weekly comparison uses equal complete seven-day windows; GSC requires seven
distinct exact previous dates. Event counts are not unique qualified leads, CRM
inventory is not weekly acquisition, and quote totals are not earned revenue.
Historical missing acquisition fields remain unknown; legacy Inquiry_ID values
are retained. No email/name/visitor-ID cross-provider project merge is performed.

Eight retained operational contexts include the Nov19 noon bidder deadline for
Elenco project2627-26 and the existing Nov18 13:00 Toronto Queleco meeting. The
bidder deadline must not be confused with the Nov25 internal closing. Plans and
qualifications remain unverified; no portal intention button has been clicked.
EST-1145 was viewed in email, with a separate unset portal flag; neither proves
acceptance or reply. Art-Systeme has active contact threads but no proven exact
EST-1144 project link,so its generic reminder is suppressed in this view. No
Books status is changed. Fresh source observations expire after30 hours; the
owner view rechecks age on every read and never refreshes age by rendering.

Five exact immutable send-review alternatives for four existing opportunities
are reused,not copied or authorized. Editorial review still binds each individual
artifact hash. All91 originals and16 packages remain,with ten packages by default.
Current analysis replaces only latest-cycle.json,including on cached zero-output
cycles. At zero pending slots,the sandbox does not construct any draft content.
No new empty receipt file is created. The existing timer and databases remain.

V1.3 private-runtime recovery uses the existing trusted admin_review_queue.py with
--business-v13. It checkpoints only review.py,runner.py,business_work.py,
business_sources.py,engine.py and manifest.json. Other runtime files,storage policy,
credentials,expiry,provider permissions and business records are preserved.
Evidence: /var/lib/optibrain/business-execution-v13-20261114/ . Root archive member
and preimage hashes are verified before restore; actual isolated restoration is
tested. To restore this exact checkpoint with trusted root administration:
sudo python3 /var/lib/optibrain/business-execution-v13-20261114/admin_review_queue.py --business-v13 --ledger /var/lib/optibrain/business-execution-v13-20261114 --rollback
This restores code only,never an old database or credential. Earlier queue/storage
rollback must refuse this newer runtime. The API release ec9a8e85 and recovery/R2
references remain unchanged. Retention A is deferred; monitor-access B is rejected
as written. Neither is installed or re-requested by this mission.
