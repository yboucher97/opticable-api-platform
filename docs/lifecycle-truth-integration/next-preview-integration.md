# Next preview control plane integration

HANDOFF ONLY. Do not execute this during the lifecycle-truth mission. Next branch: `integration/local-preview-control-plane-20261006`, original head `75c6a2b69dcbfc28ccb4eebcedae020c1f4d1738`, original parent `c22d409d96671e8b78e21ca72a4a76ea4c80879b`. Its only unique commit is the preview implementation. Lifecycle truth source `2a90b6c83c578abd6d5bd1eb886f9758d83a024a` and both existing source worktrees remain preserved.

The completed executable main is `902fdab3db92c98ee70e4e0ea14beefbbc3a4bbe`, API1.30.1, recovery `20261006T172050Z`. Fetch actual current main; a subsequent documentation-only merge can be its descendant. Verify the target contains that completed release before replaying only the preview commit. Do not merge the old PR133 candidate or cherry-pick lifecycle truth again.

## Recommended rebase in the existing preview worktree

Run only after a separate preview integration mission begins. Preserve all untracked overnight/provider evidence; do not clean the checkout. The commands verify clean tracked files, the expected branch and original head, and preserve the original commit in a new reference before replay.

```bash
preview_worktree=/home/optibrain/worktrees/optibrain-final-night-preview-integration
git -C "$preview_worktree" status --short
test "$(git -C "$preview_worktree" branch --show-current)" = integration/local-preview-control-plane-20261006
test "$(git -C "$preview_worktree" rev-parse HEAD)" = 75c6a2b69dcbfc28ccb4eebcedae020c1f4d1738
test -z "$(git -C "$preview_worktree" status --porcelain --untracked-files=no)"
git -C "$preview_worktree" branch preserve/local-preview-before-lifecycle-release-20261006 75c6a2b69dcbfc28ccb4eebcedae020c1f4d1738
git -C "$preview_worktree" fetch https://github.com/yboucher97/opticable-api-platform.git refs/heads/main:refs/remotes/origin/main
preview_target=$(git -C "$preview_worktree" rev-parse origin/main)
git -C "$preview_worktree" merge-base --is-ancestor 902fdab3db92c98ee70e4e0ea14beefbbc3a4bbe "$preview_target"
git -C "$preview_worktree" rebase --onto "$preview_target" c22d409d96671e8b78e21ca72a4a76ea4c80879b integration/local-preview-control-plane-20261006
```

If the preservation reference already exists, verify it points to75c6a2b before continuing; do not force-update it. If tracked changes or an untracked-path collision exist, retain them and prepare an isolated review checkout. Resolve conflicts against current production contracts, then `git rebase --continue`; `git rebase --abort` retains the original branch when review cannot resolve a conflict. Do not force-push or enable auto-merge.

The smallest equivalent replay in an isolated review checkout is `git cherry-pick 75c6a2b69dcbfc28ccb4eebcedae020c1f4d1738` from the verified fetched target. Keep the original branch/reference intact and choose the final branch handoff through the normal reviewed workflow; no production checkout is used.

## Conflict and validation requirements

Expected overlap is Manager store/runtime/intelligence and the documentation register. Keep business facts, owner corrections, lifecycle precedence, shared Today/brief/ranking/Sales actionability and the formatted snapshot bounds. Add preview events/stores/hooks within the existing observer. Preserve G001 fair budgets/source dates/last-good, G002 completeness, G003 sampler and G004 current metadata. Recalculate documentation counts while retaining both histories.

Use the repository's next distinct executable feature version, normally1.31.0, with matching API/registration/fixtures/architecture; determine that against fetched main. Give a later preserving release its own immutable evidence directory. Keep the original internal scopes, cutoff, expiry and effects; customer authority remains CLOSED and its timer disabled. No preview release may imply Ads, customer-send, conversion or production-website authority.

Run website-preview tests together with lifecycle truth, Manager, Today, Sales, business observation, post37 completeness/preservation/timer health and closed-policy tests. Then run the authoritative complete offline repository regression and documentation contracts. Record actual totals; require zero failures/errors/skips/network attempts. Revalidate exact PR head/main CI and normal mergeability. No provider mutation or production release is authorized by this handoff.

## Preserved owner configuration requirements

The preview owner package, `75c6a2b:docs/preview-integration/owner-actions.md`, becomes available when that commit is replayed. Its prerequisites were not changed or rechecked in this lifecycle mission:

- A separate GitHub preview App installed only on `yboucher97/opticable-website`, constrained short-lived tokens, Contents/PR permissions, read-only checks/statuses/actions, signed callback/replay protection and enforceable main protection. Audit every push/PR/workflow trigger before any unattended push.
- Successful Cloudflare Workers Builds trigger discovery READ; the retained401 is not proof of no trigger. Verify the supported account/resource role rather than guessing broader permissions.
- A separately provisioned isolated preview Worker and separate upload principal, without production routes, secrets or writable production bindings. Prove enforceable resource isolation; keep provisioning permissions outside runtime.
- Live adapter/build/exact-head CI proof, tracking disabled, noindex, production-origin canonical URLs and exact source/artifact evidence. No Forms submission, production Worker routing or deployment is part of preview validation.

Recommended next controlled execution: rebase/replay and offline verification first. After the owner prerequisites and reviewed live adapters pass, separately authorize one exact camera proposal preview and verify unchanged production state. Production website deployment remains a later exact-revision approval/executor decision. No new foundation phase is needed.
