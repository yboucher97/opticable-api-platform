# Phase 8 guarded campaign offline review

The local control branch is based on production baseline
`d2ca75d588665112d1d62329abfda23dd92d533f`. The integrated candidate
remains the separate immutable commit `dcdff624b8d04911dfb26d4af782c90527a5174f`.

Independent review found malformed `ci_jobs`, CI job names, and `stage` values
could raise Python `TypeError` instead of a named `GateError` in the pure static
validator. The static checker now rejects these values through its normal
fail-closed gates. The existing static packet still consists of self-reported
facts; its PASS cannot authorize a deployment or main push.

`ops/phase8/production_campaign.py` checks fresh prestage identity, baseline
recovery, and prepromotion identity in order. It requires a newer observation
at each checkpoint, an unchanged baseline backup generation, the exact
candidate and release ID, and the static gate's candidate backup, isolated
restore, off-host receipt, policy, CI, artifact, and production checks. It
stops before requesting the next observation on the first failure. The only
backend interface is `observe(stage)` and the CLI prints an offline plan.
There is no production collector, deployment callback, retry, or main push.

`deploy/phase8-production-root-command.py` contains an offline health-only
verifier for a future independently collected postpromotion observation. It
requires the exact successful campaign result, candidate identity at remote
main, remote branch, and production, the expected diagnostic file identity,
active service, versioned local and public health, and disabled external
actions. Its CLI prints an offline plan. It does not collect live facts or
modify the checkout, service, Git refs, provider state, or production files.
It is not installed as `/usr/local/sbin/opticable-api-deploy-root`.

The static authority also requires a separate main-push hook artifact. None
was installed or exercised here. Root-private authorization, administrator
settings, and fresh backup/restore/off-host facts remain unverified. Any
eventual release needs independent live collectors, installed and reviewed
artifact hashes, reconciliation of prior attempts, and human review of the
actual deployment and main promotion. This offline result is not release
authorization.

Offline verification: `python3 -m unittest discover -s tests -p 'test_phase8_*' -q`
passed 9 tests. `git diff --check` passed. Read-only local Git checks returned
production `d2ca75d588665112d1d62329abfda23dd92d533f` and integrated
candidate `dcdff624b8d04911dfb26d4af782c90527a5174f`. No provider action
or production mutation was run.
