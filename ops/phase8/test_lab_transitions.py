#!/usr/bin/env python3
"""Journaled positive/negative provider transition proofs on owned Test Lab records."""
import json,os,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path('/var/lib/optibrain/phase8/test-lab')
REGISTRY=ROOT/'registry.json'
JOURNAL=ROOT/'transition-journal.json'
APP=Path(__file__).resolve().parents[2]/'apps/workflow-api'

def atomic(path,value):
    temp=path.with_name('.'+path.name+'.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as handle:
        json.dump(value,handle,indent=2,sort_keys=True);handle.write('\n');handle.flush();os.fsync(handle.fileno())
    os.replace(temp,path)

def main():
    if os.geteuid()!=0 or sys.argv[1:]!=['--execute']:raise SystemExit('Root and --execute required')
    pid=subprocess.check_output(['systemctl','show','opticable-workflow-api.service','-p','MainPID','--value'],text=True).strip()
    for item in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'):
        if b'=' in item:
            key,value=item.split(b'=',1);os.environ[key.decode()]=value.decode()
    os.environ['OPTIBRAIN_PHASE8_TEST_LAB']='phase8-protected-test-lab-v1'
    sys.path.insert(0,str(APP))
    from workflow.config import load_settings
    from workflow.zoho_oauth import ZohoOAuthManager
    from workflow.zoho_gateway import ZohoGatewayClient
    from workflow.automation.providers.crm_leads import records
    from workflow.automation.test_lab_boundary import reviewed_test_lab_call,validate_lab_request
    from workflow.automation.sales_queue import build_sales_queue
    s=load_settings();c=ZohoGatewayClient(s.zoho_gateway,ZohoOAuthManager(s.zoho_oauth))
    reg=json.loads(REGISTRY.read_text());journal=json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {}
    quote_id=reg['scenarios']['quote']['lead_id'];overdue_id=reg['scenarios']['overdue']['lead_id']
    task_id=reg['related']['task_overdue']['id']
    # Technical dry run: the same boundary denies a protected target and permits an owned one.
    protected='5062683000007880001'
    denied=False
    try:validate_lab_request('PUT',f'/crm/v8/Leads/{protected}',{'data':[{'id':protected,'Scope':'forbidden'}],'trigger':[]},{'If-Unmodified-Since':'2026-09-30T00:00:00+00:00'})
    except ValueError:denied=True
    if not denied:raise AssertionError('Protected mutation dry-run was allowed')
    validate_lab_request('PUT',f'/crm/v8/Leads/{quote_id}',{'data':[{'id':quote_id,'Scope':None}],'trigger':[]},{'If-Unmodified-Since':'2026-09-30T00:00:00+00:00'})
    print('Firewall dry run: protected denied; owned allowed',flush=True)
    def get(module,identity):
        rows=records(c.request('zohoapis','GET',f'/crm/v8/{module}/{identity}'))
        if len(rows)!=1 or str(rows[0].get('id'))!=identity or not str(rows[0].get('Description') or '').startswith('OPTIBRAIN TEST — PHASE 8'):
            raise ValueError('Fresh Test Lab readback or marker invalid')
        return rows[0]
    def queue_row(identity):
        view=build_sales_queue(c,Path('/var/lib/opticable-workflow-api/output/automation/automation.db'),
                               account_id='1083319000000008002',from_address='yboucher@opticable.ca',scope='lab')
        return next(x for x in view['rows'] if x['id']==identity)
    def update(step,module,identity,changes,expected):
        if step in journal:
            if journal[step].get('state')=='verified':return
            raise ValueError(step+' unconfirmed; reconcile before retry')
        before=get(module,identity)
        body={'data':[{'id':identity,**changes}],'trigger':[],
              'skip_feature_execution':[{'name':'cadences'}]}
        headers={'If-Unmodified-Since':before['Modified_Time']}
        journal[step]={'state':'attempted','module':module,'id':identity,
                       'before':{k:before.get(k) for k in changes},'after':changes,
                       'at_utc':datetime.now(timezone.utc).isoformat()}
        atomic(JOURNAL,journal)
        with reviewed_test_lab_call(c,'PUT',f'/crm/v8/{module}/{identity}',body,headers):
            response=c.request('zohoapis','PUT',f'/crm/v8/{module}/{identity}',body=body,headers=headers,
                               reason='Phase 8 Test Lab provider transition '+step,confirm=True)
        rows=(response.get('data') or {}).get('data') or []
        if response.get('status') not in {200,201,202} or len(rows)!=1 or rows[0].get('status')!='success' or str((rows[0].get('details') or {}).get('id'))!=identity:
            raise ValueError(step+' update acknowledgement ambiguous; reconcile before retry')
        after=get(module,identity)
        if any(after.get(key)!=value for key,value in expected.items()):
            raise ValueError(step+' readback mismatch')
        journal[step]['state']='verified';journal[step]['readback']={k:after.get(k) for k in expected}
        atomic(JOURNAL,journal)
        print(step,'provider update verified',flush=True)
    quote=get('Leads',quote_id);scope=quote.get('Scope')
    if not scope:raise ValueError('Quote scenario scope absent at start')
    row=queue_row(quote_id)
    if row['quote']!='READY FOR QUOTE':raise ValueError('Quote positive state not present')
    print('quote positive READY FOR QUOTE',flush=True)
    update('quote_remove_scope','Leads',quote_id,{'Scope':None},{'Scope':None})
    row=queue_row(quote_id)
    if row['quote']!='NEEDS INFORMATION' or 'Project scope' not in row['missing']:
        raise ValueError('Quote negative transition failed')
    print('quote negative NEEDS INFORMATION',flush=True)
    update('quote_restore_scope','Leads',quote_id,{'Scope':scope},{'Scope':scope})
    if queue_row(quote_id)['quote']!='READY FOR QUOTE':raise ValueError('Quote restore failed')
    row=queue_row(overdue_id)
    if not row['neglected'] or row['followup']!='OVERDUE':raise ValueError('Neglected positive state absent')
    print('neglected positive OVERDUE',flush=True)
    update('overdue_complete_task','Tasks',task_id,{'Status':'Completed'},{'Status':'Completed'})
    row=queue_row(overdue_id)
    if row['neglected']:raise ValueError('Neglected negative transition failed')
    print('neglected negative NOT NEGLECTED',flush=True)
    update('overdue_restore_task','Tasks',task_id,{'Status':'Not Started'},{'Status':'Not Started'})
    row=queue_row(overdue_id)
    if not row['neglected']:raise ValueError('Neglected restore failed')
    print('neglected restored OVERDUE',flush=True)

if __name__=='__main__':main()
