# Configuration and secret-reference inventory

AUTHORITATIVE CURRENT. The [machine register](optibrain-configuration-register.json) enumerates observed files, environment **key names only**, external bindings and recovery roles. No credential values belong in Git, reports, chat or command output. [Runtime](OPTIBRAIN_RUNTIME_CONTRACT.md) and [state](OPTIBRAIN_STATE_CONTRACT.md) supply consumers and data ownership.

## Sources and authority

| Configuration source | Owner; secret status | Source of truth; deploy / restore / verify | Backup coverage |
|---|---|---|---|
| Repository `main`, reviewed exact release | Engineering/GitHub owner; nonsecret | Git source; PR + CI + root gate / clone or verified bundle / compare SHA and source pins | Git tag + source archive + complete-history bundle |
| `/etc/opticable-{workflow-api,password-pdf,omada-site}.env` | root; credentials and settings mixed | Root-reviewed current environment; systemd EnvironmentFile / protected backup or provider rotation / inspect key names, modes and private authenticated reads | Application backup; plaintext root-only, off-host encrypted |
| `/etc/optibrain/mutation-control.json` | root, service-readable; nonsecret safety | Universal transport kill; reviewed root policy / **fresh OFF policy**, not restored old grants / trusted owner/mode and live inspector | Application backup; rebuild overrides old authority |
| `/etc/optibrain/phase7-canary-registration.json` | root 0644; identities/source pins, no private keys | Exact-release owner-route registration; root release gate / clear execution pins then rebind exact source / hash all 38 sources + SHA | Application backup |
| `/etc/optibrain/phase8-test-lab-registry.json`, `phase9-protected-baseline.json`, `phase11-operations.json`, `protected-runtime-versions.json` | root, API group-readable; protected IDs/lineage | Ownership/identity/version evidence; reviewed root append/readback / backup with name-based ownership / registry hashes, exact provider GET comparison | Application backup; golden version summary recovered from its archived named artifact |
| `/etc/optibrain/phase5/{webhooks,delta-sync}.yaml`, `phase13-observe-workflows/` | root/API group; webhook secrets + nonsecret workflow controls | Current root observation controls; reviewed copies / backup / definition, native binding and saved cursor readback | Application backup |
| `/etc/optibrain/phase12-runner.env`, `phase9-form-enrichment.env`, `phase9-receipt-export.env` | root; last contains export key | Root runner/fallback/export controls; reviewed deployment / recover key, force auto/fallback OFF / live flags and ownership | Application backup |
| `/etc/optibrain/rebuild-safety.env` (replacement only) | root 0600; nonsecret | Recovery denial override installed last; bootstrap / regenerate / bootstrap VERIFY | Rebuild recipe; created on replacement |
| `/etc/systemd/system/*.service`, `*.timer`, drop-ins and `/dev/null` masks | root; nonsecret | Current definitions in `ops/phase15/systemd`; reviewed install + daemon-reload / bootstrap definitions with timers masked / systemd-analyze and status | Application backup + repository; enablement recreated explicitly |
| `/etc/caddy/Caddyfile`, active `conf.d/*.caddy` | root; nonsecret | Reviewed proxy containment in `ops/phase15/caddy`; syntax validate/reload / recipe + DNS/TLS reconstruction / Caddy validate and denied-route checks | App backup; `.caddy.pre-*` is inert archive, not imported |
| `/var/lib/caddy`, `/etc/{ufw,netplan,ssh}`, sudoers, hostname/fstab | root/Caddy; TLS and SSH private keys included | Host infrastructure, not application authority; secure new-host policy / infrastructure supplement only after review / listeners, firewall, TLS/SSH checks | Encrypted infrastructure supplement; app archive also contains SSH configuration |
| `/usr/local/{sbin,lib}/optibrain*`, installed deploy gate and runbook/helper digests | root; nonsecret reviewed code/trust | Pinned repository sources; manual reviewed install / bootstrap current sources / SHA256 comparisons | Source + app backup + infrastructure supplement |
| `/var/lib/opticable-api-platform/shared/zoho-oauth.json`, API OAuth cache; Omada sessions | API/Omada user; secret | Credential-bound token/session state; approved OAuth owner flow / protected copy or reconnect / permissions + minimal read, never print | App backup; browser cache expendable and omitted in clean rebuild |
| `/var/lib/opticable-workflow-api/output/automation/*.db`, root `/var/lib/optibrain` | API/root; protected operational evidence | State contract; canonical writers / online DB snapshots + root evidence / DB integrity, hashes, claims | App backup; `/run` samples are rebuilt, not durable authority |
| `/etc/optibrain/{backup.conf,phase2a.conf,age-recipient,r2-uploader.env}` | root; last is AWS INI credentials, recipient public | Fixed backup bucket/recipient/credentials; root install / backup + owner/cloudflare recovery / local hash and independent R2 downloaded-byte hash | App backup; offline AGE identity **excluded** |
| Root release/retention/recovery policies, `/var/lib/optibrain/releases`, `phase2a/state.json` | root; nonsecret references | Root-reviewed receipts/holds; deployment/upload / backup / exact source/archive/ciphertext hashes | App backup; action/effect/hold evidence never age-pruned |
| Cloudflare zone DNS/TLS/Access, Worker settings/secret bindings/KV/queues/Workflow and R2 locks | Cloudflare account owner; mixed | Provider control plane; explicit administration / retained provider inventory + owner secret reentry / read-only provider inventory and auth tests | Nonsecret inventory in recovery evidence; Worker secret values/KV require owner/provider recovery, not export from metadata |
| GitHub `.github/workflows` and repo/organization secrets/settings | GitHub owner; mixed | Repository workflow code + provider settings; PR/CI or explicit admin / Git bundle + owner secret reentry / exact-head jobs and disabled schedule readback | Source/bundle + secret references; GitHub secret values are not downloadable backups |
| Zoho CRM schemas/native watch/Forms integrations/OAuth scopes | Zoho owner/admin; mixed | Provider state; explicit admin / documented reconnect and owner native Forms disablement / GET metadata/readback; native Forms browser-only confirmation | Nonsecret observations backed; provider itself owns business records |
| OVH account/VPS/snapshot/DNS role | OVH owner/admin; credential references below | Provider infrastructure; GET-only inspection during Phase15 / new host + owner access / exact VPS/service identity | Confirmed snapshot + metadata; account credentials/ownership remain owner dependency |

