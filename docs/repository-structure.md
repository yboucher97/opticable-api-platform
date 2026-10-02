> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# Repository Structure

This repository is a monorepo. Services are grouped by responsibility, not by branch.

## Branching

- `main` is the canonical branch
- feature work should use short-lived branches
- do not use one branch per app
- do not use one branch per endpoint
- do not use branches to represent environments

## Top-Level Layout

```text
apps/
  workflow-api/
  password-pdf-service/
  omada-site-service/
docs/
  architecture.md
  repository-structure.md
install.sh
README.md
```

## Services

### `apps/workflow-api`

Public API entrypoint.

Responsibilities:

- webhook intake
- payload normalization
- generated vs predefined credential handling
- Zoho OAuth setup
- downstream job orchestration

### `apps/password-pdf-service`

WiFi credential document generation service.

Responsibilities:

- individual PDF generation
- merged PDF generation
- ZIP and text exports
- WorkDrive upload
- optional CRM update

### `apps/omada-site-service`

Omada provisioning service.

Responsibilities:

- site creation
- VLAN/LAN creation
- WLAN group creation
- SSID creation

## Conventions

- service-local implementation details stay inside each app folder
- platform-wide docs stay in `docs/`
- the root installer deploys the full platform from this monorepo
- runtime artifact names may stay backward-compatible even if source folders are renamed
