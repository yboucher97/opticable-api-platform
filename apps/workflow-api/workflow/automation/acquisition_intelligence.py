"""Explainable market decisions; no historic conversion dependency or executor."""
from collections import defaultdict
from html import escape
import math
from zoneinfo import ZoneInfo
from .acquisition_store import digest, normalized
from .evidence_quality import geography_evidence,geo_bucket,search_evidence,fact

# Independent vocabulary, not automatic translation. Unknown language remains
# unknown when words are shared. Seed phrases are hypotheses, never search volume.
SERVICES={
 'Structured cabling':('câblage','cablage','cabling','cat6','cat 6','cat6a'),
 'Fiber installation':('fibre','fiber'),
 'Commercial Wi-Fi':('wifi','wi-fi','wi fi','wireless solutions'),
 'Network infrastructure':('network infrastructure','infrastructure réseau','network installation','installation réseau'),
 'Security cameras':('camera','caméra','cctv','vidéosurveillance','videosurveillance'),
 'Access control':('access control','contrôle d’accès','contrôle d\'accès','controle acces','contrôle accès','controle d acces','contrôle centralisé'),
 'Intercom':('intercom','interphone','intercoms'),
 'Alarm':('alarme','alarm'),
 'PTP wireless':('ptp','point to point','point-to-point','point à point'),
 'Construction Wi-Fi':('construction wifi','chantier wifi','wi-fi chantier','temporary wifi'),
 'Construction cameras':('construction camera','caméra chantier','camera chantier'),
 'IP telephony':('telephony','téléphonie','telephonie','voip'),
 'Managed network':('managed network','réseau géré','reseau gere','managed services'),
 'Network support':('it support','it services','services informatiques','technical support','support informatique','network support'),
 'AI loss prevention':('loss prevention','prévention des pertes','prevention des pertes','veesion','shoplifting detection','détection vol'),
}
SEGMENTS=[
 ('Commercial Wi-Fi','Warehouses / industrial','Laval',True),
 ('Structured cabling','Commercial offices','Montréal',False),
 ('Access control','Property management','Greater Montréal',True),
 ('Security cameras','Property management','Laval',True),
 ('AI loss prevention','Pharmacies','Québec',True),
 ('Managed network','Electricians / partners','Rive-Nord',True),
 ('Construction Wi-Fi','General contractors','Montréal',True),
 ('PTP wireless','Commercial yards','Rive-Nord',True),
 ('Fiber installation','Developers','Montréal',False),
 ('Intercom','Multi-residential','Greater Montréal',True),
 ('Structured cabling','Warehouses / industrial','Laval',False),
 ('Network infrastructure','Commercial offices','Greater Montréal',True),
 ('Security cameras','Public facilities','Montréal',True),
 ('AI loss prevention','Retail / dépanneurs','Greater Montréal',True),
 ('Network support','Seniors residences','Québec City',True),
]


def service_for(text):
    text=normalized(text)
    # More specific services take precedence over shared camera/Wi-Fi tokens.
    for name in ('AI loss prevention','Construction Wi-Fi','Construction cameras','PTP wireless','Managed network','Fiber installation'):
        if any(t in text for t in SERVICES[name]):return name
    for name,tokens in SERVICES.items():
        if any(t in text for t in tokens):return name
    return None


def language_for(text):
    text=normalized(text)
    if any(t in text for t in ('câbl','cablage','réseau','reseau','caméra','vidéo','controle','contrôle','chantier','pertes','entreprise','installation wifi','téléph','alarme','immeuble')):return 'FR'
    if any(t in text for t in ('cabling','network','security','commercial wifi','wireless','loss prevention','warehouse','access control','installation cost','intercom system','fiber','telephony','managed','camera')):return 'EN'
    return 'UNKNOWN'


