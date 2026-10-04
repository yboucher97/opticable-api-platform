"""Explainable shadow trigger policy. No provider execution or CRM promotion."""
from datetime import datetime, timezone
from html import escape
import re
import unicodedata
from zoneinfo import ZoneInfo

from .acquisition_store import digest
from .sales_intelligence import collision, domain, email, live, stamp, contact_state
from .evidence_quality import geo_bucket

GEOGRAPHIES = {'MONTRÉAL', 'LAVAL', 'RIVE-NORD', 'GREATER MONTRÉAL', 'QUÉBEC CITY',
               'OTHER QUÉBEC', 'OTHER CANADA', 'FOREIGN', 'UNKNOWN'}
ACTOR_ROLES = {'BUYER', 'PROPERTY OWNER', 'DEVELOPER', 'TENANT', 'GENERAL CONTRACTOR',
               'ELECTRICAL CONTRACTOR', 'ARCHITECT', 'PROPERTY MANAGER', 'FACILITY OPERATOR', 'CONSULTANT'}
BUYING_ROLES = ACTOR_ROLES - {'ARCHITECT', 'CONSULTANT'}
ROLE_PATTERN = re.compile(r'owner|president|operations|facilit|property|immobilier|it\b|information|network|infrastructure|security|sécurité|construction|project|projet|procurement|approvision|maintenance|directeur technique', re.I)
TERMINAL = {'CLOSED', 'EXPIRED', 'CANCELLED', 'AWARDED', 'COMPLETED'}
HOLD_CHOICES = {'DO NOT CONTACT', 'BAD FIT', 'BAD TRIGGER', 'NOT NOW'}


def text(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').casefold())
                   if not unicodedata.combining(c))


def geography(row):
    geo = row.get('geography_class') or geo_bucket(row.get('geography'))
    if geo == 'QUÉBEC': geo = 'OTHER QUÉBEC'
    return geo if geo in GEOGRAPHIES else 'UNKNOWN'


def ref_id(value):
    return str(value.get('id') or '') if isinstance(value, dict) else str(value or '')


def company_identity(row, crm):
    proof = row.get('company_identity') or {}
    host = domain(row.get('domain'))
    cid = str(proof.get('crm_account_id') or '')
    accounts = [a for a in crm.get('Accounts', []) if live(a) and
                (cid and str(a.get('id')) == cid or host and domain(a.get('Website')) == host)]
    if len(accounts) > 1:
        return {'status': 'UNRESOLVED', 'domain': host, 'reason': 'Conflicting CRM company identities', 'crm_account_ids': []}
    supported = bool(host and proof.get('confidence') in {'EXACT', 'SUPPORTED'} and
                     str(proof.get('source_url', '')).startswith('https://') and
                     (domain(proof['source_url']) == host or proof.get('native_buyer_id') or proof.get('registry_number')))
    native = bool(cid and len(accounts) == 1 and proof.get('source_url'))
    native_buyer = bool(row.get('source_provider') == 'seao' and proof.get('native_buyer_id') and
                        (row.get('raw') or {}).get('buyer', {}).get('id') == proof['native_buyer_id'] and
                        proof.get('source_url') and row.get('source_record_id'))
    status = 'EXACT' if native or native_buyer else 'SUPPORTED' if supported else 'LIKELY' if host or row.get('company_name') else 'UNRESOLVED'
    return {'status': status, 'domain': host,
            'reason': 'Native CRM Account proof' if native else 'Native procurement buyer identity; domain linkage is independent' if native_buyer else 'Documented company/domain or buyer proof' if supported else 'Name/domain candidate is insufficient proof',
            'crm_account_ids': [str(a['id']) for a in accounts], 'evidence': proof}


