# First hosted camera preview — provider preflight

FIRST HOSTED CAMERA PREVIEW: **PARTIAL — existing GitHub App adapter verified; Cloudflare user-read credential required**.

Owner steering after the initial preflight accepts unavailable GitHub protection on the Free private personal repository as an **ACCEPTED PROVIDER/PLAN LIMIT**. GitHub Pro and public visibility are not required. The current execution policy must enforce the selected-repository identity, a single canonical `optimization/*` ref allowlist, exact ID/revision/SHA binding, no force/deletion/merge, draft PR only, no production credentials, and authenticated remote-ref readback. Provider-enforced prevention of direct main writes remains unavailable; application enforcement must be described accurately.

This is the controlled execution mission, not a new numbered phase. Discovery on 2026-10-06 verified the expected clean worktree, branch `execution/first-hosted-camera-preview-20261006`, and starting HEAD `e03bb3dfe5cc603d1c8e378a28490db7dac48723`. No executable, production configuration, authority, timer, or proposal record was changed. This report is preflight evidence, not a hosted preview receipt.

## GitHub configuration

Repository: `yboucher97/opticable-website`, private, personal account owner `yboucher97`.

An authenticated fetch and independent API/Git readbacks confirmed main `fc67ddc8c76b7527a620a93ca216b038f210b895`. Main reports `protected: false`. Both branch protection and ruleset reads returned HTTP 403: “Upgrade to GitHub Pro or make this repository public to enable this feature.” This is now an owner-accepted provider/plan limit. The repository remains private and no plan upgrade will be performed or requested.

Existing App: **OptiBrain Production**, App ID `5077440`, installation `164914980`, all-repository selection. The owner explicitly requires reusing it. Initial discovery used a website-restricted read token including Administration read solely to inspect protection. The candidate live adapter now mints separate ephemeral read/write-capability tokens restricted to repository ID `1179376497`, verifies that `/installation/repositories` contains only the private website and verifies exact minimum permissions. Administration is absent from these adapter tokens. Both effective permission sets were verified through live APIs; no branch or PR was written, no token was persisted, and parent App permissions/installation/key were unchanged.

Preview identity: short-lived tokens from the **existing App**, limited to `yboucher97/opticable-website`. Execution permissions are Metadata read, Contents write, Pull requests write, Actions read, Checks read and Commit statuses read. All other permissions remain ungranted. Application guards enforce the single exact proposal ref under the accepted Free plan limit. There is no force/deletion/merge/dispatch surface in the adapter. No additional App registration, installation, private key or GitHub plan action is required. Existing key `/etc/optibrain/github-app.pem` and nonsecret IDs under `/etc/optibrain/website-preview/` are securely referenced; tokens stay in memory. No production Cloudflare deployment credential is loaded by this GitHub port.

Webhook: **DEFERRED**. API 1.31.0 has no installed HTTP receiver at `/v1/preview/github/webhook`. Leave App webhook Active unchecked; use bounded polling after live adapters are released.

Current workflows were read from fetched main. `build-and-deploy.yml` deploys on filtered main pushes and manual dispatch. Manual dispatch still lacks a main-only job guard. It regenerates and pushes production `dist`, deploys `opticable-website` and the existing shared validation Worker, then runs browser checks. It must never be dispatched for this mission. Non-main proposal pushes do not match its push trigger. `measurement-validation.yml` runs on pull requests with Contents read; it builds and runs measurement/native-success checks, with no deployment step or production deploy secret. Recent unrelated PR runs include failures; no camera-head CI has run and no CI pass is claimed. Required CI context must be confirmed against actual current support before enforcement.

## Cloudflare configuration

Account: `81d07d311d1b51e5e04b451d1f254850`, `Yboucher@opti-plex.ca's Account`; workers.dev subdomain `yboucher`.

Current runtime token is account-owned: account token verification returned HTTP 200/active; user-token verification returned HTTP 401. Token policy readback shows Workers CI Read is already granted. The production Worker-tag Builds trigger read returned HTTP 401/code 12006/Invalid token. The verified cause is the **unsupported account-owned token type**, rather than a missing CI Read grant. Cloudflare's Builds API requires a user-scoped token. The separate existing test token is also account-owned and grants production edit access; it is not a safe preview writer. No identical denied endpoint was retried.

Actual current token policies support Individual Workers Editor/Content Read-Only and Account API Tokens Write. Separate selected-Worker token creation can therefore be prepared through safe APIs after the target is provisioned and the execution boundary is released. Neither existing broad token will become the preview upload identity. Provisioning authority and runtime preview writer must stay separate.

Target `opticable-optimization-preview` is absent from the successful complete Worker inventory. **No target was created, version uploaded, or preview URL registered.** Its required future configuration is empty routes, no custom domains, no external production bindings/secrets and enabled immutable version URLs. The production static ASSETS binding is generated afresh for preview; production secrets must never be copied.

Baseline production deployment: `6ee734f2-c2a8-4b50-a6e8-3fc57ee4dca1`; version `fee39430-14f1-4dac-98f7-aeb716baae9f` at 100%; created `2026-10-05T23:13:41.494036Z`. Final readback confirms the same Worker metadata/deployment and unchanged routes/DNS. The current camera page returns HTTP 200 and matches current main's generated artifact byte-for-byte; production site.js retains its baseline hash. The camera body hash differs from the initial HTTP sample, so that sample is not represented as an unchanged-body receipt. Root-private evidence records both observations and the exact-main artifact comparison. No production write was attempted.

