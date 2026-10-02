> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# Phase 14 implementation and release report

The implementation evidence and operating contracts are complete. Production certification is the post-deployment `/var/lib/optibrain/phase14/final-verification.json` and generated `/var/lib/optibrain/phase14/phase14-final-report.md`, copied to the owner's private implementation-evidence directory. These carry the exact final production/local-main/remote-main SHA, final tests/CI/runtime results and PASS/PARTIAL/BLOCKED outcome. A source document cannot contain its own Git commit hash; the schema-1 release receipt is the canonical exact identity.

| Required result | Contract / evidence |
|---|---|
| Production SHA / local main / remote main | All equal `releases/current.json.sha`; independently verified after guarded deployment |
| API | 1.12.0 |
| Protected baseline | 123/123 unchanged before and after; provider summary compares exact IDs and Modified_Time, no spoofed Test marker |
| Protected mutations / real customer sends / Books writes | 0 /0 /0; transport and journal/provider evidence |
| Real auto writes / REAL_CANARY_ALLOWED / persistent worker | OFF /FALSE /OFF |
| Release status | Exact CI + full regression + guarded runtime receipt + final-verification artifact |

## Early degraded findings

Leads authentication_failed: failed checkpoints are excluded from polling, leaving a latched failure after credentials became readable. GET at the same saved cursor proved 26 rows complete; one CAS revision was returned to idle with cursor unchanged, then the read worker advanced naturally. Root cause of the original historical 401/403 is not retained and is not invented. No token replacement or mutation was performed. Current native-watch/delta evidence is independently rechecked after release.

Native expiry/configuration drift: local requested expiry19:38:19Z differed from provider20:38:19Z; prior credential rotation checked token/events/destination but omitted exact expiry. Rotated binding also made older local verification stale. Exact GET showed matching token/destination/events/options; local env/webhook expiry reconciled to20:38:19Z and append-only verification rebound. Provider normalization mechanism unknown. No rotation/new credentials/provider channel write.

After delta resumed, readiness exposed seven retained read-observer `EventConflict` failures. Old review payloads and newer time-dependent sales decisions used the same Lead/version identity. The producer now reuses the first immutable review; new reviews fingerprint hydrated fields and fail closed if those fields change without a new provider version. A copied-store GET-only proof reproduced all seven existing reviews with seven CRM reads, zero new events and zero provider mutations. Original failed runs and envelopes remain untouched. A root receipt tied to the exact producer hash and run IDs scopes their read-only display acknowledgement; unrelated/new failures remain actionable. No consequential workflow was redriven.

## Provider efficiency and representative performance

Mail baseline ~1086/day reconnaissance estimate; fresh unchanged observer33GET/32content,8.38s. After4metadata/0content,1.29s,0duplicates/0mutations; two-day overlap307rows complete. Full seven-day audit593rows,135GET,35.72s,0new/duplicate events. Revised same-corpus estimate227observer/day and~521total/day; new-message/volume/retry costs are variable and full-day observation remains follow-up.

Lifecycle/recurring10→5 total CRM reads; recurring5→0 and~2.56s→4ms. One project9→6 CRM reads,3.67s→2.78s. Sales provider reads unchanged6CRM+3Mail; local Lab chronology now two SELECTs per ledger instead of per-Lead N+1. Receipt collection remains1Mail+1Cloudflare per stable run; earlier P1 reduction not claimed again. CRM configured scheduled estimate~792/day retained; repaired delta is legitimate restored work, not a saving. Complete accounting now includes previously omitted delta/native/drift/route/OAuth/R2/auth exchange/Sign/Books calls. Cold/warm Today and zero-provider readiness timing are in the final performance artifact.

OAuth/retry: trusted shared token cache retained; invalidate only the rejected token, preserve concurrent newer token; one GET retry after401, never403 or ambiguous mutation retry. Error payloads/credential text scrubbed from OAuth diagnostics.

## Storage, state and privilege

Fresh backup/archive staging18,782,774,178B versus16.7GiB reconnaissance. Initial cleanup reclaimed8,950,924,187B (33 proven redundant ciphertexts). All plaintext backups and exact holds retained; owner ciphertext and≥2recent verified ciphertexts retained; R2 deletions0. Deterministic dry run and changed-report/hash/symlink/coverage tests PASS. Final bytes/new-generation changes recorded in final-verification. [Retention policy](phase14-retention-policy.md) and concrete root reports are authoritative.