def collision_state(row, identity, apollo, crm, *, now, crm_at):
    base = collision({'domain': identity['domain'], 'email': row.get('email')}, apollo, crm, now=now)
    account_ids = set(identity['crm_account_ids'])
    host = identity['domain']
    people = [(m, p) for m in ('Leads', 'Contacts') for p in crm.get(m, []) if live(p) and
              (host and (domain(p.get('Website')) == host or domain(email(p.get('Email')).split('@')[-1]) == host)
               or ref_id(p.get('Account_Name')) in account_ids)]
    contacts = [c for c in apollo.get('contacts', []) if str(c.get('id')) in base['apollo_matches']]
    stages = {r['id']: r.get('display_name', '') for r in apollo.get('stages', [])}
    states = [contact_state(c, apollo.get('messages', []) + apollo.get('replies', []), stages, now=now) for c in contacts]
    suppressed = bool(base['suppressed'] or row.get('suppressed') is True or row.get('do_not_contact') is True or
                      any(p.get('Email_Opt_Out') is True or p.get('Do_Not_Contact') is True or
                          p.get('Lead_Status') in {'Do Not Contact', 'Junk Lead'} for _, p in people))
    deals = [d for d in crm.get('Deals', []) if live(d) and ref_id(d.get('Account_Name')) in account_ids and
             not re.search(r'closed|won|lost|gagn|perdu|ferm', str(d.get('Stage', '')), re.I)]
    sites = [s for s in crm.get('Service_Locations', []) if live(s) and ref_id(s.get('Linked_Account') or s.get('Account_Name')) in account_ids]
    site_ids = {str(s['id']) for s in sites}
    related_deal_ids = {str(d['id']) for d in crm.get('Deals', []) if live(d) and ref_id(d.get('Account_Name')) in account_ids}
    services = [s for s in crm.get('Services', []) if live(s) and
                (ref_id(s.get('Account_Name')) in account_ids or ref_id(s.get('Linked_Service_Location')) in site_ids or ref_id(s.get('Linked_Deal')) in related_deal_ids)
                and not re.search(r'cancel|annul', str(s.get('Service_Stage', '')), re.I)]
    customer = bool(services or any(str(a.get('Account_Type', '')).casefold() == 'customer' for a in crm.get('Accounts', []) if str(a.get('id')) in account_ids))
    observed = stamp(apollo.get('at')); checked = stamp(crm_at)
    apollo_fresh = bool(observed and 0 <= (now-observed).total_seconds() <= 6*3600 and apollo.get('contacts_complete') is True)
    crm_fresh = bool(checked and 0 <= (now-checked).total_seconds() <= 2*3600 and crm.get('_identity_complete') is True)
    matchable = bool(host or account_ids)
    classification = ('SUPPRESSED' if suppressed else 'ACTIVE OUTREACH' if base['apollo_active'] or base['recent_apollo_send']
                      else 'OPEN DEAL' if deals else 'EXISTING CUSTOMER OPPORTUNITY' if customer
                      else 'EXISTING PROSPECT' if account_ids or people or base['apollo_matches'] or base['apollo_account_matches']
                      else 'NEW COMPANY' if apollo_fresh and crm_fresh and matchable and identity['status'] in {'EXACT', 'SUPPORTED'} else 'UNKNOWN')
    candidates = [{'id': str(c['id']), 'title': c.get('title'), 'role_relevance': 'SUPPORTED',
                   'source': 'Existing Apollo saved contact', 'contact_allowed': False} for c in contacts
                  if ROLE_PATTERN.search(str(c.get('title', ''))) and not contact_state(c, [], stages, now=now)['suppressed']][:5]
    return {**base, 'classification': classification, 'suppressed': suppressed, 'existing_customer': customer,
            'crm_account_ids': sorted(account_ids), 'crm_people': [{'module': m, 'id': str(p['id'])} for m, p in people],
            'open_deal_ids': [str(d['id']) for d in deals], 'service_location_ids': [str(s['id']) for s in sites],
            'apollo_fresh_complete': apollo_fresh, 'crm_fresh_complete': crm_fresh, 'identity_matchable': matchable,
            'crm_observed_at': crm_at, 'apollo_observed_at': apollo.get('at'), 'role_candidates': candidates,
            'contact_recommendation_allowed': False, 'cold_send_allowed': False}


