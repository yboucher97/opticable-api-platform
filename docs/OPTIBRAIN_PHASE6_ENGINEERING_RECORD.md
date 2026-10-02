> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# OptiBrain Phase 6 engineering record

This record is append-only engineering evidence for Phase 6. It is not the privileged root-owned production recovery runbook. The root runbook remains protected during branch engineering and is synchronized only through a separately reviewed deployment/recovery procedure.

## 2026-09-28 — Phase 6 start

### Verified starting state

- Exact Phase 5 production/main/recovery identity: `52f11d4fc14d8582c03837e0317f849efe8aa3d7`.
- Phase 5 final recovery tag: `recovery/post-phase5-business-autonomy-v1-20260928`.
- API `1.10.0`.
- Automation DB schema V2.
- Phase 5 final backup/restore/off-host gates already passed before this branch was created.
- Books safety remains read-only/human-approved.
- Native Zoho Lead subscription remains independently managed by the Phase 5 reviewed renewal contract.

### New branch

Created `phase6/sales-autonomy-v1` directly from exact baseline `52f11d4fc14d8582c03837e0317f849efe8aa3d7`.

No production checkout, service, database, environment, provider, `main`, recovery tag or protected production file was changed by branch creation.

### Authoritative Phase 6 contract

Commit `70d591e396e3090dcd3cda564eb237ab6557aaf4` added `docs/OPTIBRAIN_PHASE6_SALES_AUTONOMY_V1.md`.

The contract deliberately keeps the first release bounded:

- internal lead maintenance and task orchestration may become automatic after proof;
- mail drafts may be prepared automatically;
- external customer sends require exact durable human approval;
- Books remains human-approved/read-only;
- no autonomous existing-Lead conversion or Account/Contact/Deal creation;
- no owner reassignment or destructive CRM metadata operation;
- AI may classify/draft but cannot independently authorize provider writes or sends;
- Phase 5 event/journal/retry/recovery machinery is reused rather than replaced.

### Gate B pure decision layer

Commit `dd16768769ecc9b365ccb65c1d7aaf2d3e8930ee` added `apps/workflow-api/workflow/automation/sales_decision.py`.

Properties:

- pure/local module with zero provider access;
- policy version `phase6-sales-v1`;
- validates exact Lead identity and timezone-aware record version;
- separates active/converted state;
- honors email opt-out before allowing draft recommendation;
- bounds language, priority and next-action values;
- advisory AI values are ignored unless they fit deterministic allowed values/state/contactability;
- `Contact in Future` preserves an explicit future `Next_Followup_At`;
- business-day deadlines use `America/Toronto` and persist UTC timezone-aware timestamps;
- decision evidence includes a stable hash over payload-safe decision metadata;
- no provider identifier, address, phone number or customer body is invented by AI.

Commit `12efc71197b1604bde7a956d0c8cd2b67167307d` added `apps/workflow-api/tests/test_phase6_sales_decision.py` with ten focused tests covering:

- converted lead refusal;
- email opt-out;
- invalid AI language/action/priority;
- stale/pre-qualified priority;
- explicit future follow-up preservation;
- Friday/weekend business-day boundaries;
- after-hours same-day rollover;
- bounded missing-information metadata;
- deterministic decision hashing;
- invalid IDs and naive timestamps fail closed.

### Gate B validation — PASS

The isolated VPS worktree validation completed against candidate `268332bac72295cc57e683524553fe8f915984cc`.

- pure import/provider boundary: PASS;
- focused Phase 6 tests: 10/10 PASS;
- complete inherited regression: 434 tests, 374 subtests, 0 failures, 0 errors, 0 skips;
- compileall: PASS;
- production remained `52f11d4fc14d8582c03837e0317f849efe8aa3d7`;
- remote `main` remained `52f11d4fc14d8582c03837e0317f849efe8aa3d7`;
- provider writes: 0;
- production changes: 0.

This closes Gate B.

## 2026-09-28 — Gate C internal CRM action hardening

### Decision-envelope hardening

Commit `9a02c970c371b94e4ae74bba66582ed7a6f1b317` strengthened the pure Phase 6 decision contract before provider wiring:

- existing future `Next_Followup_At` is preserved for any active Lead so repeated notifications do not continually shift the SLA;
- `Service_Types` trusted fill is separated from AI hints and accepts only an exact bounded service value plus a reviewed non-AI evidence category (`explicit_customer_selection` or `validated_intake`);
- the decision now records whether service type came from existing provider state or a trusted hint;
- a full decision-envelope hash validator rejects tampered policy/version/decision fields.

Commit `b517090750e42efed0e10e06727ac412d755631b` expanded pure decision tests for stable future follow-up, trusted-service separation and tamper rejection.

### Existing Lead writer extended, not duplicated

Commit `438a7573231511ec532fd71bd88f2d75606ed99f` extends `workflow/automation/providers/crm_leads.py` under the separate opt-in policy `phase6-sales-v1` while preserving legacy `phase5-lead-v1` behavior.

Phase 6 automatic Lead writes are allowlisted to exactly:

- `Normalized_Email`;
- `Normalized_Phone`;
- `Next_Followup_At`;
- `Service_Types` only when empty and backed by the trusted non-AI decision source.

Other properties:

- the exact reviewed Lead version is required before any mutation;
- writes keep `If-Unmodified-Since`, `trigger: []` and cadence suppression;
- no conversion, owner reassignment, Account/Contact/Deal creation, customer communication or Books mutation is introduced;
- reviewed events now carry a payload-safe hashed `SalesDecision` envelope;
- audit metadata stores categories, timestamps and hashes, not normalized email/phone values;
- future follow-up timestamps remain stable across self-induced/new notifications;
- task generation identity is derived from policy + Lead + internal action + follow-up timestamp, avoiding duplicate tasks for repeated versions of the same schedule;
- one exact task identity is searched/read back before creation.

### Lost-response reconciliation without retry

Phase 6 records a hash of the exact intended bounded Lead-field subset before the provider call. If the response is lost:

