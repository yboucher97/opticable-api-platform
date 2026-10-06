"""Canonical manager registry projects existing source evidence; no API probes."""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

HEALTH = {'GREEN','STALE','PARTIAL','BLOCKED','RATE_LIMITED','AUTH_EXPIRED','PLAN_LIMITED',
          'NO_CREDITS','PROVIDER_ERROR','INTENTIONALLY_OPTIONAL','OWNER_DEFERRED','UNKNOWN'}
# source id, provider, purpose, access, refresh seconds, required, capability, authority
SPECS = [
 ('crm','Zoho CRM','Canonical business relationships','OAUTH',7200,True,'SCOPED','EXISTING_INTERNAL_SCOPES'),
 ('books','Zoho Books','Financial truth and recurring billing','OAUTH',7200,True,'READ_ONLY','ABSENT'),
 ('mail','Zoho Mail','Acknowledged inquiries and conversations','OAUTH',86400,True,'SCOPED','EXISTING_CUSTOMER_SCOPES'),
 ('forms','Zoho Forms','FR/EN quote intake and conversion telemetry','WEBHOOK',7200,True,'READ_ONLY','ABSENT'),
 ('workdrive','Zoho WorkDrive','Existing documents','OAUTH',86400,False,'CONTAINED','DISABLED'),
 ('sign','Zoho Sign','Manual signature workflow','OAUTH',86400,False,'PLAN_LIMITED','ABSENT'),
 ('ga4','GA4','Production behavior and successful-form observation','OAUTH',3*86400,True,'READ_ONLY','ABSENT'),
 ('search_console','Search Console','Organic discovery','OAUTH',3*86400,True,'READ_ONLY','ABSENT'),
 ('google_ads','Google Ads','Native Ads inventory and proposal evidence','OAUTH',7*86400,True,'READ_ONLY','ABSENT'),
 ('gbp','Google Business Profile','Profile and local discovery','CACHE',7*86400,False,'READ_ONLY','ABSENT'),
 ('windsor_keyword_planner','Windsor','Cached keyword economics','CACHE',30*86400,False,'READ_ONLY','ABSENT'),
 ('apollo','Apollo','Existing outreach and contact collision evidence','CACHE',86400,True,'READ_ONLY','ABSENT'),
 ('linkedin_organic','LinkedIn','Accessible public/connector context','CONNECTOR',7*86400,False,'NONE','ABSENT'),
 ('cloudflare','Cloudflare','Edge events, queues and protected owner access','DIRECT API',7200,True,'TECHNICAL_ONLY','EXISTING_TECHNICAL_SCOPES'),
 ('github','GitHub','Reviewed source and deployment CI','DIRECT API',86400,True,'TECHNICAL_ONLY','EXISTING_TECHNICAL_SCOPES'),
 ('seao','SEAO','Public tenders and historical buyers','PUBLIC DATA',3*86400,True,'NONE','ABSENT'),
 ('montreal_permit','Montréal permits','Commercial project triggers','PUBLIC DATA',86400,True,'NONE','ABSENT'),
 ('laval_permit','Laval permits','Historical permit intelligence','PUBLIC DATA',7*86400,False,'NONE','ABSENT'),
 ('quebec_permit','Québec City permits','Bounded official permit coverage','PUBLIC DATA',7*86400,False,'NONE','ABSENT'),
 ('company_announcement','Company/project sources','Primary project proof','PUBLIC DATA',7*86400,False,'NONE','ABSENT'),
 ('website','Website repositories','Page inventory and preview preparation','CACHE',7*86400,True,'TECHNICAL_ONLY','OWNER_APPROVAL_REQUIRED'),
 ('ai_website','AI website','AI service pages and qualified demand','CACHE',7*86400,False,'TECHNICAL_ONLY','OWNER_APPROVAL_REQUIRED'),
 ('competitors','Structured research sources','Service and market context','PUBLIC DATA',7*86400,False,'NONE','ABSENT'),
 ('holo','Holo','Optional supported creative production / brief handoff','MANUAL',30*86400,False,'NONE','ABSENT'),
]


