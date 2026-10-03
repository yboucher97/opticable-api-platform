#!/usr/bin/env python3
"""Explicit manual TEST lab, isolated policy; never changes Phase17 authority."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import json,os,sys,hashlib

REPO=Path(__file__).resolve().parents[2]
ROOT=Path('/var/lib/optibrain/phase18-19')
RUN='phase18-20261003-communications-v1'
MARKER='OPTIBRAIN TEST — PHASE 18'
CONTROL=Path('/etc/optibrain/phase18-test-control.json')

def lab():
    if os.geteuid()!=0:raise ValueError('Manual root lab required')
    os.umask(0o077);ROOT.mkdir(mode=0o700,exist_ok=True)
    sys.path.insert(0,str(REPO/'ops/phase16_17'))
    import test_lab as original
    original.ROOT=ROOT;original.RUN=RUN;original.MARKER=MARKER;original.REPO=REPO
    original.STATE=ROOT/'test-lab.json';original.OWNERSHIP=ROOT/'ownership.json';original.CONTROL=CONTROL
    instance=original.Lab()
    from workflow.automation import lifecycle_control as lc
    lc.CONTROL=CONTROL;lc.REGISTRY=original.OWNERSHIP;lc.TEST_PREFIX=MARKER
    return instance

def activate(instance):
    from workflow.automation import lifecycle_control as lc
    from test_lab import atomic
    names=lc.TRANSPORT_SOURCES
    scopes={'crm.deal.prepare','crm.site.prepare','crm.service.create','crm.installation.prepare',
        'crm.link.create','crm.case.create','crm.internal.task','crm.test.transition',
        'workdrive.folder.create','sign.contract.prepare','sign.test.send'}
    policy={'schema':2,'test_writes_enabled':False,'allowed_actions':['crm.task.create'],'real_canary_allowed':False,
        'lifecycle':{'enabled':True,'test_run':RUN,'test_scopes':sorted(scopes),'real_scopes':[],
        'activated_at':None,'approved_sources':[],'expires_at':(datetime.now(timezone.utc)+timedelta(hours=4)).isoformat(),
        'source_hashes':{n:hashlib.sha256((REPO/'apps/workflow-api/workflow'/n).read_bytes()).hexdigest() for n in names},
        'phase16_checkpoint_sha256':None}}
    instance.save();atomic(CONTROL,policy)

def borrow(instance):
    prior=Path('/var/lib/optibrain/phase16-17')
    source=json.loads((prior/'ownership.json').read_text())
    scenarios=json.loads((prior/'test-lab.json').read_text())['scenarios']
    a=scenarios['A']
    ids=[('Accounts',a['conversion']['Accounts']),('Contacts',a['conversion']['Contacts']),
         ('Service_Locations',a['site_id']),('Services',a['service_ids'][0])]
    for module,identity in ids:
        row=instance.crm(module,identity);owned=source['records'].get(identity,{})
        if (owned.get('module')!=module or owned.get('ownership')!='TEST_ONLY'
                or row.get('OptiBrain_Test') is not True or 'OPTIBRAIN TEST' not in json.dumps(row,ensure_ascii=False).upper()):
            raise ValueError('Borrowed identity lacks independent synthetic provenance')
        instance.register(module,identity,{'borrowed_from_run':source['run'],'created_time':row.get('Created_Time')})
    for identity in a['workdrive'].values():
        if identity not in source['records']:raise ValueError('Borrowed folder lacks independent lineage')
        instance.register('WorkDrive',identity,{'borrowed_from_run':source['run']})
    instance.state['parents']={'account_id':a['conversion']['Accounts'],'contact_id':a['conversion']['Contacts'],
        'site_id':a['site_id'],'service_id':a['service_ids'][0],'workdrive':a['workdrive']}
    instance.save()

def prepare(instance):
    borrow(instance)
    p=instance.state['parents']
    scheduled=(datetime.now(timezone.utc)+timedelta(days=3)).astimezone(__import__('zoneinfo').ZoneInfo('America/Toronto')).replace(hour=10,minute=0,second=0,microsecond=0)
    for lang in ['fr','en']:
        if lang in instance.state['scenarios']:continue
        deal=instance.create('phase18-deal-'+lang,'Deals',{'Deal_Name':MARKER+' — Communications '+lang,
            'Account_Name':{'id':p['account_id']},'Contact_Name':{'id':p['contact_id']},'Service_Location':{'id':p['site_id']},
            'Stage':'Proposal/Price Quote','Closing_Date':scheduled.date().isoformat(),'Amount':0,
            'Service_Types':'Structured Cabling','OptiBrain_Test':True,'Description':MARKER+' — synthetic communication validation; no Finance transaction.'})
        visit=instance.create('phase18-installation-'+lang,'Installations',{'Name':MARKER+' — Communications '+lang,
            'Linked_Service':{'id':p['service_id']},'Installation_Status':'Requested','OptiBrain_Test':True,
            'Instructions_Notes':MARKER+' — TEST human scheduling and controlled Mail validation.'})
        instance.create('phase18-join-'+lang,'Installation_X_Services',{'Name':MARKER+' — Communications '+lang,
            'Linked_Installation':{'id':visit['id']},'Linked_Service':{'id':p['service_id']}})
        instance.update('phase18-schedule-'+lang,'Installations',visit['id'],{'Installation_Status':'Scheduled',
            'Scheduled_Date':scheduled.isoformat(),'Assigned_To':'Opticable TEST technician',
            'Instructions_Notes':MARKER+' — Human-selected TEST appointment. Use main entrance.'},scope='crm.test.transition')
        instance.state['scenarios'][lang]={'deal_id':deal['id'],'installation_id':visit['id'],'language':lang,
            'scheduled_at':scheduled.isoformat(),'estimate_fixture_id':RUN+'-quote-'+lang,
            'source_kind':'TEST_STATUS_EQUIVALENT','actual_finance_transaction_created':False}
        instance.save()
    print(json.dumps({'run':RUN,'scenarios':list(instance.state['scenarios']),'provider_financial_writes':0}))

def sign_probe(instance):
    from test_lab import atomic
    template=instance.get('sign','/templates/325018000000115001')['templates']
    fields=[f for doc in template.get('document_fields',[]) for f in doc.get('fields',[]) if f.get('is_mandatory')]
    texts={str(f.get('field_name') or f.get('field_label')):MARKER+' — SYNTHETIC, NO CUSTOMER CONTRACT' for f in fields if f.get('field_category')=='textfield'}
    dates={str(f.get('field_name') or f.get('field_label')):datetime.now(timezone.utc).date().isoformat() for f in fields if f.get('field_category')=='datefield'}
    action=template['actions'][0]
    payload={'templates':{'request_name':'[OPTIBRAIN TEST] Phase 18 license probe',
        'field_data':{'field_text_data':texts,'field_date_data':dates,'field_boolean_data':{},'field_radio_data':{}},
        'actions':[{'recipient_name':MARKER,'recipient_email':'yboucher@opticable.ca','action_id':action['action_id'],
            'action_type':'SIGN','role':'Signataire','signing_order':1,'verify_recipient':False}],
        'notes':'[OPTIBRAIN TEST] Synthetic license validation only. No real obligation.','email_reminders':False}}
    try:
        response=instance.call('phase18-sign-license-probe','sign.contract.prepare','sign','POST',
            '/templates/325018000000115001/createdocument',{'data':json.dumps(payload,ensure_ascii=False),'is_quicksend':'false'},content_type='application/x-www-form-urlencoded')
        request=response.get('data',{}).get('requests',{});identity=str(request.get('request_id') or '')
        if not identity.isdigit():raise ValueError('Sign probe needs reconciliation')
        actual=instance.get('sign','/requests/'+identity)['requests']
        instance.register('Sign',identity,{'request_name':actual.get('request_name'),'recipient':'yboucher@opticable.ca'})
        instance.verified('phase18-sign-license-probe',identity,{'request_id':identity,'status':actual.get('request_status'),'send':False})
        receipt={'license':'AVAILABLE','test_draft_id':identity,'sends':0}
    except Exception:
        failure=instance.state['operations'].get('phase18-sign-license-probe',{}).get('failure',{})
        data=failure.get('provider',{})
        if data.get('code')!=12000:raise
        receipt={'license':'RESTRICTED','provider_code':12000,'status':'DEFERRED — PROVIDER LICENSE','sends':0}
    atomic(ROOT/'sign-license-recheck.json',receipt)
    print(json.dumps(receipt))

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in {'prepare','sign-probe','close'}:raise ValueError('Explicit prepare/sign-probe/close required')
    instance=lab()
    if sys.argv[1]=='close':
        from test_lab import atomic
        activate(instance)
        try:
            for lang,s in instance.state['scenarios'].items():
                instance.update('phase18-close-'+lang,'Deals',s['deal_id'],{'Stage':'Closed Lost','Amount':0})
        finally:
            atomic(CONTROL,{'schema':1,'test_writes_enabled':False,'allowed_actions':['crm.task.create'],'real_canary_allowed':False})
        print('TEST lab scopes closed; Phase17 authority unchanged');return
    activate(instance)
    (prepare if sys.argv[1]=='prepare' else sign_probe)(instance)

if __name__=='__main__':main()
