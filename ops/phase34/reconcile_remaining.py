#!/usr/bin/env python3
"""One diagnostic expansion for six incomplete known reply-header lookups.

Different bounds and header-recipient checks address the documented first
three-candidate limit. No unrelated inbox content or provider effects.
"""
from datetime import datetime,timedelta,timezone
import json,os,re,sys
from pathlib import Path
ROOT=Path('/var/lib/optibrain/phase34')
def main():
    if os.geteuid()!=0:raise ValueError('Root required')
    os.umask(0o077);sys.path.insert(0,'/opt/opticable-api-platform/ops/phase16_17')
    from inventory import clients
    _,client,_=clients()
    from workflow.automation.followup_mail import _data,_headers,_addresses,_epoch_millis
    original=json.loads((ROOT/'mail-replies.json').read_text());reads=0;now=datetime.now(timezone.utc)
    def get(path,query=None):
        nonlocal reads
        reads+=1
        if reads>48:raise ValueError('Diagnostic read bound')
        return client.request('mail','GET',path,query=query or {})
    for row in original['rows']:
        if row['replies']:continue
        sent=row['sent'];contact=row['contact'];address=contact['email'].casefold();account=row['account_id']
        when=datetime.fromisoformat(sent['completed_at']);start=when.strftime('%d-%b-%Y');end=(now+timedelta(days=1)).strftime('%d-%b-%Y')
        rows=_data(get(f'/api/accounts/{account}/messages/search',{'searchKey':f'sender:{address}::fromDate:{start}::toDate:{end}::inclspamtrash:true','start':0,'limit':12}),list)
        row['expanded_attempt_at']=now.isoformat();row['expanded_bound']=12;row['diagnostics']=[]
        for candidate in rows:
            mid=str(candidate.get('messageId',''));folder=str(candidate.get('folderId',''))
            if not mid.isdigit() or not folder.isdigit() or _addresses(candidate.get('fromAddress'))!=(address,):continue
            base=f'/api/accounts/{account}/folders/{folder}/messages/{mid}';header=_headers(get(base+'/header',{'raw':'false'}))
            refs=set(re.findall(r'<[^<>\s]+@[^<>\s]+>',header.get('references','')+' '+header.get('in-reply-to','')))
            matched=sent['provider_message_id'] in refs
            row['diagnostics'].append({'id':mid,'matching_sent_reference':matched,'reference_count':len(refs)})
            recipients=','.join(v for v in (header.get('to'),header.get('cc')) if v)
            if not matched or _addresses(header.get('from'))!=(address,) or sent['from_email'].casefold() not in _addresses(recipients):continue
            data=_data(get(base+'/content'),dict);content=data.get('content');body=content.get('content') if isinstance(content,dict) else content
            if not isinstance(body,str) or len(body.encode())>131072:raise ValueError('Private body limit')
            row['replies'].append({'message_id':mid,'folder_id':folder,'internet_message_id':header.get('message-id'),'headers':header,
                'received_at':_epoch_millis(candidate.get('receivedTime') or candidate.get('receivedtime')).isoformat(),'body':body,'match':'EXACT_REFERENCES_AND_SENDER'})
        row['search_complete']=len(rows)<12
    original['expanded_provider_reads']=reads;original['expanded_at']=now.isoformat()
    with (ROOT/'mail-reconciled-validated.json').open('x') as f:json.dump(original,f,ensure_ascii=False)
    print(json.dumps({'reads':reads,'bound_conversations':sum(bool(r['replies']) for r in original['rows']),'bound_messages':sum(len(r['replies']) for r in original['rows']),'writes':0}))
if __name__=='__main__':main()
