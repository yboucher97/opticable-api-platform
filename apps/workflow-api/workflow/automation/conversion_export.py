"""One-event Data Manager export. Independent authority; no advertising strategy API.

Input events are root-held, independently verified transition receipts. A native
record's Created/Modified time is never substituted for an outcome timestamp.
Unknown delivery or an existing off-host claim means HOLD, never another POST.
"""
from datetime import datetime, timezone
from decimal import Decimal
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from .measurement import populations
from .finance_links import resolve_finance
from .recurring_lifecycle import identity, money

CONTROL = Path('/etc/optibrain/conversion-export-control.json')
ROOT = Path('/var/lib/optibrain/conversion-export')
BASE = 'https://datamanager.googleapis.com/v1/'
SCOPE = 'https://www.googleapis.com/auth/datamanager'
KINDS = {'qualified_lead':'leads', 'estimate_accepted':'estimates', 'invoice_paid':'invoices'}
GRANT=ContextVar('optibrain_conversion_export',default=None)


@contextmanager
def conversion_scope(client,plan,*,live,claim=None,audit=None):
    if GRANT.get() is not None:raise ValueError('Nested conversion authority forbidden')
    if live and (not claim or claim.get('key')!=plan['key'] or claim.get('payload_hash')!=plan['payload_hash']):
        raise ValueError('Fresh off-host conversion claim required')
    if live:
        from .action_evidence import ActionEvidence
        if not isinstance(audit,ActionEvidence) or (audit.get(conversion_action_id(plan)) or {}).get('status')!='STARTED':
            raise ValueError('Started durable conversion action required before transport')
    token=GRANT.set({'client':client,'plan':plan,'live':live,'claim':claim,'audit':audit,'used':False})
    try:yield
    finally:GRANT.reset(token)


def check_transport(client,service,method,path,body,headers,*,recheck=False,content_type='application/json',query=None):
    grant=GRANT.get()
    if not grant:return False
    expected=json.loads(json.dumps(grant['plan']['body']));expected['validateOnly']=not grant['live']
    if (not isinstance(client,DataManager) or grant['client'] is not client or service!='google_datamanager'
        or method!='POST' or path!='/v1/events:ingest' or body!=expected or headers or query
        or content_type!='application/json' or grant['used'] is not recheck):
        raise ValueError('Exact one-use conversion transport required')
    client.authorize(grant['plan'],live=grant['live'])
    if grant['live'] and grant['audit'].get(conversion_action_id(grant['plan']))['status']!='STARTED':
        raise ValueError('Conversion action is no longer executable')
    grant['used']=True
    return True


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def aware(value):
    at=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if at.tzinfo is None:raise ValueError('Explicit event timezone required')
    return at.astimezone(timezone.utc)


def event_key(event):
    kind=event.get('kind');rid=identity(event.get('record_id'))
    if kind not in KINDS or not rid or event.get('version')!=1:
        raise ValueError('Canonical business outcome identity required')
    # Time, value, observer run and conversion destination are NOT new identities.
    return digest({'provider':'google_ads','kind':kind,'record_id':rid,'version':1})


def destination(control,kind,now):
    dest=control.get('destinations',{}).get(kind,{})
    if (dest.get('account_id')!='6808491878' or not re.fullmatch(r'[0-9]+',str(dest.get('action_id','')))
        or dest.get('type')!='UPLOAD_CLICKS' or dest.get('status')!='ENABLED'
        or dest.get('primary_for_goal') is not False or dest.get('used_in_custom_goal') is not False
        or not dest.get('native_verification_receipt')):
        raise ValueError('Native enabled secondary import destination required')
    if not 0 <= (now-aware(dest.get('verified_at'))).total_seconds() <= 30*86400:
        raise ValueError('Destination verification expired')
    return dest


