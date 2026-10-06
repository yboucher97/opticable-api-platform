# BUSINESS LIFECYCLE TRUTH REMEDIATION: PASS

Implementation and bounded current-evidence validation passed locally. Incomplete source history is preserved as uncertainty; this pass does not claim every customer's current state is known. No new numbered phase was created.

START SHA: `c22d409d96671e8b78e21ca72a4a76ea4c80879b`

BRANCH: `remediation/lifecycle-truth-priorities-20261006`

FINAL HEAD: `HEAD`, the local commit containing this report. Resolve with `git rev-parse HEAD`; its exact post-commit SHA is also recorded in `/tmp/optibrain-lifecycle-current-20261006/commit-receipt.json` and the final owner response. A commit cannot embed its own hash.

PUSH: NO

DEPLOY: NO

MERGE: NO

Candidate API **1.29.0** is unchanged; no version collision was introduced. A separate later release could propose **1.30.0**, subject to the existing release lineage, without assigning it here. Preview commit `75c6a2b69dcbfc28ccb4eebcedae020c1f4d1738` is a one-commit descendant of the start SHA and absent from this branch. It was neither merged nor recreated.

## NOVECO ROOT CAUSE

**Old evidence:** October 2 service inquiry and October 5 draft estimate versions in the unchanged business projection. The overnight narrative used potential AV/access scope gaps and quoted value to assign a first-hour task.

**Newer authoritative evidence:** fresh October 6 native Books reads already contained `status=sent` for EST-1132/1133/1134, with newer October 5 source versions. The report itself acknowledged them. The owner's current correction establishes actual sent state at high confidence, without inventing a send timestamp.

**Why old action survived:** observations and recommendations lacked a shared exact-object lifecycle/actionability reconciliation. The old business cache stayed draft; Sales required retained CRM Deal linkage, missing on these estimates; the conversation path followed Apollo-linked replies. The standalone narrative still treated potential scope concerns as current required work despite recognizing sent state. There is no Noveco SQL priority row to blame: all 46 priorities and 33 proposals were inspected.

**Root cause classification:** multiple — stale projection, missing event/linkage, lifecycle/precedence reconciliation gap, derived recommendation persistence and priority actionability gap. No proven arithmetic timestamp-sort bug or blanket CRM-precedence rule is claimed. [Full reproduction and source IDs](root-cause.md).

## GENERIC FIX

| Component | Result |
|---|---|
| Event model | Deterministic exact commercial-object facts and compatible progression; explicit revisions/replies can establish newer work. |
| Source precedence | Fact-specific authority, identity confidence and event/source time; proposals/priorities cannot assert source truth. |
| Latest-event logic | Occurrence time leads; source versions distinguish updates to the same occurrence. Observation freshness never changes business event time. |
| Derived state | Separate source facts from ephemeral current state/action; retained in the existing journal architecture without a new database. |
| Next action | One shared contract used by Manager/brief, Sales conversations, Sales estimate intelligence, shared Sales Today ranking and read-only audit. |
| Waiting state | Sent/answered, provider/time/deferred states can produce `NO_ACTION`; no padded tasks. |
| Follow-up due | Actual send anchor plus exact authoritative current Task/rule; existing scoped business-day reminder policy remains intact. No applicable policy/date means `POLICY_UNKNOWN`. |
| Reply verification | Complete scoped inbound/outbound history required for a negative reply conclusion. Unknown response status yields verification, never a send-now instruction. |
| Priority invalidation | Current projection marks superseded/replacement state; old records, drafts and reports remain historical. |
| Ranking | Actionability/dependencies/source readiness gate first; imminent hard deadline before importance, then confidence/freshness and supported business factors. |
| Owner correction | Authenticated exact-version local assertion with actor/time/reason code; recomputation, suppression and subsequent provider supersession; no provider edit. |

[Event precedence](event-precedence.md), [contract](next-action-contract.md), [owner correction flow](owner-feedback.md).

No LLM is required. Low-confidence free-text intent cannot automatically accept/decline/revise a quote. Exact invoice relationships suppress old quote work without requiring perfect historical chronology. Separate estimates/projects and explicit native revisions prevent company-wide state merging. Existing Apollo ownership, provider boundaries, read budgets, cache preservation and independent optimization domains remain in place.

## NOVECO AFTER FIX

Current state: **SENT_RESPONSE_UNKNOWN** on each of the three exact estimate objects.

