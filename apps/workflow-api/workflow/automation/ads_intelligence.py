"""Deterministic, evidence-based Ads preparation; no provider execution."""
from collections import Counter, defaultdict
from datetime import timedelta
from html import escape
import re
from .acquisition_store import digest, normalized
from .acquisition_intelligence import service_for, language_for, number
from .keyword_economics import normalize as economics_rows

SERVICES = ('Security cameras','AI loss prevention','Structured cabling','Commercial Wi-Fi',
            'Access control','Fiber installation','Construction cameras','Construction Wi-Fi')
PAGES = {
    'Security cameras':('systemes-cameras-securite','security-camera-systems'),
    'Structured cabling':('cablage-structure','structured-cabling'),
    'Commercial Wi-Fi':('installation-wifi-commercial','commercial-wifi-installation'),
    'Access control':('systemes-controle-acces','access-control-systems'),
    'Fiber installation':('installation-fibre-optique','fiber-optic-installation'),
}
NEGATIVES = [
    {'text':v,'match':'PHRASE','reason':'Employment/training/DIY or explicitly home-only intent',
     'exceptions':'Review the full query; do not exclude commercial renovation, construction or installer services.'}
    for v in ('emploi','salaire','jobs','salary','career','formation','cours','diy','do it yourself',
              'pour maison','pour la maison','home security','for home','para casa')]


def rows(inventory,kind):
    r=inventory.get('reads',{}).get(kind,{})
    return r.get('data',{}).get('results',[]) if r.get('state')=='WORKING' else []


def classify_term(text):
    q=normalized(text)
    if re.search(r'@|\b\d{7,}\b',q): return 'PRIVATE QUERY — OMITTED'
    if 'opticable' in q: return 'BRAND'
    if any(t in q for t in ('emploi','salary','salaire','jobs','career','para casa','pour maison','home security','for home')):
        return 'NEGATIVE CANDIDATE'
    if any(t in q for t in ('how to','comment installer','definition','définition','diy','formation','statistics')):
        return 'RESEARCH'
    service=service_for(q)
    if not service: return 'OTHER'
    installation=any(t in q for t in ('install','entreprise','business','commercial','entrepôt','warehouse','cablage','câblage','cabling'))
    if service=='Security cameras' and not installation and any(t in q for t in ('eufy','tapo','dekco','yi camera','nest camera','vigi','acculenz')):
        return 'NEGATIVE CANDIDATE'
    if installation: return 'HIGH INTENT'
    if service in ('Security cameras','Commercial Wi-Fi'): return 'RESEARCH'
    return 'RELEVANT'


def inventory_summary(inventory):
    counts=Counter(r['campaign']['status'] for r in rows(inventory,'campaigns'))
    def totals(kind):
        rr=rows(inventory,kind);read=inventory.get('reads',{}).get(kind,{})
        if read.get('state')!='WORKING': return {'state':read.get('state','UNKNOWN'),'cost':None,'clicks':None,'impressions':None,'conversions':None}
        return {'state':'OBSERVED','date_from':read.get('date_from'),'date_to':read.get('date_to'),
                'cost':round(sum(float(r.get('metrics',{}).get('costMicros',0))/1e6 for r in rr),6),
                'clicks':sum(int(r.get('metrics',{}).get('clicks',0)) for r in rr),
                'impressions':sum(int(r.get('metrics',{}).get('impressions',0)) for r in rr),
                'conversions':sum(float(r.get('metrics',{}).get('conversions',0)) for r in rr),
                'conversion_value':sum(float(r.get('metrics',{}).get('conversionsValue',0)) for r in rr)}
    classified=[]
    for r in rows(inventory,'search_terms_history'):
        category=classify_term(r['searchTermView']['searchTerm'])
        if category=='PRIVATE QUERY — OMITTED': continue
        classified.append({'query':r['searchTermView']['searchTerm'],'category':category,
            'campaign_id':r['campaign']['id'],'cost':float(r.get('metrics',{}).get('costMicros',0))/1e6,
            'clicks':int(r.get('metrics',{}).get('clicks',0)),'impressions':int(r.get('metrics',{}).get('impressions',0))})
    return {'account':'6808491878','currency':(rows(inventory,'customer') or [{}])[0].get('customer',{}).get('currencyCode'),
        'campaigns':sum(counts.values()) if inventory.get('reads',{}).get('campaigns',{}).get('state')=='WORKING' else None,
        'campaign_statuses':dict(counts),'performance_90d':totals('performance_90d'),
        'performance_history':totals('performance_history'),'search_terms_current':len(rows(inventory,'search_terms_90d')),
        'search_terms_historical':len(classified),'term_categories':dict(Counter(r['category'] for r in classified)),
        'negative_candidates':sorted([r for r in classified if r['category']=='NEGATIVE CANDIDATE'],key=lambda r:-r['cost'])[:30],
        'term_sample':sorted(classified,key=lambda r:-r['cost'])[:40],
        'term_coverage':'Privacy-limited Search term view; excludes unreported queries and other network traffic. Not total campaign spend.',
        'conversion_actions':[r['conversionAction'] for r in rows(inventory,'conversion_actions')],
        'conversion_metrics':{k:rows(inventory,k) for k in ('conversion_metrics_90d','conversion_metrics_history')},
        'coverage':{k:{'state':r.get('state'),'complete':r.get('complete'),'observed_at':r.get('observed_at')} for k,r in inventory.get('reads',{}).items()},
        'provider_writes':0}