- the operation is still recorded `manual`/human-required;
- no second provider write is issued;
- a later Lead event may close the ambiguity only when exact readback of those same fields hashes to the prior intended hash;
- any mismatch remains human-required.

Task creation follows the same no-blind-retry rule. A lost Task response is reconciled only by an exact deterministic subject + Lead linkage readback; absence/collision does not authorize a second POST.

This improves recoverability without storing raw email/phone values in journal evidence.

### Gate C tests prepared

Commit `43b2eb3431aa1198762ec3849472a9184187cf4e` added focused fake-provider tests for:

- normalization + `Next_Followup_At` + one internal Task;
- stable follow-up/task identity across newer Lead versions;
- accepted-but-response-lost Lead update reconciled by exact hash with no second PUT;
- mismatch after a lost response remaining manual with no retry;
- accepted-but-response-lost Task reconciled by deterministic identity with no second POST;
- trusted empty `Service_Types` fill from a hashed reviewed decision;
- tampered decision failing before provider writes;
- converted Lead performing zero Phase 6 provider writes.

Commit `b05cffd4a1920a744f872c3bb8b2a00c9b7ca1dd` versions the internal reconciliation workflow description for Phase 6. No provider workflow is modified by this source change.

### Gate C validation state

Gate C code is engineering-only on `phase6/sales-autonomy-v1`. It has not been deployed and `OPTIBRAIN_CRM_LEAD_WRITES` has not been changed in production. Focused Phase 6 tests, complete regression and compile checks must pass before any live/read-only Phase 6 provider validation or draft-lifecycle work begins.

### Gate C validation and exact-readback correction — PASS

Initial validation of exact remote candidate `2b1326999710e6c6dc8d789ff41f92cde684d37a`:

- clean worktree; exact seven-file contract scope; 10 commits ahead / 0 behind the Phase 5 baseline;
- remote Phase 6 ref matched the candidate; production and remote main matched `52f11d4fc14d8582c03837e0317f849efe8aa3d7`;
- decision tests: 13; CRM-action tests: 8; Phase 5 Lead compatibility: 16 tests / 3 subtests;
- full regression: 445 tests / 374 subtests, zero failures/errors/skips.

Independent inspection found a release-blocking gap despite those passing tests: Task search reconciliation checked Lead linkage but did not check the returned subject and due date. Commit `820e41dd9c369e645ac8ec71d460fc43bf59c529` now requires exact subject, Lead linkage, due date, valid provider ID and a recognized Task status. Completed matching Tasks are retained as fulfilled generations without creating replacements. Immediate readback also checks the returned operation ID.

Validation of corrected candidate `820e41dd9c369e645ac8ec71d460fc43bf59c529`:

- focused CRM tests: 12 tests / 5 subtests, including exact mismatches, stale review, durable restart, and absent ambiguous Task;
- complete regression: **449 tests / 379 subtests, 0 failures, 0 errors, 0 skips**;
- compileall and diff whitespace checks: PASS;
- static provider boundary: only Lead reads/conditional PUT and Task reads/POST; no Books, Account/Contact/Deal, conversion or customer-send path;
- tests used temporary databases, fake providers and a runner that clears inherited environment and blocks socket connections;
- real provider writes, customer sends, Books mutations and Lead conversions during validation: **0**;
- production and remote main remain `52f11d4fc14d8582c03837e0317f849efe8aa3d7`; production health reports `ok`, API `1.10.0`;
- protected diagnostic SHA-256 remains `7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000`; root recovery runbook untouched;
- validation logs retained locally under `/var/tmp/optibrain-phase6-validation/`.

Gate C is closed after the correction. Gate D may proceed on the engineering branch only. No production policy, service, database or recovery artifact was changed.

## 2026-09-28 — Gate D draft lifecycle — PASS

Implementation candidate: `2872da4a2727d8ade85e1109efccf79f2a2bd5ee`, following Gate C evidence commit `8f9993bde36458f052ccb5898f6e2892cb636263`.

### Existing mechanism reused

The existing `lifecycle.mail_save_draft` now calls a shared `save_mail_draft` transport. The Phase 6 `lifecycle.sales_draft` action calls the same transport. It permits only the existing Mail POST with `mode: draft`, a numeric account ID and a small payload allowlist; send/scheduling fields cannot pass. The existing lifecycle draft compatibility tests pass.

