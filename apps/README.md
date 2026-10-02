> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](../docs/OPTIBRAIN_CODEX_ONBOARDING.md).

# Apps

Source services live here.

- `workflow-api`: public webhook and orchestration API
- `password-pdf-service`: document generation and WorkDrive delivery
- `omada-site-service`: Omada provisioning worker

Keep shared code out of app folders once it becomes reusable across services. Move that kind of code into a future `packages/` directory instead.
