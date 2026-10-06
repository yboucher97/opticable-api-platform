"""Hourly isolated shadow observer using existing timer, caches and journal DB."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import grp
import hashlib
import json
import os
import re
import sqlite3
import httpx
from zoneinfo import ZoneInfo

from . import lifecycle_control as lc
from .sales_intelligence import stamp
from .sales_feedback import SalesFeedback
from .trigger_intelligence import assess, sales_rows
from .trigger_store import TriggerStore
from .trigger_sources import PublicReader, SEAO_CATALOG, CKAN, LAVAL_RESOURCE, TRICOR, permits, seao, expansion

ROOT = Path('/var/lib/optibrain/acquisition-intelligence')
SALES = Path('/var/lib/optibrain/sales-intelligence')
DISPLAY = Path('/run/optibrain-readiness/trigger-intelligence.json')
SALES_DISPLAY = Path('/run/optibrain-readiness/sales-intelligence.json')
DATABASE = Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')


def research_roles(queue, saved, settings, *, now):
    """At most three zero-credit search reads; no email/phone enrichment.

    A domain filter may match past employers. Only explicit current organization
    domain plus a relevant role is supported; other returned people stay unresolved.
    """
    from .apollo_observation import ApolloReader
    from .sales_intelligence import domain
    from .trigger_intelligence import ROLE_PATTERN
    caches=dict(saved);reader=None;calls=0
    try:
        for row in queue['rows']:
            host=domain(row.get('domain'))
            if not host or row['priority_class'] not in {'ACT NOW','REVIEW'} or row['collision']['suppressed'] or row['collision']['role_candidates']:continue
            old=caches.get(host,{})
            if due(old,now,14*86400) and calls<3:
                current={**old,'attempted_at':now.isoformat()}
                try:
                    if reader is None:reader=ApolloReader(settings.apollo,limit=3)
                    data=reader.read('people_research',q_organization_domains_list=[host],page=1,per_page=5,
                                     person_titles=['Facilities','Operations','IT','Network','Security','Procurement','Maintenance'])
                    people=data.get('people',[])
                    if not isinstance(people,list) or len(people)>5:raise ValueError('Malformed bounded Apollo research')
                    candidates=[{'id':str(p['id']),'title':p.get('title'),'role_relevance':'SUPPORTED',
                                 'source':'Apollo zero-credit people API search; current employer proved','contact_allowed':False,
                                 'email':'UNKNOWN — ENRICHMENT NOT USED'} for p in people if p.get('id') and
                                domain((p.get('organization') or {}).get('primary_domain'))==host and ROLE_PATTERN.search(str(p.get('title','')))]
                    current.update(state='WORKING',observed_at=now.isoformat(),sampled=len(people),role_candidates=candidates,
                                   unresolved_people=len(people)-len(candidates),provider_writes=0,credits_used=0)
                except (ValueError,AttributeError,TypeError,KeyError) as exc:
                    message=str(exc)
                    current.update(state='PARTIAL',failure=message if message.startswith('Apollo read unavailable: HTTP') else 'Bounded Apollo research unavailable',
                                   classification='PROVIDER HTTP ACCESS/QUOTA GAP' if 'HTTP' in message else 'CREDENTIAL / SCHEMA GAP',provider_writes=0)
                calls=reader.calls if reader else calls+1;caches[host]=current;old=current
            at=stamp(old.get('observed_at'))
            if at and 0<=(now-at).total_seconds()<=14*86400:
                row['collision']['role_candidates'].extend(old.get('role_candidates',[]))
                if old.get('role_candidates'):row['missing_data']=[m for m in row['missing_data'] if not m.startswith('Relevant decision-maker')]
            row['decision_maker_research']={k:old.get(k) for k in ('state','observed_at','sampled','unresolved_people','failure','classification')}
    finally:
        if reader:reader.close()
    return caches,calls


def cache_read(path, size=2097152):
    try: return lc.trusted_json(path, size) if path.exists() else {}
    except (ValueError, OSError, KeyError, TypeError): return {}


def due(cache, now, interval):
    at = stamp(cache.get('attempted_at'))
    return not at or (now-at).total_seconds() >= interval


def collect(reader, saved, *, now, permits_cache):
    """No retries. Keep previous proof and its timestamps on a source failure."""
    caches = dict(saved); observations = []; health = []
    checked = permits_cache.get('at')
    observations.extend(permits(permits_cache.get('records', []), provider='montreal_permit', now=now, verified_at=checked))
    health.append({'source': 'montreal_permit', 'coverage': 'SUPPORTED — BOUNDED LATEST100', 'state': 'WORKING' if stamp(checked) else 'UNKNOWN',
                   'observed_at': checked, 'reason': 'Existing official cache reused; applicant/owner fields absent, actors require research', 'requests': 0})
    for source, interval in [('seao', 86400), ('laval_permit', 7*86400), ('company_announcement', 7*86400)]:
        prior = caches.get(source, {}); current = dict(prior); calls = reader.calls
        if due(prior, now, interval):
            current['attempted_at'] = now.isoformat()
            try:
                if source == 'seao':
                    body, _ = reader.get(SEAO_CATALOG)
                    catalog = json.loads(body)['result']
                    resources = [r for r in catalog['resources'] if str(r.get('format')).upper() == 'JSON' and re.fullmatch(r'(hebdo|mensuel)_\d{8}_\d{8}\.json', r.get('name', ''))]
                    latest = max(resources, key=lambda r: (r['name'].split('_')[2][:8], r.get('last_modified') or ''))
                    signature = [latest['url'], latest.get('last_modified')]
                    if prior.get('resource_signature') == signature and prior.get('records') is not None:
                        # Metadata recheck does not advance the upstream coverage date.
                        rows = prior['records']
                    else:
                        raw, headers = reader.get(latest['url'], max_bytes=80*1024*1024)
                        data = json.loads(raw)
                        if len(data.get('releases', [])) > 50000: raise ValueError('SEAO release count bound exceeded')
                        coverage_end = datetime.strptime(latest['name'].split('_')[2][:8], '%Y%m%d').replace(hour=23, minute=59, tzinfo=ZoneInfo('America/Toronto')).isoformat()
                        rows = seao(data['releases'], now=now, verified_at=now.isoformat(), published_at=coverage_end, source_url=latest['url'])
                        # Highest provider version is chosen before scope filtering. Final
                        # current/buyer recommendations never use an earlier open addendum.
                        rows = sorted(rows, key=lambda r: r['source_version_at'], reverse=True)[:120]
                        current.update(resource_signature=signature, source_url=latest['url'], published_at=data.get('publishedDate'),
                                       source_effective_at=coverage_end, raw_sha256=hashlib.sha256(raw).hexdigest(), etag=headers.get('etag'),
                                       source_records=len(data['releases']), selected_records=len(rows))
                    current.update(records=[{**r, 'last_verified_at': now.isoformat()} for r in rows], observed_at=now.isoformat(), state='WORKING',
                                   coverage='PARTIAL — OFFICIAL BATCH EXPORT', reason='Latest available official monthly/weekly release; upstream coverage date retained, not real-time status')
                elif source == 'laval_permit':
                    body, _ = reader.get(CKAN+'datastore_search', params={'resource_id': LAVAL_RESOURCE, 'limit': 100, 'sort': 'DATE_EMISSION desc'})
                    data = json.loads(body)
                    if data.get('success') is not True: raise ValueError('Laval datastore unavailable')
                    raw = data['result']['records']
                    # Date of newest provider record is a coverage observation, not today's
                    # construction volume. Missing rows do not mean no local projects.
                    latest = max((r.get('DATE_EMISSION') or '' for r in raw), default='')
                    from .trigger_sources import local_date
                    published = local_date(latest)
                    rows = permits(raw, provider=source, now=now, verified_at=now.isoformat(), published_at=published,retain_history=True)
                    current.update(records=rows, observed_at=now.isoformat(), source_effective_at=published,
                                   state='PARTIAL', coverage='PARTIAL — STALE PUBLICATION / LATEST100', source_records=len(raw),
                                   reason='Native contractor names are not resolved actors; freshness uses latest published permit date')
                else:
                    raw, _ = reader.get(TRICOR, max_bytes=1048576)
                    current.update(records=[expansion(raw, now=now)], observed_at=now.isoformat(), state='WORKING',
                                   coverage='PARTIAL — ONE VERIFIED PRIMARY COMPANY ANNOUNCEMENT', reason='Visible dated primary-source warehouse announcement; page metadata mismatch explicitly retained')
            except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                response=getattr(exc,'response',None);status=response.status_code if response is not None else None
                current.update(state='RATE LIMITED' if status==429 else 'PARTIAL' if prior.get('records') else 'BLOCKED',
                               http_status=status, failure_classification='RATE LIMIT' if status==429 else 'PUBLIC ACCESS RESTRICTION' if status in {401,403} else 'PROVIDER HTTP FAILURE' if status else 'SCHEMA / BYTE / TIME BOUND',
                               reason='Bounded public GET/schema/version validation failed; no retry; prior proof retained')
        current.setdefault('state', 'UNKNOWN')
        caches[source] = current; observations.extend(current.get('records', []))
        health.append({k: current.get(k) for k in ('coverage', 'state', 'observed_at', 'source_effective_at', 'reason', 'attempted_at', 'source_records', 'selected_records','http_status','failure_classification')} | {'source': source, 'requests': reader.calls-calls})
    return observations, caches, health


def build_queue(store, rows, apollo, crm, *, now, crm_at, feedback, source_health):
    store.initialize(); store.prune_triggers(now)
    updates = Counter()
    for row in rows:
        proof = row.get('company_identity') or {}
        from .trigger_sources import BUYER_PROOFS
        binding=BUYER_PROOFS.get(proof.get('native_buyer_id')) if row.get('source_provider')=='seao' else None
        if binding and not row.get('domain') and (row.get('raw') or {}).get('buyer',{}).get('id')==proof.get('native_buyer_id'):
            row={**row,'domain':binding[0],'company_identity':{**proof,'source_url':binding[1]}}
            proof=row['company_identity']
        if row.get('test_only') is True or row.get('evidence_kind') == 'FIXTURE':
            updates['TEST EXCLUDED'] += 1; continue
        if proof.get('confidence') in {'EXACT', 'SUPPORTED'} and (row.get('domain') or proof.get('native_buyer_id')):
            company = store.record('COMPANY', {'name': row.get('company_name'), 'domain': row.get('domain'), 'registry_number': proof.get('registry_number'),
                                   'crm_account_id': proof.get('crm_account_id')}, source=row['source_provider'], native_id=proof.get('native_buyer_id') or row.get('domain'),
                                   url=proof.get('source_url') or row['source_url'], now=now, observed_at=row['last_verified_at'])
            if company['state'].startswith('IDENTITY CONFLICT'):
                row = {**row, 'company_identity': {'confidence': 'UNRESOLVED'}}
            else: row = {**row, 'company_id': company.get('id')}
        # Additive company proof is preserved in one trigger version, never in CRM.
        result = store.upsert(row, now=now); updates[result['state']] += 1
        if result['state'] in {'NEW','UPDATED','REPLAY'}:
            normalized = {k: v for k, v in row.items() if k not in {'raw', 'last_verified_at', 'retrieved_at', 'first_observed_at'}}
            store.record('TRIGGER', normalized, source=row['source_provider'], native_id=row['source_record_id'],
                         url=row['source_url'], now=now, observed_at=row['last_verified_at'],
                         effective_date=row.get('publish_date'), raw=row.get('raw') or normalized)
    stored = store.records()
    assessed = [assess(r, apollo, crm, now=now, crm_at=crm_at, feedback=feedback) for r in stored]
    order = {'ACT NOW': 0, 'REVIEW': 1, 'RESEARCH': 2, 'WATCH': 3, 'IGNORE': 4}
    assessed.sort(key=lambda r: (order[r['priority_class']], -sum(r['quality_components'].values()), r.get('closing_date') or '9999', r['trigger_id']))
    for row in assessed:
        store.record('OPPORTUNITY', {k: row[k] for k in ('trigger_id', 'company_id', 'priority_class', 'evidence_confidence', 'geography_class', 'service_fit', 'why_now', 'mode', 'version')},
                     source='trigger_shadow', native_id=row['trigger_id'], url=row['source_url'], now=now,
                     observed_at=row['last_verified_at'], confidence=row['evidence_confidence'])
    counts = dict(Counter(r['priority_class'] for r in assessed))
    return {'schema': 1, 'state': 'SHADOW', 'scope':'live', 'read_only':True, 'at': now.isoformat(), 'rows': assessed,
            'counts': counts, 'identity_counts': dict(Counter(r['company_resolution_status'] for r in assessed)),
            'collision_counts': dict(Counter(r['collision']['classification'] for r in assessed)),
            'updates': dict(updates), 'trigger_count': len(assessed), 'version_count': store.version_count(), 'source_health': source_health,
            'storage_state': 'CAPACITY HELD — OWNER REVIEW REQUIRED' if updates['CAPACITY HELD'] else 'WORKING',
            'foreign_excluded': sum(r['geography_class'] == 'FOREIGN' for r in assessed),
            'expired_excluded': sum(r['status'] in {'CLOSED', 'EXPIRED', 'CANCELLED', 'AWARDED'} for r in assessed),
            'provider_writes': 0, 'crm_promotions': 0, 'outbound_sends': 0, 'cold_send_allowed': False,
            'promotion_states': ['RESEARCH', 'READY FOR OWNER REVIEW', 'APPROVED FOR CRM — FUTURE OWNER AUTHORITY', 'PROMOTED — NOT ENABLED'],
            'uncovered_geographies': {'RIVE-NORD': 'UNKNOWN — NO VERIFIED FEED', 'QUÉBEC CITY': 'SUPPORTED — BOUNDED OFFICIAL150 PERMITS', 'OTHER QUÉBEC': 'PARTIAL — SEAO ONLY'},
            'keyword_economics_dependency': 'OPTIONAL; use trusted cache separately, missing economics UNKNOWN', 'natural_business_effects': 0}


def projection(queue):
    rows = []
    for row in [r for r in queue['rows'] if r['geography_class'] not in {'FOREIGN', 'OTHER CANADA'}][:12]:
        r = {k: v for k, v in row.items() if k not in {'raw', 'company_identity_result', 'corroboration', 'retention'}}
        r['actors'] = [{k: v for k, v in a.items() if k not in {'note'}} for a in row['actors']][:5]
        rows.append(r)
    return {**{k: v for k, v in queue.items() if k != 'rows'}, 'rows': rows, 'display_limit': 12}


def observe(engine, settings, *, now=None):
    from .real_internal import atomic
    now = now or datetime.now(timezone.utc)
    if (ROOT/'TRIGGERS_STOP').exists(): return {'state': 'DISABLED', 'provider_writes': 0}
    if engine.dry_run: return {'state': 'DRY_RUN — NO TRIGGER PROVIDER CALLS OR WRITES', 'provider_writes': 0}
    apollo = cache_read(SALES/'apollo.json', 16777216)
    identities = cache_read(SALES/'crm.json'); business = cache_read(Path('/var/lib/optibrain/lifecycle/business-observation.json'), 16777216)
    from .observation_completeness import crm_context
    crm = crm_context(business, identities)
    cache = ROOT/'trigger-sources.json'; saved = cache_read(cache, 16777216)
    reader = PublicReader()
    try: rows, caches, health = collect(reader, saved, now=now, permits_cache=cache_read(SALES/'permits.json'))
    finally: reader.close()
    atomic(cache, caches)
    from .prospect_universe import ProspectStore, build_universe, research_contacts, owner_projection
    from .coverage_sources import collect as collect_coverage
    store = ProspectStore(DATABASE)
    store.initialize_prospects()
    if not store.baseline(): store.capture_baseline(cache_read(ROOT/'triggers-view.json',16777216),now=now)
    coverage_rows,seeds,coverage_cache,coverage_health=collect_coverage(cache_read(ROOT/'coverage-sources.json',16777216),now=now)
    atomic(ROOT/'coverage-sources.json',coverage_cache)
    rows.extend(coverage_rows);health.extend(coverage_health)
    feedback = SalesFeedback(DATABASE).latest()
    queue = build_queue(store, rows, apollo, crm, now=now, crm_at=identities.get('at'), feedback=feedback, source_health=health)
    queue['provider_calls'] = reader.calls+sum(h['requests'] for h in coverage_health)
    role_cache=cache_read(ROOT/'trigger-role-research.json')
    from .prospect_enrichment import resolve_document, actor_seeds, apply as enrich, details
    proofs,enrichment_state = resolve_document(store,cache_read(ROOT/'enrichment-proofs.json',1048576),now=now)
    seeds.extend(actor_seeds(proofs,queue,now=now))
    universe=build_universe(store,queue,apollo,crm,now=now,crm_at=identities.get('at'),seeds=seeds,research=role_cache,feedback=feedback)
    role_cache,role_calls=research_contacts(store,universe,role_cache,settings,now=now)
    # Re-assess from raw stored events; do not feed changed retention labels to
    # Phase30 Sales policy or accidentally elevate a historical event.
    if role_calls:
        queue['rows']=[assess(r,apollo,crm,now=now,crm_at=identities.get('at'),feedback=feedback) for r in store.records()]
        universe=build_universe(store,queue,apollo,crm,now=now,crm_at=identities.get('at'),seeds=seeds,research=role_cache,feedback=feedback)
    atomic(ROOT/'trigger-role-research.json',role_cache)
    if proofs:
        universe['_events'] = queue['rows']
        universe = enrich(store,universe,proofs,apollo,crm,now=now,crm_at=identities.get('at'))
    health.append({'source':'prospect_enrichment','state':'PARTIAL' if enrichment_state.startswith('PARTIAL') else 'WORKING',
                   'observed_at':proofs.get('at'),'coverage':'PARTIAL — REVIEWED NATIVE PROOFS / BOUNDED RESEARCH',
                   'requests':0,'reason':enrichment_state+'; contact age and collision freshness are checked independently'})
    detail = details(universe)
    if len(json.dumps(detail,ensure_ascii=False,indent=2).encode())>262144:raise ValueError('Prospect detail byte bound')
    detail_path=Path('/run/optibrain-readiness/prospect-details.json')
    atomic(detail_path,detail,0o600);os.chown(detail_path,0,grp.getgrnam('opticable-workflow-api').gr_gid);os.chmod(detail_path,0o640)
    queue['prospect_universe']=owner_projection(universe)
    atomic(ROOT/'prospects-view.json',queue['prospect_universe'])
    order={'ACT NOW':0,'REVIEW':1,'RESEARCH':2,'WATCH':3,'IGNORE':4}
    queue['rows'].sort(key=lambda r:(order.get(r.get('event_priority_class',r['priority_class']),4),
        -sum(r['quality_components'].values()),r.get('closing_date') or '9999',r['trigger_id']))
    queue['counts']=dict(Counter(r['priority_class'] for r in queue['rows']))
    queue['apollo_research_calls']=role_calls;queue['apollo_research_credits']=0
    health.append({'source':'apollo_roles','state':'PARTIAL' if any(c.get('state')=='PARTIAL' for c in role_cache.values()) else 'WORKING' if role_cache else 'UNKNOWN',
                   'observed_at':max((c.get('observed_at','') for c in role_cache.values()),default=None),
                   'coverage':'PARTIAL — THREE DOMAINS/TORONTO DAY', 'requests':role_calls,
                   'reason':'Likely contacts retained for research; current-employer proof required before eligibility;14-day per-domain cache'})
    for h in health:
        store.source('trigger_'+h['source'], h['state'], now, observed_at=h.get('observed_at'), reason=str(h.get('reason') or '') + '; ' + str(h.get('coverage') or ''), requests=h['requests'], cache_hit=h['requests'] == 0)
    store.prune_triggers(now); atomic(ROOT/'triggers-view.json', queue)
    display = projection(queue)
    if len(json.dumps(display, ensure_ascii=False, indent=2).encode()) > 131072: raise ValueError('Trigger owner projection exceeds byte bound')
    atomic(DISPLAY, display, 0o600); os.chown(DISPLAY, 0, grp.getgrnam('opticable-workflow-api').gr_gid); os.chmod(DISPLAY, 0o640)
    sales = cache_read(SALES_DISPLAY, 262144)
    if sales and stamp(sales.get('at')) and 0 <= (now-stamp(sales['at'])).total_seconds() < 3600:
        sales['rows'] = [r for r in sales.get('rows', []) if r.get('kind') != 'trigger'] + sales_rows(queue['rows'])
        sales['rows'].sort(key=lambda r: (r['priority'], r['key'])); sales['rows'] = sales['rows'][:20]
        sales['trigger_shadow_state'] = 'PHASE30 — NO CONTACT AUTHORITY'; sales['trigger_observed_at'] = queue['at']
        atomic(SALES_DISPLAY, sales, 0o600); os.chown(SALES_DISPLAY, 0, grp.getgrnam('opticable-workflow-api').gr_gid); os.chmod(SALES_DISPLAY, 0o640)
    return queue
