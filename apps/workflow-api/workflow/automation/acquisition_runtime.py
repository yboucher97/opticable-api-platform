"""Optional acquisition observer, isolated from working lifecycle families."""
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import grp,json,os
from . import lifecycle_control as lc
from .acquisition_store import AcquisitionStore,digest
from .acquisition_ingest import ingest
from .sales_intelligence import stamp,permit_signals
from .trigger_evidence import assess_trigger

ROOT=Path('/var/lib/optibrain/acquisition-intelligence')
DISPLAY=Path('/run/optibrain-readiness/acquisition-intelligence.json')
DATABASE=Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')


def owner_projection(view):
    # Full provenance/facts remain in the private view/store. The cockpit only
    # needs the recommendation sample, confidence and actionable exceptions.
    display={k:v for k,v in view.items() if k!='queries'}
    display['content_queue']=[{k:v for k,v in row.items() if k not in {'facts','evidence','score_components','competitor_gap','internal_links'}} for row in view.get('content_queue',[])]
    display['opportunities']=[]
    for row in view.get('opportunities',[]):
        item={k:v for k,v in row.items() if k!='facts'}
        item['evidence']=[{k:v for k,v in evidence.items() if k not in {'impressions','clicks','ctr','position','date_from','date_to'}} for evidence in row.get('evidence',[])]
        display['opportunities'].append(item)
    seo=view.get('technical_seo',{})
    display['technical_seo']={k:v for k,v in seo.items() if k not in {'issues','orphan_candidates'}}
    display['technical_seo']['issue_count']=len(seo.get('issues',[]))
    display['technical_seo']['orphan_candidate_count']=len(seo.get('orphan_candidates',[]))
    excluded=view.get('excluded_research',[])
    display['excluded_research_count']=len(excluded)
    display['excluded_research']=[{k:r.get(k) for k in ('title','geography','decision','evidence_confidence')} for r in excluded[:5]]
    return display


def observe(engine,settings,*,now=None):
    from .real_internal import atomic
    now=now or datetime.now(timezone.utc)
    if (ROOT/'STOP').exists():return {'state':'DISABLED','provider_writes':0}
    inputs=lc.trusted_json(ROOT/'inputs.json',16777216)
    inputs['apollo']=lc.trusted_json(Path('/var/lib/optibrain/sales-intelligence/apollo.json'),16777216)
    identities=lc.trusted_json(Path('/var/lib/optibrain/sales-intelligence/crm.json'),2097152)
    inputs['crm']=identities['crm'];inputs['crm_at']=identities['at']
    permits=lc.trusted_json(Path('/var/lib/optibrain/sales-intelligence/permits.json'),2097152)
    public=lc.trusted_json(Path('/var/lib/optibrain/sales-intelligence/public-triggers.json'),262144)
    inputs['signals']=permit_signals(permits['records'],now=now,retrieved_at=permits.get('at'))+public.get('signals',[])
    inputs['raw_permits']=permits['records']
    inputs['permits_at']=permits.get('at');inputs['seao_at']=public.get('at')
    google=ROOT/'google-current.json'
    if google.exists():inputs['google']=lc.trusted_json(google,2097152)
    economics=ROOT/'keyword-economics.json'
    if economics.exists():inputs['keyword_economics']=lc.trusted_json(economics,2097152)
    at=stamp(inputs.get('google',{}).get('at'))
    if not engine.dry_run and (not at or (now-at).total_seconds()>=86400):
        from workflow.google_oauth import GoogleOAuthManager
        from .acquisition_sources import GoogleAcquisitionReader
        reader=None;reads={}
        try:
            reader=GoogleAcquisitionReader(GoogleOAuthManager(settings.google_oauth).access_token())
            for kind in ('gsc_sites','gsc_sitemaps','gsc_queries','gsc_daily','gsc_devices','gsc_countries',
                         'ga4_main','ga4_other','ga4_collection','ads_customer','ads_campaigns','ads_keywords','ads_search_terms','ads_geo_constants'):
                reads[kind]=reader.read(kind,now=now)
        except (ValueError,OSError,RuntimeError):reads['collection']={'state':'PARTIAL','error':'Bounded Google reporting collection unavailable'}
        finally:
            if reader:reader.close()
        prior=inputs.get('google',{});combined={k:{**v,'observed_at':v.get('observed_at') or prior.get('at')} for k,v in prior.get('reads',{}).items()}
        for k,v in reads.items():
            if v.get('state')=='WORKING':combined[k]={**v,'observed_at':now.isoformat()}
        inputs['google']={'schema':1,'at':now.isoformat(),'reads':combined,'attempts':reads,'provider_mutations':0}
        atomic(google,inputs['google'])
    inputs['date_from']=inputs.get('google',{}).get('reads',{}).get('gsc_queries',{}).get('date_from',inputs.get('date_from'))
    inputs['date_to']=inputs.get('google',{}).get('reads',{}).get('gsc_queries',{}).get('date_to',inputs.get('date_to'))
    # Expiry/closed status must invalidate an otherwise unchanged input cache.
    time_state=[{k:r[k] for k in ('current_status','source_freshness','sales_review_eligible')} for s in inputs.get('signals',[]) for r in [assess_trigger(s,now=now)]]
    version=digest([inputs,now.astimezone(ZoneInfo('America/Toronto')).date().isoformat(),time_state]);cache=ROOT/'view.json';view=lc.trusted_json(cache,2097152) if cache.exists() else {}
    if view.get('input_version')!=version:
        if engine.dry_run:return {'state':'DRY_RUN — ACQUISITION REBUILD PLANNED','provider_writes':0}
        store=AcquisitionStore(DATABASE);view=ingest(store,inputs,now=now)
        if inputs.get('website'):
            from .seo_intelligence import enrich
            view=enrich(store,inputs,view,now=now)
        store.prune(now)
        view['input_version']=version;view['observed_at']=now.isoformat();atomic(cache,view)
    if not engine.dry_run:
        store=AcquisitionStore(DATABASE);view.update(store.summary(now));view['at']=now.isoformat()
        display=owner_projection(view)
        # Match the bytes written by atomic(), including indentation and UTF-8.
        if len((json.dumps(display,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode())>262144:raise ValueError('Owner acquisition projection exceeds byte bound')
        atomic(DISPLAY,display,0o600);os.chown(DISPLAY,0,grp.getgrnam('opticable-workflow-api').gr_gid);os.chmod(DISPLAY,0o640)
    return view
