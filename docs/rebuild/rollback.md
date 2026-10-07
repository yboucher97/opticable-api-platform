# Rollback and old-VPS retention

RECOVERY — CURRENT SPECIALIZED GUIDE. Old host `148.113.249.7` remains the fallback. No automatic termination or deletion exists.

Before cutover, create the rollback manifest with old/new hosts, exact old/proposed DNS content/TTL/proxy state, Caddy/TLS/Access policies, final source SHA/recovery, writer-freeze evidence and verified private/public checks. Preserve the previous target generation and both machines' action journals.

If a cutover regresses, freeze both hosts first. A writers-OFF replacement can still receive new inbound events; switching back without reconciling these creates data loss. Preserve a new verified replacement recovery and reconcile post-cutover receipts/audits, provider truth and independent immutable R2 claims. Do not replace old databases with an older snapshot or resume a second scheduler.

Restore the exact old Cloudflare DNS/origin record, TTL and proxy state under the approved rollback action. Verify provider readback, independent public resolution/TLS, expected API SHA/version, Access denial and the owner's real dashboard login. Restore only separately authorized read observers after state reconciliation. A code rollback preserves journals and current credential rotations; normal code rollback uses a forward revert through the existing release gate.

Recommend 14 days of old-host retention, with a first review after seven days. Extend when backup/decryption/provider/public-route evidence is weak or when substantial post-cutover data needs reconciliation. Cost may justify a different owner-approved window. Retire only after repeated new-host backup readbacks, an actual rebuild drill, stable public/provider behavior and reconciled divergence. The toolchain never terminates the VPS, removes recovery evidence or expands retention policy silently.
