"""Exact, root-only lifecycle transport; scoped policy, lineage and off-host fence.

The API cannot manufacture this authority. Legacy grants remain independent and
disabled. Existing/uncertain claims permit reconciliation only, never resending.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

CONTROL = Path('/etc/optibrain/mutation-control.json')
REGISTRY = Path('/var/lib/optibrain/phase16-17/ownership.json')
REAL_ROOT = Path('/var/lib/optibrain/lifecycle')
REAL_REGISTRY = REAL_ROOT/'ownership.json'
BASELINE = Path('/etc/optibrain/protected-runtime-versions.json')
GRANT = ContextVar('optibrain_lifecycle_grant', default=None)
TEST_PREFIX = 'OPTIBRAIN TEST — PHASE 16'
RECIPIENT = 'yboucher@opticable.ca'
MODULE_SCOPE = {'Leads':'crm.lead.intake', 'Contacts':'crm.contact.create',
    'Accounts':'crm.account.create', 'Deals':'crm.deal.prepare',
    'Service_Locations':'crm.site.prepare', 'Services':'crm.service.create',
    'Installations':'crm.installation.prepare', 'Tasks':'crm.internal.task',
    'Cases':'crm.case.create', 'Installation_X_Services':'crm.link.create'}
TEST_SCOPES = frozenset(MODULE_SCOPE.values()) | {'crm.lead.convert',
    'crm.test.transition', 'workdrive.folder.create', 'workdrive.file.create',
    'sign.contract.prepare', 'sign.test.send', 'mail.test.send','crm.schema.site_lookup','crm.config.test_exclusion','crm.config.workflow_containment','crm.test.cleanup','crm.test.metric_marker'}
REAL_SCOPES = frozenset({'crm.lead.intake','crm.lead.convert','crm.account.create',
    'crm.contact.create','crm.deal.prepare','crm.site.prepare','crm.service.create',
    'crm.internal.task','crm.installation.prepare','crm.link.create','workdrive.folder.create',
    'crm.service.activate','crm.case.prepare'})
TRANSPORT_SOURCES = {'automation/lifecycle_control.py','automation/lifecycle.py',
    'automation/remote_effects.py','automation/mutation_control.py',
    'automation/crm_write_boundary.py','zoho_gateway.py'}
REFERENCES = {'Account_Name':'Accounts','Contact_Name':'Contacts','Linked_Account':'Accounts',
    'Primary_Contact':'Contacts','Linked_Service_Location':'Service_Locations','Linked_Deal':'Deals',
    'Linked_Service':'Services','Linked_Installation':'Installations','Who_Id':'Contacts','Service_Location':'Service_Locations',
    'Related_To':'Contacts','Deal_Name':'Deals'}
FIELDS = {
 'Leads': {'Last_Name','First_Name','Company','Email','Phone','Street','City','State','Country','Zip_Code',
     'Lead_Status','Normalized_Email','Normalized_Phone','Next_Followup_At','Service_Types',
     'Description','OptiBrain_Test','Inquiry_ID','Ingestion_Source','Source_Record_ID','Owner',
     'Google_GCLID','Google_GBRAID','Google_WBRAID','Meta_FBCLID','Microsoft_MSCLKID'},
 'Contacts': {'Last_Name','First_Name','Email','Phone','Account_Name','Description','OptiBrain_Test',
     'Normalized_Email','Normalized_Phone','Inquiry_ID'},
 'Accounts': {'Account_Name','Description','OptiBrain_Test','Main_Workdrive_Folder_ID','Main_Workdrive_Folder_URL'},
 'Deals': {'Deal_Name','Account_Name','Contact_Name','Stage','Closing_Date','Amount','Service_Types',
     'Description','OptiBrain_Test','Inquiry_ID','Pipeline','Scope','Project_Timeline','Service_Location'},
 'Service_Locations': {'Name','Linked_Account','Primary_Contact','OptiBrain_Test',
     'Service_Location_Address_City','Service_Location_Address_State_Province','Service_Location_Address_Zip_Postal_Code',
     'Service_Location_Address_Country_Region','Service_Location_Address_Street_Address','Service_Location_Address_Flat_House_No_Building_Ap',
     'Service_Location_Workdrive_Folder_ID','Service_Location_Workdrive_Folder_URL'},
 'Services': {'Name','Linked_Service_Location','Linked_Deal','Service_Stage','OptiBrain_Test','Service_Type',
     'OptiBrain_Installed_On','OptiBrain_Last_Service_On'},
 'Installations': {'Name','Linked_Service','Installation_Status','Scheduled_Date','Assigned_To',
     'Instructions_Notes','Completion_Notes','Completion_Proof_Link','On_Site_Contact_Name','On_Site_Contact_Phone'},
 'Tasks': {'Subject','What_Id','$se_module','Who_Id','Status','Due_Date','Description','Owner','Send_Notification_Email'},
 'Cases': {'Subject','Account_Name','Related_To','Deal_Name','Status','Type','Description','Case_Origin'},
 'Installation_X_Services': {'Name','Linked_Installation','Linked_Service'}
}
ATTR_FIELDS = {prefix+name for prefix in ('First_','Last_') for name in
    ('Source','Medium','Campaign','Campaign_ID','Term','Content','Landing_URL','Referrer','Site','Touch_Time')}
for _module in ('Leads','Contacts','Deals'): FIELDS[_module] |= ATTR_FIELDS
for _module in ('Contacts','Deals'):
    FIELDS[_module] |= {'Google_GCLID','Google_GBRAID','Google_WBRAID','Meta_FBCLID'}
for _module in ('Tasks','Cases','Installations'): FIELDS[_module] |= {'OptiBrain_Test'}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=False).encode()).hexdigest()

def trusted_json(path, maximum=131072):
    for parent in list(path.parents)[:-1]:
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Untrusted lifecycle authority parent')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    with os.fdopen(fd) as handle:
        info=os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
                or info.st_mode & 0o022 or info.st_size > maximum):
            raise ValueError('Untrusted lifecycle authority file')
        return json.load(handle)

def read_policy():
    policy=trusted_json(CONTROL,8192)
    keys={'schema','test_writes_enabled','allowed_actions','real_canary_allowed','lifecycle'}
    if (set(policy)!=keys or policy['schema']!=2 or policy['test_writes_enabled'] is not False
            or policy['allowed_actions']!=['crm.task.create'] or policy['real_canary_allowed'] is not False):
        raise ValueError('Lifecycle requires strict scoped mutation policy')
    control=policy['lifecycle']
    if set(control)!={'enabled','test_run','test_scopes','real_scopes','activated_at','approved_sources',
            'expires_at','source_hashes','phase16_checkpoint_sha256'} or type(control['enabled']) is not bool:
        raise ValueError('Invalid lifecycle control schema')
    if (not isinstance(control['test_scopes'],list) or not set(control['test_scopes'])<=TEST_SCOPES
            or not isinstance(control['real_scopes'],list) or not set(control['real_scopes'])<=REAL_SCOPES):
        raise ValueError('Unknown lifecycle scope')
    if not control['enabled']: raise ValueError('Universal lifecycle write kill is OFF')
    expiry=datetime.fromisoformat(control['expires_at'])
    if expiry.tzinfo is None or datetime.now(timezone.utc)>=expiry: raise ValueError('Lifecycle authority expired')
    code=Path(__file__).resolve().parents[1]
    expected=TRANSPORT_SOURCES | ({'automation/real_internal.py','automation/phase9_form_receipts.py'} if control['real_scopes'] else set())
    if set(control['source_hashes'])!=expected: raise ValueError('Incomplete transport source pins')
    for name, sha in control['source_hashes'].items():
        if hashlib.sha256((code/name).read_bytes()).hexdigest()!=sha: raise ValueError('Lifecycle transport source changed')
    if control['real_scopes']:
        checkpoint=REAL_ROOT/'phase16-checkpoint.json'
        if hashlib.sha256(checkpoint.read_bytes()).hexdigest()!=control['phase16_checkpoint_sha256']:
            raise ValueError('Phase 16 checkpoint changed')
        receipt=trusted_json(checkpoint)
        if receipt.get('phase16')!='PASS' or receipt.get('safety_critical_failures')!=0:
            raise ValueError('Phase 16 did not pass')
        activation=trusted_json(REAL_ROOT/'activation.json')
        if (activation.get('family')!='REAL_LEAD_INTERNAL_AUTOMATION_V1'
                or activation.get('run')!=control['test_run']
                or activation.get('activated_at')!=control['activated_at']
                or activation.get('approved_sources')!=control['approved_sources']
                or activation.get('scopes')!=control['real_scopes']
                or not control['activated_at']
                or not set(control['approved_sources'])<={'ai_website','opticable_website','zoho_form_fr'}):
            raise ValueError('Real scope activation is not exact')
    return control

def validate_request(service,method,path,body,headers,content_type,query,*,scope,mode,run):
    if mode=='TEST_ONLY' and scope=='crm.config.workflow_containment':
        target=re.fullmatch(r'/crm/v8/settings/automation/workflow_rules/([0-9]{1,30})',path)
        plan=trusted_json(REGISTRY.parent/'native-workflow-disable-plan.json')
        if (service!='zohoapis' or method!='PUT' or not target or query or headers
                or content_type!='application/json' or plan.get('run')!=run
                or target[1] not in plan.get('rule_ids',[]) or body!={'workflow_rules':[{
                    'id':target[1],'status':{'active':False,'delete_schedule_action':False}}]}):
            raise ValueError('Native workflow containment allows only reviewed disable, with no deletion')
        return
    if mode=='TEST_ONLY' and scope=='crm.test.metric_marker':
        record=re.fullmatch(r'/crm/v8/(Tasks|Cases|Installations)/([0-9]{1,30})',path)
        if (service!='zohoapis' or method!='PUT' or not record or query or content_type!='application/json'
                or set(headers)!={'If-Unmodified-Since'} or body!={'data':[{'id':record[2],'OptiBrain_Test':True}],
                    'trigger':[],'skip_feature_execution':[{'name':'cadences'}]}):
            raise ValueError('Historical TEST marker permits one boolean only')
        old=trusted_json(Path('/var/lib/optibrain/phase8/test-lab/registry.json'))
        baseline=trusted_json(BASELINE)
        if record[2] not in old.get('records',{}).get(record[1],[]) or any(record[2] in m.get('protected_versions',{}) for m in baseline['modules'].values()):
            raise ValueError('Historical TEST marker lacks independent non-protected ownership')
        return
    if mode=='TEST_ONLY' and scope=='crm.test.cleanup':
        cleanup=trusted_json(REGISTRY.parent/'test-cleanup-plan.json')
        target=re.fullmatch(r'/crm/v8/Service_Locations/([0-9]{1,30})',path)
        if (service!='zohoapis' or method!='DELETE' or not target or body is not None or headers
                or query!={'wf_trigger':'false'} or cleanup.get('run')!=run
                or cleanup.get('id')!=target[1] or cleanup.get('unreferenced') is not True
                or datetime.now(timezone.utc)>=datetime.fromisoformat(cleanup['expires_at'])):
            raise ValueError('Only exact unreferenced owned TEST site cleanup is allowed')
        registry=trusted_json(REGISTRY);baseline=trusted_json(BASELINE)
        if any(target[1] in m.get('protected_versions',{}) for m in baseline['modules'].values()):
            raise ValueError('Protected cleanup forbidden')
        item=registry.get('records',{}).get(target[1],{})
        if item.get('ownership')!='TEST_ONLY' or item.get('run')!=run or item.get('module')!='Service_Locations':
            raise ValueError('Cleanup lacks exact TEST ownership')
        return
    if mode=='TEST_ONLY' and scope=='crm.config.test_exclusion':
        if service!='zohoapis' or headers or content_type!='application/json':
            raise ValueError('Configuration exclusion transport mismatch')
        plans=trusted_json(REGISTRY.parent/'metric-exclusion-plan.json',1048576)
        envelope=dict(service=service,method=method,path=path,body=body,headers=headers,content_type=content_type,query=query)
        if (plans.get('run')!=run or digest(envelope) not in plans.get('envelopes',{})
                or not (method=='POST' and path in {'/crm/v8/settings/fields','/crm/v8/settings/custom_views'}
                    or method=='PUT' and path=='/crm/v8/Reports')):
            raise ValueError('Exact root-reviewed exclusion plan required')
        return
    if (mode=='TEST_ONLY' and scope=='crm.schema.site_lookup' and service=='zohoapis'
            and method=='POST' and path=='/crm/v8/settings/fields' and not headers
            and content_type=='application/json' and query=={'module':'Deals'}
            and body=={'fields':[{'field_label':'Service Location','data_type':'lookup',
                'lookup':{'module':{'api_name':'Service_Locations'},'display_label':'Deals'}}]}):
        return
    if query or not isinstance(body,dict) or len(json.dumps(body))>16384:
        raise ValueError('Mutation must have one bounded canonical body and no query')
    if mode not in {'TEST_ONLY','REAL_NEW'}: raise ValueError('Unknown lifecycle ownership')
    if scope not in (TEST_SCOPES if mode=='TEST_ONLY' else REAL_SCOPES): raise ValueError('Scope forbidden for ownership')
    registry=trusted_json(REGISTRY if mode=='TEST_ONLY' else REAL_REGISTRY,1048576)
    baseline=trusted_json(BASELINE)
    protected={str(i) for m in baseline['modules'].values() for i in m.get('protected_versions',{})}
    def owned(identity, module=None, *, anchor=False, reference=True):
        identity=str(identity)
        if identity in protected: raise ValueError('Protected historical record is immutable')
        item=registry.get('records',{}).get(identity)
        if (not item or item.get('run')!=run or (item.get('ownership')!=mode
                and not (anchor and module=='WorkDrive' and mode=='TEST_ONLY' and item.get('ownership')=='TEST_ANCHOR')
                and not (reference and mode=='REAL_NEW' and item.get('ownership')=='REAL_REFERENCE'
                         and module in {'Accounts','Contacts','Service_Locations','Services','WorkDrive'}))
                or module and item.get('module')!=module):
            raise ValueError('Record reference lacks exact lifecycle lineage')
        if mode=='REAL_NEW' and item.get('ownership')=='REAL_NEW':
            control=read_policy()
            if (datetime.fromisoformat(item['created_at'])<datetime.fromisoformat(control['activated_at'])
                    or item.get('source') not in control['approved_sources']):
                raise ValueError('Real record is outside post-activation intake lineage')
        return item
    if content_type!='application/json' and not (service=='sign' and content_type=='application/x-www-form-urlencoded') and not (
            service=='zohoapis' and path=='/workdrive/api/v1/upload' and content_type=='multipart/form-data'):
        raise ValueError('Encoding is outside lifecycle boundary')
    convert=re.fullmatch(r'/crm/v8/Leads/([0-9]{1,30})/actions/convert',path)
    if service=='zohoapis' and convert:
        if method!='POST' or scope!='crm.lead.convert' or headers or set(body)!={'data'} or len(body['data'])!=1:
            raise ValueError('Invalid native Lead conversion envelope')
        owned(convert[1],'Leads',reference=False); row=body['data'][0]
        if (set(row)-{'overwrite','notify_lead_owner','notify_new_entity_owner','Accounts','Contacts','Deals'}
                or row.get('overwrite') is not False or row.get('notify_lead_owner') is not False
                or row.get('notify_new_entity_owner') is not False):
            raise ValueError('Lead conversion must suppress overwrite and notifications')
        for key in ('Accounts','Contacts'):
            if key in row:
                if not isinstance(row[key],dict) or set(row[key])!={'id'}: raise ValueError('Invalid conversion identity')
                owned(row[key]['id'],key)
        deal=row.get('Deals')
        if not isinstance(deal,dict) or not set(deal)<=FIELDS['Deals']: raise ValueError('Invalid conversion Deal')
        if mode=='TEST_ONLY' and (deal.get('OptiBrain_Test') is not True or not str(deal.get('Deal_Name','')).startswith(TEST_PREFIX)):
            raise ValueError('Conversion must carry TEST ownership')
        if mode=='REAL_NEW' and ('Amount' in deal or 'OptiBrain_Test' in deal or deal.get('Stage')!='Qualification'):
            raise ValueError('Real conversion cannot price or qualify a Deal automatically')
        return
    record=re.fullmatch(r'/crm/v8/([A-Za-z_]+)/?([0-9]{1,30})?',path)
    if service=='zohoapis' and record:
        module,target=record.groups()
        aliases={'Services':'crm.service.activate','Cases':'crm.case.prepare'}
        if module not in MODULE_SCOPE or (scope!=MODULE_SCOPE[module] and scope!=aliases.get(module)
                and not (mode=='TEST_ONLY' and scope=='crm.test.transition')):
            raise ValueError('CRM scope/module mismatch')
        if set(body)-{'data','trigger','skip_feature_execution'} or body.get('trigger')!=[] or len(body.get('data',[]))!=1:
            raise ValueError('CRM mutation must be one trigger-free record')
        if body.get('skip_feature_execution',[{'name':'cadences'}])!=[{'name':'cadences'}]:
            raise ValueError('Cadences must remain off')
        row=body['data'][0]
        if not isinstance(row,dict) or not set(row)<=FIELDS[module]|{'id'}: raise ValueError('Unreviewed CRM field')
        if target:
            owned(target,module,reference=False)
            if method!='PUT' or row.get('id')!=target or set(headers or {})!={'If-Unmodified-Since'}:
                raise ValueError('CRM update needs exact conditional version')
            if datetime.fromisoformat(headers['If-Unmodified-Since']).tzinfo is None: raise ValueError('Version needs offset')
        elif method!='POST' or headers or 'id' in row: raise ValueError('Invalid CRM create')
        if row.get('Send_Notification_Email') not in (None,False): raise ValueError('Task notification forbidden')
        if mode=='TEST_ONLY' and not target:
            title=(str(row.get('First_Name') or '')+' '+str(row.get('Last_Name') or '')).strip() if module in {'Leads','Contacts'} else row.get('Account_Name') if module=='Accounts' else row.get('Deal_Name') if module=='Deals' else row.get('Subject') if module in {'Tasks','Cases'} else row.get('Name')
            if not str(title or '').startswith(TEST_PREFIX): raise ValueError('TEST create lacks visible marker')
            if module!='Installation_X_Services' and row.get('OptiBrain_Test') is not True:
                raise ValueError('TEST create lacks boolean marker')
        for key,value in row.items():
            if isinstance(value,dict) and key!='Owner':
                if set(value)!={'id'}: raise ValueError('Invalid record reference')
                expected=row.get('$se_module') if key=='What_Id' else REFERENCES.get(key)
                if not expected: raise ValueError('Unclassified CRM reference')
                owned(value['id'],expected)
        if mode=='REAL_NEW':
            if module=='Installations' and (target or row.get('Installation_Status')!='Requested'):
                raise ValueError('Installation authority only prepares a new unscheduled visit')
            if module=='Services' and scope=='crm.service.create' and (target or row.get('Service_Stage')!='Ready for Scheduling'):
                raise ValueError('Service creation only prepares a new accepted service')
            if module=='Services' and scope!='crm.service.activate' and (
                    row.get('Service_Stage')=='Active' or any(k in row for k in ('OptiBrain_Installed_On','OptiBrain_Last_Service_On'))):
                raise ValueError('Service completion requires its individual activation scope')
            if module=='Services' and scope=='crm.service.activate':
                if (not target or not set(row)<={'id','Service_Stage','OptiBrain_Installed_On','OptiBrain_Last_Service_On'}
                        or row.get('Service_Stage')!='Active'):
                    raise ValueError('Service activation is a bounded completion update')
            if module=='Cases' and (scope!='crm.case.prepare' or target or row.get('Status')!='New'
                    or row.get('Case_Origin') not in {'Web','Email'}):
                raise ValueError('Real support authority only prepares a new linked Case')
            if any(k in row for k in {'OptiBrain_Test','Amount','Lead_Status','Scheduled_Date','Assigned_To'}):
                raise ValueError('Real test marking, qualification, pricing and scheduling are human controlled')
            if module in {'Accounts','Contacts'}:
                allowed={'id','Main_Workdrive_Folder_ID','Main_Workdrive_Folder_URL'} if module=='Accounts' else ATTR_FIELDS|{'id','Normalized_Email','Normalized_Phone','Google_GCLID','Google_GBRAID','Google_WBRAID','Meta_FBCLID'}
                if not target or not set(row)<=allowed:raise ValueError('Account/Contact creation uses native conversion; enrichment is limited')
            if module=='Deals' and 'Stage' in row and row['Stage'] not in {'Proposal/Price Quote','Contracts In Progress'}:
                raise ValueError('Real Deal stage is outside observed Finance transitions')
            if any('OPTIBRAIN TEST' in str(v).upper() or 'TEST ONLY' in str(v).upper() for v in row.values()):
                raise ValueError('Synthetic data is ineligible for real authority')
        return
    if service=='mail':
        if (mode!='TEST_ONLY' or scope!='mail.test.send' or method!='POST'
                or path!='/api/accounts/1083319000000008002/messages' or headers
                or set(body)!={'fromAddress','toAddress','subject','content','mailFormat'}
                or body['fromAddress']!=RECIPIENT or body['toAddress']!=RECIPIENT
                or not body['subject'].startswith('[OPTIBRAIN TEST]') or body['mailFormat']!='plaintext'):
            raise ValueError('Mail permits only the exact controlled TEST recipient')
        return
    if service=='zohoapis' and path=='/workdrive/api/v1/files':
        if method!='POST' or scope!='workdrive.folder.create' or headers!={'Accept':'application/vnd.api+json'}:
            raise ValueError('WorkDrive folder boundary mismatch')
        data=body.get('data',{}); attrs=data.get('attributes',{})
        if set(body)!={'data'} or set(data)!={'type','attributes'} or data['type']!='files' or set(attrs)!={'name','parent_id'}:
            raise ValueError('WorkDrive folder envelope invalid')
        owned(attrs['parent_id'],'WorkDrive',anchor=True)
        if mode=='TEST_ONLY' and not (attrs['name'].startswith(TEST_PREFIX) or attrs['name'] in {'General','Quotes','Contracts','Plans','Installation'}):
            raise ValueError('Unexpected TEST folder name')
        return
    if service=='zohoapis' and path=='/workdrive/api/v1/upload':
        if (mode!='TEST_ONLY' or method!='POST' or scope!='workdrive.file.create'
                or headers!={'Accept':'application/vnd.api+json'} or content_type!='multipart/form-data'
                or set(body)!={'parent_id','filename','content'}
                or not re.fullmatch(r'OPTIBRAIN_TEST_PHASE16_[A-C]\.txt',body.get('filename',''))
                or not isinstance(body.get('content'),str) or not body['content'].startswith(TEST_PREFIX)
                or len(body['content'].encode())>4096):
            raise ValueError('Only bounded synthetic TEST text files may be uploaded')
        owned(body['parent_id'],'WorkDrive')
        return
    if service=='sign' and re.fullmatch(r'/templates/(325018000000115001|325018000000115116)/createdocument',path):
        if method!='POST' or headers or scope not in {'sign.test.send','sign.contract.prepare'} or content_type!='application/x-www-form-urlencoded':
            raise ValueError('Sign template boundary mismatch')
        if set(body)!={'data','is_quicksend'} or body['is_quicksend']!=('true' if scope=='sign.test.send' else 'false'):
            raise ValueError('Sign preparation cannot send')
        payload=json.loads(body['data']); requests=payload.get('templates',{})
        if set(payload)!={'templates'} or set(requests)-{'request_name','field_data','actions','notes','email_reminders'}:
            raise ValueError('Unreviewed Sign request field')
        if requests.get('email_reminders') is not False:raise ValueError('Sign reminder sends forbidden')
        if mode=='TEST_ONLY' and not requests.get('request_name','').startswith('[OPTIBRAIN TEST]'): raise ValueError('Sign request lacks TEST prefix')
        actions=requests.get('actions',[])
        if (len(actions)!=1 or actions[0].get('recipient_email')!=RECIPIENT
                or set(actions[0])-{'recipient_name','recipient_email','action_id','action_type','role','signing_order','verify_recipient','private_notes'}
                or actions[0].get('action_type')!='SIGN' or actions[0].get('role')!='Signataire'
                or actions[0].get('verify_recipient') is not False):
            raise ValueError('Sign recipient is not exact controlled owner')
        if mode!='TEST_ONLY': raise ValueError('Real Sign provider preparation remains deferred; local preparation only')
        return
    raise ValueError('Provider operation is outside the lifecycle allowlist')

def check_real_effect(effect,scope,run):
    """Authority is root-only and per effect; the service-writable journal is evidence."""
    auth=trusted_json(REAL_ROOT/'authorizations'/(effect.action_id+'.json'))
    policy=read_policy()
    if (auth.get('family')!='REAL_LEAD_INTERNAL_AUTOMATION_V1' or auth.get('eligible') is not True
            or auth.get('run')!=run or run!=policy['test_run'] or auth.get('scope')!=scope
            or auth.get('payload_hash')!=effect.payload_hash or auth.get('action_id')!=effect.action_id
            or auth.get('policy_hash')!=digest(policy)
            or datetime.now(timezone.utc)>=datetime.fromisoformat(auth['expires_at'])):
        raise ValueError('Real effect lacks fresh exact root eligibility')
    source_key=auth.get('source_key','')
    if not re.fullmatch('[0-9a-f]{64}',source_key):raise ValueError('Invalid real source identity')
    source=trusted_json(REAL_ROOT/'sources'/(source_key+'.json'),1048576)
    if digest(source)!=auth.get('source_hash') or source.get('eligible') is not True:
        raise ValueError('Real trigger source changed')
    if (source.get('source') not in policy['approved_sources']
            or datetime.fromisoformat(source['occurred_at'])<datetime.fromisoformat(policy['activated_at'])):
        raise ValueError('Real trigger predates activation or is unapproved')
    if scope=='crm.lead.convert':
        from .real_internal import human_qualification
        if not human_qualification(source.get('record',{}),source.get('timeline',[]),policy['activated_at']):
            raise ValueError('Conversion needs current owner UI qualification evidence')
    if scope=='crm.service.activate':
        from .real_internal import human_transition
        if not human_transition(source.get('record',{}),source.get('timeline',[]),policy['activated_at'],
                                'Installations','Installation_Status','Completed'):
            raise ValueError('Service activation needs owner completion evidence')
    if source.get('kind')=='installation_return_visit' and scope in {'crm.installation.prepare','crm.link.create','crm.internal.task'}:
        from .real_internal import human_transition
        if not human_transition(source.get('record',{}),source.get('timeline',[]),policy['activated_at'],
                                'Installations','Installation_Status','Revisit Required'):
            raise ValueError('Return visit preparation needs current owner UI evidence')

@dataclass(frozen=True)
class LifecycleEffect:
    request_key: str
    payload: dict
    action_type: str = 'lifecycle.scoped'
    target_module: str = 'Lifecycle'
    target_id: str = ''
    @property
    def action_id(self): return hashlib.sha256(('lifecycle-v1\0'+self.request_key).encode()).hexdigest()[:32]
    @property
    def payload_hash(self): return digest(self.payload)

@contextmanager
def exact_call(client, effect, claim, journal, *, mode, run, scope):
    from .remote_effects import FreshClaim
    if (os.geteuid()!=0 or GRANT.get() or not isinstance(effect,LifecycleEffect)
            or not isinstance(claim,FreshClaim) or not claim.fresh or claim.action_id!=effect.action_id
            or claim.payload_hash!=effect.payload_hash): raise ValueError('Fresh exact root lifecycle claim required')
    grant=dict(client=client,effect=effect,claim=claim,journal=journal,mode=mode,run=run,scope=scope,used=False)
    token=GRANT.set(grant)
    try: yield
    finally: GRANT.reset(token)

def check_transport(client,service,method,path,body,headers,*,recheck=False,content_type='application/json',query=None):
    grant=GRANT.get()
    if not grant: return False
    policy=read_policy()
    envelope=dict(service=service,method=method,path=path,body=body,headers=headers or {},content_type=content_type,query=query or {})
    effect=grant['effect']
    if (os.geteuid()!=0 or grant['client'] is not client or grant['used'] is not recheck
            or effect.payload!=envelope or grant['scope'] not in policy['test_scopes' if grant['mode']=='TEST_ONLY' else 'real_scopes']
            or (grant['mode']=='TEST_ONLY' and grant['run']!=policy['test_run'])
            or not grant['journal'].attempted(effect)):
        raise ValueError('Lifecycle grant or durable intent changed')
    validate_request(service,method,path,body,headers or {},content_type,query or {},scope=grant['scope'],mode=grant['mode'],run=grant['run'])
    if grant['mode']=='REAL_NEW':check_real_effect(effect,grant['scope'],grant['run'])
    if not recheck:
        from .effect_audit import start_effect
        start_effect(grant['journal'],effect,grant['scope'],client)
        grant['used']=True
        grant['journal'].append(effect,'transport_intent',{'scope':grant['scope'],'ownership':grant['mode'],'offhost_claim':grant['claim'].key})
    return True

def check_crm_authority(client,method,path,body,headers,*,recheck=False):
    grant=GRANT.get()
    if not grant: return False
    if (os.geteuid()!=0 or grant['client'] is not client or grant['used'] is not recheck
            or any(grant['effect'].payload.get(key)!=value for key,value in
                {'service':'zohoapis','method':method,'path':path,'body':body,'headers':headers or {}}.items())):
        raise ValueError('Exact lifecycle CRM grant changed')
    read_policy()
    validate_request('zohoapis',method,path,body,headers or {},'application/json',grant['effect'].payload['query'],
                     scope=grant['scope'],mode=grant['mode'],run=grant['run'])
    return True

class LifecycleJournal:
    """Append-only evidence tables in the existing action store; no business CRM copy."""
    def __init__(self,path):
        self.path=Path(path)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS lifecycle_intents(action_id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,payload_hash TEXT NOT NULL,envelope TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS lifecycle_evidence(id INTEGER PRIMARY KEY,action_id TEXT NOT NULL,kind TEXT NOT NULL,value TEXT NOT NULL,at TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS lifecycle_intents_no_update BEFORE UPDATE ON lifecycle_intents BEGIN SELECT RAISE(ABORT,'immutable intent'); END;
            CREATE TRIGGER IF NOT EXISTS lifecycle_intents_no_delete BEFORE DELETE ON lifecycle_intents BEGIN SELECT RAISE(ABORT,'immutable intent'); END;
            CREATE TRIGGER IF NOT EXISTS lifecycle_evidence_no_update BEFORE UPDATE ON lifecycle_evidence BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;
            CREATE TRIGGER IF NOT EXISTS lifecycle_evidence_no_delete BEFORE DELETE ON lifecycle_evidence BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;''')
    def connect(self): return sqlite3.connect(self.path)
    def prepare_audit(self,effect,*,scope,before=None,source=None):
        from .effect_audit import prepare_effect
        return prepare_effect(self,effect,scope=scope,before=before,source=source)
    def intent(self,effect):
        with self.connect() as db:
            row=db.execute('SELECT payload_hash FROM lifecycle_intents WHERE action_id=?',(effect.action_id,)).fetchone()
            if row and row[0]!=effect.payload_hash: raise ValueError('Idempotency key conflicts with original payload')
            if not row: db.execute('INSERT INTO lifecycle_intents VALUES (?,?,?,?,?)',(effect.action_id,effect.request_key,effect.payload_hash,json.dumps(effect.payload,sort_keys=True),datetime.now(timezone.utc).isoformat()))
        return not bool(row)
    def append(self,effect,kind,value):
        from .action_evidence import redact
        value=redact(value)
        with self.connect() as db: db.execute('INSERT INTO lifecycle_evidence(action_id,kind,value,at) VALUES (?,?,?,?)',(effect.action_id,kind,json.dumps(value,sort_keys=True),datetime.now(timezone.utc).isoformat()))
        from .effect_audit import effect_event
        effect_event(self,effect,kind,value)
    def attempted(self,effect):
        with self.connect() as db:
            row=db.execute('SELECT payload_hash FROM lifecycle_intents WHERE action_id=?',(effect.action_id,)).fetchone()
            return bool(row and row[0]==effect.payload_hash and db.execute("SELECT 1 FROM lifecycle_evidence WHERE action_id=? AND kind='attempted'",(effect.action_id,)).fetchone())
