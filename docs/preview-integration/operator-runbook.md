# Local integration operator runbook

Use a dedicated checkout based on candidate `c22d409d96671e8b78e21ca72a4a76ea4c80879b`; this lane is `integration/local-preview-control-plane-20261006`. No push, PR, merge or deployment is part of the local mission. Production remains API 1.28.0 and PR133 remains pending.

## Local controlled preparation

1. Load the existing canonical website proposal revision. Map `detail.repository` explicitly; never infer repository identity from untrusted text.
2. Reuse one approved clone and observe/fetch incrementally through the provider boundary. Persist RepositoryState as a website SOURCE fact, retaining observed/analyzed SHA and original dates. When the SHA/semantic hash is unchanged, skip expensive analysis/preparation.
3. Construct a preparation package with proposal ID/revision/hash, repository/base SHA, bounded file allowlist, exact replacements, evidence references and required test classes.
4. Configure a private proposal root, expected remote and production-path denylist; install reviewed script/hash/class definitions. Call `prepare_local`. It persists intermediate states, creates the local proposal-only branch/worktree, applies the scope, commits and records per-head build/tests. It never pushes.
5. Call bounded `reconcile` with fake adapters to exercise provider states. For the live lane, first complete the owner configuration and separate adapter validation described in [owner actions](owner-actions.md).
6. Inspect Manager's existing proposal card and WHY/EVIDENCE/CURRENT/PROPOSED/PREVIEW/TESTS/RISK/APPROVAL STATUS package. The URL appears only with current exact-head verified evidence.
7. Record owner intent using existing Manager feedback. APPROVE on a prepared website proposal requires the verified exact preview. Revision, SHA, checks or preview changes invalidate it. Approval expiry defaults to 24 hours; verification evidence must also remain fresh.

Build/test states are NOT_RUN, RUNNING, PASS and FAIL. Required classes can be BUILD, LINT, ROUTES, FR, EN, FORMS, GA4, ATTRIBUTION, LINKS, SCHEMA, ACCESSIBILITY, RESPONSIVE and SECRET_SCAN. Every proposal defines its own subset. No class can select arbitrary command strings. On a failed build/test, retain logs and request a scoped revision. Do not reset dirty worktrees or discard owner changes.

## Blocked provider and stale handling

401/403: retain BLOCKED_AUTH and the original attempted/failed read, display PROVIDER ACCESS REQUIRED, and stop dependent reads. An empty successful result requires a successful, timestamped authoritative read. Timeout is FAILED; exhausted budget is NOT_COLLECTED. Keep old evidence dated and hide unverified URLs.

Default SHA changes: invalidate the preview/approval. Classify CURRENT, NEEDS_REBASE, CONFLICTED or SUPERSEDED using isolated Git comparison when objects are available. Otherwise require incremental fetch before conflict assessment. Do not auto-rebase or merge. Rejected/deferred/revision-requested proposals do not restart during reconciliation.

Archive eligibility is read-only: only clean rejected/superseded worktrees qualify. No deletion is implemented or authorized tonight.

## Validation

Use a dependency-complete Python environment, with the current checkout as source. The existing portable runner strips credentials, blocks networking and puts default outputs in temporary storage:

```bash
python -I ops/phase6/validate.py --suite focused --pattern test_website_preview.py --pattern test_phase37_manager.py --pattern 'test_post37*.py'
python -I ops/phase6/validate.py --suite full
python -I ops/phase15/validate_contracts.py
node --test apps/control-plane-worker/tests/*.test.js
git diff --check
```

The final-night report records the exact executed interpreter and totals. The retained website lane can be imported from its structured final JSON; do not modify that evidence worktree or run its provider commands. The imported report is historical evidence, not a new hosted deployment.

## Morning dependency order — do not execute tonight

1. Finish, merge and deploy PR133 under the existing reviewed release procedure. Record the actual final production SHA/API version; never assume the candidate SHA will be the final merge/generated SHA.
2. Verify G001 bounded collection, G002 collision/source completeness and G003 timer-health behavior in production at that exact release.
3. Create and verify matching encrypted recovery evidence for the final released SHA.
4. Close G004 with that verified production/recovery tuple. This integration branch does not alter its current-state metadata.
5. Update this local integration branch onto final completed main, preserving all local integration commits. After confirming the remote, `git fetch origin`, `git rebase origin/main` and verify candidate fix preservation. Resolve any conflicts in the dedicated integration checkout.
6. Run focused/full regression and documentation validation again. Prepare the integration change for normal owner review/release only after the rebase passes.
7. Configure and independently validate GitHub/Cloudflare preview authority, target isolation, trigger discovery, exact-head CI and callback requirements. Implement/validate live read ports and any separate preview write executor against the reviewed contract; install pinned website build policy. No existing production credential should become the preview credential.
8. Rehydrate camera revision 2, observe current website main, prepare its normalized proposal branch/worktree and exact tested head. After the deployment-safety receipt, perform one proposal-only push/draft PR and one isolated Worker version upload. Collect exact-head CI/provider/manifest/HTTP evidence, verify production deployment IDs remain unchanged, then expose owner review in Manager. Do not deploy production.

No further foundation phase is required for the local control-plane architecture. Proceed to controlled execution graduation after current remediation closure. Provider configuration, live port implementation/validation and the first hosted evidence run remain required execution work.
