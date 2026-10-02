> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# Phase 5 engineering and recovery record

Date: 2026-09-28 UTC. Specification: [authoritative campaign](OPTIBRAIN_PHASE5_AUTONOMY_CAMPAIGN.md). Architecture and provider limitations: [architecture](OPTIBRAIN_PHASE5_ARCHITECTURE.md).

## Identity and development isolation

- Exact production baseline: `209aac07160e1376381faebd86fb38a18f92582a`.
- Required branch: `hardening/phase5-business-autonomy-v1`; isolated worktree `/var/tmp/optibrain-phase5-business-autonomy-v1`.
- Campaign specification commit: `c55f9562fc592adcd7edfcdce269c5b90cb76253`.
- Production checkout remains detached at the exact baseline during development; service API `1.9.0` remains active.
- Remote `main` remains the baseline. Phase 4 recovery tag `recovery/post-phase4-durable-events-v1-20260928` peels to the baseline.
- No new schema: existing automation DB `user_version=2` and audit table are reused.

The live checkout was initially switched to the campaign branch, which contained only the specification change, then restored to the exact detached production baseline before implementation. Application development occurred in the isolated worktree. The production service was not stopped or migrated during development.

## Live inventory and governed configuration

[Before snapshot](phase5/crm-inventory-20260928.json) is deterministic and redacted. Its content hash is `6fd24967d89538992a8a29736879379c39bd7e0775e1f15916676e7f3bad5fb4`. It includes modules, operational fields/layouts/relationships, picklists, three complete workflow rules, workflow tasks/field updates, hooks, assignment/scoring/validation/cadences and safe function/button metadata. Unavailable reads remain unknown, never empty. The existing CRM organization is `5062683000000020005`, with a verified paid enterprise/Zoho One license.

[Supplemental metadata](phase5/supplemental-metadata-20260928.json) captures the internal notification action and relevant Source/Industry global picklist values. Embedded conversion mappings capture actual topology. Buildings metadata and unsupported module-specific APIs remain explicit limitations; privileges were not expanded.

The final [live governance plan](phase5/live-governance-plan-20260928.json) verified all 93 managed existing resources as `noop` using 14 live GET calls and zero writes. Plan hash: `9049109e8503ff217a2d087db5cd56a48122d64c3179c141ba49c51218632a45`. The genuine gaps were two optional Lead fields; existing attribution, qualification, owner, consent and Deal taxonomy were reused.

## Live additive writes and recovery

Before the first provider mutation, the snapshot, exact document, immutable plan, duplicate/semantic review, provider limits and leave-unused rollback were recorded. Live workflow limits were 2,500 total/2,000 active, three total/active currently; existing Lead field capacity had ample headroom. This was an additive optional-field operation, not a workflow migration.

| Leads field | Provider ID | Definition | Result |
| --- | --- | --- | --- |
| Service_Types | `5062683000007833001` | Optional text, length 255, label Service Types | Single POST; HTTP 201; immediate readback and final noop |
| Next_Followup_At | `5062683000007832003` | Optional datetime, label Next Followup At | Single POST; HTTP 201; immediate readback and final noop |

Reviewed plan hash: `1442a4c7660c9dcb878caf4c21e3d7d499c6bf3437103810cb7dc79340d5effd`. [Review](phase5/additive-plan-review.json), [durable apply evidence](phase5/live-field-apply-20260928.json), [changed entries](phase5/crm-inventory-changes-20260928.json), and [drift](phase5/live-drift-20260928.json) preserve exact identities and before/after hashes. After hash: `ea144ba3c4e9e58370b037f4a030b8815893a3a30f0a1a143c5bdb1d99484bb6`.

Only Leads fields and the provider's default Standard layout placement changed. No layout PATCH, record write, Books mutation, workflow replacement, function mutation or hook deletion occurred. All three rules remained active; both legacy hooks remained unassociated. Provider request IDs were absent and were not treated as idempotency permission.

Rollback: leave the optional fields present and unused, disable the new local observer/policy if necessary, and preserve CRM data and intent evidence. Removing fields is destructive and requires separate approval. Never create a new evidence database to evade unresolved intent from an interrupted apply.

## Implementation and failure work

Changes extend `desired_state.py`, field reconciliation, authenticated API and the existing delta runtime. New modules provide metadata projection/inventory, the existing-audit-table journal, metadata/native notification adapters, periodic read-only drift, CRM delta fallback and Phase 3 lead actions. Git configuration adds two governance/addition documents, one notification template with environment references, and two lead workflows. Recovery/deployment tools reside under `ops/phase5`; no protected recovery file or backup policy was rewritten.

Failures found and corrected:

1. The original field fake did not reflect successful writes, so the stronger immediate-verification test failed. The fake now models provider state; verification was retained.
2. Early JSON-lines bridge reads hit TTY canonical input limits. Echo/canonical buffering was disabled for the controlled bridge. These attempts produced blocked plans before any write.
3. Native notification references were initially rejected by generic secret-key redaction. Only validated uppercase environment-variable references are now allowed; actual credentials remain rejected/redacted.
4. A child-event/alert crash window could lose an internal alert. Both now commit in one SQLite transaction; an injected audit failure must roll back both.
5. Native events use `zoho.crm`, while delta checkpoints enforce `zoho_crm`. The observer now accepts both. The native test verifies a completed route and alert, not just an accepted HTTP delivery.
6. Live pinned workflow/webhook reads rejected a `module` query. The first live governance plan safely blocked five resources without writes. Correct requests subsequently verified 93 noops.
7. A legacy off-host test used a fixed old backup filename that aged out of the 36-hour rule. Fixtures now use the current generation with explicit stale/future comparisons; the production freshness check is unchanged.
8. Root umask `077` can remove directory traversal bits even when `mkdir` requests them. The new configuration/staging directories explicitly receive their intended modes, and configuration is tested under `077`.
9. Native reconciliation accepts only the reviewed Phase 5 channel and its exact authentication references, preventing use of this adapter to read or forward unrelated service secrets. Resolved native authentication references now contribute a one-way configuration hash to the immutable plan. A credential change after review rejects apply before any network mutation; plaintext credential values remain absent from plans/audits.

Failure drills cover accepted mutation/response loss, before-send timeout, unknown after-send outcome, duplicate/stale apply, concurrent controllers, failed readback, 401/429/5xx, native duplicate/collision/expiry, capture-before-routing restart, child/alert transaction failure, event replay, task dedupe and persistent manual state. Existing Phase 3/4 tests continue to cover accounting approval, worker ownership/leases, unsafe replay, quarantine, watchdog, migration discipline and source materialization guards.

## Deployment and recovery procedure

The final candidate is identified by the immutable commit argument and the checked-in clean required branch. `ops/phase5/production_campaign.py --plan --candidate <40-hex-sha>` is read-only. Actual deployment requires the existing human root authentication boundary; arbitrary root execution is not available to the agent. No sudoers, service identity, auth boundary or provider scopes are expanded.

The root campaign holds the existing deployment lock and completes these gates in order:

1. Verify candidate ancestry/clean branch, exact live baseline, remote main/Phase 4 recovery tag, protected files, authentication, schema-v2 readiness/watchdog and zero failed units.
2. Run the complete candidate workflow suite. Create a fresh normal-policy backup, verify checksum/manifest/source identity, run the existing isolated archive restore verifier and the Phase 5 drill against the actual restored production v2 database.
3. Require live governance/addition noops. Record a predeployment recovery tag. Recheck health and source before stopping the service.
4. Stop the service, require no unresolved work, fast-forward the detached production checkout, reuse Phase 4 tracked-source mode normalization and service-identity readability checks. No migration; main remains baseline until all later recovery gates pass.
5. Add root-owned service-readable callback/sync configuration beneath the already backed-up `/etc/optibrain/phase5` tree. Generate the private native token inside the root process; preserve existing channel/job configuration. Keep lead record writes in observe policy.
6. Start candidate API `1.10.0`, verify fresh watchdog/authenticated health/safe internal smoke. Create the native subscription through the same Desired State engine and require immediate noop verification.
7. Commit the synthetic delivery identity before the public HTTP request; prove authenticated intake, completed routing and duplicate suppression with zero CRM record writes. Verify the bounded CRM delta fallback GET. Record genuine native-origin evidence as durable pending/verified without waiting for a customer event.
8. Reverify live noops/health, create and restore a fresh postdeployment backup, repeat the actual restored-v2 drill, and verify encrypted off-host generation/source hash/download hash through the unchanged uploader.
9. Require protected files/source modes/zero failed units/final authenticated health/schema V2/candidate source and exact baseline remote main. Fast-forward main through the reviewed advertised-old-OID pre-push guard and require candidate readback. Only then create/publish the final post-Phase-5 recovery tag. Recheck authenticated health, protected files and exact candidate/production/main/tag equality before PASS. Provider-origin pending does not block this deterministic completion model.

Private root evidence is written under `/var/lib/optibrain/phase5/<UTC>-<suffix>/`. `progress.json` and `result.json` record stage, actual source/service/database observations, backup/archive digests, restored-copy results, provider evidence, off-host generation and recovery identities. If a gate fails, the campaign preserves the observed v2 database/source/service state. It never invokes the inherited V1 rollback, blindly repeats a provider operation, restores an old DB over new events, or reverses CRM writes.

