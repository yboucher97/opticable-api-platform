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

The root deployment wrapper validates the SHA and downloads the deployment script from that exact GitHub commit. The deployment script then verifies that the commit is an ancestor of `origin/main`.

### One-time deploy identity setup

Generate a dedicated SSH key pair on a trusted administrator machine. Do not reuse your normal workstation or root key.

Example:

```bash
ssh-keygen -t ed25519 -f opticable-api-github-deploy -C "github-actions-opticable-api" -N ""
```

Only the **public** key is needed by the server bootstrap.

On the API VM, as root, from a trusted shell:

```bash
curl -fsSL https://raw.githubusercontent.com/yboucher97/opticable-api-platform/main/deploy/bootstrap-deploy-user.sh -o /root/bootstrap-opticable-deploy.sh
chmod 700 /root/bootstrap-opticable-deploy.sh
/root/bootstrap-opticable-deploy.sh 'ssh-ed25519 PUBLIC_KEY_MATERIAL'
rm -f /root/bootstrap-opticable-deploy.sh
```

Never put the private key in the repository.

### Required GitHub Actions secrets

Repository: `yboucher97/opticable-api-platform`

- `OPTICABLE_API_DEPLOY_HOST` — production SSH hostname/IP
- `OPTICABLE_API_DEPLOY_SSH_KEY` — private half of the dedicated deploy-only key
- `OPTICABLE_API_DEPLOY_KNOWN_HOSTS` — trusted SSH host-key line for the VM
- `OPTICABLE_API_DEPLOY_PORT` — optional; defaults to 22
- `OPTICABLE_API_PUBLIC_BASE_URL` — optional; defaults to `https://api01.opticable.ca`

For the known-hosts value, prefer deriving the key from the VM itself through an already trusted administrative session rather than trusting a network scan. For example, on the VM:

```bash
printf 'api01.opticable.ca %s\n' "$(cut -d' ' -f1-2 /etc/ssh/ssh_host_ed25519_key.pub)"
```

### Deployment sequence

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
