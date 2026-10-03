"""Shadow sales decisions from exact identities and dated public evidence.

This module cannot send, enroll, enrich, create CRM records or grant authority.
Unknown collision state permits research only. Discovery is not acquisition.
"""
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
import re
from urllib.parse import urlsplit

FREE_DOMAINS = {'gmail.com','hotmail.com','outlook.com','yahoo.com','live.com','icloud.com'}
FEEDBACK = {'GOOD','BAD FIT','WRONG PERSON','ALREADY CUSTOMER','NOT NOW','DO NOT CONTACT','GOOD TRIGGER','BAD TRIGGER'}


def key(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def email(value):
    value = str(value or '').strip().casefold()
    return value if re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value) else ''


def domain(value):
    try:
        parsed = urlsplit(str(value) if '://' in str(value) else 'https://' + str(value))
        host = (parsed.hostname or '').rstrip('.').casefold().removeprefix('www.').encode('idna').decode()
        return host if '.' in host and host not in FREE_DOMAINS else ''
    except (ValueError, UnicodeError):
        return ''


def live(row):
    return str(row.get('OptiBrain_Test','')).casefold() not in {'true','1'} and str(row.get('test_only','')).casefold() not in {'true','1'} and not re.search(
        r'OPTIBRAIN TEST|TEST ONLY', ' '.join(str(row.get(k, '')) for k in ('name','Name','Full_Name','Company','Account_Name','Deal_Name')), re.I)