def build_plan(event,snapshot,control,*,now=None):
    now=now or datetime.now(timezone.utc);key=event_key(event);kind=event['kind']
    rows,_=populations(snapshot);row=rows[KINDS[kind]].get(event['record_id'])
    if row is None:raise ValueError('Missing or TEST-owned outcome denied')
    proof=event.get('proof',{})
    if (proof.get('native_record_id')!=event['record_id'] or proof.get('verified') is not True
        or not re.fullmatch(r'[0-9a-f]{64}',str(proof.get('immutable_source_sha256','')))
        or proof.get('timestamp_basis') not in {'CRM_UI_TRANSITION','NATIVE_OUTCOME_TIMESTAMP','INDEPENDENT_PROVIDER_RECEIPT'}):
        raise ValueError('Independently verified immutable transition receipt required')
    at=aware(event.get('occurred_at'));activation=aware(control.get('eligible_after'))
    if not activation <= at <= now or (now-at).total_seconds()>90*86400:
        raise ValueError('Outcome outside approved window')
    consent=event.get('consent',{})
    if consent.get('ad_user_data')!='GRANTED' or not consent.get('evidence'):
        raise ValueError('Recorded advertising consent required')
    click=event.get('click',{});ck=next((k for k in ('gclid','wbraid','gbraid') if click.get(k)),None)
    if (not ck or click.get('provenance')!='GENUINE_PROVIDER_CLICK' or click.get('test_only') is not False
        or not click.get('immutable_source_sha256') or not re.fullmatch(r'[A-Za-z0-9_-]{12,512}',str(click[ck]))):
        raise ValueError('Genuine independently captured click identifier required')
    click_at=aware(click.get('captured_at'))
    if not click_at<=at or (now-click_at).total_seconds()>90*86400:raise ValueError('Click outside import window')
    dest=destination(control,kind,now)
    if dest.get('always_use_default_value') is not False:
        raise ValueError('Destination must respect the explicit business event value')
    if ck!='gclid' and dest.get('braid_supported') is not True:raise ValueError('BRAID destination prerequisites unproven')
    payload={'transactionId':key,'eventTimestamp':at.isoformat(),'eventSource':'WEB',
        'adIdentifiers':{ck:click[ck]},'consent':{'adUserData':'CONSENT_GRANTED',
            'adPersonalization':'CONSENT_GRANTED' if consent.get('ad_personalization')=='GRANTED' else 'CONSENT_DENIED'}}
    if kind=='qualified_lead':
        if row.get('Lead_Status')!='Pre-Qualified' and row.get('$converted') is not True:
            raise ValueError('Human qualification is not proven')
        if dest.get('value_basis')!='NO_VALUE':raise ValueError('Lead value must not be invented')
        if not re.fullmatch(r'[A-Z]{3}',str(dest.get('currency_code',''))):
            raise ValueError('Native destination currency required')
        # Omission would apply Ads' existing default (currently CAD1). Explicit
        # zero means no monetary value; it never represents observed revenue.
        payload.update(conversionValue=0,currency=dest['currency_code'])
    else:
        relation=resolve_finance(row,KINDS[kind],rows)
        if relation['conflict'] or not relation['deal_id']:raise ValueError('Deterministic Finance Deal lineage required')
        if kind=='estimate_accepted':
            if row.get('status') not in {'accepted','invoiced'} or dest.get('value_basis')!='ACCEPTED_ESTIMATE_GROSS':
                raise ValueError('Accepted commercial state and intentional value policy required')
        else:
            if (row.get('status')!='paid' or money(row.get('balance'))!=Decimal(0)
                or identity(row.get('recurring_invoice_id')) or dest.get('value_basis')!='FULLY_PAID_INVOICE_GROSS'
                or proof.get('credits_refunds_checked') is not True):
                raise ValueError('Fully paid non-recurring unadjusted Invoice required; not a cash-receipt metric')
        value=money(row.get('total'));currency=row.get('currency_code')
        if value is None or value<0 or not re.fullmatch(r'[A-Z]{3}',str(currency)):
            raise ValueError('Native amount and currency required')
        payload.update(conversionValue=float(value),currency=currency)
    native_dest={'operatingAccount':{'accountType':'GOOGLE_ADS','accountId':dest['account_id']},
        'loginAccount':{'accountType':'GOOGLE_ADS','accountId':dest.get('login_account_id',dest['account_id'])},
        'productDestinationId':dest['action_id']}
    if not re.fullmatch(r'[0-9]+',native_dest['loginAccount']['accountId']):raise ValueError('Native login account required')
    body={'destinations':[native_dest],'events':[payload],'validateOnly':True}
    return {'key':key,'kind':kind,'record_id':event['record_id'],'body':body,'payload_hash':digest(body),
        'policy_hash':digest(control),'proof_hash':digest(proof),'test_only':False}


def trusted_control():
    from .lifecycle_control import trusted_json
    if os.geteuid()!=0:raise PermissionError('Conversion authority is root-only')
    value=trusted_json(CONTROL,262144)
    if value.get('schema')!=1:raise ValueError('Invalid conversion policy')
    return value


