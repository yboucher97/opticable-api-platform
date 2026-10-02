# OptiBrain documentation index

Current operation begins with [Codex onboarding](OPTIBRAIN_CODEX_ONBOARDING.md), [architecture](OPTIBRAIN_ARCHITECTURE_BLUEPRINT.md), [master runbook](OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md) and [safety invariants](OPTIBRAIN-SAFETY-INVARIANTS.md). Twelve authoritative current docs are listed in `phase14-documentation-register.json`; the deployment README is their canonical release companion.

| Current contract | Purpose |
|---|---|
| [Runtime matrix](phase14-runtime-matrix.md) | Services, identities, schedulers, flags, bounded monitoring |
| [State-store matrix](phase14-state-store-matrix.md) | Canonical state contracts and historical DB decisions |
| [Provider usage](phase14-provider-usage.md) | Measured efficiency and accounting limits |
| [Retention](phase14-retention-policy.md) | Exact holds, deterministic dry run, local-only cleanup |
| [Deprecations](phase14-deprecation-list.md) | Safe denial-preserving removal and obsolete helper retirement |
| [Recovery](phase14-recovery-runbook.md) | Reconnect/rebuild/cutover/RTO procedure and proof limits |
| [Phase14 report](phase14-final-report.md) | Implementation evidence and root final-certification pointers |
| [Deploy](../deploy/README.md) | Single current guarded release path |

Historical phase records explain past states, not current permission. Original71-document classification/digests remain in [recon register](phase14-evidence/documentation-register.json). Phase14 reconnaissance/plan/runtime/state/code inventories are investigation evidence at their original baseline, not current executable configuration. Their fifteen JSON evidence files are preserved verbatim. Former central runbook/architecture are exact byte copies under `history/phase13-*`; Git history preserves all earlier versions.

Audit/recovery evidence: [Phase13 closure](phase13-final-closure.md), remediation/P1 reports/control/timer matrices and `phase13-evidence`, Phase4/5/6/12 proof, owner offline recovery evidence and backup manifests. Older pending closure statements are resolved by the final Phase13 owner evidence; neither old nor current docs claim unsupported API readback of native Forms integration. Do not delete audit evidence to simplify navigation.

Overlapping design proposals (`architecture.md`, `api-blueprint.md`, `autonomous-automation-platform.md`, `repository-structure.md`) are historical design references. They are not bootstrap/deployment instructions. Use current root receipts/policies and this index to resolve drift; retain older files where tests/lineage/recovery still reference them.
