"""Broad research retention, with no relaxation of the separate Sales/send gate.

Source-native company identities and unresolved projects are separate. Closed
events retain buyer value. No API writes, CRM promotion or send executor exists.
"""
from collections import Counter
from datetime import timedelta
from html import escape
import json
import re

from .acquisition_store import digest, safe
from .trigger_store import TriggerStore
from .trigger_intelligence import (TERMINAL, ROLE_PATTERN, company_identity,
                                   collision_state, service_fit, geography, text)
from .sales_intelligence import domain, email, live, stamp, contact_state

FINAL_REASONS = {'NOT_SERVICE_FIT', 'WRONG_COUNTRY', 'CLEARLY_OUT_OF_MARKET',
                 'DUPLICATE_SIGNAL', 'SOURCE_NOISE', 'INVALID_RECORD',
                 'NO_COMMERCIAL_RELEVANCE', 'TERMINAL_NO_REUSE_VALUE', 'OTHER_EXPLICIT_REASON'}
ICP_PATTERNS = [
    ('property management', r'property manag|gestion immobili|immobilier|commercial landlord'),
    ('developer', r'developpeur|developer|real estate develop'),
    ('general contractor', r'construction|contractor|entrepreneur general'),
    ('electrical partner', r'electric|electri'),
    ('multi-residential', r'multiresident|multi.resident|apartments|logements'),
    ('senior housing', r'senior|residence.{0,20}aine|retirement'),
    ('warehouse', r'warehouse|entrepot|distribution|logistic|logistique'),
    ('manufacturing', r'manufactur|fabrication|industri|usine'),
    ('pharmacy', r'pharma|pharmacie'),
    ('retail', r'retail|grocery|epicer|depanneur|gas station|station.service'),
    ('automotive', r'dealership|concession|auto.parts|pieces.{0,10}auto'),
    ('institution', r'college|universit|school|scolaire|municipal|ville de|hospital|hopital'),
    ('commercial facilities', r'commercial|office|bureau|facility|facilities')]


def icp(value):
    value = text(value)
    return next((name for name, pattern in ICP_PATTERNS if re.search(pattern, value)), None)


def research_fit(row):
    fit = row.get('service_fit') or service_fit(row)
    if fit.get('primary') or fit.get('possible'): return fit
    # Venue/industry evidence can support research even when it does not support
    # Phase30's current-service scope. Never changes that independent gate.
    description = text(str(row.get('title', ''))+' '+str(row.get('description', '')))
    if re.search(r'local sportif|commercial|warehouse|entrepot|industri|bureau|logements|institution', description):
        return {'primary': [], 'secondary': [], 'possible': ['commercial Wi-Fi', 'IP cameras / CCTV', 'structured cabling'], 'basis':'GENERAL ICP FIT — NEED UNPROVEN'}
    return fit


def explicit_nonfit(row):
    return bool(row.get('not_service_fit_confirmed') or re.search(r'laue|microscop|egout|decorative fountain|abattage|piscine individuelle', text(row.get('title'))))


