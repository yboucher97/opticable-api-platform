#!/usr/bin/env python3
"""Manual single-call Test Lab Account, Contact, Deal, and Task creation."""
import os,sys,subprocess
from pathlib import Path
import json
from datetime import datetime,timezone

ROOT=Path('/var/lib/optibrain/phase8/test-lab')
REGISTRY=ROOT/'registry.json'
JOURNAL=ROOT/'relations-journal.json'
MARKER='OPTIBRAIN TEST — PHASE 8'
APP=Path(__file__).resolve().parents[2]/'apps/workflow-api'

def atomic(path,value):
    temp=path.with_name('.'+path.name+'.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as handle:
        json.dump(value,handle,indent=2,sort_keys=True);handle.write('\n');handle.flush();os.fsync(handle.fileno())
    os.replace(temp,path)

def create(client,registry,journal,key,module,row):
    from workflow.automation.test_lab_boundary import reviewed_test_lab_call
    from workflow.automation.providers.crm_leads import records
    if key in journal:
        if journal[key].get('state')=='verified': return journal[key]['id']
        raise ValueError(f'{key} unconfirmed; reconcile before retry')
    body={'data':[row],'trigger':[]}
    journal[key]={'state':'attempted','at_utc':datetime.now(timezone.utc).isoformat()}
    atomic(JOURNAL,journal)
    with reviewed_test_lab_call(client,'POST',f'/crm/v8/{module}',body):
        response=client.request('zohoapis','POST',f'/crm/v8/{module}',body=body,
                                reason=f'Create isolated Test Lab {key}',confirm=True)
    data=(response.get('data') or {}).get('data') or []
    if response.get('status') not in {200,201,202} or len(data)!=1 or data[0].get('status')!='success' or not str((data[0].get('details') or {}).get('id') or '').isdigit():
        raise ValueError(f'{key} acknowledgement ambiguous; do not retry')
    identity=str(data[0]['details']['id'])
    journal[key]['ack_id']=identity;atomic(JOURNAL,journal)
    registry['records'][module].append(identity)
    registry.setdefault('related',{})[key]={'module':module,'id':identity}
    atomic(REGISTRY,registry)
    read=records(client.request('zohoapis','GET',f'/crm/v8/{module}/{identity}'))
    if len(read)!=1 or str(read[0].get('id'))!=identity or not str(read[0].get('Description') or '').startswith(MARKER):
        raise ValueError(f'{key} readback mismatch')
    journal[key]={'state':'verified','id':identity,'at_utc':datetime.now(timezone.utc).isoformat()};atomic(JOURNAL,journal)
    print(key,identity,'verified',flush=True)
    return identity

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
    s=load_settings();c=ZohoGatewayClient(s.zoho_gateway,ZohoOAuthManager(s.zoho_oauth))
    registry=json.loads(REGISTRY.read_text());journal=json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {}
    account=create(c,registry,journal,'account','Accounts',{
        'Account_Name':MARKER+' — Lab Wireless Group','Description':MARKER+'\nSynthetic relationship account.'})
    contact=create(c,registry,journal,'contact','Contacts',{
        'First_Name':'OptiBrain Test','Last_Name':MARKER+' — Wi-Fi Quote',
        'Email':'quote@optibrain.invalid','Account_Name':{'id':account},
        'Description':MARKER+'\nSynthetic relationship contact.'})
    create(c,registry,journal,'deal','Deals',{
        'Deal_Name':MARKER+' — Lab Wireless Opportunity','Stage':'Qualification',
        'Closing_Date':'2026-11-30','Account_Name':{'id':account},'Contact_Name':{'id':contact},
        'Description':MARKER+'\nSynthetic relationship opportunity; exclude from revenue reporting.'})
    for name,date in [('overdue','2026-09-24'),('waiting','2026-10-02'),('replied','2026-10-02')]:
        lead=registry['scenarios'][name]['lead_id']
        create(c,registry,journal,'task_'+name,'Tasks',{
            'Subject':MARKER+' — '+name.upper()+' — Follow-up',
            'What_Id':{'id':lead},'$se_module':'Leads','Status':'Not Started','Due_Date':date,
            'Description':MARKER+'\nSynthetic follow-up obligation for '+name+'.'})

if __name__=='__main__':main()
