"""Fixed authoritative coverage adapters; one-time evidence is reusable at runtime."""
from datetime import datetime
import hashlib
import json
from zoneinfo import ZoneInfo

from .trigger_sources import CKAN, QUEBEC_RESOURCE, PublicReader, VisibleText, quebec_permits, local_date

PRIMARY = {
    'montoni': ('https://laval15.ecoparcmontoni.com/en/distribution', ['Écoparc Laval 15', 'groupemontoni.com', 'fall 2026']),
    'lovo': ('https://lovo.co/communiques/agrandissement-usine-saint-lambert-de-lauzon/', ['27 avril 2026', 'Saint-Lambert-de-Lauzon', 'novembre 2026']),
    'saq_gc': ('https://www.saq.com/en/content/about-us/press-releases/frare-et-gallant-chosen-by-the-saq', ['August 22, 2023', 'Frare Gallant', 'Laval']),
}


def primary_seeds(kind, raw, *, now):
    url, required = PRIMARY[kind]; parser = VisibleText(); parser.feed(raw.decode('utf-8',errors='replace'))
    visible = ' '.join(' '.join(parser.parts).split())
    if any(x not in visible for x in required): raise ValueError('Primary company evidence changed; hold for research')
    common = {'source_provider':'primary_company','source_url':url,'observed_at':now.isoformat(),
              'identity_status':'SUPPORTED','service_fit':{'primary':[],'secondary':[],
              'possible':['structured cabling','commercial Wi-Fi','IP cameras / CCTV','maintenance'],
              'recurring':['maintenance/support review'],'basis':'GENERAL ICP FIT'},
              'raw':{'sha256':hashlib.sha256(raw).hexdigest(),'required_visible_evidence':required}}
    if kind == 'montoni':
        return [{**common,'source_record_id':'montoni_laval15','company_name':'MONTONI','domain':'groupemontoni.com',
            'geography_class':'LAVAL','icp':'developer','location':'Écoparc Laval15, Laval',
            'why_opticable':'Primary developer site describes industrial distribution facilities and fall2026 leasing. Plausible tenant fit-up/network/security work; no confirmed purchase.',
            'source_contacts':[], 'timing_note':'Fall2026 leasing availability; precise tenant installation need unknown.'}]
    if kind == 'lovo':
        return [{**common,'source_record_id':'lovo_saint_lambert','company_name':'Lovo','domain':'lovo.co',
            'geography_class':'OTHER QUÉBEC','icp':'manufacturing','location':'Saint-Lambert-de-Lauzon, Québec',
            'why_opticable':'Primary company announced a plant expansion with planned November2026 completion. Network/security/support fit is inferred, not a contract.',
            'source_contacts':[{'id':'public:lovo:ceo','name':'Sébastien Léveillé','title':'Chief executive / chef de la direction',
                'source':'Primary company April27 announcement','source_url':url,'observed_at':'2026-04-27T12:00:00-04:00',
                'email':None,'email_verification':'UNKNOWN','suppressed':False,'contact_allowed':False}],
            'timing_note':'Planned November2026 completion, not independently confirmed current progress.'}]
    return [{**common,'source_record_id':'saq_montreal','company_name':'Société des alcools du Québec','domain':'saq.com',
             'geography_class':'MONTRÉAL','icp':'warehouse','location':'Montréal distribution centre',
             'why_opticable':'Historical primary client announcement identifies a distribution-centre owner; retain buyer/network/security intelligence. No current urgency.',
             'historical_project':{'id':'saq_cam_2023','date':'2023-08-22','actor_role':'PROPERTY OWNER','source_url':url}},
            {**common,'source_record_id':'frare_gallant_saq','company_name':'Frare Gallant','domain':None,'identity_status':'SUPPORTED',
             'geography_class':'LAVAL','icp':'general contractor','location':'Laval, Québec',
             'why_opticable':'Client primary source identifies historical construction-management contractor. Potential future cabling subcontract/partner fit; domain/contact research required.',
             'historical_project':{'id':'saq_cam_2023','date':'2023-08-22','actor_role':'GENERAL CONTRACTOR','source_url':url}}]