def evidence(provider,ref,at,*,truth='NATIVE_MEASURED',confidence='MODERATE',days=7,limitations=None,now=None):
    from datetime import datetime
    expiry=(datetime.fromisoformat(at.replace('Z','+00:00'))+timedelta(days=days)).isoformat() if at else None
    return {'provider':provider,'source_reference':ref,'observed_at':at,'valid_until':expiry,
            'freshness':('CURRENT' if not now or datetime.fromisoformat(at.replace('Z','+00:00'))<=now<datetime.fromisoformat(expiry) else 'STALE') if at else 'UNKNOWN','confidence':confidence,'truth_class':truth,
            'limitations':limitations or []}


def assess(inputs,now):
    inventory=inputs.get('ads',{});summary=inventory_summary(inventory)
    econ=[];econ_state='SOURCE UNAVAILABLE'
    if inputs.get('keyword_economics'):
        try:
            econ=economics_rows(inputs['keyword_economics'],now=now)
            econ_state='STALE' if any(r['stale'] for r in econ) else 'CACHED — CURRENT'
        except (ValueError,KeyError,TypeError): econ_state='INVALID SOURCE — UNKNOWN'
    demand=defaultdict(list)
    read=inputs.get('google',{}).get('reads',{}).get('gsc_queries',{})
    if read.get('state')=='WORKING':
        for r in read.get('data',{}).get('rows',[]):
            if len(r.get('keys',[]))<3 or r['keys'][2]!='can': continue
            if classify_term(r['keys'][0])=='PRIVATE QUERY — OMITTED': continue
            s=service_for(r['keys'][0])
            if s: demand[s].append(r)
    opportunities=[]
    for service in SERVICES:
        native=demand[service];impressions=sum(r.get('impressions',0) for r in native)
        available=[r for r in econ if r['service']==service]
        usable=[r for r in available if not r['stale']]
        cpc=[r['cpc'] for r in usable if r['cpc'] is not None]
        pages={lang:'https://opticable.ca/'+lang.lower()+'/services/'+PAGES[service][i]+'/' for i,lang in enumerate(('FR','EN'))} if service in PAGES else ({'FR':'https://ai.opticable.ca/fr/','EN':None} if service=='AI loss prevention' else {'FR':None,'EN':None})
        readiness={lang:inputs.get('website',{}).get(url,{}).get('readiness','NOT VERIFIED') if url else 'PREVIEW PAGE REQUIRED' for lang,url in pages.items()}
        if service=='AI loss prevention': channels=['CONTENT','OUTBOUND','PARTNERSHIP','SEO'];rating='WATCH — SEARCH SECONDARY'
        elif service=='Security cameras': channels=['GOOGLE ADS','SEO','GBP'];rating='PRIORITY PILOT — COMMERCIAL INTENT ONLY'
        elif service=='Structured cabling':
            channels=['GOOGLE ADS','SEO','PARTNERSHIP']
            rating='STRONGEST QUANTITATIVE SEARCH EVIDENCE' if cpc else 'RESEARCH — ECONOMICS UNKNOWN'
        elif service=='Commercial Wi-Fi': channels=['SEO','OUTBOUND','GOOGLE ADS AFTER CPC VALIDATION'];rating='SECONDARY — ECONOMICS UNKNOWN'
        else: channels=['SEO','OUTBOUND','PARTNERSHIP'];rating='RESEARCH — PAID ECONOMICS UNKNOWN'
        reasons=['Native Canadian organic visibility; city-level traffic not proven.',
                 'Job margin, qualified-lead rate and paid acquisition ROI remain UNKNOWN.',
                 'No historical conversion proves a profitable campaign.']
        if service=='Security cameras':reasons+=['Owner acquisition priority; commercial/consumer intent must be separated.','Related business camera estimates vary sharply; do not broaden to product shopping.']
        if service=='AI loss prevention':reasons+=['Retail/pharmacy fit supports education and targeted outreach; urgency and savings not invented.']
        organic={'impressions':impressions if read.get('state')=='WORKING' else None,
                 'clicks':sum(r.get('clicks',0) for r in native) if read.get('state')=='WORKING' else None,
                 'position':sum(r.get('position',0)*r.get('impressions',0) for r in native)/impressions if impressions else None,
                 'window':[read.get('date_from'),read.get('date_to')],'country':'CANADA','coverage':'Returned query/page/country rows, not total search demand',
                 'query_samples':[{'query':r['keys'][0],'page':r['keys'][1],'impressions':r['impressions'],'clicks':r['clicks'],'position':r['position'],
                                  'sample_confidence':'TENTATIVE' if r['impressions']<10 else 'MODERATE' if r['impressions']<100 else 'STRONG'} for r in sorted(native,key=lambda r:-r['impressions'])[:10]]}
        if impressions>=30 and organic['position'] is not None and organic['position']<=5:
            channels=['SEO','GOOGLE ADS ONLY FOR INCREMENTAL COVERAGE']
            reasons.append('Strong returned organic visibility: validate incremental paid value rather than duplicating existing coverage.')
        opportunities.append({'service':service,'rating':rating,'channels':channels,'geography':'Montréal / Laval / bounded Rive-Nord',
            'economics':available,'cpc_range':{'low':min(cpc) if cpc else None,'high':max(cpc) if cpc else None,'currency':'CAD','basis':'Québec estimates; not actual or Montréal-specific CPC'},
            'organic':organic,'landing_pages':pages,'landing_readiness':readiness,
            'confidence':'MODERATE' if usable and impressions>=10 else 'TENTATIVE',
            'opportunity_quality':'STRATEGIC' if service in {'Security cameras','AI loss prevention'} else 'COMMERCIAL HYPOTHESIS',
            'reasons':reasons,'recurring_potential':'Maintenance/managed support where scoped and contracted; revenue/margin UNKNOWN',
            'market_references':[r.get('id') or digest([r.get('service'),r.get('icp'),r.get('geography')]) for r in inputs.get('market_opportunities',[]) if r.get('service')==service],
            'trigger_references':[r.get('trigger_id') for r in inputs.get('triggers',[]) if service in str(r.get('service_fit',{}))][:10]})
    return {'schema':1,'at':now.isoformat(),'inventory':summary,'opportunities':opportunities,
        'economics_state':econ_state,'economics_provider_calls':0,
        'ga4':{'state':inputs.get('google',{}).get('reads',{}).get('ga4_collection',{}).get('state','UNKNOWN'),
               'window':[inputs.get('google',{}).get('reads',{}).get('ga4_collection',{}).get(k) for k in ('date_from','date_to')],
               'limitation':'Restored collection and diagnostic traffic; TEST reception is not natural business performance. No paid lead rate established.'},
        'business_context':inputs.get('business_context',{}),
        'natural_lead':'OWNER-CONFIRMED UNRELATED FR INQUIRY; UNATTRIBUTED / UNKNOWN Ads, keyword, gclid, qualification and revenue',
        'authority':'READ / ANALYZE / PREPARE ONLY','provider_writes':0,'execution_authorized':False}


