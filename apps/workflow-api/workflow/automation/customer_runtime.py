"""Pinned root adapter from native CRM/Finance/Mail facts to bounded send plans."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import fcntl
import json
import os
from email.utils import getaddresses

from . import customer_send_control as control
from . import customer_communications as domain
from .lifecycle_control import trusted_json, digest
from .real_internal import atomic, human_transition, synthetic, same
from .lifecycle import aware, finance_relationship, SITE_FIELDS, OWNER

DISPLAY=Path('/run/optibrain-readiness/customer-communications.json')

def identity(value):
    return str((value or {}).get('id') or '') if isinstance(value,dict) else str(value or '')

class NativeReader:
    def __init__(self,client):self.client=client;self.reads=0
    def get(self,path,query=None,*,service='zohoapis'):
        self.reads+=1
        if self.reads>160:raise ValueError('Customer observation read bound reached')
        response=self.client.request(service,'GET',path,query=query or {})
        if response.get('ok') is not True or response.get('status')!=200 or not isinstance(response.get('data'),dict):
            raise ValueError('Authoritative customer provider read failed')
        return response['data']
    def record(self,module,record_id):
        rows=self.get('/crm/v8/'+module+'/'+str(record_id)).get('data',[])
        if len(rows)!=1 or str(rows[0].get('id'))!=str(record_id):raise ValueError('Exact customer record unavailable')
        return rows[0]
    def list(self,module,fields):
        value=self.get('/crm/v8/'+module,{'fields':fields,'per_page':200})
        if value.get('info',{}).get('more_records'):raise ValueError('Customer inventory requires complete pagination')
        return value.get('data') or []
    def mail_search(self,query):
        data=self.get('/api/accounts/'+control.MAIL_ACCOUNT+'/messages/search',
            {'searchKey':query,'start':1,'limit':100,'receivedTime':int((datetime.now(timezone.utc)+timedelta(minutes=2)).timestamp()*1000)},service='mail').get('data')
        if not isinstance(data,list) or len(data)>=100:raise ValueError('Complete Mail suppression observation unavailable')
        return data

def language_code(value):
    value=str(value or '').casefold().replace('_','-')
    return value.split('-')[0] if value.split('-')[0] in {'fr','en'} else None

def preferred_language(books_customer,lineage):
    native=language_code(books_customer.get('language_code'))
    if native:return native,'native_finance'
    path=str(lineage.get('origin_path') or '')
    if path.startswith('/fr/'):return 'fr','intake_language'
    if path.startswith('/en/'):return 'en','intake_language'
    if lineage.get('source')=='zoho_form_fr':return 'fr','intake_language'
    return None,None

def decorate(plan):
    if plan.get('state')=='READY':
        plan={**plan,'message':{'fromAddress':control.SENDER,'toAddress':plan['recipient'],
            'subject':plan['subject'],'content':plan['body'],'mailFormat':'plaintext'}}
    return plan

def schedule_provenance(visit,rows,cutoff):
    """Only the latest actual logistics changes create a schedule revision."""
    chosen={}
    fields={'Installation_Status','Scheduled_Date','Assigned_To','Instructions_Notes'}
    for row in rows:
        record=row.get('record') or {}
        if identity(record)!=visit['id'] or (record.get('module') or {}).get('api_name')!='Installations':continue
        for change in row.get('field_history',[]):
            field=change.get('api_name')
            if field not in fields:continue
            at=aware(row['audited_time'])
            if field in chosen and at==chosen[field][0] and change!=chosen[field][2]:return None
            if field not in chosen or at>chosen[field][0]:chosen[field]=(at,row,change)
    evidence={}
    for field in ['Installation_Status','Scheduled_Date','Assigned_To']:
        if field not in chosen:return None
        at,row,change=chosen[field];value=change.get('_value') or {}
        if (at<aware(cutoff) or row.get('source')!='crm_ui' or identity(row.get('done_by'))!=OWNER
                or not same(value.get('new'),visit.get(field))):return None
        evidence[field]={'at':at.isoformat(),'value':visit.get(field)}
    # Access-note edits change logistics, while unrelated record edits do not.
    if 'Instructions_Notes' in chosen:
        at,row,change=chosen['Instructions_Notes']
        if (row.get('source')!='crm_ui' or identity(row.get('done_by'))!=OWNER
                or not same((change.get('_value') or {}).get('new'),visit.get('Instructions_Notes'))):return None
        evidence['Instructions_Notes']={'at':at.isoformat(),'value':visit.get('Instructions_Notes')}
    return digest(evidence)

class Adapter:
    def __init__(self,reader,state,ownership,sender):
        self.reader=reader;self.state=state;self.ownership=ownership;self.sender=sender
        self.activation=trusted_json(Path('/var/lib/optibrain/lifecycle/activation.json'))
        self.suppression=trusted_json(control.ROOT/'suppression.json',262144)
    def native(self,deal_id,transaction=None):
        lineage=self.state['deals'][deal_id]
        deal=self.reader.record('Deals',deal_id)
        contact=self.reader.record('Contacts',lineage['contact_id'])
        account=self.reader.record('Accounts',lineage['account_id'])
        site=self.reader.record('Service_Locations',lineage['site_id'])
        if any(synthetic(x) for x in [deal,contact,account,site]):raise ValueError('Synthetic record is not a real customer')
        protected={str(i) for m in trusted_json(control.BASELINE)['modules'].values() for i in m.get('protected_versions',{})}
        if any(x['id'] in protected for x in [deal,contact,account,site]):raise ValueError('Protected customer context is ineligible')
        if self.ownership['records'].get(deal_id,{}).get('ownership')!='REAL_NEW':raise ValueError('Customer Deal lacks root new-record ownership')
        books_customer={}
        if transaction:
            books=transaction['books']
            books_customer=self.reader.get('/books/v3/contacts/'+str(books['customer_id']),{'organization_id':'802337532'}).get('contact') or {}
            if str(books_customer.get('zcrm_account_id'))!=account['id']:raise ValueError('Books customer belongs to a different Account')
        locale,locale_source=preferred_language(books_customer,lineage)
        at=datetime.now(timezone.utc).isoformat()
        proof={'mode':'REAL_NEW','lineage_verified':True,'protected':False,
            'contact_id':contact['id'],'account_id':account['id'],'deal_id':deal['id'],'site_id':site['id'],
            'contact_email':contact.get('Email'),'contact_account_id':identity(contact.get('Account_Name')),
            'deal_account_id':identity(deal.get('Account_Name')),'deal_contact_id':identity(deal.get('Contact_Name')),
            'deal_site_id':identity(deal.get('Service_Location')),'site_account_id':identity(site.get('Linked_Account')),
            'contact_version':contact.get('Modified_Time'),'deal_version':deal.get('Modified_Time'),'site_version':site.get('Modified_Time'),
            'observed_at':at,'language':locale,'language_source':locale_source,
            'opt_out':contact.get('Email_Opt_Out') if contact.get('Email_Opt_Out') is not None else None}
        return lineage,deal,contact,site,proof
    def stop_signals(self,contact,since,object_id):
        recipient=domain.normalize_recipient(contact.get('Email'))
        reply=False
        for row in self.reader.mail_search('sender:'+recipient):
            senders={e.casefold() for _,e in getaddresses([str(row.get('fromAddress') or '')])}
            if recipient in senders and datetime.fromtimestamp(int(row['receivedTime'])/1000,timezone.utc)>=aware(since):reply=True
        bounce=False
        for row in self.reader.mail_search('sender:mailer-daemon')+self.reader.mail_search('sender:postmaster'):
            if datetime.fromtimestamp(int(row['receivedTime'])/1000,timezone.utc)<aware(since):continue
            base='/api/accounts/'+control.MAIL_ACCOUNT+'/folders/'+str(row['folderId'])+'/messages/'+str(row['messageId'])
            content=self.reader.get(base+'/content',service='mail').get('data') or {}
            if recipient in json.dumps(content).casefold():bounce=True
        suppressed=str(object_id) in self.suppression.get('objects',{}) or recipient in self.suppression.get('recipients',{})
        return {'replied':reply,'manual_suppression':suppressed,'delivery_failure':bounce,
                'unsubscribed':contact.get('Email_Opt_Out') is True or bool(contact.get('Unsubscribed_Time')),
                'superseded':False,'suppression_checked_at':datetime.now(timezone.utc).isoformat()}
    def history(self):
        return self.sender.history()
    def quote(self,deal_id,native):
        native=self.reader.record('CustomModule5002',native['id'])
        identifier=str(native.get('Estimate_ID') or '')
        if not identifier.isdigit():raise ValueError('Native integrated Estimate identifier required')
        books=self.reader.get('/books/v3/estimates/'+identifier,{'organization_id':'802337532'}).get('estimate') or {}
        lineage,deal,contact,site,proof=self.native(deal_id,{'books':books})
        relation=finance_relationship(kind='estimate',record=native,books=books,deals=[deal],sites=[site],services=[])
        if relation['decision']!='OBSERVE':raise ValueError('Native Estimate associations require human review')
        from .customer_finance_evidence import estimate_sent_at
        org=self.reader.get('/books/v3/organizations/802337532').get('organization') or {}
        history=self.reader.get('/books/v3/estimates/'+identifier+'/comments',{'organization_id':'802337532'})
        if history.get('page_context',{}).get('has_more_page') or history.get('info',{}).get('more_records'):
            raise ValueError('Complete native Estimate send history required')
        sent_proof=estimate_sent_at(history.get('comments'),org.get('time_zone'),estimate_id=identifier)
        if sent_proof['decision']!='OBSERVE':raise ValueError(sent_proof['reason'])
        sent=sent_proof['cadence_anchor_at']
        at=datetime.now(timezone.utc).isoformat()
        context={**{k:proof[k] for k in ['contact_id','account_id','deal_id','site_id']},'recipient_email':contact.get('Email'),
            'observed_at':at,'object_id':identifier,'estimate_id':identifier,'estimate_number':books.get('estimate_number'),
            'finance_integrated':True,'native_books_verified':True,'native_crm_finance_verified':True,
            'finance_account_id':relation['account_id'],'finance_deal_id':relation['deal_id'],
            'finance_site_id':relation['site_id'],'status':books.get('status'),'sent_at':sent,
            'expiry_date':books.get('expiry_date'),'deal_active':deal.get('Stage') not in {'Closed Won','Closed Lost','Estimate Rejected','Closed Lost to Competition'},
            **self.stop_signals(contact,sent,identifier)}
        # A newer Deal-linked Estimate supersedes the older one.
        created=aware(books['created_time'])
        for other in self.reader.list('CustomModule5002','id,Account_Name,Potential_Name,Estimate_ID'):
            if identity(other.get('Potential_Name') or other.get('PotentialName'))!=deal_id:continue
            other_id=str(other.get('Estimate_ID') or '')
            if other_id==identifier:continue
            if not other_id.isdigit():raise ValueError('Other Deal Estimate identifier unavailable')
            other_books=self.reader.get('/books/v3/estimates/'+other_id,{'organization_id':'802337532'}).get('estimate') or {}
            other_created=aware(other_books['created_time'])
            if other_created==created:raise ValueError('Multiple Estimate versions require owner choice')
            if other_created>created:context['superseded']=True
        previous=self.state.get('effects',{}).get('task:quote-followup:'+identifier)
        if previous and previous.get('state')=='verified':
            task=self.reader.record('Tasks',previous['provider_id'])
            if task.get('Status')=='Completed':context['manual_suppression']=True
        history=self.history()
        plan=decorate(domain.plan_quote_reminder(context,proof,history,datetime.now(timezone.utc),communications_enabled=True))
        return plan,{'proof':proof,'context':context,'history':history,'plan':plan,'created_at':deal['Created_Time'],
            'lineage_run':self.activation['run'],'native_sent_evidence':sent_proof}
    def installation(self,deal_id,installation_id,family,transaction=None):
        from .operational_lifecycle import installation_context
        lineage,deal,contact,site,proof=self.native(deal_id,transaction)
        visit=self.reader.record('Installations',installation_id)
        services=[self.reader.record('Services',i) for i in lineage.get('service_ids',[])]
        links=self.reader.list('Installation_X_Services','id,Linked_Installation,Linked_Service')
        context_proof=installation_context(visit,services=services,sites=[site],accounts=[self.reader.record('Accounts',lineage['account_id'])],
            deals=[deal],contacts=[contact],links=links,deal_id=deal_id)
        if context_proof['decision']!='PREPARE_INTERNAL':raise ValueError(context_proof['reason'])
        history=self.reader.get('/crm/v8/Installations/'+installation_id+'/__timeline',{'per_page':200})
        if history.get('info',{}).get('more_records'):raise ValueError('Complete owner scheduling timeline required')
        rows=history.get('__timeline') or []
        def human(field,value):return human_transition(visit,rows,self.activation['activated_at'],'Installations',field,value)
        status_human=human('Installation_Status',visit.get('Installation_Status'))
        schedule_evidence=schedule_provenance(visit,rows,self.activation['activated_at'])
        schedule_human=bool(schedule_evidence)
        completed_at=lineage.get('visits',{}).get(installation_id,{}).get('completed_at')
        at=datetime.now(timezone.utc).isoformat()
        context={**{k:proof[k] for k in ['contact_id','account_id','deal_id','site_id']},'recipient_email':contact.get('Email'),
            'observed_at':at,'object_id':installation_id,'installation_id':installation_id,
            **{'installation_'+k:proof[k] for k in ['contact_id','account_id','deal_id','site_id']},
            'installation_status':visit.get('Installation_Status'),'scheduled_at':visit.get('Scheduled_Date'),
            'timezone':'America/Toronto','technician_required':True,'technician_id':visit.get('Assigned_To'),
            'access_instructions':visit.get('Instructions_Notes'),'site_display':', '.join(str(site.get(v) or '') for v in SITE_FIELDS.values()),
            'human_schedule_confirmed':schedule_human,'human_schedule_evidence':schedule_evidence,
            'cancelled':visit.get('Installation_Status')=='Cancelled','completed_at':completed_at,
            'human_completion_confirmed':status_human and visit.get('Installation_Status')=='Completed',
            'human_completion_evidence':digest(rows) if status_human else None,
            'return_visit_required':visit.get('Installation_Status') in {'Revisit Required','RevisitRequired'},
            **self.stop_signals(contact,visit['Created_Time'],installation_id)}
        function={'customer.appointment.confirmation':domain.plan_appointment_confirmation,
                  'customer.appointment.reminder':domain.plan_appointment_reminder,
                  'customer.completion.message':domain.plan_completion_message}[family]
        history=self.history()
        plan=decorate(function(context,proof,history,datetime.now(timezone.utc),communications_enabled=True))
        return plan,{'proof':proof,'context':context,'history':history,'plan':plan,'created_at':deal['Created_Time'],'lineage_run':self.activation['run']}

def run(client,*,dry_run=False):
    from .customer_delivery import RootSender
    os.umask(0o077)
    current=control.policy()
    lock=os.open(control.ROOT/'runner.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    reader=NativeReader(client);attention=[];plans=[];sent=0
    if current['external_enabled'] and aware(current['expires_at'])-datetime.now(timezone.utc)<timedelta(days=7):
        attention.append({'context':'Review customer automation authorization','why':'Scoped authority expires within seven days',
            'next_action':'Engineer reviews evidence and deliberately renews scopes; preserve cutoff and claims','priority':'HIGH'})
    if current['external_enabled'] and current['real_scopes']:
        state=trusted_json(Path('/var/lib/optibrain/lifecycle/state.json'),1048576)
        ownership=trusted_json(Path('/var/lib/optibrain/lifecycle/ownership.json'),1048576)
        sender=RootSender(client,lambda:None)
        adapter=Adapter(reader,state,ownership,sender)
        native=reader.list('CustomModule5002','id,Account_Name,Potential_Name,Estimate_ID') if state.get('deals') else []
        for deal_id,lineage in state.get('deals',{}).items():
            estimate_rows=[row for row in native if identity(row.get('Potential_Name') or row.get('PotentialName'))==deal_id]
            candidates=[('customer.quote.reminder',lambda row=row:adapter.quote(deal_id,row)) for row in estimate_rows]
            latest=None
            for row in estimate_rows:
                identifier=str(row.get('Estimate_ID') or '')
                if identifier.isdigit():
                    books=reader.get('/books/v3/estimates/'+identifier,{'organization_id':'802337532'}).get('estimate') or {}
                    if books.get('status')=='accepted':latest={'books':books}
            for installation_id in list(dict.fromkeys([lineage.get('installation_id'),*lineage.get('visits',{})])):
                if installation_id:
                    candidates.extend((family,lambda family=family:adapter.installation(deal_id,installation_id,family,latest))
                        for family in ['customer.appointment.confirmation','customer.appointment.reminder','customer.completion.message'])
            for family,build in candidates:
                if family not in current['real_scopes']:continue
                try:
                    plan,source=build();plans.append({k:plan.get(k) for k in ['family','state','reason','idempotency_key']})
                    if plan['state']=='READY' and not dry_run and sent<current['per_cycle_limit']:
                        sender.refresh=lambda build=build:build()[0]
                        result=sender.send(plan,source)
                        sent+=int(result.get('state')=='VERIFIED')
                        if result.get('state') in {'HOLD','DUPLICATE','BOUNDED'}:
                            attention.append({'context':'Customer communication paused','why':result.get('reason') or 'Provider effect needs reconciliation',
                                'next_action':'Engineer reviews this family before retry','module':'Deals','identity':deal_id,'priority':'HIGH'})
                    elif plan['state'] in {'HUMAN','RECONCILE'}:
                        attention.append({'context':'Customer communication needs review','why':plan['reason'],'next_action':'Review customer context in CRM','module':'Deals','identity':deal_id,'priority':'HIGH'})
                    elif plan['state']=='SUPPRESSED' and (source['context'].get('replied') or source['context'].get('delivery_failure')):
                        attention.append({'context':'Customer email delivery issue' if source['context'].get('delivery_failure') else 'Customer reply',
                            'why':'Automatic follow-up suppressed by fresh Mail evidence','next_action':'Review the customer conversation in Zoho Mail / CRM',
                            'module':'Deals','identity':deal_id,'priority':'HIGH'})
                except Exception:
                    attention.append({'context':'Customer communication paused','why':'Recipient, provider or effect evidence needs review','next_action':'Engineer reconciles this family before retry','module':'Deals','identity':deal_id,'priority':'HIGH'})
    result={'schema':1,'scope':'live','read_only':True,'at':datetime.now(timezone.utc).isoformat(),
        'state':'DRY_RUN' if dry_run else 'READY' if current['external_enabled'] else 'OFF',
        'attention':attention,'plans':plans,'sends_this_cycle':sent,'provider_reads':reader.reads}
    atomic(DISPLAY,result,0o644)
    return result
