"""Small deterministic lifecycle plans over native CRM/Finance entities.

Plans confer no transport authority. Human qualification, pricing, external sends
and financial writes remain separate. Ambiguity produces attention, not guesses.
"""
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo
from .lifecycle_control import ATTR_FIELDS, digest

SOURCES={'ai_website':'https://ai.opticable.ca','opticable_website':'https://opticable.ca','zoho_form':None,
         'zoho_form_fr':'https://opticable.ca'}
SERVICES={'Structured Cabling':'Cabling Installation','CCTV':'Camera Installation',
    'Access Control':'Access Control Installation','Commercial WiFi':'Wifi Installation',
    'PTP Link':'Other','Managed Network':'Other'}
OWNER='5062683000000339001'

def aware(value):
    result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if result.tzinfo is None: raise ValueError('Lifecycle timestamp needs an offset')
    return result.astimezone(timezone.utc)

def email(value):
    value=str(value or '').strip().casefold()
    if not re.fullmatch(r'[^\s@]{1,64}@[^\s@]{1,189}',value):raise ValueError('Valid identity email required')
    return value

def phone(value):
    text=str(value or '').strip()
    if not text:return ''
    digits=re.sub(r'\D','',text)
    if len(digits)==10:digits='1'+digits
    if not 8<=len(digits)<=15:raise ValueError('Phone cannot be normalized deterministically')
    return '+'+digits

def next_followup(value):
    local=aware(value).astimezone(ZoneInfo('America/Toronto'))+timedelta(days=1)
    while local.weekday()>4:local+=timedelta(days=1)
    return local.replace(hour=10,minute=0,second=0,microsecond=0).isoformat()

def address_key(value):
    text=re.sub(r'[^\w\s]',' ',str(value or '').casefold())
    text=' '.join(text.split())
    # Exact punctuation/case/whitespace normalization only. No fuzzy street,
    # unit or postal-code merge and no inferred location from a company name.
    if len(text)<12:return None
    return text

SITE_FIELDS={'street':'Service_Location_Address_Street_Address','unit':'Service_Location_Address_Flat_House_No_Building_Ap',
    'city':'Service_Location_Address_City','province':'Service_Location_Address_State_Province',
    'postal_code':'Service_Location_Address_Zip_Postal_Code','country':'Service_Location_Address_Country_Region'}

def structured_site_key(value):
    # Use actual writable address components. Zoho silently ignores writes to
    # its read-only combined Service_Location_Address display field.
    parts={name:str(value.get(name,value.get(field,'')) or '').strip() for name,field in SITE_FIELDS.items()}
    if any(not parts[n] for n in ('street','city','province','postal_code','country')):return None
    if not re.search(r'\d',parts['street']) or len(parts['street'])<5:return None
    if parts['country'].casefold()!='canada':return None
    postal=re.sub(r'\s','',parts['postal_code']).upper()
    if not re.fullmatch(r'[A-Z]\d[A-Z]\d[A-Z]\d',postal):return None
    provinces={'qc':'quebec','québec':'quebec','quebec':'quebec','on':'ontario','ontario':'ontario'}
    province=provinces.get(parts['province'].casefold())
    if not province:return None
    return tuple(re.sub(r'[^\w]','',parts[n].casefold()) for n in ('street','unit','city'))+(province,postal,'canada')

def site_fields(value):
    if structured_site_key(value) is None:raise ValueError('Complete deterministic Canadian site address required')
    return {field:str(value.get(name,value.get(field,'')) or '').strip() for name,field in SITE_FIELDS.items()}

def site_match(sites,account_id,address):
    if isinstance(address,dict):
        key=structured_site_key(address)
        if not key:return {'decision':'HUMAN','reason':'Complete structured site address required'}
        existing=[s for s in sites if str((s.get('Linked_Account') or {}).get('id'))==str(account_id)]
        if any(structured_site_key(s) is None for s in existing):return {'decision':'HUMAN','reason':'Existing site lacks complete address; reconcile first'}
        matches=[s for s in existing if structured_site_key(s)==key]
        if len(matches)>1:return {'decision':'HUMAN','reason':'Multiple Service Locations match'}
        return {'decision':'REUSE' if matches else 'CREATE','record':matches[0] if matches else None,'key':key}
    key=address_key(address)
    if not key:return {'decision':'HUMAN','reason':'Full site address required'}
    matches=[s for s in sites if str((s.get('Linked_Account') or {}).get('id'))==str(account_id)
             and address_key(s.get('Service_Location_Address'))==key]
    missing=[s for s in sites if str((s.get('Linked_Account') or {}).get('id'))==str(account_id)
             and not address_key(s.get('Service_Location_Address'))]
    if missing:return {'decision':'HUMAN','reason':'Existing customer site has missing address; reconcile before creating another'}
    if len(matches)>1:return {'decision':'HUMAN','reason':'Multiple Service Locations match'}
    return {'decision':'REUSE' if matches else 'CREATE','record':matches[0] if matches else None,'key':key}