def measurement(service,language):
    return {'metrics':[{'metric':'deterministically attributed qualified inquiries','source_reference':'Immutable intake + owner CRM qualification + original click/consent evidence',
        'unit':'count','baseline_value':None,'baseline_status':'UNKNOWN','baseline_sample':None,
        'baseline_window':None,'cohort_geography_language':service+' / '+language+' / approved local pilot'}],
        'window':'28 days from separately approved activation; review at day 7 and day 14; no activation now',
        'minimum_usable_sample':'30 relevant paid clicks for intent diagnosis; 3 independently qualified inquiries for a directional lead-quality decision. Neither proves statistical ROI.',
        'guardrails':['Separate owner-approved total spend cap; daily delivery may reach twice the average budget.',
                      'Review/pause manually if >20% reviewed paid search-term spend is clearly irrelevant.',
                      'Stop/review on broken inquiry path, privacy failure, disputed consent or attribution; no automatic campaign writer.',
                      'No duplicate outreach, TEST conversions or fabricated financial values.'],
        'success':'At least 3 owner-qualified, deterministically campaign-linked genuine inquiries within the approved cap, no guardrail breach; continue only after economic review.',
        'neutral':'Usable click sample and relevant intent, but qualified outcomes unchanged or too sparse; no inferred revenue.',
        'regression':'Any guardrail breach or predominantly irrelevant paid intent; recommend manual pause and retain evidence.',
        'insufficient_data':'Fewer than required samples, missing click/consent/qualification linkage, or only diagnostic TEST events; no CPA/ROAS claim.',
        'test_exclusion':'Exclude known provider-backed TEST receipts and operator diagnostic sessions from business KPIs. GA4 Testing filters label rather than exclude.',
        'attribution_limits':'Browser consent/session dedupe differs from canonical Mail identity. No global cross-browser exactly-once, deterministic historical Ads attribution or margin claim.'}


