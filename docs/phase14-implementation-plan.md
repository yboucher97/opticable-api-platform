> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# Phase 14 implementation order — preparation only

Input: [reconnaissance](phase14-reconnaissance.md) and its linked runtime/state/code evidence at production `4bc1beec112c55b161c3025529733d0f0b1213b3`. **No implementation is authorized by this document itself.** The next mission requires a new user instruction. Real/protected writes, sends, Books writes and real canaries remain 0; persistent development worker staysOFF.

Use impact HIGH/MEDIUM/LOW; risk LOW/MEDIUM/HIGH; effort S (bounded change), M (several related modules/contracts), L (migration/design). Dependencies are explicit. Validate each change against its actual invariant; do not expand to broad refactors or weaken safety to reduce test time.

## Recommended order

| Group / order | Bounded implementation | Impact / risk / effort | Dependencies / acceptance |
|---|---|---|---|
| **P14-A1 — immediate simplification** | Establish one redacted operational summary from existing checkpoints/job metrics/receipts. Expose failed Lead delta, native-binding/expiry drift, stale timer/backup age and historical/Test exception scope | HIGH / LOW–MEDIUM / M | Use current read-only models; no resume/replay/new monitor platform. Prove health 200 cannot hide stale sync; provider/counter failures visible without leaking payloads or credentials |
| **P14-A2** | Add missing ProviderUsage scopes to drift/native/delta/operator reads; distinguish normal scheduled estimates from zero-cadence workflow metrics and R2/auth omissions | HIGH / LOW / S–M | Extend existing 30 d/10k accounting; never let metrics failure affect safety/execution. Compare actual known 32–33 Mail/run and 5 service/run without logging IDs/URLs/secrets |
| **P14-A3** | Remove proven unreachable PDF CRM/WorkDrive mutation bodies after retaining deny stubs/interfaces; label old metadata/runtime docs clearly | MEDIUM / LOW / S | Reference/import evidence and pipeline/local generation/containment tests. No whole-module removal, no reactivation. Keep public 403/source guards |
| **P14-B1 — provider efficiency** | General mailbox known-message body cache/checkpoint before duplicate work, with overlap, completeness bounds, changed-metadata invalidation and periodic revalidation | HIGH / MEDIUM / M | A2 accounting; receipt semantics are a useful existing contract, not an interchangeable mailbox model. Prove delayed/reordered delivery, body change, duplicate and partial-read behavior; no missed messages/real writes |
| **P14-B2** | Shared time-stamped lifecycle/recurring display projection from existing snapshots; target-filtered project reads; immutable Sent-evidence reuse | HIGH / MEDIUM / M | Complete scope/ownership/time contract. Preserve daily deletion checks, browser no-store, fresh source/version/uniqueness/inbox reads before every consequential action |
| **P14-B3** | Batch unique source-trace relationships and local Lab chronology; checkpoint connector receipt export; back off unresolved form-to-CRM rescans | MEDIUM–HIGH / MEDIUM / M | Exact source namespace/immutable replay/completeness proof; server cursor not based solely on client newest time. Current pending-match count 0 means savings are conditional |
| **P14-B4** | Reuse or stagger duplicate native-watch/desired-state metadata reads; diagnose failed delta/auth and native evidence mismatch | MEDIUM / MEDIUM / M | Fresh safe readback, timestamp/binding contract and separate delta/native independence. Record/reconcile local evidence first; no automatic provider renewal, checkpoint resume or read-window skip |
| **P14-C1 — state/data cleanup** | Evidence-aware retention hold index and **dry-run** cleanup report for plaintext/AGE cache; implement approved bounded pruning only after protected holds resolve | HIGH / MEDIUM / M | Preserve generation 20261001T202728Z, exact rollback/release/archive holds and≥2 independently verified usable generations. Remote delete permission remains absent; failed/uncertain upload is never pruned as expendable cache |
| **P14-C2** | Measured indexes/read-only getters for recent runs, feedback/canonical order, connector receipt time and action display order | MEDIUM / LOW–MEDIUM / S–M | EXPLAIN + representative data + backup/schema compatibility; move setup to explicit initialization safely. No speculative service-event index, online VACUUM or mass WAL switch |
| **P14-C3** | Document canonical Services/Service_Locations, stable IDs and receipt/Test registry/projection contracts; archive reviewed historical state after dependency index | MEDIUM / MEDIUM / M | Immutable crosswalk/attempt/history and restore compatibility. Keep five active DBs initially; no major ledger migration. A future migration is separate L/HIGH work |
| **P14-D1 — privilege/security cleanup** | Reproducible root-owned dependency/source release contract; narrow runner write paths and separate read work from privileged claim/ack operations | HIGH / HIGH / L | A1/A2 + exact source/helper pins + state-loss/kill/restore gates. Existing runner source import/dependency trust must remain intact. Do not lower policy ownership to API UID |
| **P14-D2** | Review dedicated uploader UID/staged-input design and scrub raw provider-auth exception detail where still present (notably Google/PDF legacy clients) | MEDIUM / MEDIUM / M | Keep credential custody, archive privacy, independent verification and create-only R2 semantics. Verify fixed errors/logging; do not move secrets or change OAuth grants |
| **P14-E1 — operator UX** | Lightweight read-only Today home, shared navigation/counters, single attention item per verified customer/project/state with links to existing drill-downs | HIGH / MEDIUM / M | A1/B display scopes and freshness; no new DB/business engine. Test-only/historical evidence and unverified revenue must be clearly scoped |
| **P14-E2** | Exceptions ownership/acknowledge/resolve/reconcile display contract; technical details move to operations drill-down | MEDIUM / MEDIUM / M | Preserve immutable transitions and uncertain-effect fences; ordinary denial/no-op should not drown true failure. No automatic resolving or granting approvals |
| **P14-F1 — docs/recovery/deployment cleanup** | Canonicalize source/bootstrap/docs on installed exact-SHA core gate; maintain separate Worker/connector targets; archive old release helpers only after recovery dependency review | HIGH / MEDIUM / M | Source-vs-installed trust, unexpired manual auth, exact CI/main/backup and rollback tests. No “latest branch” deployment, candidate-owned root scripts or stale phase gate reuse |
| **P14-F2** | Keep onboarding authoritative; consolidate duplicate architecture pointers; add retention/reconnect/new-OS/cutover/RTO procedures | MEDIUM / LOW for docs; MEDIUM for later drills / S–M | Do not repin master runbook silently or rewrite historical evidence. Existing owner AGE identity stays offline; no repeat Phase 13 drill just to complete optimization |

