# Recovery authority contract

AUTHORITATIVE CURRENT — Foundation completion, API 1.21.0. Capability never grants authorization. Fresh disaster recovery differs from an ordinary reviewed exact-SHA deployment.

| Authority/evidence | Fresh recovery behavior | Ordinary release behavior |
|---|---|---|
| Conversion destinations and native validation evidence | PRESERVE known IDs, metadata, value/currency policies, validation receipts | PRESERVE |
| Conversion execution | RESET TO OFF; clear global enable, per-family local enable, allowed event keys, release/source pins and execution window; REQUIRE OWNER RECONFIRMATION | Preserve OFF; no upload activation |
| Customer communication | RESET TO OFF; fresh root control, masked service/timer; REQUIRE OWNER RECONFIRMATION | Preserve the existing 4 scopes, original activation/expiry, claims and holds after closed-writer deploy and reviewed dry run |
| Internal real lifecycle | RESET TO OFF; empty real scopes, masked service/timer; REQUIRE OWNER RECONFIRMATION | Preserve existing 12 scopes and original source cutoffs/expiry/claims after reviewed release |
| TEST canaries / Phase7 approval / Phase9 enrichment / Phase12 writes | RESET TO OFF; approval IDs cleared and safety environment applied | Existing unarmed families remain OFF |
| Immutable effects, pending/uncertain claims, source receipts, R2 claims, suppression | PRESERVE; reconcile before any renewed authority, never replay uncertain effects | PRESERVE |
| Expiry | EXPIRE NATURALLY; never extend from restore/deploy time | EXPIRE NATURALLY |
| Persistent development worker | RESET TO OFF, six retired units masked; no authorization marker | OFF |

`ops/phase15/recovery_authority.py` implements deterministic conversion reset without provider calls. Bootstrap creates disabled conversion control; restore excludes raw archived conversion control and separately restores its configuration through that reset. Verification rejects enabled global/family/event authority or untrusted control files. Invalid archived configuration fails closed. Archive restore drills exercise the same reviewed helper, retain destinations, and report explicit authorization OFF. Installed helper is root-owned and ships alongside the drill.

Restored destination readiness does not bypass current provider verification, release binding, source proof, valid user-data consent, genuine event, expiry, TEST denial or off-host effect claim. A restored grant is not sufficient: owner reconfirmation creates a new reviewed root authorization after independent reconciliation. No upload occurs during recovery or its tests.

Root readiness reports capability, authorization, operation state and expiry separately. Seven timers are expected when both scoped policies are authorized, five when they are deliberately disabled. EXPIRED and BLOCKED do not appear ACTIVE. Retained review items with no explicit classification are UNKNOWN, and exact reconciled read failures are RESOLVED READ-ONLY; age alone never marks an issue resolved or accepted.

Changing-release guard still requires all scoped writers closed. `opticable-api-deploy-root --verify-current <exact-current-SHA>` is an explicit local read-only integrity/version check, with no fetch, restart, policy write or authority grant; it refuses another SHA. The normal changing-release path and automatic job guard remain unchanged.

Post-restore steps: run bootstrap VERIFY; inspect conversion authority OFF and retained destinations; confirm all recovery timers masked and private credentials trusted; reconcile native/off-host effects; verify exact source/SQLite/protected baseline; obtain separate owner authorization before enabling scoped actions. Never request or expose the owner private AGE key. [Recovery guide](OPTIBRAIN_RECOVERY_GUIDE.md) remains the operational runbook.
