#!/usr/bin/env python3
"""Manually invoked TEST_ONLY lab. All effects use scoped central transport.

No timers call this tool. Exact root policy expires; uncertain effects are never
retried. Run IDs and provider readbacks prove ownership, independently of names.
"""
from inventory import clients, ROOT
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import httpx
import shlex
import fcntl
import traceback

REPO=Path(__file__).resolve().parents[2]
RUN='phase16-20261002-lifecycle-v1'
MARKER='OPTIBRAIN TEST — PHASE 16'
STATE=ROOT/'test-lab.json'
OWNERSHIP=ROOT/'ownership.json'
CONTROL=Path('/etc/optibrain/mutation-control.json')

def atomic(path,value,mode=0o600):
    temporary=path.with_name('.'+path.name+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,sort_keys=True,indent=2,ensure_ascii=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.chmod(temporary,mode);os.replace(temporary,path)

def same_value(actual,desired):
    if actual is None and desired=='':return True  # Zoho represents empty text as null.
    if isinstance(actual,dict) and isinstance(desired,dict):
        return str(actual.get('id'))==str(desired.get('id'))
    if isinstance(actual,str) and isinstance(desired,str) and 'T' in actual and 'T' in desired:
        try:
            a=datetime.fromisoformat(actual.replace('Z','+00:00'))
            b=datetime.fromisoformat(desired.replace('Z','+00:00'))
            if a.tzinfo is not None and b.tzinfo is not None:return a==b
        except ValueError:pass
    return actual==desired

class Lab:
    def __init__(self):
        if os.geteuid()!=0: raise ValueError('Manual root session required')
        os.umask(0o077)
        self.lock=os.open(ROOT/'test-lab.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.settings,self.client,_=clients(REPO)
        from workflow.automation.lifecycle_control import LifecycleJournal
        from workflow.automation.remote_effects import RemoteEffects
        self.journal=LifecycleJournal('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
        self.remote=RemoteEffects.root_store()
        self.state=json.loads(STATE.read_text()) if STATE.exists() else {'run':RUN,'operations':{},'scenarios':{}}
        if self.state['run']!=RUN: raise ValueError('Test run lineage changed')
        self.ownership=json.loads(OWNERSHIP.read_text()) if OWNERSHIP.exists() else {'schema':1,'run':RUN,'records':{}}
    def save(self): atomic(STATE,self.state);atomic(OWNERSHIP,self.ownership)
    def get(self,service,path,query=None,headers=None):
        return self.client.request(service,'GET',path,query=query or {},headers=headers or {})['data']
    def lists(self,module,fields):
        value=self.get('zohoapis','/crm/v8/'+module,{'fields':fields,'per_page':200})
        if value and value.get('info',{}).get('more_records'):raise ValueError('Identity inventory exceeds bound')
        return (value or {}).get('data',[])
    def receipts(self):
        key=os.environ.get('OPTIBRAIN_RECEIPT_EXPORT_KEY')
        if not key:
            for line in Path('/etc/optibrain/phase9-receipt-export.env').read_text().splitlines():
                if line.startswith('OPTIBRAIN_RECEIPT_EXPORT_KEY='):key=shlex.split(line.split('=',1)[1])[0]
        if not key:raise ValueError('Private receipt export unavailable')
        cursor=None;items=[]
        for _ in range(10):
            params={'limit':100}
            if cursor:params['cursor']=cursor
            response=httpx.get('https://connect.opticable.ca/api/intake-receipts',headers={'Authorization':'Bearer '+key},params=params,timeout=30)
            if response.status_code!=200:raise ValueError('Private receipt export denied')
            value=response.json();items+=value['receipts'];cursor=value.get('cursor')
            if not cursor:return items
        raise ValueError('Receipt export exceeded bound')
    def crm(self,module,identity):
        data=self.get('zohoapis','/crm/v8/'+module+'/'+identity)
        if not isinstance(data,dict) or len(data.get('data',[]))!=1: raise ValueError('Exact provider record unavailable')
        return data['data'][0]
    def register(self,module,identity,evidence):
        identity=str(identity)
        from workflow.automation.lifecycle_control import trusted_json, BASELINE
        baseline=trusted_json(BASELINE)
        if any(identity in v.get('protected_versions',{}) for v in baseline['modules'].values()): raise ValueError('Protected ID cannot acquire TEST ownership')
        old=self.ownership['records'].get(identity)
        row={'module':module,'ownership':'TEST_ONLY','run':RUN,'evidence':evidence,'at':datetime.now(timezone.utc).isoformat()}
        if old and any(old[k]!=row[k] for k in ('module','ownership','run')): raise ValueError('Ownership conflicts')
        if not old:self.ownership['records'][identity]=row
        self.save()
    def activate(self):
        current=json.loads(CONTROL.read_text())
        if current.get('schema')==1:
            if current['test_writes_enabled'] is not False or current['real_canary_allowed'] is not False: raise ValueError('Starting safety state changed')
            saved=ROOT/'mutation-control-before.json'
            if not saved.exists(): atomic(saved,current)
        from workflow.automation.lifecycle_control import TEST_SCOPES
        source=REPO/'apps/workflow-api/workflow'
        paths=['automation/lifecycle_control.py','automation/lifecycle.py','automation/remote_effects.py','automation/mutation_control.py','automation/crm_write_boundary.py','zoho_gateway.py']
        policy={'schema':2,'test_writes_enabled':False,'allowed_actions':['crm.task.create'],'real_canary_allowed':False,
            'lifecycle':{'enabled':True,'test_run':RUN,'test_scopes':sorted(TEST_SCOPES),'real_scopes':[],
            'activated_at':None,'approved_sources':[],'expires_at':(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),
            'source_hashes':{p:hashlib.sha256((source/p).read_bytes()).hexdigest() for p in paths},'phase16_checkpoint_sha256':None}}
        self.save();atomic(CONTROL,policy,mode=0o644)
        print('TEST_ONLY exact scopes activated; real scopes empty; legacy writers OFF; canary FALSE',flush=True)
    def call(self,key,scope,service,method,path,body,headers=None,content_type='application/json',query=None):
        from workflow.automation.lifecycle_control import LifecycleEffect,exact_call
        envelope=dict(service=service,method=method,path=path,body=body,headers=headers or {},content_type=content_type,query=query or {})
        effect=LifecycleEffect(RUN+':'+key,envelope)
        operation=self.state['operations'].get(key)
        if operation:
            if operation['payload_hash']!=effect.payload_hash: raise ValueError('Test operation payload changed; use reconciliation')
            if operation['state']=='verified': return operation['result']
            raise ValueError('Existing attempt requires independent reconciliation')
        self.journal.intent(effect)
        claim=self.remote.claim(effect)
        if not claim.fresh: raise ValueError('Existing off-host claim permits reconciliation only')
        self.state['operations'][key]={'state':'attempted','payload_hash':effect.payload_hash,'action_id':effect.action_id,'scope':scope,'at':datetime.now(timezone.utc).isoformat()};self.save()
        self.journal.append(effect,'attempted',{'ownership':'TEST_ONLY','run':RUN,'scope':scope})
        try:
            with exact_call(self.client,effect,claim,self.journal,mode='TEST_ONLY',run=RUN,scope=scope):
                response=self.client.request(service,method,path,body=body,headers=headers or {},content_type=content_type,query=query or {},
                    reason='Phase 16 owned TEST lifecycle '+key,confirm=True)
        except Exception as exc:
            provider=getattr(exc,'response',None)
            detail={'error_type':type(exc).__name__,'http_status':getattr(provider,'status_code',None)}
            if provider is not None:
                try: detail['provider']=provider.json()
                except ValueError: pass
            self.state['operations'][key]['failure']=detail;self.save();self.journal.append(effect,'exception',detail)
            raise
        self.state['operations'][key]['result']=response;self.state['operations'][key]['state']='acknowledged';self.save()
        return response
    def verified(self,key,provider_id,evidence):
        from workflow.automation.lifecycle_control import LifecycleEffect
        from workflow.automation.remote_effects import PREFIX
        operation=self.state['operations'][key]
        with self.journal.connect() as db: row=db.execute('SELECT envelope FROM lifecycle_intents WHERE action_id=?',(operation['action_id'],)).fetchone()
        effect=LifecycleEffect(RUN+':'+key,json.loads(row[0]))
        self.remote.complete(effect,str(provider_id));self.journal.append(effect,'verified',evidence)
        operation.update(state='verified',provider_id=str(provider_id),readback=evidence);self.save()
    def create(self,key,module,row):
        from workflow.automation.lifecycle_control import MODULE_SCOPE
        body={'data':[row],'trigger':[],'skip_feature_execution':[{'name':'cadences'}]}
        response=self.call(key,MODULE_SCOPE[module],'zohoapis','POST','/crm/v8/'+module,body)
        data=response.get('data',{}).get('data',[])
        if len(data)!=1 or data[0].get('code')!='SUCCESS': raise ValueError('CRM create not successful; inspect exact response')
        identity=str(data[0]['details']['id']);actual=self.crm(module,identity)
        self.register(module,identity,{'action_id':self.state['operations'][key]['action_id'],'created_at':actual.get('Created_Time')})
        ignored=[k for k,v in row.items() if not same_value(actual.get(k),v)]
        if ignored:raise ValueError('CRM create readback differs for: '+','.join(ignored))
        self.verified(key,identity,{'id':identity,'version':actual.get('Modified_Time')})
        return actual
    def update(self,key,module,identity,patch,scope=None):
        from workflow.automation.lifecycle_control import MODULE_SCOPE
        actual=self.crm(module,identity)
        prior=self.state['operations'].get(key)
        if prior:
            with self.journal.connect() as db:
                intent=db.execute('SELECT envelope FROM lifecycle_intents WHERE action_id=?',(prior['action_id'],)).fetchone()
            original=json.loads(intent[0])
            intended=original['body']['data'][0]
            if original['path']!='/crm/v8/'+module+'/'+identity or intended!={'id':identity,**patch}:
                raise ValueError('Existing update intent changed; reconciliation only')
            if prior['state'] not in {'acknowledged','verified'} or any(not same_value(actual.get(k),v) for k,v in patch.items()):
                raise ValueError('Existing effect requires independent reconciliation')
            if prior['state']=='acknowledged':
                self.verified(key,identity,{'id':identity,'version':actual['Modified_Time'],'patch':patch,'reconciled_by':'independent provider GET; no resend'})
            return actual
        body={'data':[{'id':identity,**patch}],'trigger':[],'skip_feature_execution':[{'name':'cadences'}]}
        response=self.call(key,scope or MODULE_SCOPE[module],'zohoapis','PUT','/crm/v8/'+module+'/'+identity,body,{'If-Unmodified-Since':actual['Modified_Time']})
        data=response.get('data',{}).get('data',[])
        if len(data)!=1 or data[0].get('code')!='SUCCESS':raise ValueError('CRM update not successful')
        actual=self.crm(module,identity)
        if any(not same_value(actual.get(k),v) for k,v in patch.items()):raise ValueError('CRM update readback mismatch')
        self.verified(key,identity,{'id':identity,'version':actual['Modified_Time'],'patch':patch});return actual
    def folder(self,key,name,parent):
        rows=self.get('zohoapis','/workdrive/api/v1/files/'+parent+'/files',{'page[limit]':50},headers={'Accept':'application/vnd.api+json'})
        matches=[r for r in rows.get('data',[]) if r.get('attributes',{}).get('name')==name]
        if len(matches)>1:raise ValueError('Duplicate WorkDrive folder effects')
        if matches:
            identity=matches[0]['id']
            if identity not in self.ownership['records']:raise ValueError('Existing folder lacks TEST lineage; reconcile')
            return matches[0]
        response=self.call(key,'workdrive.folder.create','zohoapis','POST','/workdrive/api/v1/files',
            {'data':{'type':'files','attributes':{'name':name,'parent_id':parent}}},headers={'Accept':'application/vnd.api+json'})
        actual=response.get('data',{}).get('data',{});identity=str(actual.get('id') or '')
        if not identity:raise ValueError('WorkDrive folder create unconfirmed')
        actual=self.get('zohoapis','/workdrive/api/v1/files/'+identity,headers={'Accept':'application/vnd.api+json'})['data']
        if actual['attributes']['name']!=name or actual['attributes']['parent_id']!=parent:raise ValueError('WorkDrive folder readback mismatch')
        self.register('WorkDrive',identity,{'action_id':self.state['operations'][key]['action_id'],'parent_id':parent})
        self.verified(key,identity,{'folder_id':identity,'parent_id':parent,'name':name});return actual

def sign(lab):
    template=lab.get('sign','/templates/325018000000115001')['templates']
    prefill=[f for doc in template.get('document_fields',[]) for f in doc.get('fields',[]) if f.get('is_mandatory')]
    texts={str(f.get('field_name') or f.get('field_label')):MARKER+' — SYNTHETIC, NO CUSTOMER CONTRACT' for f in prefill if f.get('field_category')=='textfield'}
    dates={str(f.get('field_name') or f.get('field_label')):datetime.now(timezone.utc).date().isoformat() for f in prefill if f.get('field_category')=='datefield'}
    action=template['actions'][0]
    payload={'templates':{'request_name':'[OPTIBRAIN TEST] Phase 16 synthetic lifecycle contract',
        'field_data':{'field_text_data':texts,'field_date_data':dates,'field_boolean_data':{},'field_radio_data':{}},
        'actions':[{'recipient_name':MARKER+' Test Signer','recipient_email':'yboucher@opticable.ca','action_id':action['action_id'],
            'action_type':'SIGN','role':'Signataire','signing_order':1,'verify_recipient':False,'private_notes':'TEST ONLY. No customer or financial commitment.'}],
        'notes':'[OPTIBRAIN TEST] Synthetic lifecycle validation only. No real work, customer, invoice or financial obligation.',
        'email_reminders':False}}
    body={'data':json.dumps(payload,ensure_ascii=False),'is_quicksend':'true'}
    response=lab.call('sign-general-v1','sign.test.send','sign','POST','/templates/325018000000115001/createdocument',body,content_type='application/x-www-form-urlencoded')
    request=response.get('data',{}).get('requests',{});identity=str(request.get('request_id') or '')
    if not identity.isdigit(): raise ValueError('Sign send not acknowledged')
    actual=lab.get('sign','/requests/'+identity)['requests']
    if len(actual.get('actions',[]))!=1 or actual['actions'][0].get('recipient_email')!='yboucher@opticable.ca':raise ValueError('Sign recipient readback mismatch')
    lab.register('Sign',identity,{'request_name':actual.get('request_name'),'recipient':'yboucher@opticable.ca'})
    lab.verified('sign-general-v1',identity,{'request_id':identity,'status':actual.get('request_status'),'recipient':'yboucher@opticable.ca'})
    lab.state['sign']={'request_id':identity,'status':actual.get('request_status')};lab.save()
    print('TEST Sign request',identity,'status',actual.get('request_status'),'controlled recipient verified; duplicate replay fenced',flush=True)

def inquiry(lab,scenario,origin,service,campaign):
    from workflow.automation.lifecycle import plan_intake
    from workflow.automation.lifecycle_control import digest
    key='public-'+scenario
    if key in lab.state:
        body=lab.state[key]['body']
    else:
        now=datetime.now(timezone.utc).isoformat()
        attribution={}
        for prefix in ('first_','last_'):
            attribution.update({prefix+'source':'google' if campaign=='initial' else 'referral',prefix+'medium':'cpc' if campaign=='initial' else 'referral',
                prefix+'campaign':'phase16-'+campaign,prefix+'campaign_id':'phase16-utm-id-'+campaign,
                prefix+'content':scenario,prefix+'term':'synthetic-structured-cabling',prefix+'landing_url':origin+'/fr/contact/',
                prefix+'referrer':'https://opticable.ca/services/',prefix+'site':origin,prefix+'touch_time':now})
        attribution['google_gclid']='OPTIBRAIN_TEST_SYNTHETIC_GCLID'
        body={'name':MARKER+' — Person A','company':MARKER+' — Lifecycle Company A',
            'email':' Logs@Opticable.ca ','phone':'(514) 555-0116','city':'Montréal',
            'message':MARKER+' — Synthetic '+service+' inquiry. No real customer work. '+scenario,
            'language':'en','page_path':'/fr/evaluation/' if 'ai.' in origin else '/fr/contact/',
            'inquiry_id':RUN+'-'+scenario,'source_record_id':RUN+'-'+scenario,'consent':True,'website':'',
            'service':service,'address':'123 TEST Avenue, Montréal QC H1A 1A1, Unit '+('2' if scenario=='B' else '1'),
            'attribution':attribution}
        lab.state[key]={'state':'intent','body':body,'origin':origin,'request_hash':digest(body)};lab.save()
    if lab.state[key]['state']=='intent':
        lab.state[key]['state']='attempted';lab.save()
        response=httpx.post('https://connect.opticable.ca/public/lead',headers={'Origin':origin,'Content-Type':'application/json'},json=body,timeout=60)
        lab.state[key]['response']={'status':response.status_code,'data':response.json()};lab.save()
        if response.status_code!=200 or response.json().get('action') not in {'would_create_lead','would_update_lead','would_create_deal_for_contact'}:
            raise ValueError('Public intake did not stay in centrally routed receipt mode')
        lab.state[key]['state']='acknowledged';lab.save()
    receipts=[r for r in lab.receipts() if r['inquiry_id']==body['inquiry_id']]
    if len(receipts)!=1 or receipts[0]['request_hash']!=digest(body):raise ValueError('Exactly one immutable public receipt required')
    receipt=receipts[0]
    lab.state[key]['receipt']=receipt;lab.save()
    leads=lab.lists('Leads','id,Email,Phone,Created_Time,Modified_Time,First_Source,First_Medium,First_Campaign,First_Campaign_ID,First_Content,First_Term,First_Landing_URL,First_Referrer,First_Site,First_Touch_Time')
    contacts=lab.lists('Contacts','id,Email,Account_Name')
    baseline=json.loads(Path('/etc/optibrain/protected-runtime-versions.json').read_text())
    protected={i for value in baseline['modules'].values() for i in value.get('protected_versions',{})}
    plan=plan_intake(receipt,leads,contacts,protected_ids=protected)
    if plan['decision'] not in {'CREATE','UPDATE'}:raise ValueError('Intake requires human identity review')
    patch=plan['patch'];patch['OptiBrain_Test']=True
    operation_key='intake-'+scenario
    previous=lab.state['operations'].get(operation_key)
    if previous and previous.get('failure',{}).get('http_status')==400 and previous.get('failure',{}).get('provider',{}).get('data',[{}])[0].get('code')=='INVALID_DATA':
        if plan['decision']!='CREATE' or any(r.get('Inquiry_ID')==receipt['inquiry_id'] for r in lab.lists('Leads','id,Inquiry_ID')):
            raise ValueError('Rejected create has a possible provider effect; reconcile')
        operation_key+='-validated-v2'
    if plan['decision']=='CREATE':lead=lab.create(operation_key,'Leads',patch)
    else:lead=lab.update(operation_key,'Leads',plan['record_id'],patch)
    if lead.get('Normalized_Email')!='logs@opticable.ca' or lead.get('OptiBrain_Test') is not True:raise ValueError('Intake readback mismatch')
    existing=lab.state.setdefault('lead_tasks',{}).get(str(lead['id']))
    if not existing:
        task=lab.create('intake-task-'+str(lead['id']),'Tasks',{'Subject':MARKER+' — Review inquiry '+str(lead['id']),
            'What_Id':{'id':str(lead['id'])},'$se_module':'Leads','Status':'Not Started',
            'Due_Date':str(lead['Next_Followup_At'])[:10],'Description':MARKER+' — Internal only; human qualification.','Send_Notification_Email':False,'OptiBrain_Test':True})
        lab.state['lead_tasks'][str(lead['id'])]=str(task['id'])
    lab.state.setdefault('leads',{})[scenario]=str(lead['id']);lab.state[key]['state']='verified';lab.save()
    print('Provider-backed intake',scenario,'Lead',lead['id'],'decision',plan['decision'],'task count for Lead',1,'origin',receipt['origin'],flush=True)
    return lead

def convert(lab,scenario,lead_id,account=None,contact=None):
    previous=lab.state['operations'].get('convert-'+scenario)
    if previous:
        if previous['state'] not in {'acknowledged','verified'}:raise ValueError('Conversion requires independent reconciliation')
        response=previous['result']
    else:
        lead=lab.update('qualify-'+scenario,'Leads',lead_id,{'Lead_Status':'Pre-Qualified'},scope='crm.test.transition')
        from workflow.automation.lifecycle_control import ATTR_FIELDS
        fields={k:v for k,v in lead.items() if k in ATTR_FIELDS|{'Google_GCLID','Google_GBRAID','Google_WBRAID','Meta_FBCLID'} and v is not None}
        deal={'Deal_Name':MARKER+' — Opportunity '+scenario,'Stage':'Qualification','Closing_Date':'2026-10-30',
            'Amount':0,'OptiBrain_Test':True,'Service_Types':lead['Service_Types'],'Inquiry_ID':lead['Inquiry_ID'],
            'Description':MARKER+' — Native Finance Estimate remains human. Site: '+str(lead.get('Street') or ''),**fields}
        data={'overwrite':False,'notify_lead_owner':False,'notify_new_entity_owner':False,'Deals':deal}
        if account:data['Accounts']={'id':account}
        if contact:data['Contacts']={'id':contact}
        response=lab.call('convert-'+scenario,'crm.lead.convert','zohoapis','POST','/crm/v8/Leads/'+lead_id+'/actions/convert',{'data':[data]})
    rows=response.get('data',{}).get('data',[])
    if len(rows)!=1 or rows[0].get('code')!='SUCCESS':raise ValueError('Native conversion failed')
    details=rows[0]['details']
    if not all(details.get(k) for k in ('Accounts','Contacts','Deals')):raise ValueError('Conversion relationship IDs missing')
    ids={k:str(details[k]['id'] if isinstance(details[k],dict) else details[k]) for k in ('Accounts','Contacts','Deals')}
    if previous and previous['state']=='verified' and lab.state['scenarios'].get(scenario,{}).get('conversion')==ids:
        actual=lab.crm('Deals',ids['Deals'])
        if str((actual.get('Account_Name') or {}).get('id'))!=ids['Accounts'] or str((actual.get('Contact_Name') or {}).get('id'))!=ids['Contacts']:
            raise ValueError('Verified native conversion association drifted')
        print('Native conversion replay',scenario,'read-only; no provider mutation',flush=True)
        return ids
    for module,identity in ids.items():
        actual=lab.crm(module,identity)
        if not actual.get('Created_Time') or (identity not in lab.ownership['records'] and datetime.fromisoformat(actual['Created_Time'])<datetime.fromisoformat(lab.state['public-A']['receipt']['occurred_at'])):
            raise ValueError('Conversion returned an old unowned business identity')
        lab.register(module,identity,{'native_conversion':lead_id,'created_at':actual['Created_Time']})
        if actual.get('OptiBrain_Test') is not True:lab.update('mark-'+scenario+'-'+module,module,identity,{'OptiBrain_Test':True})
    actual=lab.crm('Deals',ids['Deals'])
    if str((actual.get('Account_Name') or {}).get('id'))!=ids['Accounts'] or str((actual.get('Contact_Name') or {}).get('id'))!=ids['Contacts']:
        raise ValueError('Converted Deal customer links disagree')
    if account and ids['Accounts']!=account or contact and ids['Contacts']!=contact:raise ValueError('Native conversion failed to reuse selected TEST identity')
    person=lab.crm('Contacts',ids['Contacts'])
    from workflow.automation.lifecycle_control import ATTR_FIELDS
    carry={k:actual[k] for k in ATTR_FIELDS|{'Google_GCLID','Google_GBRAID','Google_WBRAID','Meta_FBCLID'}
        if actual.get(k) is not None and not (k.startswith('First_') and person.get(k))}
    if carry:lab.update('contact-attribution-'+scenario,'Contacts',ids['Contacts'],carry)
    lab.verified('convert-'+scenario,ids['Deals'],{'lead_id':lead_id,'native_ids':ids})
    lab.state['scenarios'].setdefault(scenario,{})['conversion']=ids;lab.save()
    print('Native conversion',scenario,ids,'reuse',bool(account),bool(contact),flush=True)
    return ids

def schema(lab):
    fields=lab.get('zohoapis','/crm/v8/settings/fields',{'module':'Deals'})['fields']
    match=[f for f in fields if f['api_name']=='Service_Location']
    if not match:
        response=lab.call('schema-deal-site-v1','crm.schema.site_lookup','zohoapis','POST','/crm/v8/settings/fields',
            {'fields':[{'field_label':'Service Location','data_type':'lookup','lookup':{'module':{'api_name':'Service_Locations'},'display_label':'Deals'}}]},query={'module':'Deals'})
        rows=response.get('data',{}).get('fields',[])
        if len(rows)!=1 or rows[0].get('code')!='SUCCESS':raise ValueError('Deal site lookup not created')
        fields=lab.get('zohoapis','/crm/v8/settings/fields',{'module':'Deals'})['fields'];match=[f for f in fields if f['api_name']=='Service_Location']
        if len(match)!=1:raise ValueError('Deal site lookup readback unavailable')
        lab.verified('schema-deal-site-v1',match[0]['id'],{'api_name':'Service_Location','module':'Deals','lookup':'Service_Locations'})
    if len(match)!=1 or match[0].get('lookup',{}).get('module',{}).get('api_name')!='Service_Locations':raise ValueError('Deal site lookup mismatch')
    print('One canonical Deal Service Location lookup verified',flush=True)

def main():
    if sys.argv[1:] not in (['prepare'],['sign'],['schema'],['intake-A'],['return-A'],['convert-A'],['workdrive-root'],['intake-B'],['intake-C'],['convert-B'],['convert-C']):raise ValueError('Unknown manual lab step')
    lab=Lab()
    if sys.argv[1]=='prepare':lab.activate()
    elif sys.argv[1]=='sign':sign(lab)
    elif sys.argv[1]=='schema':schema(lab)
    elif sys.argv[1]=='intake-A':inquiry(lab,'A','https://ai.opticable.ca','Structured Cabling','initial')
    elif sys.argv[1]=='return-A':inquiry(lab,'return-A','https://opticable.ca','Structured Cabling','return-main')
    elif sys.argv[1]=='convert-A':convert(lab,'A',lab.state['leads']['A'])
    elif sys.argv[1]=='intake-B':inquiry(lab,'B','https://ai.opticable.ca','CCTV, Structured Cabling','existing-account-new-site')
    elif sys.argv[1]=='intake-C':inquiry(lab,'C','https://opticable.ca','Access Control','existing-site-addition')
    elif sys.argv[1] in {'convert-B','convert-C'}:
        s=sys.argv[1][-1];ids=lab.state['scenarios']['A']['conversion']
        convert(lab,s,lab.state['leads'][s],ids['Accounts'],ids['Contacts'])
    elif sys.argv[1]=='workdrive-root':
        anchor=next(i for i,r in lab.ownership['records'].items() if r['module']=='WorkDrive' and 'anchor' in r['evidence'])
        folder=lab.folder('workdrive-account-v1',MARKER+' — Lifecycle Company A',anchor)
        lab.state['workdrive_account']=folder['id'];lab.save();print('TEST Account WorkDrive folder',folder['id'],'verified')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        if os.geteuid()==0:(ROOT/'test-lab-exception.txt').write_text(traceback.format_exc())
        raise SystemExit('Test lab stopped: '+type(exc).__name__)