Practical sequence: **A1/A2 → B1 → C1 hold/dry-run → B2/B3 → C2/C3 → E1/E2 → F1/F2**. D1 is a later separately bounded privilege milestone with safety/recovery proof, not a quick cleanup. D2 safe diagnostic scrubbing can run earlier when changes are isolated. Failed observer diagnostics may become an early reliability task, but any resume must be explicit, bounded and within unchanged read-only authority.

## Best ten quick wins

| Rank | Change | Expected result | Risk / bounded test |
|---|---|---|---|
| 1 | General Mail pre-content dedupe/cache | Largest measured read saving: latest 33 → near 1 for unchanged windows outside validation, up to~768 GET/day less for that observer before new-message/audit overhead; lower~8.6 s run latency | MEDIUM; delayed/change/partial/pagination/replay cases, identity preserved; compare counters without sends |
| 2 | Unified stale-observer/timer/backup summary | Reveal failed delta/native mismatch even with liveness 200; owner understands data may be stale | LOW–MEDIUM; fixture stale/failure/healthy/no-secret summaries; no repair or restart side effect |
| 3 | Existing accounting scopes for all hot reads | Rank actual background/operator use rather than undercounting native/drift/R2 | LOW; known fake transport counts, bounded retention and failure isolation |
| 4 | Retention hold inventory + dry-run report | Make ~16.7 GiB archive/cache footprint reviewable; potential>10 GB later reclaim, subject to hold policy | LOW for inventory, MEDIUM for eventual delete; exact owner-proof/rollback/uncertain-upload holds and retained-generation tests |
| 5 | Shared lifecycle/recurring display reads | Two related page loads can reuse one 5-read inventory; fewer requests and consistent timestamps | MEDIUM; scope/freshness/deletion/completeness tests; cannot authorize writes |
| 6 | Project detail only loads requested registered dependencies | Avoid rebuilding all three projects on one detail visit; fewer module/ID reads as projects grow | LOW–MEDIUM; missing/unexpected/duplicate/foreign-ID batch failures must stay fail-closed |
| 7 | Recent-run/feedback/connector/action display indexes | Remove demonstrated scans/temp sorts and protect increasing watchdog/operator workload | LOW–MEDIUM; representative EXPLAIN and restore/schema compatibility; tiny present DB means modest immediate benefit |
| 8 | Proven unreachable mutation-body removal with deny stubs retained | Reduce confusing dormant provider client code/attack-review surface without changing behavior | LOW; imports/pipeline/containment reviewed; executable-code change still requires release gates |
| 9 | Read-only Today navigation shell using current models | Fewer phase/provider pages; immediate business attention with existing evidence links | MEDIUM; scope/auth/no-store/escaped rendering, zero action side effects |
| 10 | Bootstrap/release documentation alignment and historical-helper index | Prevent a fresh session from selecting obsolete root staging/deploy commands | LOW for docs/index; MEDIUM for helper changes; installed/source/hash/rollback dependency evidence |