class ProspectStore(TriggerStore):
    MAX_PROSPECTS = 5000

    def initialize_prospects(self):
        self.initialize()
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS acquisition_prospects(
              id TEXT PRIMARY KEY, company_id TEXT, first_seen TEXT NOT NULL,
              last_seen TEXT NOT NULL, last_evaluated TEXT NOT NULL, record TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS acquisition_prospects_company ON acquisition_prospects(company_id);
            CREATE TABLE IF NOT EXISTS acquisition_phase30_classifications(
              trigger_id TEXT PRIMARY KEY, captured_at TEXT NOT NULL, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS acquisition_trigger_retention(
              trigger_id TEXT PRIMARY KEY, evaluated_at TEXT NOT NULL, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS acquisition_research_attempts(
              id TEXT PRIMARY KEY, prospect_id TEXT NOT NULL, provider TEXT NOT NULL,
              attempt_type TEXT NOT NULL, observed_at TEXT NOT NULL,
              next_eligible_at TEXT NOT NULL, result TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS acquisition_research_due
              ON acquisition_research_attempts(prospect_id,provider,attempt_type,observed_at);
            ''')

    def capture_baseline(self, queue, *, now):
        """An immutable source receipt, not a recomputed historical decision."""
        self.initialize_prospects()
        with self.connect() as db:
            if db.execute('SELECT count(*) FROM acquisition_phase30_classifications').fetchone()[0]: return
            rows = queue.get('rows', [])
            if len(rows) != 125 or len({r['trigger_id'] for r in rows}) != 125 or queue.get('trigger_count') != 125:
                raise ValueError('Exact125 Phase30 baseline receipt required before reclassification')
            for row in rows:
                record = {k: row.get(k) for k in ('trigger_id', 'priority_class', 'status',
                          'source_provider', 'source_record_id', 'source_version', 'version', 'company_id')}
                db.execute('INSERT INTO acquisition_phase30_classifications VALUES(?,?,?)',
                           (row['trigger_id'], now.isoformat(), json.dumps(record)))

    def baseline(self):
        self.initialize_prospects()
        with self.connect() as db:
            return {r['trigger_id']: json.loads(r['record']) for r in
                    db.execute('SELECT * FROM acquisition_phase30_classifications')}

    def persist(self, records, audits, *, now):
        self.initialize_prospects(); held = 0
        with self.connect() as db:
            count = db.execute('SELECT count(*) FROM acquisition_prospects').fetchone()[0]
            for row in records:
                safe(row)
                old = db.execute('SELECT first_seen FROM acquisition_prospects WHERE id=?', (row['prospect_id'],)).fetchone()
                if not old and count >= self.MAX_PROSPECTS:
                    held += 1; continue
                row['first_seen'] = old[0] if old else row['first_seen']
                raw = json.dumps(row, ensure_ascii=False)
                if len(raw.encode()) > 131072: raise ValueError('Prospect record bound exceeded')
                db.execute('INSERT INTO acquisition_prospects VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                           'company_id=excluded.company_id,last_seen=excluded.last_seen,last_evaluated=excluded.last_evaluated,record=excluded.record',
                           (row['prospect_id'], row.get('company_identity_id'), row['first_seen'], row['last_seen'], now.isoformat(), raw))
                if not old: count += 1
            for audit in audits:
                db.execute('INSERT OR REPLACE INTO acquisition_trigger_retention VALUES(?,?,?)',
                           (audit['trigger_id'], now.isoformat(), json.dumps(audit, ensure_ascii=False)))
        return held

    def records(self, *, prospects=False):
        if not prospects: return super().records()
        self.initialize_prospects()
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT record FROM acquisition_prospects ORDER BY id LIMIT ?', (self.MAX_PROSPECTS,))]

    def attempt(self, pid, provider, kind, result, *, now, interval=14*86400):
        self.initialize_prospects(); safe(result)
        key = digest([pid, provider, kind, now.isoformat()])
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO acquisition_research_attempts VALUES(?,?,?,?,?,?,?)',
                       (key, pid, provider, kind, now.isoformat(), (now+timedelta(seconds=interval)).isoformat(), json.dumps(result)))

    def retry_due(self, pid, provider, kind, *, now):
        self.initialize_prospects()
        with self.connect() as db:
            row = db.execute('SELECT next_eligible_at FROM acquisition_research_attempts WHERE prospect_id=? AND provider=? AND attempt_type=? ORDER BY observed_at DESC LIMIT 1',
                             (pid, provider, kind)).fetchone()
        return not row or stamp(row[0]) <= now


def event_retention(row, original, *, now):
    fit = research_fit(row); reusable = bool((fit.get('primary') or fit.get('possible')) and
        (row.get('company_name') or row.get('actors') or row.get('location')))
    terminal_event = row['status'] in TERMINAL
    reason = ('WRONG_COUNTRY' if row['geography_class'] in {'FOREIGN', 'OTHER CANADA'} else
              'INVALID_RECORD' if row.get('test_only') else
              'NOT_SERVICE_FIT' if explicit_nonfit(row) else
              'TERMINAL_NO_REUSE_VALUE' if terminal_event and not reusable else None)
    suppressed = row['collision']['suppressed']
    category = ('TERMINAL IGNORE' if reason else 'SUPPRESSED' if suppressed else
                'HISTORICAL INTELLIGENCE' if terminal_event else
                'NEEDS COMPANY RESOLUTION' if row['company_resolution_status'] not in {'EXACT', 'SUPPORTED'} else
                'WATCH' if row['priority_class'] == 'WATCH' else
                'CURRENT OPPORTUNITY' if row['priority_class'] in {'REVIEW', 'ACT NOW'} else 'RESEARCH')
    return {'trigger_id': row['trigger_id'], 'original_phase30': original,
            'event_status': row['status'], 'current_actionability': bool(not terminal_event and row['priority_class'] in {'REVIEW', 'ACT NOW'} and not reason and not suppressed),
            'retention_class': category, 'historical_reuse_value': terminal_event and reusable and not reason,
            'company_resolution_value': bool(not reason and row['company_resolution_status'] not in {'EXACT', 'SUPPORTED'}),
            'contact_resolution_value': bool(not reason and not row['collision']['role_candidates']),
            'repeat_buyer_value': bool(not reason and row.get('company_name') and fit['primary']),
            'service_fit_value': bool(fit.get('primary') or fit.get('possible')), 'watch_value': bool(not reason and (terminal_event or category == 'WATCH')),
            'ignore': {'reason': reason, 'at': now.isoformat() if reason else None,
                       'source': row['source_url'], 'reconsideration': 'REVISITABLE' if reason in {'NOT_SERVICE_FIT', 'TERMINAL_NO_REUSE_VALUE'} else 'FINAL' if reason else None},
            'suppression_for_execution': suppressed, 'outbound_authorized': False}


def saved_company_seeds(apollo, crm, *, now, crm_at):
    """Already-paid native business data only; no name-based company merging."""
    seeds = []
    for source, rows in [('apollo', apollo.get('accounts', [])), ('zoho_crm', crm.get('Accounts', []))]:
        for a in rows:
            if not live(a): continue
            name = a.get('name') or a.get('Account_Name'); host = domain(a.get('primary_domain') or a.get('domain') or a.get('website_url') or a.get('Website'))
            family = icp(' '.join(str(a.get(k) or '') for k in ('name', 'Account_Name', 'industry', 'Industry', 'description', 'Description')))
            customer = source == 'zoho_crm' and (str(a.get('Account_Type', '')).casefold() == 'customer' or any(
                str((s.get('Account_Name') or {}).get('id')) == str(a.get('id')) for s in crm.get('Services', []) if isinstance(s.get('Account_Name'), dict)))
            if not name or not a.get('id') or not (family or customer): continue
            city = a.get('organization_city') or a.get('city') or a.get('Billing_City')
            region = a.get('organization_state') or a.get('state') or a.get('Billing_State')
            country = a.get('organization_country') or a.get('country') or a.get('Billing_Country')
            from .trigger_sources import location_geography
            geo = location_geography(city, region, country)
            url = 'https://app.apollo.io/#/accounts/'+str(a['id']) if source == 'apollo' else 'https://crm.zoho.com/crm/tab/Accounts/'+str(a['id'])
            seeds.append({'company_name': name, 'domain': host, 'geography_class': geo,
                'source_provider': source, 'source_record_id': str(a['id']), 'source_url': url,
                'observed_at': apollo.get('at') if source == 'apollo' else crm_at,
                'identity_status': 'SUPPORTED' if source == 'apollo' else 'EXACT',
                'crm_account_id': str(a['id']) if source == 'zoho_crm' else None,
                'apollo_organization_id': a.get('organization_id') if source == 'apollo' else None,
                'icp': family or 'existing customer', 'industry': a.get('industry') or a.get('Industry'),
                'location': {'city': city, 'region': region, 'country': country},
                'why_opticable': 'Observed '+(family or 'customer relationship')+' business; service needs are GENERAL ICP FIT, not confirmed work.',
                'service_fit': {'primary': [], 'secondary': [], 'possible': ['structured cabling', 'commercial Wi-Fi', 'IP cameras / CCTV', 'maintenance'], 'basis': 'GENERAL ICP FIT', 'recurring': ['maintenance/support review']},
                'raw': {k: a.get(k) for k in ('id', 'name', 'Account_Name', 'primary_domain', 'Website', 'industry', 'Industry', 'city', 'state', 'country')}})
    return seeds


def contacts_for(prospect, apollo, crm, research, *, now):
    host = prospect.get('domain'); account_ids = set(prospect['collision']['crm_account_ids']); result = {}
    stages = {s['id']: s.get('display_name', '') for s in apollo.get('stages', [])}
    for p in apollo.get('contacts', []):
        account = p.get('account') or {}
        bound = bool(host and domain(account.get('primary_domain') or account.get('domain') or account.get('website_url')) == host)
        if not bound or not p.get('id') or not ROLE_PATTERN.search(str(p.get('title', ''))): continue
        at = stamp(p.get('updated_at')) or stamp(apollo.get('at'))
        status = 'SUPPORTED_CURRENT' if at and 0 <= (now-at).total_seconds() <= 180*86400 and not p.get('contact_job_change_event') else 'STALE'
        state = contact_state(p, apollo.get('messages', [])+apollo.get('replies', []), stages, now=now)
        result['apollo:'+str(p['id'])] = {'id': 'apollo:'+str(p['id']), 'name': p.get('name'), 'title': p.get('title'), 'confidence': status,
            'source': 'Apollo saved contact', 'source_url': 'https://app.apollo.io/#/contacts/'+str(p['id']), 'observed_at': at.isoformat() if at else None,
            'email': email(p.get('email')) or None, 'email_verification': p.get('email_status'), 'suppressed': state['suppressed'], 'contact_allowed': False}
    for p in crm.get('Contacts', []):
        account = p.get('Account_Name') or {}
        if not live(p) or str(account.get('id')) not in account_ids or not ROLE_PATTERN.search(str(p.get('Title') or p.get('Designation') or '')): continue
        result['crm:'+str(p['id'])] = {'id': 'crm:'+str(p['id']), 'name': p.get('Full_Name'), 'title': p.get('Title') or p.get('Designation'),
            'confidence': 'SUPPORTED_CURRENT' if prospect['collision']['crm_fresh_complete'] else 'STALE', 'source': 'CRM native Account link',
            'source_url': 'https://crm.zoho.com/crm/tab/Contacts/'+str(p['id']), 'email': email(p.get('Email')) or None,
            'email_verification': 'UNKNOWN', 'observed_at': prospect['collision']['crm_observed_at'], 'suppressed': p.get('Email_Opt_Out') is True, 'contact_allowed': False}
    for p in research.get(host, {}).get('candidates', []):
        candidate = dict(p); at = stamp(candidate.get('observed_at'))
        if candidate.get('confidence') in {'VERIFIED_CURRENT', 'SUPPORTED_CURRENT'} and (not at or (now-at).total_seconds() > 180*86400): candidate['confidence'] = 'STALE'
        result[candidate['id']] = candidate
    for p in prospect.get('source_contacts', []):
        candidate = dict(p); at = stamp(candidate.get('observed_at'))
        supplied = candidate.get('confidence', 'SUPPORTED_CURRENT')
        candidate['confidence'] = supplied if supplied not in {'VERIFIED_CURRENT', 'SUPPORTED_CURRENT'} else supplied if at and 0 <= (now-at).total_seconds() <= 180*86400 else 'STALE'
        candidate['contact_allowed'] = False; result[candidate['id']] = candidate
    return list(result.values())[:30]


def build_universe(store, queue, apollo, crm, *, now, crm_at, seeds=(), research=None, feedback=None):
    store.initialize_prospects(); original = store.baseline(); research = research or {}; groups = {}; audits = []
    # Prior seeds/candidates remain retained even if an upstream cache drops them.
    retained = store.records(prospects=True)
    previous = {p['prospect_id']: p for p in retained}
    rows = queue['rows']
    def add(seed, event=None):
        if seed.get('test_only') or seed.get('evidence_kind') == 'FIXTURE': return
        name = seed.get('company_name'); proof = seed.get('company_identity') or {}; host = domain(seed.get('domain'))
        identity = seed.get('identity_status') or seed.get('company_resolution_status') or 'UNRESOLVED'
        cid = seed.get('company_id'); source = seed['source_provider']; native = proof.get('native_buyer_id') or seed.get('source_record_id')
        if not name:
            pid = digest(['unresolved_project', source, native]); kind = 'UNRESOLVED PROJECT'
        else:
            kind = 'ORGANIZATION'
            if not cid and identity in {'EXACT', 'SUPPORTED'}:
                hit = store.record('COMPANY', {'name': name, 'domain': host, 'crm_account_id': seed.get('crm_account_id'),
                                  'apollo_organization_id': seed.get('apollo_organization_id')}, source=source, native_id=native,
                                  url=seed['source_url'], now=now, observed_at=seed.get('observed_at') or seed.get('last_verified_at'))
                if hit['state'].startswith('IDENTITY CONFLICT'): identity = 'UNRESOLVED'
                else: cid = hit['id']
            pid = digest(['prospect', cid]) if cid else digest(['unresolved_actor', source, native, seed.get('actor_role'), name])
        if pid not in groups:
            proof_row = {**seed, 'company_identity': {**proof, 'crm_account_id': seed.get('crm_account_id') or proof.get('crm_account_id')}}
            ci = company_identity(proof_row, crm)
            if identity in {'EXACT', 'SUPPORTED'}: ci['status'] = identity
            check = collision_state(proof_row, ci, apollo, crm, now=now, crm_at=crm_at)
            groups[pid] = {'prospect_id': pid, 'entity_kind': kind, 'company_identity_id': cid, 'canonical_name': name,
                'legal_name': seed.get('legal_name'), 'trade_name': seed.get('trade_name'), 'domain': host or None,
                'website': 'https://'+host if host else None, 'identity_status': identity, 'geography_class': geography(seed),
                'location': seed.get('location'), 'industry': seed.get('industry'), 'icp': seed.get('icp'),
                'size_band': seed.get('size_band'), 'location_count': seed.get('location_count'), 'collision': check,
                'source_provenance': [], 'trigger_ids': [], 'current_trigger_ids': [], 'historical_trigger_ids': [], 'actors': [],
                'source_contacts': [], 'historical_projects': [], 'service_categories_seen': [], 'first_seen': seed.get('first_observed_at') or now.isoformat(),
                'last_seen': seed.get('last_verified_at') or seed.get('observed_at') or now.isoformat(), 'last_enriched': None,
                'why_opticable': seed.get('why_opticable') or 'Observed project/procurement service scope; plausible future buyer, not proven demand.',
                'why_now': 'NO CURRENT TRIGGER', 'sales_actionable': False, 'quality': seed.get('opportunity_quality', 'MEDIUM'),
                'confidence': seed.get('evidence_confidence', 'TENTATIVE'), 'service_basis': seed.get('service_fit', {}).get('basis', 'UNKNOWN')}
        p = groups[pid]
        seen=stamp(seed.get('last_verified_at') or seed.get('observed_at'))
        if seen and (not stamp(p['last_seen']) or seen > stamp(p['last_seen'])): p['last_seen']=seen.isoformat()
        p['source_provenance'].append({'provider': source, 'record_id': str(native), 'url': seed['source_url'], 'observed_at': seed.get('last_verified_at') or seed.get('observed_at')})
        p['actors'].extend(seed.get('actors', [])); p['source_contacts'].extend(seed.get('source_contacts', []))
        if seed.get('historical_project'): p['historical_projects'].append(seed['historical_project'])
        fit = research_fit(seed)
        p['service_categories_seen'] = sorted(set(p['service_categories_seen']) | set(fit.get('primary', [])+fit.get('secondary', [])+fit.get('possible', [])))
        if event:
            tid = event['trigger_id']; p['trigger_ids'].append(tid)
            if event['status'] in TERMINAL: p['historical_trigger_ids'].append(tid)
            elif event['status'] in {'OPEN','ISSUED','ANNOUNCED'}: p['current_trigger_ids'].append(tid)
            if event['status'] in {'OPEN','ISSUED','ANNOUNCED'}: p['why_now'] = event['why_now']
            p['sales_actionable'] |= event['sales_review_eligible']
            if event['opportunity_quality'] == 'HIGH': p['quality'] = 'HIGH'
            if event['evidence_confidence'] == 'STRONG': p['confidence'] = 'STRONG'
    for row in rows:
        audit = event_retention(row, original.get(row['trigger_id']), now=now); audits.append(audit)
        row['retention'] = audit; row['event_priority_class'] = row['priority_class']
        if row['priority_class'] == 'IGNORE': row['priority_class'] = audit['retention_class']
        add(row, row)
        for actor in row.get('actors', []):
            if not actor.get('name') or actor.get('role') == 'BUYER' or actor.get('name') == row.get('company_name'): continue
            actor_seed = {**row, 'company_id': None, 'company_name': actor['name'], 'domain': actor.get('domain'),
                          'company_identity': {}, 'identity_status': actor.get('confidence', 'UNRESOLVED'),
                          'source_record_id': str(actor.get('source_actor_id') or row['source_record_id'])+':'+actor['role'],
                          'source_url': actor.get('source_url') or row['source_url'], 'actor_role': actor['role'], 'actors': [actor]}
            add(actor_seed, row)
    for seed in [*saved_company_seeds(apollo, crm, now=now, crm_at=crm_at), *seeds]: add(seed)
    for p in retained:
        if p['prospect_id'] not in groups: groups[p['prospect_id']] = p
    for p in groups.values():
        # Retained organizations must be rechecked against current caches, even
        # when their original source no longer supplies them this run.
        old_check=p['collision']; accounts=old_check.get('crm_account_ids',[])
        proof_row={'domain':p.get('domain'),'company_name':p.get('canonical_name'),
                   'company_identity':{'crm_account_id':accounts[0] if len(accounts)==1 else None},
                   'suppressed':old_check.get('suppressed',False)}
        identity=company_identity(proof_row,crm)
        if identity.get('reason')!='Conflicting CRM company identities': identity['status']=p['identity_status']
        p['collision']=collision_state(proof_row,identity,apollo,crm,now=now,crm_at=crm_at)
        enriched=stamp(research.get(p.get('domain'),{}).get('observed_at'))
        if enriched: p['last_enriched']=enriched.isoformat()
        p['trigger_ids'] = sorted(set(p['trigger_ids'])); p['current_trigger_ids'] = sorted(set(p['current_trigger_ids'])); p['historical_trigger_ids'] = sorted(set(p['historical_trigger_ids']))
        # An event that closed cannot remain in an organization's current set.
        closed = {r['trigger_id'] for r in rows if r['status'] in TERMINAL}
        p['current_trigger_ids'] = [i for i in p['current_trigger_ids'] if i not in closed]
        p['historical_trigger_ids'] = sorted(set(p['historical_trigger_ids']) | (set(p['trigger_ids']) & closed))
        p['trigger_count'] = len(p['trigger_ids']); p['current_trigger_count'] = len(p['current_trigger_ids']); p['historical_trigger_count'] = len(p['historical_trigger_ids'])
        p['repeat_buyer_count'] = p['trigger_count']; p['repeat_buyer'] = p['trigger_count'] >= 2
        p['contacts'] = contacts_for(p, apollo, crm, research, now=now)
        valid = [c for c in p['contacts'] if c['confidence'] in {'VERIFIED_CURRENT', 'SUPPORTED_CURRENT'} and not c.get('suppressed')]
        p['contact_coverage'] = {'valid_roles': len(valid), 'candidates': len(p['contacts']), 'primary_role': valid[0].get('title') if valid else None,
                                'secondary_roles': [c.get('title') for c in valid[1:]], 'role_strategy': ['Operations / Facilities', 'IT / Security', 'Procurement / Construction']}
        check = p['collision']; reason = []
        if p['identity_status'] not in {'EXACT', 'SUPPORTED'}: reason.append('NO_COMPANY')
        if not p.get('domain'): reason.append('NO_DOMAIN')
        if p['geography_class']=='UNKNOWN': reason.append('UNKNOWN_GEOGRAPHY')
        if not valid: reason.append('NO_CONTACT')
        if any(c['confidence'] == 'STALE' for c in p['contacts']): reason.append('STALE_CONTACT')
        if check['classification'] == 'UNKNOWN' or not check['crm_fresh_complete'] or not check['apollo_fresh_complete']: reason.append('UNKNOWN_COLLISION')
        if not p['current_trigger_count']: reason.append('NO_CURRENT_TRIGGER')
        if not p['service_categories_seen']: reason.append('WEAK_SERVICE_FIT')
        if p['historical_trigger_count']: reason.append('EXPIRED_EVENT')
        suppressed = check['suppressed'] or any(c.get('suppressed') and c['confidence'] in {'VERIFIED_CURRENT', 'SUPPORTED_CURRENT'} for c in p['contacts'])
        if suppressed: reason.append('SUPPRESSED')
        foreign = p['geography_class'] in {'FOREIGN', 'OTHER CANADA'}
        terminal = foreign or any(a['trigger_id'] in p['trigger_ids'] and a['ignore']['reason'] in FINAL_REASONS for a in audits) and not p['service_categories_seen']
        pool = ('SUPPRESSED' if suppressed else 'TERMINAL IGNORE' if terminal else
                'ACTIVE APOLLO' if check['apollo_active'] or check['recent_apollo_send'] else
                'ACTIVE DEAL' if check['open_deal_ids'] else 'EXISTING CUSTOMER' if check['existing_customer'] else
                'SALES ACTIONABLE' if p['sales_actionable'] else
                'NEEDS COMPANY RESOLUTION' if 'NO_COMPANY' in reason or 'NO_DOMAIN' in reason else
                'NEEDS CONTACT' if not valid else
                'HISTORICAL INTELLIGENCE' if (p['historical_trigger_count'] or p.get('historical_projects')) and not p['current_trigger_count'] else
                'PROSPECTING READY' if check['crm_fresh_complete'] and check['apollo_fresh_complete'] and check['classification'] != 'UNKNOWN' and p['geography_class'] != 'UNKNOWN' else 'RESEARCH')
        p['pools'] = sorted(set([pool]+(['HISTORICAL INTELLIGENCE'] if (p['historical_trigger_count'] or p.get('historical_projects')) and not terminal else [])+
            (['WATCH'] if not p['current_trigger_count'] and not terminal else [])+(['NEEDS CONTACT'] if not valid and not terminal else [])))
        p['prospecting_status'] = pool; p['why_not_ready'] = reason
        p['CRM_state'] = 'OPEN DEAL' if check['open_deal_ids'] else 'EXISTING CUSTOMER' if check['existing_customer'] else 'CRM ACCOUNT' if check['crm_account_ids'] else 'CRM CONTACT/LEAD' if check['crm_people'] else 'NEW' if check['classification'] == 'NEW COMPANY' else 'UNKNOWN'
        p['Apollo_state'] = 'ACTIVE SEQUENCE / RECENT CONTACT' if check['apollo_active'] or check['recent_apollo_send'] else 'IN APOLLO' if check['apollo_matches'] or check['apollo_account_matches'] else 'NOT IN APOLLO' if check['apollo_fresh_complete'] and check['identity_matchable'] else 'UNKNOWN'
        p['suppression_state'] = 'SUPPRESSED' if suppressed else 'NO KNOWN SUPPRESSION; HUMAN CONSENT CHECK STILL REQUIRED' if check['crm_fresh_complete'] and check['apollo_fresh_complete'] and check['classification'] != 'UNKNOWN' else 'UNKNOWN'
        p['research_components'] = {'service_fit': bool(p['service_categories_seen']), 'current_trigger': bool(p['current_trigger_count']),
            'repeat_buyer': p['repeat_buyer'], 'existing_relationship': check['existing_customer'] or bool(check['open_deal_ids']),
            'missing_domain': not bool(p.get('domain')), 'missing_contact': not bool(valid)}
        p['research_priority'] = 'HIGH' if p['quality'] == 'HIGH' or p['repeat_buyer'] or check['existing_customer'] else 'MEDIUM'
        interval = 7 if p['current_trigger_count'] or p['research_priority'] == 'HIGH' else 30
        prior_due = stamp(previous.get(p['prospect_id'], {}).get('next_research_at'))
        p['next_research_at'] = prior_due.isoformat() if prior_due else (now+timedelta(days=interval)).isoformat()
        p['revisit_reasons'] = [('MISSING_DOMAIN' if x == 'NO_DOMAIN' else 'MISSING_CONTACT' if x == 'NO_CONTACT' else 'UNKNOWN_COLLISION' if x == 'UNKNOWN_COLLISION' else 'NO_CURRENT_TRIGGER') for x in reason if x in {'NO_DOMAIN', 'NO_CONTACT', 'UNKNOWN_COLLISION', 'NO_CURRENT_TRIGGER'}]
        if p['repeat_buyer']: p['revisit_reasons'].append('HISTORICAL_REPEAT_BUYER')
        p['future_outreach_state'] = 'SUPPRESSED' if suppressed else 'RESEARCHING' if 'NO_COMPANY' in reason or 'NO_DOMAIN' in reason or 'UNKNOWN_GEOGRAPHY' in reason else 'CONTACT_REQUIRED' if not valid else 'COLLISION_REVIEW' if check['classification'] in {'UNKNOWN', 'ACTIVE OUTREACH', 'OPEN DEAL', 'EXISTING CUSTOMER OPPORTUNITY'} else 'OWNER_REVIEW'
        p['execution_readiness'] = check['execution_readiness']; p['outbound_authorized'] = False; p['crm_promote_allowed'] = False
        p['ignore_audit'] = {'reason': 'WRONG_COUNTRY' if foreign else 'NOT_SERVICE_FIT' if terminal else None,
                             'at': now.isoformat() if terminal else None, 'source': p['source_provenance'][0]['url'], 'reconsideration': 'FINAL' if foreign else 'REVISITABLE' if terminal else None}
    records = sorted(groups.values(), key=lambda p: (p['prospecting_status'] in {'TERMINAL IGNORE', 'SUPPRESSED'}, p['research_priority'] != 'HIGH', -p['current_trigger_count'], -p['repeat_buyer_count'], p['prospect_id']))
    held = store.persist(records, audits, now=now)
    organizations = [p for p in records if p['entity_kind'] == 'ORGANIZATION']; relevant = [p for p in organizations if p['prospecting_status'] != 'TERMINAL IGNORE']
    counts = Counter(p['prospecting_status'] for p in records); losses = Counter(x for p in relevant for x in p['why_not_ready'])
    baseline_audits = [a for a in audits if a['original_phase30']]
    baseline_ignored = [a for a in baseline_audits if a['original_phase30']['priority_class'] == 'IGNORE']
    funnel = {'raw_signals': len(rows), 'organizations': len(organizations), 'relevant_organizations': len(relevant),
              'resolved': sum(p['identity_status'] in {'EXACT', 'SUPPORTED'} for p in relevant),
              'with_contacts': sum(p['contact_coverage']['valid_roles'] > 0 for p in relevant),
              'prospecting_ready': counts['PROSPECTING READY'], 'sales_actionable': counts['SALES ACTIONABLE'],
              'suppressed': counts['SUPPRESSED'], 'existing_relationship': counts['EXISTING CUSTOMER']+counts['ACTIVE DEAL']}
    return {'schema': 1, 'mode': 'SHADOW', 'at': now.isoformat(), 'records': records, 'trigger_audits': audits,
            'funnel': funnel, 'pool_counts': dict(counts), 'why_not_ready': dict(losses),
            'identity_counts': dict(Counter(p['identity_status'] for p in organizations)),
            'contact_counts': dict(Counter(c['confidence'] for p in organizations for c in p['contacts'])),
            'current_trigger_prospects': sum(bool(p['current_trigger_count']) for p in relevant),
            'icp_only_prospects': sum(not p['trigger_count'] for p in relevant),
            'no_current_trigger_prospects': sum(not p['current_trigger_count'] for p in relevant),
            'historical_organizations': sum(bool(p['historical_trigger_count'] or p.get('historical_projects')) for p in relevant),
            'repeat_buyers': sum(p['repeat_buyer'] for p in relevant),
            'unresolved_projects': sum(p['entity_kind'] == 'UNRESOLVED PROJECT' for p in records),
            'baseline_review': {'original_triggers': len(baseline_audits), 'original_ignore': len(baseline_ignored),
                 'original_ignore_reusable': sum(a['historical_reuse_value'] or a['company_resolution_value'] or a['watch_value'] for a in baseline_ignored),
                 'retention_counts': dict(Counter(a['retention_class'] for a in baseline_audits))},
            'research_queue': [{'prospect_id': p['prospect_id'], 'company': p['canonical_name'], 'priority': p['research_priority'],
                               'reasons': p['revisit_reasons'], 'next_research_at': p['next_research_at']} for p in records if p['prospecting_status'] not in {'SUPPRESSED', 'TERMINAL IGNORE'}][:100],
            'research_backlog':sum(p['prospecting_status'] not in {'SUPPRESSED', 'TERMINAL IGNORE'} for p in records),
            'revisit_backlog':sum(bool(stamp(p['next_research_at']) and stamp(p['next_research_at']) <= now) for p in records),
            'coverage_health': {'company_resolution':{'numerator':funnel['resolved'],'denominator':len(relevant)},
                'contact_coverage':{'numerator':funnel['with_contacts'],'denominator':len(relevant)},
                'unknown_collision':{'numerator':losses['UNKNOWN_COLLISION'],'denominator':len(relevant)},
                'stale_contact':{'numerator':losses['STALE_CONTACT'],'denominator':len(relevant)}},
            'storage_held': held, 'provider_writes': 0, 'outbound_sends': 0, 'crm_promotions': 0}


def owner_projection(view):
    public = {k: v for k, v in view.items() if k not in {'records', 'trigger_audits', 'research_queue'}}
    public['research_backlog'] = view.get('research_backlog', len(view['research_queue'])); public['research_queue_limit'] = 100
    keys = ('prospect_id', 'canonical_name', 'entity_kind', 'identity_status', 'domain', 'geography_class', 'prospecting_status',
            'pools', 'service_categories_seen', 'why_opticable', 'why_now', 'quality', 'confidence', 'contact_coverage',
            'CRM_state', 'Apollo_state', 'suppression_state', 'why_not_ready', 'repeat_buyer_count', 'current_trigger_count',
            'historical_trigger_count', 'next_research_at', 'research_priority', 'future_outreach_state', 'outbound_authorized')
    public['rows'] = [{k: p.get(k) for k in keys} | {'source_url': p['source_provenance'][0]['url']} for p in view['records'][:8]]
    for row, p in zip(public['rows'], view['records']):
        row.update({k: p.get(k) for k in ('domain_confidence', 'enrichment_readiness', 'enrichment_queue')})
    return public


def render(view):
    h = lambda x: escape(str(x if x is not None else 'UNKNOWN'), quote=True)
    html = '<section><h2>Prospect universe — retained research</h2><p>Discovery does not authorize outreach. Current event and organization value are separate.</p>'
    html += '<p>'+h(' · '.join(k+': '+str(v) for k, v in view.get('funnel', {}).items()))+'</p>'
    html += '<p>Coverage gaps: '+h(' · '.join(k+': '+str(v) for k, v in view.get('why_not_ready', {}).items()))+'</p>'
    html += '<p>Pools: '+h(' · '.join(k+': '+str(v) for k, v in view.get('pool_counts', {}).items()))+'</p>'
    html += '<p>Enrichment: '+h(' · '.join(k+': '+str(v) for k, v in view.get('enrichment_metrics', {}).items()))+'</p>'
    for p in view.get('rows', []):
        html += '<article><strong>'+h(p['prospecting_status'])+' · '+h(p['canonical_name'] or 'Unresolved project')+'</strong><p>'+h(p['geography_class'])+' · company '+h(p['identity_status'])+' · contacts '+h(p['contact_coverage']['valid_roles'])+'</p>'
        html += '<p>'+h(p['why_opticable'])+'<br>'+h(p['why_now'])+'</p><p>CRM: '+h(p['CRM_state'])+' · Apollo: '+h(p['Apollo_state'])+'<br>Needs: '+h(', '.join(p['why_not_ready']))+'</p></article>'
        if p.get('entity_kind') == 'ORGANIZATION': html += '<p><a href="/v1/operator/acquisition?prospect_id='+h(p['prospect_id'])+'">Prospect evidence and roles</a></p>'
    return html+'</section>'


def research_contacts(store, view, cache, settings, *, now):
    """Three reads/Toronto day,14-day per-domain attempts, no paid enrichment.

    Retain LIKELY candidates instead of discarding provider results with missing
    employer proof. This never changes the strict independent Sales gate.
    """
    from zoneinfo import ZoneInfo
    from .apollo_observation import ApolloReader
    local = now.astimezone(ZoneInfo('America/Toronto'))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(now.tzinfo).isoformat()
    with store.connect() as db:
        spent = db.execute('SELECT count(*) FROM acquisition_research_attempts WHERE provider=? AND observed_at>=?', ('apollo', start)).fetchone()[0]
    saved = dict(cache); reader = None; calls = 0
    # Provider-wide auth/quota failures pause all domains until the next Toronto
    # day, instead of trying a different domain every hourly observer run.
    if any(c.get('state')=='PARTIAL' and stamp(c.get('attempted_at')) and stamp(c['attempted_at']) >= stamp(start) for c in saved.values()):
        return saved,0
    try:
        for p in view['records']:
            host = p.get('domain'); pid = p['prospect_id']; prior = saved.get(host, {})
            if spent+calls >= 3: break
            if not host or p['prospecting_status'] in {'TERMINAL IGNORE', 'SUPPRESSED', 'ACTIVE APOLLO', 'ACTIVE DEAL'} or p['contact_coverage']['valid_roles']: continue
            at = stamp(prior.get('attempted_at'))
            if at and (now-at).total_seconds() < 14*86400: continue
            if not store.retry_due(pid, 'apollo', 'PEOPLE SEARCH', now=now): continue
            outcome = {'attempted_at': now.isoformat(), 'state': 'PARTIAL', 'candidates': prior.get('candidates', [])}
            try:
                if reader is None: reader = ApolloReader(settings.apollo, limit=3)
                from .prospect_enrichment import useful_role
                titles = ['Estimator','Project Manager','Construction','Operations'] if p.get('icp') in {'general contractor','electrical partner'} else ['Property Manager','Facilities','Operations','IT'] if p.get('icp') in {'property management','developer'} else ['Procurement','Facilities','IT','Security'] if p.get('icp') == 'institution' else ['Operations','Facilities','IT','Security','Maintenance']
                data = reader.read('people_research', q_organization_domains_list=[host], page=1, per_page=5, person_titles=titles)
                people = data.get('people', [])
                if not isinstance(people, list) or len(people)>5: raise ValueError('Bounded Apollo person schema')
                candidates = []
                for person in people:
                    if not person.get('id'): continue
                    current = domain((person.get('organization') or {}).get('primary_domain')) == host
                    relevant = useful_role(person.get('title'))
                    candidates.append({'id':'apollo_search:'+str(person['id']), 'name':person.get('first_name'),
                        'title':person.get('title'), 'confidence':'SUPPORTED_CURRENT' if current and relevant else 'LIKELY',
                        'current_employer_proven':current, 'role_relevant':relevant, 'source':'Apollo people API search',
                        'source_url':'https://app.apollo.io/#/people/'+str(person['id']), 'observed_at':now.isoformat(),
                        'email':None, 'email_verification':'UNKNOWN — ENRICHMENT NOT USED','suppressed':bool(person.get('email_unsubscribed') or person.get('do_not_contact')),'contact_allowed':False})
                outcome.update(state='WORKING',observed_at=now.isoformat(),candidates=candidates,sampled=len(people),credits_used=0)
            except (ValueError,AttributeError,TypeError,KeyError) as exc:
                message=str(exc); match=re.search(r'HTTP (\d{3})',message)
                outcome.update(classification='AUTHORIZATION FAILURE' if match and match[1]=='401' else 'PERMISSION / PLAN / API GAP' if match and match[1]=='403' else 'RATE LIMIT' if match and match[1]=='429' else 'API ACCESS / CREDENTIAL / SCHEMA GAP',
                    http_status=int(match[1]) if match else None, endpoint='/api/v1/mixed_people/api_search', operation='READ people search',
                    reason=message if message.startswith('Apollo read unavailable: HTTP') else 'Read failed; no immediate retry and no fabricated contact')
            calls += 1; saved[host] = outcome
            store.attempt(pid,'apollo','PEOPLE SEARCH',outcome,now=now)
            if outcome['state']=='PARTIAL': break
    finally:
        if reader: reader.close()
    return saved, reader.calls if reader else 0
