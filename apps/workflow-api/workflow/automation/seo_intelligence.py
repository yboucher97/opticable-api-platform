"""Live HTML inventory and explainable acquisition content decisions."""
from collections import defaultdict
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit,urlunsplit
import hashlib,json,re
from .acquisition_intelligence import SERVICES,service_for,intent_for,language_for,market_priority,number
from .acquisition_store import digest,normalized
from .evidence_quality import geography_evidence,search_evidence,fact

OWN_HOSTS={'opticable.ca','ai.opticable.ca','connect.opticable.ca'}


def own_url(url):
    try:
        p=urlsplit(str(url))
        return p.scheme=='https' and p.hostname in OWN_HOSTS and not p.username and not p.password and p.port in (None,443)
    except ValueError:return False


def clean_url(url):
    p=urlsplit(url);return urlunsplit((p.scheme,p.netloc,p.path,'',''))


class PageParser(HTMLParser):
    def __init__(self,url):
        super().__init__(convert_charrefs=True);self.url=url;self.title=[];self.description=[];self.h1=[];self.h2=[]
        self.canonicals=[];self.hreflang={};self.robots=[];self.links=[];self.scripts=[];self.forms=[];self.lang='UNKNOWN'
        self.capture=None;self.skip=0;self.text=[];self.main_text=[];self.main=0;self.ld=None;self.structured=[];self.structured_errors=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='html':self.lang=a.get('lang','UNKNOWN')
        if tag=='main':self.main+=1
        if tag=='meta':
            name=a.get('name','').casefold()
            if name=='description':self.description.append(a.get('content',''))
            if name in {'robots','googlebot'}:self.robots.append(a.get('content',''))
        if tag=='link':
            rel=a.get('rel','').casefold().split();href=urljoin(self.url,a.get('href',''))
            if 'canonical' in rel:self.canonicals.append(href)
            if 'alternate' in rel and a.get('hreflang'):self.hreflang[a['hreflang']]=href
        if tag in ('title','h1','h2'):self.capture={'tag':tag,'parts':[]}
        if tag=='a' and a.get('href'):self.links.append(urljoin(self.url,a['href']))
        if tag=='form':self.forms.append({'action':urljoin(self.url,a.get('action','')),'method':a.get('method','GET').upper()})
        if tag=='script':
            if a.get('src'):self.scripts.append(urljoin(self.url,a['src']))
            if a.get('type','').casefold()=='application/ld+json':self.ld=[]
        if tag in ('script','style','svg'):self.skip+=1
    def handle_endtag(self,tag):
        if self.capture and self.capture['tag']==tag:
            text=' '.join(' '.join(self.capture['parts']).split())
            getattr(self,tag).append(text);self.capture=None
        if tag=='script' and self.ld is not None:
            try:self.structured.append(json.loads(''.join(self.ld)))
            except (ValueError,TypeError):self.structured_errors+=1
            self.ld=None
        if tag in ('script','style','svg'):self.skip=max(0,self.skip-1)
        if tag=='main':self.main=max(0,self.main-1)
    def handle_data(self,data):
        if self.ld is not None:self.ld.append(data)
        if self.skip:return
        if self.capture:self.capture['parts'].append(data)
        if data.strip():
            self.text.append(data)
            if self.main:self.main_text.append(data)


