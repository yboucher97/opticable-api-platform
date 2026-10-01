#!/usr/bin/env python3
"""At-most-once controlled outbound Mail for the Phase 8 Test Lab."""
import json,os,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path('/var/lib/optibrain/phase8/test-lab')
REGISTRY=ROOT/'registry.json'
JOURNAL=ROOT/'mail-journal.json'
APP=Path(__file__).resolve().parents[2]/'apps/workflow-api'
ACCOUNT='1083319000000008002'
SENT='1083319000000008022'
SENDER='yboucher@opticable.ca'
RECIPIENTS={'waiting':'hckyan97+obp8wait@gmail.com','replied':'info@opticable.ca'}

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
    sys.path.insert(0,str(APP))
    from workflow.config import load_settings
    from workflow.zoho_oauth import ZohoOAuthManager
    from workflow.zoho_gateway import ZohoGatewayClient
    from workflow.automation.followup_mail import _data
    from workflow.automation.providers.outbound_mail import _provider_message_id
    from workflow.automation.providers.crm_leads import records
    s=load_settings();c=ZohoGatewayClient(s.zoho_gateway,ZohoOAuthManager(s.zoho_oauth))
    registry=json.loads(REGISTRY.read_text());journal=json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {}
    for scenario,recipient in RECIPIENTS.items():
        lead_id=registry['scenarios'][scenario]['lead_id']
        if lead_id not in registry['records']['Leads'] or registry['scenarios'][scenario]['email']!=recipient:
            raise ValueError('Mail target is not exact owned scenario identity')
        lead=records(c.request('zohoapis','GET',f'/crm/v8/Leads/{lead_id}'))[0]
        if str(lead['id'])!=lead_id or lead.get('OptiBrain_Test') is not True or lead.get('Email')!=recipient:
            raise ValueError('Fresh Lead identity does not match Test Lab recipient')
        if scenario in journal:
            if journal[scenario].get('state')=='verified':
                print(scenario,'already sent',journal[scenario]['message_id'],flush=True);continue
            raise ValueError('Prior Mail attempt unconfirmed; reconcile before retry')
        subject=f'OPTIBRAIN TEST — PHASE 8 — {scenario.upper()} — {lead_id}'
        content=('OPTIBRAIN TEST ONLY. This is an operator-controlled synthetic sales scenario. '
                 'Please do not treat it as customer correspondence.\n\n'
                 +('We have logged your test inquiry. We will wait until the scheduled follow-up before another message.'
                   if scenario=='waiting' else
                   'Could you share the site address and the number of access points for the test Wi-Fi project?'))
        body={'fromAddress':SENDER,'toAddress':recipient,'subject':subject,
              'content':content,'mailFormat':'plaintext'}
        journal[scenario]={'state':'attempted','at_utc':datetime.now(timezone.utc).isoformat(),
                           'lead_id':lead_id,'subject':subject,'recipient':recipient}
        atomic(JOURNAL,journal)
        response=c.request('mail','POST',f'/api/accounts/{ACCOUNT}/messages',body=body,
                           reason=f'Single operator-controlled Phase 8 Test Lab send for {scenario}',confirm=True)
        message_id=_provider_message_id(response)
        if not message_id:raise ValueError('Mail acknowledgement ambiguous; do not retry')
        journal[scenario]['ack_id']=message_id;atomic(JOURNAL,journal)
        path=f'/api/accounts/{ACCOUNT}/folders/{SENT}/messages/{message_id}'
        item=_data(c.request('mail','GET',path+'/details'),dict)
        if str(item.get('messageId'))!=message_id or str(item.get('folderId'))!=SENT or item.get('subject')!=subject or recipient not in str(item.get('toAddress') or '').lower():
            raise ValueError('Sent readback mismatch')
        millis=int(item.get('receivedTime') or item.get('receivedtime'))
        sent_at=datetime.fromtimestamp(millis/1000,timezone.utc).isoformat()
        registry['scenarios'][scenario]['mail']={'message_id':message_id,'sent_at':sent_at,
                                                  'subject':subject,'recipient':recipient,'sender':SENDER,
                                                  'account_id':ACCOUNT,'state':'sent'}
        atomic(REGISTRY,registry)
        journal[scenario]={'state':'verified','message_id':message_id,'sent_at':sent_at,
                           'recipient':recipient,'subject':subject,'lead_id':lead_id}
        atomic(JOURNAL,journal)
        print(scenario,message_id,'sent/readback verified',flush=True)

if __name__=='__main__':main()