def verify_plan(plan,control):
    """Transport reloads independent root receipts; a forged in-memory plan fails."""
    from .lifecycle_control import trusted_json
    now=datetime.now(timezone.utc)
    if not re.fullmatch(r'[0-9a-f]{64}',plan.get('key','')):raise ValueError('Invalid conversion identity')
    release=trusted_json(Path('/var/lib/optibrain/releases/current.json'),262144)
    if (release.get('sha')!=control.get('release_sha') or release.get('state')!='deployed'
        or sha256(Path(__file__).read_bytes()).hexdigest()!=control.get('source_sha256')):
        raise ValueError('Reviewed exact release pin required')
    event=trusted_json(ROOT/'events'/(plan['key']+'.json'),262144)
    proof=event.get('proof',{});source_key=proof.get('immutable_source_sha256','')
    if not re.fullmatch(r'[0-9a-f]{64}',source_key):raise ValueError('Immutable source receipt required')
    source=trusted_json(ROOT/'sources'/(source_key+'.json'),262144)
    if digest(source)!=source_key or any(source.get(k)!=event.get(k) for k in ('kind','record_id','occurred_at')):
        raise ValueError('Outcome identity/time disagrees with immutable source')
    if source.get('verified_by') not in {'INDEPENDENT_PROVIDER_RECONCILIATION','CRM_UI_TIMELINE_RECONCILIATION'}:
        raise ValueError('Independent outcome reconciliation required')
    cache=trusted_json(Path('/var/lib/optibrain/lifecycle/business-observation.json'),16777216)
    if not 0 <= (now-aware(cache['observed_at'])).total_seconds() <= 3600:
        raise ValueError('Native business observation is stale')
    actual=build_plan(event,cache['snapshot'],control,now=now)
    if actual!=plan:raise ValueError('Conversion plan differs from current native evidence')
    from .lifecycle_control import BASELINE,REAL_REGISTRY
    baseline=trusted_json(BASELINE)
    if any(plan['record_id'] in m.get('protected_versions',{}) for m in baseline['modules'].values()):
        raise ValueError('Protected historical business outcome denied')
    registry=trusted_json(REAL_REGISTRY,1048576).get('records',{})
    if plan['kind']=='qualified_lead':did=plan['record_id']
    else:
        rows,_=populations(cache['snapshot'])
        did=resolve_finance(rows[KINDS[plan['kind']]][plan['record_id']],KINDS[plan['kind']],rows)['deal_id']
    if registry.get(did,{}).get('ownership')!='REAL_NEW':raise ValueError('Only eligible owned new business outcomes may export')


class DataManager:
    """Fixed ingestion/status URLs, no redirects/retries, no caller headers/paths."""
    def __init__(self,oauth):
        from .action_evidence import ActionEvidence
        from .manager_runtime import DATABASE
        self.oauth=oauth;self.audit=ActionEvidence(DATABASE)
    def authorize(self,plan,*,live=False):
        control=trusted_control()
        verify_plan(plan,control)
        if plan['policy_hash']!=digest(control):raise ValueError('Conversion policy changed')
        destination(control,plan['kind'],datetime.now(timezone.utc))
        if digest(plan['body'])!=plan['payload_hash']:raise ValueError('Conversion payload changed')
        validation=control.get('validated_families',{}).get(plan['kind'],{})
        if live and (control.get('enabled') is not True or validation.get('passed') is not True
            or validation.get('destination_sha256')!=digest(control['destinations'][plan['kind']])):
            raise ValueError('Conversion uploads stopped or unvalidated')
        dest=control['destinations'][plan['kind']]
        if live and (dest.get('local_enabled') is not True or dest.get('allowed_event_keys')!=[plan['key']]):
            raise ValueError('One independently reviewed natural event must be authorized for this family')
        if live and not datetime.now(timezone.utc)<aware(control.get('expires_at')):raise ValueError('Conversion authorization expired')
        return control
    def ingest(self,plan,*,live=False):
        import httpx
        self.authorize(plan,live=live)
        saved=self.oauth.load_saved_credentials() or {}
        if SCOPE not in str(saved.get('scope','')).split():raise ValueError('Native Data Manager consent missing')
        body=json.loads(json.dumps(plan['body']));body['validateOnly']=not live
        if len(body['events'])!=1 or len(body['destinations'])!=1:raise ValueError('One-event verification bound required')
        from .mutation_control import require_business_transport
        require_business_transport(self,'google_datamanager','POST','/v1/events:ingest',body)
        token=self.oauth.access_token()
        require_business_transport(self,'google_datamanager','POST','/v1/events:ingest',body,recheck=True)
        from .provider_usage import record_call,record_response
        record_call('google_datamanager','POST','events:ingest')
        response=httpx.post(BASE+'events:ingest',json=body,headers={'Authorization':'Bearer '+token},
            timeout=httpx.Timeout(30,connect=10),follow_redirects=False)
        record_response('google_datamanager','POST','events:ingest',response.status_code)
        if response.status_code!=200:raise ValueError('Data Manager ingestion unavailable: HTTP '+str(response.status_code))
        value=response.json()
        if not live and value.get('fieldWarnings'):raise ValueError('Data Manager validation warnings require review')
        return value
    def status(self,request_id):
        import httpx
        if os.geteuid()!=0 or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',request_id):raise ValueError('Root-held request ID required')
        response=httpx.get(BASE+'requestStatus:retrieve',params={'requestId':request_id},
            headers={'Authorization':'Bearer '+self.oauth.access_token()},timeout=30,follow_redirects=False)
        if response.status_code!=200:raise ValueError('Conversion diagnostics unavailable')
        return response.json()


