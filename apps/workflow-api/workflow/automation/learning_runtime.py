"""Incremental bounded evidence review on the existing Manager observer."""
from datetime import datetime, timezone
import json
from .acquisition_store import digest
from .action_evidence import ActionEvidence, local_record
from .optimization_learning import evidence_bundle


def context(item):
    from .website_registry import site_for
    r=item['record'];d=item['detail']
    site=site_for(repository=d.get('repository'),page=r.get('target_url_or_record'),site_id=d.get('site_id'))
    return {'site':site['site_id'] if site else d.get('site','UNKNOWN'),'service':d.get('service','UNKNOWN'),
        'language':d.get('language','UNKNOWN'),'audience':d.get('audience') or d.get('icp','UNKNOWN'),
        'channel':d.get('channel') or r.get('target_system','UNKNOWN'),'change_class':r.get('proposal_type','UNKNOWN')}


def cached_evidence(item, inputs):
    """Only exact target/page/business object matches become proposal evidence.

    Available unmatched datasets are recorded as searched, never copied or
    claimed relevant just because they share a source or service label.
    """
    r=item['record'];target=r.get('target_object',{});identifier=target.get('entity_id');page=r.get('target_url_or_record')
    candidates=[];coverage={}
    domain=r.get('target_system')
    sources={'website':['search_console','ga4','forms','crm','books','google_ads','mail','website','competitors'],
        'ads':['google_ads','ga4','forms','crm','books','mail','competitors'],
        'sales':['mail','crm','books','apollo','forms']}
    family='website' if domain in {'WEBSITE','SEO','CONTENT','ZOHO_FORM'} else 'ads' if domain=='GOOGLE_ADS' else 'sales'
    snapshot=inputs.get('business',{}).get('snapshot',{})
    collections=[('CRM',k,v) for k,v in snapshot.items() if k in {'leads','contacts','accounts','deals'} and isinstance(v,list)]
    collections += [('BOOKS',k,v) for k,v in snapshot.items() if k in {'books_invoices','books_estimate_index'} and isinstance(v,list)]
    collections += [('GA4',k,v) for k,v in snapshot.items() if 'ga4' in k and isinstance(v,list)]
    collections += [('SEARCH_CONSOLE','content_queue',inputs.get('acquisition-intelligence',{}).get('content_queue',[])),
        ('MAIL','conversations',inputs.get('sales-conversations',{}).get('conversations',[]))]
    for source,name,rows in collections:
        coverage.setdefault(source.lower(),{'state':'REVIEWED','available':True,'matching_rows':0})
        for row in rows[:500]:
            if not isinstance(row,dict):continue
            identities=[str(row.get(k,'')) for k in ('id','invoice_id','estimate_id','conversation_id','existing_page','page','landing_page','page_url')]
            if not any(v and v in {str(identifier),str(page)} for v in identities):continue
            at=row.get('source_at') or row.get('observed_at') or row.get('search_sample',{}).get('observed_at') or row.get('last_verified_at')
            if at is None and source in {'CRM','BOOKS','GA4'}:
                module=snapshot.get('collection',{}).get('modules',{}).get(name,{})
                at=module.get('source_at')  # Projection timestamp never rejuvenates provider data.
            coverage[source.lower()]['matching_rows']+=1
            candidates.append({'provider':source,'source_reference':name+':'+str(identifier or page),
                'source_at':at,'observed_at':row.get('observed_at') or snapshot.get('observed_at'),
                'freshness':'CURRENT','truth_class':'PROVIDER_FACT','relationship':'Exact canonical target match',
                'completeness':row.get('completeness','UNKNOWN'),
                'value':{k:row[k] for k in ('clicks','impressions','sessions','qualified','Stage','status','amount','source','traffic_mix') if k in row},
                'evidence_class':'COUNTEREVIDENCE' if row.get('counterevidence') else 'SUPPORTING',
                'counterevidence':row.get('counterevidence'),
                'limitations':['Exact object context does not prove acquisition or revenue causation.']})
            if len(candidates)>=100:break
    for name in sources[family]:coverage.setdefault(name,{'state':'UNAVAILABLE','available':False,'reason':'No inspectable target-specific cache supplied'})
    for e in r.get('source_evidence',[]):coverage.setdefault(str(e.get('provider','UNKNOWN')).lower(),{'state':'REVIEWED','available':True})
    return candidates[:100],coverage


