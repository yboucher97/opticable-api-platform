"""Fixed root orchestrator for new intake and native, human/Finance triggers.

No service queue, journal row, UI endpoint or environment flag grants authority.
Every provider effect needs root source evidence, an exact fresh authorization,
conditional CRM version and a create-only off-host fence. Uncertainty stops writes.
"""
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import unicodedata

from . import lifecycle_control as lc
from .lifecycle import (ATTR_FIELDS, OWNER, SITE_FIELDS, accepted_plan, attribution,
    aware, digest, email_or_empty, finance_relationship, next_followup,
    plan_intake, site_fields, site_match, verify_receipt)

ROOT=lc.REAL_ROOT
FAMILY='REAL_LEAD_INTERNAL_AUTOMATION_V1'
DISPLAY=Path('/run/optibrain-readiness/lifecycle.json')
MAX_NEW=20
MAX_EFFECTS=12

class HumanAttention(ValueError):pass
class UnsafeOutcome(ValueError):pass

def atomic(path,value,mode=0o600,*,immutable=False):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n'
    if immutable and path.exists():
        if lc.trusted_json(path,1048576)!=value:raise UnsafeOutcome('Immutable root evidence conflicts')
        return
    temp=path.with_name('.'+path.name+'.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'w') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.chmod(temp,mode);os.replace(temp,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def synthetic(value):
    raw=json.dumps(value,ensure_ascii=False).upper()
    if any(x in raw for x in ('OPTIBRAIN TEST','TEST ONLY','TEST_ONLY','PHASE16','PHASE 16','PHASE17','PHASE 17')):return True
    identity=email_or_empty(value.get('Email',value.get('email')))
    return bool(value.get('OptiBrain_Test') is True or identity in {'logs@opticable.ca','yboucher@opticable.ca'}
                or identity.endswith(('@example.com','@example.net','@example.org','.invalid'))
                or 'hckyan97+obp' in identity)

def human_transition(record,timeline,activation,module,field,desired):
    """Latest status transition, across ALL sources, must be the owner's CRM UI."""
    if record.get(field)!=desired or synthetic(record):return False
    changes=[]
    for row in timeline:
        if (str((row.get('record') or {}).get('id'))!=str(record.get('id'))
                or ((row.get('record') or {}).get('module') or {}).get('api_name')!=module):continue
        for change in row.get('field_history',[]):
            if change.get('api_name')==field:changes.append((aware(row['audited_time']),row,change))
    if not changes:return False
    at,row,change=max(changes,key=lambda x:x[0]);value=change.get('_value') or {}
    return (at>=aware(activation) and row.get('source')=='crm_ui'
            and str((row.get('done_by') or {}).get('id'))==OWNER
            and value.get('new')==desired and value.get('old')!=desired)

def human_qualification(record,timeline,activation):
    return human_transition(record,timeline,activation,'Leads','Lead_Status','Pre-Qualified')

def folded(value):
    value=''.join(c for c in unicodedata.normalize('NFKD',str(value or '').casefold()) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]','',value)

def safe_site_match(sites,account_id,address):
    match=site_match(sites,account_id,address)
    if match['decision']!='CREATE':return match
    # Potential formatting collisions require review, never fuzzy merging.
    postal=folded(address.get('postal_code'));number=re.findall(r'\d+',str(address.get('street','')))
    for row in sites:
        if str((row.get('Linked_Account') or {}).get('id'))!=str(account_id):continue
        other=re.findall(r'\d+',str(row.get(SITE_FIELDS['street']) or ''))
        if postal and folded(row.get(SITE_FIELDS['postal_code']))==postal and number and other and number[0]==other[0]:
            return {'decision':'HUMAN','reason':'Possible address formatting/unit collision; choose site in CRM'}
    return match

def same(actual,desired):
    if actual is None and desired=='':return True
    if isinstance(actual,dict) and isinstance(desired,dict):return str(actual.get('id'))==str(desired.get('id'))
    if isinstance(actual,str) and isinstance(desired,str) and 'T' in desired:
        try:return aware(actual)==aware(desired)
        except ValueError:pass
    return actual==desired

def safe_conversion_references(lead,accounts,contacts,protected):
    """Protect against implicit native conversion matches, including equal names."""
    mail=email_or_empty(lead.get('Email'));company=folded(lead.get('Company'))
    name=folded(str(lead.get('First_Name') or '')+' '+str(lead.get('Last_Name') or ''))
    matches=[c for c in contacts if email_or_empty(c.get('Email'))==mail]
    names=[c for c in contacts if folded(str(c.get('First_Name') or '')+' '+str(c.get('Last_Name') or ''))==name]
    candidates=[a for a in accounts if company and folded(a.get('Account_Name'))==company]
    if len(matches)>1 or len(candidates)>1 or any(str(r['id']) in protected or synthetic(r) for r in matches+candidates+names):
        raise HumanAttention('Ambiguous, TEST or protected conversion association')
    contact=matches[0] if matches else None;account=candidates[0] if candidates else None
    if any(not contact or str(c['id'])!=str(contact['id']) for c in names):raise HumanAttention('Native conversion could match another person by name')
    if contact:
        aid=str((contact.get('Account_Name') or {}).get('id') or '')
        account=next((a for a in accounts if str(a['id'])==aid),None)
        if (not account or str(account['id']) in protected or synthetic(account)
                or company and folded(account.get('Account_Name'))!=company):
            raise HumanAttention('Contact/company relationship requires owner decision')
    if not company and not account:raise HumanAttention('Customer/company required in CRM before conversion')
    return account,contact

def conversion_deal(lead,now=None):
    now=now or datetime.now(timezone.utc)
    fields={k:v for k,v in lead.items() if k in ATTR_FIELDS|{'Google_GCLID','Google_GBRAID','Google_WBRAID','Meta_FBCLID','Inquiry_ID'} and v not in (None,'')}
    return {'Deal_Name':(str(lead.get('Company') or lead['Last_Name'])+' — '+str(lead.get('Service_Types') or 'New opportunity'))[:120],
        'Stage':'Qualification','Closing_Date':(now+timedelta(days=30)).date().isoformat(),
        'Service_Types':lead.get('Service_Types') or '', 'Description':str(lead.get('Description') or '')[:4000],**fields}

class Engine:
    def __init__(self,client,*,dry_run=False):
        if os.geteuid()!=0:raise ValueError('Root orchestrator required')
        self.policy=lc.read_policy()
        if self.policy['test_scopes'] or not self.policy['real_scopes']:raise ValueError('Real runner requires TEST scopes closed')
        self.run=self.policy['test_run'];self.client=client;self.dry_run=dry_run
        ROOT.mkdir(mode=0o700,exist_ok=True)
        self.lock=os.open(ROOT/'lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.state=lc.trusted_json(ROOT/'state.json',4194304) if (ROOT/'state.json').exists() else {'schema':1,'run':self.run,'receipts':{},'leads':{},'deals':{},'effects':{},'attention':{}}
        if self.state['run']!=self.run:raise UnsafeOutcome('State is from another activation; reconcile, never reset')
        self.ownership=lc.trusted_json(lc.REAL_REGISTRY,1048576) if lc.REAL_REGISTRY.exists() else {'schema':1,'run':self.run,'records':{}}
        if self.ownership['run']!=self.run:raise UnsafeOutcome('Ownership activation changed')
        self.protected={str(i) for m in lc.trusted_json(lc.BASELINE)['modules'].values() for i in m.get('protected_versions',{})}
        self.effects=0;self.reads=0;self.plans=[]
        self.source=None
        self.journal=lc.LifecycleJournal('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
        from .remote_effects import RemoteEffects
        self.remote=RemoteEffects.root_store()
        if (ROOT/'HOLD.json').exists() and not dry_run:raise UnsafeOutcome('Recovery HOLD: independent effect reconciliation required')
        self.save()
    def save(self):
        if self.dry_run:return
        atomic(ROOT/'state.json',self.state);atomic(lc.REAL_REGISTRY,self.ownership)
    def get(self,path,query=None,*,service='zohoapis',headers=None):
        self.reads+=1
        if self.reads>160:raise HumanAttention('Provider-read bound reached; continue next cycle')
        try:return self.client.request(service,'GET',path,query=query or {},headers=headers or {})['data']
        except Exception as exc:raise HumanAttention('Provider read unavailable; preserve state and retry observation later') from exc
    def list(self,module,fields=None):
        fields=fields or ','.join(sorted(lc.FIELDS.get(module,set())|{'id','Created_Time','Modified_Time'}))
        rows=[]
        for page in range(1,6):
            value=self.get('/crm/v8/'+module,{'fields':fields,'per_page':200,'page':page}) or {}
            rows.extend(value.get('data') or [])
            if not value.get('info',{}).get('more_records'):return rows
        raise HumanAttention('Complete CRM inventory exceeds read bound')
    def record(self,module,identity):
        value=self.get('/crm/v8/'+module+'/'+str(identity)) or {}
        if len(value.get('data',[]))!=1:raise UnsafeOutcome('Exact provider record unavailable')
        return value['data'][0]
    def register(self,module,record,*,reference=False,source=None):
        identity=str(record['id'])
        if identity in self.protected or synthetic(record):raise UnsafeOutcome('Protected or TEST record cannot acquire real lineage')
        item={'module':module,'ownership':'REAL_REFERENCE' if reference else 'REAL_NEW','run':self.run,
              'created_at':record.get('Created_Time') or datetime.now(timezone.utc).isoformat(),
              'source':source or self.source['source'],'source_key':digest(self.source)}
        if not reference and aware(item['created_at'])<aware(self.policy['activated_at']):raise UnsafeOutcome('New effect returned an old provider record')
        old=self.ownership['records'].get(identity)
        if old and (old['module']!=module or old['ownership']=='REAL_REFERENCE' and not reference):
            raise UnsafeOutcome('Real lineage conflicts')
        if not old:self.ownership['records'][identity]=item
        self.save()
    def trigger(self,value):
        value={**value,'eligible':True};key=digest(value)
        if not self.dry_run:atomic(ROOT/'sources'/(key+'.json'),value,immutable=True)
        self.source=value;return key
    def attention(self,key,context,reason,action='Review in CRM',module='Leads',identity=''):
        self.state['attention'][key]={'context':context,'why':reason,'next_action':action,'module':module,'identity':str(identity),'priority':'HIGH','source':'Native CRM and scoped lifecycle','freshness':datetime.now(timezone.utc).isoformat()}
        self.save()
    def hold(self,reason,effect=None):
        if not self.dry_run:atomic(ROOT/'HOLD.json',{'at':datetime.now(timezone.utc).isoformat(),'reason':reason,'action_id':effect.action_id if effect else None})
        raise UnsafeOutcome(reason)
    def call(self,key,scope,path,body,*,headers=None,verify):
        envelope={'service':'zohoapis','method':'PUT' if headers and 'If-Unmodified-Since' in headers else 'POST','path':path,
                  'body':body,'headers':headers or {},'content_type':'application/json','query':{}}
        effect=lc.LifecycleEffect(self.run+':'+key,envelope)
        old=self.state['effects'].get(key)
        if old:
            if old['payload_hash']!=effect.payload_hash:self.hold('Immutable effect plan changed',effect)
            if old['state']!='verified':self.hold('Existing attempt requires read-only reconciliation',effect)
            return old['record']
        if self.effects>=MAX_EFFECTS:raise HumanAttention('Effect bound reached; safe continuation next cycle')
        self.plans.append({'action_id':effect.action_id,'scope':scope,'path':path,'payload_hash':effect.payload_hash})
        if self.dry_run:return None
        if self.source is None:raise UnsafeOutcome('Independent trigger evidence required')
        # Independent root intent BEFORE claiming and BEFORE a provider effect.
        auth={'action_id':effect.action_id,'payload_hash':effect.payload_hash,'scope':scope,'family':FAMILY,
              'run':self.run,'eligible':True,'policy_hash':digest(self.policy),'source_key':digest(self.source),
              'source_hash':digest(self.source),'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        atomic(ROOT/'authorizations'/(effect.action_id+'.json'),auth,immutable=True)
        lc.validate_request('zohoapis',envelope['method'],path,body,envelope['headers'],'application/json',{},scope=scope,mode='REAL_NEW',run=self.run)
        lc.check_real_effect(effect,scope,self.run)
        self.journal.intent(effect)
        try:claim=self.remote.claim(effect)
        except Exception:self.hold('Off-host claim is unavailable or uncertain',effect)
        if not claim.fresh:self.hold('Off-host claim already exists; state loss cannot authorize replay',effect)
        self.state['effects'][key]={'state':'attempted','action_id':effect.action_id,'payload_hash':effect.payload_hash,'scope':scope,'trigger':auth['source_key'],'envelope':envelope,'at':datetime.now(timezone.utc).isoformat()};self.save()
        self.journal.append(effect,'attempted',{'ownership':'REAL_NEW','family':FAMILY,'scope':scope,'source_key':auth['source_key']})
        try:
            with lc.exact_call(self.client,effect,claim,self.journal,mode='REAL_NEW',run=self.run,scope=scope):
                response=self.client.request('zohoapis',envelope['method'],path,body=body,headers=envelope['headers'],reason='Scoped new-record internal lifecycle',confirm=True)
            self.journal.append(effect,'provider_ack',response)
            record=verify(response['data'])
            identity=str(record['id']);self.remote.complete(effect,identity)
            self.state['effects'][key].update(state='verified',record=record,provider_id=identity,response=response['data']);self.save()
            self.journal.append(effect,'verified',{'provider_id':identity,'record':record,'scope':scope})
            self.effects+=1;return record
        except Exception as exc:
            self.journal.append(effect,'exception',{'type':type(exc).__name__})
            self.hold('Provider outcome or readback uncertain; no automatic retry',effect)
    def create(self,key,module,row):
        old=self.state['effects'].get(key)
        if old and old['state']=='verified':return self.record(module,old['provider_id'])
        def verify(data):
            item=(data.get('data') or [{}])[0]
            if item.get('code')!='SUCCESS':raise UnsafeOutcome('CRM create not acknowledged')
            record=self.record(module,item['details']['id'])
            if any(not same(record.get(k),v) for k,v in row.items()):raise UnsafeOutcome('CRM ignored requested field')
            self.register(module,record);return record
        return self.call(key,lc.MODULE_SCOPE[module],'/crm/v8/'+module,{'data':[row],'trigger':[],'skip_feature_execution':[{'name':'cadences'}]},verify=verify)
    def update(self,key,module,record,patch):
        if synthetic(record):raise HumanAttention('Record is now marked TEST; exclude from real automation')
        if all(same(record.get(k),v) for k,v in patch.items()):return record
        old=self.state['effects'].get(key)
        if old:
            if old['state']!='verified':self.hold('Existing update requires reconciliation')
            # Never rewind a verified effect after human/provider progress.
            return record
        def verify(data):
            item=(data.get('data') or [{}])[0]
            if item.get('code')!='SUCCESS':raise UnsafeOutcome('CRM update not acknowledged')
            actual=self.record(module,record['id'])
            if any(not same(actual.get(k),v) for k,v in patch.items()):raise UnsafeOutcome('CRM conditional update readback differs')
            return actual
        return self.call(key,lc.MODULE_SCOPE[module],'/crm/v8/'+module+'/'+record['id'],
            {'data':[{'id':record['id'],**patch}],'trigger':[],'skip_feature_execution':[{'name':'cadences'}]},
            headers={'If-Unmodified-Since':record['Modified_Time']},verify=verify)
    def task(self,key,module,record,subject,description,due=None):
        # One deterministic task; owner completion/defer is never reopened.
        row={'Subject':subject,'What_Id':{'id':record['id']},'$se_module':module,'Status':'Not Started',
            'Description':description,'Owner':{'id':OWNER},'Send_Notification_Email':False}
        if due:row['Due_Date']=due
        return self.create('task:'+key,'Tasks',row)
    def intakes(self,receipts):
        leads=self.list('Leads');contacts=self.list('Contacts','id,Email,Phone,First_Name,Last_Name,Account_Name,OptiBrain_Test')
        for receipt in sorted(receipts,key=lambda r:r.get('occurred_at','')):
            # Skip old generations without assuming they have the new payload schema.
            if aware(receipt['occurred_at'])<aware(self.policy['activated_at']):continue
            key=receipt['inquiry_id']
            if key in self.state['receipts']:continue
            if receipt.get('source') not in self.policy['approved_sources']:continue
            payload=verify_receipt(receipt)
            if synthetic(payload):continue
            if len(self.state['leads'])>=MAX_NEW:
                self.attention('volume','New inquiries','20-record verification bound reached; engineer reviews before extending');break
            self.trigger({'kind':'intake','source':receipt['source'],'occurred_at':receipt['occurred_at'],'receipt':receipt})
            plan=plan_intake(receipt,leads,contacts,protected_ids=self.protected,activation_at=self.policy['activated_at'])
            if plan['decision'] not in {'CREATE','UPDATE'}:
                self.attention('intake:'+key,payload.get('name'),plan['reason']);continue
            if plan['decision']=='UPDATE':
                record=next(r for r in leads if r['id']==plan['record_id'])
                if self.ownership['records'].get(record['id'],{}).get('ownership')!='REAL_NEW':
                    self.attention('intake:'+key,payload.get('name'),'Existing Lead has no post-activation lineage');continue
                patch=dict(plan['patch']);patch.pop('Description',None)  # retain previous inquiry notes
                if not payload.get('phone'):patch.pop('Normalized_Phone',None)
                record=self.update('intake:'+key,'Leads',record,patch)
            else:record=self.create('intake:'+key,'Leads',plan['patch'])
            if self.dry_run:continue
            task=self.task('lead:'+record['id'],'Leads',record,'Review new inquiry',payload.get('message',''),record['Next_Followup_At'][:10])
            self.state['leads'].setdefault(record['id'],{'source':receipt['source'],'inquiry_id':key,'task_id':task['id']})
            self.state['receipts'][key]={'lead_id':record['id'],'source_key':digest(self.source)};self.save()
            leads=[r for r in leads if r['id']!=record['id']]+[record]
            self.state['attention'].pop('intake:'+key,None)
    def conversions(self):
        if not self.state['leads']:return
        accounts=self.list('Accounts','id,Account_Name,OptiBrain_Test,Created_Time,Modified_Time')
        contacts=self.list('Contacts','id,Email,First_Name,Last_Name,Account_Name,OptiBrain_Test,Created_Time,Modified_Time')
        for identity,lineage in list(self.state['leads'].items()):
            if lineage.get('deal_id'):continue
            lead=self.record('Leads',identity)
            if lead.get('Lead_Status')!='Pre-Qualified':continue
            history=self.get('/crm/v8/Leads/'+identity+'/__timeline',{'per_page':200}) or {}
            if history.get('info',{}).get('more_records'):raise HumanAttention('Qualification timeline incomplete')
            timeline=history.get('__timeline') or []
            if not human_qualification(lead,timeline,self.policy['activated_at']):
                self.attention('qualification:'+identity,lead.get('Company') or lead.get('Last_Name'),'Qualify in the CRM UI; API/workflow status is not an owner trigger',identity=identity);continue
            account,contact=safe_conversion_references(lead,accounts,contacts,self.protected)
            self.trigger({'kind':'human_qualification','source':lineage['source'],'occurred_at':datetime.now(timezone.utc).isoformat(),'record':lead,'timeline':timeline})
            for module,row in [('Accounts',account),('Contacts',contact)]:
                if row:self.register(module,row,reference=True)
            deal=conversion_deal(lead)
            row={'overwrite':False,'notify_lead_owner':False,'notify_new_entity_owner':False,'Deals':deal}
            if account:row['Accounts']={'id':account['id']}
            if contact:row['Contacts']={'id':contact['id']}
            def verify(data):
                response=(data.get('data') or [{}])[0]
                if response.get('code')!='SUCCESS':raise UnsafeOutcome('Native conversion not acknowledged')
                result={k:str(v.get('id')) if isinstance(v,dict) else str(v) for k,v in response['details'].items() if k in {'Accounts','Contacts','Deals'}}
                if set(result)!={'Accounts','Contacts','Deals'}:raise UnsafeOutcome('Native conversion IDs incomplete')
                for module,prior in [('Accounts',account),('Contacts',contact),('Deals',None)]:
                    actual=self.record(module,result[module])
                    if prior and actual['id']!=prior['id']:raise UnsafeOutcome('Native reuse returned wrong customer')
                    if prior:
                        metadata={'Modified_Time','Change_Log_Time__s'}
                        # Snapshots of all business fields prevent silent native overwrites.
                        before=self.source['parents'][module]
                        if any(not same(actual.get(k),v) for k,v in before.items() if k not in metadata and not k.startswith('$')):
                            raise UnsafeOutcome('Native reuse changed parent business content')
                    self.register(module,actual,reference=bool(prior))
                current=self.record('Deals',result['Deals'])
                if str((current.get('Account_Name') or {}).get('id'))!=result['Accounts'] or str((current.get('Contact_Name') or {}).get('id'))!=result['Contacts']:
                    raise UnsafeOutcome('Converted Deal associations disagree')
                return {'id':result['Deals'],'conversion':result}
            parents={module:self.record(module,p['id']) for module,p in [('Accounts',account),('Contacts',contact)] if p}
            self.trigger({**self.source,'parents':parents})
            converted=self.call('convert:'+identity,'crm.lead.convert','/crm/v8/Leads/'+identity+'/actions/convert',{'data':[row]},verify=verify)
            if self.dry_run:continue
            result=converted['conversion'];lineage['deal_id']=result['Deals'];self.state['deals'][result['Deals']]={'lead_id':identity,'source':lineage['source'],'account_id':result['Accounts'],'contact_id':result['Contacts'],'site_address':{'street':lead.get('Street'),'city':lead.get('City'),'province':lead.get('State'),'postal_code':lead.get('Zip_Code'),'country':lead.get('Country')}};self.save()
            if lineage.get('task_id'):
                task=self.record('Tasks',lineage['task_id'])
                if task.get('Status') in {'Not Started','In Progress'}:
                    self.update('qualified-task:'+identity,'Tasks',task,{'Status':'Completed'})
            # Attribution enrichment is allowed only on a newly created Contact.
            if not contact:
                c=self.record('Contacts',result['Contacts']);patch=attribution({'attribution':{k.casefold():v for k,v in lead.items() if k in ATTR_FIELDS}},c)
                patch.update({k:lead[k] for k in ('Google_GCLID','Google_GBRAID','Google_WBRAID','Meta_FBCLID') if lead.get(k)})
                if patch:self.update('contact-context:'+identity,'Contacts',c,patch)
            self.task('prepare-estimate:'+result['Deals'],'Deals',self.record('Deals',result['Deals']),'Prepare estimate in Zoho Finance','Review scope, design and pricing. Create/send the native Finance Estimate from this Deal.')
            accounts=self.list('Accounts','id,Account_Name,OptiBrain_Test,Created_Time,Modified_Time')
            contacts=self.list('Contacts','id,Email,First_Name,Last_Name,Account_Name,OptiBrain_Test,Created_Time,Modified_Time')
    def sites(self):
        if not self.state['deals']:return
        sites=self.list('Service_Locations')
        for identity,lineage in self.state['deals'].items():
            deal=self.record('Deals',identity)
            self.trigger({'kind':'converted_deal','source':lineage['source'],'occurred_at':deal['Created_Time'],'record':deal})
            direct=(deal.get('Service_Location') or {}).get('id')
            if direct:
                site=self.record('Service_Locations',direct)
                if str((site.get('Linked_Account') or {}).get('id'))!=lineage['account_id']:self.hold('Wrong Deal/site Account association')
                self.register('Service_Locations',site,reference=str(direct) not in self.ownership['records'])
                lineage['site_id']=str(direct);self.save();continue
            match=safe_site_match(sites,lineage['account_id'],lineage['site_address'])
            if match['decision']=='HUMAN':
                self.attention('site:'+identity,deal['Deal_Name'],match['reason'],'Choose or create Service Location in CRM',module='Deals',identity=identity);continue
            if match['decision']=='REUSE':
                site=match['record'];self.register('Service_Locations',site,reference=True)
            else:
                site=self.create('site:'+identity,'Service_Locations',{'Name':str(lineage['site_address']['street'])[:120],
                    'Linked_Account':{'id':lineage['account_id']},'Primary_Contact':{'id':lineage['contact_id']},**site_fields(lineage['site_address'])})
            if self.dry_run:continue
            self.update('deal-site:'+identity,'Deals',deal,{'Service_Location':{'id':site['id']}})
            lineage['site_id']=site['id'];self.save();sites=[s for s in sites if s['id']!=site['id']]+[site]
            self.state['attention'].pop('site:'+identity,None)
    def folder(self,key,parent,name):
        old=self.state['effects'].get(key)
        if old and old['state']=='verified':
            actual=(self.get('/workdrive/api/v1/files/'+old['provider_id'],headers={'Accept':'application/vnd.api+json'}) or {})['data']
            if actual['attributes'].get('name')!=name or actual['attributes'].get('parent_id')!=parent:self.hold('WorkDrive folder association changed')
            return actual
        listing=self.get('/workdrive/api/v1/files/'+parent+'/files',{'page[limit]':200},headers={'Accept':'application/vnd.api+json'}) or {}
        if listing.get('links',{}).get('next'):raise HumanAttention('WorkDrive directory pagination incomplete')
        matches=[f for f in listing.get('data',[]) if f.get('attributes',{}).get('name')==name]
        if len(matches)>1:raise HumanAttention('Multiple WorkDrive folders share name')
        if matches:
            actual=matches[0]
            if actual.get('attributes',{}).get('type') not in {'folder','teamfolder'}:raise HumanAttention('WorkDrive name collides with a file')
            self.register('WorkDrive',actual,reference=True);return actual
        def verify(data):
            actual=data.get('data') or {};actual=(self.get('/workdrive/api/v1/files/'+actual['id'],headers={'Accept':'application/vnd.api+json'}) or {})['data']
            if actual['attributes'].get('name')!=name or actual['attributes'].get('parent_id')!=parent:raise UnsafeOutcome('WorkDrive new folder association differs')
            self.register('WorkDrive',actual);return actual
        return self.call(key,'workdrive.folder.create','/workdrive/api/v1/files',{'data':{'type':'files','attributes':{'name':name,'parent_id':parent}}},headers={'Accept':'application/vnd.api+json'},verify=verify)
    def accepted(self,deal,lineage,observation):
        identity=deal['id'];site_id=lineage.get('site_id')
        if deal.get('Stage') in {'Closed Lost','Estimate Rejected','Closed Lost to Competition','Closed Won'}:
            raise HumanAttention('Deal is closed; respect owner suppression before preparing more work')
        if not site_id:raise HumanAttention('Choose Service Location on the Deal before acceptance automation')
        plan=accepted_plan(deal.get('Service_Types'),account_id=lineage['account_id'],deal_id=identity,site_id=site_id)
        if plan['decision']!='PREPARE_INTERNAL' or any(s['type']=='Other' for s in plan.get('services',[])):
            raise HumanAttention('Accepted Services require owner-confirmed deterministic catalog mapping')
        if deal.get('Stage') not in {'Closed Lost','Estimate Rejected','Closed Lost to Competition','Closed Won'}:
            self.update('accepted-stage:'+identity,'Deals',deal,{'Stage':'Contracts In Progress'})
        existing=self.list('Services');created=[]
        for s in plan['services']:
            matches=[r for r in existing if str((r.get('Linked_Service_Location') or {}).get('id'))==site_id and r.get('Service_Type')==s['type']]
            if len(matches)>1 or matches and str((matches[0].get('Linked_Deal') or {}).get('id'))!=identity:
                raise HumanAttention('Existing durable Service: review expansion versus reuse in CRM')
            if matches:
                service=matches[0]
                if service['id'] not in self.ownership['records']:raise HumanAttention('Service has no new-record ownership')
            else:service=self.create('service:'+identity+':'+s['type'],'Services',{'Name':s['label']+' — '+deal['Deal_Name'],
                'Linked_Service_Location':{'id':site_id},'Linked_Deal':{'id':identity},'Service_Type':s['type'],'Service_Stage':'Ready for Scheduling'})
            if service:created.append(service)
        if self.dry_run:return
        account=self.record('Accounts',lineage['account_id']);site=self.record('Service_Locations',site_id)
        activation=lc.trusted_json(ROOT/'activation.json')
        anchor={'id':activation['workdrive_parent']};self.register('WorkDrive',anchor,reference=True)
        parent=account.get('Main_Workdrive_Folder_ID')
        if parent:
            a=(self.get('/workdrive/api/v1/files/'+parent,headers={'Accept':'application/vnd.api+json'}) or {})['data'];self.register('WorkDrive',a,reference=True)
        else:a=self.folder('wd-account:'+account['id'],anchor['id'],account['Account_Name']);parent=a['id']
        self.folder('wd-general:'+account['id'],parent,'General')
        if site.get('Service_Location_Workdrive_Folder_ID'):
            folder=(self.get('/workdrive/api/v1/files/'+site['Service_Location_Workdrive_Folder_ID'],headers={'Accept':'application/vnd.api+json'}) or {})['data']
            if folder['attributes'].get('parent_id')!=parent:raise UnsafeOutcome('Site WorkDrive folder is under wrong Account')
            self.register('WorkDrive',folder,reference=True)
        else:folder=self.folder('wd-site:'+site_id,parent,site['Name'])
        contracts=self.folder('wd-contracts:'+site_id,folder['id'],'Contracts')
        if self.ownership['records'][account['id']]['ownership']=='REAL_NEW':
            self.update('wd-account-link:'+account['id'],'Accounts',account,{'Main_Workdrive_Folder_ID':parent,'Main_Workdrive_Folder_URL':'https://workdrive.zoho.com/folder/'+parent})
        if self.ownership['records'][site_id]['ownership']=='REAL_NEW':
            self.update('wd-site-link:'+site_id,'Service_Locations',site,{'Service_Location_Workdrive_Folder_ID':folder['id'],'Service_Location_Workdrive_Folder_URL':'https://workdrive.zoho.com/folder/'+folder['id']})
        contact=self.record('Contacts',lineage['contact_id'])
        recipient=email_or_empty(contact.get('Email'))
        if not recipient or str((contact.get('Account_Name') or {}).get('id'))!=account['id']:
            raise HumanAttention('Contract contact/recipient requires owner review')
        contract={'account_id':account['id'],'deal_id':identity,'site_id':site_id,'contact_id':lineage['contact_id'],
                  'estimate_id':observation['transaction_id'],'folder_id':contracts['id'],'state':'PREPARE_ONLY','external_send':False,'template_id':'325018000000115116'}
        contract['merge_context']={'account':account['Account_Name'],'contact':str(contact.get('Full_Name') or contact.get('Last_Name')),
            'recipient':recipient,'site':{k:site.get(v) for k,v in SITE_FIELDS.items()},'deal':deal['Deal_Name'],'services':[s['Name'] for s in created]}
        atomic(ROOT/'contracts'/(identity+'.json'),contract)
        installation=self.create('installation:'+identity,'Installations',{'Name':'Installation — '+deal['Deal_Name'],
            'Linked_Service':{'id':created[0]['id']},'Installation_Status':'Requested','Instructions_Notes':'Accepted estimate '+str(observation['number'])+'. Human scheduling, technician and access instructions required.'})
        for service in created:self.create('installation-link:'+identity+':'+service['id'],'Installation_X_Services',{
            'Name':'Service installation','Linked_Installation':{'id':installation['id']},'Linked_Service':{'id':service['id']}})
        self.task('send-contract:'+identity,'Deals',deal,'Send contract manually','Prepared context validated; use Zoho Sign manually. No automatic external send.')
        self.task('schedule:'+identity,'Deals',deal,'Schedule installation','Select date, technician and final access instructions in CRM. No automatic scheduling or confirmation.')
        lineage.update(service_ids=[s['id'] for s in created],installation_id=installation['id'],contract=contract,accepted=True);self.save()
    def finance(self):
        if not self.state['deals']:return
        deals=[self.record('Deals',i) for i in self.state['deals']];sites=self.list('Service_Locations');services=self.list('Services')
        for module,kind in [('CustomModule5002','estimate'),('CustomModule5001','invoice')]:
            rows=self.list(module,'id,Account_Name,Potential_Name,'+('Estimate_ID' if kind=='estimate' else 'Invoice_ID'))
            for native in rows:
                # Use the actual native association keys; no inference from customer name.
                potential=(native.get('Potential_Name') or native.get('PotentialName') or {}).get('id')
                if str(potential) not in self.state['deals']:continue
                identifier=str(native.get('Estimate_ID' if kind=='estimate' else 'Invoice_ID') or '')
                if not identifier.isdigit():raise HumanAttention('Native Finance transaction ID unavailable')
                books=(self.get('/books/v3/'+kind+'s/'+identifier,{'organization_id':'802337532'}) or {}).get(kind) or {}
                if not books.get('created_time') or aware(books['created_time'])<aware(self.policy['activated_at']):continue
                observation=finance_relationship(kind=kind,record=native,books=books,deals=deals,sites=sites,services=services)
                if observation['decision']!='OBSERVE':raise HumanAttention(observation['reason'])
                lineage=self.state['deals'][str(potential)];deal=next(d for d in deals if d['id']==str(potential))
                self.trigger({'kind':'finance_'+kind,'source':lineage['source'],'occurred_at':books['created_time'],'native':native,'books':books})
                lineage.setdefault('finance',{})[identifier]=observation;self.save()
                if kind=='estimate':
                    status=books.get('status')
                    if status in {'accepted','declined','rejected','invoiced','void'} or deal.get('Stage') in {'Closed Won','Closed Lost','Estimate Rejected','Closed Lost to Competition'}:
                        previous=self.state['effects'].get('task:quote-followup:'+identifier)
                        if previous and previous['state']=='verified':
                            task=self.record('Tasks',previous['provider_id'])
                            self.update('stop-followup:'+identifier,'Tasks',task,{'Status':'Completed'})
                    if status=='accepted':self.accepted(deal,lineage,observation)
                    elif status in {'sent','viewed'} and deal.get('Stage') not in {'Closed Won','Closed Lost','Estimate Rejected','Closed Lost to Competition'}:
                        if deal.get('Stage') in {'Qualification','Needs Analysis','Value Proposition'}:
                            self.update('estimate-sent:'+identifier,'Deals',deal,{'Stage':'Proposal/Price Quote'})
                        lineage.setdefault('sent_at',{}).setdefault(identifier,datetime.now(timezone.utc).isoformat());self.save()
                        due=next_followup(lineage['sent_at'][identifier])
                        contact=self.record('Contacts',lineage['contact_id'])
                        replied=self.reply_observed(contact,lineage['sent_at'][identifier])
                        if replied or contact.get('Email_Opt_Out') is True:
                            previous=self.state['effects'].get('task:quote-followup:'+identifier)
                            if previous and previous['state']=='verified':
                                self.update('reply-stop:'+identifier,'Tasks',self.record('Tasks',previous['provider_id']),{'Status':'Completed'})
                        elif aware(due)<=datetime.now(timezone.utc):
                            self.task('quote-followup:'+identifier,'Deals',deal,'Review quote follow-up','Check for customer response and suppression before any manual reminder. OptiBrain sends nothing.',due[:10])
                elif books.get('balance',0)>0:
                    self.task('invoice-attention:'+identifier,'Deals',deal,'Review invoice/payment status','Books remains financial truth. Observe balance/due date; all invoice and payment actions are human.',books.get('due_date'))
    def reply_observed(self,contact,since):
        from email.utils import getaddresses
        identity=email_or_empty(contact.get('Email'))
        if not identity:raise HumanAttention('Quote follow-up requires a validated Contact email')
        response=self.get('/api/accounts/1083319000000008002/messages/search',
            {'searchKey':'sender:'+identity,'start':0,'limit':100},service='mail') or {}
        rows=response.get('data')
        if not isinstance(rows,list) or len(rows)>=100:raise HumanAttention('Mail reply observation unavailable/incomplete; suppress follow-up')
        return any(identity in {email_or_empty(e) for _,e in getaddresses([str(r.get('fromAddress') or '')])}
                   and datetime.fromtimestamp(int(r['receivedTime'])/1000,timezone.utc)>=aware(since) for r in rows)
    def completions(self):
        for identity,lineage in self.state['deals'].items():
            if not lineage.get('installation_id') or lineage.get('completed'):continue
            installation=self.record('Installations',lineage['installation_id'])
            if installation.get('Installation_Status')!='Completed':continue
            history=self.get('/crm/v8/Installations/'+installation['id']+'/__timeline',{'per_page':200}) or {}
            if history.get('info',{}).get('more_records') or not human_transition(installation,history.get('__timeline') or [],self.policy['activated_at'],'Installations','Installation_Status','Completed'):
                self.attention('completion:'+identity,installation['Name'],'Record completion in the CRM UI; API/workflow completion is not a human trigger',module='Installations',identity=installation['id']);continue
            # Completion is observed, not manufactured; scheduling/execution remain human.
            self.trigger({'kind':'installation_completed','source':lineage['source'],'occurred_at':installation['Modified_Time'],'record':installation})
            for sid in lineage.get('service_ids',[]):
                service=self.record('Services',sid)
                if service.get('Service_Stage') in {'Cancelled','Suspended'}:raise HumanAttention('Service was suppressed in CRM; review completion manually')
                self.update('service-active:'+sid,'Services',service,{'Service_Stage':'Active'})
            if self.dry_run:continue
            deal=self.record('Deals',identity)
            self.task('billing:'+identity,'Deals',deal,'Review billing and support handoff','Installation complete. Human invoice creation in Finance; no automatic financial or review message.')
            lineage.update(completed=True,post_sale_eligibility='Human review required for warranty, maintenance and renewal scope');self.save()
    def publish(self,error=None):
        rows=[]
        for identity,lineage in self.state['deals'].items():
            if lineage.get('accepted') and not lineage.get('completed'):
                rows.append({'context':'Accepted work','why':'Contract and scheduling need human action','next_action':'Send contract / schedule installation in CRM','module':'Deals','identity':identity,'priority':'MEDIUM'})
        rows.extend(self.state['attention'].values())
        if error:rows.append({'context':'Internal automation paused','why':error,'next_action':'Engineer reconciles before retry','module':'','identity':'','priority':'HIGH'})
        value={'schema':1,'family':FAMILY,'at':datetime.now(timezone.utc).isoformat(),'read_only':True,'scope':'live','state':'HOLD' if (ROOT/'HOLD.json').exists() else 'DRY_RUN' if self.dry_run else 'READY',
               'eligible_leads':len(self.state['leads']),'effects_this_cycle':self.effects,'provider_reads':self.reads,'attention':rows,'plans':self.plans}
        atomic(DISPLAY,value,0o644);return value

def private_receipts():
    import httpx
    key=None
    for line in Path('/etc/optibrain/phase9-receipt-export.env').read_text().splitlines():
        if line.startswith('OPTIBRAIN_RECEIPT_EXPORT_KEY='):key=shlex.split(line.split('=',1)[1])[0]
    if not key:raise HumanAttention('Private intake export unavailable')
    rows=[];cursor=None
    for _ in range(10):
        params={'limit':100}
        if cursor:params['cursor']=cursor
        response=httpx.get('https://connect.opticable.ca/api/intake-receipts',headers={'Authorization':'Bearer '+key},params=params,timeout=30)
        response.raise_for_status();value=response.json();rows+=value['receipts'];cursor=value.get('cursor')
        if not cursor:return rows
    raise HumanAttention('Private intake export pagination exceeds bound')

def approved_form(receipt):
    from .phase9_form_receipts import MAIN_FORM
    return receipt.get('form_id')==MAIN_FORM and receipt.get('test_only') is False

def form_receipts(engine):
    """Fetch provider facts directly; the service-writable receipt ledger is not authority."""
    from .phase9_form_receipts import parse_notification, UnsupportedFormNotification
    rows=[]
    found=engine.get('/api/accounts/1083319000000008002/messages/search',
        {'searchKey':'sender:notifications@zohoforms.com','start':0,'limit':100},service='mail') or {}
    if not isinstance(found.get('data'),list) or len(found['data'])>=100:raise HumanAttention('Native form search requires bounded backfill')
    for item in found['data']:
        at=datetime.fromtimestamp(int(item['receivedTime'])/1000,timezone.utc)
        if at<aware(engine.policy['activated_at']):continue
        message=str(item['messageId']);folder=str(item['folderId'])
        if not message.isdigit() or not folder.isdigit():raise ValueError('Invalid native form Mail identity')
        base='/api/accounts/1083319000000008002/folders/'+folder+'/messages/'+message
        facts={kind:(engine.get(base+'/'+kind,{'raw':'false'} if kind=='header' else {},service='mail') or {}).get('data') for kind in ('details','content','header')}
        if any(not isinstance(v,dict) for v in facts.values()):raise HumanAttention('Form provider facts incomplete')
        try:receipt=parse_notification(message_id=message,details=facts['details'],content=facts['content'],headers=facts['header']['headerContent'],now=datetime.now(timezone.utc))
        except UnsupportedFormNotification:continue
        if not approved_form(receipt):continue  # English path unproven; never infer language from body text.
        f=receipt['fields'];at=receipt['occurred_at']
        payload={'name':f['name'],'email':receipt['submitted_email'],'phone':f['phone'],'company':f['company'],
            'service':f.get('service',''),'message':f.get('notes',''),'consent':True,
            'attribution':{prefix+k:v for prefix in ('first_','last_') for k,v in {'source':'zoho_form','site':'https://opticable.ca','touch_time':at}.items()}}
        rows.append({'schema':1,'source':'zoho_form_fr','origin':'https://opticable.ca','inquiry_id':receipt['event_id'],
            'submitted_email':receipt['submitted_email'],'occurred_at':at,'request':payload,'payload_hash':digest(payload),
            'request_hash':receipt['raw_hash'],'origin_site':'https://opticable.ca','origin_path':'/fr/contact/','provider_mail':facts})
    return rows

def run(*,dry_run=False):
    from workflow.config import load_settings
    from workflow.zoho_gateway import ZohoGatewayClient
    from workflow.zoho_oauth import ZohoOAuthManager
    settings=load_settings();engine=Engine(ZohoGatewayClient(settings.zoho_gateway,ZohoOAuthManager(settings.zoho_oauth)),dry_run=dry_run)
    try:
        for rule in ('5062683000007022006','5062683000006841055','5062683000006639142'):
            data=engine.get('/crm/v8/settings/automation/workflow_rules/'+rule)
            if any(r.get('status',{}).get('active') is not False for r in data.get('workflow_rules',[])) or not data.get('workflow_rules'):
                engine.hold('Native bypass workflow reactivated or unreadable')
        receipts=private_receipts()
        if 'zoho_form_fr' in engine.policy['approved_sources']:receipts+=form_receipts(engine)
        for work in (lambda:engine.intakes(receipts),engine.conversions,engine.sites,engine.finance,engine.completions):
            try:work()
            except HumanAttention as exc:engine.attention('review:'+getattr(work,'__name__','intake'),'Lifecycle needs review',str(exc))
    except HumanAttention as exc:
        engine.attention('bounded-review','Lifecycle needs review',str(exc));return engine.publish()
    except Exception as exc:
        if not dry_run:atomic(ROOT/'HOLD.json',{'at':datetime.now(timezone.utc).isoformat(),'reason':type(exc).__name__})
        engine.publish('Provider/effect evidence requires engineer review');raise
    return engine.publish()
