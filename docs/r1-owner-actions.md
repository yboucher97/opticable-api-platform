# Remediation 1 — current provider actions

The owner selected GA4 property **530093120**, stream **14233342137**, measurement ID **G-ZEQXVSZWRL**. Both sites use this one property. Property530619880 remains historical; do not delete or dual-tag it.

## Google Tag Manager — no blocking action

Both saved Google OAuth and the owner browser account see no accounts for GTM-NTSPMGJX. The bounded production fallback is one direct site-owned GA4 path. Existing GTM/Yellow Pages/Ads/Bing and first-party gateway are preserved. Do not add another GA4 tag to that container: any future consolidation must remove the direct path in the same reviewed release and prove one event. Container ownership recovery is optional and no longer blocks this remediation.

## One acquisition context field on each Forms form

Do this for **Formulairedemandedesoumission** (FR) and **RequestaQuote** (EN):

1. Zoho Forms → form builder → add a **Multi Line** field, label exactly **OptiBrain Acquisition Context**. Set the maximum accepted length to at least12000 characters if this setting exists; keep it optional.
2. Settings → Prefill → **Field Alias - Prefill URL** → Configure Now → select **OptiBrain Acquisition Context** → set alias `ob_attribution` → Save. Configure the field as hidden from respondents using the form's field visibility setting; retain its submitted value. Do not mark it required.
3. Settings → Email & Notifications → notification recipient **soumissions@opticable.ca**; include this field in the notification's field table. Keep respondent auto-replies **OFF**. Retain the native subject (the controlled OPTIBRAIN TEST subject exception remains approved).
4. Integrations → Zoho CRM → keep the native writer **OFF**. Save/publish the existing form without changing other questions.
5. Engineering verifies the live field/alias with read-only browser inspection, then performs one uniquely identified controlled TEST entry per language and reconciles native authenticated mail → central immutable receipt → TEST-only lineage. Replays reconcile without resubmitting.

The website prefill value is a versioned JSON object carrying language and the existing consented First/Last/click/origin fields. No customer name/email/phone/message is added to this context. Notifications remain the authoritative delivery evidence. No campaign is reconstructed from browser memory when the provider omitted it. English real automation remains excluded until separately graduated under current safety rules.


## Forms administration diagnosis — one-time UI configuration

Provider: **Zoho Forms**. Operation: read existing form metadata and configure one hidden acquisition field/prefill alias/admin-notification inclusion. Current access: existing OptiBrain Zoho OAuth US client and direct adapter; one client, existing refresh token, no new credentials.

Current status: blocked dependent setup; existing French notification runtime continues. Exact failure: GET https://forms.zoho.com/api/v1/forms returned **HTTP404**, HTML **Sorry! Page not found**, without a structured OAuth error, with both authorization-scheme diagnostics. CRM GET /crm/v8/org and Mail GET /api/accounts returned200 in the same session. The saved grant already contains **ZohoForms.forms.READ**. Initial classification was **O UNKNOWN**. The owner subsequently supplied current provider guidance that standalone Forms has no direct public API; a Zoho-authored G-Cloud14 service definition, page18, also states its REST API is not exposed to third parties. Current classification: **G PROVIDER-SIDE API LIMITATION** for these administration operations; available ZohoCRM MCP is CRM-only (**M execution-environment access gap**). No missing scope, expired grant, region error or license defect was proved.

Exact configuration needed: the one optional hidden Multi Line field, prefill alias and admin-notification inclusion above. **No additional OAuth scope is indicated for UI-only administration.** Do not request guessed ZohoForms.forms.UPDATE/ALL, revoke the working grant, create another client or purchase a plan.

Steps:
1. Use the existing owner session at https://forms.zoho.com/opticable/form/Formulairedemandedesoumission/builder (FR) and the RequestaQuote builder (EN). The legacy /zohoforms/form/allforms path showed a permission error; the opticable namespace was verified accessible. Apply only the hidden-field, alias and notification-inclusion steps above. This is one-time setup, not recurring browser execution.
2. Reopen saved settings and inspect the published field/alias. Preserve native CRM integration and respondent auto-replies OFF. Do not submit until recipient, hidden value and writer boundaries are verified.
3. Perform one uniquely identified TEST_ONLY submission per language. Reconcile native authenticated Mail → immutable central receipt → attribution/CRM plan; replay without another submission. English real automation remains excluded until separately graduated.

Reauthorization required: **NO** for this one-time UI setup. A future documented API scope would extend the existing client only when needed. Risk: bounded field/notification setup; no business-record, financial or grant change. Existing-system impact: none to CRM, Books, Mail, WorkDrive or proven automation. Mission can continue: **YES**, except native Forms configuration/parity proof. Recurring browser dependency: **NO**.

Final setup result (October4): the owner requested that the one-time browser task finish. It terminated with **Browser session closed unexpectedly**, no saved-change confirmation. Independent published-form GET-only inspection afterward found the context field/alias absent on both FR and EN; no submission was made. This is a browser-execution failure, not evidence of an OAuth-scope, license or account-access defect. The existing owner session had previously opened the correct `opticable` builder. Do not request another OAuth grant or repeat an unbounded browser run. The exact one-time manual setup above remains required; normal runtime remains authenticated Mail → central intake, with no recurring browser dependency.

GTM access diagnosis: native accounts.list returns200 with zero accounts despite saved readonly/edit/publish scopes; classification **J role/admin restriction**, not A missing scope. GTM ownership repair is optional because the owner-approved single consented site-owned GA4 path is collecting. Future consolidation requires container access and removal of the direct path in one reviewed change; never add a duplicate GA4 tag.

Official supported UI references: [Field alias configuration](https://help.zoho.com/portal/en/kb/forms/form-settings/prefill/articles/field-alias), [Form builder](https://help.zoho.com/portal/en/kb/forms/form-types/standard-forms/articles/understanding-your-form-builder), [Webhook configuration](https://help.zoho.com/portal/en/kb/forms/integrations/webhooks/articles/webhook-configuration). These document UI setup and runtime outbound delivery; they support the one-time setup and API/webhook runtime distinction. [Zoho-authored service definition, page18](https://assets.applytosupply.digitalmarketplace.service.gov.uk/g-cloud-14/documents/721684/829976568833637-service-definition-document-2024-05-06-1119.pdf) explicitly describes the public REST limitation. The historical document date is retained; the owner supplied current guidance separately. Zoho Creator form APIs are a different product and must not be substituted for these standalone Forms.
