# Verified recovery and knowledge preservation

RECOVERY — CURRENT SPECIALIZED GUIDE. The [catalog](recovery-catalog.json) records `20261007T030438Z`, API `1.34.1`, source `be8cdfe2b36b562ba9e2a57484d8a3d2e8c92caa`, plaintext SHA256 `1005074668c9b5e60bed640eae008d36301accfe842b4e74fc8ac4ab97baec48`, and ciphertext SHA256 `70422eed74ff52da3f020dd2e2193b1a0dababecc7b8c9d1fd01cbca970a0669`. Selection requires independently downloaded ciphertext verification and a compatible reviewed source/format. The newest filename is insufficient. An explicit `--generation YYYYMMDDTHHMMSSZ` pins a generation.

Export a fresh catalog through this read-only source-host operation, after an existing backup/upload has verified:

```bash
sudo python3 -B ops/rebuild/cli.py catalog --archive /var/backups/optibrain/optibrain-backup-GENERATION.tar.gz --upload-state /var/lib/optibrain/phase2a/state.json --workspace /dev/shm --output /PRIVATE/catalog.json
```

The exporter reads one copied database at a time and records all present schemas, tables, counts, primary-key hashes, row hashes and audit chains. The output is nonsecret metadata. Trust it through authenticated transfer from the source host or an exact reviewed repository release. Never replace it with an unauthenticated catalog downloaded from an arbitrary URL.

Download the selected encrypted object and its independently verified descriptor to the owner device using existing scoped R2 recovery access. Check ciphertext hash/size before offline AGE decryption; verify the resulting plaintext hash. Transfer only the verified plaintext archive/catalog through encrypted SSH into private target staging. The current generation has ciphertext/readback and component restore proof; owner offline decryption of this exact generation has not been claimed. The earlier golden decryption proof does not automatically certify every later archive.

The restore engine checks archive traversal, duplicate names, links, unsupported types, generation, source/API identity, complete file coverage, metadata modes/named owners and hashes. It normalizes the existing backup-v1 benign metadata `/.` suffix. It never extracts over `/`. All databases validate before promotion, and the core online snapshot supersedes WAL/SHM. Bad hashes, missing stores, foreign-key errors, unexpected schema/count/identity changes or a broken audit chain stop the operation.

| Persistent intelligence | Canonical recovery location |
|---|---|
| Core events, workflow runs, checkpoints, idempotency, approvals/audit | `automation.db` |
| Decision Card inputs, priorities, proposal/asset revisions | `phase12-autonomy.db`: `optimization_records`, `action_envelopes`, `action_evidence`; cards derive from exact source |
| Business Events and owner corrections | `manager_events` including `source=OWNER`; `manager_feedback` |
| Todos and priority transitions | Immutable `action_evidence`; lifecycle/Manager projection reconstructs the view |
| Action Evidence Envelopes and evidence bundles | `action_envelopes`, hash-chained `action_evidence`, root evidence files |
| Learning Records and outcomes/baselines | `manager_learning`, immutable proposal/action evidence and referenced root artifacts |
| CRM/Books relationships | `manager_links`, root operations crosswalk, finance/recurring links and confirmations |
| Source health and research history | `acquisition_sources`, facts/snapshots/timeseries, `provider_usage`, root observations |
| Website preview state | `website_preview_observations`, `website_preview_webhooks`, root preview/source evidence |
| Customer lifecycle and effect fences | Root `/var/lib/optibrain/{lifecycle,customer-communications,conversion-export}` plus local immutable journals and external R2 claims |
| Forms/mail chronology and future document intelligence | Receipt/intake stores, root evidence; future tables/files discovered automatically; large documents stay in WorkDrive |

The selected recovery contains 51 distinct persisted priority identities (286 revisions), 34 distinct proposals (76 revisions), 116 phase12 envelopes, 603 phase12 audit events, 547 Manager events, three owner fact corrections, 109 preview observations, zero Manager feedback and **zero Learning Records**. These are recovery-snapshot counts, not assertions that current production remains frozen. Every table's exact reference is in the catalog. The live active-priority projection is derived, evolves during observation, and must be regenerated/reconciled from retained facts; historical stored priority identities are the strict preservation assertion.

Future nonzero Learning Records require no count constants or special migration: every table's rows/IDs/hash are compared. Final synchronization additionally requires immutable historical rows to be a subset of the final snapshot. Missing newer provider effects cannot be solved by SQLite restoration; read independent locked R2 claims and provider truth before any eventual execution authority.

All restored approvals/queued jobs remain evidence. Closed root policies, final EnvironmentFile overrides, service masks and disabled worker boot prevent stale execution. No approval pin, expiry, source registration or recovered timestamp enables a provider effect.
