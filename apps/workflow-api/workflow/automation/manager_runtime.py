"""Existing internal observer hook; local evidence only, no second orchestrator."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import grp,json,os,sqlite3
from . import lifecycle_control as lc
from .manager_store import ManagerStore,ENTITY_TYPES
from .manager_intelligence import build_manager,authority_health
from .manager_sources import registry,stamp
from .manager_forms import models
from .manager_preparation import prepare,prepare_forms
from .ads_runtime import persist,invocation_origin
from .acquisition_store import digest

DATABASE=Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
DISPLAY=Path('/run/optibrain-readiness/manager.json')
PROJECTIONS=['business','recurring','sales-intelligence','sales-conversations','acquisition-intelligence',
             'trigger-intelligence','ads-intelligence','forms','status','queue-depth','lifecycle','customer-communications']


def collect(directory=Path('/run/optibrain-readiness')):
    inputs={}
    for name in PROJECTIONS:
        path=directory/(name+'.json')
        try:
            value=lc.trusted_json(path,2097152)
            if name in {'status','queue-depth'} or value.get('scope')=='live' and value.get('read_only') is True:
                inputs[name]=value
        except (OSError,ValueError):continue
    return inputs


def ref(system,kind,identifier):return {'system':system,'entity_type':kind,'entity_id':str(identifier)}
def key(r):return ':'.join(str(r[k]) for k in ('system','entity_type','entity_id'))


def relationships(inputs,store):
    """Provider native IDs and already-resolved exact associations only."""
    crosswalk={};snapshot=inputs.get('business',{}).get('snapshot',{});at=snapshot.get('observed_at')
    for name,kind,idfield in [('accounts','ACCOUNT','id'),('contacts','CONTACT','id'),('leads','LEAD','id'),('deals','DEAL','id'),
        ('sites','SERVICE_LOCATION','id'),('services','SERVICE','id'),('customers','CUSTOMER','contact_id'),
        ('books_invoices','INVOICE','invoice_id'),('profiles','RECURRING_PROFILE','recurring_invoice_id')]:
        system='BOOKS' if kind in {'CUSTOMER','INVOICE','RECURRING_PROFILE'} else 'CRM'
        for row in snapshot.get(name,[])[:500]:
            if not row.get(idfield):continue
            left=ref(system,kind,row[idfield])
            for field,other in [('Account_Name','ACCOUNT'),('Contact_Name','CONTACT'),('Linked_Account','ACCOUNT'),
                ('Service_Location','SERVICE_LOCATION'),('Linked_Service_Location','SERVICE_LOCATION'),('Linked_Deal','DEAL'),
                ('customer_id','CUSTOMER'),('zcrm_account_id','ACCOUNT'),('zcrm_potential_id','DEAL'),('estimate_id','ESTIMATE'),
                ('recurring_invoice_id','RECURRING_PROFILE')]:
                value=row.get(field);rid=value.get('id') if isinstance(value,dict) else value
                if not rid or field==idfield:continue
                other_system='BOOKS' if other in {'CUSTOMER','ESTIMATE','INVOICE','RECURRING_PROFILE'} else 'CRM'
                store.link(left,field,ref(other_system,other,rid),'PROVIDER_FACT',{'reference':field,'observed_at':at})
    for c in inputs.get('sales-conversations',{}).get('conversations',[])[:150]:
        cid=c['conversation_id'];cr=c.get('CRM_references',{});canonical=None
        for module,kind in [('Leads','LEAD'),('Accounts','ACCOUNT'),('Contacts','CONTACT'),('Deals','DEAL')]:
            ids=cr.get(module,[])
            if len(ids)==1:
                right=ref('CRM',kind,ids[0]);canonical=canonical or key(right)
                store.link(ref('OPTIBRAIN','CONVERSATION',cid),'EXACT_CRM_CONTEXT',right,'DERIVED_DETERMINISTICALLY',{'reference':cid})
        canonical=canonical or key(ref('OPTIBRAIN','CONVERSATION',cid))
        for kind in ('SALES_REPLY','CONVERSATION','CUSTOMER_EXPANSION'):
            crosswalk[key(ref('OUTREACH',kind,cid))]=canonical
        for contact in c.get('Apollo_references',{}).get('contact_ids',[]):
            crosswalk[key(ref('APOLLO','PERSON',contact))]=canonical
    for t in inputs.get('trigger-intelligence',{}).get('rows',[])[:300]:
        collision=t.get('collision',{});account_ids=collision.get('crm_account_ids',[])
        canonical=key(ref('CRM','ACCOUNT',account_ids[0])) if len(account_ids)==1 and not collision.get('ambiguous') else key(ref('OPTIBRAIN','COMPANY',t.get('company_id') or t['key']))
        people=collision.get('crm_people',[])
        if not account_ids and len(people)==1 and not collision.get('ambiguous') and people[0].get('module') in {'Leads','Contacts'}:
            canonical=key(ref('CRM','LEAD' if people[0]['module']=='Leads' else 'CONTACT',people[0]['id']))
        for system in ('OPTIBRAIN','ACQUISITION'):
            crosswalk[key(ref(system,'TRIGGER',t['key']))]=canonical
        if t.get('company_id'):
            store.link(ref('OPTIBRAIN','TRIGGER',t['key']),'SOURCE_ACTOR',ref('OPTIBRAIN','COMPANY',t['company_id']),
                'DERIVED_DETERMINISTICALLY',{'reference':t.get('source_url'),'confidence':t.get('actor_confidence')})
        if len(account_ids)==1 and not collision.get('ambiguous'):
            store.link(ref('OPTIBRAIN','COMPANY',t.get('company_id') or t['key']),'EXACT_CRM_ACCOUNT',ref('CRM','ACCOUNT',account_ids[0]),
                'DERIVED_DETERMINISTICALLY',{'reference':t['key']})
    for p in store.rows():
        r=p['record'];obj=r['target_object'];kind=obj['entity_type']
        norm={'SALES_REPLY':'CONVERSATION','OUTREACH_PROPOSAL':'PROSPECT','CUSTOMER_EXPANSION':'PROSPECT',
              'CAMPAIGN_DRAFT':'CAMPAIGN','LANDING_PAGE':'WEBSITE_PAGE'}.get(kind,kind)
        if norm in ENTITY_TYPES:
            store.link(ref('OPTIBRAIN','OPTIMIZATION_PROPOSAL',r['proposal_id']),'PROPOSES_FOR',ref(obj['system'],norm,obj['entity_id']),
                'DERIVED_DETERMINISTICALLY',{'revision':r['revision'],'reference':r['preview_location']})
    return crosswalk


def sync_events(inputs,store,now,*,origin='UNKNOWN'):
    added=0;existing=store.counts()['events']>0
    def event(source,native,version,observed,title,kind,classification='NATURAL_BUSINESS_EFFECT',truth='PROVIDER_FACT'):
        nonlocal added
        added+=store.put_event(source,str(native),digest(version),observed,now,{'title':title,'kind':kind,
            'classification':classification,'truth_class':truth,'invocation_origin':origin if source=='OPTIBRAIN' else 'UNKNOWN','source_reference':str(native),
            'change_type':'CHANGE' if existing else 'INITIAL_OBSERVATION','provider_data_copied':False})
    snapshot=inputs.get('business',{}).get('snapshot',{})
    for r in snapshot.get('leads',[])[:500]:
        event('CRM',r['id'],[r.get('Lead_Status'),r.get('$converted')],r.get('Created_Time'),'Lead observed · '+r['id'],'LEAD')
    for group,idfield,statefield in [('deals','id','Stage'),('books_invoices','invoice_id','status'),('profiles','recurring_invoice_id','status')]:
        for r in snapshot.get(group,[])[:500]:event('BOOKS' if group!='deals' else 'CRM',r[idfield],r.get(statefield),snapshot.get('observed_at'),group+' status · '+str(r.get(statefield)),group.upper())
    for c in inputs.get('sales-conversations',{}).get('conversations',[])[:150]:
        event('APOLLO_MAIL',c['conversation_id'],[c.get('last_reply_at'),c.get('reply_class')],c.get('last_reply_at') or c.get('last_verified_at'),
            'Conversation · '+str(c.get('company') or c.get('person_name')),'CONVERSATION','NATURAL_BUSINESS_EFFECT' if c.get('last_reply_at') else 'MANUAL_PROVIDER_ACTION','DERIVED_DETERMINISTICALLY')
    for p in store.rows():
        r=p['record'];event('OPTIBRAIN',r['proposal_id'],p['payload_hash'],r['updated_at'],r['recommended_change'],'PROPOSAL','UNATTENDED' if origin=='UNATTENDED' else 'OWNER_INITIATED' if origin=='MANUAL' else 'UNKNOWN','DERIVED_DETERMINISTICALLY')
    for s in registry(inputs,now):
        event('SOURCE_HEALTH',s['source_id'],s['data_health'],s['observed_at'],s['provider']+' · '+s['data_health'],'SOURCE_HEALTH','AUTOMATIC_EXISTING_WORKFLOW','DERIVED_DETERMINISTICALLY')
    for job in inputs.get('status',{}).get('activity',{}).get('jobs',[]):
        if not job.get('invocation_id') or not stamp(job.get('completed_at')):continue
        store.receipt(job['job'],job['invocation_id'],stamp(job['completed_at']),
            {'origin':job.get('origin','UNKNOWN'),'state':job.get('state','UNKNOWN'),'counters':job.get('counters',{}),
             'classification':'TEST_ONLY' if 'test' in job['job'] else 'AUTOMATIC_EXISTING_WORKFLOW',
             'effect_ownership':'OptiBrain existing scope only; Apollo/Claude sends excluded'})
    return added


def sync_priorities(inputs,store,now):
    sources=registry(inputs,now);candidates=[]
    def add(target,what,why,action,observed,*,urgency='HIGH',due=None,provider='OPTIBRAIN',deadline=None):
        at=stamp(observed)
        if not at or at>now:return
        r={'schema':1,'type':'optibrain.business_priority','priority_id':digest(['manager-attention',target]),'domain':'MANAGER',
            'targets':[target],'proposal_id':None,'what':what,'why':why,'business_impact':'Preserve qualified business attention and existing service continuity; value UNKNOWN',
            'urgency':urgency,'due_at':due,'confidence':'MODERATE','data_quality':'Deterministic native/status observation',
            'source_evidence':[{'provider':provider,'source_reference':key(target),'observed_at':at.isoformat(),
                'valid_until':deadline or (at+timedelta(days=1)).isoformat(),'freshness':'CURRENT','confidence':'MODERATE',
                'truth_class':'DERIVED_DETERMINISTIC','limitations':['No provider write authority from owner priority.']}],
            'priority_reasons':[why],'dependency':None,'blocker':None,'actor':'OWNER','can_prepare':True,
            'owner_approval_required':True,'status':'OWNER_REVIEW','created_at':now.isoformat(),'updated_at':now.isoformat(),'next_action':action}
        candidates.append({'record':r,'detail':{}})
    for a in authority_health(inputs,now):
        expiry=stamp(a.get('expires_at'))
        # October25 action appears seven days before review deadline, then remains until resolved/expired.
        if expiry and now.astimezone(__import__('zoneinfo').ZoneInfo('America/Toronto')).date().isoformat()>='2026-10-18':
            add(ref('OPTIBRAIN','BUSINESS_PRIORITY',a['authority']), 'Review '+a['authority']+' authority by October25',
                'Existing scopes expire '+a['expires_at']+'; renewal is deliberate', 'Review exact scopes/expiry with owner; never silently renew',
                inputs.get('status',{}).get('captured_at'),due='2026-10-25T23:59:00-04:00',deadline=expiry.isoformat())
    for s in sources:
        if s['required'] and s['data_health'] in {'STALE','BLOCKED','AUTH_EXPIRED','PROVIDER_ERROR','RATE_LIMITED'}:
            add(ref('OPTIBRAIN','BUSINESS_PRIORITY','source:'+s['source_id']), 'Review '+s['provider']+' data health',s['reason'],
                'Resolve source limitation; independent domains continue',now.isoformat(),provider='SOURCE_HEALTH')
    for s in inputs.get('status',{}).get('signals',[]):
        if s.get('state') in {'ACTION REQUIRED','CRITICAL','FAILED'}:
            add(ref('OPTIBRAIN','BUSINESS_PRIORITY','system:'+s['name']),s['name']+' needs attention',s.get('reason','Observed system failure'),
                'Inspect current system evidence',inputs.get('status',{}).get('captured_at'),provider='SYSTEM_HEALTH')
    snapshot=inputs.get('business',{}).get('snapshot',{})
    for lead in snapshot.get('leads',[])[:500]:
        at=stamp(lead.get('Created_Time'))
        if at and 0<=(now-at).total_seconds()<7*86400 and lead.get('Lead_Status') not in {'Converted','Lost Lead','Not Qualified'} and lead.get('$converted') is not True:
            add(ref('CRM','LEAD',lead['id']),'Review recent inquiry · '+lead['id'],'Genuine native Lead requires qualification',
                'Review CRM context and existing intake receipt; use existing scopes only',snapshot.get('observed_at'),provider='ZOHO_CRM')
    for t in inputs.get('trigger-intelligence',{}).get('rows',[])[:30]:
        if t.get('priority_class') not in {'ACT NOW','REVIEW'} or t.get('collision',{}).get('suppressed') or t.get('collision',{}).get('ambiguous'):continue
        due=t.get('closing_date');expiry=stamp(due)
        if expiry and expiry<=now:continue
        add(ref('OPTIBRAIN','TRIGGER',t['key']), 'Review '+t.get('company_name','project')+' project signal',
            t.get('why_now') or t.get('description','Source verified project'),
            'Review native tender/permit and customer/collision context; no send or bid',
            t.get('last_verified_at') or t.get('observed_at') or t.get('source_effective_at'),provider='SEAO' if 'tender' in str(t.get('kind','')).lower() or due else 'PUBLIC_TRIGGER',due=due,deadline=due,
            urgency='HIGH' if t.get('priority_class')=='ACT NOW' else 'MEDIUM')
    persist({'proposals':[],'priorities':candidates,'assets':[]},store)
    return [c['record']['priority_id'] for c in candidates]


def intake_observation(store,now):
    output={'genuine_inquiries':None,'test_submissions':None,'coverage':'UNKNOWN'};path=store.path.with_name('phase9-form-receipts.db')
    if not path.exists():return output
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
        links={r[0]:{'system':'CRM','entity_type':'LEAD' if r[1]=='Leads' else 'CONTACT','entity_id':r[2]} for r in db.execute('SELECT event_id,canonical_module,canonical_id FROM form_receipt_links') if r[1] in {'Leads','Contacts'}}
        counts=db.execute('''SELECT CASE WHEN r.test_only=1 OR t.event_id IS NOT NULL THEN 1 ELSE 0 END is_test,count(*)
            FROM form_receipts r LEFT JOIN form_test_classifications t ON r.event_id=t.event_id GROUP BY is_test''').fetchall()
        output={'genuine_inquiries':sum(n for test,n in counts if not test),'test_submissions':sum(n for test,n in counts if test),
            'coverage':'Retained immutable acknowledged native Forms receipts; not all CRM Leads or website visitors'}
        for event_id,form_id,occurred,test_only in db.execute('''SELECT r.event_id,r.form_id,r.occurred_at,
            CASE WHEN r.test_only=1 OR t.event_id IS NOT NULL THEN 1 ELSE 0 END FROM form_receipts r
            LEFT JOIN form_test_classifications t ON r.event_id=t.event_id ORDER BY r.recorded_at DESC LIMIT 100'''):
            store.put_event('ZOHO_FORMS',event_id,event_id,occurred,now,{'title':'TEST submission' if test_only else 'Genuine acknowledged inquiry',
                'kind':'FORM_SUBMISSION','classification':'TEST_ONLY' if test_only else 'NATURAL_BUSINESS_EFFECT',
                'truth_class':'PROVIDER_FACT','source_reference':event_id,'form_id':form_id,'canonical_context':links.get(event_id),
                'change_type':'INITIAL_OBSERVATION' if now-stamp(occurred)>timedelta(days=1) else 'CHANGE','provider_data_copied':False})
            if event_id in links:
                store.link(ref('ZOHO_FORMS','FORM',form_id),'ACKNOWLEDGED_NATIVE_INQUIRY',links[event_id],'PROVIDER_FACT',{'receipt_reference':event_id})
    return output


def refresh(inputs,store,now,*,origin='UNKNOWN'):
    store.setup();prep=prepare(inputs,store,now)
    form_prep=prepare_forms(inputs,store,now,maximum=3-len(prep['created']));prep['form_drafts']=form_prep['created']
    active=sync_priorities(inputs,store,now)
    crosswalk=relationships(inputs,store);added=sync_events(inputs,store,now,origin=origin);intake=intake_observation(store,now)
    from .lifecycle_projection import collect_states
    collect_states(inputs,now,store,record_facts=True)
    view=build_manager(inputs,store,now,active_ids=active,crosswalk=crosswalk)
    view.update(active_priority_ids=active,crosswalk=crosswalk,preparation=prep,intake=intake,forms=models(),
        input_version=digest({k:v.get('input_version') or v.get('observed_at') or v.get('captured_at') or v.get('at') for k,v in inputs.items()}))
    version=digest([view['brief'],now.date().isoformat()]);view['brief_id']=store.brief(view['brief']['day'],version,now,view['brief'])
    view['refresh']={'origin':origin,'events_added':added,'provider_reads':0,'provider_writes':0,'model_calls':0}
    return view


def observe(engine,*,now=None):
    if engine.dry_run:return {'state':'DRY_RUN — LOCAL MANAGER ONLY','provider_writes':0}
    from .real_internal import atomic
    now=now or datetime.now(timezone.utc)
    view=refresh(collect(),ManagerStore(DATABASE),now,origin=invocation_origin())
    # Full manager canonical state has references only, never raw datasets.
    raw=json.dumps(view,ensure_ascii=False)
    if len(raw.encode())>1048576:raise ValueError('Manager projection exceeds 1 MiB bound')
    atomic(DISPLAY,view,0o600);os.chown(DISPLAY,0,grp.getgrnam('opticable-workflow-api').gr_gid);os.chmod(DISPLAY,0o640)
    return {'state':'PREPARED','provider_reads':0,'provider_writes':0,'model_calls':0,'events_added':view['refresh']['events_added']}