class ConversionClaims:
    """Independent, immutable R2 create-only effects survive local state rollback."""
    def __init__(self,client):self.client=client
    def key(self,plan,kind):return 'conversion-effects/v1/'+plan['key']+'/'+kind+'.json'
    def read(self,plan,kind):
        from .remote_effects import BUCKET
        try:value=self.client.get_object(Bucket=BUCKET,Key=self.key(plan,kind))['Body'].read(65537)
        except Exception as exc:
            if str(getattr(exc,'response',{}).get('Error',{}).get('Code','')) in {'404','NoSuchKey'}:return None
            raise ValueError('Conversion evidence unavailable') from exc
        if len(value)>65536:raise ValueError('Unbounded conversion evidence')
        value=json.loads(value)
        if value.get('key')!=plan['key'] or value.get('payload_hash')!=plan['payload_hash']:
            raise ValueError('Immutable conversion identity changed; HOLD')
        return value
    def put(self,plan,kind,extra=None):
        from .remote_effects import BUCKET
        value={'schema':1,'key':plan['key'],'payload_hash':plan['payload_hash'],
            'kind':plan['kind'],'proof_hash':plan['proof_hash'],'at':datetime.now(timezone.utc).isoformat(),**(extra or {})}
        self.client.put_object(Bucket=BUCKET,Key=self.key(plan,kind),Body=json.dumps(value).encode(),
            ContentType='application/json',IfNoneMatch='*')
        if self.read(plan,kind)!=value:raise ValueError('Conversion evidence readback differs')
        return value


def conversion_action_id(plan):
    return 'conversion:'+plan['key']


def prepare_conversion_audit(plan,client,audit,control,now):
    """Existing independently reviewed one-event authority, never an export grant."""
    from .action_evidence import envelope,approval_binding
    action_id=conversion_action_id(plan)
    record=envelope(action_id,'CONVERSION_OUTCOME_EXPORT',{'type':'CONVERSION_EVENT','identity':plan['key']},now,
        provider='GOOGLE_DATA_MANAGER',source_system='CRM',trigger='INDEPENDENTLY_VERIFIED_BUSINESS_OUTCOME',
        mutation=True,approval_required=True,authority_class='EXISTING_OWNER_APPROVED_SINGLE_EVENT',
        reason='Export the exact independently verified outcome under existing one-event authority.',
        before_supported=False,before_state={'local_offhost_claim':'ABSENT'},
        unknowns=['Provider has no event-presence lookup before upload; immutable off-host claim prevents replay.'],
        proposed_state={**plan['body'],'validateOnly':False},
        exact_versions={'payload_hash':plan['payload_hash'],'policy_hash':plan['policy_hash'],'proof_hash':plan['proof_hash']},
        related_entities=[{'kind':plan['kind'],'record_id':plan['record_id']}],
        evidence_refs=[plan['proof_hash'],plan['policy_hash']],rollback_capability='IRREVERSIBLE',irreversible=True,
        consequence='Advertising systems may consume the uploaded outcome; an upload cannot be unsent.',
        compensating_action='Hold further exports, reconcile diagnostics, and request owner review of supported provider adjustments.',
        provider_request={'method':'POST','path':'/v1/events:ingest','payload_hash':plan['payload_hash']})
    audit.plan(record,now)
    audit.approve(action_id,'EXISTING_INDEPENDENT_ROOT_SINGLE_EVENT_APPROVAL',now,
        binding=approval_binding(record),expires_at=control['expires_at'])
    audit.start(action_id,now,authority_check=lambda:client.authorize(plan,live=True))
    return action_id