Provider contract reference: [Zoho Mail Save Draft / Template](https://www.zoho.com/mail/help/api/post-save-draft-template.html). This documents the existing POST endpoint and required draft mode. Gate D has **not** performed a live Mail write or claimed live response-shape verification. A response without an explicit success envelope and provider message ID remains human-required.

### Deterministic policy and durable evidence

- New workflow `opticable.sales-draft` consumes internal `opticable.crm.lead.reviewed` events and has one write attempt.
- `OPTIBRAIN_SALES_DRAFTS=phase6-sales-v1` is a separate explicit opt-in. Its default and every other value return observe before provider access. Disabling it is rechecked immediately before the POST.
- The mailbox must be explicitly configured using `OPTIBRAIN_SALES_DRAFT_ACCOUNT_ID` and `OPTIBRAIN_SALES_DRAFT_FROM`; the sender must be a valid Opticable address. No production environment was edited.
- Fixed French/English templates provide bounded draft content without an AI call. A reviewed decision with unknown language stops for review; this gate does not assume that production CRM exposes a configured language field. Language classification/intake configuration must be established before live enablement.
- Recipient comes only from a freshly read Lead matching the exact reviewed version. Converted/inactive state, opt-out or unknown consent, missing/invalid/multiple recipients, and internal sender loops produce zero Mail writes.
- Optional message binding reads the immutable existing event ledger entry using its event ID and exact content hash. Source type, sender, mailbox and Lead correspondence must match; reply headers must be present and valid. Missing headers stop for review, rather than treating a provider message ID as an Internet Message-ID. The current mailbox poller does not guarantee these headers, so message reply binding remains fail-closed until they are available.
- Journal identity binds the connected Lead identity, optional exact message identity, reviewed version and content hash. Changing notification account metadata cannot bypass dedupe or an unresolved operation.
- The existing cross-process `DesiredJournal` lock serializes writes. Started intent is durable before POST. Response loss, malformed acknowledgement and a crash after provider acceptance all fence the same source, including newer versions, without another POST. No automatic ambiguous-draft readback/reconciliation is claimed.
- Reprocessing the same source/version/content returns the stored draft ID across restart. Changed content on the same version requires review. A newer version may create a new draft with `supersedes_draft_id`; earlier drafts are preserved and never sent/deleted.
- Evidence and action results contain IDs, bounded categories and hashes, not recipients or raw message bodies. Existing captured inbound source events retain their pre-existing intake semantics; their body is not copied into new journal evidence.
- Lead state, recipient and policy are rechecked immediately before writing. Mail POST cannot atomically condition itself on a CRM version; a later concurrent CRM edit is a cross-provider limitation. This path creates drafts only.

### Validation

- Focused draft lifecycle: **23 tests / 26 subtests**.
- Existing lifecycle compatibility: **4 tests**, all PASS.
- Complete regression on exact candidate `2872da4a2727d8ade85e1109efccf79f2a2bd5ee`: **472 tests / 405 subtests, 0 failures, 0 errors, 0 skips**.
- Compileall and whitespace checks: PASS.
- Static Phase 6 draft provider boundary: CRM Lead GET plus shared Mail draft POST only; no Account/Contact/Deal, Books, owner, conversion, metadata, customer send or delete operation.
- Fault coverage includes response loss, malformed/error acknowledgements, missing provider ID, process loss before verified journal commit, concurrent journal locking, source/hash mismatch, changed recipient, stale versions, policy disable during execution, restart dedupe and newer-version supersession.
- Validation used isolated temporary databases, fake providers, cleared inherited environment and blocked Python socket connections. Real provider writes, customer sends, Books mutations and Lead conversions: **0**.
- Production and remote main remain `52f11d4fc14d8582c03837e0317f849efe8aa3d7`; live local health remains `ok`, API `1.10.0`.
- Protected diagnostic SHA-256 unchanged: `7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000`.
- Root-owned production runbook SHA-256 unchanged: `cdab559d264fb7a17c469fd10953827a98a24ac4a926939db1055522a6dfc085`.
- Logs: `/var/tmp/optibrain-phase6-validation/gate-d-focused.log`, `gate-d-compatibility.log`, `gate-d-full.log`.

Gate D engineering is closed. No production policy was enabled, no deployment/reconciliation campaign was run, and no manual VPS validation is needed for this engineering result. Gate E (durable outbound approval envelope) and Gates F/G remain separate, unfinished release gates; automatic sends remain outside this draft workflow.

## 2026-09-28 — Gate E durable outbound approval envelope — PASS

### Exact engineering identities and scope

- Last fully validated Gate D evidence: `0114b536699746b74854b24ed7c5fced2d3e0a5d`.
- Existing WIP inspected and retained: ledger commit `0a25cbddc8c47fb12607c29ba18f871b15d70a0f`, consumption commit `d70a9248d1e18d6e448e1970152728210d389cae`.
- Gate E hardened implementation and test candidate: **`c0109c043392830f8fbd53e097d2c7e2261616e9`**.
- Engineering branch: `phase6/sales-autonomy-v1` only. The initially clean local checkout was fast-forwarded from Gate D evidence to the exact remote WIP before editing.
- Gate E changes comprise `workflow/automation/outbound_approval.py`, `workflow/automation/providers/outbound_mail.py`, `workflow/automation/providers/lifecycle_mailbox.py`, `config/automation/workflows/customer-lifecycle-approved-email-reply.yaml`, `tests/test_phase6_outbound_approval.py`, and `tests/test_lifecycle_mailbox.py` under `apps/workflow-api/`, plus this engineering record. No schema migration, startup registration or issuance endpoint was added.

### Envelope validation and human authority

Issuance is an explicit library operation, never an automation action. The actor uses the bounded `human:<subject>` namespace; missing actors and machine/system/automation actors are rejected. **This string is not authentication**: Gate F must derive it from an authenticated, authorized human session, never from workflow/AI inputs. No approval issuance endpoint is production-exposed.

The immutable envelope binds the approval ID, human actor, approved timestamp, expiry, action type, source type/ID/version, mailbox account, reply message ID where applicable, recipient, sender, subject hash, content hash and exact `phase6-sales-v1` policy. Model validation is repeated on consumption, not only at issuance.

- IDs are validated at issuance, model loading and inspection; duplicate approval IDs cannot be issued again, including after consumption.
- Approval timestamps and caller-supplied test clocks must be timezone-aware. Lifetime must be positive and at most 24 hours. Future-issued or expired approvals cannot send.
- Lead source versions require strict timezone-bearing timestamps. `2026-09-28T18:00:00+00:00`, the corresponding `Z` form and equivalent offsets normalize to the same UTC instant. Naive timestamps and malformed offsets fail. Message/draft opaque revisions retain bounded exact identity; timestamp-shaped revisions must also validate as timestamps. Source IDs are not trimmed or broadly relaxed.
- Sender must be a single address in `opticable.ca` or `opti-plex.ca`. Customer recipients cannot use those domains or their subdomains. Multiple addresses, header injection and malformed addresses are rejected. Email domains are canonicalized; local-part case is preserved.
- Subject is bounded to 500 characters and content to 12,000. Subject control characters and unsafe body controls are rejected. Hashing and transmission preserve exact strings, including whitespace.
- Reply requires a numeric message ID; new-email approvals forbid one. Gate E sends are plaintext only. Unknown fields, CC/BCC, attachments, scheduling, and boolean approval flags are rejected.
- Approval audit evidence contains exact identity/address bindings and hashes, not raw subject/body text, credentials or provider error bodies. Provider request IDs are hashed before storage; provider message IDs must be numeric. Only bounded error categories are journaled.

### Durable failure semantics

The existing `automation_audit` table is the ledger. A dedicated file lock, canonicalized to the database path, serializes consumers across processes. Symlink/unsafe lock files are refused. State transitions require ownership of that lock and equality with the exact stored envelope; partial binding dictionaries and unchecked modified models cannot authorize consumption.

Normal transition: `issued -> consuming -> consumed`. A known exception or unconfirmed provider acknowledgement becomes `manual`. `manual` and `consumed` are permanently non-reusable. A crash can leave `consuming`, which is also permanently unavailable to automatic consumption and requires human investigation.

The consumer rereads the issued envelope, checks expiry and bindings, and commits `consuming` **before** any provider call. It rechecks the consuming envelope/expiry and disable policy before the POST. Disable before consumption leaves the approval issued; disable after the durable marker cancels the send and records manual. An already in-flight request cannot be recalled by changing policy.

A failure to persist intent produces zero provider calls. Process exit after intent, process exit after provider acceptance, timeout, response loss, 4xx/5xx or unexpected status, malformed acknowledgement, and missing message ID never authorize a second automatic send. If finalization/manual journaling itself fails, the durable consuming marker remains a fence and the action still reports an unconfirmed outcome. There is no automatic reset/reissue/reconciliation operation.

`lifecycle.mail_send_approved_v2` is deliberately not retry-safe; even a test workflow requesting five attempts produces at most one fake provider call. Its separate opt-in is `OPTIBRAIN_OUTBOUND_SENDS=phase6-sales-v1`; every other value returns observe before provider access.

### Zoho provider contract and exposure

Verified against official documentation, without any live provider request:

- [Send an Email](https://www.zoho.com/mail/help/api/post-send-an-email.html): POST `/api/accounts/{accountId}/messages`.
- [Send Reply to an Email](https://www.zoho.com/mail/help/api/post-reply-to-an-email.html): POST `/api/accounts/{accountId}/messages/{messageId}` with `action: reply`.

The implementation builds these two paths and a fixed plaintext payload. No Books, CRM, conversion, Account/Contact/Deal, deletion, metadata, SMS or phone mutation occurs in this path. The current acknowledgement contract requires HTTP success, an explicit provider success status and `data.messageId`; generic IDs/partial responses remain manual. These request documentation checks do not establish a live acknowledgement-shape proof.

**The new outbound action is registered only by explicit test setup.** The production startup source does not import/call its registration helper; no active shipped workflow references it. No issuance API/UI exists. No live email send occurred and no production outbound opt-in was configured.

### Legacy boolean reply path — option B

`customer.lifecycle.approved-email-reply` is now definition version 2, **disabled**, with one attempt. It is not migrated to the new action during Gate E.

The legacy `lifecycle.mail_reply_approved` handler rejects execution by default, including an already-queued V1 definition with `approved_to_send=true` and two attempts. This prevents disabled workflow configuration from being bypassed by an old queued snapshot. Compatibility is retained only through an explicit code-level `allow_legacy_reply=True` hook; no runtime startup caller uses that hook. The inherited successful-reply test invokes it explicitly to prove preserved compatibility. Any eventual use outside tests requires separate reviewed authorization; it is unavailable in the Phase 6 release's default runtime.

Tests also inspect all active shipped workflows and startup source for a legacy-send route or new outbound registration. The old boolean-only path cannot silently coexist as an active Phase 6 workflow.

### Validation on exact candidate c0109c043392830f8fbd53e097d2c7e2261616e9

| Suite | Tests | Subtests | Result |
| --- | ---: | ---: | --- |
| Gate E outbound approval | 55 | 75 | PASS |
| Existing lifecycle mailbox | 3 | 0 | PASS |
| Gate D sales drafts | 23 | 26 | PASS |
| Gate C CRM actions | 12 | 5 | PASS |
| Phase 6 sales decisions | 13 | 0 | PASS |
| Complete inherited regression | **527** | **480** | **PASS** |

All suites: **0 failures, 0 errors, 0 skips**. Compileall and `git diff --check`: PASS. Full-suite duration: 32.007 seconds. The previous 472-test / 405-subtest baseline is exceeded.

Validation used temporary databases, fake providers, cleared inherited environment and blocked Python socket connections. It includes real child-process exit after the consuming marker and after fake-provider acceptance, plus two concurrent processes sharing the same approval database. Fake-provider calls are assertions only; **real provider writes = 0, customer sends = 0, Books mutations = 0, Lead conversions = 0**.

Production, remote `main`, and the local/remote peeled Phase 5 recovery tag remain exactly `52f11d4fc14d8582c03837e0317f849efe8aa3d7`. Production environment, service, database and policy were not modified. Protected diagnostic SHA-256 remains `7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000`. The root-owned production runbook remains root-owned and its SHA-256 remains `cdab559d264fb7a17c469fd10953827a98a24ac4a926939db1055522a6dfc085`.

Logs are under `/var/tmp/optibrain-phase6-validation/`: `gate-e-test_phase6_outbound_approval.py.log`, `gate-e-test_lifecycle_mailbox.py.log`, `gate-e-test_phase6_sales_drafts.py.log`, `gate-e-test_phase6_crm_actions.py.log`, `gate-e-test_phase6_sales_decision.py.log`, and `gate-e-full.log`.

### Remaining Gate F requirements; Gate E does not authorize them

1. Build/review the human issuance and inspection UI/API with authentication, authorization, server-derived human actor, and explicit display of the exact source, sender, recipient, action, content and expiry. Do not expose issuance to automation or accept a claimed human actor from workflow inputs.
2. Resolve and revalidate the authoritative source version, current recipient/contactability/opt-out, and current draft content at the integration boundary immediately before consumption. Gate E compares the supplied exact envelope; it does not independently hydrate a live Lead/message/draft. Plan handling of source drift and the unavoidable cross-provider timing gap.
3. Verify mailbox identity, authorized sender alias, provider read scopes and the response contract using a separately reviewed live-safe plan. Request paths are documented; live acknowledgement shape remains unproven. No real customer send is part of default validation. Any send canary needs explicit human approval tied to its exact recipient/content/source.
4. Review any new action registration, one-attempt workflow routing and issuance exposure separately. Preserve the disabled legacy path, audit existing queued/custom workflow definitions read-only before promotion, and prove they cannot restore a boolean-only bypass. Leave outbound policy disabled until its specific enablement gate is approved.
5. Carry forward Gate D's unresolved live prerequisites: reviewed language classification, explicit draft mailbox configuration, and validated Internet Message-ID availability for message-bound replies. Preserve no-blind-retry investigation of manual/consuming operations, without resets or automatic resends.
6. Perform the contract's live read-only validation and approved internal smoke/canary work, then the distinct Gate G backup, restored recovery, off-host verification, protected-file and promotion gates. Gate E supplies no production deployment or main-promotion authorization.

Gate E engineering is complete. No manual VPS command is required for this completed fake-provider validation.


## 2026-09-28 — Gate F isolated engineering validation — PASS

Exact tested candidate: **`5921473c06470aafae2003607b0a8c85c25f0caf`**. The complete candidate remained clean and detached in `/var/tmp/optibrain-phase6-validation/gate-f-5921473/worktree`. This documentation update is made separately on `phase6/sales-autonomy-v1`; no tested implementation or test file was changed.

### Resolved failure and protected cleanliness interpretation

The earlier candidate `4c28f4c4ad2c17c3947caeb381d9f65ba1fd4597` had one failing Content-Type assertion and an independently reproduced terminal-approval inspection defect. The exact new candidate contains the dependency-based mutation guard and terminal envelope/evidence separation. Focused tests now explicitly prove wrong Content-Type returns **415**, consumed/manual inspection returns **200** without 500, and terminal consumption returns **409** before source/provider access. Durable single-use, expiry, exact content/source binding and no-blind-retry protections remain intact.

The first preflight attempt for 5921473 stopped before any tests because a strict empty Git-status interpretation rejected the existing protected untracked diagnostic. This was a **conservative preflight false stop, not a Phase 6 code/test failure**. Original evidence is preserved under `initial-preflight-stop/` in the evidence directory. The user explicitly authorized the following exact cleanliness exception for resumed validation:

1. `git diff --exit-code` and `git diff --cached --exit-code` both pass.
2. No tracked file is changed, deleted or added.
3. The only untracked path is `ops/backup/optibrain-cloudflare-auth-diagnostic.sh`.
4. Its SHA-256 is exactly `7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000`.
5. Any additional tracked/untracked change or hash mismatch stops validation.

The exception changes validation interpretation only. The diagnostic was not deleted, moved, committed, modified or chmod-changed. `.gitignore` was not changed. Before/after protected-file mode, ownership, size and mtime checks match as well as hashes. The root-owned production runbook remains untouched with SHA-256 `cdab559d264fb7a17c469fd10953827a98a24ac4a926939db1055522a6dfc085`.

### Exact validation results

- Focused modules: `test_phase6_gate_f_operator.py`, `test_phase6_gate_f_mailbox.py`, `test_phase6_gate_f_terminal_regression.py`, `test_phase6_outbound_approval.py`.
- Focused validation: **84 tests / 90 subtests; 0 failures, 0 errors, 0 skips**.
- Complete inherited regression: **556 tests / 495 subtests; 0 failures, 0 errors, 0 skips**.
- No tests were weakened, skipped, deleted, xfailed or modified for validation.
- The existing production virtualenv interpreter and dependencies were used with the same VPS prerequisites as prior authoritative validations. Test processes cleared inherited environment, used the isolated checkout and temporary databases, and blocked Python socket connects, DNS resolution and datagram sends. **Blocked network attempts: 0** in both focused and full runs; providers were fakes.
- Compileall over workflow, tests, `ops/phase4` and `ops/phase5`: **PASS**, with compiled bytecode directed outside the checkout.
- `git diff --check` from Gate E evidence through the tested candidate: **PASS**.
- Static Gate F provider calls: **GET only**. No Books, CRM mutation/conversion, Account/Contact/Deal, deletion, metadata, SMS or phone mutation path was introduced by Gate F.
- Operator routes and the new outbound action are still absent from production startup registration and shipped workflows. The legacy boolean-send workflow remains disabled with one attempt; its default handler refusal remains covered by inherited tests.
- Candidate and remote engineering branch matched before/after validation. Production, remote `main`, and the peeled local/remote Phase 5 recovery tag remained **`52f11d4fc14d8582c03837e0317f849efe8aa3d7`**.
- Production health before/after: **`ok`, API `1.10.0`**.
- **Real provider writes = 0; customer sends = 0; Books mutations = 0; Lead conversions = 0; production changes = 0**.

Evidence directory: `/var/tmp/optibrain-phase6-validation/gate-f-5921473/`.

Required artifacts: `summary.json`, `findings.md`, `focused-tests.log`, `full-regression.log`, `compile-static.log`, `before-after-state.txt`. Additional artifacts preserve per-suite counts, network-isolated runner, resumed-validation driver/log, original preflight-stop evidence and the final documentation publication checks.

### Engineering result and remaining release boundary

**Gate F isolated engineering validation is PASS.** This result does not claim live Cloudflare operator configuration, live provider mailbox readiness, or live send acknowledgement proof. Those prerequisites and any canary remain subject to their separately reviewed read-only/live-safe procedures. Production routes, services, environment and outbound policy were not changed. No real provider send was attempted.

No deployment, `main` merge, recovery-tag change or Gate G promotion was performed. Gate G deployment/recovery/promotion must not start without explicit subsequent instructions. The next safe action is to review the preserved evidence and remaining live-readiness prerequisites; outbound sends remain disabled.


## 2026-09-29 — Gate G engineering recovery and portable validation

Resumed at `49617098d1e5d65cb461c34b2fa25f898050b5a6`, preserving the interrupted uncommitted engineering work and original Gate F evidence at `5921473c06470aafae2003607b0a8c85c25f0caf`. No commit/history was reset. Earlier 573-test results were superseded because additional regression coverage was present. Current complete result: **580 tests / 540 subtests**; focused Phase 6: **156 tests / 166 subtests**; **0 failures, 0 errors, 0 skips, 0 blocked network attempts**. Test processes clear inherited environment and block Python sockets/DNS. Compileall, shell syntax, workflow YAML, static registration checks, `git diff --check` and the unchanged Worker dry-run pass.

The original GitHub 79 errors were classified individually: 77 absent VPS identity prerequisites and 2 non-self-contained Git-history fixtures. Constructor-scoped identity fixtures preserve distinct service/owner checks without real users. Temporary repositories provide their own pinned history and restricted push-hook fixtures. Production identity and security checks remain in place. No tests were skipped, weakened, xfailed or deleted. Portable CI now uses the network-blocked counted full runner.

Runtime source change in this Gate G work is API source-of-truth version **1.11.0**; new tests bind both health aliases, app metadata and the Phase 6 contract. No outbound action, operator routes or issuance endpoint was registered. The legacy boolean reply workflow remains disabled. Other changes implement deployment/recovery engineering, CI and test fixtures.

The new guarded Phase 6 campaign defaults to plan-only, requires root-private exact human authorization and frozen source, verifies backup/restore/encrypted off-host evidence before staging, and promotes main only after staged health, candidate recovery and isolated rollback proof. The prepared root wrapper verifies exact current remote main before executing code and fences delayed baseline deployment during staging. Generic deployment refuses a fresh Phase 6 switch and reconciles an already-staged SHA only. Neither wrapper installation nor campaign execution occurred.

Canonical observed API host is **optibrain.opticable.ca**, public health **https://optibrain.opticable.ca/v1/system/health**. The old api01 fallback does not resolve and was corrected only in branch code/docs. Live DNS/Caddy/secrets were not changed. Installed root deployment wrapper still has the download-before-ancestry trust gap; privileged policy/receipts, actual deployment secret target and a complete live rollback policy remain release blockers. The baseline-on-candidate-DB isolated drill disables workflows in a disposable copy and cannot authorize live baseline startup with Phase 6 workflows or approval resets.

A scheduled production mailbox poll was observed failed with curl timeout after 30 seconds and zero response bytes. Completion is ambiguous; it was not retried or dispatched. Current monitor health remains good. Read-only queue investigation requires the unavailable authenticated/root evidence.

Full procedure, prerequisites and rollback limits are in `docs/OPTIBRAIN_PHASE6_GATE_G_RECOVERY.md`, a normal non-privileged supplement. The protected root-owned master runbook and diagnostic remain unchanged. Evidence lives under `/var/tmp/optibrain-phase6-validation/gate-g-engineering/evidence/`; original Gate F and preparation evidence remain intact. No root collector result has been received; passwordless administrative helpers were not used because they write audit state.

Production, remote main and the Phase 5 recovery reference remain `52f11d4fc14d8582c03837e0317f849efe8aa3d7`; production API remains 1.10.0. **Real provider writes = 0; customer sends = 0; Books mutations = 0; Lead conversions = 0; production changes = 0** during this work. Fresh authoritative VPS validation of the new exact candidate is mandatory; Gate F PASS is not inherited. Gate G readiness remains **BLOCKED** until the outstanding privileged/security/recovery prerequisites are resolved. No deployment or main promotion is authorized.

Additional resume hardening removes the inherited automatic restoration of a modified production bootstrap script. The normal deploy driver now rejects tracked/staged changes and every unexpected untracked path, accepting only the exact protected diagnostic path/hash. Three disposable Git/bash regression tests prove refusal without repair, wrong-hash refusal and the exact approved exception. The full/focused runs were repeated only because this deployment code and its tests changed.

Exact Gate G executable/deployment engineering commit: **`6d8a21fe2bdca43c6d13f4dea59f531d4fb97e9c`**. Its tested working-tree content was committed unchanged after the 580-test / 540-subtest full run and 156-test / 166-subtest focused run. This following evidence update is documentation-only; the published branch head is recorded in `gate-g-engineering/summary.json`. GitHub CI publication/results are preserved in `evidence/github-ci.json` and its per-job logs; do not infer PASS until that artifact records the exact published SHA and successful jobs. Fresh authoritative VPS validation must select the final published branch SHA, including this documentation update. No Gate G release execution is authorized.

The first publication at `75f2f87353c3f40c4d0727c77799f9ec05784645` triggered GitHub run **36502696289**. Worker passed; Python reported **580 tests / 537 subtests, 3 failures and 1 error**. Exact failures: `test_lifecycle_and_migration_defensive_guard` still constructed ResumeCloseout without the identity fixture; `test_failure_preserves_actual_state_without_legacy_rollback` indirectly inspected host source permissions through an unmocked failure-reporting helper; `test_pending_origin_complete_deterministic_deployment_and_release_order` and `test_failure_at_tag_publication_reports_main_already_promoted` still read the protected diagnostic/runbook directly during fake preflight. Local VPS files had masked the last dependencies. These are fixture portability defects, not production-code changes. The missed constructor now uses the scoped identity fixture; the observation-only test explicitly mocks and asserts non-normalizing permission inspection; fake end-to-end campaigns now bind disposable protected files. Existing failure/refusal/order assertions remain intact. The failed log is preserved as `evidence/github-ci-36502696289-failed.log`; the failed run was not bypassed or retried unchanged.

The first local fixture correction then exposed an additional permissions-dependent branch: the real root-only configuration directory on the VPS raised before the permission-inspection assertion, while an absent directory on GitHub did not. The failure-reporting fixture now binds both configuration and permission probes explicitly to disposable/mocked observations. This intermediate failed log is retained as `evidence/full-regression-fixture-observation-failed.log`; the once-only observation and no-recovery/no-process assertions remain enforced.

Corrected local full regression again passes **580 tests / 540 subtests; 0 failures/errors/skips/network attempts**. Focused Phase 6 remains **156 tests / 166 subtests PASS**, reused because the corrections changed only inherited Phase 4/5 test fixtures and documentation. Subsequent candidate history contains only those fixture corrections after the staged-deployment executable implementation; the final exact candidate and GitHub job counts are bound in the external summary and CI evidence. Compileall and whitespace checks pass. All production/provider mutation counters remain zero.

### Exact GitHub portability validation — PASS

Executable/test candidate **`94e3e1d6f9c74dcef8507cddc83172a89ce7c261`** passed GitHub **Validate API Platform run 36503022829**, [exact run](https://github.com/yboucher97/opticable-api-platform/actions/runs/36503022829), on the Phase 6 pull request. Python job **109198035751**: **580 tests / 540 subtests; 0 failures/errors/skips/network attempts**, 18.105 seconds. Worker job **109198036017**: **PASS, wrangler deploy --dry-run only**. Both jobs and the workflow concluded success. The original 79 errors and all four residual host-fixture defects are resolved without reduced suites or host-user provisioning.

The final publication update is documentation-only relative to that exact successful candidate; it does not alter executable/runtime/test/deployment/workflow behavior. Its branch SHA and own CI result are recorded in `/var/tmp/optibrain-phase6-validation/gate-g-engineering/summary.json` and `evidence/github-ci.json`; the successful executable-candidate job logs remain preserved by run ID. Runtime/deployment implementation remains `6d8a21fe2bdca43c6d13f4dea59f531d4fb97e9c`, with subsequent changes limited to inherited fixture corrections and evidence docs. Final local full **580/540** and focused Phase 6 **156/166** results are reusable because the final update changes documentation only.

**Gate G engineering remains BLOCKED for release/readiness** pending sanitized privileged receipts/effective authenticated state and deployment identity, separate authorization to install the prepared hardened root wrapper, reviewed live rollback/workflow compatibility, and fresh authoritative VPS validation of the final exact published branch SHA. No merge, deploy, tag rewrite, production config/service change or provider action occurred. Production/main/recovery remain the Phase 5 baseline; protected master/diagnostic hash and metadata checks pass unchanged.


## 2026-09-29 — Gate G CRM containment, static trust ordering and preservation recovery

Engineering resumed from exact published candidate `67014c48cf8b0a0941648127f2216b56b2afad0a`. Original Gate F executable evidence remains `5921473c06470aafae2003607b0a8c85c25f0caf`; none of its results are inherited for changed runtime/security code. Production/main/Phase 5 recovery remain `52f11d4fc14d8582c03837e0317f849efe8aa3d7`. The exact new published candidate, CI run and authoritative test counts are recorded in `/var/tmp/optibrain-phase6-validation/gate-g-authoritative/summary.json` after commit; this entry does not claim those outstanding gates have passed.

The root-collected read-only evidence has passed for effective fixed-wrapper sudo, forced-key restrictions, service identities/no unexpected drop-ins, absent CRM/draft/outbound flags in config/process, authenticated automation (297 completed; zero queued/running/failed/backlog/quarantine), healthy services/timers, local baseline generation `20260928T190202Z` and matching encrypted `download_hash_verified` receipt. Canonical health is `https://optibrain.opticable.ca/v1/system/health`. These completed observations are preserved. Seven generations were observed; exact older archive identities/milestone classes/off-host coverage, stored workflow hashes, effective SSH configuration and GitHub/recovery credential identity still require additional read-only evidence.

**Legacy writer trace and containment.** Inbound lifecycle API/event ingestion → `customer.lifecycle.lead.intake` → legacy Lead upsert/follow-up → `customer.lifecycle.lead.synced` → AI qualification (`promotion_allowed`) → `lifecycle.crm_promote_lead` → Accounts POST / Contacts POST or PUT / Deals POST or PUT. Automation API events/manual workflow runs/redrive, scheduled or emitted events and durable queued snapshots could also invoke these registered actions; disabling only the YAML would not protect persisted work. The four legacy CRM workflows are now disabled, five legacy CRM actions refuse before input parsing/provider access, and their mutation bodies are removed. AI classification remains advisory, with `promotion_allowed=false` and a recommendation field. Read-only CRM search/report/finance compatibility remains tested.

The shared gateway rejects every CRM mutation lacking an exact non-serializable, single-use grant from the existing journaled Phase 6 reconciler. Only bounded reviewed-version Lead PUT and deterministic internal Task POST can receive that grant with the exact Phase 6 opt-in flag. It binds client/method/path/body/version; checks live policy again after OAuth and before transport; rejects Account/Contact/Deal CRUD, metadata/watch mutations, conversion, owner changes, serialized approvals, generic `confirm`, encoded/traversal paths and method overrides. Lost-response writes never fail over or reuse a grant. There is no alternate direct CRM HTTP implementation: remaining reconcilers/generic/API/scheduler paths share this gateway. Native subscription renewal/metadata apply mutations are deliberately unavailable until separately reviewed; read-only verification remains available. Production flags and provider state were not altered.

**Deployment trust.** The prepared root wrapper now embeds a static stdlib verifier and performs health-only reconciliation, never executing candidate scripts. Authorization, policy-file ownership/parents, exact reviewed SHA, repository/CI identity, backup receipt/archive hash, recovery reference and completed gates precede fixed-repository metadata/ancestry checks. Production Git runs as its owner, not as root. The forced command accepts exactly `deploy SPACE 40-lowercase-hex`, uses fixed `/usr/bin/sudo`, and refuses refs/URLs/extra args/newlines/metacharacters. The separate static human-root loader verifies baseline backup/receipt, root-private exact approval, production/main/recovery/branch/CI/ancestry before candidate blobs are considered. It validates a link-free archive and reviewed campaign digest, builds trusted root-owned source/Git configuration and uses the system interpreter before invoking the selected campaign. No loader/wrapper installation, privileged campaign execution or credential change occurred. The installed old wrapper remains a release-blocking unsafe pre-validation execution path.

**Backups and recovery.** Maximum-five was an implementation assumption. The proposed campaign preserves all generations, verifies sidecars/hashes and byte headroom (max of 4 GiB or six largest restore workspaces plus two largest archives), and refuses changes to original generation hashes. The backup primitive has explicit `--preserve-existing`; normal installed retention remains unchanged. A black-box temporary-repository test preserves seven historical archives and sidecars even with retention=1 while creating/verifying an eighth fixture archive. Before any future execution, a separately approved retention hold must leave the scheduled backup timer inactive; engineering did not stop timers or delete/move backups. Production-owner Git prevents root execution of mutable checkout configuration in the reviewed primitive.

An isolated baseline → candidate → baseline-code probe on copied fixture state → corrected-code recovery exercise proves schema V2 reads, event/dedupe state, durable consumed/manual/consuming approvals, queued snapshots, provider-operation journals and persistent files. Baseline API health reports 1.10.0 and can read the state, but its legacy queued promotion invokes fake CRM writers: **direct baseline dispatch is unsafe**. Corrected forward recovery blocks that queued write and preserves non-reusable approvals/journals. No DB replacement, schema migration, automatic rollback or live-state exercise occurred. Live administrator identity/current-backup recovery approval remains a blocker.

Stored workflow provenance is now checked for disabled rows as well as enabled rows; unexplained hashes/custom definitions block before internal smoke or promotion. Candidate baseline/shipped hashes are reproducible through `WorkflowDefinition` canonical normalization. Actual persisted hashes remain pending the additional pinned root collector; hashes were not inferred from workflow IDs or source-path labels.

**Validation and failures retained.** The engineering suite passed **617 tests / 683 subtests**, failures/errors/skips/blocked network attempts **0**, before commit. Focused Phase 6 passed **193 tests / 309 subtests**, failures/errors/skips/blocked network attempts 0. Exact-candidate reruns will be recorded in the external authoritative summary. Compileall, shell syntax and whitespace checks passed. Earlier logs preserve the initial 602-test/609-subtest run with three errors: two incomplete new gateway settings fixtures and one existing native-subscription test that regenerated reviewed expiry across repeated calls; the fixture now binds one expiry without weakening single-write/manual assertions. A newly appended workflow-hash test had an indentation collection error; placement was corrected, no test was removed/skipped, and its failed log is retained. An adversarial method-override test also showed headers were stripped instead of explicitly refused before OAuth; the gateway now rejects those headers immediately. Its two attempted fake GET transports were blocked by the socket guard, with no network/provider operation performed. The final suite reports zero blocked attempts. The recovery exercise initially omitted the required audit success argument; that failed log is also preserved. All failures were resolved before publication, never promoted as PASS.

Gate G remains **BLOCKED** until the exact new SHA passes GitHub CI and fresh isolated authoritative VPS validation, root-only archive/workflow/SSH provenance is complete, GitHub/SSH/recovery identity is verified, the installed unsafe wrapper is replaced under separate authorization, and retention/recovery prerequisites are explicitly approved. All work was branch-only or isolated/read-only. Real provider writes, customer sends, CRM mutations, Books mutations, Lead conversions and production changes during engineering are **0**. No main merge, deployment, recovery-tag mutation, environment/DNS change, service restart or outbound registration/enablement occurred. The protected diagnostic and privileged master runbook remain unchanged; this non-privileged supplement is the normal engineering/runbook update.


### Exact-head CI correction before final selection

Commit `720020b0f8bbab8e43c87a67660d3a18cb46a132` published the containment/recovery changes. GitHub validation run **36509205714** passed both jobs, with Python **617 tests / 683 subtests**, zero failures/errors/skips/network attempts. Its log nevertheless showed the default PR synthetic merge checkout (`59301b2…`, merging this candidate into the unchanged Phase 5 baseline). Although its code tree matched the candidate, the final validation must bind commit identity too. Both validation jobs now explicitly check out `${{ github.event.pull_request.head.sha || github.sha }}`; Python retains full history for the pinned baseline recovery fixture. This following commit changes only CI checkout configuration and this record. Original passing job logs are preserved as `gate-g-authoritative/github-720020b-*.log`. Final exact-head CI and authoritative VPS validation must select the published SHA containing this correction; deployment remains unauthorized/skipped.


### Loader archive canonicalization review

Exact-head CI for `44bfb52895effd5f32e52625a83d917f14b6196b` passed run **36509466920** (both jobs, Python 617/683) and its isolated VPS validation passed 193/309 focused and 617/683 full. Final source review then identified that `Path.parts` normalized dot/empty segments before validation, leaving a potential archive-member alias of the approved campaign path. The prepared loader now validates raw POSIX components, rejects empty/dot/parent/Git/backslash/NUL components and deduplicates canonical directory/file identities before extraction. Four new adversarial subcases cover dot aliases, doubled slashes and Git-path aliases. The loader remains uninstalled/unexecuted; no privileged production code was exposed. This security change supersedes 44bfb52 as the final selection and requires fresh exact-SHA CI/VPS evidence, retained in the external authoritative summary. No production/main/recovery/protected changes occurred.

The same final review hardened the inline root verifier against working-directory/module and executable lookup substitution: it now uses fixed `/bin/bash`, `/usr/bin/env` and `/usr/bin/python3 -I -`. A malicious `json.py` in a disposable deploy-user working directory is not imported. The forced-command bootstrap also uses fixed `/bin/bash`. These stdlib isolation checks occur before any release-policy data is interpreted; no installed wrapper was changed.

The loader additionally verifies the complete archive file set and every file's Git blob identity against the authorized commit tree before extraction/execution. It rejects omitted or transformed helpers (including export-ignore/export-subst effects), not merely a matching top-level campaign digest. Adversarial modified/omitted-helper cases and a real current-commit archive round trip prove the full-source binding.

Before this final security correction was committed, focused Phase 6 passed **196 tests / 315 subtests** and full regression passed **620 tests / 689 subtests**, with failures/errors/skips/blocked network attempts **0**. Compileall, shell syntax and diff checks passed. The final published exact SHA still requires its own GitHub and isolated VPS reruns; their evidence belongs to the external authoritative summary, without changing the protected master runbook.