def stamp(value):
    try:
        at=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return at if at.tzinfo is not None else None
    except (ValueError,TypeError):return None


def health_state(value):
    t=str(value or '').upper().replace(' ','_')
    for k in ('AUTH_EXPIRED','RATE_LIMITED','PLAN_LIMITED','NO_CREDITS','PROVIDER_ERROR','BLOCKED','OWNER_DEFERRED'):
        if k in t:return k
    if t in {'WORKING','OK','HEALTHY','FRESH','GREEN','COMPLETED','PROVEN','MEASURED'}:return 'GREEN'
    if 'STALE' in t:return 'STALE'
    if t in {'PARTIAL','DEGRADED','ISSUE','ACTION_REQUIRED'}:return 'PARTIAL'
    return 'UNKNOWN'


def registry(inputs,now):
    existing={}
    for view in ('acquisition-intelligence','trigger-intelligence'):
        for r in inputs.get(view,{}).get('source_health',[]):existing[r.get('source')]=r
    business=inputs.get('business',{});snapshot=business.get('snapshot',{})
    sales=inputs.get('sales-conversations',{})
    signals={r.get('name'):r for r in inputs.get('status',{}).get('signals',[])}
    output=[]
    for sid,provider,purpose,access,ttl,required,write,authority in SPECS:
        r=dict(existing.get(sid,{}));observed=r.get('source_effective_at') or r.get('observed_at')
        auth='UNKNOWN';state=health_state(r.get('state'));reason=r.get('reason') or 'No independent source observation retained'
        if sid in {'crm','books'} and snapshot:
            collection=business.get('collection') or snapshot.get('collection',{})
            names=('accounts','contacts','leads','deals','services','sites') if sid=='crm' else ('books_estimate_index','books_invoices','customers','recurring_details')
            modules=collection.get('modules',{})
            complete=all(modules.get(n,{}).get('state')=='COMPLETE' for n in names)
            dates=[modules.get(n,{}).get('source_at') for n in names]
            observed=min(dates) if all(dates) else business.get('observed_at') or snapshot.get('observed_at')
            state='GREEN' if complete else 'PARTIAL';auth='GREEN' if any(modules.get(n,{}).get('successful_reads',0) for n in names) else 'UNKNOWN'
            reason='Independent native module completeness; missing or reused stages cannot certify a fresh whole source'
            r['latest_error']={n:modules.get(n,{}).get('state','NOT_COLLECTED_UNKNOWN') for n in names if modules.get(n,{}).get('state')!='COMPLETE'} or None
        if sid=='apollo' and sales.get('apollo_observed_at') and state in {'GREEN','UNKNOWN'}:
            from .observation_completeness import APOLLO_REQUIRED
            coverage=inputs.get('sales-intelligence',{}).get('module_completeness',{}).get('apollo',{})
            observed=sales['apollo_observed_at'];state='GREEN' if all(coverage.get(n,{}).get('complete') for n in APOLLO_REQUIRED) else 'PARTIAL'
            auth='UNKNOWN';reason='Cached workspace; bounded activity samples and missing ownership/suppression coverage remain partial'
        if sid=='mail' and sales.get('observed_at'):
            observed=sales['observed_at'];state='GREEN' if sales.get('source_health',{}).get('mail',{}).get('fresh') else 'PARTIAL'
            reason='Exact-header-bound replies only; unknown bodies retained';auth='GREEN' if sales.get('source_health',{}).get('mail',{}).get('last_read_count',0)>0 else 'UNKNOWN'
        if sid=='forms':
            jobs=inputs.get('status',{}).get('activity',{}).get('jobs',[])
            job=next((j for j in jobs if j.get('job')=='opticable-phase9-intake-receipts'),{})
            if job:
                observed=job.get('completed_at');state=health_state(job.get('state'));reason='Observed receipt processing; authentication and genuine inquiry volume are separate'
        if sid=='google_ads':
            ah=inputs.get('ads-intelligence',{}).get('source_health',{})
            if ah:
                observed=ah.get('last_successful_read');state=health_state(ah.get('state'));reason='Weekly native inventory; projection date is not a provider refresh'
                r['latest_error']=ah.get('attempt_results') if state!='GREEN' else None
        if sid=='ga4':
            g=snapshot.get('ga4_collection_health',{})
            auth=health_state(g.get('auth_status'));reason=g.get('coverage_notes') or reason
            if g:state=health_state(g.get('collection_status'));observed=g.get('last_observed_data') or observed
            if isinstance(observed,str) and len(observed)==10:
                observed=datetime.fromisoformat(observed).replace(tzinfo=ZoneInfo('America/Toronto')).isoformat()
            r['observed_at']=g.get('report_observed_at') or r.get('observed_at')
        if sid=='cloudflare':
            q=inputs.get('queue-depth',{});observed=q.get('captured_at')
            state=health_state(q.get('status'));reason='Queue observation only; Access authentication is independent'
        if sid=='github':
            s=signals.get('Deployment',{});observed=inputs.get('status',{}).get('captured_at')
            state=health_state(s.get('state'));reason=s.get('reason') or reason
        if sid=='gbp':state='INTENTIONALLY_OPTIONAL';auth='BLOCKED';reason='Native read lacks business.manage OAuth scope; cached metrics do not prove profile configuration'
        if sid in {'workdrive','sign','linkedin_organic','holo'} and not r:
            state='INTENTIONALLY_OPTIONAL';reason={'sign':'Manual licensed-provider action; automated Sign transport remains contained','holo':'Supported public API unverified; local briefs only, no browser automation'}.get(sid,'Optional direct coverage; no new access or provider required')
        if sid=='ai_website':
            r=dict(existing.get('website',{}));observed=r.get('observed_at');state=health_state(r.get('state'));reason='Shared repository/page cache; site-specific behavior is tracked separately'
        at=stamp(observed)
        if at and not (0<=(now-at).total_seconds()<=ttl) and state=='GREEN':state='STALE'
        if not at and state=='GREEN':state='UNKNOWN'
        age=max(0,int((now-at).total_seconds())) if at else None
        output.append({'source_id':sid,'provider':provider,'business_purpose':purpose,'access_type':access,
            'read_capability':'BOUNDED / AVAILABLE WHERE EVIDENCE EXISTS','write_capability':write,'optibrain_authority':authority,
            'authentication_health':auth,'data_health':state,'data_freshness':('CURRENT' if at and age<=ttl and at<=now else 'STALE' if at else 'UNKNOWN'),
            'observed_at':observed,'latest_successful_read':r.get('observed_at') or observed,
            'latest_error':r.get('latest_error') or (reason if state in {'BLOCKED','PARTIAL','PROVIDER_ERROR','RATE_LIMITED','AUTH_EXPIRED'} else None),
            'cache_age_seconds':age,'refresh_seconds':ttl,'newer_data_expected':required and (age is None or age>ttl),
            'rate_limit':r.get('rate_limit','UNKNOWN'),'plan_limitation':reason if state=='PLAN_LIMITED' else 'UNKNOWN',
            'cost_credits':r.get('credits'),'request_count':r.get('request_count',r.get('requests')),'cache_hits':r.get('cache_hits'),
            'fallback':'Last dated evidence; confidence degrades; independent domains continue','required':required,
            'owner_action':'Optional GBP native read scope' if sid=='gbp' else None,
            'source_confidence':'MODERATE' if state=='GREEN' else 'INSUFFICIENT' if state in {'STALE','BLOCKED','UNKNOWN'} else 'TENTATIVE',
            'reason':reason,'truth_class':'DERIVED_DETERMINISTICALLY'})
    # Retain other active structured sources; optional vendors never become dependencies.
    known={r['source_id'] for r in output}
    for sid,r in sorted(existing.items()):
        if sid in known or not sid or sid.startswith('trigger_') and sid[8:] in existing:continue
        optional=sid in {'semrush','ahrefs','clay','google_basic','keyword_planner'}
        observed=r.get('source_effective_at') or r.get('observed_at');at=stamp(observed);ttl=r.get('refresh_seconds',7*86400 if sid in {'lovo','montoni','saq_gc','apollo_roles','prospect_enrichment'} else 86400)
        state=health_state(r.get('state'))
        if at and (now-at).total_seconds()>ttl and state=='GREEN':state='STALE'
        output.append({**output[-1],'source_id':sid,'provider':sid,'business_purpose':'Structured research evidence',
            'access_type':'CACHE','write_capability':'NONE','optibrain_authority':'ABSENT','authentication_health':'UNKNOWN',
            'data_health':'OWNER_DEFERRED' if sid in {'keyword_planner','google_basic'} else 'INTENTIONALLY_OPTIONAL' if optional else state,'observed_at':observed,
            'data_freshness':'CURRENT' if at and 0<=(now-at).total_seconds()<=ttl else 'STALE' if at else 'UNKNOWN',
            'cache_age_seconds':int((now-at).total_seconds()) if at else None,'refresh_seconds':ttl,
            'latest_successful_read':r.get('observed_at'),'latest_error':r.get('reason') if state!='GREEN' else None,
            'owner_action':None,'required':False,'reason':r.get('reason','UNKNOWN'),'cost_credits':r.get('credits'),
            'request_count':r.get('request_count',r.get('requests')),'cache_hits':r.get('cache_hits'),
            'newer_data_expected':False,'source_confidence':'MODERATE' if state=='GREEN' else 'TENTATIVE'})
    return output