def intent_for(query):
    q=normalized(query)
    if 'opticable' in q:return 'BRANDED'
    if any(t in q for t in ('emploi','job','salary','salaire','police-reported','statistics canada','shoplifting statistics','shoplifting stats','juristat','sécurité internet','yes please')):return 'IRRELEVANT'
    if any(t in q for t in ('how ','what ','comment ','qu\'est','statistique','statistics','definition','définition')):return 'INFORMATIONAL'
    if not service_for(q):return 'INFORMATIONAL'
    if any(t in q for t in ('montréal','montreal','laval','rive-nord','québec','quebec','la prairie','chambly','terrebonne')):return 'LOCAL SERVICE'
    if any(t in q for t in ('cost','pricing','price','prix','coût','vs ','comparison','comparaison')):return 'COMMERCIAL INVESTIGATION'
    return 'TRANSACTIONAL'


def number(value):
    if isinstance(value,bool) or value is None:return None
    try:v=float(value)
    except (TypeError,ValueError):return None
    return v if math.isfinite(v) and v>=0 else None


def market_priority(item,*,outcomes=None):
    """Components are visible policy points, not revenue forecasts."""
    intent=item.get('intent','TRANSACTIONAL')
    components={'intent':{'TRANSACTIONAL':24,'LOCAL SERVICE':28,'COMMERCIAL INVESTIGATION':20,'INFORMATIONAL':4,'BRANDED':5,'IRRELEVANT':0}.get(intent,0)}
    volume=number(item.get('market_volume'));impressions=number(item.get('observed_search_impressions'))
    components['market_demand']=min(20,math.log1p(volume)*2) if volume is not None else 0
    components['observed_visibility']=min(12,math.log1p(impressions)*2) if impressions is not None else 0
    components['buying_trigger']=20 if item.get('recent_triggers',0)>0 else 0
    components['known_company_coverage']=min(10,math.log1p(item.get('addressable_companies',0))*2)
    components['recurring_potential']=6 if item.get('recurring_potential') else 0
    geo=geography_evidence(item)
    target_geo=geo_bucket(item.get('target_geography') or item.get('geography'))
    components['owner_geography']=6 if target_geo in {'MONTRÉAL','LAVAL','RIVE-NORD','GREATER MONTRÉAL'} else 3 if target_geo in {'CANADA','QUÉBEC','QUÉBEC CITY'} else 0
    components['service_fit']=12 if item.get('service') in SERVICES else 0
    if intent in {'INFORMATIONAL','IRRELEVANT','BRANDED'}:
        components={k:(v if k=='intent' else v*.25) for k,v in components.items()}
    score=min(100,round(sum(components.values()),1));basis='MARKET-BASED PRIORITY';weight=0
    # Later verified cohort outcomes may progressively outweigh generic market
    # points. Missing/TEST/partial historical populations cannot enter this path.
    if outcomes and outcomes.get('truth')=='PROVEN' and outcomes.get('test_only') is False:
        n=outcomes.get('eligible_opportunities',0);wins=outcomes.get('won',0)
        if type(n) is int and type(wins) is int and n>=10 and 0<=wins<=n:
            weight=min(.8,n/100);score=round(score*(1-weight)+(wins/n*100)*weight,1);basis='MARKET + VERIFIED OPTICABLE OUTCOMES'
    missing=[k for k in ('market_volume','cpc','seo_difficulty','paid_competition','contact_coverage') if item.get(k) is None]
    channels=[]
    strong=volume is not None and volume>=100 or impressions is not None and impressions>=10
    little=volume is not None and volume<10
    position=number(item.get('position'));cpc=number(item.get('cpc'))
    if strong and not little and intent not in {'INFORMATIONAL','IRRELEVANT','BRANDED'}:
        channels=['SEO','CONTENT']
        if position is None or position>10:channels.append('GOOGLE ADS — OWNER REVIEW')
        if item.get('geography') in {'Montréal','Laval','Greater Montréal'}:channels.append('LOCAL SEO')
    if item.get('recent_triggers',0) or item.get('addressable_companies',0)>=10:
        channels.insert(0 if little or not strong else len(channels),'OUTBOUND — SHADOW RESEARCH')
    if not channels:channels=['RESEARCH']
    if not geo['quebec_recommendation_allowed']:channels=['OUT OF SCOPE — RESEARCH ONLY'];score=0
    sample=search_evidence({'impressions':impressions,'position':item.get('position')})
    if basis=='MARKET-BASED PRIORITY' and sample['class'] in {'TENTATIVE EVIDENCE','INSUFFICIENT EVIDENCE'} and not item.get('recent_triggers') and (volume is None or volume<100):score=min(69,score)
    confidence='PARTIAL' if missing else 'MARKET EVIDENCE AVAILABLE'
    if item.get('outreach_owner')=='CLAUDE_APOLLO':channels=[c for c in channels if not c.startswith('OUTBOUND')]+['COORDINATE EXISTING CLAUDE/APOLLO']
    return {**item,'score':score,'priority':'HIGH' if score>=70 else 'MEDIUM' if score>=40 else 'LOW',
            'basis':basis,'outcome_weight':weight,'components':components,'channels':channels,'missing_data':missing,
            'confidence':confidence,'evidence_confidence':sample['class'],'geography_evidence':geo,
            'facts':{k:fact(item.get(k),'Native observation' if k.startswith('observed_') else 'Declared market policy','ESTIMATE' if k in {'market_volume','cpc','seo_difficulty'} else 'DERIVED FACT') for k in ('observed_search_impressions','position','market_volume','cpc','seo_difficulty','addressable_companies','recent_triggers')},
            'cold_send_allowed':False,'crm_promote_allowed':False,'ad_mutation_allowed':False}