def page_inventory(raw):
    url=raw['url'];p=PageParser(raw.get('final_url') or url);p.feed(raw.get('html',''))
    text=' '.join(' '.join(p.main_text or p.text).split());base=urlsplit(url)
    language=p.lang.split('-')[0].upper() if p.lang!='UNKNOWN' else 'UNKNOWN'
    title=' | '.join(p.title);description=' | '.join(p.description)
    canonical=p.canonicals[0] if len(p.canonicals)==1 else None
    internal=sorted({clean_url(u) for u in p.links if own_url(u)})
    external=sorted({clean_url(u) for u in p.links if urlsplit(u).scheme in ('http','https') and not own_url(u)})
    service=service_for(title+' '+' '.join(p.h1)+' '+base.path)
    kind='SERVICE INDEX' if re.fullmatch('/(fr|en)/services/?',base.path) else 'SERVICE' if '/services/' in base.path else 'INDUSTRY' if '/industr' in base.path or '/secteurs/' in base.path else 'CASE STUDY' if '/case-stud' in base.path or '/etudes-de-cas/' in base.path else 'GUIDE' if '/guides/' in base.path else 'BLOG' if '/blog/' in base.path else 'LOCATION' if '/locations/' in base.path else 'OTHER'
    if kind=='SERVICE INDEX':service=None
    ctas={'quote':any(any(t in u for t in ('contact','quote','soumission','demande','connect.opticable.ca')) for u in p.links),
          'phone':any(u.startswith('tel:') for u in p.links),'email':any(u.startswith('mailto:') for u in p.links)}
    robots=','.join(p.robots+[raw.get('x_robots_tag','')]).casefold()
    crawlable=raw.get('status')==200 and raw.get('robots_allowed') is True and bool(raw.get('html'))
    indexable=crawlable and 'noindex' not in robots
    issues=[]
    if not crawlable:issues.append('HTTP/robots access needs review')
    if not title:issues.append('Missing title')
    if len(p.title)>1:issues.append('Multiple titles')
    if not description:issues.append('Missing meta description')
    if len(p.h1)!=1:issues.append('H1 count '+str(len(p.h1)))
    if len(p.canonicals)!=1:issues.append('Canonical count '+str(len(p.canonicals)))
    if canonical and clean_url(canonical)!=clean_url(raw.get('final_url') or url):issues.append('Canonical points elsewhere — inspect intent')
    if indexable and language in {'FR','EN'} and not p.hreflang:issues.append('No HTML hreflang; inspect sitemap alternates')
    if p.structured_errors:issues.append('Invalid JSON-LD')
    if 'noindex' in robots and raw.get('in_sitemap'):issues.append('Noindex URL in sitemap')
    if len(text.split())<150 and indexable:issues.append('Short visible content — manual relevance review')
    return {'url':url,'final_url':raw.get('final_url') or url,'status':raw.get('status'),'redirect_chain':raw.get('redirect_chain',[]),
        'title':title,'meta_description':description,'h1':p.h1,'h2':p.h2[:30],'canonical':canonical,'language':language,
        'hreflang':p.hreflang,'crawlable':crawlable,'indexable_candidate':indexable,'indexed':None,'robots':robots,
        'in_sitemap':raw.get('in_sitemap',False),'sitemap_lastmod':raw.get('lastmod'),'structured_data':p.structured,
        'internal_links':internal[:300],'external_links':external[:100],'page_type':kind,'service':service,'geography':'UNKNOWN','icp':'UNKNOWN',
        'target_query':None,'cta':ctas,'forms':p.forms,'instrumentation':{'script_sources':p.scripts,'ga4_explicit':any('googletagmanager.com/gtag/js?id=G-' in u for u in p.scripts),'gtm':any('googletagmanager.com/gtm.js' in u for u in p.scripts),'confirmed_intake_event':'NOT PROVEN BY HTML'},
        'word_count':len(text.split()),'content_hash':hashlib.sha256(text.encode()).hexdigest(),'performance':None,'mobile_measurement':None,
        'issues':issues,'retrieved_at':raw.get('retrieved_at'),'content_excerpt':text[:400]}


def technical_audit(pages):
    issues=[{'url':p['url'],'issue':i} for p in pages for i in p['issues']]
    by_url={clean_url(p['url']):p for p in pages};titles=defaultdict(list);hashes=defaultdict(list);incoming=defaultdict(int)
    for p in pages:
        if p['indexable_candidate'] and not p['redirect_chain']:
            titles[(p['language'],p['title'])].append(p['url']);hashes[(p['language'],p['content_hash'])].append(p['url'])
        for u in p['internal_links']:incoming[clean_url(u)]+=1
        for lang,u in p['hreflang'].items():
            other=by_url.get(clean_url(u))
            if not other:continue
            if clean_url(p['url']) not in {clean_url(v) for v in other['hreflang'].values()}:
                issues.append({'url':p['url'],'issue':'Hreflang reciprocity missing in inspected counterpart','counterpart':u})
    for label,groups in [('Duplicate title',titles),('Duplicate visible text',hashes)]:
        for _,urls in groups.items():
            if len(urls)>1:issues.append({'issue':label,'urls':urls,'status':'REVIEW — NO AUTOMATIC CANONICAL CHANGE'})
    orphans=[p['url'] for p in pages if p['in_sitemap'] and p['indexable_candidate'] and not incoming[clean_url(p['url'])]]
    return {'pages_analyzed':len(pages),'crawlable':sum(p['crawlable'] for p in pages),'indexable_candidates':sum(p['indexable_candidate'] for p in pages),
            'indexed_verified':sum(p.get('indexed') is True for p in pages) or None,'issues':issues,'orphan_candidates':orphans,'orphan_scope':'No incoming link in bounded inspected inventory; not a complete external crawl',
            'page_performance':'UNMEASURED','mobile_performance':'UNMEASURED','source_changes':0}