## Camera proposal and OptiBrain

Proposal ID: `49d2893d1498325eb5ae8f5a7304d1e3d199d03afcb4c6d0383dd7ed6ab32c17`.

Canonical live revision: **3**, preserving historical revision 2. Original tested content commit: `a0650b92007f197d68c252363362e2066f9db063`. The normalized local branch `optimization/49d2893d1498325eb5ae8f5a7304d1e3d199d03afcb4c6d0383dd7ed6ab32c17-camera-cta-fr` already points to that commit. Its diff changes only `sitegen.py`: French commercial IP-camera wording, quotation CTA and coverage FAQ. Remote branch and matching PR observations are verified empty. This mission created zero branches, pushed zero branches, created zero PRs and uploaded zero previews. Do not overwrite the existing local identity or replay historical generated artifacts.

Historical worktree `/home/optibrain/worktrees/opticable-website-preview` remains clean at `91e36b551d61e9b6a8796b24fe3b7222ef99e66e` and was read only. Fresh execution worktree `/home/optibrain/worktrees/opticable-camera-preview-live` has not been created.

No fresh camera build or tests ran because the required execution boundary is blocked. Historical local test passes remain reference evidence only. The live journal retains historical prepared head `2db20ef78fef1f30e5e7a8afaf3d0ac099d4f3d7`; this is not a newly prepared mission SHA or hosted proof. There is no fresh proposal head, exact-head CI receipt, immutable preview ID/URL or hosted HTTP SHA verification.

The existing live journal remains `PROVIDER_BLOCKED`, preview `BLOCKED_AUTH`, owner `PENDING`, stale `UNKNOWN`; no PREVIEW_READY or OWNER_REVIEW state was fabricated. Live provider adapters and native pinned website build policy are absent from deployed API 1.31.0. The isolated checkout now contains a bounded existing-App GitHub adapter wired to the existing reconciliation port and proposal-only executor, with adversarial/offline write-boundary tests and authenticated live scope verification. Its native CI requirement is the actual `validate` job; separate local test classes must all pass. The Cloudflare upload adapter and native build policy still require completion. Run full regression and the existing guarded OptiBrain release **before provider execution**. Shell discovery probes are read-only audit helpers, not a permanent preview executor.

The owner-authorized GitHub Free model has candidate proposal execution guards and the verified existing-App port in this isolated checkout. The retained preview tests and new token/transport/ref/path/SHA/readback/draft/CI tests passed full offline regression: **1,801 tests / 1,631 subtests**, zero failures, errors, skips or network attempts. Documentation/configuration contracts passed with 264 documents and zero issues. Candidate code is not deployed or enabled. The only current manual provider prerequisite is recorded in [exact Cloudflare configuration package](owner-configuration.md); neither another App nor a plan upgrade is required.

Production OptiBrain receipt and health confirm API **1.31.0**, executable `9501fe3c52fc80270d8aeaa0684abae297206f25`. Current truth retains G001–G004 RESOLVED, RED 0, PARTIAL_CONTROLLABLE 0, lifecycle truth PASS and Noveco suppression PASS. Original twelve internal scopes, cutoff and expiry remain unchanged; the internal timer is enabled/active. Customer authority remains closed and timer disabled/inactive. Internal/customer historical effects remain 2/12 with zero holds. No authority renewal or effect reset was performed. No new executable recovery was created.

## Resume boundary and remaining owner actions

1. Existing GitHub App reuse and website-restricted token capability are **VERIFIED**. Retain the exact ref/SHA guards and guarded release requirement; no GitHub owner configuration remains.
2. Create a **user-scoped, read-only** Cloudflare token for production Builds trigger discovery: effective Workers CI Read or current Workers product Content Read-Only equivalent, scoped to this account. No CI write, DNS/route write, or production edit grants. Securely store separately and verify one bounded successful trigger read. Account tokens cannot substitute. This read is needed before pushing: GitHub workflow safety alone does not prove Cloudflare Git branch triggers cannot deploy production.

Selected-Worker preview writer creation does not currently require owner UI intervention: safe account APIs and resource scopes are available. Do not ask the owner to create a broad editor token. Target provisioning/upload waits for the verified live execution boundary.

After prerequisites: prepare/retest the existing exact camera proposal, bind canonical revision and current base, push exactly one proposal branch, create exactly one draft PR, require passing exact-head CI, build an attested preview artifact, upload one isolated immutable preview, validate provider/HTTP/page evidence, reconcile through the control plane and expose the owner package. Fetch main and compare production baselines before presentation. Stop before any website merge/deploy.

Mission writes to production website, routes, DNS, Forms, Ads, CRM, Books and customer communications: **0**. The current live page remains `https://opticable.ca/fr/services/systemes-cameras-securite/`. No proposed hosted preview is available for review yet. No further foundation phase is required.

Private evidence directory: `/var/lib/optibrain/first-hosted-camera-preview/`, root-owned 0700 with evidence files 0600. It contains sanitized GitHub/Cloudflare discovery, OptiBrain safety hashes and production readbacks. Credential values, installation tokens and private keys are excluded.

Sources: [GitHub installation token restrictions](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app), [Cloudflare Builds token requirements](https://developers.cloudflare.com/workers/ci-cd/builds/api-reference/), [Cloudflare selected-Worker roles](https://developers.cloudflare.com/workers/authorization/workers/).