These are implementation candidates, not all mandatory in one session. One good bounded set is A1/A2, B1, C1-dry-run, E1-navigation, F2-doc pointers. Complete accepted scopes before adding migration/root redesign. Do not claim the already completed receipt 7 → 1 or operations 22 → 9 reductions as new savings.

## Do not touch without care

- Universal mutation control, central Action/BusinessJournal immutable envelopes/hash chain, root Test ownership and protected 123 baselines; denial stays authoritative over every legacy flag/approval.
- Locked off-host action claims/results, provider intent/ack/readback/root attempt history, reconcile-before-kill behavior and ambiguous/replay fences. An apparent duplicate is often a distinct state-loss defense.
- Native notification credential/origin checks and independent CRM delta fallback; repair diagnostics does not authorize watch renewal, resume or loss of completeness.
- Receipt authentication, daily seven-day revalidation, two-day overlap, failed-checkpoint rules and source namespace/immutable receipt IDs; caches are never ownership evidence.
- Services/Service_Locations and verified service dates; Deal stage/history does not establish installed work or recurring revenue. Crosswalk IDs must not be regenerated from replacement provider IDs.
- Access JWT issuer/audience/allowlist, exact origin/CSRF/content-type checks, fail-closed shared-key authentication, loopback bindings, Caddy matcher order and intrinsic legacy route/writer guards.
- Root release/source/helper/dependency pins, static reviewed deploy gate, exact-main CI, previous env/manifest/venv rollback; never replay old state from a zero attempt counter.
- Local online SQLite snapshots, private plaintext backup, create-only encrypted R2 upload, independent hash readback, owner-held AGE identity and exact generation 20261001T202728Z; no secret/private identity migration.
- All five legitimate timers until a replacement's responsibility/safety/recovery contract is proven; old disabled unit boot states do not make timer-triggered jobs dead.
- Six masked development units and immutable retirement archive; manual Codex sudo/root authority remains unchanged.
- Safety/provider-fake/recovery tests and immutable historical evidence/tags; old scaffolding may encode still-required recovery. No deleting tests to improve reported pass rate.
- Connector/core OAuth domains and remote preview/D1/R2 bindings whose usage is UNKNOWN. No customer outreach, real canary, financial write, provider mutation-authority expansion or new monitoring platform.

## Validation and release boundaries

For implementation, run meaningful changed-area and mandatory safety checks; executable production changes require the current full release regression and exact-SHA release controls. A passing PR/main test alone is not a runtime receipt. For documentation-only work, check links/digests/schema/counts and unchanged live safety; no811-test rerun. Deploy only the concretely reviewed scope under the user's session authorization and existing root gate requirements.

## Recommended next prompt

> Begin the FULL Phase 14 implementation mission using `docs/OPTIBRAIN_CODEX_ONBOARDING.md`, `docs/phase14-reconnaissance.md`, `docs/phase14-implementation-plan.md` and their evidence as the input. Revalidate SHA/safety and stale-observer facts first. Implement P14-A, then the bounded high-value Mail read optimization, retention hold/dry-run, shared operator display/navigation and canonical documentation/release-path cleanup in the evidence-based order. Keep real/protected mutations, customer sends and Books writes at 0, REAL_CANARY_ALLOWED FALSE, persistent development workerOFF. Preserve every safety/reconciliation/auth/recovery/rollback contract. Do not begin a major DB migration or privilege redesign without its own bounded acceptance scope. Run relevant checks and the full release gate only for executable production changes; report measured before/after savings and exact receipts. Do not run a real canary or contact customers.

**Preparation ends here. Implementation has not begun.**