def content_opportunity(keyword,pages,*,competitors=(),outcomes=None):
    query=keyword['query'];language=keyword.get('language') or language_for(query);service=keyword.get('service') or service_for(query)
    intent=keyword.get('intent') or intent_for(query)
    # Explicit GSC ranking URL is stronger than a guessed page/topic similarity.
    ranked=next((p for p in pages if clean_url(p['url'])==clean_url(keyword.get('page','')) and p['indexable_candidate'] and (p['language']==language or language=='UNKNOWN')),None)
    suitable=[p for p in pages if p['indexable_candidate'] and p['service']==service and p['language']==language and p['page_type'] in {'SERVICE','INDUSTRY','GUIDE'}]
    existing=ranked if ranked and ranked['service']==service and ranked['page_type'] in {'SERVICE','INDUSTRY','GUIDE','CASE STUDY'} else next(iter(sorted(suitable,key=lambda p:p['page_type']!='SERVICE')),None)
    geo=geography_evidence(keyword);sample=search_evidence(keyword)
    target_geo=geo['geography']
    item={'service':service,'intent':intent,'geography':target_geo,'market_volume':keyword.get('market_volume'),
          'observed_search_impressions':keyword.get('impressions'),'cpc':keyword.get('cpc'),'position':keyword.get('position'),
          'addressable_companies':keyword.get('addressable_companies',0),'recurring_potential':service in {'Commercial Wi-Fi','AI loss prevention','Managed network','PTP wireless'},
          'seo_difficulty':keyword.get('seo_difficulty'),'paid_competition':keyword.get('paid_competition'),'contact_coverage':None}
    score=market_priority(item,outcomes=outcomes);pos=number(keyword.get('position'));demand=number(keyword.get('market_volume'))
    if not geo['quebec_recommendation_allowed']:
        decision='OUT OF SCOPE — RESEARCH ONLY';why='Foreign/other-Canada evidence is retained, but excluded from Québec SEO and paid recommendations.'
    elif language=='UNKNOWN' or not service or intent in {'IRRELEVANT','BRANDED'}:
        decision='RESEARCH / HOLD';why='Language, service fit or acquisition relevance is not established.'
    elif intent=='INFORMATIONAL':decision='LOWER PRIORITY EDUCATION';why='Useful education requires business relevance; volume alone is insufficient.'
    elif demand is not None and demand<10 and keyword.get('addressable_companies',0)>=10:
        decision='NO SEO PAGE — OUTBOUND RESEARCH';why='Observed search demand is low; known company market supports shadow research instead.'
    elif existing:
        decision='IMPROVE EXISTING PAGE';why='An indexable page already covers this service/language; strengthen intent and internal links before creating a duplicate.'
        if ranked and existing['url']==ranked['url'] and pos is not None and 8<=pos<=20 and (number(keyword.get('impressions')) or 0)>0:
            bonus=round(12*sample['position_support'],1)
            score['score']=min(100,score['score']+bonus);score['components']['existing_near_page_one']=bonus
            why=sample['position_note']+'. Improve the existing relevant page; validate demand before a major investment.'
    else:
        decision='NEW PAGE CANDIDATE';why='No suitable inspected service/language page covers this commercial need. Confirm unique expertise and demand before publication.'
    corroborated=bool((demand is not None and demand>=100) or keyword.get('verified_independent_signals'))
    if sample['class'] in {'TENTATIVE EVIDENCE','INSUFFICIENT EVIDENCE'} and not corroborated:score['score']=min(69,score['score'])
    service_slug=re.sub('[^a-z0-9]+','-',normalized(service or query)).strip('-')
    existing_url=existing['url'] if existing else None
    return {'id':digest([normalized(query),language,service,keyword.get('geography','UNKNOWN')]),'title':query,'language':language,'service':service,
        'icp':keyword.get('icp','Business buyers — refine from evidence'),'geography':item['geography'],
        'geography_basis':geo['basis'],'geography_evidence':geo,'evidence_confidence':sample['class'],'search_sample':sample,'target_query':query,'intent':intent,
        'decision':decision,'why':why,'why_now':'Observed search visibility / verified market evidence; not proven ROI.',
        'score':score['score'],'priority':'HIGH' if score['score']>=70 else 'MEDIUM' if score['score']>=40 else 'LOW','basis':score['basis'],'score_components':score['components'],'missing_data':score['missing_data'],
        'existing_page':existing_url,'recommended_url':existing_url or '/'+language.lower()+'/services/'+service_slug+'/',
        'content_type':'Existing service improvement' if existing else 'Service / use-case brief','cta':'Request a site assessment / Estimate',
        'internal_links':[p['url'] for p in suitable[:3]],'ads_use':'Landing-page relevance review only','outbound_use':'Optional evidence resource; existing Apollo ownership remains unchanged',
        'selected_page_position':pos if ranked and existing and existing['url']==ranked['url'] else None,
        'evidence':{**{k:keyword.get(k) for k in ('page','impressions','clicks','ctr','position','market_volume','cpc','source','date_from','date_to','observed_at')},
            'metric_scope':'Observed query-page pair, not a ranking for a different chosen page or total market demand'},
        'facts':{k:fact(keyword.get(k),keyword.get('source'), 'ESTIMATE' if k in {'market_volume','cpc','seo_difficulty'} else 'MEASURED FACT') for k in ('impressions','clicks','ctr','position','market_volume','cpc','seo_difficulty')},
        'recommendation_strength':'TENTATIVE — RESEARCH / SMALL IMPROVEMENT' if sample['class'] in {'TENTATIVE EVIDENCE','INSUFFICIENT EVIDENCE'} else 'SUPPORTED — OWNER REVIEW',
        'competitor_gap':{'observed_service_pages':[c['url'] for c in competitors if service in c.get('services',[])][:3],'ranking_gap':'UNMEASURED'},
        'requires_owner_expertise':True,'publication_allowed':False,'paid_changes_allowed':False,'doorway_expansion_allowed':False}


