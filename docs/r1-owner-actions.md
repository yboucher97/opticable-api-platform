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