Active SQLite5→5; historical3→3 ARCHIVE in place; no consolidation. Listing medians<1ms justify no speculative indexes. Rebuildable cache primary keys and existing due/identity indexes retained. State contracts, canonical writers/readers/identity/retention/rebuild/backup documented. Final full integrity checks required.

Services remain3app+proxy, five oneshots/timers; GitHub1active+3disabled business schedules; Cloudflare1cron/2queues/1Workflow. No redundant responsibility was removed without proof. Root jobs3→3: TEST runner keeps private ownership/claim boundary with five necessary capabilities and read-only policy mounts; actual hardened cycle success,0writes. Uploader already empty capabilities; root kept to avoid wider plaintext/credential access. Backup ROOT REQUIRED. Manual Codex full sudo/root preserved.

## Operator, deployment and documentation

Today implemented: leads needing review/response, due follow-ups, quote review, projects/install work, maintenance/renewal, current exceptions/approvals and system attention. Each item has priority, reason, next action, due/freshness/context/source and existing drill-down. Synthetic/Test/historical/resolved evidence cannot create REAL CURRENT urgency. Model/auth/cache-failure/escaping/no-store tests pass; owner live-login browser validation is not impersonated. Final routing found the legacy Access hostname had no public DNS; the existing application/audience/policies were reused on the proxied optibrain operator prefix. Owner entry https://optibrain.opticable.ca/v1/operator/today now has an Access login boundary; origin JWT/owner enforcement remains independent. This single-host routing verification is not full replacement-OS/DNS/TLS disaster failover proof. Readiness uses durable observations and a root sampler,0provider calls; remote queue depth remains explicitly UNKNOWN.

Canonical release path: installed root `opticable-api-deploy-root` from reviewed `manual-guarded-release.py`. Exact main CI/source/version/backup/dependency/safety gates plus schema-1 receipt with tests, migrations, service/timer health and rollback. Obsolete bootstrap/update/Phase6 direct entrypoints and24installed historical release helpers refuse execution; current restricted SSH bootstrap installs the same canonical gate. Previous master/architecture bytes archived; onboarding and current docs consolidated under docs/README. Twelve current docs are distinguished from 71 pre-existing historical/audit/recovery files; immutable phase evidence was not deleted.

Monitoring covers disk/staging/DB/log growth, queues, provider-call anomalies and last successes. Repeated identical health failures do not generate repeated comments. Recovery docs/tooling cover reconnect/rebuild/cutover/RTO without claiming untested full-OS/DNS/provider/RTO proof.

## Testing and safety certification

Focused A/B/C/D/E/F receipts are in private implementation evidence; all accepted runs have zero failures/errors/skips/network attempts. R2 create-only/ambiguous/denied/corrupt readback fixtures pass. The authoritative complete local regression passed:852tests,760subtests,0failures/errors/skips/network attempts. Control-plane fake tests and dry-run compilation, Omada TypeScript build and R2 immutable-upload fixtures passed. Exact-SHA PR/main CI and production certification are recorded in the root release/final receipts.

Required final PASS gates: auth fail-closed; universal kill; state-loss/stale-journal reconciliation;123protected unchanged; native Forms DISABLED (owner closure/API evidence limit); fallback OFF; connector/Omada/PDF/WorkDrive/Mail/Sign contained; Books WRITE DENIED; unguarded consequential paths0; no real canary/development worker/customer sends. Any failed gate requires rollback or truthful PARTIAL/BLOCKED certification.

## Outcome and next mission

Architecture/maintainability/performance/provider efficiency/operator UX/documentation/monitoring: STRONG for the bounded delivered scope, subject to final release certification. Recovery maturity: ACCEPTABLE; full replacement OS/DNS/provider reconnect and guaranteed RTO remain unproven.

P1: No remaining authorized business-write activation; preserve current containment. P2: Measure a complete ordinary24h provider profile; owner login/browser acceptance; independently measure remote queue depth; test new-OS/reconnect/DNS cutover and RTO in a new bounded mission. P3: Consider a narrow privileged broker only if it improves secret/recovery boundaries; investigate unknown preview consumers before retirement.

Recommended next manual mission: Phase15 rebuild/onboarding/documentation closure, with real business writes and canary still OFF. Do not begin it automatically. Do not enable a real canary. STOP after Phase14 certification.