def sync_learning_contract(inputs, store, now):
    added=0
    for item in store.rows():
        r=item['record'];pid=r['proposal_id'];additional,coverage=cached_evidence(item,inputs)
        bundle=evidence_bundle(r,item['detail'],now,additional=additional,coverage=coverage)
        # Exclude observer clock: stable cache evidence replays without daily noise.
        fingerprint=digest(bundle);aid=digest(['optimization',r['type'],pid,r['revision'],item['payload_hash']])
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            local_record(db,aid,'LEGACY_PROPOSAL_OBSERVED',{'type':r['type'],'identity':pid},now,
                before={'historical_execution':'UNKNOWN'},after={'revision':r['revision'],'payload_hash':item['payload_hash']},
                reason='Observe existing immutable proposal; no historical execution or learning is inferred',
                proposal_id=pid,evidence_refs=r['source_evidence'],exact_versions={'revision':r['revision'],'payload_hash':item['payload_hash']})
            prior=db.execute("SELECT evidence_json FROM action_evidence WHERE action_id=? AND kind='optimization_bundle' ORDER BY event_id DESC LIMIT 1",(aid,)).fetchone()
            if prior and json.loads(prior['evidence_json'])['fingerprint']==fingerprint:continue
            ActionEvidence.append(db,aid,'optimization_bundle',{'fingerprint':fingerprint,'bundle':bundle},now);added+=1
    return {'bundles_updated':added,'provider_reads':0,'provider_writes':0,'historical_learning_count':len(store.learning_records())}


def sync_todo_lifecycle(store, view, now):
    current={p['priority_id']:p for p in view['priorities']}
    known={}
    with store.connect() as db:
        for row in db.execute("SELECT evidence_json FROM action_evidence WHERE kind='todo_lifecycle' ORDER BY event_id"):
            value=json.loads(row['evidence_json']);known[value['priority_id']]=value
    for pid in set(current)|set(known):
        p=current.get(pid);old=known.get(pid)
        if p:
            event=p.get('lifecycle',{}).get('latest_authoritative_event')
            state=p.get('actionability','UNKNOWN');reason=p.get('reason_code') or p['why']
            next_state={'priority_id':pid,'actionability':state,'latest_event':event,
                'proposal_ids':p.get('proposal_ids',[]),'evidence':p.get('evidence',[]),
                'decision_card_id':p.get('decision_card',{}).get('audit_record_id'),'reason':reason,'context':p.get('target_object') or (p.get('targets') or [{}])[0]}
        else:
            next_state={**old,'actionability':'SUPPRESSED','reason':'No longer an active canonical priority; owner feedback or current lifecycle determines suppression'}
            feedback=store.feedback_latest().get(('PRIORITY',pid))
            proposal_feedback=next((store.feedback_latest().get(('PROPOSAL',i)) for i in old.get('proposal_ids',[]) if store.feedback_latest().get(('PROPOSAL',i))),None)
            feedback=feedback or proposal_feedback
            from .lifecycle_truth import context_key
            ctx=old.get('context',{})
            state=view.get('commercial_states',{}).get(context_key(ctx),{}) if ctx.get('system') and ctx.get('entity_type') and ctx.get('entity_id') else {}
            next_state['latest_event']=feedback and {'feedback_id':feedback['id'],'choice':feedback['choice']} or state.get('latest_authoritative_event') or old.get('latest_event')
            next_state['reason']='Owner feedback: '+feedback['choice'] if feedback else state.get('reason_code') or next_state['reason']
        signature=digest({k:next_state.get(k) for k in ('priority_id','actionability','latest_event','proposal_ids','decision_card_id','reason')})
        if old and old.get('signature')==signature:continue
        completed=bool(p and p.get('lifecycle',{}).get('completion_evidence'))
        transition='CREATED' if old is None else 'COMPLETED' if completed else 'SUPPRESSED' if next_state['actionability'] in {'SUPPRESSED','NO_ACTION','WAITING_EXTERNAL','DONE'} else 'REOPENED' if old['actionability'] in {'SUPPRESSED','NO_ACTION','DONE'} else 'UPDATED'
        aid=digest(['todo',pid,signature,old.get('audit_action_id') if old else None]);next_state.update(signature=signature,transition=transition,audit_action_id=aid)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            local_record(db,aid,'TODO_'+transition,{'type':'BUSINESS_PRIORITY','identity':pid},now,
                before=old,after=next_state,reason=next_state['reason'],priority_id=pid,evidence_refs=next_state['evidence'])
            ActionEvidence.append(db,aid,'todo_lifecycle',next_state,now)
    return len(current)
