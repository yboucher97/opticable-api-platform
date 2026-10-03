# Live measurement contract

AUTHORITATIVE CURRENT. Complements the [attribution contract](OPTIBRAIN_MARKETING_ATTRIBUTION_CONTRACT.md); [business intelligence](OPTIBRAIN_BUSINESS_INTELLIGENCE_CONTRACT.md) defines owner metrics. Provider facts are observations, never authority to repair CRM or upload conversions.

## Truth and lineage

PROVEN is a directly observed native field/count. DERIVED DETERMINISTICALLY is a reproducible join/calculation over exact provider IDs. PARTIAL identifies incomplete relations or populations. UNKNOWN means missing/conflicting evidence. UNKNOWN never becomes DIRECT. First acquisition and latest meaningful touch remain separate; source **and medium** distinguish paid and organic Google traffic. No name/date/amount matching establishes lineage.

Books Customer `zcrm_account_id` → CRM Account; CRM Finance `Estimate_ID`/`Invoice_ID` → Books object; native `Potential_Name`/`zcrm_potential_id` → Deal. Exact Invoice `estimate_id` may supply a Deal only after independent customer/parent validation. Deal → native Site/Services must agree with Account. Conflicts are quarantined, never silently reassigned. Recurring profile → generated Invoice is native evidence; Service/Site acquisition requires the separate recurring contract. Monthly billing never creates new Leads/conversions.

Read-only audit on October3:13 real Leads,45 Contacts,41 Accounts,1 Deal,12 Sites,12 Services;87 Books Estimates,120 Invoices (107 non-draft/non-void),23 recurring profiles (19 active). All financial customer/Account joins are deterministic; one Estimate has a native Deal. No real acquisition source is recorded. All23 profile→Service relations remain UNLINKED. Protected Account references remain READ ONLY. Historical billing classification is per relationship: Account-linked does not imply Deal/Site/campaign-linked. Six independent financial detail reads agreed with the existing snapshot. Private proof includes exact IDs/joins; versioned checkpoints contain only aggregates.

## Actual production observations

Owner Cloud API/scopes, browser consent and Explorer approval are complete. Independent refresh and native read receipts on October3 prove both GA4 properties/streams, key events, Ads linkage and Google Ads680-849-1878 (CAD, America/Toronto). GA4 property 530093120 / stream14233342137 / G-ZEQXVSZWRL has generate_lead, a legacy thank-you-page event and a native Ads link; its currency is USD. Property 530619880 / stream14281746924 / G-GYLGWDS464 is CAD with qualify_lead/close_convert_lead key events and no native Ads link. Both enable enhanced form interactions and email redaction. These metadata facts do not prove one successful business inquiry or duplicate-free reporting.

Publicly fetched GTM-NTSPMGJX published resource version4 contains Ads/Bing/legacy tags and no GA4 tag. Current OAuth user sees no GTM accounts. Prior Windsor actual event reception remains evidence of past reception, not current tag configuration. AI build measurement ID is empty. GA4 stays PARTIAL; domain/consent/internal-filter settings require the [single noncritical owner action batch](phase25-owner-actions.md). Filter API404 is not evidence that no filters exist. No tracking, bidding goal, budget or campaign was changed. Yellow Pages/legacy assets remain preserved; do not remove the published container to simplify analytics.

Native Ads confirms three enabled secondary UPLOAD_CLICKS actions with 90-day click windows and no custom conversion goals. Existing customer-data terms/enhanced-conversion setting are enabled; they do **not** establish an individual customer's advertising consent. Existing primary FR quote Merci7567646545 is unchanged. Qualified/accepted actions count MANY_PER_CLICK; paid-value action counts ONE_PER_CLICK. Our immutable business identity limits each outcome to one export independently of provider counting. No GA4 import or primary goal is substituted for these destinations.

French Forms native notification proof is reused. English delivery and complete campaign aliases remain PARTIAL; English is excluded from real intake. Current main/AI assets match previously validated capture/first/last/click/consent hashes. Native Forms→CRM writer remains OFF. Unknown historical source stays UNATTRIBUTED; optional Meta/LinkedIn expansion is deferred.

## Offline export: READY, uploads OFF

| Family | Native destination | Meaning |
|---|---|---|
| qualified_lead |7795448568| Human qualification; **zero CAD monetary value**, explicitly overrides provider's CAD1 default |
| estimate_accepted |7795962128| Native accepted Estimate gross in its currency; not paid revenue |
| invoice_paid |7796070369| Fully paid, non-recurring, unadjusted Invoice gross; **not period cash receipts** |

Native Data Manager validation-only returned HTTP200 without warnings for all three destinations, with zero executed events. [validate_destinations.py](../ops/phase24_25/validate_destinations.py) uses synthetic identifiers only with hardcoded validateOnly=true and has no live option. This is provider schema/access proof, not real Ads attribution or a genuine conversion. The genuine exporter rejects TEST data and synthetic IDs. No genuine eligible event has occurred; no event or consent was fabricated.

[conversion_runner.py](../ops/phase24_25/conversion_runner.py) supports CHECK, validation-only, one live send, diagnostics and STOP. Root `/etc/optibrain/conversion-export-control.json` controls only export, with separate destinations/family enables and one exact allowed event key. Production upload stays OFF until an independently reconciled natural outcome is registered and that one family/event is armed. No automatic export timer or service is enabled. First verification is one event, immediate provider diagnostics, then deliberate bounded continuation; an uncertain effect holds the family and never retries the POST.

Root event/source receipts under `/var/lib/optibrain/conversion-export` must prove genuine independently captured click, explicit advertising user-data consent, outcome time, native Finance relationship, new owned record and TEST/protected exclusion. Contact/analytics consent is insufficient. Exact deployed source/destination pins, freshness, provider validation and independent enable are mandatory. No outcome time is fabricated from Created/Modified time. Only gclid exports have native schema validation; BRAID/enhanced-PII paths remain unarmed pending their separate prerequisites/proof. Capture still preserves supplied gclid/gbraid/wbraid.

R2 `conversion-effects/v1/` create-only claims survive restore/deployment. Identity binds provider, kind, native record ID and version; time/value/destination changes never create a new acquisition identity. ACKNOWLEDGED is not processing success/Ads attribution. Diagnostics require matching destination and one successful event, no warnings/errors. Unknown response/claim → HOLD, not another POST. No annual/monthly recurring acquisition upload, historical upload or automatic adjustment exists. A destination forcing its default value is denied. Margin remains disabled without deterministic costs.

Stop only exports: `sudo /opt/opticable-api-platform/apps/workflow-api/.venv/bin/python /opt/opticable-api-platform/ops/phase24_25/conversion_runner.py --stop`. This never disables intake, customer communication, operations, observation or Business Overview. Rebuild/restore defaults OFF and preserves root receipts/off-host claims.

Private proof: `/var/lib/optibrain/phase24-25/google-native-20261003T151221Z.json`, `google-refresh-verified.json`, `ga4-native-settings.json`, native validation under `/var/lib/optibrain/conversion-export/validation`; [Phase25 checkpoint](PHASE25_CHECKPOINT.md) records aggregates only. No secrets or customer identities belong in versioned evidence.
