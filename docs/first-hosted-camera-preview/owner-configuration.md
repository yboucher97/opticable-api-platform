# Owner configuration — existing App and GitHub Free preview boundary

The owner's current instruction authorizes reuse of **OptiBrain Production**, App ID `5077440`, installation `164914980`, account `yboucher97`. Do not create another App, alter this installation, upgrade GitHub or make the website public. GitHub Free's unavailable protection is an **ACCEPTED PROVIDER/PLAN LIMIT**. Application guards enforce the preview boundary; provider-enforced direct-main prevention remains unavailable.

## Verified GitHub configuration

The existing installation selects all repositories. The bounded adapter reduces every short-lived installation token to repository ID `1179376497`, private repository `yboucher97/opticable-website`. Readback of `/installation/repositories` must contain exactly that one private repository. Read tokens grant Metadata, Contents, Pull requests, Actions, Checks and Commit statuses read. Write tokens change only Contents and Pull requests to write. No Administration, Secrets, Environments, Actions write, Workflows, Deployments write or organization permissions are requested.

The candidate adapter successfully verified both effective token permission sets through the live APIs, using the existing root-owned key `/etc/optibrain/github-app.pem` without modifying it. Nonsecret IDs are read from `/etc/optibrain/website-preview/github-app-id` and `github-installation-id`. Installation tokens remain in memory, expire within approximately one hour, are refreshed only when necessary and are never serialized. The broad parent installation is disclosed rather than represented as a narrowly installed App. The adapter verifies effective token scope separately from parent App scope.

Live readback confirmed main `fc67ddc8c76b7527a620a93ca216b038f210b895`, the expected proposal ref absent and matching PR inventory empty. This verification issued **zero branch writes and zero PR writes**. Sanitized proof is stored root-private at `/var/lib/optibrain/first-hosted-camera-preview/github-live-adapter-verification.json`.

`website_preview_execution.py` and `website_preview_github_live.py` bind the complete canonical proposal ID/revision/hash/repository/base/branch/head tuple. They reject foreign repositories, main/master and every non-allowlisted ref before provider calls. Writes require current exact-head build/test evidence, reviewed source paths/content, a clean registered worktree, fresh boundary evidence and current main. Publication uses a fixed non-force refspec; authenticated readback must match the exact SHA. PR creation uses base main, the exact proposal branch, a draft and no auto-merge. Existing mismatched branches or PRs fail; exact execution replay creates neither a second branch nor a second PR. Neither adapter exposes merge, deletion, force push, workflow dispatch or production deployment.

Native CI is the actual `validate` job in `measurement-validation.yml`, bound to the exact proposal SHA and branch. Local required test classes remain separately attested; a single CI job is never relabeled as all local tests. Reconciliation requires a real open draft PR for this live adapter. Existing adversarial tests remain intact.

Webhook: **DEFERRED**. The live receiver is not installed or validated. Bounded polling is sufficient for the first preview. Do not enable or change the production App webhook for this mission.

## Verified Cloudflare credentials and remaining production-linked trigger exception

The owner completed credential setup and explicitly authorizes reusing the broader **user-owned** token at `/etc/optibrain/website-preview/cloudflare-builds-user.token`. Its account grants are Workers CI Edit and Workers Scripts Edit for `81d07d311d1b51e5e04b451d1f254850`. The existing root-owned file is mode 0640, group `opticable-workflow-api`, inside the root-private directory. Do not duplicate, replace, downgrade or require the previously requested filename. The checkpoint's read-only recommendation is superseded by the owner's explicit permission choice. The existing account-owned `/etc/optibrain/cloudflare-test-token` remains distinct and is used only with supported account-scoped APIs.

Programmatic verification passed HTTP 200 / success true / no error codes for `/user/tokens/verify`, exact account identity, Workers script metadata and the production Worker-tag Builds triggers endpoint. The original account-token Invalid token cause is resolved by using the supported user token. GitHub App reuse and effective website-only token scopes are also reverified. Website main remains `fc67ddc8c76b7527a620a93ca216b038f210b895`.