def opportunities(queries,signals,competitors,companies,*,outcomes=None):
    result=[]
    for service,icp,geo,recurring in SEGMENTS:
        qs=[r for r in queries if geography_evidence(r)['quebec_recommendation_allowed'] and service_for(r.get('query',''))==service and intent_for(r['query']) not in {'IRRELEVANT','BRANDED','INFORMATIONAL'}]
        relevant=[s for s in signals if s.get('current_status') in {'OPEN','ISSUED'} and (s.get('geography')==geo or geo=='Greater Montréal' and s.get('geography') in {'Montréal','Laval','Rive-Nord'}) and (service_for(s.get('title','')+' '+s.get('why',''))==service or any(service_for(t)==service for t in s.get('service_fit',[])))]
        competing=[c for c in competitors if service in c.get('services',[])]
        # This is the observed saved-company population, not a market-size estimate.
        firms=[c for c in companies if c.get('icp')==icp and c.get('geography')==geo]
        counts=[number(q.get('impressions')) for q in qs]
        impressions=sum(counts) if counts and all(n is not None for n in counts) else None
        positions=[(number(q.get('position')),number(q.get('impressions')) or 0) for q in qs if number(q.get('position')) is not None]
        total=sum(w for _,w in positions)
        position=sum(p*w for p,w in positions)/total if total else None
        evidence=[{'source':'Search Console','query':q['query'],'url':q.get('page'),'geography':geography_evidence(q),'search_sample':search_evidence(q),'impressions':q.get('impressions'),'clicks':q.get('clicks'),'ctr':q.get('ctr'),'position':q.get('position'),'date_from':q.get('date_from'),'date_to':q.get('date_to'),'scope':'Observed Opticable visibility, not total market volume or city demand'} for q in sorted(qs,key=lambda q:number(q.get('impressions')) or 0,reverse=True)[:3]]
        evidence += [{'source':s['source'],'url':s.get('source_url'),'trigger':s['title'],'effective_date':s.get('effective_date'),'deadline':s.get('deadline')} for s in relevant[:2]]
        evidence += [{'source':'Discovered competitor page','url':c['url'],'domain':c['domain']} for c in competing[:2]]
        item={'id':digest([service,icp,geo]),'service':service,'icp':icp,'geography':geo,'target_geography':geo,'geography_basis':'TARGET HYPOTHESIS','intent':'LOCAL SERVICE',
              'observed_search_impressions':impressions if qs else None,'market_volume':None,'cpc':None,'seo_difficulty':None,
              'paid_competition':None,'contact_coverage':None,'position':round(position,2) if position is not None else None,
              'addressable_companies':len(firms),'recent_triggers':len(relevant),'competitor_pages':len(competing),
              'recurring_potential':recurring,'evidence':evidence,'why_this_market':'Service fits the selected ICP; evidence and gaps are shown separately.',
              'why_now': relevant[0]['why'] if relevant else 'Existing search visibility can be improved.' if qs else 'Research candidate from owner-defined service/geography priorities; demand not yet proven.',
              'market_scope_note':'ICP/geography is a target hypothesis. Query metrics are property-wide unless the query explicitly identifies the market.'}
        result.append(market_priority(item,outcomes=(outcomes or {}).get(item['id'])))
    return sorted(result,key=lambda r:(-r['score'],r['id']))


