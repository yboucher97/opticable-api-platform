# Phase 13 manual P0 remediation

This follows the independent audit on 2026-10-01. The owner pre-authorized technical remediation, provider configuration changes, exact TEST_ONLY proof, guarded merging/deployment and non-destructive recovery. Real customer/prospect sends, protected-record changes, financial writes, real canaries and broad real automation remain forbidden. Phase 14 has not begun.

## Implemented safety architecture

The fixed root-owned `/etc/optibrain/mutation-control.json` is authoritative. Missing, malformed, substituted or untrusted control state denies provider mutations. `real_canary_allowed` must be false; this implementation cannot grant real-business authority. It starts with `test_writes_enabled=false`. An environment flag or issued approval cannot override it.

The Zoho transport admits only `crm.task.create` through the central action journal, running as root, with exact TEST_ONLY ownership, an exact fresh off-host conditional claim, matching action/payload/body/client, an attempted journal state and the independent lower CRM/Test ownership firewall. Authority is consumed before OAuth and revalidated immediately before HTTP transport. Reads and reconciliation continue with the kill off. All other Zoho write classes, Mail sends/drafts/Sign, Google mutations and runtime provider/infrastructure administration are forbidden. The independent connector denies provider writes before OAuth. WorkDrive/PDF and unauthenticated legacy job/controller executors are retired at source and contained at the proxy.

The journal preserves immutable full action envelopes and append-only hash-chained decision, approval, attempt, transport-intent, provider-response and reconciliation evidence. Secret fields/current credential literals are rejected from envelopes and redacted from evidence. Existing histories are explicitly incomplete; new evidence cannot retroactively reconstruct missing historical events.

Tasks cannot have provider unique fields. Atomic R2 `If-None-Match: *` claims under `business-effects/v1/<action_id>/` precede CRM transport. An existing or uncertain claim grants no retry, including after journal loss or stale backup. Exact action markers, immutable target/payload bindings, bounded CRM readback and immutable off-host result IDs permit read-only recovery. The prefix is protected by an independently verified indefinite R2 bucket lock. It has no pruning/TTL. Failure to reach R2 blocks new Tasks. The store is TEST_ONLY; it contains no real business payloads.

## Credentials and infrastructure

The exposed shared API key was rotated across core/GitHub/Cloudflare; the old key returned 401. The CRM notification channel verification credential was rotated in Zoho and local configuration; provider readback matched the replacement and rejected the old credential. Secret values are absent from committed evidence. Connector client secret and connector API key were migrated from plaintext Cloudflare bindings to secret bindings; health remained 200.

All six persistent Codex development units are masked, with original definitions archived under `/var/lib/optibrain/phase13-remediation/retired-development-units`. The prior authorization condition remains absent. Application timers remain available. Duplicate GitHub business schedules are disabled remotely and have their cron triggers removed in source; the Cloudflare schedule is canonical and GitHub health monitoring remains active.

Core operator shared-key authentication now fails closed when unset. URL query credentials are rejected. Access logs remain disabled after credential exposure; business/security execution evidence remains enabled. The core service has no privilege escalation/capabilities and restricted write paths. Real Access-based human approval is still not proven; R3 transport remains forbidden.

The root deployment helper is now a reviewed generic manual gate rather than historical SHA dispatch. It requires root-owned exact-SHA authorization, live successful exact-head CI, exact remote main, immutable validated environment, rollback archive, writers off, source manifest rebinding and healthy restart. It executes no checkout scripts as root. Failure restores code, manifest and environment without reverting rotated credentials. The forced SSH deploy command remains constrained to a single 40-hex SHA. New releases outside a manual authorization fail closed.

Backup coverage now includes all phase registries/documents/journals, online SQLite snapshots, root safety configuration, service drop-ins, deployment helper, SSH identity and retired-unit mask metadata. Mask restoration is explicit and does not extract absolute symlinks. Production is never overwritten during drills.

## Validation and remaining external dependencies

Exact final deployment, provider-backed Task, kill/isolation/auth and fresh recovery results are recorded in the completion evidence accompanying this report. Initial full baseline: 783 tests passed. Root-only diagnostic failures were caused by fixture privilege/Git ownership assumptions. The portable validator now drops to the checkout owner rather than skipping those assertions. Intermediate remediated full regression: 793 tests and 742 subtests passed, zero failures/errors/skips/network. The completion regression passed797 tests/742 subtests, zero failures/errors/skips/network. It includes production API fail-closed behavior, financial denial, pre-transport execution context and locked-claim reconciliation.

Native Zoho Forms is a separate provider-owned producer outside the OptiBrain transport. Its native CRM integration cannot be conclusively disabled using the available supported API/scopes. Owner UI verification/deactivation is required; do not claim the application kill switch controls it. Native Forms mapping repair remains deferred; receipt collection continues read-only. Current owner-held offline AGE identity is unavailable to the server. An isolated temporary-key roundtrip can prove the encryption/storage/restore pipeline, but cannot prove the owner's ability to decrypt that recipient's current backup. Exact owner steps and readiness effects are in the final manual checklist.

No authorization to begin Phase 14 or real automation is implied by this report.
