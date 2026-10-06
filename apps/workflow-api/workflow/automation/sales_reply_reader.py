"""Exact sender/date/header-bound Mail reads for saved Apollo reply contacts.

This is not a mailbox ingestion or send API. At most four known conversations,
sixteen GETs and forty seconds per existing observer cycle. Partial searches
never establish that a contact has not replied or that a follow-up is due.
"""
from datetime import timedelta, timezone
import re
from time import monotonic
from .followup_mail import _data, _headers, _addresses, _epoch_millis
from .sales_intelligence import email, stamp
from .acquisition_store import digest

ACCOUNT='1083319000000008002'
SENDER='yboucher@opticable.ca'

def read_replies(client,apollo,cache,*,now,max_calls=16):
    if type(max_calls) is not int or not 0<=max_calls<=16:raise ValueError('Fixed Mail budget required')
    contacts={str(c['id']):c for c in apollo.get('contacts',[])}
    old={str(r['contact']['id']):r for r in cache.get('rows',[])}
    calls=0;started=monotonic();attempts=[]
    def get(path,query=None):
        nonlocal calls
        if calls>=max_calls or monotonic()-started>40:raise ValueError('SALES_MAIL_READ_BUDGET')
        calls+=1
        return client.request('mail','GET',path,query=query or {})
    for sent in sorted(apollo.get('replies',[]),key=lambda m:m.get('completed_at') or '',reverse=True):
        if calls>=max_calls:break
        if len(attempts)>=4:break
        c=contacts.get(str(sent.get('contact_id')));when=stamp(sent.get('completed_at'))
        if not c or not when or not email(c.get('email')) or sent.get('from_email','').casefold()!=SENDER:continue
        internet=sent.get('provider_message_id','')
        if not re.fullmatch(r'<[^<>\s]+@[^<>\s]+>',internet):continue
        prior=old.get(str(c['id']),{});next_at=stamp(prior.get('next_eligible_at'))
        if next_at and next_at>now and prior.get('sent',{}).get('id')==sent['id']:continue
        row={'contact':c,'sent':sent,'account_id':ACCOUNT,'replies':list(prior.get('replies',[])),
             'at':now.isoformat(),'search_complete':False,'next_eligible_at':(now+timedelta(hours=24)).isoformat()}
        attempts.append(str(c['id']))
        try:
            address=email(c['email']);start=when.strftime('%d-%b-%Y');end=(now+timedelta(days=1)).strftime('%d-%b-%Y')
            found=_data(get(f'/api/accounts/{ACCOUNT}/messages/search',{'searchKey':f'sender:{address}::fromDate:{start}::toDate:{end}::inclspamtrash:true','start':0,'limit':10}),list)
            row['candidate_count']=len(found);row['candidate_bound']=2
            for candidate in found[:2]:
                mid=str(candidate.get('messageId',''));folder=str(candidate.get('folderId',''))
                if not mid.isdigit() or not folder.isdigit() or folder=='1083319000000008022' or _addresses(candidate.get('fromAddress'))!=(address,):continue
                base=f'/api/accounts/{ACCOUNT}/folders/{folder}/messages/{mid}'
                header=_headers(get(base+'/header',{'raw':'false'}))
                refs=set(re.findall(r'<[^<>\s]+@[^<>\s]+>',header.get('references','')+' '+header.get('in-reply-to','')))
                recipients=','.join(v for v in (header.get('to'),header.get('cc')) if v)
                if internet not in refs or _addresses(header.get('from'))!=(address,) or SENDER not in _addresses(recipients):continue
                payload=_data(get(base+'/content'),dict);content=payload.get('content')
                body=content.get('content') if isinstance(content,dict) else content
                if not isinstance(body,str) or len(body.encode())>131072:raise ValueError('MAIL_BODY_BOUND')
                at=_epoch_millis(candidate.get('receivedTime') or candidate.get('receivedtime'))
                if not when<at<=now+timedelta(minutes=2):continue
                item={'message_id':mid,'folder_id':folder,'internet_message_id':header.get('message-id'),'headers':header,
                      'received_at':at.isoformat(),'body':body,'match':'EXACT_REFERENCES_AND_SENDER'}
                existing=next((r for r in row['replies'] if r['message_id']==mid),None)
                if existing and existing.get('body')!=body:
                    # Representation changes are not silently overwritten. The
                    # canonical Forms receipts are wholly separate and untouched.
                    row['diagnostic']='MESSAGE_REPRESENTATION_CHANGED — EXISTING EVIDENCE RETAINED'
                    variant={'message_id':mid,'original_hash':digest(existing.get('body')),'incoming_hash':digest(body),'observed_at':now.isoformat()}
                    variants=row.setdefault('representation_variants',list(prior.get('representation_variants',[])))
                    if not any(v['incoming_hash']==variant['incoming_hash'] and v['message_id']==mid for v in variants):variants.append(variant)
                elif not existing:row['replies'].append(item)
            row['replies']=sorted(row['replies'],key=lambda r:r['received_at'])[-5:]
            row['search_complete']=len(found)<=2
            row['result']='EXACT_REPLY_BOUND' if row['replies'] else 'NO_EXACT_REPLY_BOUND — NOT NO_REPLY'
            if row['replies']:row['next_eligible_at']=(now+timedelta(hours=6)).isoformat()
        except (ValueError,OSError,RuntimeError) as exc:
            row['result']='READ_FAILED_OR_BOUNDED';row['error_class']=type(exc).__name__
        old[str(c['id'])]=row
    return {'schema':1,'at':now.isoformat(),'origin':cache.get('origin','UNKNOWN'),'provider_reads':calls,'provider_writes':0,
            'rows':list(old.values()),'attempted_contacts':attempts,'authority':'READ ONLY'}
