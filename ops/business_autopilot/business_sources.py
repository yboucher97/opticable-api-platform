"""Bounded proposal-only reads on the existing worker, gateway, cache and store.

No scheduler, intake replay, write transport or credential store. Fresh imported
observations and the existing immutable mailbox evidence are reused first. Each
Toronto date reserves one read budget in existing manager receipts before I/O;
interruption cannot cause unbounded retries. Optional contained services stay out.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import signal
import sqlite3
import time
import zlib
from zoneinfo import ZoneInfo
from business_work import fresh, stable_id, synthetic

SOURCE='platform:business_operations'
ACCOUNT='1083319000000008002'
MAX_CALLS=5


def rows(response):
    data=response.get('data',{})
    return data if isinstance(data,list) else data.get('data',[]) if isinstance(data,dict) else []


def inquiry(details,content):
    # Reuse the existing parser; this is not a new authenticated form receipt.
    from workflow.automation.phase9_form_receipts import _FormTable, LABELS, _MergedContexts
    identity=stable_id(details.get('messageId'))
    if details.get('fromAddress','').casefold()!='notifications@zohoforms.com' or 'soumissions@opticable.ca' not in str(details.get('toAddress','')).casefold():return None
    parser=_FormTable();parser.feed(content)
    fields={LABELS[row[0]]:row[-1][:6000] for row in parser.rows if len(row)>=2 and row[0] in LABELS}
    if not all(fields.get(k) for k in ('company','name','service','notes')) or synthetic(fields):return None
    lang='fr' if any(row and row[0]=='Nom du contact' for row in parser.rows) else 'en'
    merge=_MergedContexts();merge.feed(content);contexts=[]
    for raw in merge.contexts:
        try:contexts.append(json.loads(raw))
        except (ValueError,TypeError):pass
    return {'message_id':identity,'account_id':ACCOUNT,'received_at':datetime.fromtimestamp(int(details['receivedTime'])/1000,timezone.utc).isoformat(),
            'fields':fields,'language':lang,'captured_context':contexts,'acknowledgement':'NATIVE_NOTIFICATION_ONLY_NOT_COMPLETE_FORM_ACK',
            'content_sha256':hashlib.sha256(content.encode()).hexdigest()}


def normalize(raw):
    observed=raw['captured_at'];mail=[]
    for v in raw.get('mail',[]):
        item=inquiry(v['details'],v['content']['content'])
        if item:mail.append(item)
    # Exact native ID join; do not join similar names, company or email.
    leads={x['id']:x for x in rows(raw.get('lead_inventory',{})) if isinstance(x.get('id'),str) and not synthetic(x)}
    for v in rows(raw.get('leads',{})):
        if v.get('id') in leads:leads[v['id']].update(v)
    return {'schema':1,'captured_at':observed,'mail':{'observed_at':observed,'inquiries':mail,'coverage':'Bounded read of submission notifications; not complete mail or reply coverage'},
            'crm':{'observed_at':observed,'leads':list(leads.values()),'tasks':[x for x in rows(raw.get('tasks',{})) if not synthetic(x)],
                   'partial':bool(raw.get('tasks',{}).get('data',{}).get('info',{}).get('more_records',True))},
            'calendar':{'observed_at':observed,'calendar_id':'info@opticable.ca','events':[{**e,'start_time':e['start'],'end_time':e['end']} for e in raw.get('calendar',{}).get('events',[])]},
            'native_lead_fields':[{k:f.get(k) for k in ('api_name','data_type','length','read_only','field_read_only','operation_type')} for f in raw.get('lead_fields',{}).get('data',{}).get('fields',[])],
            'blocked':raw.get('blocked',[]),'provider_writes':0,'paid_calls':0}


def latest(database):
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT id,raw,raw_bytes FROM acquisition_snapshots WHERE source=? ORDER BY retrieved_at DESC,id DESC LIMIT 1',(SOURCE,)).fetchone()
    if not row:return {}
    d=zlib.decompressobj();raw=d.decompress(row[1],2097153)
    if not d.eof or len(raw)!=row[2] or len(raw)>2097152:raise ValueError('Business snapshot size/integrity')
    result=json.loads(raw);result['snapshot_ids']=[row[0]];return result


class Reader:
    def __init__(self,client):self.client=client;self.calls=0;self.bytes=0
    def get(self,service,path,query):
        allowed=(service=='zohoapis' and path in ('/crm/v8/Leads','/crm/v8/Tasks')) or (service=='mail' and (
            path==f'/api/accounts/{ACCOUNT}/messages/search' or re.fullmatch(r'/api/accounts/'+ACCOUNT+r'/folders/\d+/messages/\d+/content',path)))
        if not allowed or self.calls>=MAX_CALLS:raise PermissionError('Exact read-only endpoint/budget required')
        self.calls+=1
        value=self.client.request(service,'GET',path,query=query)
        size=len(json.dumps(value).encode());self.bytes+=size
        if size>1048576 or self.bytes>2097152:raise ValueError('Business source byte budget')
        if value.get('ok') is False:raise ValueError('Native business read unavailable')
        return value


def refresh(database, settings, now, store):
    """Parent-only. Failure holds reads; independent content work can continue."""
    saved=latest(database)
    if fresh(saved.get('captured_at'),now,hours=22):return saved,{'state':'CACHED','provider_calls':0}
    day=now.astimezone(ZoneInfo('America/Toronto')).date().isoformat()
    from workflow.automation.acquisition_store import digest
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True) as db:
        prior=db.execute('SELECT 1 FROM manager_receipts WHERE id=?',(digest(['business-source-read',day]),)).fetchone()
    if prior:return saved,{'state':'HELD_PRIOR_DAILY_ATTEMPT','provider_calls':0}
    from workflow.automation.manager_store import ManagerStore
    manager=ManagerStore(database)
    manager.receipt('business-source-read',day,now,{'state':'RESERVED','max_calls':MAX_CALLS,'provider_writes':0,'paid_calls':0})
    from workflow.zoho_gateway import ZohoGatewayClient
    from workflow.zoho_oauth import ZohoOAuthManager
    from dataclasses import replace
    oauth=ZohoOAuthManager(settings.zoho_oauth)
    # Reuse only the existing bound cache. Independent OAuth renewal owns refresh.
    # No token copy, credential modification, new refresh path or standby fallback.
    try:credentials=oauth.load_saved_credentials();cache=oauth._read_cache()
    except Exception as error:
        return saved,{'state':'HELD_EXISTING_OAUTH_UNAVAILABLE','error_class':type(error).__name__,'provider_calls':0}
    binding=hashlib.sha256((str(settings.zoho_oauth.client_id)+'\0'+str((credentials or {}).get('refresh_token',''))).encode()).hexdigest()
    if cache.get('binding')!=binding or not cache.get('access_token') or cache.get('access_token_expires_at',0)<time.time()+120:
        return saved,{'state':'HELD_EXISTING_OAUTH_RENEWAL_REQUIRED','provider_calls':0}
    class CachedOAuth:
        def status(self):return oauth.status()
        def access_token(self):return cache['access_token']
        def invalidate_access_token(self,token):raise PermissionError('Existing OAuth renewal owns token invalidation')
    reader=Reader(ZohoGatewayClient(replace(settings.zoho_gateway,timeout_seconds=5,standby_enabled=False),CachedOAuth()))
    value={**saved};value.pop('snapshot_ids',None);value['captured_at']=now.isoformat()
    def timeout(*_):raise TimeoutError('Business source deadline')
    previous=signal.signal(signal.SIGALRM,timeout);signal.alarm(30)
    state='CURRENT';errors=[]
    try:
        # CRM first: precise existing tasks and links are valuable without any write.
        leads=reader.get('zohoapis','/crm/v8/Leads',{'fields':'id,First_Name,Last_Name,Company,Email,Description,Lead_Status,Inquiry_ID,First_Source,First_Campaign_ID,Last_Campaign_ID','per_page':50})
        tasks=reader.get('zohoapis','/crm/v8/Tasks',{'fields':'id,Subject,Due_Date,Status,What_Id,Who_Id,Description,Modified_Time','sort_by':'Modified_Time','sort_order':'desc','per_page':50})
        value['crm']={'observed_at':now.isoformat(),'leads':[x for x in rows(leads) if not synthetic(x)],'tasks':[x for x in rows(tasks) if not synthetic(x)],
                      'partial':any(x.get('data',{}).get('info',{}).get('more_records',True) for x in (leads,tasks))}
        # Reuse immutable bodies where present, fetch at most two missing bodies.
        cutoff=(now-timedelta(days=7)).strftime('%d-%b-%Y')
        mail=reader.get('mail',f'/api/accounts/{ACCOUNT}/messages/search',{'searchKey':'to:soumissions@opticable.ca::fromDate:'+cutoff,'start':1,'limit':10})
        inquiries=[]
        for item in rows(mail)[:10]:
            if item.get('fromAddress','').casefold()!='notifications@zohoforms.com':continue
            identity=stable_id(item.get('messageId'));folder=stable_id(str(item.get('folderId','')))
            body=None
            p=settings.automation.db_path
            with sqlite3.connect(Path(p).resolve().as_uri()+'?mode=ro',uri=True) as db:
                row=db.execute("SELECT payload_json FROM automation_events WHERE source='zoho-mail-poller' AND idempotency_key=? LIMIT 1",('email:'+ACCOUNT+':'+identity,)).fetchone()
            if row:
                payload=json.loads(row[0]);body=payload.get('body')
                # Existing plain-body events cannot substitute for native table content.
                if body and '<table' not in body:body=None
            if body is None:
                if reader.calls>=MAX_CALLS:errors.append('Additional inquiry bodies deferred by fixed daily read budget');break
                response=reader.get('mail',f'/api/accounts/{ACCOUNT}/folders/{folder}/messages/{identity}/content',{})
                from workflow.automation.providers.lifecycle_mailbox import _message_content
                body=_message_content(response)
            parsed=inquiry(item,body or '')
            if parsed:inquiries.append(parsed)
        value['mail']={'observed_at':now.isoformat(),'inquiries':inquiries,'coverage':'Bounded 7-day/10-header search; at most two missing bodies; sent/thread audit absent; no unanswered claim'}
    except Exception as error:
        state='PARTIAL';errors.append(type(error).__name__)
    finally:signal.alarm(0);signal.signal(signal.SIGALRM,previous)
    value['source_refresh']={'state':'PARTIAL' if errors else state,'errors':errors,'provider_calls':reader.calls,'paid_calls':0,'provider_writes':0}
    # Each group preserves its own observation timestamp when an upstream read fails.
    sid=store.snapshot(SOURCE,'https://www.zohoapis.com/crm/v8/Tasks',value,now)
    value['snapshot_ids']=[sid]
    manager.receipt('business-source-read-result',day,now,value['source_refresh'])
    return value,value['source_refresh']
