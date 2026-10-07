# Migration preparation and final synchronization

RECOVERY — CURRENT SPECIALIZED GUIDE. There is no new VPS in this mission. Old production remains active at `148.113.249.7`; original internal scopes continue under existing authority. Customer authority/timer remain closed. Nothing here authorizes source-host freezing, routing changes or writer activation today.

A future migration uses `restore --migration` on the replacement while the old host continues observation. Validate private API/Manager/authentication, exact release, all databases/knowledge, closed authority, providers, systemd/proxy/firewall, storage and a new encrypted backup. Compare the bounded source/target performance baselines. Review `/var/lib/optibrain-rebuild/result.json`; resolve any critical blocker before scheduling the final window.

For final synchronization, the source operator records before-state and invokes the existing reviewed writer-stop helpers under that future cutover mission, then stops observation schedules so no new receipt/audit chronology is created during capture. Preserve invocation journals and uncertain provider effects. Stop the API/PDF/Omada source services for the final short window as well: an observer freeze alone does not prevent new inbound receipts. Wait for in-flight services to end and verify listeners/intake are closed. Keep the replacement privately validated and ready first to bound this brief downtime. Capture a new online recovery with `--preserve-existing`, run the existing encrypted uploader and independent download-hash readback, then export its snapshot catalog. Do not copy live SQLite files or invent replication.

Record a root-owned 0600 source freeze receipt with `old_host`, aware UTC `frozen_at`, `writers_off:true`, `observers_off:true`, `intake_off:true`, `source_sha`, and the final `recovery_generation`. It must describe actual readbacks, not merely requested commands. Generation must be after freezing, and the receipt must be no older than one hour when the target uses it. Transfer the new catalog/archive/freeze receipt privately through the existing owner decryption boundary.

On the replacement:

```bash
sudo bash /recovery/toolchain/ops/rebuild/bootstrap.sh final-sync --manifest /recovery/toolchain/docs/rebuild/current-host-manifest.json --catalog /recovery/final-catalog.json --archive /recovery/final-recovery.tar.gz --generation latest-verified --migration --freeze-receipt /recovery/source-freeze.json
```

The target stops contained apps/schedules, stages and verifies the new generation, compares immutable envelopes/events/learning/priority revisions against its previous generation, checks unchanged exact source, and switches only its own proven bind mounts. Both generations survive. An application release change during the window stops synchronization and requires a reviewed compatible manifest/source plan. The operation revalidates private health/providers/backups and produces fresh action evidence. Partial sync stays contained and retains its exact pending generation. A shared nonblocking lock serializes restore, verification and final sync. Interrupted unmounts accept only proven old/new mounts or empty targets on rerun; never delete a generation to retry.

The final public switch is separately owner-approved: [cutover](cutover.md). If source collection resumes while approval is pending, the final recovery is stale and must be repeated. Avoid two observation schedulers and any overlapping effect executors. Retain the old host frozen for rollback and independently reconcile provider effects newer than each archive.

Use `migration-plan --old-host OLD --new-host NEW --dns-state PRIVATE_JSON --recovery GENERATION --output PRIVATE_PLAN` to bind hosts, exact DNS before/proposed state, recovery, rollback and retention. This command prepares JSON; it has no DNS mutation adapter.
