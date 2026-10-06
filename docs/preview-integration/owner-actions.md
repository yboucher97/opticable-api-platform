# OWNER ACTION / PROVIDER CONFIG REQUIRED

This package is a morning configuration proposal grounded in the retained website lane's `github-permissions.md` and `cloudflare-preview.md`. No permission, token, project, workflow, callback or production setting was changed tonight. Existing provider rejection endpoints were not retried.

## GitHub

Install a separate preview GitHub App on **only `yboucher97/opticable-website`**. Runtime minimums from the website audit:

| Capability | Repository permission |
| --- | --- |
| Repository identity | Metadata read |
| Source/ref reads and proposal branch push | Contents write, using separately constrained short-lived installation tokens |
| Draft PR reads/create/update | Pull requests write |
| Checks and commit conclusions | Checks read; Commit statuses read |
| Workflow/job/log observation | Actions read |
| GitHub deployment evidence, if used | Deployments read, optional |

Subscribe to push, pull_request and workflow_run. Configure an HTTPS callback with raw-body HMAC verification, selected installation/repository checks, 64 KiB ingress bound, delivery IDs, durable replay protection and queued bounded reconciliation. Runtime needs no repository webhook-write permission for App delivery; one-time App configuration belongs to the owner.

Main is currently unprotected per retained evidence. Enforce main protections/rules for required checks, reviewed PR merge, no force/direct production push and no runtime bypass. GitHub Contents write has no proposal-prefix-only scope: enforce optimization refs in the executor and protect main independently. If the account cannot enforce that boundary, use an owner-approved isolated preview repository or resolve the protection capability before enabling unattended push.

Audit every GitHub/Cloudflare trigger before the first push. Harden the existing production workflow's manual-dispatch main guard separately where necessary; never use it to build/deploy a proposal preview. Preview runtime needs no Administration, Actions write, Workflows write, Secrets write, DNS or production authority. Any new preview CI must use isolated credentials, exact-head tests and no auto-merge.

## Cloudflare

Missing proof: successful READ of Workers Builds trigger discovery for the active website integration. The retained endpoint returned **401 Invalid token**, code 12006. It did not prove that no trigger exists. The website audit identifies **Workers CI Read**, or its actual supported Workers product-scope equivalent (the audited newer role mapping is Content Read-Only). Confirm the account's available role/scope and validate one successful read tomorrow; do not guess broader grants.

The website is a Worker with static assets. Provision a **separate isolated preview Worker**, proposed name `opticable-optimization-preview` after verifying the name/ownership. Give it no production routes/custom domains, production secrets or writable production bindings. Enable appropriate workers.dev/immutable version preview URLs on that target only. Do not repurpose the shared main-built `opticable-website-preview` validation Worker or enable production Worker version URLs as isolation.

Use a separate upload principal restricted to the pre-provisioned preview Worker. The audited Workers role proposal is Editor on that Worker for version uploads, subject to the account's actual supported resource scoping. If individual Worker scoping cannot be enforced, select an isolated account/resource architecture before runtime writes. Keep one-time provisioning authority outside runtime. No DNS/Workers Routes permission or production Worker editor authority is needed for the preview executor.

Require a preview-only build with tracking disabled, noindex and production-origin canonical URLs. Include nonsecret proposal/revision/repository/base/branch/full-head evidence and artifact digest in `/preview-evidence.json`. Upload one version with exact source annotations and a sanitized alias; retain and validate the immutable version URL and ID. Do not route/deploy that version to production. Use bounded GETs only; do not submit Forms to live intake.

## Minimal remaining actions for the first hosted camera preview

1. Close PR133 production verification/recovery/G004, then rebase and revalidate this integration branch.
2. Establish the scoped preview GitHub App, enforceable main boundary and signed callback; prove all push/PR deployment triggers are safe.
3. Restore effective Builds trigger READ and provision/verify the isolated preview Worker plus its separate upload principal.
4. Validate live adapters, pinned native website build/test policy and preview-only exact-head CI/executor against this contract. Execute one controlled camera preview and verify unchanged production state.

No new credentials are created tonight. No authority is renewed. Production deployment remains a separate future executor with its own exact-revision approval, authority receipt, expiry, idempotency, rollback and read-after-write requirements.
