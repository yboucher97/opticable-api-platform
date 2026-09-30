# Phase 8 static release controls

Branch `phase8/static-release-controls-20260930` is a separately reviewed control
proposal based on production baseline `d2ca75d588665112d1d62329abfda23dd92d533f`.
It does not change the immutable candidate
`dcdff624b8d04911dfb26d4af782c90527a5174f` or either Phase 6 program.

`phase8-static-release-gates.py` accepts a root-private Phase 8 authority and a
data-only observation packet. It fixes the repository, branch, candidate,
baseline, GitHub run and successful job identities. Its strict schemas reject
extra fields, stale authority or observations, changed reviewed artifact hashes,
wrong production identity, enabled external actions, and stale or mismatched
backup, isolated restore and downloaded off-host receipt evidence. A second
prepromotion packet requires the exact staged candidate, a distinct candidate
backup generation and a passing forward-recovery result.

The command has **no execution mode**. It makes no deployment, main push,
backup, provider, or service change and never imports candidate code. A PASS
only means the supplied packet is internally consistent. The packet is not
cryptographically attested or independently collected by this checker; a future
root campaign must re-read every live source and reconcile prior attempts before
any stage. The administrator must separately review and install the loader,
campaign, root deploy wrapper, and main push hook and then issue a fresh
root-private authority at `/etc/optibrain/phase8-release-authorization.json`.
The checker refuses missing installed artifacts or authority. No Phase 8
authority, campaign, wrapper, or hook was installed by this task. The existing
Phase 6 campaign and wrapper are incompatible and must not be used for Phase 8.

The current private active-release, effective policy, registration, workflow,
fresh backup, isolated restore, and off-host state remain unverified. These are
administrator read-only evidence gaps, not presumed approvals. Release and
provider actions stay disabled. A future campaign requires its own independent
code review and human authorization before a real deployment or main promotion.

The separate offline campaign and health-only verifier review is recorded in
`docs/phase8/phase8-guarded-campaign-offline-20260930.md`. Neither has an
installed live execution path.