def repurpose(brief):
    return {'topic_id':brief['id'],'source':'Owner-verified project / technical expertise / equipment facts required',
        'assets':[{'type':kind,'purpose':purpose,'state':'BRIEF — NOT PUBLISHED'} for kind,purpose in (
            ('SEO page / case study','Answer the commercial question with evidence'),('GBP project post','Local project proof and service consistency'),
            ('LinkedIn','Technical decision and partner value'),('Facebook / Instagram','Actual installation photos and useful context'),
            ('Short video','Demonstrate the technical decision or installation'),('Sales proof','Reusable asset for owner/Apollo context; no new sends'))],
        'false_claim_guard':'No unverified certifications, client names, results, prices or equipment claims.'}


def build_content(queries,pages,*,competitors=(),market_keywords=()):
    keywords=[{**q,'language':language_for(q['query']),'source':'Native Search Console'} for q in queries]
    keywords+=list(market_keywords)
    candidates=[content_opportunity(q,pages,competitors=competitors) for q in keywords]
    eligible=[r for r in candidates if r['decision'] not in {'RESEARCH / HOLD','OUT OF SCOPE — RESEARCH ONLY','LOWER PRIORITY EDUCATION','NO SEO PAGE — OUTBOUND RESEARCH'}]
    # One brief per existing page or distinct service/language target. No article
    # or doorway-page explosion from multiple variants of a single query.
    grouped={}
    for c in sorted(eligible,key=lambda r:-r['score']):
        key=c['existing_page'] or (c['service'],c['language'])
        if key not in grouped:grouped[key]=c
    queue=sorted(grouped.values(),key=lambda r:(-r['score'],r['id']))[:30]
    paid=[]
    for c in queue:
        if c['intent'] not in {'TRANSACTIONAL','LOCAL SERVICE','COMMERCIAL INVESTIGATION'}:continue
        pos=number(c.get('selected_page_position'));cpc=number(c['evidence'].get('cpc'))
        paid.append({'service':c['service'],'language':c['language'],'keyword':c['target_query'],'cpc':cpc,
            'geography':c['geography'],'geography_evidence':c['geography_evidence'],'evidence_confidence':c['evidence_confidence'],'search_sample':c['search_sample'],
            'campaign_family':c['service']+' / '+c['language'],'landing_page':c['existing_page'],'landing_gap':not bool(c['existing_page']),
            'reason':'Commercial visibility exists; organic position is weak. Coordinate SEO and future paid testing.' if pos is not None and pos>10 else 'Commercial hypothesis; owner validates economics before any campaign.',
            'negative_themes':['employment / salary','residential-only where commercial service is intended','irrelevant generic research'],'changes_allowed':False})
    universe={(normalized(k['query']),k.get('language')):k for k in keywords}
    return {'content_queue':queue,'paid_opportunities':paid,'repurposing':[repurpose(r) for r in queue[:5]],
        'excluded_research':[r for r in candidates if r['decision']=='OUT OF SCOPE — RESEARCH ONLY'],
        'technical_seo':technical_audit(pages),'keyword_universe':{'count':len(universe),
            'languages':{l:sum(k.get('language')==l for k in universe.values()) for l in ('FR','EN','UNKNOWN')},
            'service_families':sorted({service_for(k['query']) for k in keywords if service_for(k['query'])}),
            'intent_counts':{i:sum(intent_for(k['query'])==i for k in universe.values()) for i in ('TRANSACTIONAL','COMMERCIAL INVESTIGATION','LOCAL SERVICE','INFORMATIONAL','BRANDED','IRRELEVANT')}},
        'local_strategy':'Improve real service coverage and proof for Montréal/Laval/Rive-Nord; no near-duplicate city pages. GBP service/category consistency and genuine project assets await owner review.',
        'content_performance_contract':{'stages':['published','indexing','impressions','clicks','ranking','landing sessions','CTA','Lead','qualified Lead','Deal','Estimate','won','Invoice','paid revenue'],
            'missing_is':None,'test_excluded':True,'first_party_precedence':True,'outcome_join':'Exact content/landing attribution → native CRM/Finance lineage; no date/name guessing','conversion_uploads':'EXISTING PHASE25 CONTROL — OFF'},
        'next_actions':[{'title':r['decision']+': '+r['title'],'why':r['why']} for r in queue[:5]]}