def service_fit(row):
    description = text(str(row.get('title', '')) + ' ' + str(row.get('description', '')))
    explicit = []
    for service, pattern in [
        ('structured cabling', r'cablage|cat\s?6|low voltage|cabling'), ('fiber', r'fibre|fiber'),
        ('commercial Wi-Fi', r'wi.?fi|sans.fil'), ('network infrastructure', r'network|reseau informatique|telecommunication'),
        ('IP cameras / CCTV', r'camera|videosurveillance|cctv'), ('access control', r'access control|controle d.acces'),
        ('intercom', r'intercom'), ('alarm / security', r'alarme|intrusion'), ('IP telephony', r'telephonie|telephony|voip'),
        ('temporary construction Wi-Fi', r'construction.{0,40}wi.?fi|chantier.{0,40}wi.?fi'),
        ('construction cameras / timelapse', r'timelapse|chantier.{0,40}camera'),
        ('PTP / wireless links', r'point.to.point|ptp|liaison sans.fil'),
        ('AI loss prevention', r'loss prevention|prevention.{0,15}pertes'),
        ('managed network/support', r'managed network|reseau gere|support informatique'), ('maintenance', r'maintenance|entretien')]:
        if re.search(pattern, description): explicit.append(service)
    inferred = []
    if not explicit and re.search(r'warehouse|entrepot|commercial|industrial|industriel|office|bureau|multiresident|logements|institution', description):
        inferred = ['structured cabling', 'commercial Wi-Fi', 'IP cameras / CCTV']
    fits = explicit or inferred
    return {'primary': fits[:1], 'secondary': fits[1:3], 'basis': 'EXPLICIT SCOPE' if explicit else 'PROJECT-TYPE INFERENCE' if inferred else 'UNKNOWN',
            'recurring': ['maintenance/support review'] if fits else [], 'scope_confirmed': bool(explicit)}