The legacy `optibrain-admin sync-master-runbook` and `optibrain-admin-update` publishers are **DEFERRED — NON-CRITICAL**. They require historical private staging and `/etc/optibrain`0700, incompatible with the current root-owned0755 directory needed for service-readable controls. Do not change that directory to make them run. Current publishing is reviewed Git + the canonical root release gate; health, scheduler, capacity, local backup/verify and restore-drill admin operations remain supported. The unused publishers are not bootstrap/recovery dependencies.

## Exact precedence

Code defaults < process environment. For systemd: unit and lexically ordered drop-ins compose the definition; **EnvironmentFile values override Environment=**, later EnvironmentFiles override earlier ones, empty assignments reset lists. API root observation drop-in selects `/etc/optibrain/phase13-observe-workflows`; it is not the editable repository workflow directory. Recovery `99-rebuild-safety.conf` appends `/etc/optibrain/rebuild-safety.env` as the final EnvironmentFile to all app/observer/runner units. CLI bind arguments override the configured host/port, so canonical units explicitly bind loopback.

Root safety gates are conjunctive: an env true, workflow enabled or approval cannot override a missing/corrupt/OFF mutation policy, protected ownership, exact-release registration, immutable envelope or off-host claim. Real canary must always be false in the accepted root policy. Books non-GET denial is independent. Application env may name the shared core OAuth path; PDF points to the same shared file; the connector’s KV token domain is separate. Caddy file is current authority; Caddy API changes are overwritten by reload and are not the configuration procedure. Snapshot/backup copies never override current credential rotations, provider truth or newer effect claims.

## Secret references and rotation

Every observed credential key and remote secret binding is individually listed in the machine register with purpose/provider, storage, consumer, rotation/recovery rule and backup inclusion. Credential families:

| Purpose/provider | Reference; consumer | Rotation and recovery requirement |
|---|---|---|
| Core/PDF/Omada service authentication | service env API key/webhook token keys; core/edge/GitHub consumers | Owner-approved generated replacement, synchronize callers, prove old key denied; protected env backup recovers values |
| Zoho core OAuth | workflow env client secret + shared `zoho-oauth.json`; API/PDF | Owner Zoho admin OAuth consent/scopes; preserve token binding/checkpoints, verify GET-only, never revive retired writers |
| Connector OAuth/export | Cloudflare `opticable-ai-connector` secrets and OAUTH KV; collector export env key/private PEM | Owner Cloudflare/Zoho admin, separate OAuth domain; reenter unavailable secrets through provider UI; bundle/source are in golden root artifacts |
| Cloudflare API/R2 | workflow env CF token/account; AWS INI `r2-uploader.env`; root uploader/queue sampler | Owner scoped token rotation; verify GET/R2 readback before replacing; keep create-only recovery and claim locks |
| GitHub App/deploy SSH | workflow App IDs + `/etc/optibrain/github-app.pem`; root deploy private key; GitHub secret refs | GitHub owner app key/deploy key/known-host update; reviewed root files and restricted command; never broaden root automation |
| OVH direct | `OVH_APPLICATION_KEY/SECRET/CONSUMER_KEY`, `OVH_ENDPOINT` in workflow env | OVH owner machine credential/consumer rotation; core GET-only; recovery env backup or owner reissue |
| OVH gateway | same key **names** as secret bindings in connector, nonsecret `OVH_ENDPOINT`; gateway | Separate provider authority, owner Cloudflare + OVH access; reconnect GET first; credential metadata gives broad capability, not automatic mutation permission |
| Optional Google/Windsor/Apollo/OpenAI/Anthropic/Omada credentials | workflow env, provider token files, Omada state | Deferred if absent/outage; recover/rotate through account owner only when explicitly needed; never log values or use a paid action as a health probe |
| AGE recovery | `/etc/optibrain/age-recipient` public; private identity offline owner | Never rotate/regenerate merely to test. Owner verifies/decrypts locally; private identity is excluded from every VPS backup/source/log |

