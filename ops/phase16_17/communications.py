#!/usr/bin/env python3
"""Two controlled TEST reminders; reply/acceptance/suppression stop sends."""
from test_lab import Lab,MARKER,RUN,ROOT,atomic
from datetime import datetime,timezone
import json

ACCOUNT='1083319000000008002';SENT='1083319000000008022';RECIPIENT='yboucher@opticable.ca'

def main():
    lab=Lab()
    from workflow.automation.lifecycle import reminder_due
    evidence=[]
    for number in [1,2]:
        key='mail-test-reminder-'+str(number)
        body={'fromAddress':RECIPIENT,'toAddress':RECIPIENT,
            'subject':'[OPTIBRAIN TEST] Phase 16 synthetic estimate reminder '+str(number),
            'content':MARKER+'\nSynthetic lifecycle validation only. No customer quote, contract, invoice, payment or work is requested.\nRun: '+RUN+'\nReminder '+str(number),
            'mailFormat':'plaintext'}
        prior=lab.state['operations'].get(key)
        response=prior['result'] if prior and prior['state']=='acknowledged' else lab.call(key,'mail.test.send','mail','POST','/api/accounts/'+ACCOUNT+'/messages',body)
        data=response.get('data',{}).get('data',{});identity=str(data.get('messageId') or '')
        if not identity:raise ValueError('Mail send lacks provider ID')
        actual=lab.get('mail','/api/accounts/'+ACCOUNT+'/folders/'+SENT+'/messages/'+identity+'/details')['data']
        from email.utils import getaddresses
        from html import unescape
        recipients=[a.casefold() for _,a in getaddresses([unescape(str(actual.get('toAddress') or ''))])]
        if (actual.get('subject')!=body['subject'] or recipients!=[RECIPIENT]
                or actual.get('ccAddress') not in (None,'','Not Provided') or actual.get('bccAddress') not in (None,'','Not Provided')):
            raise ValueError('Mail readback recipient/subject mismatch')
        lab.register('Mail',identity,{'recipient':RECIPIENT,'subject':body['subject'],'action_id':lab.state['operations'][key]['action_id']})
        lab.verified(key,identity,{'message_id':identity,'recipient':RECIPIENT,'subject':body['subject']})
        evidence.append({'message_id':identity,'number':number,'recipient':RECIPIENT,'subject':body['subject']})
        print('TEST reminder',number,'sent and independently verified; recipient',RECIPIENT,flush=True)
    stops=[]
    for reason,kwargs in [('response',{'replied':True}),('acceptance',{'estimate_status':'accepted'}),
        ('decline',{'estimate_status':'declined'}),('manual suppression',{'suppressed':True}),('Deal closed',{'deal_closed':True})]:
        args=dict(estimate_status='sent',due_at='2026-10-01T10:00:00-04:00',now=datetime.now(timezone.utc).isoformat());args.update(kwargs)
        result=reminder_due(**args)
        if result['decision']!='STOP' or result['external_send']:raise ValueError('Reminder stop condition failed')
        stops.append({'reason':reason,'result':result,'provider_send_calls':0})
    # Replaying the verified exact operation returns stored acknowledgment; no
    # second transport grant or provider POST exists.
    before=len(lab.state['operations'])
    r=lab.call('mail-test-reminder-2','mail.test.send','mail','POST','/api/accounts/'+ACCOUNT+'/messages',body)
    if len(lab.state['operations'])!=before:raise ValueError('Replay created a second operation')
    atomic(ROOT/'mail-reminder-evidence.json',{'schema':1,'run':RUN,'sends':evidence,'stop_conditions':stops,'duplicate_sends':0,'replay':'verified result returned; zero provider resend'})
    print('Two TEST Mail sends; replay fenced; five stop conditions PASS',flush=True)

if __name__=='__main__':main()
