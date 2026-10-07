"""Bounded Ads preparation attached to the existing acquisition observer.

No new timer, model loop, campaign writer or approval adapter. Freshness and
failed attempt cooldown are distinct; old evidence retains its original date.
"""
from datetime import datetime,timezone
from pathlib import Path
import grp,json,os
from . import lifecycle_control as lc
from .acquisition_store import digest
from .optimization_store import OptimizationStore
from .decision_card import concise_card
from .ads_intelligence import build_bundle

ROOT=Path('/var/lib/optibrain/acquisition-intelligence')
DISPLAY=Path('/run/optibrain-readiness/ads-intelligence.json')
DATABASE=Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
INTERVAL=7*86400
COOLDOWN=86400


def stamp(value):
    try:
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:return None


def invocation_origin():
    """Reuse the root-installed Phase32 sampler, tied to this invocation.

    A running service or an enabled timer alone cannot prove scheduling. A
    shell without this service's invocation ID is explicitly manual.
    """
    invocation=os.environ.get('INVOCATION_ID')
    if not invocation:return 'MANUAL'
    import importlib.util,stat,subprocess
    helper=Path('/usr/local/lib/optibrain/activity_snapshot.py')
    try:
        for path in (helper,*helper.parents):
            s=path.stat()
            if s.st_uid!=0 or s.st_mode&0o022:return 'UNKNOWN'
        spec=importlib.util.spec_from_file_location('reviewed_activity_origin',helper)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        proof=module.job('opticable-lifecycle-internal')
        if proof['invocation_id']!=invocation:return 'UNKNOWN'
        return 'UNATTENDED' if proof['origin']=='SCHEDULED' else 'MANUAL'
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):return 'UNKNOWN'


def persist(bundle,store):
    for group,kind in [('proposals','optibrain.optimization_proposal'),('priorities','optibrain.business_priority'),('assets','optibrain.optimization_asset')]:
        old={r['record'].get('proposal_id' if group=='proposals' else 'priority_id' if group=='priorities' else 'asset_id'):r for r in store.rows(kind)}
        for item in bundle[group]:
            record=item['record'];key=record.get('proposal_id' if group=='proposals' else 'priority_id' if group=='priorities' else 'asset_id')
            prior=old.get(key)
            if prior:
                compare=lambda r:{k:v for k,v in r.items() if k not in {'created_at','updated_at','revision'}}
                if compare(prior['record'])==compare(record) and prior['detail']==item['detail']:
                    item['record']=prior['record'];continue
                record['created_at']=prior['record']['created_at']
                # Priority/asset revisions are store metadata; interchange format
                # remains the reviewed shared contract rather than new envelopes.
                with store.connect() as db:
                    revision=db.execute('SELECT max(revision) FROM optimization_records WHERE kind=? AND id=?',(kind,key)).fetchone()[0]+1
                if group=='proposals':record['revision']=revision
                store.record(record,item['detail'],revision=revision)
            else:store.record(record,item['detail'])


def projection(bundle,store,*,collection_origin,preparation_origin,health):
    proposal_ids={r['record']['proposal_id'] for r in bundle['proposals']}
    asset_ids={r['record']['asset_id'] for r in bundle['assets']}
    priorities=[r for r in store.rows('optibrain.business_priority') if r['record']['proposal_id'] in proposal_ids]
    proposals=[r for r in store.rows() if r['record']['proposal_id'] in proposal_ids]
    return {'schema':1,'scope':'live','read_only':True,'at':bundle['intelligence']['at'],'authority':'READ / ANALYZE / PREPARE ONLY',
        'execution_authorized':False,'provider_writes':0,'proposal_count':len(proposals),
        'hook_count':sum(r['record']['asset_id'] in asset_ids for r in store.rows('optibrain.optimization_asset')),'priority_count':len(priorities),
        'collection_origin':collection_origin,'preparation_origin':preparation_origin,'effect_class':'NONE',
        'source_health':health,'economics_state':bundle['intelligence']['economics_state'],
        'inventory':bundle['intelligence']['inventory'],'opportunities':bundle['intelligence']['opportunities'],
        'proposals':[{'proposal_id':r['record']['proposal_id'],'revision':r['record']['revision'],
            'title':r['record']['proposal_type']+' · '+str(r['detail'].get('service') or r['detail'].get('campaign_name') or 'FR/EN'),
            'status':r['effective_status'],'confidence':r['record']['confidence'],
            'budget':r['detail'].get('budget',{}).get('average_daily'),'why':r['record']['business_problem'],
            'decision_summary':concise_card(r['decision_card'])} for r in proposals],
        'priorities':[{**r['record'],'status':'REJECTED' if next((p['effective_status'] for p in proposals if p['record']['proposal_id']==r['record']['proposal_id']),None)=='REJECTED' else r['record']['status']} for r in priorities],
        'natural_lead':bundle['intelligence']['natural_lead'],
        'autonomy':'Existing daily Google reporting observer; bounded weekly inventory/preparation. No Ads effect or scheduled model calls.'}