Recovery requires reviewing the fixed stage and observed state first. After a service stop/start failure, verify actual HEAD, schema, unresolved work and source modes; start only the proven source/configuration after correcting the diagnosed problem. Restore damaged state only from a separately checksum-verified backup into isolated staging first, with explicit operator authorization for production replacement. After an ambiguous subscription write, read the pinned channel and journal together; a matching readback is evidence for human reconciliation, not permission to issue another POST. Preserve the same channel/token/configuration and unresolved audit entry until reviewed. The exact reviewed renewal policy now advances an already verified channel before expiry through the existing Desired State engine. Matching readback can reconcile only the same durable renewal intent/configuration; uncertain or mismatched state remains manual with no second write. Expired/missing native channels never stop delta reconciliation.

The unchanged off-host model deliberately keeps the age private key off this host. Downloaded ciphertext/hash verification is the deployment gate; this campaign does not claim an offline decrypt/restore ceremony with an unavailable external private key.

## Implementation commits

- Control plane and lead intake: `61b1eb33a94aa1d7eb401b7b0d15ace17ab86ba3`.
- Verified CRM desired state and evidence: `681cc00dcb22a3ccca08d66f2051cda847048efc`.
- Pinned deployment/recovery preparation: `c4dd0119707616e09cfdd4602be0cca7fdd92d93`.

The final documentation commit is included in the clean candidate SHA supplied to the root campaign. The campaign records that exact candidate and published production recovery identities.

## Completion status

Previous reviewed candidate validation: 386 workflow API tests, 325 subtests, zero failures/errors/skips; six deployment-driver tests were included. The superseding hardening validation below is authoritative for the new release. Administrator security/recovery: 37 tests PASS. Backup/off-host Python regression: 11 tests PASS. Backup, uploader/unit, bucket-listing and R2-health shell regressions PASS. The unprivileged backup shell run intentionally does not claim its root ownership variant; production gates execute under the required identities.

Candidate validation results and exact safe evidence are in [validation](phase5/candidate-validation.json). Unprivileged isolated schema-v2 startup, process/worker restart, dedupe, backup/restore and ambiguity drills passed on a fixture copy. This is explicitly distinct from the root gate against an actual restored production archive.

The existing limited helper reported health PASS and latest archive verification PASS. Its backup command stopped at conservative retained-generation headroom, and its latest restore command returned a fixed failure category. Neither is counted as a fresh pre/post Phase 5 backup/restore PASS. The prepared root campaign uses the unchanged normal backup policy and current checked-in restore verifier, and stops with evidence if those gates fail.

Production deployment, native subscription/callback, fresh actual-production backup/restore and matching encrypted off-host gates remain pending human root invocation. Final candidate commit, production/recovery tag SHA, archive digests and off-host generation are recorded by that pinned root campaign; they are not fabricated here. `OPTIBRAIN_PHASE5_COMPLETE: PASS` is forbidden until every applicable gate has actually passed.

## Superseding production-review hardening — 2026-09-28

Previous reviewed candidate: `5a3364d74510786de56f30731e47f3c2546c0331`. New logical implementation commit: `0ce2612f6b3d227100865762bd7cce9e567bf550`; existing history is retained. The final candidate includes the subsequent evidence/documentation commit on `hardening/phase5-business-autonomy-v1`.

The candidate recovery tag is `recovery/phase5-business-autonomy-v1-candidate-hardening-20260928`. Its annotated message is the immutable release manifest: exact final candidate SHA, Phase 4 merge base and SHA256 of `git diff --binary 209aac07160e1376381faebd86fb38a18f92582a <candidate>`. Keeping the final SHA/diff hash in the annotation avoids a self-referential committed hash. The previous candidate remains an ancestor; existing tags are preserved. This candidate tag does not claim a deployed recovery point. Final post-Phase-5 recovery publication remains gated on production verification and main promotion.

The three production-review fixes are implemented: deterministic deployment plus durable provider-origin pending/verified evidence; exact reviewed automatic native renewal through the existing Desired State journal; and final fast-forward-only remote main promotion after every production/recovery gate, followed by tag publication and final identity equality. The separate architecture section describes authentication, ambiguity and fallback limits.

A separate self-review pass found and corrected: stale callback expiry after provider renewal; an old verified health observation masking changed authentication; identity aliases bypassing channel journal identity; failure evidence assuming unchanged main when its state was unknown; and the preflight/push remote-main race. Focused tests retain all those cases, including actual isolated Git transport tests. This is self-review, not a claim that another person approved the release.

Validation: **419 workflow API tests and 374 subtests**, zero failures/errors/skips. Phase 5 tests: **94 tests and 70 subtests** (included in the full suite). Administrator security/recovery: **37 tests PASS**. Backup/restore/off-host Python: **11 tests PASS**. Backup, uploader/unit, bucket-listing and R2-health shell suites PASS; uploader shell repeats nine of the Python tests. Diff whitespace, compileall, script syntax, credential-pattern scan and cold Git bundle restoration are required and recorded in [hardening validation](phase5/hardening-validation-20260928.json). Restored fixture-V2 startup/process and worker restart, dedupe, ambiguity/replay protection and backup/restore drill PASS without migration. The actual restored production V2 and live encrypted off-host gates remain root deployment work.

