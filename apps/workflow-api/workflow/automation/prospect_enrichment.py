"""Evidence-bound research enrichment. No execution authority or provider writes.

Reviewed proofs are supplied by the existing root observer, not a public API.
Source-native bindings, role age and scoped domains are checked on every replay.
The Phase30 event/Sales policy is deliberately unchanged.
"""
from collections import Counter
from datetime import timedelta
from html import escape
import json
import re
from urllib.parse import urlsplit

from .acquisition_store import digest, safe
from .sales_intelligence import domain, email, stamp
from .trigger_intelligence import collision_state, company_identity, text

CURRENT = {'VERIFIED_CURRENT', 'SUPPORTED_CURRENT'}
DOMAINS = {'OFFICIAL', 'SUPPORTED', 'LIKELY', 'UNKNOWN'}
SHARED = {'quebec.ca', 'gouv.qc.ca', 'montreal.ca', 'pharmaprix.ca'}
ROLE = re.compile(r'president|owner|operations|operation|facilit|property|immobili|informat|\bit\b|network|infrastructure|securit|construction|projet|project|procurement|approvision|maintenance|estimateur|estimator|plant manager|surintendant|developpement|resources materi|ressources materi|directeur general', re.I)
STRATEGIES = {
    'general contractor': ['Estimation / Project Management', 'Construction / Operations'],
    'electrical partner': ['Owner / Estimation', 'Low Voltage / Service Management'],
    'property management': ['Property Management / Facilities', 'Operations / IT'],
    'developer': ['Development / Construction', 'Property Management / IT'],
    'warehouse': ['Operations / Facilities', 'IT / Security'],
    'manufacturing': ['Plant / Maintenance', 'IT / Security'],
    'pharmacy': ['Owner / Operations', 'IT / Loss Prevention'],
    'retail': ['Facilities / Store Development', 'IT / Loss Prevention'],
    'institution': ['Procurement / Facilities', 'IT / Infrastructure'],
}


def useful_role(title):
    return bool(ROLE.search(text(title)))


