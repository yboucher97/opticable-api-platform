# Manual actions required from owner

**Current status: both actions CLOSED — PASS.** [Final closure](phase13-final-closure.md) records the exact forms, all three non-secret recovery hashes, AGE exit0/archive-list exit0, independent manifest/off-host consistency and evidence limits. Owner key remains offline. The steps below are retained recovery/administration procedures; they are not new pending requests. No real canary or Phase14 is authorized by completing them.


No credentials should be sent in chat, Git, email, documentation or evidence. These actions close external proof gaps; they do not authorize a real canary. All OptiBrain provider writers remain OFF. Phase 14 has not begun.

## MANUAL-01 — contain native Zoho Forms → CRM

**Status: CLOSED — PASS. Historical severity P0; final authoritative owner-admin evidence satisfies this gate.**

**System:** native Zoho Forms / Opticable CRM. Codex has valid CRM read access and technical API administration, but no supported authenticated API with available scopes can deactivate the native per-form CRM integrations. This is separate from the connector and core transport; disabling those cannot control a native Forms write.

**Exact steps:**

1. Sign in to [Zoho Forms](https://forms.zoho.com/) with the Opticable owner/admin account.
2. In All Forms, locate the French contact form by its **Share → Public Link** suffix `i6pIlfoGOFER0OCZ4oUH_KMxVWRZKC9Of8vbyNAjR0g`. Locate the English form with suffix `5kpuPyq6HG3cmmNAHG_2cFprnp16uoMzojC7Fxq42xo`. Use these public identifiers rather than guessing a displayed form name.
3. Open each form's **Integrations → Zoho CRM** configuration. Preserve the existing configuration as an owner-private note; deactivate/remove the CRM integration using that integration's removal control. The required end state is **no enabled add-record, update-response or upsert push to CRM** for either form. Keep the forms and their submissions.
4. If the organization uses unified Zoho One integration management, also open [Zoho One](https://one.zoho.com/), top-right **Admin Panel → App Management → Integrations → Integrations tab → CRM → Active → Forms (⋮) → Deactivate**, then confirm **Deactivate**. In Unified UI use **Directory → Integrations → Integrations tab → CRM → Forms → Deactivate**. Zoho documents this supported deactivation in its [admin guide](https://help.zoho.com/portal/en/kb/one/admin-guide/integrations/zoho-crm/articles/integrate-zoho-crm-with-zoho-forms).
5. Reopen both forms' CRM integration pages and confirm the end state in step 3. Return only the two form IDs, disabled/not-configured status, owner confirmation and timestamp. A future manual validation may use an existing registered TEST_ONLY identity; do not submit a real customer's identity to test this.

**Required configuration:** native Forms CRM mutation OFF for both exact form IDs. **What NOT to change:** no historical CRM record edits/deletions/merges; no form/submission deletion; no CRM OAuth token revocation; do not enable the fallback enrichment. Turning off CRM's **Pre-population of Data** toggle alone does not prove push containment.

**Expected result / verification:** both forms show no active CRM add/update/upsert integration. OptiBrain API and connector continue healthy, and receipt collection can remain read-only. The owner UI status is the indispensable check; a core API curl cannot prove this external integration is disabled.

**Already completed:** connector transport blocked, core universal gate installed, form enrichment OFF, protected baseline verified, public OptiBrain legacy executors retired. **After this action:** independently confirm provider configuration, then update P0 closure; do not enable real automation.

## MANUAL-02 — prove the actual offline AGE recovery identity

**Status: CLOSED — PASS. Historical severity P0; exact existing owner-key proof and independent manifest/hash consistency satisfy this gate.**

**System:** encrypted R2 recovery backups. The legitimate owner identity is intentionally offline and unavailable to this VPS. Codex proved current ciphertext download/hash, eight DB restores, configuration/masks, fresh dependencies and restored application boot; a temporary-key encrypted R2 roundtrip passed separately. That does not prove your real private identity can decrypt the configured recipient.

**Exact steps on a trusted owner computer:**

1. Open [the R2 recovery bucket](https://dash.cloudflare.com/81d07d311d1b51e5e04b451d1f254850/r2/default/buckets/optibrain-recovery-prod). Download `backups/2026/10/01/20261001T202728Z.tar.gz.age` into a private recovery directory. This exact deployed safety-release generation is immutable evidence; later generations do not invalidate the drill.
2. Install/use AGE on that computer. Place your **existing offline OptiBrain identity** at `./optibrain-recovery-identity.txt` in the private directory. Do not generate a replacement identity for this test.
3. Set file/directory permissions and verify the public recipient fingerprint:

```bash
chmod 700 .
chmod 600 optibrain-recovery-identity.txt
age-keygen -y optibrain-recovery-identity.txt | tr -d '\n' | sha256sum
sha256sum 20261001T202728Z.tar.gz.age
```

Expected recipient SHA-256: `d3593cf7f443701fe9d863b6fa2b7ba7ff17ed216f6a6f463e1333589cd8a96f`.
Expected ciphertext SHA-256: `801cf07d3b16930e676d39c8640defb856a25bd03debeb881afa2719baa5148f`.
On macOS use `shasum -a 256` in place of `sha256sum`.

4. Decrypt locally and verify plaintext:

```bash
age --decrypt --identity optibrain-recovery-identity.txt \
  --output optibrain-backup-20261001T202728Z.tar.gz \
  20261001T202728Z.tar.gz.age
chmod 600 optibrain-backup-20261001T202728Z.tar.gz
sha256sum optibrain-backup-20261001T202728Z.tar.gz
tar -tzf optibrain-backup-20261001T202728Z.tar.gz > archive-members.txt
```

Expected plaintext SHA-256: `9b37c94a4cb5be5f2bac6907bfcf17754e6fda10f5a464b1360f6b72c7a4be84`.

5. Return only generation ID, the three matching fingerprints/hashes, successful AGE exit status and successful archive-list check. Keep the key, decrypted backup and member list private: the backup contains production credentials and business data.

**What NOT to change:** do not rotate the primary recipient, upload the private identity to the server/chat, overwrite production, re-enable timers/writers, or restore revoked old credentials. **Expected result:** all three exact hashes match and decryption/archive opening succeed.

**Already completed:** downloaded-hash-verified current off-host backup, safe isolated DB/config/source/mask restore and unprivileged application boot with fresh dependencies and no provider network. **After this action:** record non-secret proof that the owner recipient works. Fresh OS installation, DNS/TLS cutover and real provider reconnect remain tabletop/runbook scope; no guaranteed RTO is claimed.

## Future gate — actual human approval before any R3

**Classification: DOES NOT BLOCK current P0 containment because every production R3 writer is forbidden.** Genuine Cloudflare Access login/interactive approval remains required before a future R3 executor is implemented or authorized. No owner action on that future gate is requested in this mission. Issued fixture/local approvals are not evidence of authenticated human authorization and cannot enable Mail sends.