def proposal(kind,service,language,evidences,now,detail,*,problem,change,confidence='MODERATE',risk=None):
    pid=digest(['optimization','6808491878',kind,service,language]);at=now.isoformat()
    return {'schema':1,'type':'optibrain.optimization_proposal','proposal_id':pid,'revision':1,
        'proposal_type':kind,'target_system':'GOOGLE_ADS' if kind!='LANDING_PAGE' else 'WEBSITE',
        'target_object':{'system':'GOOGLE_ADS' if kind!='LANDING_PAGE' else 'WEBSITE','entity_type':'CAMPAIGN_DRAFT' if kind=='GOOGLE_ADS_CAMPAIGN' else kind,'entity_id':pid},
        'target_url_or_record':'https://ads.google.com/aw/overview?ocid=6808491878' if kind!='LANDING_PAGE' else detail['target_url'],
        'created_at':at,'updated_at':at,'source_evidence':evidences,'business_problem':problem,
        'why_now':'Phase32 native technical telemetry is proven; no active campaign currently serves. Launch remains a separate decision.',
        'recommended_change':change,'expected_benefit':'More relevant commercial inquiries; qualified-lead rate, revenue and profitability UNKNOWN.',
        'risk':risk or 'Sparse local demand, uncertain CPC, unproven genuine conversion lineage and no current execution authority.',
        'confidence':confidence,'data_quality':'Native inventory + dated Québec estimates; separate organic visibility, diagnostic TEST and unproven natural paid outcomes.',
        'affected_files_or_records':[service+' / '+language+' / new reviewable draft only'],
        'preview_location':'/v1/operator/acquisition?proposal_id='+pid,
        'owner_action_required':'Review exact preview; separate explicit execution authority required.',
        'authority_class':'C','status':'PREVIEW_READY',
        'approved_by':None,'approved_at':None,'execution_reference':None,'deployed_at':None,
        'measurement_plan':measurement(service,language),'measurement_start':None,'measurement_end':None,
        'result':None,'learning':None,'rollback_reference':'Future owner-controlled deactivate/pause exact new campaign; preserve removed history. Website preview retains exact production rollback SHA.'}