def enrich(store,inputs,view,*,now):
    """Persist page/topic/brief evidence, expose only a compact owner projection."""
    raw=inputs.get('website',{});pages=[page_inventory(r) for r in raw.get('pages',[])]
    inspections=inputs.get('market_research',{}).get('reads',{})
    for p in pages:
        for name in ('gsc_inspect_wifi_fr','gsc_inspect_wifi_en'):
            r=inspections.get(name,{});v=r.get('data',{}).get('inspectionResult',{}).get('indexStatusResult',{})
            if r.get('state')=='WORKING' and v.get('userCanonical')==p['url']:
                p['indexed']=v.get('verdict')=='PASS';p['indexing_proof']={'provider':'Search Console URL Inspection','last_crawl':v.get('lastCrawlTime'),'google_canonical':v.get('googleCanonical'),'observed_at':inputs['market_research'].get('at')}
        source=next(r for r in raw['pages'] if r['url']==p['url'])
        sid=store.snapshot('website_'+digest(p['url']),p['url'],source,now)
        normalized_page={k:v for k,v in p.items() if k not in {'structured_data','internal_links','external_links'}}
        store.record('OPTICABLE_PAGE',normalized_page,source='website',native_id=p['url'],url=p['url'],now=now,snapshot=sid,
            observed_at=raw.get('at'),raw={k:v for k,v in source.items() if k!='html'},confidence='LIVE HTML OBSERVED; INDEXED ONLY WHERE NATIVE INSPECTION PROVES IT')
    seeds=[]
    # All required service families can be researched without inventing volume.
    # These independently phrased seeds remain declared hypotheses; observed
    # FR/EN query records take precedence for priority and existing-page choice.
    seed_pairs=[('câblage structuré','structured cabling'),('câblage réseau entreprise','network cabling'),('installation cat6','cat6 installation'),
        ('installation cat6a','cat6a cabling'),('installation fibre optique','fiber installation'),('installation wifi commercial','commercial wifi installation'),
        ('wifi entreprise','enterprise wifi installation'),('installation réseau entreprise','network installation'),('infrastructure réseau','network infrastructure'),
        ('caméra surveillance entreprise','commercial security cameras'),('vidéosurveillance commerciale','commercial cctv'),('contrôle accès immeuble','access control installation'),
        ('intercom immeuble','commercial intercom'),('alarme commerciale','commercial alarm installation'),('liaison sans fil point à point','ptp wireless'),
        ('internet temporaire chantier wifi','temporary construction wifi'),('caméra chantier','construction cameras'),('téléphonie ip entreprise','business ip telephony'),
        ('réseau géré entreprise','managed network'),('support informatique réseau','network support'),('prévention des pertes par intelligence artificielle','ai loss prevention')]
    for fr,en in seed_pairs:
        for language,query in (('FR',fr),('EN',en)):
            seeds.append({'query':query,'language':language,'geography':'Greater Montréal','source':'OWNER SERVICE SCOPE — UNMEASURED SEED',
                          'market_volume':None,'cpc':None,'intent':intent_for(query),'service':service_for(query),'seed_only':True})
    for seed in seeds:
        store.record('KEYWORD',seed,source='owner_service_scope',native_id=digest([seed['query'],seed['language']]),url='https://optibrain.opticable.ca/v1/operator/acquisition',now=now,confidence='DECLARED RESEARCH HYPOTHESIS — NO DEMAND METRIC')
    # Optional native Keyword Planner results are used only if successfully read.
    for name in ('market_keywords_fr','market_keywords_en'):
        r=inspections.get(name,{})
        if r.get('state')!='WORKING':continue
        for result in r.get('data',{}).get('results',[]):
            metrics=result.get('keywordMetrics',{})
            seeds.append({'query':result['text'],'language':'FR' if name.endswith('_fr') else 'EN','geography':'Québec',
                'market_volume':number(metrics.get('avgMonthlySearches')),'cpc':number(metrics.get('averageCpcMicros'))/1e6 if number(metrics.get('averageCpcMicros')) is not None else None,
                'currency':'CAD','source':'Native Keyword Planner historical estimate','intent':intent_for(result['text'])})
    report=build_content(view.get('queries',[]),pages,competitors=view.get('competitors',[]),market_keywords=seeds)
    url='https://optibrain.opticable.ca/v1/operator/acquisition'
    for c in report['content_queue']:
        store.record('CONTENT_TOPIC',c,source='optibrain_content',native_id=c['id'],url=url,now=now,confidence='EXPLAINABLE DERIVED RECOMMENDATION — NOT PROVEN ROI')
    for asset in report['repurposing']:
        store.record('CONTENT_ASSET',asset,source='optibrain_content',native_id=asset['topic_id'],url=url,now=now,confidence='PREPARATION PLAN — NOT PUBLISHED')
    store.source('website','WORKING',now,observed_at=raw.get('at'),reason='Bounded own-site HTML/robots/sitemap inventory; two native URL inspections prove indexing. Performance remains unmeasured.',requests=len(pages))
    planner=all(inspections.get(k,{}).get('state')=='WORKING' for k in ('market_keywords_fr','market_keywords_en'))
    store.source('keyword_planner','WORKING' if planner else 'PLAN LIMITED',now,observed_at=inputs.get('market_research',{}).get('at'),
        reason='Native Quebec FR/EN demand estimates.' if planner else 'Explorer access rejects KeywordPlanIdeaService: DEVELOPER_TOKEN_NOT_APPROVED. Basic/Standard application required; no automatic retry or purchase.',requests=2)
    for name in ('website','keyword_planner'):store.record('SOURCE',{'name':name,'role':'Acquisition observation / research only'},source='optibrain_market',native_id=name,url=url,now=now,confidence='DECLARED SOURCE ROLE')
    report['keyword_universe']['required_keyword_families_evaluated']=21
    report['keyword_universe']['independent_fr_en_seed_families']=21
    report['keyword_universe']['seed_metrics']='UNMEASURED; not presented as volume, CPC or ranking'
    return {**view,**report,**store.summary(now)}