Environment values can include unused historical credentials; presence does not authorize use. Backup archives include credential-bearing files under root-only storage and off-host encryption; secret metadata reports only names/types/paths. Cloudflare/GitHub secret **values** are not included in provider-setting inventories. Human custody remains required for total account loss.

## Owner-held dependencies

| Dependency | Why/how often; instructions | Never share |
|---|---|---|
| Offline AGE identity and trusted decryption device | Required for encrypted off-host recovery; incident/drill only; recovery guide | Private identity, passphrase or unencrypted credential archive in chat/VPS |
| OVH owner/admin login + MFA + billing control | Fresh-host acquisition, snapshot/host/billing incident; recovery guide and OVH Manager | Login/MFA recovery codes/API secrets |
| Cloudflare ownership + MFA | DNS/TLS/Access, R2 or Worker secret loss/cutover; recovery/config guides | Account tokens or global key |
| GitHub ownership + MFA/App control | Repo/private access, app/deploy secret rotation; deployment guide | Private SSH/App keys or recovery codes |
| Zoho owner/admin + MFA/browser UI | OAuth reconnect and native Forms settings; recovery guide | Session cookies, client secret, refresh token, MFA codes |
| Domain registration ownership | Domain renewal/registrar DNS ownership incident; owner’s registrar/billing records | Registrar credentials/MFA; registrar identity was not independently inventoried here (documented P2 dependency) |

No human-only step is needed for routine read-only local health. Account creation/billing, MFA, native Forms controls and AGE decryption cannot be safely inferred or automated from a backup. Registrar outage does not block app reconstruction when existing Cloudflare DNS ownership remains available.

## OVH access contract

Canada endpoint `ovh-ca`; production `vps-214ba8cd.vps.ovh.ca`; service `41299869`; region `os-bhs6`; product VPS-2 2027. Access is **BOTH** direct VPS and `connect.opticable.ca` gateway. Direct key references live only in the root env; gateway authority lives in Cloudflare connector secret bindings. Preflight independently verified both; Phase15 only uses GET inventory. Core source rejects non-GET before HTTP. Gateway provider mutations require explicit human confirmation/reason/audit; snapshot restore/reboot/reinstall/delete/network/account operations require an exact human incident authorization, never workflow/health authority.

On a replacement host restore/reissue direct credentials securely, verify `--ovh` GET identity, retain the gateway’s external bindings/KV or have its owner restore them, and verify the existing endpoint. VPS reconstruction does not require mutating OVH through the app. The confirmed VM snapshot is recovery insurance, not bootstrap input.

## Individually scoped internal authority

Root `/etc/optibrain/mutation-control.json` schema2 may authorize exact new-record internal families while legacy env flags and real canary stay false. `/var/lib/optibrain/lifecycle/activation.json` binds cutoff, approved sources, family, scopes and Phase16 checkpoint; `/etc/optibrain/lifecycle-runtime.json` binds immutable exact-SHA source and interpreter. Root `authorizations/` binds each effect to independent source evidence, eligibility, scope, payload hash, policy hash and five-minute expiry. No env variable or DB row can enable this. Kill policy overrides everything; restore defaults are schema1 all OFF, all application timers masked. Root release deployment requires lifecycle scopes closed. New runner reuses existing core OAuth, private export and root R2 references; adds no credential. Zoho’s three legacy notification/function workflows are disabled, definitions preserved; current root runner independently reads their disabled state before effects. English Forms notification delivery is unproven and its intake scope excluded.

## Separate customer-send authority

`/etc/optibrain/customer-communication-control.json` is independent of internal mutation policy. Four exact Mail scopes require root source pins, the passed Phase18 checkpoint, native eligibility and one off-host claim. `customer-communications-runtime.json` pins the immutable release and every Python source. The installed `customer_runner.py --stop` closes all automatic external sends without affecting internal intake. Root evidence/suppression lives in `/var/lib/optibrain/customer-communications`; dated `/run/optibrain-readiness/customer-communications.json` is display only. No new secret or listener. Replacement bootstrap/restore forces customer flags OFF and masks its service/timer; backup authority never re-enables them. Details: [communication contract](OPTIBRAIN_CUSTOMER_COMMUNICATION_CONTRACT.md).

Read-only lifecycle observation adds root cache `business-observation.json`, optional owner-reviewed `recurring-links.json`, and derived readiness `recurring.json`/`marketing.json`; see [state](OPTIBRAIN_STATE_CONTRACT.md). No new credential/secret/feature flag or provider write authorization. Windsor Ads/GA4 account discovery is diagnostic; destination IDs and advertising consent remain unverified, so upload is OFF.

Owner Business Overview adds minimized root:opticable-workflow-api0640 `/run/optibrain-readiness/business.json`, regenerated by the existing internal observer; no secret or provider-write scope. The configuration register specifies ownership, restore and verification.
