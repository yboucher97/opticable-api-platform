# Owner configuration — existing App and GitHub Free preview boundary

The owner's current instruction authorizes reuse of **OptiBrain Production**, App ID `5077440`, installation `164914980`, account `yboucher97`. Do not create another App, alter this installation, upgrade GitHub or make the website public. GitHub Free's unavailable protection is an **ACCEPTED PROVIDER/PLAN LIMIT**. Application guards enforce the preview boundary; provider-enforced direct-main prevention remains unavailable.

## Verified GitHub configuration

The existing installation selects all repositories. The bounded adapter reduces every short-lived installation token to repository ID `1179376497`, private repository `yboucher97/opticable-website`. Readback of `/installation/repositories` must contain exactly that one private repository. Read tokens grant Metadata, Contents, Pull requests, Actions, Checks and Commit statuses read. Write tokens change only Contents and Pull requests to write. No Administration, Secrets, Environments, Actions write, Workflows, Deployments write or organization permissions are requested.

The candidate adapter successfully verified both effective token permission sets through the live APIs, using the existing root-owned key `/etc/optibrain/github-app.pem` without modifying it. Nonsecret IDs are read from `/etc/optibrain/website-preview/github-app-id` and `github-installation-id`. Installation tokens remain in memory, expire within approximately one hour, are refreshed only when necessary and are never serialized. The broad parent installation is disclosed rather than represented as a narrowly installed App. The adapter verifies effective token scope separately from parent App scope.

Live readback confirmed main `fc67ddc8c76b7527a620a93ca216b038f210b895`, the expected proposal ref absent and matching PR inventory empty. This verification issued **zero branch writes and zero PR writes**. Sanitized proof is stored root-private at `/var/lib/optibrain/first-hosted-camera-preview/github-live-adapter-verification.json`.

`website_preview_execution.py` and `website_preview_github_live.py` bind the complete canonical proposal ID/revision/hash/repository/base/branch/head tuple. They reject foreign repositories, main/master and every non-allowlisted ref before provider calls. Writes require current exact-head build/test evidence, reviewed source paths/content, a clean registered worktree, fresh boundary evidence and current main. Publication uses a fixed non-force refspec; authenticated readback must match the exact SHA. PR creation uses base main, the exact proposal branch, a draft and no auto-merge. Existing mismatched branches or PRs fail; exact execution replay creates neither a second branch nor a second PR. Neither adapter exposes merge, deletion, force push, workflow dispatch or production deployment.

Native CI is the actual `validate` job in `measurement-validation.yml`, bound to the exact proposal SHA and branch. Local required test classes remain separately attested; a single CI job is never relabeled as all local tests. Reconciliation requires a real open draft PR for this live adapter. Existing adversarial tests remain intact.

Webhook: **DEFERRED**. The live receiver is not installed or validated. Bounded polling is sufficient for the first preview. Do not enable or change the production App webhook for this mission.

## Remaining manual Cloudflare action

The existing account-owned token has Workers CI Read but the Builds API rejects its token type. A user-owned read token is required to inspect production Git integration before any proposal push: unknown branch triggers cannot be assumed safe. The owner must create this credential in the user profile; account-token APIs cannot create user-owned credentials. Do not repeat the denied account-token call.

OWNER ACTION REQUIRED

SYSTEM:
Cloudflare

ACTION:
Create one user-owned read-only token for Workers Builds trigger discovery. Store it securely on this host at `/etc/optibrain/website-preview/cloudflare-trigger-read.token`, root:root, mode 0600. Do not paste the token into chat.

EXACT UI PATH:
Cloudflare Dashboard → profile icon → My Profile → API Tokens → Create Token → Create Custom Token: https://dash.cloudflare.com/profile/api-tokens

EXACT VALUES:
Token name: `OptiBrain Preview Trigger Read`.
Account: `Yboucher@opti-plex.ca's Account` — `81d07d311d1b51e5e04b451d1f254850`.
Permission: Workers product scope → **Content Read-Only**. If the UI still shows legacy permissions, use Account → **Workers CI → Read**. The current Workers role documentation identifies these as equivalents. No write permission is required for the list-triggers endpoint.
Account resources: Include → Specific account → the account above.
Credential destination: `/etc/optibrain/website-preview/cloudflare-trigger-read.token`, root:root 0600.

CHECKBOXES:
Select only the specified account and the read-only permission. No zone resources or edit grants.

DO NOT ENABLE:
Account-owned token creation, Workers Builds Configuration Edit, Workers CI Write, Workers Editor/Admin, DNS write, Workers Routes write, or any production deployment/edit authority.

After credential intake, verify user-token identity/scopes, then issue one bounded trigger-discovery read using production Worker tag `e3fc5eaa3a46499893264f7805709d8e`. Inspect actual repository/branch/deploy rules before allowing publication. A denied or partial read remains non-ready.

## Automatic work after credential verification

Provision exactly `opticable-optimization-preview` using separate one-time provisioning authority after the guarded adapter release. Create a distinct writer with **Individual Workers Editor only** on that Worker's immutable tag using the supported selected-resource token API. No broad production token becomes the preview runtime writer. The target must have zero routes/custom domains, no copied production secrets or external production bindings, and an isolated static-assets binding generated for this preview.

Finish the bounded Cloudflare transport and pinned native build policy, then run final full regression and the existing guarded OptiBrain release before provider writes. The candidate GitHub adapter has been verified, but is **not deployed or enabled** in API 1.31.0. Current timers, original authority, effects and proposal state remain unchanged. No foundation phase is needed.

Sources: [GitHub installation token downscoping](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app), [Cloudflare user-token requirement](https://developers.cloudflare.com/workers/ci-cd/builds/api-reference/), [read-only trigger API](https://developers.cloudflare.com/api/resources/workers_builds/subresources/triggers/methods/list/), [current Workers roles](https://developers.cloudflare.com/workers/authorization/workers/).
