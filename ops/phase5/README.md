> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](../../docs/OPTIBRAIN_CODEX_ONBOARDING.md).

# Phase 5 campaign tools

Use only the clean `hardening/phase5-business-autonomy-v1` worktree and the exact Phase 4 production baseline `209aac07160e1376381faebd86fb38a18f92582a`.

- `crm_campaign.py` runs the canonical Desired State engine using a GET-only snapshot or a credential-free JSON-lines connector bridge. Its live write surface is restricted to the two exact optional Lead field definitions. Preserve its evidence database after any interrupted write.
- `isolated_drill.py` requires a cold/restored schema-v2 copy with completed work. It preserves source evidence, tests candidate API/worker restart and dedupe, snapshots/restores the resulting DB and checks ambiguous replay denial. It never migrates production.
- `production_provider.py` runs as the existing service identity with privately supplied production environment. It checks exact live noops, creates/verifies the native subscription through the same engine, proves the synthetic authenticated public intake path and separately checks an actual native callback. It never prints credentials or writes CRM records/Books.
- `production_campaign.py --plan --candidate <commit>` prints read-only deployment gates. Root execution requires the same pinned clean candidate and holds the existing normal deployment lock. It reuses Phase 4 source materialization, service readability, backup verification and isolated restore safeguards. It does not update main or expand privileges.

Runtime additions are root-owned under `/etc/optibrain/phase5`, already included in normal backups. The service environment remains root-only. Record-write policy remains observe by default. Native subscription expiry/renewal and unsupported changes require reviewed reconciliation; do not re-run a partially completed deployment as a provider retry.

Root campaign failures leave bounded private evidence and preserve actual source/database/service state. A missing ordinary Zoho callback is reported as a pending gate after backups/off-host/recovery tags; the synthetic hint is not promoted into native proof. Do not create customer/test records merely to cause existing workflow side effects. See the [engineering record](../../docs/OPTIBRAIN_PHASE5_ENGINEERING_RECORD.md) before any recovery action.
