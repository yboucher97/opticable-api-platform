# Deploy

Deployment assets for the monorepo can live here when they apply to the whole platform.

Current note:

- the root `install.sh` remains the canonical Linux bootstrap entrypoint because it is convenient to fetch directly with `curl`

Service-specific deployment files stay inside each service folder under `apps/*/deploy/`.


## Production workflow API deployment

The workflow API has a validation-gated, rollback-safe deployment path.

Files:

- `deploy/update-production.sh` — validates an exact main-branch commit in a temporary worktree, updates only the workflow API, restarts it, health-checks it, and rolls back on failure.
- `deploy/bootstrap-deploy-user.sh` — creates a restricted `opticable-deploy` SSH identity that cannot open a shell or run arbitrary remote commands.
- `.github/workflows/deploy-api-platform.yml` — deploys only after the `Validate API Platform` workflow succeeds on `main`.

### Trust model

The GitHub Actions private key should **not** be a normal root SSH key.

The bootstrap creates a forced-command SSH account. Its authorized key is restricted with:

- no interactive shell
- no PTY
- no agent forwarding
- no TCP port forwarding
- no X11 forwarding
- no user rc
- one forced deployment command

The only accepted request is:

`deploy <40-hex-commit-sha>`

The reviewed root wrapper fetches only the fixed repository's current remote `main` into a private bare Git repository, checks exact SHA equality, and only then materializes and executes its deployment script. Caller-controlled Git configuration and the writable production repository are excluded from this trust decision. During a staged Phase 6 release, a root-private release marker also rejects delayed workflows targeting another SHA.

For Phase 6, automatic deployment is reconciliation only: the exact candidate must already be running following the separately authorized staged campaign. A fresh Phase 6 checkout switch through the ordinary SSH deployment path is refused. See [the Phase 6 recovery supplement](../docs/OPTIBRAIN_PHASE6_GATE_G_RECOVERY.md). The inherited rollback flow below applies to earlier releases; it is not a Phase 6 rollback authorization.

### One-time deploy identity setup

Generate a dedicated SSH key pair on a trusted administrator machine. Do not reuse your normal workstation or root key.

Example:

```bash
ssh-keygen -t ed25519 -f opticable-api-github-deploy -C "github-actions-opticable-api" -N ""
```

Only the **public** key is needed by the server bootstrap.

Only after separate administrative approval, use a complete, verified release source bundle containing both `deploy/bootstrap-deploy-user.sh` and its adjacent `deploy/production-root-command.sh`. The bootstrap fails before changes if the reviewed wrapper is missing. The following changes privileged state and must not run during engineering readiness:

```bash
# Run from the reviewed immutable source bundle; preserve the existing key policy.
bash deploy/bootstrap-deploy-user.sh 'ssh-ed25519 PUBLIC_KEY_MATERIAL'
```

Never put the private key in the repository.

### Required GitHub Actions secrets

Repository: `yboucher97/opticable-api-platform`

- `OPTICABLE_API_DEPLOY_HOST` — production SSH hostname/IP
- `OPTICABLE_API_DEPLOY_SSH_KEY` — private half of the dedicated deploy-only key
- `OPTICABLE_API_DEPLOY_KNOWN_HOSTS` — trusted SSH host-key line for the VM
- `OPTICABLE_API_DEPLOY_PORT` — optional; defaults to 22
- `OPTICABLE_API_PUBLIC_BASE_URL` — optional; defaults to `https://optibrain.opticable.ca`

For the known-hosts value, prefer deriving the key from the VM itself through an already trusted administrative session rather than trusting a network scan. For example, on the VM:

```bash
# Use the independently verified SSH host; it need not equal the API hostname.
printf '%s %s\n' 'REVIEWED_SSH_HOST' "$(cut -d' ' -f1-2 /etc/ssh/ssh_host_ed25519_key.pub)"
```

### Inherited deployment sequence (before Phase 6)

1. Push/merge to `main`.
2. `Validate API Platform` compiles and tests the workflow service and shell deployment scripts.
3. Only a successful validation run triggers `Deploy API Platform`.
4. The GitHub runner connects using the deploy-only SSH key.
5. The VM validates the requested SHA belongs to `origin/main`.
6. A temporary worktree + temporary virtualenv is built.
7. Python compilation and unit tests run against the target.
8. Only then is the production checkout switched.
9. Production dependencies are updated.
10. Only `opticable-workflow-api` is restarted.
11. The local health endpoint is checked repeatedly.
12. On failure, the previous commit and dependencies are restored and the service is restarted.
13. GitHub performs a public health check after successful remote deployment.

This intentionally does **not** reinstall the PDF service, Omada service, Caddy, firewall, OAuth credentials, or other VM configuration on routine application deployments.

For Phase 6, backup, restore, encrypted off-host verification and staged health gates precede main promotion. CI then validates main and the forced-command deployment reconciles the already-running exact SHA without a checkout change or restart. Public health must report the version declared by that exact source tree. No deploy-only SSH command authorizes provider writes or customer sends.