Latest event: **OWNER_VERIFIED_FACT / QUOTE_SENT**, assertion October 6 13:09:42 UTC, corroborated by Books native sent states. Actual send occurrence date remains unknown.

Next action: **NO_ACTION**. Follow-up applicability/date: **FOLLOWUP_POLICY_UNKNOWN**.

Actionable: **NO**.

Confidence: **HIGH** that quotes were sent; later response/completion/current follow-up policy remain unknown.

Neither `FINISH_QUOTE` nor a speculative today follow-up survives. This is deliberately more precise than asserting no later customer reply. [Exact per-object replay](revalidation.json).

## OTHER OVERNIGHT TOP ITEMS

| Item | State / next action | Confidence |
|---|---|---|
| ANJOU80 | INQUIRY_RESPONSE_UNKNOWN / VERIFY FIRST for latest Mail/Sent/phone/ownership; no supported urgent due date | HIGH inquiry; current qualification/response need unknown |
| ART SYSTEMS | DELIVERABLE_PROMISED / VERIFY FIRST whether corrected handwritten document/page initials already delivered | HIGH promise; completion unknown |
| MAISONNEUVE | TENDER_OPEN / urgent VERIFY FIRST eligibility, addenda and prior submission; go/no-go before October 7 10:00 EDT | HIGH recorded deadline; qualifications/submission unknown |
| MONT-ROYAL | TENDER_OPEN / OPTIONAL research, verify fit/eligibility/prior action before pursuing; October 27 11:00 EDT | HIGH recorded notice; actual current bid readiness unknown |

The fifth original group, operator release/recovery closure, stays separate from commercial lifecycle; no release or fresh remote PR read was performed. [All 35 contexts, drafts and expansion hypotheses](current-business-revalidation.md).

## CORRECTED OWNER TOP FIVE

Only three urgent business verification actions are justified:

1. **Maisonneuve:** check current deadline/addenda, existing submission and eligibility; make a short go/no-go. Deadline October 7 **10:00 EDT**. Reason `TENDER_DEADLINE`.
2. **Parc olympique:** verify retained October 7 **10:00 EDT** deadline, addenda, prior participation and qualifying partner/capabilities. This is an older feed observation, not a fresh page confirmation or a bid instruction. Reason `TENDER_DEADLINE`.
3. **Art Systems:** verify whether promised document corrections/page initials were already delivered before repeating the work. Day-only October 6 promise. Reason `PROMISED_DELIVERABLE_OUTSTANDING`.

The candidate's complete Manager Today includes these three plus two independent existing operational diagnostics, Books source health and Growth system health. That does not justify two additional customer tasks. Anjou remains nonurgent verify-first; Support-TI waits until afternoon; Noveco has no current action.

## STALE PRIORITIES FOUND

Count: **5 obsolete recommendation contexts**, comprising **1 report-only Noveco quote group + 4 cached canonical reply contexts**. This is not five stored priority rows.

Actions: Noveco quote preparation superseded; Support-TI waiting in the audited morning; Alsys/G.S.D waiting; Art's old reply superseded and replaced by document-completion verification. Candidate Manager priority projections: **3 SUPERSEDED, 1 CURRENT_DERIVED_ACTION**. Four old Sales reply proposal projections are superseded. All **46 priority records and 33 proposal records** remain.