def private_triggers(seeds, *, now):
    """Dated announced expansion and undated development evidence, not contracts."""
    rows=[]
    for seed in seeds:
        key=seed['source_record_id']
        if key not in {'montoni_laval15','lovo_saint_lambert'}: continue
        dated=key=='lovo_saint_lambert'
        rows.append({**seed,'trigger_type':'COMPANY EXPANSION' if dated else 'CONSTRUCTION / DEVELOPMENT',
            'source_version':seed['raw']['sha256'],'source_version_at':seed['observed_at'],
            'first_observed_at':seed['observed_at'],'last_verified_at':seed['observed_at'],
            'publish_date':'2026-04-27T12:00:00-04:00' if dated else None,'closing_date':None,
            'source_effective_at':'2026-04-27T12:00:00-04:00' if dated else None,
            'status':'ANNOUNCED' if dated else 'UNKNOWN','event_max_age_days':365,
            'refresh_seconds':7*86400,'coverage_seconds':14*86400,
            'title':'Lovo factory expansion planned November2026' if dated else 'MONTONI Laval15 industrial distribution development',
            'description':'Industrial plant expansion planned for November2026; April27 primary announcement.' if dated else 'Industrial distribution facilities listed for fall2026 leasing; service need unconfirmed.','why_now':seed['timing_note']+'; source recheck does not prove construction progress or an open service contract.',
            'company_identity':{'confidence':'SUPPORTED','native_buyer_id':key,'source_url':seed['source_url']},
            'actors':[{'name':seed['company_name'],'role':'FACILITY OPERATOR' if dated else 'DEVELOPER',
                       'source_actor_id':key,'source_url':seed['source_url'],'confidence':'SUPPORTED','domain':seed['domain']}],
            'evidence_kind':'CURRENT PUBLIC SIGNAL'})
    return rows


def collect(saved, *, now, reader=None):
    """At most five GETs per refresh; unchanged40MiB municipal file is cached."""
    from .trigger_runtime import due
    reader = reader or PublicReader(limit=5); caches = dict(saved); seeds=[]; rows=[]; health=[]
    try:
        for source in ['quebec_permit', *PRIMARY]:
            old = caches.get(source,{}); current=dict(old); before=reader.calls
            if due(old,now,7*86400):
                current['attempted_at']=now.isoformat()
                try:
                    if source == 'quebec_permit':
                        raw,_=reader.get(CKAN+'resource_show',params={'id':QUEBEC_RESOURCE})
                        metadata=json.loads(raw)['result'];signature=[metadata['url'],metadata.get('last_modified')]
                        if signature != old.get('signature') or 'records' not in old:
                            body,_=reader.get(metadata['url'],max_bytes=50*1024*1024);data=json.loads(body)
                            published=max((f.get('properties',{}).get('DATE_DELIVRANCE','') for f in data['features']),default='')
                            records=quebec_permits(data,now=now,verified_at=now.isoformat(),published_at=local_date(published))
                            current.update(records=records,signature=signature,raw_sha256=hashlib.sha256(body).hexdigest(),
                                           source_effective_at=local_date(published),source_records=len(data['features']))
                        current['records']=[{**r,'last_verified_at':now.isoformat()} for r in current.get('records',[])]
                    else:
                        raw,_=reader.get(PRIMARY[source][0],max_bytes=1048576)
                        current['seeds']=primary_seeds(source,raw,now=now)
                    current.update(state='WORKING',observed_at=now.isoformat(),classification=None,reason='Bounded primary/official evidence; no buyer or contact invented')
                except Exception as exc:
                    import httpx
                    if not isinstance(exc,(httpx.HTTPError,ValueError,KeyError,TypeError)): raise
                    status=getattr(getattr(exc,'response',None),'status_code',None)
                    current.update(state='PARTIAL' if old.get('records') or old.get('seeds') else 'BLOCKED',
                        http_status=status,classification='RATE LIMIT' if status==429 else 'PUBLIC ACCESS GAP' if status in {401,403} else 'SOURCE / SCHEMA / BYTE / TIME BOUND',
                        reason='No retry; prior evidence retained, source change needs research')
            current.setdefault('state','UNKNOWN')
            caches[source]=current;rows.extend(current.get('records',[]));seeds.extend(current.get('seeds',[]))
            health.append({k:current.get(k) for k in ['state','observed_at','source_effective_at','classification','reason','source_records','http_status']}|
                          {'source':source,'coverage':'BOUNDED OFFICIAL150 PERMITS' if source=='quebec_permit' else 'ONE CURATED PRIMARY SOURCE','requests':reader.calls-before})
    finally:reader.close()
    rows.extend(private_triggers(seeds,now=now))
    return rows,seeds,caches,health