def render_acquisition(view):
    h=lambda v:escape(str(v if v is not None else 'Unknown'),quote=True)
    at=view.get('at');date=at
    if at:
        from datetime import datetime
        date=datetime.fromisoformat(at).astimezone(ZoneInfo('America/Toronto')).strftime('%Y-%m-%d %H:%M %Z')
    html="<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Acquisition intelligence</title><style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:24px;color:#163445;background:#f5f7f8}nav a{margin-right:16px}article,section{background:white;padding:18px;margin:16px 0;border-radius:8px}h2{font-size:22px}small{color:#526571}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px;border-bottom:1px solid #ddd}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}li{margin:8px 0}</style></head><body><nav><a href='/v1/operator/today'>Today</a><a href='/v1/operator/sales'>Sales</a><a href='/v1/operator/business'>Business</a></nav><h1>Acquisition intelligence</h1>"
    html+=f"<p>Market-based priorities · {h(date)} · research and recommendations</p><p>CRM stays focused on real sales work. Claude/Apollo continues outreach. No content publication, campaign change or conversion upload is enabled here.</p>"
    health=view.get('measurement_health',{})
    html+=f"<section><h2>Measurement health</h2><p>GA4 authentication: {h(health.get('auth_status'))} · Collection: {h(health.get('collection_status'))}<br>Last production data: {h(health.get('last_observed_data'))}</p><small>{h(health.get('coverage_notes'))}</small></section>"
    for site,status in health.get('site_status',{}).items():html+=f"<p><small>{h(site)}: {h(status.get('status'))} · last data {h(status.get('last_observed_data'))}</small></p>"
    html+="<section><h2>What should we do next?</h2><ol>"
    for r in view.get('next_actions',[])[:5]:html+=f"<li><strong>{h(r['title'])}</strong><br>{h(r['why'])}</li>"
    html+='</ol></section><h2>Top market opportunities</h2><div class="grid">'
    for r in view.get('opportunities',[])[:10]:
        html+=f"<article><h3>{h(r['service'])}</h3><p>{h(r['icp'])} · {h(r['geography'])}</p><p>{h(r['priority'])} · {h(r['basis'])} · {h(r.get('evidence_confidence'))}</p><p>{h(r['why_now'])}</p><p>{h(', '.join(r['channels']))}</p><small>Missing: {h(', '.join(r['missing_data']))}. {h(r.get('market_scope_note'))}</small><details><summary>Evidence and policy components</summary><p>{h(r['components'])}</p>"
        for e in r.get('evidence',[]):
            url=e.get('url','')
            html+=f"<p>{h(e.get('query') or e.get('trigger') or e.get('domain'))} · {h(e['source'])}"+(f" · <a href='{h(url)}' rel='noreferrer'>Source</a>" if url.startswith('https://') else '')+'</p>'
            if e.get('search_sample'):
                sample=e['search_sample'];html+=f"<small>{h(sample.get('impressions'))} impressions · {h(sample.get('clicks'))} clicks · CTR {h(sample.get('ctr'))} · average position {h(sample.get('position'))} · {h(sample.get('date_from'))}–{h(sample.get('date_to'))} · {h(e.get('geography',{}).get('geography'))}</small>"
        html+='</details></article>'
    html+='</div><section><h2>Prospect signals</h2>'
    for s in view.get('prospect_signals',[])[:5]:html+=f"<p><strong>{h(s['title'])}</strong> · {h(s['why'])}<br><small>{h(s.get('recommendation_state'))} · {h(s.get('current_status'))} · {h(s.get('source_freshness'))} · actors {h(s.get('actor_confidence'))} · {h(s.get('geography'))}<br>Checked: {h(s.get('last_checked'))}. Missing: {h(', '.join(s.get('missing_evidence') or []))}. Contact clearance remains off.</small></p>"
    html+='</section><section><h2>Content and SEO queue</h2>'
    for c in view.get('content_queue',[])[:8]:
        sample=c.get('search_sample',{})
        html+=f"<p><strong>{h(c['decision'])}: {h(c['title'])}</strong> · {h(c['language'])}<br>{h(c['why'])}<br><small>{h(c.get('evidence_confidence'))} · {h(c.get('geography'))} · {h(sample.get('impressions'))} impressions · {h(sample.get('clicks'))} clicks · CTR {h(sample.get('ctr'))} · average position {h(sample.get('position'))} · {h(sample.get('date_from'))}–{h(sample.get('date_to'))}<br>{h(c.get('existing_page') or c.get('recommended_url'))} · CTA: {h(c.get('cta'))}</small></p>"
    html+='</section>'
    if view.get('ads_intelligence'):
        from .ads_intelligence import render_summary
        html+=render_summary(view['ads_intelligence'])
    if view.get('trigger_intelligence'):
        from .trigger_intelligence import render_queue
        html+=render_queue(view['trigger_intelligence'])
        if view['trigger_intelligence'].get('prospect_universe'):
            from .prospect_universe import render
            html+=render(view['trigger_intelligence']['prospect_universe'])
    html+='<section><h2>Paid search research</h2>'
    economics=view.get('keyword_economics',{})
    if economics:
        html+=f"<p>Keyword economics: {h(economics.get('state'))} · {h(economics.get('geography'))} · {h(economics.get('currency'))}<br><small>{h(economics.get('access'))}. Retrieved {h(economics.get('retrieved_at'))}. Trial continuity: {h(economics.get('trial_continuity'))}.</small></p>"
        examples=[r for language in ('FR','EN') for r in [x for x in economics.get('rows',[]) if x.get('language')==language][:3]]
        for r in examples:
            html+=f"<p>{h(r['query'])} · {h(r['language'])}<br><small>Monthly searches: {h(r['market_volume'])} · CPC estimate: {h(r['cpc'])} CAD · competition: {h(r['paid_competition'])}. {h(r['window'])}.</small></p>"
    for p in view.get('paid_opportunities',[])[:5]:html+=f"<p>{h(p['service'])} · {h(p['reason'])}<br><small>Campaign changes require owner approval. CPC: {h(p.get('cpc'))}</small></p>"
    html+='</section><section><h2>Local proof and content reuse</h2><p>'+h(view.get('local_strategy','Owner-reviewed project evidence comes before publication.'))+'</p>'
    for plan in view.get('repurposing',[])[:2]:html+='<p>'+h(' → '.join(a['type'] for a in plan['assets']))+'<br><small>'+h(plan['source'])+'</small></p>'
    seo=view.get('technical_seo',{})
    html+='</section><section><h2>Website and competitor evidence</h2><p>'+h(seo.get('pages_analyzed'))+' URLs analyzed · '+h(seo.get('indexable_candidates'))+' crawlable/indexable candidates · '+h(seo.get('indexed_verified'))+' native indexing proofs. Performance: '+h(seo.get('page_performance'))+'.</p><p>Competitor baseline: service overlap on inspected primary pages. Ranking, traffic, paid presence and changes over time remain unmeasured.</p>'
    for c in view.get('competitors',[])[:7]:html+=f"<p><a href='{h(c['url'])}' rel='noreferrer'>{h(c['domain'])}</a> · {h(', '.join(c.get('services',[])))}</p>"
    html+='</section><section><h2>Source health</h2><table><tr><th>Source</th><th>State</th><th>Coverage / blocker</th></tr>'
    for r in view.get('source_health',[]):html+=f"<tr><td>{h(r['source'])}</td><td>{h(r['state'])}{' · STALE' if r.get('stale') else ''}</td><td>{h(r['reason'])}</td></tr>"
    html+='</table></section><p><small>Observed visibility is not total search demand. Unknown volume, costs, rankings and ROI are never fabricated. Raw evidence stays in the private acquisition store.</small></p></body></html>'
    return html