def assess(row, apollo, crm, *, now, crm_at, feedback=None):
    if now.tzinfo is None: raise ValueError('Aware trigger time required')
    row = dict(row); identity = company_identity(row, crm); checked = collision_state(row, identity, apollo, crm, now=now, crm_at=crm_at)
    geo = geography(row); fit = service_fit(row)
    verified = stamp(row.get('last_verified_at')); publication = stamp(row.get('source_effective_at'))
    source_fresh = bool(verified and 0 <= (now-verified).total_seconds() <= row.get('refresh_seconds', 86400)*2)
    # Download time is not publication coverage. An old export cannot certify current status.
    coverage_fresh = bool(publication and 0 <= (now-publication).total_seconds() <= row.get('coverage_seconds', 7*86400))
    status = row.get('status', 'UNKNOWN'); deadline = stamp(row.get('closing_date'))
    if status not in {'CANCELLED', 'AWARDED', 'COMPLETED'} and deadline and deadline <= now: status = 'CLOSED'
    occurred = stamp(row.get('publish_date')); age = (now-occurred).total_seconds()/86400 if occurred else None
    recent = age is not None and 0 <= age <= row.get('event_max_age_days', 90)
    if status == 'ISSUED' and age is not None and age > row.get('event_max_age_days', 90): status = 'EXPIRED'
    actors = [{**a, 'confidence': a.get('confidence') if a.get('confidence') in {'EXACT', 'SUPPORTED', 'LIKELY', 'UNRESOLVED'} else 'UNRESOLVED'} for a in row.get('actors', []) if a.get('role') in ACTOR_ROLES]
    proven_actors = [a for a in actors if a['role'] in BUYING_ROLES and a['confidence'] in {'EXACT', 'SUPPORTED'} and a.get('source_actor_id') and a.get('source_url')]
    independent = len({e.get('source_provider') for e in row.get('corroboration', []) if e.get('source_provider') and e.get('source_url')} | {row.get('source_provider')})
    timely_tender = row.get('trigger_type') != 'PUBLIC TENDER' or bool(publication and (now-publication).total_seconds() <= 3*86400)
    confidence = ('STRONG' if identity['status'] in {'EXACT', 'SUPPORTED'} and proven_actors and source_fresh and coverage_fresh and timely_tender and row.get('source_version') and fit['primary']
                  else 'MODERATE' if identity['status'] in {'EXACT', 'SUPPORTED'} and (source_fresh or independent >= 2)
                  else 'TENTATIVE' if row.get('source_url') and row.get('title') else 'INSUFFICIENT')
    components = {'timing': 3 if deadline and 0 < (deadline-now).total_seconds() <= 7*86400 else 2 if recent else 0,
                  'service_fit': 3 if fit['basis'] == 'EXPLICIT SCOPE' else 2 if fit['primary'] else 0,
                  'geography': 2 if geo in {'MONTRÉAL', 'LAVAL', 'RIVE-NORD', 'GREATER MONTRÉAL'} else 1 if geo in {'QUÉBEC CITY', 'OTHER QUÉBEC'} else 0,
                  'relationship': 2 if checked['existing_customer'] or checked['open_deal_ids'] else 0,
                  'recurring_potential': 1 if fit['recurring'] else 0}
    quality = 'HIGH' if sum(components.values()) >= 8 else 'MEDIUM' if sum(components.values()) >= 5 else 'LOW'
    missing = []
    if identity['status'] not in {'EXACT', 'SUPPORTED'}: missing.append('Target company proof')
    if not proven_actors: missing.append('Buyer/operator actor proof; applicant is not automatically buyer')
    if not source_fresh or not coverage_fresh or not timely_tender: missing.append('Current source/version coverage; batch export may lag live addenda')
    if not checked['crm_fresh_complete'] or not checked['apollo_fresh_complete'] or not checked['identity_matchable']: missing.append('Fresh complete CRM/Apollo collision observation with matchable company identity')
    if not checked['role_candidates']: missing.append('Relevant decision-maker; procurement can be reviewed without a person')
    excluded = geo in {'FOREIGN', 'OTHER CANADA'} or status in TERMINAL or row.get('test_only') is True
    disposition = ('IGNORE' if excluded or not fit['primary'] else 'RESEARCH' if identity['status'] not in {'EXACT', 'SUPPORTED'} or geo == 'UNKNOWN' or status == 'UNKNOWN'
                   else 'WATCH' if not source_fresh or not coverage_fresh or not recent or checked['suppressed']
                   else 'ACT NOW' if confidence == 'STRONG' and components['timing'] == 3 and checked['crm_fresh_complete'] and checked['apollo_fresh_complete'] and checked['identity_matchable'] and not checked['ambiguous']
                   else 'REVIEW')
    if checked['ambiguous']: disposition = 'RESEARCH'
    tid = row.get('trigger_id') or digest([row['source_provider'], str(row['source_record_id'])])
    candidate = digest({'kind': 'trigger', 'record': tid})
    choice = (feedback or {}).get(candidate, {}).get('choice')
    if choice in HOLD_CHOICES: disposition = 'WATCH' if choice == 'NOT NOW' else 'IGNORE'
    if choice == 'DO NOT CONTACT': checked.update(suppressed=True, classification='SUPPRESSED')
    why = row.get('why_now') or ('Open procurement closes ' + str(row.get('closing_date')) if status == 'OPEN' else
          'Dated ' + row.get('trigger_type', 'project') + ': ' + str(row.get('publish_date')) + '; verify installation timing')
    action = ('No outreach recommendation; suppression applies' if checked['suppressed'] else
              'Review existing Apollo conversation; do not start competing outreach' if checked['apollo_active'] or checked['recent_apollo_send'] else
              'Review the existing CRM Deal / customer relationship' if checked['open_deal_ids'] or checked['existing_customer'] else
              'Resolve company and buying actors from source evidence' if disposition == 'RESEARCH' else
              'Retain historical research; no active sales action' if disposition == 'IGNORE' else
              'Verify current source/status before review' if disposition == 'WATCH' else
              'Review procurement requirements and current addenda; no bid or contact authorized' if row.get('trigger_type') == 'PUBLIC TENDER' else
              'Owner reviews service need, installation timing and relevant role; no contact authorized')
    sales_eligible = bool(disposition in {'ACT NOW', 'REVIEW'} and confidence == 'STRONG' and checked['crm_fresh_complete'] and checked['apollo_fresh_complete'] and checked['identity_matchable'] and
                          not checked['suppressed'] and not checked['ambiguous'] and not excluded)
    result = {**row, 'trigger_id': tid, 'key': candidate, 'status': status, 'geography_class': geo,
              'company_resolution_status': identity['status'], 'company_id': row.get('company_id'), 'company_identity_result': identity,
              'actors': actors, 'actor_confidence': 'SUPPORTED' if proven_actors else 'UNRESOLVED',
              'service_fit': fit, 'opportunity_quality': quality, 'quality_components': components,
              'evidence_confidence': confidence, 'independent_source_count': independent,
              'confidence_reasons': {'company': identity['status'], 'buyer_actor_proven': bool(proven_actors), 'source_verified': source_fresh, 'publication_coverage_current': coverage_fresh, 'tender_version_timely': timely_tender},
              'freshness': 'FRESH' if source_fresh and coverage_fresh else 'STALE / UNVERIFIED', 'event_age_days': round(age, 1) if age is not None else None,
              'collision': checked, 'priority_class': disposition, 'why_now': why, 'missing_data': missing,
              'commercial_value_band': row.get('commercial_value_band', 'UNKNOWN'),
              'recommended_next_action': action, 'owner_review_state': choice or ('READY FOR OWNER REVIEW' if disposition in {'REVIEW', 'ACT NOW'} else 'RESEARCH'),
              'sales_review_eligible': sales_eligible, 'contact_allowed': False, 'cold_send_allowed': False,
              'crm_promote_allowed': False, 'mode': 'SHADOW', 'evidence_kind': row.get('evidence_kind', 'CURRENT PUBLIC SIGNAL')}
    result['version'] = digest([tid, row.get('source_version'), disposition, confidence, checked['classification'], checked['suppressed'], checked['open_deal_ids']])
    reviewed = (feedback or {}).get(candidate, {})
    result['new_since_review'] = not reviewed or reviewed.get('version') != result['version']
    return result


