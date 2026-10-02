> SUPERSEDED — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_RECOVERY_GUIDE.md).

# Phase 14 retention and hold policy

Retention is conservative and local only. Root policy schema 1 retains seven latest plaintext generations plus every exact audit/recovery/release reference; two recent verified ciphertext generations plus owner proof; all failed/uncertain uploads and immutable preparation/readback evidence. It implements no R2 deletion.

Fresh backup/archive footprint was 18,782,774,178 bytes after a new pre-change backup (about 17.49 GiB), compared with reconnaissance 16.7 GiB. Exact dry run found 8,950,924,187 bytes in 33 redundant encrypted spool files. All 33 passed full local hash, immutable remote download-hash+manifest evidence, hold and retained-generation coverage checks. Those files were deleted under the uploader lock; remote objects deleted 0. The remainder immediately after cleanup was about 9.83 GB. Final snapshot may include a new release backup and upload; final-verification.json records exact final bytes and any further same-policy cleanup.

| Family | Classification | Rule / action |
|---|---|---|
| `/var/backups/optibrain` plaintext archives | AUTHORITATIVE BACKUP / RECOVERY HOLD | Seven newest plus all exact root/historical references; unverified hash/coverage ⇒ MANUAL REVIEW |
| Independently downloaded/hash-verified immutable R2 archive + manifest | OFF-HOST VERIFIED | KEEP indefinitely in Phase 14; remote delete absent |
| Owner generation 20261001T202728Z | RECOVERY HOLD / AUDIT HOLD | Keep plaintext, ciphertext, manifest and owner proof indefinitely; offline identity never copied |
| Two newest independently verified local ciphertexts | RECOVERY HOLD | KEEP in addition to owner generation; complete SHA coverage required before any deletion |
| Older completed encrypted duplicates | STAGING / SAFE DELETE CANDIDATE | Candidate only after local cipher hash, remote full-byte hash, exact manifest hash and >=2 recent+owner coverage |
| Partial encryption / failed or ambiguous upload | TEMPORARY / RECOVERY HOLD | KEEP until exact outcome is reconciled; age alone insufficient |
| prepared.json, upload audit/state/failure/locks | AUDIT HOLD | KEEP; no deletion by cache pruning |
| Isolated restore/proof directories and historical DB copies | AUDIT HOLD / RECOVERY HOLD | KEEP / ARCHIVE in place; dependency/evidence references retained |
| Retired deployment/dev code and old central docs | OBSOLETE runtime / AUDIT HOLD | Archive source/evidence; direct obsolete release execution refused |
| Manual temporary reports | TEMPORARY | Default 30 d only if no referenced audit/recovery role; this mission's reports retained |
| Successful retry/transient bookkeeping | TEMPORARY | Existing 30 d bounded maintenance only; never action envelope, idempotency fence or reconciliation intent |
| Provider metrics | TEMPORARY | 30 d /10k rows; non-authoritative |
| Mail metadata cache | TEMPORARY | 30 d seen-at; daily validation; committed event required |
| CRM display snapshots / Today process cache | TEMPORARY | 5 min /60 s display TTL; daily complete provider inventory; no mutation authority |
| Journald/logs | TEMPORARY | Existing bounded journal policy preserved; 128/512 MiB warning/action growth sample; mission/audit logs held |
| Unknown paths/remote consumers | UNKNOWN | MANUAL REVIEW; never age-delete |

Installed `/usr/local/lib/optibrain/phase14-retention.py` defaults to dry run. Report fields: exact path, bytes, classification, KEEP/ARCHIVE/DELETE CANDIDATE/MANUAL REVIEW, reason, retention rule, hold and expected hash. Report SHA covers policy, sorted paths, holds and recovery coverage. Execution refuses changed reports/policy, symlinks, nonregular/hardlinked candidates, out-of-family paths or any hash/hold conflict; all candidates are revalidated before the first unlink. Backup/helper/audit material never becomes a candidate solely because it is old.

Concrete root reports: `/var/lib/optibrain/phase14/retention/dry-run.json` and `execution.json`. Preserve execution receipts. Holds include exact generations found in root release/recovery/historical documents and owner evidence; this conservatively kept every plaintext generation during initial cleanup. To release a hold later, review its dependency, record why the independently retained evidence suffices and rerun the full dry run. Do not edit an old report to authorize deletion.

No remote retention policy was claimed proven. R2 recovery generations, locked business effect claims and owner recovery evidence remain intact. A manually requested reupload of a pruned old ciphertext must download/reconcile the exact existing immutable object; never re-encrypt over its existing key. Routine uploader selects the newest retained fresh archive, unaffected by older ciphertext pruning.

The [exact major-family inventory](phase14-implementation-evidence/storage-family-inventory.json) records eleven storage/log/evidence families plus three archived DB copies, with bytes, hold, rule and KEEP/ARCHIVE/MANUAL REVIEW decisions. Deletion candidates and exact per-file hashes are in the root retention dry run; family totals can overlap, so they are not summed as a host total.
