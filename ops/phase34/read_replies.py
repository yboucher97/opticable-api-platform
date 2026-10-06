#!/usr/bin/env python3
"""One bounded manual GET-only reconciliation of known Apollo reply contacts.

Private provider records stay root-only. Search is exact sender/date; bodies are
read only when authoritative headers reference a known team's sent Message-ID.
"""
from datetime import datetime, timedelta, timezone
import json, os, re, sys
from pathlib import Path

ROOT = Path('/var/lib/optibrain/phase34')

def main():
    if os.geteuid()!=0: raise ValueError('Root-only provider evidence')
    os.umask(0o077)
    sys.path.insert(0,'/opt/opticable-api-platform/ops/phase16_17')
    from inventory import clients
    _, client, _ = clients()
    from workflow.automation.followup_mail import _data, _headers, _addresses, _plain_body, _epoch_millis
    apollo=json.loads(Path('/var/lib/optibrain/sales-intelligence/apollo.json').read_text())
    contacts={c['id']:c for c in apollo['contacts']}
    selected=[]
    for p in ROOT.glob('replied-*.json'):selected.extend(json.loads(p.read_text())['emailer_messages'])
    ids={m['id'] for m in selected}
    known=[m for m in apollo['replies'] if m['id'] in ids]
    if len(known)!=len(ids) or len(ids)>20:raise ValueError('Fresh known-message bound disagrees')
    reads=0
    def get(path,query=None):
        nonlocal reads
        reads+=1
        if reads>100:raise ValueError('Mail read bound')
        return client.request('mail','GET',path,query=query or {})
    accounts=_data(get('/api/accounts'),list)
    sender_set={m['from_email'].casefold() for m in known}
    accounts=[a for a in accounts if str(a.get('primaryEmailAddress','')).casefold() in sender_set]
    if len(accounts)!=1:raise ValueError('Unique authorized sending mailbox unavailable')
    account=str(accounts[0]['accountId']);now=datetime.now(timezone.utc)
    result=[]
    for sent in known:
        contact=contacts[sent['contact_id']];sender=str(contact.get('email','')).casefold()
        if not re.fullmatch(r'[^\s:]+@[^\s:]+',sender):raise ValueError('Exact contact sender required')
        start=datetime.fromisoformat(sent['completed_at']).strftime('%d-%b-%Y')
        end=(now+timedelta(days=1)).strftime('%d-%b-%Y')
        query={'searchKey':f'sender:{sender}::fromDate:{start}::toDate:{end}::inclspamtrash:true','start':0,'limit':20}
        rows=_data(get(f'/api/accounts/{account}/messages/search',query),list)
        bound=[]
        for row in rows[:3]:
            mid=str(row.get('messageId',''));folder=str(row.get('folderId',''))
            if not mid.isdigit() or not folder.isdigit() or _addresses(row.get('fromAddress'))!=(sender,):continue
            if sent['from_email'].casefold() not in _addresses(row.get('toAddress')):continue
            base=f'/api/accounts/{account}/folders/{folder}/messages/{mid}'
            headers=_headers(get(base+'/header',{'raw':'false'}))
            refs=set(re.findall(r'<[^<>\s]+@[^<>\s]+>',headers.get('references','')+' '+headers.get('in-reply-to','')))
            if sent['provider_message_id'] not in refs:continue
            details=_data(get(base+'/details'),dict)
            if str(details.get('messageId'))!=mid or _addresses(details.get('fromAddress'))!=(sender,):continue
            body=_plain_body(get(base+'/content'))
            bound.append({'message_id':mid,'folder_id':folder,'internet_message_id':headers.get('message-id'),
                'headers':headers,'received_at':_epoch_millis(row.get('receivedTime') or row.get('receivedtime')).isoformat(),
                'body':body,'subject':row.get('subject'),'match':'EXACT_REFERENCES_AND_SENDER'})
        result.append({'sent':sent,'contact':contact,'replies':bound,'search_complete':len(rows)<20,
                       'candidate_count':len(rows),'candidate_bound':3,'account_id':account})
    output={'schema':1,'at':now.isoformat(),'scope':'live','read_only':True,'provider_reads':reads,'provider_writes':0,'rows':result}
    with (ROOT/'mail-replies.json').open('x') as f:json.dump(output,f,ensure_ascii=False)
    print(json.dumps({'reads':reads,'writes':0,'known_contacts':len(result),'bound_conversations':sum(bool(r['replies']) for r in result),
                      'bound_messages':sum(len(r['replies']) for r in result),'path':str(ROOT/'mail-replies.json')}))

if __name__=='__main__':main()
