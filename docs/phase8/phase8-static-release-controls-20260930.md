# Phase 8 static release control implementation — 2026-09-30 UTC

Task `phase8-static-release-control-implementation`. New local branch:
`phase8/static-release-controls-20260930`, forked from production baseline
`d2ca75d588665112d1d62329abfda23dd92d533f`. The immutable candidate
branch remained at `dcdff624b8d04911dfb26d4af782c90527a5174f`.

The new data-only gate checker and offline tests are in `deploy/` and `tests/`.
The checker hard pins repository, branch, candidate, baseline, CI run
`36651969227`, and both successful jobs. It requires a distinct, maximum
two-hour root-private human authority; exact installed artifact digests;
fresh production and policy observations; and matching preserve-existing
backup, isolated restore, journal/dedupe, and downloaded off-host evidence.
Prepromotion also requires distinct candidate recovery and forward recovery.
There is no execute path. It returns `deployment_authorized=false` and
`provider_actions_authorized=false` even on a passing synthetic packet.

Offline focused tests: `python3 -m unittest discover -s tests -p
'test_phase8_static_release_gates.py' -v` passed 4 methods, including 13
failure cases for identity, time, CI, artifact, recovery and action-policy
gates. `python3 -m py_compile deploy/phase8-static-release-gates.py` and
`git diff --check` passed. A CLI call without administrator authority exited
1 with `result=BLOCKED`, with both action-authorized fields false.

Bounded read-only live readbacks on 2026-09-30 UTC:

| Source | Readback |
| --- | --- |
| `git ls-remote origin` | main `d2ca75d588665112d1d62329abfda23dd92d533f`; candidate branch `dcdff624b8d04911dfb26d4af782c90527a5174f` |
| GitHub Actions run API | `36651969227`, `Validate API Platform`, push, exact branch and candidate SHA, completed success |
| GitHub Actions jobs API | `control-plane-worker` and `workflow-api` each completed success |
| public `/v1/system/health` | `status=ok`, `version=1.11.0` |
| production checkout | HEAD `d2ca75d588665112d1d62329abfda23dd92d533f`; only untracked diagnostic script; its SHA-256 `7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000` |

The checker does not attest that a supplied packet came from those sources.
The current private active-release, effective policy, workflow/registration,
fresh backup, isolated restore and off-host gates were not readable here and
remain unverified. No Phase 8 root-private authority or installed campaign,
wrapper, or hook was created. A passing offline packet cannot authorize a
release. No main push, deployment, backup, provider write, or production
mutation occurred.