def initialize(store):
    store.initialize_prospects()
    with store.connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS acquisition_enrichment_proofs(
          id TEXT PRIMARY KEY, prospect_id TEXT NOT NULL, observed_at TEXT NOT NULL,
          record TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS acquisition_enrichment_target ON acquisition_enrichment_proofs(prospect_id,observed_at);
        CREATE TABLE IF NOT EXISTS acquisition_enrichment_lookups(
          id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, provider TEXT NOT NULL,
          prospect_id TEXT NOT NULL, observed_at TEXT NOT NULL,
          next_eligible_at TEXT NOT NULL, result TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS acquisition_enrichment_retry ON acquisition_enrichment_lookups(fingerprint,observed_at);
        CREATE TABLE IF NOT EXISTS acquisition_enrichment_bundles(
          id TEXT PRIMARY KEY, accepted_at TEXT NOT NULL, record TEXT NOT NULL);
        ''')


def lookup_due(store, provider, kind, query, *, now):
    initialize(store); fingerprint = digest([provider, kind, query])
    with store.connect() as db:
        row = db.execute('SELECT next_eligible_at FROM acquisition_enrichment_lookups WHERE fingerprint=? ORDER BY observed_at DESC LIMIT 1', (fingerprint,)).fetchone()
    return not row or stamp(row[0]) <= now


def remember_lookup(store, provider, kind, query, result, *, now, prospect_id='', days=14):
    initialize(store); safe(query); safe(result)
    fingerprint = digest([provider, kind, query]); identifier = digest([fingerprint, now.isoformat()])
    with store.connect() as db:
        db.execute('INSERT OR IGNORE INTO acquisition_enrichment_lookups VALUES(?,?,?,?,?,?,?)',
                   (identifier, fingerprint, provider, prospect_id, now.isoformat(), (now+timedelta(days=days)).isoformat(), json.dumps(result)))


def validate(document):
    safe(document)
    if not isinstance(document, dict) or document.get('schema') != 1: raise ValueError('Enrichment proof schema required')
    if len(json.dumps(document).encode()) > 1048576: raise ValueError('Enrichment proof byte limit')
    if len(document.get('organizations', [])) > 256 or len(document.get('actors', [])) > 128: raise ValueError('Enrichment proof row limit')
    for proof in document.get('organizations', []):
        if not re.fullmatch('[0-9a-f]{64}', str(proof.get('prospect_id', ''))): raise ValueError('Native prospect binding required')
        if not proof.get('bindings'): raise ValueError('Source-native bindings required')
        if not str(proof.get('source_url', '')).startswith('https://') or not stamp(proof.get('observed_at')): raise ValueError('Dated HTTPS evidence required')
        host = domain(proof.get('domain'))
        if host and (host != proof['domain'] or proof.get('domain_confidence') not in DOMAINS): raise ValueError('Normalized domain confidence required')
        if host and not proof.get('domain_evidence'): raise ValueError('Explicit website evidence required')
        if len(proof.get('contacts', [])) > 30: raise ValueError('Contact bound')
        for person in proof.get('contacts', []):
            if not person.get('id') or person.get('confidence') not in CURRENT | {'LIKELY', 'STALE', 'UNRESOLVED'}: raise ValueError('Separate contact confidence required')
            if not str(person.get('source_url', '')).startswith('https://') or not stamp(person.get('observed_at')): raise ValueError('Contact provenance required')
            if person.get('confidence') in CURRENT and not person.get('current_employer_proven'): raise ValueError('Current employer proof required')
            if person.get('email') and not person.get('email_source_url'): raise ValueError('No inferred email patterns')
    return document


def resolve_document(store, supplied, *, now):
    """Isolate one bad input and reuse original dates; never invent freshness."""
    initialize(store)
    try:
        document = validate(supplied)
    except (ValueError, TypeError, KeyError):
        with store.connect() as db:
            row = db.execute('SELECT record FROM acquisition_enrichment_bundles ORDER BY accepted_at DESC LIMIT 1').fetchone()
        document = validate(json.loads(row[0])) if row else {'schema': 1, 'organizations': [], 'actors': []}
        return document, 'PARTIAL — PRIOR DATED EVIDENCE RETAINED'
    with store.connect() as db:
        db.execute('INSERT OR IGNORE INTO acquisition_enrichment_bundles VALUES(?,?,?)', (digest(document), now.isoformat(), json.dumps(document, ensure_ascii=False)))
    return document, 'WORKING'


def bound(proof, prospect):
    sources = {(s['provider'], str(s['record_id'])) for s in prospect['source_provenance']}
    return all((b['provider'], str(b['record_id'])) in sources for b in proof['bindings'])


def actor_seeds(document, queue, *, now):
    """Tenant/operator proof is not proof of the commissioning buyer."""
    events = {r['trigger_id']: r for r in queue['rows']}; seeds = []
    for a in document.get('actors', []):
        row = events.get(a.get('trigger_id'))
        if not row or str(row['source_record_id']) != str(a.get('source_record_id')): continue
        if a.get('confidence') not in {'EXACT', 'SUPPORTED', 'LIKELY', 'UNRESOLVED'} or not a.get('name') or not stamp(a.get('observed_at')) or not str(a.get('source_url', '')).startswith('https://'): continue
        seeds.append({'company_name': a['name'], 'identity_status': a['confidence'],
            'source_provider': 'prospect_actor', 'source_record_id': a['organization_key'],
            'source_url': a['source_url'], 'observed_at': a['observed_at'],
            'domain': a.get('domain'), 'actor_role': a['role'], 'actors': [a],
            'location': row.get('location'), 'geography_class': row['geography_class'],
            'icp': a.get('icp'), 'service_fit': {'primary': [], 'secondary': [], 'possible': a.get('service_fit', ['structured cabling', 'commercial Wi-Fi', 'IP cameras / CCTV']), 'basis': 'GENERAL ICP FIT — NEED UNPROVEN'},
            'why_opticable': a['role']+' at a sourced commercial/institutional site; procurement responsibility is unproven.'})
    return seeds


def apply(store, view, document, apollo, crm, *, now, crm_at):
    initialize(store); validate(document)
    records = view['records']; targets = {p['prospect_id']: p for p in records}; held = []
    for attempt in document.get('lookups', [])[:128]:
        at = stamp(attempt.get('observed_at'))
        if at and at <= now:
            remember_lookup(store, attempt['provider'], attempt['kind'], attempt['query'],
                            {k:v for k,v in attempt.items() if k not in {'response','query'}},
                            now=at, prospect_id=attempt.get('prospect_id',''))
    for proof in document.get('organizations', []):
        p = targets.get(proof['prospect_id'])
        if not p or not bound(proof, p): held.append({'prospect_id': proof['prospect_id'], 'reason': 'SOURCE BINDING MISMATCH'}); continue
        identifier = digest(proof)
        with store.connect() as db:
            db.execute('INSERT OR IGNORE INTO acquisition_enrichment_proofs VALUES(?,?,?,?)', (identifier, p['prospect_id'], proof['observed_at'], json.dumps(proof, ensure_ascii=False)))
        p['enrichment_evidence'] = proof
        p['last_enriched'] = proof['observed_at']
        if proof.get('domain'):
            p['domain'] = proof['domain']; p['website'] = proof.get('website') or 'https://'+proof['domain']
            p['domain_confidence'] = proof['domain_confidence']
            if p['identity_status'] not in {'EXACT','SUPPORTED'} and proof['domain_confidence']=='OFFICIAL':
                p['identity_status']='SUPPORTED'
        if proof.get('geography_class'): p['geography_class'] = proof['geography_class']
        if proof.get('location'): p['location'] = proof['location']
        if proof.get('icp'): p['icp'] = proof['icp']
        shared = proof.get('shared_domain') or p.get('domain') in SHARED
        p['domain_scope'] = 'SHARED ORGANIZATION / DEPARTMENT' if shared else 'DEDICATED ORGANIZATION'
        # Generic government/corporate domains cannot establish a distinct buyer
        # or prove absence across CRM/Apollo. Native CRM ID is still usable.
        ids = p['collision'].get('crm_account_ids', [])
        native = proof.get('crm_account_id') or (ids[0] if len(ids) == 1 else None)
        if proof.get('crm_account_id'):
            account = next((x for x in crm.get('Accounts', []) if str(x.get('id')) == str(native)), None)
            contacts = [x for x in crm.get('Contacts', []) if str((x.get('Account_Name') or {}).get('id')) == str(native)]
            address = email(proof.get('crm_contact_email'))
            public_binding = bool(address and domain(address.split('@')[-1]) == p.get('domain') and any(
                email(c.get('email')) == address and c.get('email_source_url') and c.get('current_employer_proven') for c in proof.get('contacts', [])))
            if not public_binding or not account or not any(email(x.get('Email')) == address for x in contacts if x.get('Email')):
                held.append({'prospect_id': p['prospect_id'], 'reason': 'NATIVE CRM CONTACT BINDING MISMATCH'}); native = None
        check_row = {'domain': None if shared else p.get('domain'), 'company_name': p['canonical_name'], 'company_identity': {'crm_account_id': native}, 'suppressed': p['collision'].get('suppressed', False)}
        identity = company_identity(check_row, crm)
        if identity.get('reason') != 'Conflicting CRM company identities': identity['status'] = p['identity_status']
        p['collision'] = collision_state(check_row, identity, apollo, crm, now=now, crm_at=crm_at)
        old = {c['id']: c for c in p['contacts']}
        for supplied in proof.get('contacts', []):
            c = dict(supplied); at = stamp(c['observed_at'])
            c['role_relevant'] = useful_role(c.get('title'))
            if c['confidence'] in CURRENT:
                if not 0 <= (now-at).total_seconds() <= 180*86400: c['confidence'] = 'STALE'
                elif not c['role_relevant']: c['confidence'] = 'LIKELY'
            c['contact_allowed'] = False
            c.setdefault('email_verification', 'PUBLICLY LISTED — DELIVERABILITY UNKNOWN' if c.get('email') else 'UNKNOWN')
            c['role_confidence'] = c['confidence']; c['company_domain_match'] = c.get('current_employer_proven', False)
            # Propagate native opt-out/bounce/active ownership rather than using
            # public directory evidence to clear suppression.
            address = email(c.get('email'))
            c['suppressed'] = bool(c.get('suppressed') or old.get(c['id'], {}).get('suppressed') or any(
                email(x.get('Email')) == address and x.get('Email_Opt_Out') is True for x in crm.get('Contacts', []) if address))
            matches = [x for x in apollo.get('contacts', []) if address and email(x.get('email')) == address]
            c['suppressed'] |= any(x.get('email_unsubscribed') or x.get('do_not_contact') or x.get('email_status') == 'bounced' for x in matches)
            old[c['id']] = c
        # Same exact sourced email can consolidate duplicate person receipts.
        # Names/title similarity and absent email never merge people.
        by_email = {}; combined = []
        for c in old.values():
            address = email(c.get('email'))
            if address and address in by_email:
                prior = by_email[address]
                winner, loser = (c, prior) if c.get('confidence') in CURRENT and prior.get('confidence') not in CURRENT else (prior, c)
                winner['suppressed'] = bool(winner.get('suppressed') or loser.get('suppressed'))
                winner['source_variants'] = list({v['id']:v for v in winner.get('source_variants', [])+[{'id':loser['id'],'source_url':loser.get('source_url'),'confidence':loser.get('confidence')} ]}.values())
                if winner is c: combined[combined.index(prior)] = c; by_email[address] = c
            else:
                combined.append(c)
                if address: by_email[address] = c
        p['contacts'] = combined[:30]
    # Preserve project placeholders and source history. A supported operator
    # narrows research but does not invent an owner/GC/permit applicant.
    for p in records:
        links = [a for a in document.get('actors', []) if a.get('trigger_id') in p['trigger_ids']]
        if links: p['resolved_project_actors'] = links
        if p['entity_kind'] == 'ORGANIZATION' and p['source_provenance'][0]['provider'] == 'prospect_actor':
            links = [a for a in document.get('actors', []) if a['organization_key'] == p['source_provenance'][0]['record_id']]
            p['project_actor_links'] = links
            p['domain_confidence'] = 'OFFICIAL' if p.get('domain') and links else 'UNKNOWN'
            for a in links:
                event = next(r for r in view.get('_events', []) if r['trigger_id'] == a['trigger_id']) if view.get('_events') else None
                if event and a.get('service_trigger_supported', True) and event['status'] not in {'CLOSED', 'EXPIRED', 'CANCELLED', 'AWARDED'}:
                    p['current_trigger_ids'] = sorted(set(p['current_trigger_ids']) | {a['trigger_id']})
                p['trigger_ids'] = sorted(set(p['trigger_ids']) | {a['trigger_id']})
        refresh_status(p)
    # Equivalent native identities may be grouped only by explicit reviewed
    # native-email + official-site evidence; originals remain durable receipts.
    for proof in document.get('organizations', []):
        p = targets.get(proof['prospect_id']); other = targets.get(proof.get('equivalent_prospect_id'))
        if p and other and bound(proof, p) and proof.get('crm_account_id') and p['collision'].get('crm_account_ids') == [str(proof['crm_account_id'])] and domain(other.get('domain')) == p.get('domain'):
            other['equivalent_to'] = p['prospect_id']; other['equivalence_evidence'] = proof['source_url']
            p['equivalent_source_ids'] = sorted(set(p.get('equivalent_source_ids', [])) | {other['prospect_id']})
            # Canonical row already gathered saved contacts for this domain;
            # merging the native identity must not duplicate that same person.
            known_emails={email(c.get('email')) for c in p['contacts'] if email(c.get('email'))}
            known_ids={c['id'] for c in p['contacts']}
            p['contacts'] += [c for c in other['contacts'] if c['id'] not in known_ids and (not email(c.get('email')) or email(c.get('email')) not in known_emails)]
            p['contacts'] = p['contacts'][:30]
            p['trigger_ids'] = sorted(set(p['trigger_ids']+other['trigger_ids'])); refresh_status(p)
    store.persist(records, [], now=now)
    active = [p for p in records if not p.get('equivalent_to')]
    orgs = [p for p in active if p['entity_kind'] == 'ORGANIZATION']
    relevant = [p for p in orgs if p['prospecting_status'] != 'TERMINAL IGNORE']
    losses = Counter(x for p in relevant for x in p['why_not_ready'])
    metrics = {'organizations': len(orgs), 'domains_resolved': sum(bool(p.get('domain')) and p.get('domain_confidence') in {'OFFICIAL', 'SUPPORTED'} for p in orgs),
        'domains_missing': sum(not p.get('domain') for p in orgs), 'useful_contact_organizations': sum(p['contact_coverage']['valid_roles'] > 0 for p in orgs),
        'organizations_needing_contacts': sum(not p['contact_coverage']['valid_roles'] for p in orgs),
        'unknown_collisions': sum(p['collision']['classification'] == 'UNKNOWN' for p in orgs),
        'projects_retained': sum(p['entity_kind'] == 'UNRESOLVED PROJECT' for p in active),
        'projects_with_supported_actors': sum(p['entity_kind'] == 'UNRESOLVED PROJECT' and any(a['confidence'] in {'EXACT', 'SUPPORTED'} for a in p.get('resolved_project_actors', [])) for p in active),
        'prospecting_ready': sum(p['enrichment_readiness'] == 'PROSPECTING_READY' for p in relevant),
        'one_step_away': sum(sum(x in {'NO_DOMAIN', 'NO_CONTACT', 'UNKNOWN_COLLISION', 'UNKNOWN_GEOGRAPHY', 'NO_COMPANY'} for x in p['why_not_ready']) == 1 for p in relevant if not p['collision']['suppressed']),
        'equivalent_records_retained': len(records)-len(active)}
    view.update(schema=2, enrichment_metrics=metrics, enrichment_holds=held, records=active,
        enrichment_backlog=dict(Counter(x for p in active for x in p['enrichment_queue'])),
        domain_confidence_counts=dict(Counter(p['domain_confidence'] for p in orgs)),
        contact_counts=dict(Counter(c['confidence'] for p in orgs for c in p['contacts'])),
        unknown_collisions=metrics['unknown_collisions'], why_not_ready=dict(losses),
        pool_counts=dict(Counter(p['prospecting_status'] for p in active)))
    view.update(identity_counts=dict(Counter(p['identity_status'] for p in orgs)),
        current_trigger_prospects=sum(bool(p['current_trigger_count']) for p in relevant),
        no_current_trigger_prospects=sum(not p['current_trigger_count'] for p in relevant),
        icp_only_prospects=sum(not p['trigger_count'] for p in relevant),
        historical_organizations=sum(bool(p['historical_trigger_count'] or p.get('historical_projects')) for p in relevant),
        repeat_buyers=sum(p['repeat_buyer'] for p in relevant))
    view['funnel'].update(organizations=len(orgs), relevant_organizations=len(relevant), resolved=sum(p['identity_status'] in {'EXACT','SUPPORTED'} for p in relevant), with_contacts=sum(p['contact_coverage']['valid_roles'] > 0 for p in relevant), prospecting_ready=metrics['prospecting_ready'])
    view['coverage_health'].update(company_resolution={'numerator':view['funnel']['resolved'],'denominator':len(relevant)}, contact_coverage={'numerator':view['funnel']['with_contacts'],'denominator':len(relevant)},unknown_collision={'numerator':losses['UNKNOWN_COLLISION'],'denominator':len(relevant)})
    view.pop('_events', None)
    return view


def refresh_status(p):
    check = p['collision']; contacts = p.get('contacts', [])
    p['trigger_count'] = len(p['trigger_ids']); p['current_trigger_count'] = len(p['current_trigger_ids']); p['historical_trigger_count'] = len(p['historical_trigger_ids'])
    for c in contacts: c['contact_allowed'] = False
    valid = [c for c in contacts if c.get('confidence') in CURRENT and not c.get('suppressed')]
    p.setdefault('domain_confidence', 'SUPPORTED' if p.get('domain') else 'UNKNOWN')
    p['company_confidence'] = p['identity_status']
    p['contact_coverage'] = {'valid_roles': len(valid), 'candidates': len(contacts), 'primary_role': valid[0].get('title') if valid else None,
        'secondary_roles': [c.get('title') for c in valid[1:]], 'role_strategy': STRATEGIES.get(p.get('icp'), ['Facilities / Operations', 'IT / Procurement']),
        'named_people': sum(bool(c.get('name')) for c in valid), 'functional_endpoints': sum(c.get('contact_kind') == 'ROLE_ENDPOINT' for c in valid)}
    p['CRM_state'] = 'OPEN DEAL' if check['open_deal_ids'] else 'EXISTING CUSTOMER' if check['existing_customer'] else 'CRM ACCOUNT' if check['crm_account_ids'] else 'CRM CONTACT/LEAD' if check['crm_people'] else 'NEW' if check['crm_fresh_complete'] and check['identity_matchable'] and not check['ambiguous'] else 'UNKNOWN'
    p['Apollo_state'] = 'ACTIVE SEQUENCE / RECENT CONTACT' if check['apollo_active'] or check['recent_apollo_send'] else 'IN APOLLO' if check['apollo_matches'] or check['apollo_account_matches'] else 'NOT IN APOLLO' if check['apollo_fresh_complete'] and check['identity_matchable'] else 'UNKNOWN'
    reasons = [x for x in p.get('why_not_ready', []) if x not in {'NO_COMPANY', 'NO_DOMAIN', 'NO_CONTACT', 'UNKNOWN_COLLISION', 'UNKNOWN_GEOGRAPHY', 'SUPPRESSED'}]
    if p['identity_status'] not in {'EXACT','SUPPORTED'}: reasons.append('NO_COMPANY')
    if not p.get('domain') or p['domain_confidence'] not in {'OFFICIAL', 'SUPPORTED'}: reasons.append('NO_DOMAIN')
    if not valid: reasons.append('NO_CONTACT')
    if check['classification'] == 'UNKNOWN': reasons.append('UNKNOWN_COLLISION')
    if p['geography_class'] == 'UNKNOWN': reasons.append('UNKNOWN_GEOGRAPHY')
    suppressed = check['suppressed'] or any(c.get('suppressed') and c.get('confidence') in CURRENT for c in contacts)
    if suppressed: reasons.append('SUPPRESSED')
    p['why_not_ready'] = sorted(set(reasons)); p['outbound_authorized'] = False; p['crm_promote_allowed'] = False
    active_elsewhere = check['apollo_active'] or check['recent_apollo_send'] or bool(check['open_deal_ids'])
    ready = not suppressed and not active_elsewhere and p['identity_status'] in {'EXACT', 'SUPPORTED'} and p['domain_confidence'] in {'OFFICIAL', 'SUPPORTED'} and bool(valid) and p['geography_class'] not in {'FOREIGN', 'OTHER CANADA', 'UNKNOWN'} and check['classification'] != 'UNKNOWN' and not check['ambiguous'] and bool(p['service_categories_seen'])
    p['enrichment_readiness'] = 'SUPPRESSED' if suppressed else 'ACTIVE_ELSEWHERE' if active_elsewhere else 'PROSPECTING_READY' if ready else 'COMPANY_ONLY' if 'NO_DOMAIN' in reasons else 'ROLE_NEEDED' if not valid else 'COLLISION_PENDING' if 'UNKNOWN_COLLISION' in reasons else 'CONTACT_SUPPORTED'
    p['future_outreach_state'] = 'SUPPRESSED' if suppressed else 'COLLISION_REVIEW' if active_elsewhere or check['existing_customer'] or check['classification']=='UNKNOWN' else 'OWNER_REVIEW' if ready else 'CONTACT_REQUIRED' if not valid else 'RESEARCHING'
    p['enrichment_queue'] = (['RESOLVE_ACTOR'] if p['entity_kind'] == 'UNRESOLVED PROJECT' else []) + (['RESOLVE_COMPANY'] if 'NO_COMPANY' in reasons else []) + (['RESOLVE_DOMAIN'] if 'NO_DOMAIN' in reasons else []) + (['FIND_PRIMARY_ROLE'] if not valid else ['FIND_SECONDARY_ROLE'] if len(valid) == 1 else []) + (['VERIFY_EMPLOYER'] if any(c.get('confidence') in {'LIKELY', 'STALE', 'UNRESOLVED'} for c in contacts) else []) + (['CHECK_CRM', 'CHECK_APOLLO'] if 'UNKNOWN_COLLISION' in reasons else [])
    if suppressed: p['prospecting_status'] = 'SUPPRESSED'; p['suppression_state'] = 'SUPPRESSED'
    elif p['geography_class'] in {'FOREIGN', 'OTHER CANADA'}: p['prospecting_status'] = 'TERMINAL IGNORE'; p['ignore_audit']['reason'] = 'WRONG_COUNTRY'
    elif active_elsewhere: p['prospecting_status'] = 'ACTIVE DEAL' if check['open_deal_ids'] else 'ACTIVE APOLLO'
    elif check['existing_customer']: p['prospecting_status'] = 'EXISTING CUSTOMER'
    elif ready: p['prospecting_status'] = 'PROSPECTING READY'
    elif 'NO_COMPANY' in reasons or 'NO_DOMAIN' in reasons: p['prospecting_status'] = 'NEEDS COMPANY RESOLUTION'
    elif not valid: p['prospecting_status'] = 'NEEDS CONTACT'
    else: p['prospecting_status'] = 'RESEARCH'


def details(view):
    keys = ('prospect_id', 'canonical_name', 'domain', 'website', 'location', 'icp', 'geography_class', 'why_opticable', 'why_now', 'service_categories_seen', 'current_trigger_count', 'historical_trigger_count', 'repeat_buyer_count', 'company_confidence', 'domain_confidence', 'domain_scope', 'contact_coverage', 'CRM_state', 'Apollo_state', 'suppression_state', 'enrichment_readiness', 'enrichment_queue', 'next_research_at', 'last_enriched', 'why_not_ready')
    rows = []
    for p in view['records']:
        if p['entity_kind'] != 'ORGANIZATION': continue
        row = {k: p.get(k) for k in keys}
        row['contacts'] = [{k: c.get(k) for k in ('name', 'title', 'confidence', 'contact_kind', 'source_url', 'observed_at', 'email_verification', 'suppressed')} | {'channel_available': bool(c.get('email')), 'contact_allowed': False} for c in p['contacts'][:12]]
        row['source_url'] = p.get('enrichment_evidence', {}).get('source_url') or p['source_provenance'][0]['url']; rows.append(row)
    total=len(rows);rows=rows[:256]
    # The research DB retains every record. Display truncation never deletes
    # evidence or makes one large contact directory disable other observers.
    while rows and len(json.dumps(rows,ensure_ascii=False,indent=2).encode())>250000:rows.pop()
    return {'schema': 1, 'at': view['at'], 'scope': 'live', 'read_only': True, 'rows': rows, 'display_limit': 256, 'omitted':total-len(rows)}


def render_detail(row):
    h = lambda value: escape(str(value if value is not None else 'UNKNOWN'), quote=True)
    result = '<h1>'+h(row['canonical_name'])+'</h1><p>Shadow research. No outreach or CRM promotion authority.</p>'
    for key in ('website', 'geography_class', 'icp', 'why_opticable', 'why_now', 'service_categories_seen', 'company_confidence', 'domain_confidence', 'CRM_state', 'Apollo_state', 'suppression_state', 'enrichment_readiness', 'enrichment_queue', 'last_enriched', 'next_research_at'):
        result += '<p><strong>'+h(key.replace('_',' '))+':</strong> '+h(row.get(key))+'</p>'
    result += '<h2>Roles and contacts</h2>'
    for c in row.get('contacts', []):
        result += '<p>'+h(c.get('name') or 'Functional role endpoint')+' · '+h(c.get('title'))+' · '+h(c.get('confidence'))+' · '+h(c.get('observed_at'))+'<br>Channel: '+h(c.get('channel_available'))+' · '+h(c.get('email_verification'))+'<br><a href="'+h(c.get('source_url'))+'">Source evidence</a></p>'
    return result+'<p><a href="/v1/operator/acquisition">Acquisition coverage</a></p>'
