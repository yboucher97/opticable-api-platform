# Preview integration security boundary

The control plane stops at local preparation and owner review. Tonight all new provider reads are fake; no provider credentials, network writer or webhook endpoint are added. The candidate G001/G002 completeness fixes and G003 timer-health fixes are inherited unchanged. G004 release/recovery metadata remains untouched.

| Input or effect | Boundary and proof |
| --- | --- |
| Proposal identity | Canonical ID/revision/hash and repository mapping checked against the existing immutable proposal journal |
| Branch | Traceable fixed optimization prefix; normalized ASCII slug; bounded length; rejects traversal, ref syntax, control characters and shell syntax |
| Worktree | Private configured root; deterministic repo/ID path; common Git identity, exact branch/base and private record; rejects symlinks/collisions/production paths; cap three |
| Source edits | Structured unique before/after replacements on bounded allowed files; workflows, dotfiles, deployment, credentials and dependencies excluded; dirty work preserved |
| Git process | Fixed list argv, shell=false, timeout/output limits, cleared credential environment, hooks/signing/fsmonitor/external filters disabled |
| Build/test process | Trusted pinned script catalog, bounded classes and timeout, preview environment, per-head logs; refuses dirty or changed scripts and source mutations |
| Provider state | Dated read accounting; auth/timeouts/partial/budget exhaustion distinct from verified-empty success |
| Hosted preview | Exact repo/proposal/revision/branch/base/head; explicit non-production project/environment; exact host allowlist; HTTPS and no redirects |
| HTTP validation | Expected content, noindex/canonical, CTA/Forms requirements and exact manifest; bounded GETs, no live form submits |
| Webhook | Raw-body HMAC verification, allowlisted repo/type, delivery ID, 64 KiB bound, durable unique replay protection, no executable payload text |
| Owner decision | Revision/head/build/test/preview evidence digest and expiry; immediate transaction checks revision/observation sequence; changed material evidence invalidates approval |
| Production | Interface contract only; no deployment implementation or new authority; APPROVED never implies DEPLOYED |

The local runner is a policy boundary, not a sandbox for malicious code. An operator must review the pinned script and its dependencies, ensure it cannot write providers or invoke production tooling, isolate credentials, bound disk use, and restrict its execution identity before hosted graduation. The catalog pins the top-level script; complete dependency/toolchain isolation and artifact digest attestation belong to controlled execution validation. Generated artifact logs remain outside worktree source. The allowed file policy is conservative and can be extended only through reviewed repository policy.

The configured clone/root/remote/production-path denylist and command catalog are trusted operator configuration, never webhook/proposal fields. A registered production checkout must be included in that denylist; worktree methods accept no arbitrary caller path. This mission's mutation tests create and dispose only temporary repositories and worktrees. Existing website evidence is read-only.

Approval and provider evidence are local journal observations protected by the existing service/owner boundary; accepting JSON is not cryptographic provider attestation. Live adapters must authenticate reads and collect manifests themselves. No transport capable of executing provider writes is shipped in this lane.

Focused tests include branch/path/command injection, wrong repository and proposal, cross-repo worktrees, dirty repos, collisions, malicious definitions, pinned-script drift, hook/filter execution, spoofed preview hosts, production redirects, wrong SHA/branch/environment, signature failures, replay, size bounds and unexpected provider responses. The full suite runs under the repository's network-blocking fake-provider validator.
