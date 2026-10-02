> SUPERSEDED — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_DEPLOYMENT_GUIDE.md).

# Phase 14 deprecations and preservation

Reconnaissance commit `1a13a8d41684bb8d40620c829a4e9bda6554ab6a` is an ancestor of implementation. Its six docs and fifteen evidence files remain in Git; promoted onboarding has its original version in that commit. No bad nested paths or blind merge were introduced.

| Component | Decision | Dependency evidence / surviving contract |
|---|---|---|
| `wifi_pdf.zoho_crm.update_generated_password_fields` body after immediate denial | REMOVED unreachable body | Guard dominates every call; public execution contained; read/pipeline/import/recovery interfaces retained |
| `wifi_pdf.workdrive` upload/move/create/resolve mutation bodies after immediate denial | REMOVED unreachable bodies | Same intrinsic guard; no route, timer/workflow can reach the removed statements; interfaces and denial remain |
| `deploy/manual-guarded-release.py` | CANONICAL | Installed root exact-SHA/CI/backup/venv gate; sole current release authority |
| `deploy/bootstrap-deploy-user.sh` | CURRENT restricted identity setup | Installs canonical manual gate; not run in Phase 14, existing SSH key retained |
| `deploy/production-root-command.sh` | DEPRECATED, direct execution refused | Historical embedded Phase 6 verifier preserved for security fixtures/provenance; no active release dependency |
| `deploy/update-production.sh` | DEPRECATED, direct execution refused | Historical cleanliness/rollback fixtures retained; cannot invoke obsolete install path |
| `deploy/phase6-release-loader.py` | ARCHIVED entrypoint | Direct CLI refuses; historical archive validation tests and source remain |
| root `install.sh`, workflow app `install.sh` | DEPRECATED, direct execution refused | Unsafe historical writer defaults/in-place dependency bootstrap; use current rebuild procedure |
| 24 installed historical reconciliation/release aliases (20 one-off Python helpers +4 obsolete sbin entrypoints) | ARCHIVED; direct execution refused | Fresh current-unit/runtime/installed-helper dependency scan found 0 references; exact bytes/hashes retained under `/var/lib/optibrain/phase14/retired-release-helpers`; current runner/backup/recovery imports remain active |
| Previous master runbook / architecture | ARCHIVE exact Phase 13 bytes under docs/history | Current short documents replace live claims; history retains every narrative and recovery reference |
| Three historical DBs | ARCHIVE in place | Still covered by eight-DB backup/restore; no active-reader promotion or deletion |
| Legacy behavioral gates | KEEP safety where still consulted | 23 gates /16 workflow settings reviewed; denial/source/recovery dependencies make count-only deletion unjustified |
| Six persistent development units | KEEP MASKED / INACTIVE | Retirement archive/evidence and full manual sudo preserved |
| Preview Workers / unknown D1/R2 consumers / duplicate inactive Caddy unit | MANUAL REVIEW | Unknown external/recovery dependencies; no destructive removal based on absence of cron |

Static reference evidence is [the reconnaissance source map](phase14-evidence/source-map.json) and [deprecation references](phase14-evidence/deprecation-references.json). Dominating denial makes statements after the guard unreachable even though callers/imports of the retained surface remain. Focused provider-fake/pipeline/containment and full release tests validate the surviving interface. No complete production module or audit family was removed merely to reduce file count.
