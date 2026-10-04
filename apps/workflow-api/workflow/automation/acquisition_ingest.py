"""Normalize bounded source snapshots without changing any provider record."""
from datetime import datetime, timezone
import re
from .acquisition_store import digest, normalized
from .acquisition_intelligence import service_for, language_for, intent_for, SERVICES, opportunities
from .sales_intelligence import domain, live, contact_state, stamp


def gsc_rows(read):
    return [{'query':r['keys'][0],'page':r['keys'][1],**{k:r.get(k) for k in ('clicks','impressions','ctr','position')}} for r in read.get('data',{}).get('rows',[]) if len(r.get('keys',[]))==2]


def ingest(store,inputs,*,now):
    if inputs.get('schema')!=1 or now.tzinfo is None:raise ValueError('Versioned aware acquisition inputs required')
    apollo=inputs.get('apollo',{});companies={};queries=[];signals=[];competitors=[]
    def put(kind,row,source,rid,url,sid=None,raw=None,at=None):
        return store.record(kind,row,source=source,native_id=rid,url=url,now=now,snapshot=sid,raw=raw,
                            observed_at=at or inputs.get('at'),effective_date=row.get('effective_date'),
                            confidence='DERIVED MARKET POLICY' if source=='optibrain_market' else 'SOURCE OBSERVED; NORMALIZATION / CLASSIFICATION EXPLAINED')
    def snapshot(source,url,raw):
        period=raw if isinstance(raw,dict) and raw.get('date_from') else inputs if source=='search_console' else inputs.get('broker_period',{}) if source=='gbp' else {}
        return store.snapshot(source,url,raw,now,effective_from=period.get('date_from'),effective_to=period.get('date_to'))
    # Existing saved Apollo state is reused; no prospect creation or credit call.
    for n in range(0,len(apollo.get('contacts',[])),100):
        contacts=apollo['contacts'][n:n+100];sid=snapshot('apollo_contacts_'+str(n//100),'https://app.apollo.io/',contacts)
        stages={r['id']:r.get('display_name') or r.get('name','') for r in apollo.get('stages',[])}
        for c in contacts:
            if not live(c):continue
            a=c.get('account') or {};native=str(a.get('id') or c.get('account_id') or '')
            company=None
            if native:
                company={'name':a.get('name'),'domain':a.get('domain'),'apollo_organization_id':a.get('organization_id'),
                         'outreach_owner':'CLAUDE_APOLLO','geography':a.get('city') or 'UNKNOWN','icp':'UNKNOWN'}
                r=put('COMPANY',company,'apollo',native,'https://app.apollo.io/#/accounts/'+native,sid,raw=a,at=apollo.get('at'))
                if not r.get('id') or r['state'].startswith('IDENTITY CONFLICT'):continue
                company_id=r['id'];companies[company_id]={**company,'id':company_id}
            else:company_id=None
            p={'name':' '.join(str(c.get(k) or '') for k in ('first_name','last_name')).strip(),'email':c.get('email'),
               'title':c.get('title'),'apollo_contact_id':c['id'],'company_id':company_id,'outreach_owner':'CLAUDE_APOLLO'}
            r=put('PERSON',p,'apollo',c['id'],'https://app.apollo.io/#/contacts/'+c['id'],sid,raw=c,at=apollo.get('at'))
            if not r.get('id') or r['state'].startswith('IDENTITY CONFLICT'):continue
            state=contact_state(c,apollo.get('messages',[])+apollo.get('replies',[]),stages,now=now)
            put('OUTREACH_STATE',{'person_id':r['id'],'owner':'CLAUDE_APOLLO','cold_send_allowed':False,
                               'active':state.get('active'),'recent_send':state.get('recent_send')},'apollo',c['id'],'https://app.apollo.io/#/contacts/'+c['id'],sid,at=apollo.get('at'))
            if state.get('suppressed'):put('SUPPRESSION',{'person_id':r['id'],'suppressed':True,'reasons':state.get('reasons',[])},'apollo',c['id'],'https://app.apollo.io/#/contacts/'+c['id'],sid,at=apollo.get('at'))
    accounts=apollo.get('accounts',[]);sid=snapshot('apollo_accounts','https://app.apollo.io/',accounts)
    for a in accounts:
        row={'name':a.get('name'),'domain':a.get('primary_domain') or a.get('domain'),'apollo_organization_id':a.get('organization_id'),
             'website':a.get('website_url'),'founded_year':a.get('founded_year'),'geography':a.get('city') or 'UNKNOWN','icp':'UNKNOWN','outreach_owner':'CLAUDE_APOLLO'}
        r=put('COMPANY',row,'apollo',a['id'],'https://app.apollo.io/#/accounts/'+a['id'],sid,raw=a,at=apollo.get('at'))
        if r.get('id') and not r['state'].startswith('IDENTITY CONFLICT'):companies[r['id']]={**row,'id':r['id']}
    store.source('apollo','WORKING' if apollo.get('contacts_complete') else 'PARTIAL',now,observed_at=apollo.get('at'),
                 reason='Saved workspace reused; outreach ownership and suppressions protected. No enrichment or sequence changes.',credits=0,requests=0,cache_hit=True)
    crm=inputs.get('crm',{});sid=snapshot('crm_identity','https://crm.zoho.com/',crm)
    for r in crm.get('Accounts',[]):
        if not live(r):continue
        row={'name':r.get('Account_Name'),'website':r.get('Website'),'crm_account_id':r['id'],'existing_customer':True,'outreach_owner':'OWNER_MANUAL'}
        put('COMPANY',row,'crm',r['id'],'https://crm.zoho.com/crm/tab/Accounts/'+r['id'],sid,raw=r,at=inputs.get('crm_at'))
    for r in crm.get('Contacts',[]):
        if not live(r):continue
        row={'name':r.get('Full_Name'),'email':r.get('Email'),'crm_contact_id':r['id'],'existing_customer':True}
        put('PERSON',row,'crm',r['id'],'https://crm.zoho.com/crm/tab/Contacts/'+r['id'],sid,raw=r,at=inputs.get('crm_at'))
    store.source('crm','WORKING',now,observed_at=inputs.get('crm_at'),reason='Existing exact CRM identity cache reused; protected records READ ONLY, no raw research promotion.',cache_hit=True)
    google=inputs.get('google',{}).get('reads',{});gsc=google.get('gsc_queries',{})
    queries=gsc_rows(gsc) if gsc.get('state')=='WORKING' else inputs.get('gsc',[])
    url='https://search.google.com/search-console?resource_id=sc-domain%3Aopticable.ca';sid=snapshot('search_console',url,queries)
    for r in queries:
        row={**r,'language':language_for(r['query']),'geography':'UNKNOWN','service':service_for(r['query']),'intent':intent_for(r['query']),
             'market_volume':None,'metric_scope':'Opticable query-page visibility; not total search demand'}
        observed=gsc.get('observed_at') or inputs.get('google',{}).get('at') if gsc.get('state')=='WORKING' else inputs.get('broker_at')
        put('KEYWORD',row,'search_console',digest([r['query'],r['page']]),url,sid,raw=r,at=observed)
        put('SOURCE_PERFORMANCE',row,'search_console',digest([r['query'],r['page'],inputs.get('date_from'),inputs.get('date_to')]),url,sid,raw=r,at=observed)
    attempts=inputs.get('google',{}).get('attempts',{})
    current_gsc=gsc.get('state')=='WORKING' and attempts.get('gsc_queries',{}).get('state','WORKING')=='WORKING' and not attempts.get('collection')
    store.source('search_console','WORKING' if current_gsc else 'PARTIAL',now,observed_at=(gsc.get('observed_at') or inputs.get('google',{}).get('at')) if gsc.get('state')=='WORKING' else inputs.get('broker_at'),
                 reason='Native bounded query/page and historical reports.' if gsc.get('state')=='WORKING' else 'Windsor first-party performance fallback; native read blocked.',requests=6 if gsc.get('state')=='WORKING' else 0,query='query/page, daily, country, device')
    for name in ('ads_campaigns','ads_keywords','ads_search_terms','ga4_main','ga4_other','gsc_daily','gsc_countries','gsc_devices','gsc_sitemaps'):
        read=google.get(name,{})
        if read.get('state')!='WORKING':continue
        source='google_ads' if name.startswith('ads_') else 'ga4' if name.startswith('ga4') else 'search_console'
        url='https://ads.google.com/aw/overview?ocid=6808491878' if source=='google_ads' else 'https://analytics.google.com/' if source=='ga4' else 'https://search.google.com/search-console/'
        sid=snapshot(name,url,read)
        data=read['data'];rows=data.get('results',data.get('rows',[]))
        put('SOURCE_PERFORMANCE',{'report':name,'row_count':len(rows),'effective_date':read.get('date_to'),'snapshot_id':sid},source,name,url,sid,at=read.get('observed_at') or inputs.get('google',{}).get('at'))
        if name=='gsc_daily':
            for r in rows:
                if r.get('keys'):store.timeseries('search_console',r['keys'][0],r,sid,now)
        if name=='ads_keywords':
            for r in read['data'].get('results',[]):
                c=r.get('adGroupCriterion',{});text=c.get('keyword',{}).get('text')
                if not text:continue
                row={'query':text,'language':language_for(text),'geography':'UNKNOWN','service':service_for(text),'intent':intent_for(text),
                     'negative':c.get('negative'),'status':c.get('status'),'match_type':c.get('keyword',{}).get('matchType'),
                     'metrics':r.get('metrics',{}),'quality_score':c.get('qualityInfo',{}).get('qualityScore')}
                put('AD_KEYWORD',row,'google_ads',c.get('resourceName'),url,sid,raw=r,at=read.get('observed_at') or inputs.get('google',{}).get('at'))
                if not c.get('negative'):put('KEYWORD',row,'google_ads',c.get('resourceName'),url,sid,raw=r,at=read.get('observed_at') or inputs.get('google',{}).get('at'))
    ads=google.get('ads_customer',{})
    store.source('google_ads','PARTIAL' if attempts.get('ads_customer',{}).get('state','WORKING')!='WORKING' or attempts.get('collection') else ads.get('state','UNKNOWN'),now,observed_at=ads.get('observed_at') or inputs.get('google',{}).get('at'),
        reason='Native account, campaigns, keywords and search-term reads; CAD / Toronto. Historical removed campaigns remain unchanged; missing CPC is unknown.',requests=5)
    ga=[google.get(k,{}) for k in ('ga4_main','ga4_other')]
    store.source('ga4','PARTIAL',now,
        observed_at=ga[0].get('observed_at') or inputs.get('google',{}).get('at'),reason='Native reporting API works; inspected reports have no rows. Event/consent instrumentation remains partial; missing events are not inferred.',requests=2)
    gbp=inputs.get('gbp',[]);url='https://business.google.com/';sid=snapshot('gbp',url,gbp)
    put('SOURCE_PERFORMANCE',{'report':'GBP visibility','rows':gbp,'metric_scope':'Provider daily report; missing reviews are not zero reviews'},'gbp','7349986536842101698',url,sid)
    store.source('gbp','PARTIAL' if gbp else 'UNKNOWN',now,observed_at=inputs.get('gbp_at') or inputs.get('broker_at'),reason='Windsor native GBP daily visibility read; reviews/posts/call attribution partial.',requests=1)
    store.source('windsor','WORKING',now,observed_at=inputs.get('broker_at'),reason='Connected source/field discovery and cached first-party fallback. Native Ads avoids duplicate paid collection.',requests=0,cache_hit=True,cost_class='EXISTING SUBSCRIPTION; INCREMENTAL COST NOT EXPOSED')
    for name,report in inputs.get('social',{}).items():
        if name not in {'facebook_organic','instagram','linkedin_organic'}:continue
        url={'facebook_organic':'https://www.facebook.com/','instagram':'https://www.instagram.com/','linkedin_organic':'https://www.linkedin.com/'}[name]
        sid=snapshot(name,url,report)
        put('SOURCE_PERFORMANCE',{'report':name,'row_count':len(report.get('rows',[])),
            'metric_scope':'Bounded connected-account report; empty period is not proof of no historical posts'},name,name,url,sid,at=report.get('at'))
        store.source(name,'WORKING' if report.get('rows') else 'PARTIAL',now,observed_at=report.get('at'),
            reason='Connected Windsor read accepted; inspected period returned no rows. No posts or campaigns changed.',requests=1,cache_hit=True)
    # Public records retain native identifiers. Business certification is context,
    # never a buying trigger or permission to contact.
    rows=inputs.get('public_business',[]);url='https://www.donneesquebec.ca/recherche/dataset/entreprises-certifiees-oqlf';sid=snapshot('oqlf',url,rows)
    for r in rows:
        row={'name':r.get('NOM_ENTREPRISE'),'registry_number':str(r['MATRICULE']),'address':r.get('ADDR_PARTIE1'),
             'geography':r.get('ADDR_PARTIE2'),'postal_code':r.get('C_POSTAL'),'certification_date':r.get('CERTIF_PERM'),'buying_intent':False}
        put('COMPANY',row,'oqlf',r['MATRICULE'],url,sid,raw=r,at=inputs.get('public_business_at'))
        put('LOCATION',row,'oqlf',str(r['MATRICULE'])+':address',url,sid,raw=r,at=inputs.get('public_business_at'))
    store.source('registry','PARTIAL',now,observed_at=inputs.get('public_business_at'),reason='OQLF CC BY 4.0 bounded business/NEQ sample works. REQ bulk CC BY-NC-SA is excluded from commercial acquisition.',requests=1)
    raw_permits={str(r.get('id_permis')):r for r in inputs.get('raw_permits',[])}
    raw_tenders={r.get('ocid'):r for r in inputs.get('seao_raw',[])}
    permit_snapshot=snapshot('montreal_permit_native','https://donnees.montreal.ca/dataset/permis-construction',inputs.get('raw_permits',[]))
    for r in inputs.get('signals',[]):
        ends=stamp(r.get('deadline'))
        if ends and ends<=now:continue
        row={'id':r['key'],'source':r['source'],'title':r['trigger'],'why':r['why_now'],'source_url':r['source_url'],
             'record_id':r['record_id'],'effective_date':r.get('trigger_at'),'deadline':r.get('deadline'),
             'site':r.get('site'),'company':r.get('company'),'service_fit':[r.get('fit','')],'geography':r.get('geography','Montréal' if r['source']=='montreal_permit' else 'UNKNOWN'),
             'contact_allowed':False,'identity_unresolved':True,'outreach_owner':'OPTIBRAIN_RESEARCH_ONLY'}
        proof=raw_permits.get(r['record_id']) or raw_tenders.get(r['record_id']) or r
        sid=permit_snapshot if r['source']=='montreal_permit' else snapshot(r['source'],r['source_url'],proof)
        at=inputs.get('permits_at') if r['source']=='montreal_permit' else inputs.get('seao_at')
        put('PROJECT',row,r['source'],r['record_id'],r['source_url'],sid,raw=proof,at=at)
        put('TRIGGER',row,r['source'],r['record_id'],r['source_url'],sid,raw=proof,at=at)
        signals.append(row)
    store.source('permits','PARTIAL',now,observed_at=inputs.get('permits_at'),reason='Montréal latest 100 native records reused; two relevant commercial proofs. Laval result is road obstruction, not building intent; no misclassification.',cache_hit=True)
    store.source('seao','PARTIAL',now,observed_at=inputs.get('seao_at'),reason='Curated native OCDS proof; active deadlines enforced. Latest procurement amendment/requirements still need review.',cache_hit=True)
    for r in inputs.get('competitors',[]):
        text=re.sub('<[^>]+>',' ',r.get('html','')).casefold();url=r['url'];host=domain(url)
        services=[s for s,tokens in SERVICES.items() if any(t in text for t in tokens)]
        row={'domain':host,'url':url,'services':services,'discovery_query':r['discovery_query'],
             'http_status':r.get('http_status'),'ranking':None,'authority':None,'paid_presence':None,
             'method':'Live service-search discovery; service overlap from fetched primary page, not measured rank/share'}
        sid=snapshot('competitor_'+host,url,r)
        proof={k:v for k,v in r.items() if k!='html'};proof['html_hash']=digest(r.get('html',''))
        put('COMPETITOR',row,'competitors',host,url,sid,raw=proof,at=inputs.get('competitors_at'))
        put('COMPETITOR_PAGE',row,'competitors',url,url,sid,raw=proof,at=inputs.get('competitors_at'))
        if 'html' in r:competitors.append(row)
    store.source('competitors','PARTIAL',now,observed_at=inputs.get('competitors_at'),reason='Live FR/EN service-search discovery and bounded primary pages; neutral rankings, backlinks and paid visibility unmeasured.',requests=len(inputs.get('competitors',[])))
    for source,reason in [('clay','BLOCKED IN EXECUTION ENVIRONMENT — installed plugin, no callable tools; no credits spent.'),
                          ('semrush','Installed plugin, no callable tools in this execution. Prior insufficient API units remains unverified; one discovery check, no retry/purchase.'),
                          ('ahrefs','Installed plugin, no callable tools in this execution. Prior insufficient-plan limitation remains unverified; one discovery check, no retry/upgrade.')]:
        store.source(source,'BLOCKED',now,observed_at=inputs.get('providers_checked_at'),reason=reason,requests=0)
    markets=opportunities(queries,signals,competitors,list(companies.values()),outcomes=inputs.get('verified_outcomes'))
    for m in markets:
        url='https://optibrain.opticable.ca/v1/operator/acquisition'
        put('MARKET_SEGMENT',{'service':m['service'],'icp':m['icp'],'geography':m['geography']},'optibrain_market',m['id'],url)
        put('OPPORTUNITY',m,'optibrain_market',m['id'],url)
    url='https://optibrain.opticable.ca/v1/operator/acquisition'
    for name in SERVICES:put('SERVICE',{'name':name,'method':'Owner-defined Opticable service vocabulary; not an installed CRM Service'},'optibrain_market',name,url)
    for name in sorted({r['icp'] for r in markets}):put('ICP',{'name':name,'method':'Owner-defined acquisition target'},'optibrain_market',name,url)
    for health in store.summary(now)['source_health']:put('SOURCE',{'name':health['source'],'refresh_seconds':health['refresh_seconds'],'cost_class':health['cost_class']},'optibrain_market',health['source'],url)
    return {'schema':1,'at':now.isoformat(),'scope':'live','read_only':True,**store.summary(now),
            'opportunities':markets,'prospect_signals':signals,'competitors':competitors,
            'queries':queries,'mode':'ZERO-LEAD MARKET EVIDENCE','content_publication_enabled':False,
            'conversion_upload_enabled':False,'financial_writes':0,'advertising_mutations':0,
            'next_actions':[{'title':'Review '+s['title'],'why':s['why']} for s in signals[:2]]}