def verify_receipt(receipt):
    if receipt.get('schema')!=1 or receipt.get('source') not in SOURCES:raise ValueError('Unapproved intake source')
    expected=SOURCES[receipt['source']]
    if expected and receipt.get('origin')!=expected:raise ValueError('Intake origin/source mismatch')
    payload=receipt.get('request')
    if not isinstance(payload,dict) or receipt.get('payload_hash')!=digest(payload):raise ValueError('Private intake payload is missing or changed')
    if payload.get('consent') is not True:raise ValueError('Intake consent required')
    if not receipt.get('inquiry_id') or len(str(receipt['inquiry_id']))>255:raise ValueError('Stable inquiry identity required')
    if email(payload.get('email'))!=receipt.get('submitted_email'):raise ValueError('Receipt email mismatch')
    aware(receipt['occurred_at'])
    return payload

def attribution(payload,existing=None):
    incoming=payload.get('attribution') or {}
    fields={}
    for name in ATTR_FIELDS:
        key=name.casefold()
        value=incoming.get(key)
        if name.startswith('First_') and existing and existing.get(name):continue
        if value not in (None,''):
            fields[name]=aware(value).isoformat(timespec='seconds') if name.endswith('_Touch_Time') else str(value)[:2000]
    # Existing first-touch is immutable through returning inquiries. New last
    # touch is recorded, while every receipt remains append-only campaign history.
    return fields

def plan_intake(receipt,leads,contacts,*,protected_ids,activation_at=None,now=None):
    payload=verify_receipt(receipt)
    current=now or datetime.now(timezone.utc)
    received=aware(receipt['occurred_at'])
    if received>current+timedelta(minutes=5):raise ValueError('Intake server timestamp is in the future')
    if activation_at and received<aware(activation_at):return {'decision':'INELIGIBLE','reason':'Inquiry predates activation'}
    identity=email(payload['email']);telephone=phone(payload.get('phone'))
    matches=[r for r in leads if email_or_empty(r.get('Email'))==identity or telephone and phone_or_empty(r.get('Phone'))==telephone]
    contact_matches=[r for r in contacts if email_or_empty(r.get('Email'))==identity]
    if len(matches)>1 or len(contact_matches)>1:return {'decision':'HUMAN','reason':'Ambiguous exact identity'}
    if matches and email_or_empty(matches[0].get('Email'))!=identity:
        return {'decision':'HUMAN','reason':'Phone matches a different email; identity decision required'}
    if any(str(r['id']) in protected_ids for r in matches+contact_matches):return {'decision':'HUMAN','reason':'Protected historical identity; no automatic mutation'}
    if matches and activation_at and aware(matches[0]['Created_Time'])<aware(activation_at):return {'decision':'HUMAN','reason':'Existing Lead predates activation'}
    row=matches[0] if matches else None
    name=str(payload.get('name') or '').strip().split()
    if not name:return {'decision':'HUMAN','reason':'Person name required for qualification'}
    service=str(payload.get('service') or '').strip()
    patch={'Email':identity,'Normalized_Email':identity,
        'Last_Name':name[-1],'First_Name':' '.join(name[:-1]),
        'Service_Types':service,'Description':str(payload.get('message') or '')[:4000],
        'Inquiry_ID':str(receipt['inquiry_id']),'Ingestion_Source':receipt['source'],
        'Source_Record_ID':str(payload.get('source_record_id') or receipt['inquiry_id']),
        'Next_Followup_At':next_followup(receipt['occurred_at']),**attribution(payload,row)}
    if telephone:patch.update(Phone=telephone,Normalized_Phone=telephone)
    for field,key in [('Company','company'),('City','city')]:
        value=str(payload.get(key) or '').strip()
        if value:patch[field]=value
    if not row:patch['Owner']={'id':OWNER}
    if payload.get('address'):patch['Street']=str(payload['address'])
    for native,key in {'Google_GCLID':'google_gclid','Google_GBRAID':'google_gbraid',
            'Google_WBRAID':'google_wbraid','Meta_FBCLID':'meta_fbclid'}.items():
        value=payload.get('attribution',{}).get(key)
        if value:patch[native]=str(value)[:255]
    return {'decision':'UPDATE' if row else 'CREATE','record_id':str(row['id']) if row else None,
        'patch':patch,'contact_candidate':str(contact_matches[0]['id']) if contact_matches else None,
        'trigger':{'source':receipt['source'],'inquiry_id':receipt['inquiry_id'],'received_at':receipt['occurred_at'],
            'payload_hash':receipt['payload_hash'],'request_hash':receipt['request_hash']},
        'origin':{'site':receipt.get('origin_site',receipt.get('origin')),'path':receipt.get('origin_path'),
            'service':receipt.get('origin_service')},'click_ids':{k:v for k,v in payload.get('attribution',{}).items()
                if k in {'google_gclid','google_gbraid','google_wbraid','meta_fbclid','microsoft_msclkid','meta_fbp','meta_fbc'}}}