def observe(engine,settings,*,now=None,base_view=None,origin='UNKNOWN'):
    from .real_internal import atomic
    now=now or datetime.now(timezone.utc)
    if (ROOT/'ADS_STOP').exists(): return {'state':'DISABLED','provider_writes':0}
    if engine.dry_run: return {'state':'DRY_RUN — ADS READ/PREPARATION ONLY','provider_writes':0}
    if origin=='UNKNOWN':origin=invocation_origin()
    path=ROOT/'ads-inventory.json';attempt_path=ROOT/'ads-attempt.json'
    inventory=lc.trusted_json(path,8388608) if path.exists() else {}
    attempt=lc.trusted_json(attempt_path,262144) if attempt_path.exists() else {}
    observed=stamp(inventory.get('at'));last_attempt=stamp(attempt.get('at'))
    due=not observed or (now-observed).total_seconds()>=INTERVAL
    if due and (not last_attempt or (now-last_attempt).total_seconds()>=COOLDOWN):
        from workflow.google_oauth import GoogleOAuthManager
        from .ads_sources import AdsInventoryReader,queries
        reader=None;reads={}
        try:
            reader=AdsInventoryReader(GoogleOAuthManager(settings.google_oauth).access_token())
            for kind in queries(now)[0]:reads[kind]=reader.read(kind,now=now)
        except (ValueError,OSError,RuntimeError):reads['collection']={'state':'ENVIRONMENT_OR_TOKEN_FAILURE'}
        finally:
            if reader:reader.close()
        attempt={'schema':1,'at':now.isoformat(),'origin':origin,
                 'results':{k:{field:v.get(field) for field in ('state','http_status','error_codes','complete')} for k,v in reads.items()},
                 'calls':reader.calls if reader else 0,'provider_writes':0}
        atomic(attempt_path,attempt)
        # Failed partial refresh never relabels old snapshots fresh. Persist
        # separate immutable raw attempt so a gap cannot masquerade as empty Ads.
        atomic(ROOT/('ads-read-'+now.strftime('%Y%m%dT%H%M%S%fZ')+'.json'),{'schema':1,'at':now.isoformat(),'reads':reads,'origin':origin})
        if all(reads.get(k,{}).get('state')=='WORKING' and reads[k].get('complete') is True for k in queries(now)[0]):
            inventory={'schema':1,'at':now.isoformat(),'reads':reads,'origin':origin,'provider_writes':0}
            atomic(path,inventory);observed=now
    google=lc.trusted_json(ROOT/'google-current.json',2097152) if (ROOT/'google-current.json').exists() else {}
    economics=lc.trusted_json(ROOT/'keyword-economics.json',2097152) if (ROOT/'keyword-economics.json').exists() else {}
    context=lc.trusted_json(ROOT/'ads-context.json',2097152) if (ROOT/'ads-context.json').exists() else {}
    view=base_view or {};inputs={**context,'ads':inventory,'google':google,'keyword_economics':economics,
        'market_opportunities':view.get('opportunities',[])}
    version=digest(inputs);cache=ROOT/'ads-view.json';cached=lc.trusted_json(cache,2097152) if cache.exists() else {}
    store=OptimizationStore(DATABASE)
    # Clock expiry must invalidate economic evidence, not wait for new inputs.
    version=digest([version,now.date().isoformat()])
    if cached.get('input_version')!=version:
        bundle=build_bundle(inputs,now);persist(bundle,store)
        cached={'input_version':version,'bundle':bundle,'origin':origin};atomic(cache,cached)
    health={'state':'WORKING' if observed and 0<=(now-observed).total_seconds()<INTERVAL else 'STALE / SOURCE UNAVAILABLE',
            'last_successful_read':inventory.get('at'),'last_attempt':attempt.get('at'),'attempt_results':attempt.get('results',{}),
            'inventory_interval_days':7,'failed_attempt_cooldown_hours':24,'data_gap':'UNKNOWN; cached evidence retains provenance' if not observed else None}
    display=projection(cached['bundle'],store,collection_origin=inventory.get('origin','UNKNOWN'),
                       preparation_origin=cached.get('origin','UNKNOWN'),health=health)
    # Projection freshness means refreshed operator state, not new provider proof.
    display['at']=now.isoformat();display['prepared_at']=cached['bundle']['intelligence']['at']
    raw=json.dumps(display,ensure_ascii=False,indent=2)
    if len(raw.encode())>262144: raise ValueError('Ads owner projection exceeds bound')
    atomic(DISPLAY,display,0o600);os.chown(DISPLAY,0,grp.getgrnam('opticable-workflow-api').gr_gid);os.chmod(DISPLAY,0o640)
    return display
