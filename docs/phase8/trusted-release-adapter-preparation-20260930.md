# Phase 8 trusted release adapter preparation

Task: `phase8-trusted-release-adapter-preparation`. This is branch-only source;
no root adapter, authority, recovery producer, stage executor, or hook is
installed. The immutable sales candidate remains
`dcdff624b8d04911dfb26d4af782c90527a5174f`.

`ops/phase8/trusted_release_adapter.py` reads fixed GitHub refs, GitHub CI run
and same-head jobs, GitHub ancestry, production Git HEAD/status, the diagnostic
hash, service state and stable PID, local and public health, effective service
environment, root-private active-release state, installed artifact bytes, and
root-private recovery records. It recomputes archive hashes, parses the archive's
embedded production SHA and generation, and checks the sidecar, off-host
download hash receipt, and isolated restore record against those bytes. Each
packet is validated by the static Phase 8 gates before use. Missing, stale,
inconsistent, or inaccessible sources stop collection. No caller-supplied
packet can enter the staging adapter.

The guarded adapter reads root-private authority itself and verifies installed
artifact hashes, its own installed path, prestage identity, and a second newer baseline recovery
observation before it asks an injected root executor to claim the release ID
durably and stage the exact candidate. A false claim or any ambiguous stage
result is terminal; a new adapter instance must still be refused by the
executor's durable claim. It then recollects prepromotion identity and
candidate recovery. It returns no deployment, main-promotion, or provider
authorization. No CLI or default executor stages anything.

The separate guarded installation task must review and install a root-owned
executor with an atomic, durable `claim_once` journal and exact-SHA staging
operation, plus independent producers of the Phase 8 active-release and
recovery records. It must review the backup/restore and off-host receipt
producers, ensure the root-only file contract and retention hold, bind the
new adapter hash in the authority, and verify protected installed hashes.
The source file alone grants no release permission. A root executor must
reconcile an ambiguous prior claim before any new release authority or
stage attempt. These records are absent now, so live staging fails closed.

The collector's root-private recovery record contract is per release ID under
`/var/lib/optibrain/phase8/recovery/<release_id>/`, with `baseline-backup.json`,
`baseline-offhost.json`, `baseline-restore.json`, analogous candidate files,
and `forward-recovery.json`. Records are checked against the actual root-owned
archive and sidecar at `/var/backups/optibrain/`. The active-release file is
`/var/lib/optibrain/phase8/active-release.json`. Producers must write those
files only after the corresponding bounded backup, off-host download/hash,
and isolated restore have completed. The collector never creates them.

Read-only live checks on 2026-09-30 confirmed remote main at
`d2ca75d588665112d1d62329abfda23dd92d533f`, the candidate branch at
`dcdff624b8d04911dfb26d4af782c90527a5174f`, production HEAD at the
baseline with only the known diagnostic untracked, service active, and public
health `ok` at version `1.11.0`. An initial public URL probe used a wrong
hostname and failed DNS; source was reconciled against the prior explicit
health URL and a focused recheck passed. No provider or production mutation
was made. Root-private recovery and effective policy are not claimed verified.
