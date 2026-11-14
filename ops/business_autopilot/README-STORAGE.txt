OptiBrain storage budget and disposable lifecycle — NEW vps-f8e9b20e

This extends Business Autopilot V1.2. No application release, new database,
scheduler, agent, provider writer, credential store or permission is introduced.
All 45 consequential flags remain OFF. Existing encrypted R2 recovery and every
GitHub recovery reference stay protected. Local business engineering is distinct
from publishing or customer/financial execution.

Enforced admission
2 new marketing files/Toronto calendar day; 10/rolling 168 hours; 30 active
marketing/recommendation items awaiting review. An individual language, media
file, calendar or content pack counts as one file; no free variants. Revisions
consume the same marketing limits. Legacy excess is preserved and pauses new
optional content; it is never deleted simply to satisfy a count.
2 GiB disposable ceiling, counting previews, quarantined identities and uncertain
generation reservations. Pause at 1800 MiB, leaving an 8 MiB bounded run margin.
25 GiB minimum reserve; pause optional file generation before available space
falls below 35 GiB plus 8 MiB. The existing root monitor retains its original
50/35/25 GiB alerts and backup protections. These guards bound this producer;
protected backups and unrelated system writers still require capacity monitoring.
Daily/weekly counts include expired and deleted creations while in their window.
Reservations in existing action_evidence charge uncertain interrupted attempts.

Useful work during a pause
Native bounded observations, inquiry/lead follow-up preparation, quote review,
business prioritization and analysis continue. latest-cycle.json replaces a
bounded derived projection; it is not an immutable authority or a new registry.
All new files, including business work, share 8 MiB/run and disk admission.
Existing equivalent pending semantic work blocks copies across dates/weeks/social
slot numbers. Explicit requested improvements can produce budgeted revisions;
original reviewed/commented bytes and decisions remain protected.

Lifecycle and exact scope of proposed standing permission
Unreviewed marketing drafts and recommendations: 30 days since latest metadata
interaction, registration or file change. Any owner approval (even expired),
rejection, comment or revision request permanently protects that item.
Temporary tests: 7 days; private staging: 14 days. These additionally require
explicit disposable=true, in_use=false and evidence_required=false metadata.
Unregistered files, unknown statuses, changed hashes, missing ownership proof,
symlinks, hardlinks and unresolved action/incident/test references are held.

Exact source allowlist, no recursive tree deletion:
/var/lib/opticable-workflow-api/output/automation/business-autopilot/artifacts
/var/lib/opticable-workflow-api/output/automation/business-autopilot/temporary
/var/lib/opticable-workflow-api/output/automation/business-autopilot/disposable-previews
Private website-preview remains measured and protected; its currently active
review pages are not classified as disposable staging. Engineering repositories,
browser/tool caches and old backup staging are inventoried but not allowlisted.
Source files must be single-link regular files owned by the existing service UID,
with an exact registered path, byte count and content SHA256. Every directory is
opened using no-follow dirfds with verified ownership and mode.

Eligible files move without replacement, on the same filesystem, to:
/var/lib/optibrain/resource-management/disposable-quarantine
This is root-owned 0700 custody. Moving an item frees zero storage. Each moved
inode is reverified; uncertainty holds it without unlinking. After at least seven
full days, recheck protection, approval, hash, ownership, open descriptors/maps
and exact file identity before unlinking only the sealed quarantine name.
Never delete approved/rejected/commented, legal, customer, financial, audit,
GitHub source, backup, recovery or unresolved incident/test evidence. No R2
expiration, remote deletion, Git operation, business-row deletion or evidence
table pruning exists in this implementation. Immutable lightweight lifecycle
receipts retain identity/provenance/policy, not disposable content bytes.

The existing business execution.lock and SQLite writer transactions serialize
worker admission, review and cleanup. Durable QUARANTINE_INTENT and DELETE_INTENT
precede effects. A fresh process reconciles interrupted moves/unlinks. Each exact
path+hash has one operation identity; final receipts prevent duplicate deletion.
At most 100 files can progress per existing monitor cycle. New holds win on every
phase. Future code/policy changes invalidate standing authority automatically.

Approval state
No initial production move or deletion is authorized or performed. The runtime
loads /etc/optibrain/business-storage-policy.json, root-owned, non-writable to the
worker. The root-only approval file is ABSENT:
/etc/optibrain/business-storage-approval.json
Thus the existing resource timer performs classification/reporting only.

One future owner decision can authorize recurring eligible local disposal:
"Approve the verified OptiBrain disposable storage policy [policy SHA256] and
cleanup implementation [cleanup code SHA256]: automatically quarantine only
eligible allowlisted items, then delete them after seven days under the documented
protection/identity checks; preserve immutable receipts."
Use the final report's exact hashes. Trusted owner administration then records
schema=1, actor=owner:opticable, actual approved_at, exact policy_sha256 and
cleanup_code_sha256, quarantine_enabled=true, permanent_deletion_enabled=true
in the root-owned 0600 approval file. Never manufacture approval or copy a packet
with a placeholder date into the live approval path. No per-file approval is
needed after that standing decision, within this exact scope. This grants no
authority to prune broader staging/cache/recovery families.

Verification and recovery
Private evidence family /var/lib/optibrain/storage-budget-20261114 contains
checkpoint.json, pre-storage-runtime.tar.gz, installed.json, dry-run inventory,
tests and source identities. Existing whole-state encrypted backups cover it.
Existing resource monitor exposes business_storage through latest.json and
daily-summary.txt; business-storage-latest.json contains precise file decisions.
No separate cleanup timer is installed.

Run regressions from isolated development with the existing dependency venv:
/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -B -m unittest discover -s ops/business_autopilot -p 'test_*.py' -v
/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -I -B ops/phase6/validate.py
sudo /opt/opticable-api-platform/apps/workflow-api/.venv/bin/python -I -B ops/business_autopilot/test_storage.py --root-integration
Root integration is synthetic, isolated and tests the actual restore function,
fresh-process interrupted cleanup, seven-day quarantine, late comment holds,
immutable receipts, changed approval and duplicate deletion. It deletes no
production artifacts.

Manual private-runtime rollback requires absence of cleanup approval and exact
installed hashes. Use the preserved committed admin_storage.py from the ledger:
sudo python3 /var/lib/optibrain/storage-budget-20261114/admin_storage.py --ledger /var/lib/optibrain/storage-budget-20261114 --rollback
It restores only V1.2 private runtime/monitor preimages, relaunches private review
with the existing UID/identity/expiry and holds optional drafting by clearing its
existing ExecStartPost. Native collection continues. No API restart, old database
restore, artifact/audit loss or renewed owner access occurs. Forward-fix budgets
before restoring the prior exact business-artifacts.conf hook. Never restore the
entire archive over the host or roll back business journals.
If standing cleanup was subsequently enabled, remove that authority deliberately,
hold the producer and review quarantine/reconciliation receipts before any code
rollback. Existing encrypted R2/offline AGE full-host recovery remains separate.