Discovery exposed an existing **production-linked** non-production Builds trigger: `0a7fcf36-1a8a-4adf-8c04-03a7b517938d`, **Deploy non-production branches**, attached to `opticable-website`, Worker tag `e3fc5eaa3a46499893264f7805709d8e`. It includes `*`, excludes only `main` and runs `npx wrangler versions upload`. Pushing the proposal would therefore upload a version to the production Worker outside this mission's allowed target. The main trigger is separate (`66679014-4b6f-4b6f-b5d3-b4656d9c425b`) and runs `npx wrangler deploy` only for main.

The current authorization permits writes to the isolated preview target and explicitly forbids changing the production Worker. Editing its attached non-production Builds configuration requires a specific owner exception to that production boundary. The exact minimal proposed API change is prepared in [reviewable exclusion plan](production-build-trigger-exclusion.json), **not applied**. It changes only `branch_excludes` from `["main"]` to `["main", "optimization/*"]`; production main builds, other branch behavior, commands, Worker code/versions/bindings, routes and DNS stay untouched. No replacement credential is needed. Workers documentation does not establish a per-commit skip mechanism that can be relied upon here while still running exact-head GitHub PR CI.

The candidate read-only `CloudflarePushSafety` adapter uses the canonical existing token, checks account/Worker/repository identity and branch filters, and fails before GitHub token issuance or branch publication if an automatic Worker write matches. On a safe receipt it must inspect every Worker trigger, with bounded reads and a 30-second cache. It exposes no trigger mutation/upload/token-creation operation. Focused containment tests pass; full regression passes **1,813 tests / 1,658 subtests**, zero failures/errors/skips/network attempts. This code remains an unreleased local checkpoint.

The live 1.31.0 preview journal was updated through its existing contract: successful authentication is recorded separately; state remains `PROVIDER_BLOCKED`, preview `FAILED`, owner `PENDING`, no verified URL. The exact reason is `PRODUCTION_BUILDS_TRIGGER_MATCHES_PROPOSAL`. No authentication blocker is fabricated and no PREVIEW_READY is claimed.

OWNER ACTION REQUIRED

SYSTEM:
Cloudflare

ACTION:
Authorize OptiBrain to apply the prepared one-field exclusion to the production Worker's attached non-production Builds trigger. Your hard stop on production Worker changes is why this specific exception is required. No new credential or App is needed.

EXACT UI PATH:
For inspection: Cloudflare Dashboard → Workers & Pages → `opticable-website` → Settings → Build → Branch control. No dashboard edit is required if you authorize the exact API change here.

EXACT VALUES:
Account: `81d07d311d1b51e5e04b451d1f254850`.
Worker: `opticable-website`.
Non-production trigger: `0a7fcf36-1a8a-4adf-8c04-03a7b517938d` — `Deploy non-production branches`.
One changed field: `branch_excludes = ["main", "optimization/*"]`.
Existing production main trigger: unchanged.
Reply: `Authorize only this non-production Builds exclusion, then continue the existing camera preview mission.`

CHECKBOXES:
No checkbox change required for the API exclusion. Keep production branch `main`; retain other existing settings.

DO NOT ENABLE:
A new credential/App, repository public visibility, auto-merge, production upload/deploy, routes/DNS changes, or the irreversible Switch to Worker Previews migration.

## Automatic work after credential verification

Provision exactly `opticable-optimization-preview` using separate one-time provisioning authority after the guarded adapter release. Reuse the verified credentials without duplicate token creation. Verify preview write authority against the existing owner constraints and supported selected-Worker boundary before upload; retain a fixed exact-target adapter and keep production deployment credentials out of the preview process. The target must have zero routes/custom domains, no copied production secrets or external production bindings, and an isolated static-assets binding generated for this preview.

Finish the bounded Cloudflare transport and pinned native build policy, then run final full regression and the existing guarded OptiBrain release before provider writes. The candidate GitHub adapter has been verified, but is **not deployed or enabled** in API 1.31.0. Current timers, original authority, effects and proposal state remain unchanged. No foundation phase is needed.

Sources: [GitHub installation token downscoping](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app), [Cloudflare user-token requirement](https://developers.cloudflare.com/workers/ci-cd/builds/api-reference/), [read-only trigger API](https://developers.cloudflare.com/api/resources/workers_builds/subresources/triggers/methods/list/), [current Workers roles](https://developers.cloudflare.com/workers/authorization/workers/).