def sales_rows(rows):
    result = []
    for row in rows:
        if not row['sales_review_eligible']: continue
        result.append({'key': row['key'], 'version': row['version'], 'kind': 'trigger',
                       'title': row.get('company_name') or row['title'], 'why': row['why_now'],
                       'action': row['recommended_next_action'], 'priority': 3 if row['priority_class'] == 'ACT NOW' else 4,
                       'outreach_owner': row['collision']['outreach_owner'], 'link': row['source_url'],
                       'priority_class': row['priority_class'], 'evidence_confidence': row['evidence_confidence'],
                       'geography': row['geography_class'], 'freshness': row['freshness'], 'collision_state': row['collision']['classification'],
                       'source_version': row['source_version'], 'source_effective_at': row.get('source_effective_at'),
                       'contact_allowed': False, 'cold_send_allowed': False, 'mode': 'SHADOW', 'suppressed': False})
    return result[:5]


def render_queue(view):
    h = lambda value: escape(str(value if value is not None else 'UNKNOWN'), quote=True)
    when = lambda value: stamp(value).astimezone(ZoneInfo('America/Toronto')).strftime('%Y-%m-%d %H:%M %Z') if stamp(value) else 'UNKNOWN'
    html = '<section><h2>Trigger opportunities — shadow owner review</h2><p>No outreach or CRM promotion. Priority and confidence are separate.</p>'
    for row in view.get('rows', [])[:8]:
        url = row.get('source_url', '')
        source = f"<a href='{h(url)}' rel='noreferrer'>Source</a>" if url.startswith('https://') else 'Source unavailable'
        html += f"<article><strong>{h(row['priority_class'])} · {h(row.get('company_name') or row['title'])}</strong><p>{h(row['title'])}<br>{h(row['why_now'])}</p>"
        html += f"<p>{h(row['geography_class'])} · confidence {h(row['evidence_confidence'])} · identity {h(row['company_resolution_status'])} · {h(row['freshness'])}<br>CRM/Apollo: {h(row['collision']['classification'])} · handled by {h(row['collision']['outreach_owner'])}</p>"
        html += f"<p>Service fit: {h(', '.join(row['service_fit']['primary'] + row['service_fit']['secondary']))} ({h(row['service_fit']['basis'])})<br>{h(row['recommended_next_action'])}</p>"
        html += '<p>Actors: '+h('; '.join(str(a.get('name') or 'Unresolved')+' ('+a['role']+', '+a['confidence']+')' for a in row.get('actors',[])[:3]) or 'UNRESOLVED')+'<br>Relevant roles: '+h('; '.join(str(c.get('title') or 'UNKNOWN') for c in row['collision'].get('role_candidates',[])[:3]) or 'UNKNOWN — OWNER RESEARCH')+'</p>'
        html += f"<small>{source} · version {h(row.get('source_version'))} · source coverage {when(row.get('source_effective_at'))} · checked {when(row.get('last_verified_at'))}<br>Missing: {h('; '.join(row['missing_data']))} · {'New / changed since review' if row['new_since_review'] else 'Reviewed'}</small>"
        html += f"<p><a href='/v1/operator/acquisition/review/{row['key']}'>Record owner review</a></p></article>"
    if not view.get('rows'): html += '<p>No current eligible trigger sample. See source coverage and research holds.</p>'
    return html + '</section>'
