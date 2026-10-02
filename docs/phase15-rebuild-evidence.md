# Phase15 rebuild evidence

AUDIT EVIDENCE — actual clean reconstruction PASS, 2026-10-02. Current instructions are solely in [recovery](OPTIBRAIN_RECOVERY_GUIDE.md). Raw aggregate receipts are root-only `/var/lib/optibrain/phase15`; approved credential-bearing staging is never versioned.

## Actual environment and inputs

Fresh Ubuntu24.04 amd64 userland was installed by `debootstrap --variant=minbase --include=ca-certificates noble`, then fresh apt packages, Python3.12 environments, verified official Node22.23.3/npm and locked Omada dependencies/build. No old Python/Node installation, unit, service identity, existing `/opt`, browser cache or whole-VPS copy was used as a dependency. The disposable root was under a root0700 parent at `/var/tmp/optibrain-phase15-isolated/rootfs`, outside application backup state; its OS root was0755 for service traversal.

Inputs: reviewed repository source, current guides/unit/proxy recipes, and golden app archive generation `20261002T123816Z`, SHA256 `ff91b86f3a4f9491158c7e7bcd067ca9cb06bb29b6a424d22dc0c9d31c82d7ba`. The infrastructure tarball/VM snapshot and owner private AGE identity were **not** rebuild inputs. Complete-history bundle and independently verified encrypted golden recovery remain available; existing preflight/decryption evidence was accepted.

Final executable source: `d489eef4c53564b93db35e0aceb3747ca5e9204d`; later report/guide edits change no executable behavior. Source copied by independent `git clone --no-local`, never by copying a live worktree or installed dependencies. Production release identity is the exact CI-backed root release receipt defined by deployment, rather than a self-referential SHA in this report.

## Measured proof

| Check | Observed result |
|---|---|
| Bootstrap CHECK/PREPARE/VERIFY | PASS; all prerequisites present; four named identities; no unit started; safety/ownership/helpers/proxy checked |
| Golden restore | PASS; complete hash/member/file/metadata validation;717 selected files restored; all8 independent DB integrity checks `ok`; name-based ownership; old execution authorizations excluded |
| Final preparation + restore + source rebind (before allocated-journal-only fix) | **MEASURED25.995s**; restore component25.485s, package downloads/install excluded; final receipt `final-reconstruction-receipt.json` |
| Registration and default controls |38 source pins verified, business actions false, all execution pins null; root global/Test transport OFF, canary false; final recovery env disables internal observers/fallback/sends; five timers + TEST service + six retired units masked |
| Isolated API | PASS; version1.12.0; two actual HTTP boots, configured/missing key; **MEASURED6.569s**; authenticated local readiness/execution-health200, anonymous inspection401 or missing-key503, owner routes401, invalid key401, legacy writer403 |
| Operator rendering | Authoritative fake-provider regression exercises Today/system-health and owner-auth boundaries; no production JWT impersonation/provider reconnect |
| Supporting API boot | PDF health200/unauthenticated webhook401; Omada health200/retired route403; fresh Node build; **MEASURED5.937s** |
| Unit/proxy syntax |13 canonical application service/timer definitions pass systemd-analyze; recovery masks remain intact; Caddy validates with provider networking blocked; no timers enabled |
| Rebuilt-host backup round trip | PASS; generation `20261002T145459Z` validated774 files,960 metadata entries, all8 DBs, source extraction and3 critical configs; six retired + six recovery denial masks restored in disposable validation |
| Release regression |865 tests,760 subtests;0 failures/errors/skips/network attempts; **MEASURED39.137s**, fresh unprivileged engineering clone inside offline namespaces |
| Focused changed-area checks |22 tests/14 subtests;0 failures/errors/skips/network attempts; includes bounded logs, queue reads/freshness, unsafe bootstrap paths/ownership and real backup preservation |

Containment: separate mount/PID/network namespaces and private IPC/shared memory for full tests; only loopback, no default route/external interface. API process received only safe flags and an ephemeral local key, **no production provider credentials**. Its socket guard recorded0 external attempts; primary provider/OVH mutation attempts0. Supporting services received no provider credentials and rejected tested consequential requests before jobs. No production business action was executed.

## Dependencies/defects discovered and closed

1. Historical entry points/runbook host and safety grant could conflict with current state: one small current set, explicit precedence and historical banners/register.
2. Live unit/drop-in/proxy/helper definitions were not sufficient repository reconstruction inputs: current reviewed definitions and complete configuration/secret-reference inventory added.
3. Protected version comparison depended on a phase-named engineering workspace: canonical root baseline reference added; golden normalization documented/tested.
4. Official Node installed under `/usr/local`, unit used `/usr/bin/node`: fresh-target adapter added. Archived numeric ownership could expose root-helper parents: install `--no-same-owner`, root ownership check enforced.
5. Root clone failed backup Git ownership checks: documented engineering checkout ownership, immutable dependencies stay root-owned; actual backup rerun passed.
6. Admin executable modes/audit directory and trusted runbook digest mode were implicit: bootstrap installs exact modes/root0700 audit directory and verifies helper parents/config structure.
7. Fresh timer masks produced unrestorable absolute symlinks in new archives: backup1.0.4 encodes only known denial masks as metadata; strict validator preserves bounded masks and rejects unknown/traversal names; actual round trip passed.
8. Contained test fixtures needed normal `/proc`, private1777 `/dev/shm`, and a separate engineering checkout for historical production-path fixtures: repeatable namespace instructions added. Initial probe errors were corrected without weakening assertions.
9. API probe launcher needed `/usr/sbin/runuser`; missing configured auth correctly returns503, so the probe now recognizes denial instead of calling it open. Actual401/403/503 checks remain strict.
10. The constrained runbook publisher requires its exact original title and0440 trust digest; preserved the title/digest contract after rewriting content.
11. Two-timer admin scheduler command was mistaken for full coverage: exact five-timer command now appears in onboarding/operator/runbook.

Zero undocumented P0/P1 dependencies remain. Human-only AGE/MFA/provider ownership/native Forms settings and domain registration ownership are explicit. Registrar identity detail is a documented P2 external dependency; optional peripheral integrations remain DEFERRED — NON-CRITICAL.

## Scope and recovery limits

**PROVEN:** fresh Linux userland/packages/dependencies, source/config/users/permissions, eight-store restore, compiled Omada, source/unit/proxy reconstruction, safe contained API/support boot and rebuilt backup round trip without VM snapshot or old chats.

**DOCUMENTED, not failover-tested:** fresh OVH provisioning/kernel/systemd PID1 boot, production DNS/TLS/Access cutover, owner MFA and provider reconnect/reconciliation after an actual host loss. The drill shares the existing host kernel; it is not a new booted VM. Snapshot remains owner CONFIRMED and was not restored destructively.

RPO assumption: daily verified online backup plus normally30–45min upload delay; outages may extend it, choose the latest independently verified generation. Full OS-to-provider/traffic-ready RTO is **UNKNOWN**; measured components above exclude host acquisition, package download variability, owner decryption/MFA, provider outages and DNS/TLS. No guaranteed RTO or browser-only provider setting verification is claimed.