def campaign_preview(service,language,opportunity):
    fr=language=='FR';camera=service=='Security cameras'
    keywords=(['installation caméras commerciales','caméra surveillance commerciale','installation caméra entreprise'] if fr else
              ['commercial security cameras','commercial camera installation','warehouse camera installation']) if camera else (
              ['cablage structuré','câblage réseau entreprise','installation cat6 entreprise'] if fr else ['structured cabling','commercial network cabling','cat6 installation business'])
    if camera:
        headlines=(['Caméras pour entreprises','Installation de caméras IP','Sécurité de votre commerce','Caméras pour entrepôts','Demandez une soumission','Montréal et Laval','Une couverture adaptée','Opticable'] if fr else
                   ['Commercial Security Cameras','IP Camera Installation','Cameras for Your Business','Warehouse Camera Coverage','Request a Quote','Montréal and Laval','Plan Your Camera Coverage','Opticable'])
        descriptions=(['Planifiez la couverture caméra de votre commerce ou entrepôt. Demandez une soumission.',
                       'Installation de caméras IP pour entreprises. Discutez de votre bâtiment avec Opticable.',
                       'Entrées, zones de travail et stockage : précisez vos besoins de surveillance.',
                       'Un projet à Montréal ou Laval? Appelez-nous ou remplissez notre formulaire.'] if fr else
                      ['Plan camera coverage for your business or warehouse. Request a quote from Opticable.',
                       'Commercial IP camera installation. Discuss your building and priorities with our team.',
                       'Entrances, work areas and storage: define the coverage your site needs.',
                       'A project in Montréal or Laval? Call us or use our quote form.'])
        icp='Commercial property managers, warehouse operators, retail and institutional facilities'
    else:
        headlines=(['Câblage structuré commercial','Câblage Cat6 et Cat6A','Réseau pour votre entreprise','Bureaux et entrepôts','Demandez une soumission','Montréal et Laval','Planifiez votre câblage','Opticable'] if fr else
                   ['Commercial Structured Cabling','Cat6 and Cat6A Installation','Cabling for Your Business','Offices and Warehouses','Request a Quote','Montréal and Laval','Plan Your Network Cabling','Opticable'])
        descriptions=(['Planifiez le câblage réseau de vos bureaux ou de votre entrepôt avec Opticable.',
                       'Câblage structuré Cat6 et Cat6A pour entreprises. Demandez une soumission.',
                       'Ajout de postes ou déménagement? Précisez vos besoins réseau et votre échéancier.',
                       'Un projet à Montréal ou Laval? Discutez du câblage et de la connectivité de votre site.'] if fr else
                      ['Plan network cabling for your office or warehouse with Opticable.',
                       'Commercial Cat6 and Cat6A structured cabling. Request a quote for your site.',
                       'Adding workstations or moving? Tell us your network needs and project timing.',
                       'A Montréal or Laval project? Discuss the cabling and connectivity your site requires.'])
        icp='Commercial offices, warehouse operators, general contractors and electrical partners'
    assert all(len(h)<=30 for h in headlines) and all(len(d)<=90 for d in descriptions)
    used=[]
    for term in keywords:
        match=next((r for r in opportunity['economics'] if normalized(r['query'])==normalized(term) and r['language']==language),None)
        used.append({'text':term,'match_types':['EXACT','PHRASE'],'basis':'CACHED PROVIDER KEYWORD' if match else 'SERVICE-INTENT HYPOTHESIS — NO NATIVE VOLUME',
                     'monthly_volume':match['market_volume'] if match and not match['stale'] else None,
                     'estimated_cpc':match['cpc'] if match and not match['stale'] else None,
                     'competition':match['paid_competition'] if match and not match['stale'] else None})
    cpc=next((r['estimated_cpc'] for r in used if r['estimated_cpc'] is not None),None)
    daily=15 if camera else 10
    return {'campaign_name':('FR' if fr else 'EN')+' | '+('Commercial cameras' if camera else 'Structured cabling')+' | Montréal-Laval | PROPOSAL',
        'service':service,'icp':icp,'language':language,'objective':'Genuine commercial quote inquiries; qualification and recurring opportunity assessed separately',
        'type':'SEARCH','status':'PREVIEW_READY','networks':{'google_search':True,'search_partners':False,'display':False},
        'locations':{'include':['Montréal','Laval'],'optional_owner_review':['explicit serviced Rive-Nord municipalities'],
                     'presence':'PRESENCE','exclude':'Outside approved serviced areas; no Québec-wide launch','resource_ids':'Revalidate exact native location IDs before any future paused creation'},
        'ad_groups':[{'name':'Commercial installation','keywords':used,'responsive_search_ad':{'headlines':headlines,'descriptions':descriptions,
                        'cta':'Demandez une soumission' if fr else 'Request a quote'},'landing_page':opportunity['landing_pages'][language]}],
        'negatives':NEGATIVES,'broad_match':False,'broad_reason':'No meaningful qualified-conversion volume; exact/phrase do not eliminate close-variant risk.',
        'budget':{'currency':'CAD','average_daily':daily,'monthly_30_4_approx':daily*30.4,'pilot_28_day_average':daily*28,
                  'suggested_owner_total_cap':500 if camera else 350,'not_enforced':'Shadow suggestion only; average daily budget is not a hard daily or total cap.',
                  'daily_overdelivery_risk':daily*2,'shared_portfolio_limit':'Run one language/service pilot first. Do not add these independent proposals into simultaneous spend.'},
        'bidding':{'recommendation':'MAXIMIZE_CLICKS with separately owner-reviewed CPC ceiling; alternatively manual CPC if available for exact pilot configuration',
                   'suggested_cpc_ceiling':7 if camera else 5,'basis':'Risk limit, not proven clearing price; can underserve competitive auctions.',
                   'conversion_optimization':'No Target CPA/ROAS or broad/Performance Max launch based on diagnostic tests.'},
        'expected_economics':{'cached_keyword_cpc':cpc,'currency':'CAD','scope':'Québec; city, language and close variants not interchangeable',
            'illustrative_28_day_clicks':round(daily*28/cpc,1) if cpc and cpc>0 else None,
            'sensitivity_cpc_range':[5,15] if camera else [3,10],
            'sensitivity_click_range':[round(daily*28/(15 if camera else 10),1),round(daily*28/(5 if camera else 3),1)],
            'click_forecast':'Spend/CPC arithmetic only. Demand/auction/consent may yield fewer clicks; no guaranteed leads.',
            'qualified_lead_rate':None,'job_margin':None,'CPA':None,'ROAS':None},
        'landing_readiness':opportunity['landing_readiness'][language],
        'launch_state':'LANDING PAGE REVIEW REQUIRED' if opportunity['landing_readiness'][language] in {'NOT VERIFIED','LANDING PAGE REVIEW REQUIRED','PREVIEW PAGE REQUIRED'} else 'TRACKING / AUTHORITY REVIEW REQUIRED',
        'conversion_hierarchy':['acknowledged native form success (diagnostic technical proof; exclude TEST)',
                                'genuine CRM Lead with deterministic click/consent linkage',
                                'owner-qualified Lead','accepted Estimate','paid Invoice'],
        'conversion_goal_proposal':'Review legacy Merci primary; native generate_lead informational until separately approved pilot measurement design. Three validated offline destinations remain secondary and OFF.',
        'launch_dependencies':['Exact owner-approved paused-campaign graduation and separate activation authority',
                               'Approve goal/legacy-tag/test-isolation plan; no change made here',
                               'Confirm manual English quote handling; English real customer automation remains disabled',
                               'Confirm local coverage, current landing preview and bounded spend/stop procedure'],
        'execution_authorized':False}