def email_or_empty(value):
    if not value:return ''
    try:return email(value)
    except ValueError:return ''

def phone_or_empty(value):
    try:return phone(value)
    except ValueError:return ''

def finance_relationship(record,books,kind,deals,sites,services):
    if kind not in {'estimate','invoice'}:raise ValueError('Unknown Finance kind')
    identifier=record.get('Estimate_ID' if kind=='estimate' else 'Invoice_ID')
    if str(identifier)!=str(books.get(kind+'_id')):raise ValueError('Finance/Books native transaction ID disagrees')
    account=str((record.get('Account_Name') or {}).get('id') or '')
    deal_id=str((record.get('Potential_Name') or {}).get('id') or books.get('zcrm_potential_id') or '')
    if not account or not deal_id:return {'decision':'HUMAN','reason':'Finance requires native Account and Deal association','financial_writes':False}
    deal=next((d for d in deals if str(d['id'])==deal_id),None)
    if not deal or str((deal.get('Account_Name') or {}).get('id'))!=account:
        return {'decision':'HUMAN','reason':'Finance Account/Deal association disagrees','financial_writes':False}
    related=[s for s in services if str((s.get('Linked_Deal') or {}).get('id'))==deal_id]
    site_ids={str((s.get('Linked_Service_Location') or {}).get('id')) for s in related}
    direct=(deal.get('Service_Location') or {}).get('id')
    if direct:site_ids.add(str(direct))
    site=next((s for s in sites if str(s['id']) in site_ids),None)
    if len(site_ids)!=1 or not site or str((site.get('Linked_Account') or {}).get('id'))!=account:
        return {'decision':'HUMAN','reason':'One unambiguous Service Location required','financial_writes':False}
    return {'decision':'OBSERVE','transaction_id':identifier,'number':books.get(kind+'_number'),
        'account_id':account,'deal_id':deal_id,'site_id':str(site['id']),'service_ids':[str(s['id']) for s in related],
        'status':books.get('status'),'amount':books.get('total'),'balance':books.get('balance'),
        'due_date':books.get('due_date'),'financial_writes':False}

def reminder_due(*,estimate_status,due_at,now,replied=False,suppressed=False,deal_closed=False):
    if estimate_status in {'accepted','declined','rejected','invoiced','void'} or replied or suppressed or deal_closed:
        return {'decision':'STOP','external_send':False}
    if estimate_status not in {'sent','viewed'}:return {'decision':'WAIT','external_send':False}
    return {'decision':'INTERNAL_TASK' if aware(due_at)<=aware(now) else 'WAIT','external_send':False}

def accepted_plan(service_types,*,account_id,deal_id,site_id):
    requested=[p.strip() for p in str(service_types or '').split(',') if p.strip()]
    if not requested or len(set(requested))!=len(requested) or any(s not in SERVICES for s in requested):
        return {'decision':'HUMAN','reason':'Accepted scope needs deterministic service mapping'}
    if not all(str(i).isdigit() for i in (account_id,deal_id,site_id)):
        return {'decision':'HUMAN','reason':'Native customer/Deal/site links required'}
    return {'decision':'PREPARE_INTERNAL','services':[{'label':s,'type':SERVICES[s]} for s in requested],
        'account_id':str(account_id),'deal_id':str(deal_id),'site_id':str(site_id),
        'workdrive':['Account','General','Service Location','Contracts'],
        'contract':'PREPARE_ONLY','installation':'UNSCHEDULED','external_sends':False,'financial_writes':False}