def evidence_health(evidence,sources,now):
    """A refreshed display cannot rejuvenate evidence or missing provider facts."""
    by={r['source_id']:r for r in sources};result=[]
    aliases={'zoho_mail':'mail','zoho_crm':'crm','zoho_books':'books','google_ads':'google_ads',
             'google':'google_ads','search_console':'search_console','windsor':'windsor_keyword_planner'}
    for original in evidence:
        e=dict(original);key=str(e.get('provider','')).lower().replace(' ','_')
        related=[by[sid] for name,sid in aliases.items() if name in key and sid in by]
        if 'apollo' in key and 'apollo' in by:related.append(by['apollo'])
        if key=='public_trigger':related.extend(by[s] for s in ('seao','montreal_permit','quebec_permit') if s in by and s in str(e.get('source_reference','')))
        at=stamp(e.get('observed_at'));until=stamp(e.get('valid_until'))
        ttl=min([s['refresh_seconds'] for s in related] or [7*86400])
        stale=bool(at and (now-at).total_seconds()>ttl or until and now>until)
        unknown=at is None or at>now if at else True
        degraded=any(s['data_health'] in {'STALE','BLOCKED','AUTH_EXPIRED','RATE_LIMITED','PROVIDER_ERROR','NO_CREDITS'} for s in related)
        e.update(cache_age_seconds=max(0,int((now-at).total_seconds())) if at else None,
            freshness='STALE' if stale or degraded or e.get('freshness')=='STALE' else 'UNKNOWN' if unknown else e.get('freshness','CURRENT'),
            newer_data_expected=stale or degraded,source_health=[s['data_health'] for s in related],
            fact_class={'NATIVE_MEASURED':'PUBLIC_SOURCE_FACT' if any(n in key for n in ('permit','seao','public')) else 'PROVIDER_FACT',
                        'OWNER_CONFIRMED':'USER_CONFIRMED','DERIVED_DETERMINISTIC':'DERIVED_DETERMINISTICALLY',
                        'ESTIMATED':'ESTIMATE','INFERRED':'MODEL_INFERENCE'}.get(e.get('truth_class'),'UNKNOWN'))
        result.append(e)
    return result