def build_bundle(inputs,now):
    intelligence=assess(inputs,now);at=inputs.get('ads',{}).get('at')
    native=evidence('Google Ads API','private:phase33/ads-inventory',at,now=now,limitations=['Historical removed campaigns; no recent paid activity. Search terms are privacy-limited.'])
    qa=evidence('Phase32 owner/native intake proof','phase32-evidence/final-report.json',inputs.get('phase32_at'),truth='OWNER_CONFIRMED',days=30,
                limitations=['PROVIDER-PROVEN TEST; genuine attribution, qualification and revenue unproven.'])
    economics=inputs.get('keyword_economics',{})
    ev=evidence('Google Keyword Planner via Windsor','private:acquisition-intelligence/keyword-economics.json',economics.get('retrieved_at'),truth='ESTIMATED',days=30,
                limitations=['Québec estimates; not Montréal demand or actual CPC. Unknown fields not fabricated. Trial continuity external.'])
    if intelligence['economics_state']!='CACHED — CURRENT':ev['freshness']='STALE' if intelligence['economics_state']=='STALE' else 'UNKNOWN';ev['confidence']='INSUFFICIENT'
    proposals=[];assets=[];priorities=[]
    for service in ('Security cameras','Structured cabling'):
        op=next(r for r in intelligence['opportunities'] if r['service']==service)
        for language in ('FR','EN'):
            detail=campaign_preview(service,language,op)
            record=proposal('GOOGLE_ADS_CAMPAIGN',service,language,[native,ev,qa],now,detail,
                problem='No active paid acquisition; historical generic/product traffic did not establish meaningful conversion outcomes.',
                change='Review the complete conservative '+language+' '+service+' pilot; launch one bounded test only after separate authority.',
                confidence='MODERATE' if any(r['language']==language and r['cpc'] is not None and not r['stale'] for r in op['economics']) else 'TENTATIVE')
            proposals.append({'record':record,'detail':detail})
            for index,hook in enumerate(detail['ad_groups'][0]['responsive_search_ad']['headlines'][:3]):
                asset={'schema':1,'type':'optibrain.optimization_asset','asset_id':digest([record['proposal_id'],hook]),
                    'asset_type':'HOOK','proposal_id':record['proposal_id'],'service':service,'icp':detail['icp'],
                    'geography':'Montréal / Laval','language':language,'channel':'SEARCH_AD / WEBSITE / CONTENT',
                    'source_evidence':[native,qa],'provider':'OptiBrain deterministic draft','brief_or_prompt_reference':record['preview_location'],
                    'draft_or_asset_reference':record['preview_location']+'#hook-'+str(index),'rights_source_status':'Original draft grounded in current service scope',
                    'usage':'DRAFT ONLY; not published or enrolled','illustrative':False,'performance_evidence':[],'created_at':now.isoformat()}
                assets.append({'record':asset,'detail':{'text':hook,'keyword_intent':'commercial installation'}})
    detail={'actions':['Review/retire page-visit-only Merci as a primary success goal before future pilot; preserve all history.',
                       'Review removed campaign custom-goal references that no longer resolve in current custom-goal inventory.',
                       'Keep all removed campaigns removed; do not revive Performance Max or obsolete seasonal offers.',
                       'Apply no negatives now; review exact consumer/product search terms and exceptions.'],
            'negative_candidates':intelligence['inventory']['negative_candidates'],'goals':rows(inputs.get('ads',{}),'campaign_goals'),
            'goal_config':rows(inputs.get('ads',{}),'goal_config'),'customer_goals':rows(inputs.get('ads',{}),'customer_goals'),
            'current_actions':intelligence['inventory']['conversion_actions'],'provider_writes':0}
    proposals.append({'record':proposal('GOOGLE_ADS_CLEANUP','Account measurement','FR/EN',[native,qa],now,detail,
        problem='Enabled primary page-visit goal can misrepresent successful inquiries; removed campaign goal references require review.',
        change='Review the frozen conversion-goal and negative-candidate inventory. Approve a separate exact change set before a future pilot.'),'detail':detail})
    detail={'measurement_id':'G-ZEQXVSZWRL','property':'530093120','filters':'Internal/Developer Exclude/Testing retained; labels do not remove TEST reporting.',
            'proposed_steps':['Approve narrowly scoped TEST exclusion decision separately; do not activate filters here.',
                              'Preserve consented gclid/gbraid/wbraid capture when genuinely supplied; never fabricate IDs.',
                              'Evaluate genuine form success → CRM qualification association before any outcome-based bidding.',
                              'Three existing secondary offline destinations stay READY but uploads OFF. First eligible natural export needs separate explicit graduation.'],
            'real_lead':'UNATTRIBUTED; not evidence Ads converted','execution_authorized':False}
    proposals.append({'record':proposal('MEASUREMENT','Paid acquisition outcomes','FR/EN',[native,qa],now,detail,
        problem='Diagnostic native form reception proves implementation, not genuine Ads-to-qualified-lead outcomes.',
        change='Review pilot tracking and TEST isolation before activation; retain browser/canonical identity and consent boundaries.'),'detail':detail})
    for language in ('FR','EN'):
        page=next(r for r in intelligence['opportunities'] if r['service']=='Security cameras')['landing_pages'][language]
        detail={'target_url':page,'preview_reference':'phase33-evidence/previews/cameras-'+language.lower()+'.html',
            'headline':'Caméras IP pour commerces et entrepôts' if language=='FR' else 'IP camera coverage for businesses and warehouses',
            'sections':['Define entrances, work areas and storage coverage without invented guarantees.',
                        'Explain site review, installation scope, network/storage constraints and optional maintenance.',
                        'Quote CTA preserves existing FR/EN contact route and native attribution.'],
            'unchanged':'Existing URL, canonical/hreflang, Forms, consent, tracking and service portfolio.',
            'deployment':'PREVIEW ONLY — owner approval and normal website release required','production_rollback_sha':inputs.get('website_sha')}
        detail['draft_section']={
            'headline':detail['headline'],
            'intro':('Définissez les zones à surveiller avant de choisir vos caméras. Opticable installe des systèmes de caméras IP pour les bâtiments commerciaux à Montréal, Laval et sur la Rive-Nord.' if language=='FR' else
                     'Define the areas you need to monitor before choosing cameras. Opticable installs IP camera systems for commercial buildings in Montréal, Laval and the North Shore.'),
            'scope_heading':'Préparez une soumission adaptée à votre site' if language=='FR' else 'Prepare a quote around your site',
            'scope':(['Indiquez les entrées, les zones de travail et les espaces de stockage à couvrir.',
                      'Précisez votre réseau actuel, les besoins d’enregistrement et les accès au bâtiment.',
                      'Discutez de l’installation, de la configuration et des besoins de maintenance.'] if language=='FR' else
                     ['Identify entrances, work areas and storage areas that need coverage.',
                      'Describe your existing network, recording requirements and building access.',
                      'Discuss installation, configuration and ongoing maintenance requirements.']),
            'faq':[{'question':'Faut-il remplacer toutes les caméras?' if language=='FR' else 'Do all existing cameras need replacing?',
                    'answer':'La compatibilité doit être vérifiée selon les caméras, le réseau et le système d’enregistrement existants.' if language=='FR' else 'Compatibility needs to be checked against your existing cameras, network and recording system.'},
                   {'question':'Combien de caméras faut-il?' if language=='FR' else 'How many cameras does the site need?',
                    'answer':'Le nombre dépend des zones à couvrir, des angles de vue et des conditions du bâtiment. La soumission précise le périmètre proposé.' if language=='FR' else 'The number depends on coverage areas, viewing angles and building conditions. The quote defines the proposed scope.'}],
            'cta':'Demander une soumission' if language=='FR' else 'Request a quote',
            'cta_url':'https://opticable.ca/'+language.lower()+'/contact/',
            'note':'DRAFT / PREVIEW — no publication, tracking, submission or fabricated project result.'}
        proposals.append({'record':proposal('LANDING_PAGE','Security cameras',language,[qa],now,detail,
            problem='Align paid commercial intent with explicit audience, installation scope and existing native quote path.',
            change='Review the actual camera-page section preview before a pilot; retain completed Phase32 pages.'),'detail':detail})
    # AI produces useful shared hooks without forcing an unsupported search campaign.
    for language,hook in [('FR','Repérez les gestes suspects'),('EN','Review suspicious gestures')]:
        assets.append({'record':{'schema':1,'type':'optibrain.optimization_asset','asset_id':digest(['AI',language,hook]),
            'asset_type':'HOOK','proposal_id':None,'service':'AI loss prevention','icp':'Pharmacies and retail operators',
            'geography':'Greater Montréal','language':language,'channel':'EDUCATIONAL CONTENT / OWNER-REVIEW OUTBOUND',
            'source_evidence':[qa],'provider':'OptiBrain draft','brief_or_prompt_reference':'phase32-camera-ai-content-pack',
            'draft_or_asset_reference':'phase33-evidence/previews/creative-brief.md','rights_source_status':'Original educational draft; no proven savings',
            'usage':'DRAFT ONLY; support human review, never accusation or guaranteed detection','illustrative':True,
            'performance_evidence':[],'created_at':now.isoformat()},'detail':{'text':hook,'limitation':'Human verification remains necessary; no automatic outreach or publication.'}})
    for item in proposals:
        r=item['record'];p={'schema':1,'type':'optibrain.business_priority','priority_id':digest(['priority',r['proposal_id']]),
            'domain':'ADS_INTELLIGENCE','targets':[r['target_object']],'proposal_id':r['proposal_id'],
            'what':r['recommended_change'],'why':r['business_problem'],'business_impact':r['expected_benefit'],
            'urgency':'HIGH' if r['proposal_type'] in {'MEASUREMENT','GOOGLE_ADS_CLEANUP'} else 'MEDIUM',
            'due_at':None,'confidence':r['confidence'],'data_quality':r['data_quality'],'source_evidence':r['source_evidence'],
            'priority_reasons':['Owner acquisition priority' if item['detail'].get('service')=='Security cameras' else 'Concrete preview and explicit data gaps',
                                'No active campaigns; existing primary tracking requires review'],
            'dependency':'Tracking, landing-page and spend/authority decisions before activation','blocker':None,
            'actor':'OWNER','can_prepare':True,'owner_approval_required':True,'status':'OWNER_REVIEW',
            'created_at':now.isoformat(),'updated_at':now.isoformat(),'next_action':'Review / request research / reject exact proposal; execution unavailable.'}
        priorities.append({'record':p,'detail':{}})
    return {'intelligence':intelligence,'proposals':proposals,'assets':assets,'priorities':priorities,
            'origin':'MANUAL','effect_class':'NONE','provider_writes':0}


