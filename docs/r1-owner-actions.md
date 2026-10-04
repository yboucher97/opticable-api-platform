# Remediation 1 — current provider actions

The owner selected GA4 property **530093120**, stream **14233342137**, measurement ID **G-ZEQXVSZWRL**. Both sites use this one property. Property530619880 remains historical; do not delete or dual-tag it.

## Google Tag Manager — no blocking action

Both saved Google OAuth and the owner browser account see no accounts for GTM-NTSPMGJX. The bounded production fallback is one direct site-owned GA4 path. Existing GTM/Yellow Pages/Ads/Bing and first-party gateway are preserved. Do not add another GA4 tag to that container: any future consolidation must remove the direct path in the same reviewed release and prove one event. Container ownership recovery is optional and no longer blocks this remediation.

## One acquisition context field on each Forms form

Do this for **Formulairedemandedesoumission** (FR) and **RequestaQuote** (EN):

1. Zoho Forms → form builder → add a **Multi Line** field, label exactly **OptiBrain Acquisition Context**. Set the maximum accepted length to at least12000 characters if this setting exists; keep it optional.
2. Field Properties → Advanced → **Field Alias / Prefill alias**: `ob_attribution`. Configure the field as hidden from respondents using the form's field visibility setting; retain its submitted value. Do not mark it required.
3. Settings → Email & Notifications → notification recipient **soumissions@opticable.ca**; include this field in the notification's field table. Keep respondent auto-replies **OFF**. Retain the native subject (the controlled OPTIBRAIN TEST subject exception remains approved).
4. Integrations → Zoho CRM → keep the native writer **OFF**. Save/publish the existing form without changing other questions.
5. Engineering verifies the live field/alias with read-only browser inspection, then performs one uniquely identified controlled TEST entry per language and reconciles native authenticated mail → central immutable receipt → TEST-only lineage. Replays reconcile without resubmitting.

The website prefill value is a versioned JSON object carrying language and the existing consented First/Last/click/origin fields. No customer name/email/phone/message is added to this context. Notifications remain the authoritative delivery evidence. No campaign is reconstructed from browser memory when the provider omitted it. English real automation remains excluded until separately graduated under current safety rules.


## OWNER ACTION REQUIRED — supported Forms administration path

Provider: **Zoho Forms**. Operation: read existing form metadata and configure one hidden acquisition field/prefill alias/admin-notification inclusion. Current access: existing OptiBrain Zoho OAuth US client and direct adapter; one client, existing refresh token, no new credentials.

Current status: blocked dependent setup; existing French notification runtime continues. Exact failure: GET https://forms.zoho.com/api/v1/forms returned **HTTP404**, HTML **Sorry! Page not found**, without a structured OAuth error, with both authorization-scheme diagnostics. CRM GET /crm/v8/org and Mail GET /api/accounts returned200 in the same session. The saved grant already contains **ZohoForms.forms.READ**. Classification: **O UNKNOWN — supported administration endpoint not established**; available ZohoCRM MCP is CRM-only (**M execution-environment access gap**). No missing write scope or plan requirement has been proved.

Exact scope/config needed: **NOT YET ESTABLISHED**. Do not request guessed ZohoForms.forms.UPDATE/ALL, revoke the working grant, create another OAuth client or purchase a plan.

Steps:
1. Zoho Forms → Help/Support, using the existing account that owns Formulairedemandedesoumission and RequestaQuote. Ask for the supported public OAuth endpoint/specification for listing existing Forms fields, adding a hidden Multi Line field, changing its prefill alias and including it in admin email notifications. Supply the404 endpoint and the existing read scope above. Ask for required region/base URL, exact scopes, account feature/plan and form-owner role. This support request is prepared for the owner; OptiBrain has not sent it.
2. If Zoho supplies a supported API, engineering will extend the existing adapter/grant only as documented, then verify the same metadata read and exact field readback. If Zoho confirms UI-only administration, the hidden-field steps above are one-time setup and may be performed by the owner or an authorized bounded browser task.
3. Only after saved settings are verified, perform one uniquely identified TEST_ONLY submission per language. Reconcile native authenticated Mail → immutable central receipt → attribution/CRM plan; replay without another submission. Keep native CRM writers/respondent auto-replies OFF and English real automation excluded.

Reauthorization required: **NO reauthorization currently justified**; if a documented additional scope is returned, reauthorization of the existing client will be required for that scope. Risk: no grant or business-state change now. Existing-system impact: none to CRM, Books, Mail, WorkDrive or proven automation. Mission can continue: **YES**, except native Forms configuration/parity proof. Recurring browser dependency: **NO**.

GTM access diagnosis: native accounts.list returns200 with zero accounts despite saved readonly/edit/publish scopes; classification **J role/admin restriction**, not A missing scope. GTM ownership repair is optional because the owner-approved single consented site-owned GA4 path is collecting. Future consolidation requires container access and removal of the direct path in one reviewed change; never add a duplicate GA4 tag.