def export_one(plan,client,claims,*,live=False):
    control=client.authorize(plan,live=live)
    if not live:
        with conversion_scope(client,plan,live=False):value=client.ingest(plan,live=False)
        return {'state':'VALIDATION_ONLY_PASS','key':plan['key'],'request_id':value.get('requestId'),'uploads':0}
    # Existing claims, even without a result, revoke authority. No automatic retry.
    if claims.read(plan,'claim') is not None:
        result=claims.read(plan,'result')
        return {'state':'RECONCILIATION_REQUIRED','key':plan['key'],'request_id':(result or {}).get('request_id'),'uploads':0}
    from .action_evidence import ActionEvidence
    audit=getattr(client,'audit',None)
    if not isinstance(audit,ActionEvidence):raise ValueError('Durable conversion journal required')
    now=datetime.now(timezone.utc)
    action_id=prepare_conversion_audit(plan,client,audit,control,now)
    try:claim=claims.put(plan,'claim')
    except Exception as exc:
        audit.finish(action_id,datetime.now(timezone.utc),provider_success=False,
            failure={'stage':'OFFHOST_CLAIM','error_class':type(exc).__name__,'provider_status':None,
                'safe_details':'Off-host claim unavailable; provider was not called.',
                'partial_effects':False,'recovery_action':'Inspect claim state before any owner-authorized retry.'})
        raise
    try:
        with conversion_scope(client,plan,live=True,claim=claim,audit=audit):response=client.ingest(plan,live=True)
        request_id=response.get('requestId')
        if not request_id:raise ValueError('Provider acknowledgement missing')
        claims.put(plan,'result',{'request_id':request_id,'state':'ACKNOWLEDGED_NOT_YET_RECONCILED',
            'warnings_present':bool(response.get('fieldWarnings'))})
        audit.event(action_id,'TECHNICAL_AUDIT','ACKNOWLEDGED_NOT_YET_RECONCILED',
            {'request_id':request_id,'warnings_present':bool(response.get('fieldWarnings'))},datetime.now(timezone.utc))
    except Exception as exc:
        audit.finish(action_id,datetime.now(timezone.utc),provider_success=False,
            failure={'stage':'CONVERSION_UPLOAD','error_class':type(exc).__name__,'provider_status':None,
                'safe_details':'Conversion outcome uncertain; immutable claim remains in place.',
                'partial_effects':'UNKNOWN','recovery_action':'Hold and reconcile; never automatically retry.'})
        raise ValueError('Conversion outcome uncertain; HOLD and reconcile, never retry') from exc
    return {'state':'ACKNOWLEDGED_NOT_YET_RECONCILED','key':plan['key'],'request_id':request_id,'uploads':1,'audit_action_id':action_id}


def reconcile(plan,client,request_id):
    value=client.status(request_id);rows=value.get('requestStatusPerDestination',[])
    expected=plan['body']['destinations'][0]
    if len(rows)!=1 or any(rows[0].get('destination',{}).get(k)!=v for k,v in expected.items()):
        raise ValueError('Wrong or missing conversion destination diagnostics')
    row=rows[0]
    if row.get('requestStatus')!='SUCCESS' or row.get('errorInfo') or row.get('warningInfo'):
        return {'state':'RECONCILIATION_REQUIRED','request_id':request_id,'provider_status':row.get('requestStatus')}
    count=row.get('eventsIngestionStatus',{}).get('recordCount')
    if str(count)!='1':raise ValueError('One provider conversion event not proven')
    from .action_evidence import ActionEvidence
    audit=getattr(client,'audit',None);action_id=conversion_action_id(plan)
    if isinstance(audit,ActionEvidence) and (audit.get(action_id) or {}).get('status')=='STARTED':
        audit.finish(action_id,datetime.now(timezone.utc),provider_success=True,actual_after=row,
            verified=True,response={'request_id':request_id,'events':1,'ads_attribution_proven':False})
    return {'state':'PROVIDER_PROCESSING_PASS','request_id':request_id,'events':1,'ads_attribution_proven':False}
