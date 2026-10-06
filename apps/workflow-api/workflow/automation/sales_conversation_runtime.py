"""Bounded preparation on the existing internal observer; no new timer/model loop."""
from datetime import datetime,timezone
from pathlib import Path
import fcntl,grp,json,os
from . import lifecycle_control as lc
from .acquisition_store import digest
from .optimization_store import OptimizationStore
from .sales_conversations import build_bundle,ConversationStore
from .ads_runtime import persist,invocation_origin
from .sales_intelligence import stamp

ROOT=Path('/var/lib/optibrain/sales-intelligence')
DATABASE=Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
DISPLAY=Path('/run/optibrain-readiness/sales-conversations.json')

def observe(engine,settings,*,apollo,crm,now):
    if engine.dry_run:return {'state':'DRY_RUN — NO SALES PROVIDER READ OR PREPARATION','provider_writes':0}
    if (ROOT/'STOP').exists() or (ROOT/'CONVERSATIONS_STOP').exists():return {'state':'DISABLED','provider_writes':0}
    lock=os.open(ROOT/'conversations.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'state':'BUSY — OTHER BOUNDED OBSERVER','provider_writes':0}
        return prepare(engine,apollo,crm,now)
    finally:os.close(lock)

def prepare(engine,apollo,crm,now):
    from .real_internal import atomic
    from .sales_reply_reader import read_replies
    origin=invocation_origin();path=ROOT/'conversation-mail.json'
    cache=lc.trusted_json(path,8388608) if path.exists() else {'rows':[]}
    # Every query has its own cooldown; a failed search cannot storm each minute.
    mail=read_replies(engine.client,apollo,cache,now=now,max_calls=max(0,min(16,160-engine.reads)))
    engine.reads+=mail['provider_reads']
    if mail['provider_reads']:
        mail['origin']=origin
        atomic(path,mail)
    else:mail=cache
    prospect_path=Path('/run/optibrain-readiness/prospect-details.json')
    prospects=lc.trusted_json(prospect_path,262144) if prospect_path.exists() else {}
    fresh=stamp(prospects.get('at'))
    usable=bool(fresh and 0<=(now-fresh).total_seconds()<900 and prospects.get('read_only') is True)
    seq=ROOT/'conversation-sequences.json';sequences=lc.trusted_json(seq,2097152) if seq.exists() else {}
    # Period metrics retain their original observation time; cache is not a
    # continuously running analytics connector. Sequence recommendations expire.
    seq_at=stamp(sequences.get('at'));seq_current=bool(seq_at and 0<=(now-seq_at).total_seconds()<7*86400)
    semantic={'apollo':apollo,'mail':mail,'crm':crm,'prospects':prospects.get('rows',[]) if usable else [],
              'sequence_evidence':sequences if seq_current else {},'day':now.date().isoformat()}
    version=digest(semantic);bundle_path=ROOT/'conversation-bundle.json'
    saved=lc.trusted_json(bundle_path,8388608) if bundle_path.exists() else {}
    store=OptimizationStore(DATABASE)
    if saved.get('input_version')!=version:
        bundle=build_bundle(apollo,mail,crm,semantic['prospects'],now=now,sequence_evidence=semantic['sequence_evidence'])
        persist(bundle,store)
        for row in bundle['conversations']:ConversationStore(DATABASE).record(row)
        saved={'schema':1,'input_version':version,'bundle':bundle,'origin':origin,'at':now.isoformat()}
        atomic(bundle_path,saved)
    bundle=saved['bundle'];ids={p['record']['proposal_id'] for p in bundle['proposals']}
    proposals=[r for r in store.rows() if r['record']['proposal_id'] in ids]
    priorities=[r['record'] for r in store.rows('optibrain.business_priority') if r['record']['proposal_id'] in ids and next((p['effective_status'] for p in proposals if p['record']['proposal_id']==r['record']['proposal_id']),None)!='REJECTED']
    rows=bundle['conversations'];latest=stamp(mail.get('at'));mail_fresh=bool(latest and 0<=(now-latest).total_seconds()<24*3600)
    projection={'schema':1,'scope':'live','read_only':True,'at':now.isoformat(),'state':'SHADOW — PREPARATION ONLY' if mail_fresh and usable else 'DEGRADED — EVIDENCE GAP; EXECUTION HELD',
        'observed_at':mail.get('at'),'apollo_observed_at':apollo.get('at'),'collection_origin':mail.get('origin','UNKNOWN'),
        'preparation_origin':saved['origin'],'last_prepared_at':saved['at'],'effect_class':'NONE','provider_writes':0,'runtime_model_calls':0,
        'conversations':rows,'coverage':bundle['coverage'],'coverage_gaps':bundle['coverage_gaps'],'sequence_evidence':sequences,
        'source_health':{'mail':{'at':mail.get('at'),'fresh':mail_fresh,'last_read_count':mail.get('provider_reads',0),'unknown_bodies':sum(not c['reply_excerpt'] for c in rows)},
            'prospects':{'fresh':usable,'omitted':prospects.get('omitted')},'sequence_metrics':{'fresh':seq_current,'at':sequences.get('at'),'automatic_refresh':'NOT IMPLEMENTED — CONNECTOR SNAPSHOT'}},
        'proposals':[{'proposal_id':p['record']['proposal_id'],'title':p['record']['recommended_change'],'status':p['effective_status'],'type':p['record']['proposal_type']} for p in proposals],
        'priorities':sorted(priorities,key=lambda r:r['urgency']!='HIGH')[:5],
        'send_authority':'ABSENT','English_real_automation':'DISABLED','execution_authorized':False}
    # Bounded projection may omit detail but never delete canonical evidence.
    while len(json.dumps(projection,ensure_ascii=False,indent=2).encode())>250000 and projection['conversations']:
        projection['conversations'].pop();projection['display_truncated']=True
    atomic(DISPLAY,projection,0o600)
    os.chown(DISPLAY,0,grp.getgrnam('opticable-workflow-api').gr_gid);os.chmod(DISPLAY,0o640)
    return projection