def stamp(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d if d.tzinfo else None
    except (ValueError, TypeError):
        return None


def identity_index(apollo, crm):
    """Exact email/native IDs and unique employer domains; no name or fuzzy merge."""
    index = {'apollo_email': {}, 'apollo_domain': {}, 'apollo_account':{}, 'crm_email': {}, 'crm_domain': {}}
    for row in apollo.get('contacts', []):
        address = email(row.get('email'))
        if address:
            index['apollo_email'].setdefault(address, []).append(row)
            host = domain(address.split('@')[1])
            if host:
                index['apollo_domain'].setdefault(host, []).append(row)
        host=domain(row.get('website_url'))
        if host and row not in index['apollo_domain'].get(host,[]):index['apollo_domain'].setdefault(host,[]).append(row)
    for row in apollo.get('accounts',[]):
        host=domain(row.get('primary_domain') or row.get('domain') or row.get('website_url'))
        if host:index['apollo_account'].setdefault(host,[]).append(row)
    for module in ('Leads', 'Contacts'):
        for row in crm.get(module, []):
            if not live(row): continue
            address = email(row.get('Email'))
            if address: index['crm_email'].setdefault(address, []).append((module, row))
    for row in crm.get('Accounts', []):
        if not live(row): continue
        host = domain(row.get('Website'))
        if host: index['crm_domain'].setdefault(host, []).append(row)
    return index


def contact_state(contact, messages, stages, *, now=None):
    now = now or datetime.now(timezone.utc)
    memberships = contact.get('contact_campaign_statuses') or []
    own = [r for r in messages if str(r.get('contact_id')) == str(contact.get('id'))]
    stage = stages.get(contact.get('contact_stage_id'), '').casefold()
    reasons = []
    if contact.get('email_unsubscribed') is True or 'unsubscrib' in stage or stage in {'do not contact','not interested','bad data','changed job'}:
        reasons.append('Unsubscribed / do not contact')
    if contact.get('person_deleted') or 'bounce' in stage or any(r.get('bounce') or r.get('spam_blocked') for r in own):
        reasons.append('Bounce / invalid delivery')
    if contact.get('email_status') not in ('verified',): reasons.append('Email not verified')
    active = any(r.get('status') in ('active','scheduled','paused') for r in memberships)
    return {'owner': 'CLAUDE_APOLLO', 'active': active, 'suppressed': bool(reasons), 'reasons': reasons,
            'replied': any(r.get('replied') is True for r in own),
            'positive': any(r.get('reply_class') == 'willing_to_meet' for r in own),
            'recent_send': any(r.get('status') == 'completed' and stamp(r.get('completed_at')) and
                               0 <= (now-stamp(r['completed_at'])).total_seconds() <= 30*86400 for r in own),
            'membership_count': len(memberships)}


def collision(subject, apollo, crm, *, now=None):
    """No clear-to-contact result: unknown Mail/complaint/consent always needs review."""
    now = now or datetime.now(timezone.utc)
    index = identity_index(apollo, crm)
    address, host = email(subject.get('email')), domain(subject.get('domain'))
    if not host and address:host=domain(address.split('@')[1])
    matches = index['apollo_email'].get(address, []) if address else index['apollo_domain'].get(host, []) if host else []
    crm_people = index['crm_email'].get(address, []) if address else []
    crm_accounts = index['crm_domain'].get(host, []) if host else []
    apollo_accounts=index['apollo_account'].get(host,[]) if host else []
    stages = {r['id']:r.get('display_name', '') for r in apollo.get('stages', [])}
    states = [contact_state(r, apollo.get('messages', []) + apollo.get('replies', []), stages, now=now) for r in matches]
    observed = stamp(apollo.get('at'))
    fresh = bool(observed and 0 <= (now-observed).total_seconds() <= 3600 and apollo.get('contacts_complete') is True)
    return {'outreach_owner': 'CLAUDE_APOLLO' if matches or apollo_accounts else 'OWNER_MANUAL' if crm_people or crm_accounts else 'OPTIBRAIN_RESEARCH_ONLY',
            'apollo_matches': [r['id'] for r in matches], 'apollo_active': any(r['active'] for r in states),
            'apollo_account_matches':[r['id'] for r in apollo_accounts],
            'recent_apollo_send': any(r['recent_send'] for r in states),
            'suppressed': any(r['suppressed'] for r in states),
            'existing_customer': bool(any(m == 'Contacts' for m,_ in crm_people) or crm_accounts),
            'crm_matches': [str(r['id']) for _,r in crm_people] + [str(r['id']) for r in crm_accounts],
            'ambiguous': len(crm_people) > 1 or len(crm_accounts) > 1,
            'identity_known': bool(address or host), 'apollo_fresh_complete': fresh,
            'zoho_recent_mail': 'REQUIRES HUMAN CHECK', 'complaint_check': 'REQUIRES HUMAN CHECK',
            'contact_recommendation_allowed': False, 'cold_send_allowed': False,
            'next_action': 'Review existing Apollo account / conversation' if matches or apollo_accounts else 'Review current customer context' if crm_people or crm_accounts else 'Research identity and review collision/suppression before outreach'}


def permit_signals(records, *, now=None):
    now = now or datetime.now(timezone.utc)
    output = {}
    for row in records:
        issued = stamp(str(row.get('date_emission', '')) + 'T12:00:00-04:00')
        category = str(row.get('description_type_batiment', '')).casefold()
        text = str(row.get('nature_travaux', ''))
        if not issued or not 0 <= (now-issued).days <= 60 or category not in ('commercial','industriel'):
            continue
        if row.get('code_type_base_demande') != 'CO' and not re.search(r'réaménag|reamenag|agrand|aménagement intérieur|amenagement interieur', text, re.I):
            continue
        if re.search(r'uniquement.{0,20}(toiture|façade)|abattage|auvent|marquise', text, re.I): continue
        record = str(row.get('id_permis') or '')
        if not record: continue
        identity = key({'source':'montreal_permit','record':record})
        output[identity] = {'key':identity, 'source':'montreal_permit','record_id':record,
            'company':'Project owner not identified', 'site':str(row.get('emplacement','')),
            'trigger':text[:700], 'trigger_at':row['date_emission'], 'fit':'Potential structured cabling / network infrastructure; scope unconfirmed',
            'why_now':'Recent commercial/industrial permit issued', 'who':'Identify developer / project manager',
            'source_url':'https://donnees.montreal.ca/dataset/permis-construction',
            'discovery_source':'PUBLIC_PERMIT','marketing_first_touch':'NOT APPLICABLE — RESEARCH',
            'contact_allowed':False, 'identity_unresolved':True}
    return list(output.values())


def tender_signals(releases, *, now=None):
    now = now or datetime.now(timezone.utc)
    found = {};latest={}
    for row in releases:
        if row.get('ocid') and str(row.get('id',''))>str(latest.get(row['ocid'],{}).get('id','')):latest[row['ocid']]=row
    for row in latest.values():
        tender = row.get('tender', {});title = tender.get('title', '')
        ends = stamp(tender.get('tenderPeriod', {}).get('endDate'))
        if tender.get('status') != 'active' or not ends or ends <= now: continue
        if not re.search(r'vidéosurveillance|g[ué]é?rites.{0,30}caméras|câblage.{0,20}(informatique|communication)|fibre optique|intercommunication', title, re.I): continue
        if re.search(r'égout|laue|incendie', title, re.I): continue
        record = row.get('ocid')
        if not record: continue
        old = found.get(record)
        if old and str(old['native_version']) >= str(row.get('id', '')): continue
        source = next((d['url'] for d in tender.get('documents', []) if str(d.get('url','')).startswith('https://seao.gouv.qc.ca/')), 'https://seao.gouv.qc.ca/avis-du-jour')
        found[record] = {'key':key({'source':'seao','record':record}), 'source':'seao','record_id':record,
            'native_version':str(row.get('id','')), 'company':row.get('buyer',{}).get('name','Unknown buyer'),
            'trigger':title, 'trigger_at':row.get('date'), 'deadline':ends.isoformat(),
            'source_url':source,'fit':'CCTV' if re.search(r'caméra|vidéosurveillance',title,re.I) else 'Structured cabling',
            'why_now':'Published procurement opportunity; confirm latest amendment/requirements',
            'who':'Public procurement process / owner reviews requirements',
            'discovery_source':'PUBLIC_TENDER','marketing_first_touch':'NOT APPLICABLE — RESEARCH',
            'contact_allowed':False, 'identity_unresolved':True}
    return list(found.values())


def build_shadow(apollo, crm, signals, *, now=None):
    now = now or datetime.now(timezone.utc)
    index = identity_index(apollo,crm)
    exact = sum(bool(index['crm_email'].get(email(c.get('email')))) for c in apollo.get('contacts', []))
    stages = {r['id']:r.get('display_name','') for r in apollo.get('stages', [])}
    states = [contact_state(c,apollo.get('messages',[])+apollo.get('replies',[]),stages,now=now) for c in apollo.get('contacts',[])]
    prospects = []
    for row in signals:
        if row.get('deadline') and (not stamp(row['deadline']) or stamp(row['deadline']) <= now):continue
        checked = collision(row,apollo,crm,now=now)
        prospects.append({**row,**checked,'mode':'SHADOW','draft_send_allowed':False,'version':key(row)})
    return {'schema':1,'scope':'live','read_only':True,'at':now.isoformat(),'observed_at':apollo.get('at'),
            'state':'SHADOW','provider_writes':0,'contacts':len(states),'active_contacts':sum(s['active'] for s in states),
            'suppressed_contacts':sum(s['suppressed'] for s in states),'exact_crm_contact_overlap':exact,
            'prospects':prospects[:20], 'cold_outbound':'OFF','raw_crm_promotions':0,
            'sources':{'apollo':'READ ONLY','clay':'DEFERRED — NO CALLABLE READ CONNECTION','claude':'Private conversation history unavailable'}}


def build_sales(apollo, crm, signals, *, now=None, recurring=None, feedback=None, estimates=None):
    """One priority universe. Reviews never recommend a second outreach controller."""
    now = now or datetime.now(timezone.utc)
    view = build_shadow(apollo, crm, signals, now=now)
    feedback = feedback or {}
    rows = {}; stages = {r['id']:r.get('display_name','') for r in apollo.get('stages', [])}
    sequences = {r['id']:r.get('name','') for r in apollo.get('sequences', [])}
    lead_guards = {}
    def add(kind, identity, title, why, action, priority, owner, link, **extra):
        identity = key({'kind':kind,'record':str(identity)})
        choice = feedback.get(identity, {}).get('choice')
        if choice in {'DO NOT CONTACT','BAD FIT','NOT NOW','BAD TRIGGER'}:return
        if choice=='WRONG PERSON':action='Identify the correct role; do not contact the rejected person'
        if choice=='ALREADY CUSTOMER':owner='OWNER_MANUAL';action='Review existing customer and Service context in CRM'
        if choice=='GOOD TRIGGER':priority=max(3,priority-1)
        row = dict(key=identity,kind=kind,title=title,why=why,action=action,priority=priority,
                   outreach_owner=owner,link=link,contact_allowed=False,cold_send_allowed=False,review_choice=choice,**extra)
        row['version'] = key(row)
        rows[identity] = row
    for c in apollo.get('contacts', []):
        state = contact_state(c,apollo.get('messages',[])+apollo.get('replies',[]),stages,now=now)
        if not live(c) or not state['replied']:continue
        names = sorted({sequences.get(m.get('emailer_campaign_id'),'Observed Apollo sequence') for m in c.get('contact_campaign_statuses',[])})
        add('apollo_reply',c['id'],c.get('name') or 'Apollo reply',
            ('Provider classified willing to meet; human qualification required' if state['positive'] else 'Reply observed; meaning requires human review') +
            ('; suppression present — no sales outreach' if state['suppressed'] else ''),
            'Read the existing conversation in Apollo; coordinate there',0,'CLAUDE_APOLLO',
            'https://app.apollo.io/#/contacts/'+str(c['id']),sequences=names,active=state['active'],suppressed=state['suppressed'])
    for c in crm.get('Leads', []):
        if not live(c) or c.get('Lead_Status') in {'Not Qualified','Junk Lead','Lost','Do Not Contact','Converted'}:continue
        checked = collision({'email':c.get('Email'),'domain':c.get('Website')},apollo,crm,now=now)
        lead_guards[str(c['id'])] = {k:checked[k] for k in ('outreach_owner','apollo_active','recent_apollo_send','suppressed')}
        modified=stamp(c.get('Modified_Time'));stale=bool(modified and (now-modified).days>=30)
        add('inbound_lead',c['id'],c.get('Full_Name') or c.get('Company') or 'CRM Lead',
            ('Stale Lead — review continued relevance' if stale else 'Human qualification required') + ('; existing Apollo owner — avoid competing follow-up' if checked['apollo_matches'] else ''),
            'Review existing Apollo conversation' if checked['apollo_matches'] else 'Review and qualify in CRM; check recent communication before contacting',
            6 if stale else 1,checked['outreach_owner'],'https://crm.zoho.com/crm/org763070937/tab/Leads/'+str(c['id']))
    for d in crm.get('Deals', []):
        if not live(d) or re.search(r'closed|lost|perdu',str(d.get('Stage','')),re.I):continue
        modified = stamp(d.get('Modified_Time'))
        stale = bool(modified and (now-modified).days >= 30)
        add('deal',d['id'],d.get('Deal_Name') or 'Open Deal',
            str(d.get('Stage','Stage unknown'))+('; no update for 30 days' if stale else ''),
            'Review next action in CRM; confirm current customer and Finance context',3 if stale else 2,'OWNER_MANUAL',
            'https://crm.zoho.com/crm/org763070937/tab/Deals/'+str(d['id']))
    for e in estimates or []:
        if not live(e) or e.get('status') not in {'sent','accepted'}:continue
        add('estimate',e['id'],e.get('title') or 'Finance Estimate',
            'Accepted work requires internal preparation' if e['status']=='accepted' else 'Sent Estimate — check reply and suppression before follow-up',
            'Review the existing Deal and operational context in CRM',2 if e['status']=='accepted' else 3,
            'OWNER_MANUAL','https://crm.zoho.com/crm/org763070937/tab/Deals/'+str(e['deal_id']))
    for p in view['prospects'][:5]:
        add('trigger',p['key'],p['company'],p['why_now']+': '+p['trigger'],
            p['next_action']+'; '+p['who'],4,p['outreach_owner'],p['source_url'],
            fit=p['fit'],site=p.get('site'),source=p['source'],source_record=p['record_id'],
            apollo_matches=len(p['apollo_matches']),existing_customer=p['existing_customer'],
            source_version=p.get('native_version'),trigger_at=p.get('trigger_at'))
    for a in (recurring or {}).get('attention', []):
        if a.get('test_only'):continue
        add('customer_attention',key(a),a.get('context') or 'Customer lifecycle attention',
            a.get('why') or 'Renewal / customer context requires review',a.get('next_action') or 'Review in CRM',
            5,'OWNER_MANUAL','/v1/operator/recurring')
    view.update(rows=sorted(rows.values(),key=lambda r:(r['priority'],r['title']))[:60],lead_guards=lead_guards,
                tasks_created=0,feedback_choices=sorted(FEEDBACK),
                policy='Shadow research and coordinated human review only; no outreach clearance')
    return view


def render_sales(view):
    h=lambda v:escape(str(v if v is not None else 'Unknown'),quote=True)
    parts=["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>OptiBrain · Today Sales</title>",
           "<style>body{font:16px/1.5 system-ui;max-width:1050px;margin:2rem auto;padding:0 1rem}article{border:1px solid #ccd6df;border-radius:8px;padding:1rem;margin:1rem 0}a{color:#075aa7}small{color:#536173}</style></head><body>",
           "<h1>Today — Sales</h1><p><a href='/v1/operator/today'>Today</a> · <a href='/v1/operator/business'>Business Overview</a></p>",
           "<p>Replies, inbound Leads, open Deals and additive project research. Outreach already handled in Apollo stays there.</p>",
           f"<p>{h(view['contacts'])} Apollo contacts · {h(view['active_contacts'])} with active/paused membership · {h(view['exact_crm_contact_overlap'])} exact CRM email matches.</p>",
           f"<p><small>Apollo observed {h(view.get('observed_at'))}. Latest activity is a bounded sample. Missing activity is not proof of no contact.</small></p>"]
    for r in view.get('rows', []):
        link=r['link'] if str(r['link']).startswith(('https://app.apollo.io/','https://crm.zoho.com/','https://seao.gouv.qc.ca/','https://donnees.montreal.ca/','/v1/operator/')) else '/v1/operator/sales'
        parts.append(f"<article><h2>{h(r['title'])}</h2><p>{h(r['why'])}</p><p><b>Outreach handled by:</b> {h(r['outreach_owner'])}</p><p><b>Next:</b> {h(r['action'])}</p>"+
                     (f"<p>Likely service: {h(r['fit'])} · {h(r.get('site'))}</p>" if 'fit' in r else '')+
                     f"<p><a href='{h(link)}'>Review source</a> · <a href='/v1/operator/sales/review/{r['key']}'>Record review feedback</a></p></article>")
    parts.append("<p>OptiBrain cold outbound is OFF. Consent, recent Zoho Mail and open complaints require human review before any contact. Discovery source is separate from marketing acquisition.</p></body></html>")
    return ''.join(parts)


def clay_decision(apollo_email_present, missing):
    if apollo_email_present and not missing:return 'NOT NEEDED — reuse Apollo'
    return 'DEFERRED — supplemental gaps only; verify callable Clay read access and bounded credits first'