Live read-only revalidation confirmed `Leads.Service_Types` (`5062683000007833001`, text 255) and `Leads.Next_Followup_At` (`5062683000007832003`, datetime) as two canonical Desired State noops; plan hash `71040e826d661c7e7f5f9bed85876eed09e4f314a32fabcdd1d9af1d85ce2778`. All three existing workflows remain active, and both legacy hooks remain present/unassociated. **No live CRM/Books mutation occurred during this hardening.** The two field additions from the earlier campaign remain unchanged.

Production remains detached Phase 4 `209aac07160e1376381faebd86fb38a18f92582a`, active API 1.9.0; remote main remains that exact baseline. The fixed authenticated helper health check passed. Protected diagnostic hash/mode/owner/mtime and root recovery runbook hash/mode/owner/mtime remain unchanged. No root deployment was attempted. The final pinned command is supplied only after engineering verification; production PASS is not claimed here.

### Production callback-gate correction — 2026-09-28

During the first resumed Phase 5 production closeout, the
`authenticated-public-lead-delivery-drill` blocked even though the production
API, DB V2, native subscription readback, governance noops and safe production
smoke were healthy.

Root cause: `/v1/automation/webhooks/{endpoint_name}` intentionally returns
HTTP 202 after durable webhook capture, while
`ops/phase5/production_provider.py --mode notification-proof` incorrectly
required HTTP 200 for both the accepted delivery and the duplicate delivery.

The gate was corrected to require the actual HTTP 202 API contract. A focused
regression test now proves that a 202 accepted response followed by a 202
duplicate response completes the synthetic notification proof, remains
classified as synthetic, does not promote provider-origin evidence, and
performs zero CRM record writes.

No Zoho subscription retry, CRM record mutation, Books mutation, or main-branch
promotion was performed as part of this correction. Production remained on the
previous Phase 5 candidate while the corrected candidate was validated.

### CRM delta HTTP 304 correction — 2026-09-28

During resumed Phase 5 production closeout, the authenticated public webhook
and duplicate-delivery gate passed, but the read-only CRM delta fallback gate
blocked with `SyncFailure`.

Read-only production diagnostics proved the configured Leads checkpoint
remained at revision 0 with its original cursor and no successful advancement.
The apparent `network_timeout` was not a network failure: Zoho returned HTTP
304 Not Modified to the conditional `If-Modified-Since` Get Records request.

`CrmLeadDeltaAdapter` already defines HTTP 204/304 as a valid empty incremental
window. The incompatibility was in `ZohoGatewayClient`, which treated every
non-2xx response as an error before the adapter could inspect status 304.

The gateway was corrected narrowly so only HTTP 304 on GET is considered a
valid local provider response. Mutations and all other non-2xx responses remain
fail-closed. A gateway regression proves a 304 conditional GET returns locally
with `ok=True` and never invokes standby. A CRM-delta regression proves the
same response becomes an empty successful page with an advanced observation
cursor.

No Zoho write, CRM record mutation, Books mutation, notification subscription
retry, checkpoint cursor advancement, or main-branch promotion was performed
as part of diagnosing or engineering this correction.

At the time of this correction production was running the superseded Phase 5
candidate `16bcf566562b08c316b2984565079f7bd3c25841`, while `origin/main`
remained the Phase 4 baseline `209aac07160e1376381faebd86fb38a18f92582a`.

### Restored V2 isolated-health correction — 2026-09-28

After the Zoho conditional-GET HTTP 304 correction passed in production, the
postdeployment backup itself completed successfully and its archive, manifest,
database/config/source extraction, and isolated archive verification all
passed.

The subsequent disposable restored-V2 API drill blocked only at the
`health_alerts` assertion. A second disposable diagnostic reproduced the
failure without touching production and showed exactly one alert:
`native_subscription_degraded`.

This warning is expected in the Phase 5 isolated restore environment. The
restored database contains the verified native Zoho subscription evidence, but
the drill intentionally launches with no webhook or sync configuration and no
provider credentials. Native health therefore correctly reports the missing
runtime binding as degraded/configuration drift.

The isolated drill health policy was corrected narrowly. The inherited Phase 4
drill now accepts an optional explicit warning allowlist; its default remains
strict and accepts no alerts. Phase 5 supplies only
`native_subscription_degraded`. Critical alerts and every other warning remain
fatal to the restore drill.

The backup was not weakened, production health rules were not changed, native
subscription verification was not bypassed in production, and no Zoho/CRM/
Books mutation or subscription retry was performed.
