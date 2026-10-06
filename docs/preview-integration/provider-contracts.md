# Provider and structured handoff contracts

This lane uses local Git and fake providers exclusively. The new provider module contains no live GitHub or Cloudflare client. Production adapter mutation defaults raise `OWNER ACTION / PROVIDER CONFIG REQUIRED`; the explicit fake-only mutation mode records simulated calls with `provider_writes=0`. It cannot write to an external account.

## Read results

Every port returns a bounded `ReadResult`: state, bounded data, original `source_at`, `observed_at`, attempted/successful/failed counts and reason. Allowed states are COMPLETE, VERIFIED_EMPTY, PARTIAL, FAILED, NOT_COLLECTED, STALE and BLOCKED_AUTH. A successful timestamped read is necessary for complete or verified-empty evidence. Failed data cannot masquerade as successful empty data. HTTP 401/403 is BLOCKED_AUTH, timeout is FAILED, and an exhausted read budget is NOT_COLLECTED. No access-denied retries occur.

Fake provider budgets default to 20 operations, capped at 30; deployment lists are capped at 20 objects and response data at 256 KiB. Reconciliation processes at most three proposals per call; fake HTTP performs at most eight GETs with a 256 KiB response bound. A live port must impose equivalent request timeout, byte, page, retry and operation bounds on the transport itself. Unknown/partial lists cannot prove absence.

## GitHub

Methods: get_repository, get_branch, get_commit, get_pr, get_workflow_status, push_proposal_branch, open_draft_pr, read_webhook_event. Ref/commit results bind repository, branch and full SHA. Workflow results bind repository/branch/full SHA and every proposal-required check. Draft PR observations require exact repository/branch/head/base, positive number and draft status. Missing PR is an explicit verified-empty observation and does not block local fake-provider proof; live graduation additionally requires the reviewed remote CI/PR safety boundary.

No merge, production push, force push, tag, workflow dispatch, settings, credential or rules-management operation is provided. Future live writes need a fresh deployment-trigger safety receipt, selected repository identity, exact proposal-only ref and head, fast-forward rule, idempotency and a separate preview principal.

## Cloudflare

Methods: get_project, get_preview_configuration, list_deployments, find_deployment_for_sha, read_deployment, validate_preview_url. The current website is a **Worker with static assets**, not Pages. An immutable version upload ID can serve as `preview_deployment_id`; adapters must preserve the provider object type and distinguish upload from routed deployment.

Project and configuration evidence must show the exact configured target, `environment=preview`, explicit isolation and no production routes. Deployment evidence must match proposal ID, revision, repository, exact branch/base/head, immutable ID/URL and original source time. Wrong/missing SHA, unknown environment, production branch/environment/hostname, stale source time or inconsistent readback cannot pass. The host policy uses an exact allowlist, never a suffix match.

Hosted validation requires HTTPS, success without redirects, expected page content, noindex, production-origin canonical behavior, exact proposal manifest, CTA and Forms shell where required. It performs GETs only. Forms presence does not prove a submitted inquiry; no form submissions are authorized. An actual adapter must collect the manifest from the expected preview origin and authenticate provider state, rather than trusting a supplied JSON document.

## Events and missed events

`handle_webhook` accepts push, pull_request and workflow_run. A verifier interface validates the signature over the raw body before JSON intake. The HMAC fake fixtures cover valid/invalid signatures. Allowed repository, delivery ID, known kind and a 64 KiB body bound are required. A unique durable delivery ID prevents replay. Only normalized repository/event/hash/reconciliation references are retained; raw webhook command/text fields never become executable instructions.

No callback is installed. At graduation use a TLS receiver with bounded streaming body intake, trusted App delivery/installation context, secret storage outside the journal, durable receipt insertion before acknowledgement and queued reconciliation. Events are hints; authoritative reads settle event order and missed deliveries.

`reconcile` is callable by existing infrastructure later. It checks default/proposal branch, draft PR, exact-head workflow, isolated target configuration, deployment and readback, then bounded HTTP validation. It does not create a timer, fetch network Git objects, mutate a provider or start a new preparation process. Denied/unknown observations keep readiness blocked while independent proposals can be processed within the budget.

## Website report handoff

The checked-in fixture copies the proven website lane's final JSON report, read from the retained worktree without modifying it. `import_website_report` bounds JSON to 128 KiB, checks schema/non-production/proposal/revision/repository/base, and preserves:

- camera proposal commit `a0650b92007f197d68c252363362e2066f9db063`;
- prepared/tested head `2db20ef78fef1f30e5e7a8afaf3d0ac099d4f3d7`;
- later evidence-only final head `91e36b551d61e9b6a8796b24fe3b7222ef99e66e` in fixture provenance;
- original base `fc67ddc8c76b7527a620a93ca216b038f210b895`;
- reported local build/test PASS, Cloudflare BLOCKED_AUTH and owner review BLOCKED.

Import never grants hosted readiness or approval, never adopts the website evidence worktree for mutation, and never treats arbitrary Markdown as state. Imported historical test results are reference evidence; the live readiness tuple requires fresh runner/provider/HTTP receipts. The camera ID is `49d2893d1498325eb5ae8f5a7304d1e3d199d03afcb4c6d0383dd7ed6ab32c17`, revision 2. The original historical branch remains evidence; fresh preparation uses the normalized proposal branch.

## Production executor interface only

`handoff_contract` requires current exact-revision approval/evidence, all required checks, current conflict-free base, rollback SHA, separate scoped authority receipt with matching tuple and expiry, and a digest idempotency key. The contract requires fresh base checks and provider read-after-write verification. It explicitly returns `execution_authorized=false`. No production executor, merge, deploy or rollback implementation exists here.
