# Authoritative documentation index

AUTHORITATIVE CURRENT. Only the ten primary documents below define current operation. Read in order: **CURRENT ONBOARDING → CURRENT ARCHITECTURE → CURRENT RUNBOOK → CURRENT SPECIALIZED GUIDE → CURRENT MATRICES → HISTORICAL EVIDENCE**. Latest manual owner scope and trusted root safety policy govern authority; documents cannot enable writes. Current root receipts/provider truth govern observed state. Historical phase claims never override this set.

| Current document | Responsibility |
|---|---|
| [Codex onboarding](OPTIBRAIN_CODEX_ONBOARDING.md) | First15min; identity, safety and exact read-only inspection |
| [Architecture](OPTIBRAIN_ARCHITECTURE_BLUEPRINT.md) | System/provider/ownership boundaries |
| [Master runbook](OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md) | Daily engineering contract and incident routing |
| [Owner/operator](OPTIBRAIN_OPERATOR_GUIDE.md) | Today, health interpretation and emergency stop |
| [Deployment](OPTIBRAIN_DEPLOYMENT_GUIDE.md) | Sole guarded release/receipt/rollback procedure |
| [Recovery](OPTIBRAIN_RECOVERY_GUIDE.md) | Sole fresh-host/backup/snapshot recovery procedure |
| [Configuration](OPTIBRAIN_CONFIGURATION_INVENTORY.md) | Sources/precedence/secret references/owner dependencies |
| [Runtime/health](OPTIBRAIN_RUNTIME_CONTRACT.md) | Services/timers/ports/readiness contract |
| [State/identity](OPTIBRAIN_STATE_CONTRACT.md) | Canonical writers, stores, lineage/replay safety |
| This index | Precedence, classification and evidence routing |

Supporting security control: [safety invariants](OPTIBRAIN-SAFETY-INVARIANTS.md). Machine matrices: [configuration register](optibrain-configuration-register.json) and [complete document register](optibrain-documentation-register.json). Release/health schema is defined in deployment/runtime and read from `/var/lib/optibrain/releases/current.json`; never hard-code “latest SHA” into multiple guides.

## Historical archive and evidence

The complete machine register classifies **every** repo document/README and docs JSON as AUTHORITATIVE CURRENT, RECOVERY, SECURITY / CONTROL, AUDIT EVIDENCE, HISTORICAL, SUPERSEDED or OBSOLETE. UNKNOWN is prohibited. It records purpose/superseder, not stale instruction authority. Original phase content remains available beneath explicit historical/superseded banners. Byte-preserved original archive files under `history/` and JSON evidence retain original hashes/content; this index/register supplies their classification.

| Family | Useful for | Current superseder |
|---|---|---|
| Phases1–2 backup/R2/root bootstrap | Original backup format/access/owner proof, old procedures as evidence | Recovery + configuration |
| Phases4–7 architecture/campaign/canary/gates | Decision rationale and tests of containment/effect fencing; **no current canary grant** | Architecture + runbook + safety controls |
| Phases8–12 intake/lifecycle/operations/autonomy | Schema lineage, synthetic IDs and prior validation | State + runtime + operator |
| Phase13 audits/remediation/control/timer/owner closure | Historical safety findings, key rotation and native Forms owner confirmation | Current safety/config/runbook; native UI evidence limit retained |
| Phase14 recon/implementation/provider/retention/final records | Measured efficiency, storage holds, prior release results | Current guides/matrices; retained audit evidence |
| Old architecture/api/repository/Omada/Google design proposals and app install READMEs | Original design/compatibility fixtures | Architecture + deployment + recovery |
| Old root/deploy/docs README entry points | Navigation only; obsolete instructions superseded | Onboarding / current deployment / this index |

[Phase15 rebuild evidence](phase15-rebuild-evidence.md), [fresh onboarding validation](phase15-onboarding-validation.md) and [final report](phase15-final-report.md) are audit evidence of this mission, not additional competing procedures. Phase1–14 history is optional context; no current operation/rebuild step requires reading it.

## Generated versus versioned evidence

Version in Git: concise current contracts, reviewed bootstrap/restore/inspection/sampler code, secret-reference/classification matrices and sanitized proof summaries. Root-only runtime: credential-bearing source state, per-record protected IDs/versions, immutable action/reconciliation evidence, release/backup/upload receipts. Back up those root/app stores with protected app archives and encrypted off-host copies; retain independent locked R2 claims separately.

Temporary private staging: extracted archives/package/download/build logs and isolated credentials, removed after proof while receipts/hashes survive. Historical archive: useful original phase reports/schema evidence and complete Git history. Do not commit raw live environments, customer payloads, extracted SQLite DBs, archive bytes, process dumps, transient sampler noise or an offline AGE identity. No `git clean` on production; do not delete recovery/audit state to simplify the tree.