Measured before/after: obsolete old actions **5 → 0**; duplicate cached reply recommendations **4 → 0**; inspected waiting contexts with old actionable wording **4 → 0**; verify-first converted to send-cleared actions **0 → 0**. The historical overnight draft pack was already conditional, so no additional unsafe sends are invented as a metric. [Grains and limitations](current-business-revalidation.md#measured-change).

## TESTS

| Run | Tests | Subtests | Failures | Errors | Skips |
|---|---:|---:|---:|---:|---:|
| New lifecycle | 41 | 35 | 0 | 0 | 0 |
| Focused/subsystem | 240 | 125 | 0 | 0 | 0 |
| Full workflow application | 1,670 | 1,352 | 0 | 0 | 0 |

Runs overlap; their counts are not added. Full discovery covers `apps/workflow-api/tests`, using the installed application virtualenv. The focused suite includes priority/Today/Manager, Sales, business-observation compatibility, native finance evidence, Sales send boundaries and all three post-phase37 regression modules. Event/source/time precedence, waiting/no action, exact identity/revision/invoice relations, completeness, owner correction/authentication, legacy Manager loads and morning ranking are covered.

G001 bounded-observation/last-good behavior, G002 independent collision completeness and G003 truthful timer health remain passing; release preservation is also covered. Existing expectation changes only reflect the intended move from unverified quote/inquiry action to verification.

All regression runs denied IP socket connection and datagram sends; **0 attempted IP socket operations**, **0 provider network writes**. Read-only evidence replay: **35 contexts**, **3 business actions**, **46 priorities/33 proposals retained**, Manager JSON **828,533 bytes**. No full-Mail scan or new provider collection was added. `git diff --check` passes. [Lifecycle totals](validation-lifecycle.json), [focused totals](validation-focused.json), [full totals](validation-full.json).

Re-run with:

```sh
/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python ops/lifecycle_truth/run_tests.py --suite focused --output /tmp/lifecycle-focused.json
/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python ops/lifecycle_truth/run_tests.py --suite full --output /tmp/lifecycle-full.json
```

## SAFETY

| Action | Count |
|---|---:|
| Emails sent | 0 |
| Apollo sends | 0 |
| CRM writes | 0 |
| Books writes | 0 |
| Ads writes | 0 |
| Conversion uploads | 0 |
| Website deployments | 0 |
| Cloudflare mutations | 0 |
| Authority changes | 0 |
| Native provider reads during this mission | 0 |
| Pushes / merges / deployments | 0 |

Only repository files and isolated test/replay journals were written. Production journals/caches, provider records, expiry policies and historical reports were not changed. Read-only exports used the existing database architecture; raw email bodies and addresses were not committed. The correction is validated in the candidate and replay, **not yet deployed to live Manager**.

## FINAL QUESTIONS

1. **Why did OptiBrain incorrectly tell the owner to finish Noveco's quotes?** It promoted an old inquiry/scope concern into mandatory work without reconciling fresh sent facts or applying a current actionability gate; the product's business projection also remained draft and missed native Deal/conversation linkage.
2. **Was “quote sent” already available?** Yes, Books sent record states were already available and acknowledged in the overnight report. They alone do not prove actual Mail delivery/time; the owner's correction establishes sent state.
3. **Is the bug now fixed generically?** Yes in this locally validated candidate: no company-specific production condition, one deterministic exact-object event/next-action contract.
4. **Can later sent/replied/accepted evidence supersede an older draft task?** Yes; sent, replies, accepted work and exact downstream invoice/payment events supersede preparation or change the action. Explicit revisions can reopen the appropriate cycle.
5. **Can WAITING CUSTOMER produce NO ACTION?** Yes. Unknown reply coverage is distinguished from proven waiting; both can avoid work when no due policy is established.
6. **Can unknown reply status produce VERIFY FIRST rather than FOLLOW UP?** Yes. A due follow-up with incomplete response history becomes verification; no due policy remains no action/policy unknown.
7. **Can stale priorities be suppressed without deleting history?** Yes. Current projections suppress or replace old recommendations; canonical history and historical reports remain intact.
8. **Does owner correction update derived state?** Yes through authenticated exact-version local business facts, tested with immediate Manager recomputation. This mission applied the Noveco facts only to the isolated replay, not production.
9. **Did other top-five items have the same flaw?** Anjou's qualification need and Art's promised completion were not proven still outstanding. Art now verifies delivery; Anjou verifies reply status. Four canonical cached Sales replies also had later owner responses, already recognized by the standalone overnight report. Mont-Royal was useful research, not a due-today action. Tender eligibility/submission remains verification.
10. **What is the corrected top action?** Maisonneuve's current submission/eligibility/addenda go/no-go, supported by a fresh native notice and October 7 10:00 EDT deadline. Parc olympique shares that recorded deadline but has older evidence.
11. **Does Manager explain why an action is current?** Yes in the candidate: current state, reason, latest source fact, actual event date or explicit unknown, confidence, waiting/follow-up and completeness details. Live Manager awaits separately controlled release.
12. **Were G001/G002/G003 preserved?** Yes; all focused preservation regressions and the full suite pass.
13. **Any customer-facing action?** NO. No customer message, provider write, deployment, merge or authority change.
14. **Another foundation phase required?** NO. The shared contract uses the existing storage, observations and owner surfaces; no numbered phase was added.
15. **Next controlled real-world execution?** First perform the private urgent tender verification/go-no-go. The next possible customer execution remains exactly one separately owner-approved Anjou80 qualification reply, only after a fresh bounded Mail/Sent/phone/Apollo ownership check proves it remains needed. Record its receipt and stop. This mission authorizes and performs no send; release/recovery of this candidate remains a separate controlled process.

Machine report: [final-report.json](final-report.json).
