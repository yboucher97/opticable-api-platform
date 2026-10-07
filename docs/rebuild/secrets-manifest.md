# Secrets recovery manifest

SECURITY / CONTROL — PATH METADATA ONLY. Secret values printed: **0**. The selected recovery covers all 17 identified durable credential-bearing paths. The full individual environment key-name inventory and fingerprints are in [current-host-manifest.json](current-host-manifest.json). OAuth access caches are regenerable sensitive state; engineering/Codex credentials and SSH host identities are outside application recovery.

| Path | Owner:group | Mode | Recovery source | Consumer |
|---|---|---|---|---|
| `/etc/optibrain/cloudflare-test-token` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/optibrain/control-plane.key` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/optibrain/github-actions-deploy-ed25519` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/optibrain/github-app.pem` | root:opticable-workflow-api | 0640 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/optibrain/phase12-runner.env` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/optibrain/phase9-form-enrichment.env` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/optibrain/phase9-receipt-export-private.pem` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/optibrain/phase9-receipt-export.env` | root:opticable-workflow-api | 0640 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/optibrain/r2-uploader.env` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/optibrain/website-preview/cloudflare-builds-user.token` | root:opticable-workflow-api | 0640 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/optibrain/zoho-oauth-traverse-recovery.txt` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/opticable-omada-site.env` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/opticable-password-pdf.env` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/etc/opticable-workflow-api.env` | root:root | 0600 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/var/lib/opticable-api-platform/shared/zoho-oauth.json` | opticable-workflow-api:siteandpassword | 0640 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/var/lib/opticable-api-platform/shared/zoho-oauth.json.pre-full` | root:siteandpassword | 0640 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |
| `/var/lib/opticable-workflow-api/output/integrations/google-oauth.json` | opticable-workflow-api:opticable-workflow-api | 0640 | selected AGE-encrypted recovery | API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named |

Existing local recovery archives contain credential-bearing files under root-only 0700/0600 storage. They are not plaintext Git artifacts. Off-host recovery is AGE-encrypted to the existing public recipient; the private AGE identity remains owner-held. This mission does not create another secret bundle/platform, weaken permissions, copy the owner identity onto any VPS or reauthorize working providers. Hashes cover whole files and act as recovery fingerprints; no token/private key content appears in documentation.

On the trusted owner device, verify independently downloaded ciphertext/hash, decrypt with the existing offline AGE identity, and verify plaintext/hash. Transfer the verified archive/catalog through encrypted SSH into private replacement staging. Restore exact owner/group names and modes; never revert a newer credential rotation. OAuth checks now use temporary credential/cache copies. If refresh binding fails, report OWNER ACTION REQUIRED with error class/HTTP code, without logging provider bodies or silently starting a consent flow.

GitHub: preserve **OptiBrain Production**, App ID `5077440`, installation `164914980`, PEM `/etc/optibrain/github-app.pem`. Validation uses JWT metadata reads, an ephemeral in-memory installation auth exchange, and repository access read; no token is logged.

Cloudflare: account-owned application token is in the API env; user-owned Builds token is `/etc/optibrain/website-preview/cloudflare-builds-user.token`; root test token is separate. Verify account identity, Worker read scope and bound Builds triggers through GETs. R2 scoped upload credentials remain `/etc/optibrain/r2-uploader.env`; public AGE recipient `/etc/optibrain/age-recipient` is not a private key.

Zoho: API env contains core OAuth/client/provider bindings, and shared `/var/lib/opticable-api-platform/shared/zoho-oauth.json` retains the portable refresh credential. API/PDF share the named `siteandpassword` group. CRM, Books, Mail, Forms receipt export and WorkDrive identity/read tests reuse those credentials; connector OAuth/KV remains a separate Cloudflare-owned domain. Native Forms writer settings cannot be certified through the supported API and stay owner-disabled.

Google: existing OAuth binding supports GA4 `530093120` and GSC `sc-domain:opticable.ca`; Ads Basic access remains owner-deferred. Apollo probe is authenticated zero-credit `/auth/health`; no enrichment/outreach. Other optional provider/model keys are covered as named env-file fields, never exercised through paid/model-generation probes.

Owner MFA/account ownership is needed only when Cloudflare/GitHub/Zoho/OVH/domain/provider account access is lost or a host-bound credential fails portable validation. The normal recovery has three owner checkpoints: new VPS/access, offline decryption/private packet transfer, final traffic approval. No new provider authorization is presumed necessary.

## Regenerable system identities

These paths are metadata-only inventory, separate from the 17 canonical durable credential paths. Stock recovery does not capture Caddy TLS private state; origin TLS must be regenerated or supplied through an owner-authorized encrypted supplement before public cutover. A local Host override can verify an installed certificate; it cannot issue a certificate or satisfy ACME DNS validation. Stock Caddy here has no configured Cloudflare DNS-01 module/credential, so DNS-01 is a future reviewed option, not an existing automated capability. SSH host identities are freshly generated.

| Path | Owner/group | Mode | Consumer | Recovery |
|---|---|---|---|---|
| /var/lib/caddy/.local/share/caddy/acme/acme-staging-v02.api.letsencrypt.org-directory/users/default/default.key | caddy:caddy | 0600 | caddy.service | Existing Caddy TLS state is outside the current normal recovery bundle; regenerate or owner-authorize an encrypted TLS supplement before cutover |
| /var/lib/caddy/.local/share/caddy/acme/acme-v02.api.letsencrypt.org-directory/users/default/default.key | caddy:caddy | 0600 | caddy.service | Existing Caddy TLS state is outside the current normal recovery bundle; regenerate or owner-authorize an encrypted TLS supplement before cutover |
| /var/lib/caddy/.local/share/caddy/certificates/acme-v02.api.letsencrypt.org-directory/optibrain.opticable.ca/optibrain.opticable.ca.key | caddy:caddy | 0600 | caddy.service | Existing Caddy TLS state is outside the current normal recovery bundle; regenerate or owner-authorize an encrypted TLS supplement before cutover |
| /etc/ssh/ssh_host_ecdsa_key | root:root | 0600 | ssh.service | Regenerate new host identity; never blindly restore old host keys |
| /etc/ssh/ssh_host_ed25519_key | root:root | 0600 | ssh.service | Regenerate new host identity; never blindly restore old host keys |
| /etc/ssh/ssh_host_rsa_key | root:root | 0600 | ssh.service | Regenerate new host identity; never blindly restore old host keys |