def render_proposal(item):
    import json
    h=lambda v:escape(str(v),quote=True)
    r=item['record'];pid=r['proposal_id']
    html="<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Optimization preview</title><style>body{font:16px system-ui;max-width:1000px;margin:auto;padding:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}button{padding:12px}</style><body>"
    html+="<a href='/v1/operator/acquisition'>Acquisition</a><h1>"+h(r['proposal_type'])+'</h1>'
    html+=f"<p>{h(item.get('effective_status') or r['status'])} · revision {r['revision']} · {h(r['confidence'])} evidence · owner production approval required</p>"
    for key in ('business_problem','why_now','recommended_change','expected_benefit','risk','data_quality'):
        html+=f"<h2>{h(key.replace('_',' ').title())}</h2><p>{h(r[key])}</p>"
    detail=item['detail']
    if detail.get('ad_groups'):
        html+='<h2>Ad preview</h2>'
        for group in detail['ad_groups']:
            ad=group['responsive_search_ad']
            html+='<article><h3>'+h(' | '.join(ad['headlines'][:3]))+'</h3><p>'+h(ad['descriptions'][0])+'</p><p>'+h(group['landing_page'])+'</p></article>'
        html+='<p>Suggested average budget: '+h(detail['budget']['average_daily'])+' CAD/day. '+h(detail['budget']['not_enforced'])+'</p>'
    if detail.get('draft_section'):
        draft=detail['draft_section'];html+='<section><h2>Actual landing-section draft</h2><h3>'+h(draft['headline'])+'</h3><p>'+h(draft['intro'])+'</p><h4>'+h(draft['scope_heading'])+'</h4><ul>'
        html+=''.join('<li>'+h(v)+'</li>' for v in draft['scope'])+'</ul>'
        for faq in draft['faq']:html+='<h4>'+h(faq['question'])+'</h4><p>'+h(faq['answer'])+'</p>'
        html+='<p>'+h(draft['cta'])+' → '+h(draft['cta_url'])+'</p><small>'+h(draft['note'])+'</small></section>'
    html+='<h2>Complete preview</h2><pre>'+h(json.dumps(item['detail'],indent=2,ensure_ascii=False))+'</pre>'
    html+='<h2>Evidence</h2><pre>'+h(json.dumps(r['source_evidence'],indent=2,ensure_ascii=False))+'</pre>'
    html+='<h2>Frozen measurement plan</h2><pre>'+h(json.dumps(r['measurement_plan'],indent=2,ensure_ascii=False))+'</pre>'
    html+='<p>Read / prepare only. Review does not create Ads, approve execution, publish a page or grant a writer.</p>'
    html+=f"<form method='post' action='/v1/operator/acquisition/proposal/{pid}/review'><input type='hidden' name='revision' value='{r['revision']}'><input type='hidden' name='payload_hash' value='{h(item['payload_hash'])}'><select name='choice'><option>REVIEWED</option><option>RESEARCH</option><option>REJECT</option></select><button>Record local review</button></form></body></html>"
    return html


def render_summary(summary):
    h=lambda v:escape(str(v if v is not None else 'UNKNOWN'),quote=True)
    html='<section><h2>Ads intelligence · owner review</h2><p>Read / analyze / prepare only. No campaign execution or conversion export authority.</p>'
    html+=f"<p>{h(summary.get('proposal_count'))} concrete previews · {h(summary.get('hook_count'))} shared hooks · economics {h(summary.get('economics_state'))}</p>"
    html+=f"<p>Collection: {h(summary.get('collection_origin'))} · preparation: {h(summary.get('preparation_origin'))} · observed {h(summary.get('at'))}. No Ads business effect.</p>"
    for p in summary.get('proposals',[]):
        html+=f"<article><a href='/v1/operator/acquisition?proposal_id={h(p['proposal_id'])}'>{h(p['title'])}</a><p>{h(p['status'])} · confidence {h(p['confidence'])} · cost {h(p.get('budget'))} CAD/day suggested</p><small>{h(p['why'])}</small></article>"
    return html+'</section>'
