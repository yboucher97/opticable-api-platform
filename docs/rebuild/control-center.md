# Future recovery status integration

AUTHORITATIVE CURRENT — DATA CONTRACT ONLY. Owner Control Center is NOT BUILT in this mission.

Ingest `/var/lib/optibrain-rebuild/result.json` using [result.schema.json](result.schema.json), original release/backup readback receipts and the existing Action Evidence tables. Display last backup, last component restore test, last full fresh-host drill, recovery generation/hash, application and tooling SHA, dynamic database health, learning count/hash/IDs, audit verification, provider health and recovery confidence. A missing/full-drill timestamp is unknown, never PASS.

Show source-generation snapshot counts alongside current source counts; do not treat natural evolution as restoration loss. Expose exact blockers and owner-held key/reauthorization dependencies. Cutover readiness requires every critical check and fresh target-created backup verification. Traffic approval and provider write authority are separate records. Link technical readback/rollback evidence; never surface secret contents, mail bodies or private model reasoning.

Publish neither this model nor any internal database publicly. Future UI must use the established verified owner identity and normal Access boundary. Do not build another audit or authorization platform around this status file.
