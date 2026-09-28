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

Failure drills cover accepted mutation/response loss, before-send timeout, unknown after-send outcome, duplicate/stale apply, concurrent controllers, failed readback, 401/429/5xx, native duplicate/collision/expiry, capture-before-routing restart, child/alert transaction failure, event replay, task dedupe and persistent manual state. Existing Phase 3/4 tests continue to cover accounting approval, worker ownership/leases, unsafe replay, quarantine, watchdog, migration discipline and source materialization guards.

## Deployment and recovery procedure

The final candidate is identified by the immutable commit argument and the checked-in clean required branch. `ops/phase5/production_campaign.py --plan --candidate <40-hex-sha>` is read-only. Actual deployment requires the existing human root authentication boundary; arbitrary root execution is not available to the agent. No sudoers, service identity, auth boundary or provider scopes are expanded.

The root campaign holds the existing deployment lock and completes these gates in order:

1. Verify candidate ancestry/clean branch, exact live baseline, remote main/Phase 4 recovery tag, protected files, authentication, schema-v2 readiness/watchdog and zero failed units.
2. Run the complete candidate workflow suite. Create a fresh normal-policy backup, verify checksum/manifest/source identity, run the existing isolated archive restore verifier and the Phase 5 drill against the actual restored production v2 database.
3. Require live governance/addition noops. Record a predeployment recovery tag. Recheck health and source before stopping the service.
4. Stop the service, require no unresolved work, fast-forward the detached production checkout, reuse Phase 4 tracked-source mode normalization and service-identity readability checks. No migration or main update.
5. Add root-owned service-readable callback/sync configuration beneath the already backed-up `/etc/optibrain/phase5` tree. Generate the private native token inside the root process; preserve existing channel/job configuration. Keep lead record writes in observe policy.
6. Start candidate API `1.10.0`, verify fresh watchdog/authenticated health/safe internal smoke. Create the native subscription through the same Desired State engine and require immediate noop verification.
7. Perform a real-ID, synthetic authenticated public notification/duplicate drill, require a completed lead review run, and separately mark this as synthetic evidence. Do not create a test Lead or invoke existing operational functions just to generate traffic.
8. Reverify live noops/health, create and restore a fresh postdeployment backup, repeat the actual restored-v2 drill, and verify encrypted off-host generation/source hash/download hash through the unchanged uploader.
9. Require protected files/source modes/zero failed units/main unchanged; publish and verify pinned pre/post recovery tags. Require a different authenticated native callback on the private new channel to complete the provider-origin gate. If none arrives during the bounded observation, preserve deployment and report that gate as blocked rather than invent delivery proof.

Private root evidence is written under `/var/lib/optibrain/phase5/<UTC>-<suffix>/`. `progress.json` and `result.json` record stage, actual source/service/database observations, backup/archive digests, restored-copy results, provider evidence, off-host generation and recovery identities. If a gate fails, the campaign preserves the observed v2 database/source/service state. It never invokes the inherited V1 rollback, blindly repeats a provider operation, restores an old DB over new events, or reverses CRM writes.

Recovery requires reviewing the fixed stage and observed state first. After a service stop/start failure, verify actual HEAD, schema, unresolved work and source modes; start only the proven source/configuration after correcting the diagnosed problem. Restore damaged state only from a separately checksum-verified backup into isolated staging first, with explicit operator authorization for production replacement. After an ambiguous subscription write, read the pinned channel and journal together; a matching readback is evidence for human reconciliation, not permission to issue another POST. Preserve the same channel/token/configuration and unresolved audit entry until reviewed. An expired channel requires a separately reviewed native renewal; delta reconciliation remains the fallback.

The unchanged off-host model deliberately keeps the age private key off this host. Downloaded ciphertext/hash verification is the deployment gate; this campaign does not claim an offline decrypt/restore ceremony with an unavailable external private key.

## Implementation commits

- Control plane and lead intake: `61b1eb33a94aa1d7eb401b7b0d15ace17ab86ba3`.
- Verified CRM desired state and evidence: `681cc00dcb22a3ccca08d66f2051cda847048efc`.
- Pinned deployment/recovery preparation: `c4dd0119707616e09cfdd4602be0cca7fdd92d93`.

The final documentation commit is included in the clean candidate SHA supplied to the root campaign. The campaign records that exact candidate and published production recovery identities.

## Completion status

Final candidate validation: 384 workflow API tests, 325 subtests, zero failures/errors/skips; six deployment-driver tests are included. Administrator security/recovery: 37 tests PASS. Backup/off-host Python regression: 11 tests PASS. Backup, uploader/unit, bucket-listing and R2-health shell regressions PASS. The unprivileged backup shell run intentionally does not claim its root ownership variant; production gates execute under the required identities.

Candidate validation results and exact safe evidence are in [validation](phase5/candidate-validation.json). Unprivileged isolated schema-v2 startup, process/worker restart, dedupe, backup/restore and ambiguity drills passed on a fixture copy. This is explicitly distinct from the root gate against an actual restored production archive.

The existing limited helper reported health PASS and latest archive verification PASS. Its backup command stopped at conservative retained-generation headroom, and its latest restore command returned a fixed failure category. Neither is counted as a fresh pre/post Phase 5 backup/restore PASS. The prepared root campaign uses the unchanged normal backup policy and current checked-in restore verifier, and stops with evidence if those gates fail.

Production deployment, native subscription/callback, fresh actual-production backup/restore and matching encrypted off-host gates remain pending human root invocation. Final candidate commit, production/recovery tag SHA, archive digests and off-host generation are recorded by that pinned root campaign; they are not fabricated here. `OPTIBRAIN_PHASE5_COMPLETE: PASS` is forbidden until every applicable gate has actually passed.
