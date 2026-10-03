"""Independent root-only customer-send authority; no CRM or Finance write grant.

The runtime API, a service journal and an environment flag cannot grant a send.
Every single-use grant binds an immutable plan, a fresh remote effect claim and
a short-lived root authorization. The external kill never disables intake.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from .lifecycle_control import LifecycleEffect, trusted_json, digest, BASELINE
from .remote_effects import FreshClaim

ROOT = Path('/var/lib/optibrain/customer-communications')
CONTROL = Path('/etc/optibrain/customer-communication-control.json')
GRANT = ContextVar('optibrain_customer_send_grant', default=None)
SCOPES = frozenset({'customer.quote.reminder','customer.appointment.confirmation',
                   'customer.appointment.reminder','customer.completion.message'})
MAIL_ACCOUNT = '1083319000000008002'
SENDER = 'yboucher@opticable.ca'
SOURCES = {'automation/customer_send_control.py','automation/customer_delivery.py',
           'automation/customer_communications.py','automation/customer_runtime.py','automation/customer_finance_evidence.py','automation/mutation_control.py',
           'automation/lifecycle_control.py','automation/remote_effects.py','zoho_gateway.py'}

def policy():
    value = trusted_json(CONTROL,16384)
    if set(value) != {'schema','external_enabled','test_enabled','test_run','test_scopes',
            'real_scopes','activated_at','expires_at','source_hashes','phase18_checkpoint_sha256',
            'per_family_limit','per_cycle_limit'} or value['schema'] != 1:
        raise ValueError('Invalid customer communication policy')
    if (type(value['external_enabled']) is not bool or type(value['test_enabled']) is not bool
            or not isinstance(value['test_scopes'],list) or not set(value['test_scopes'])<=SCOPES
            or not isinstance(value['real_scopes'],list) or not set(value['real_scopes'])<=SCOPES
            or type(value['per_family_limit']) is not int or not 1<=value['per_family_limit']<=10
            or type(value['per_cycle_limit']) is not int or not 1<=value['per_cycle_limit']<=4):
        raise ValueError('Customer scopes or limits are invalid')
    expiry=datetime.fromisoformat(value['expires_at'])
    if expiry.tzinfo is None or datetime.now(timezone.utc)>=expiry:
        raise ValueError('Customer authority expired')
    if set(value['source_hashes']) != SOURCES: raise ValueError('Missing customer source pins')
    code=Path(__file__).resolve().parents[1]
    for name, expected in value['source_hashes'].items():
        if hashlib.sha256((code/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Customer source changed')
    if value['external_enabled']:
        checkpoint=ROOT/'phase18-checkpoint.json'
        if hashlib.sha256(trusted_json_bytes(checkpoint)).hexdigest()!=value['phase18_checkpoint_sha256']:
            raise ValueError('Customer checkpoint changed')
        proof=trusted_json(checkpoint)
        if proof.get('phase18')!='PASS' or proof.get('safety_critical_failures')!=0:
            raise ValueError('Customer TEST gates did not pass')
        if not set(value['real_scopes'])<=set(proof.get('passed_families',[])):
            raise ValueError('Unproven customer family')
    return value

def trusted_json_bytes(path):
    # Verify ownership/modes/parents before hashing the original durable bytes.
    trusted_json(path)
    return path.read_bytes()

def validate_envelope(envelope, plan, mode):
    if (set(envelope)!={'service','method','path','body','headers','query','content_type'}
            or envelope['service']!='mail' or envelope['method']!='POST'
            or envelope['path']!='/api/accounts/'+MAIL_ACCOUNT+'/messages'
            or envelope['headers'] or envelope['query']
            or envelope['content_type']!='application/json'):
        raise ValueError('Customer authority permits only one canonical Mail send')
    body=envelope['body']
    if (not isinstance(body,dict) or set(body)!={'fromAddress','toAddress','subject','content','mailFormat'}
            or body['fromAddress']!=SENDER or body['mailFormat']!='plaintext'
            or any(not isinstance(body[k],str) for k in body) or len(body['content'])>12000
            or any(x in body['subject'] for x in '\r\n') or len(body['subject'])>240):
        raise ValueError('Customer send body is outside the exact allowlist')
    if plan.get('state')!='READY' or plan.get('family') not in SCOPES:
        raise ValueError('Customer plan is not eligible')
    expected=plan.get('message',{})
    if body != expected: raise ValueError('Customer template/recipient differs from proven plan')
    recipient=body['toAddress']
    if not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',recipient):
        raise ValueError('Customer recipient is not one strict address')
    if mode=='TEST_ONLY':
        if recipient!=SENDER or not body['subject'].startswith('[OPTIBRAIN TEST]'):
            raise ValueError('TEST customer send must target the controlled owner')
    elif mode=='REAL_NEW':
        if recipient.casefold().endswith('@opticable.ca') or any(
                x in json.dumps(body).upper() for x in ['OPTIBRAIN TEST','TEST ONLY']):
            raise ValueError('Synthetic identity cannot acquire real customer send authority')
    else: raise ValueError('Unknown customer ownership mode')

def validate_source(source,mode,scope):
    """Re-render the pinned planner; a root READY label alone is insufficient."""
    from . import customer_communications as domain
    proof=source.get('proof',{});context=source.get('context',{})
    if proof.get('mode')!=mode or source.get('plan',{}).get('family')!=scope:
        raise ValueError('Customer source ownership/family mismatch')
    if mode=='REAL_NEW' and source.get('test_clock'):
        raise ValueError('A test clock cannot advance real customer eligibility')
    now=datetime.now(timezone.utc)
    if mode=='TEST_ONLY' and source.get('test_clock'):
        at=datetime.fromisoformat(source['native_observed_at'])
        if not 0<=(now-at).total_seconds()<=300:
            raise ValueError('TEST native evidence is stale')
        now=domain.aware(source['test_clock'])
    function={'customer.quote.reminder':domain.plan_quote_reminder,
        'customer.appointment.confirmation':domain.plan_appointment_confirmation,
        'customer.appointment.reminder':domain.plan_appointment_reminder,
        'customer.completion.message':domain.plan_completion_message}[scope]
    planned=function(context,proof,source.get('history',[]),now,communications_enabled=True)
    expected={'fromAddress':SENDER,'toAddress':planned.get('recipient'),
        'subject':planned.get('subject'),'content':planned.get('body'),'mailFormat':'plaintext'}
    if (planned.get('state')!='READY' or source['plan'].get('message')!=expected
            or planned.get('idempotency_key')!=source['plan'].get('idempotency_key')
            or planned.get('expected_native_bindings')!=source['plan'].get('expected_native_bindings')):
        raise ValueError('Customer plan conflicts with recipient, eligibility or template evidence')

@contextmanager
def exact_send(client,effect,claim,journal,*,mode,scope,authorization_path,refresh):
    if (os.geteuid()!=0 or GRANT.get() is not None or not isinstance(effect,LifecycleEffect)
            or not isinstance(claim,FreshClaim) or not claim.fresh
            or claim.action_id!=effect.action_id or claim.payload_hash!=effect.payload_hash
            or scope not in SCOPES or not callable(refresh)):
        raise ValueError('Fresh exact root customer claim required')
    token=GRANT.set(dict(client=client,effect=effect,claim=claim,journal=journal,
        mode=mode,scope=scope,authorization_path=authorization_path,refresh=refresh,used=False,transported=False))
    try: yield
    finally: GRANT.reset(token)

def check_transport(client,service,method,path,body,headers,*,recheck=False,
                    content_type='application/json',query=None):
    grant=GRANT.get()
    if not grant:return False
    current=policy()
    mode=grant['mode']; effect=grant['effect']
    if (os.geteuid()!=0 or grant['client'] is not client or grant['used'] is not recheck
            or recheck and grant['transported']
            or not grant['journal'].attempted(effect)
            or grant['scope'] not in current['test_scopes' if mode=='TEST_ONLY' else 'real_scopes']
            or not current['test_enabled' if mode=='TEST_ONLY' else 'external_enabled']):
        raise ValueError('Customer kill, scope or exact grant is unavailable')
    envelope=dict(service=service,method=method,path=path,body=body,headers=headers or {},
                  content_type=content_type,query=query or {})
    if envelope!=effect.payload:raise ValueError('Exact customer envelope changed')
    auth=trusted_json(grant['authorization_path'],262144)
    expected_path=ROOT/'authorizations'/(effect.action_id+'.json')
    if (grant['authorization_path']!=expected_path or auth.get('action_id')!=effect.action_id
            or auth.get('payload_hash')!=effect.payload_hash or auth.get('policy_hash')!=digest(current)
            or auth.get('mode')!=mode or auth.get('scope')!=grant['scope']
            or datetime.now(timezone.utc)>=datetime.fromisoformat(auth['expires_at'])):
        raise ValueError('Root customer authorization is stale or changed')
    source_key=auth.get('source_key','')
    if not re.fullmatch('[a-f0-9]{64}',source_key):raise ValueError('Invalid customer source key')
    source=trusted_json(ROOT/'sources'/(source_key+'.json'),262144)
    if digest(source)!=auth.get('source_hash'):raise ValueError('Customer source proof changed')
    if source.get('plan',{}).get('family')!=grant['scope'] or source.get('plan',{}).get('mode')!=mode:
        raise ValueError('Customer family or ownership changed')
    validate_source(source,mode,grant['scope'])
    proof=source.get('proof',{})
    protected={str(i) for m in trusted_json(BASELINE)['modules'].values() for i in m.get('protected_versions',{})}
    if any(str(proof.get(k,'')) in protected for k in ['contact_id','account_id','deal_id','site_id']):
        raise ValueError('Protected historical identity is outside customer scope')
    if mode=='REAL_NEW':
        if source.get('lineage_run')!='real-internal-20261002-v1' or not source.get('created_at'):
            raise ValueError('Customer source lacks new-record lineage')
        lineage=trusted_json(Path('/var/lib/optibrain/lifecycle/ownership.json'),1048576)
        item=lineage.get('records',{}).get(str(proof.get('deal_id')),{})
        if item.get('ownership')!='REAL_NEW' or item.get('run')!=source['lineage_run']:
            raise ValueError('Customer Deal lacks independent real lineage')
        activation=trusted_json(Path('/var/lib/optibrain/lifecycle/activation.json'))
        if datetime.fromisoformat(item['created_at'])<datetime.fromisoformat(activation['activated_at']):
            raise ValueError('Customer Deal predates approved intake')
    # The pinned caller refreshes native versions, associations and stop signals
    # immediately before the actual transport; a stale READY plan is insufficient.
    refreshed=grant['refresh']() if recheck else source['plan']
    validate_envelope(envelope,refreshed,mode)
    if refreshed.get('idempotency_key')!=source['plan'].get('idempotency_key'):
        raise ValueError('Customer schedule/Estimate version changed')
    if (refreshed.get('family')!=grant['scope'] or refreshed.get('mode')!=mode
            or refreshed.get('expected_native_bindings')!=source['plan'].get('expected_native_bindings')):
        raise ValueError('Customer native relationships changed before transport')
    if not recheck:
        grant['used']=True
        grant['journal'].append(effect,'transport_intent',{'scope':grant['scope'],
            'ownership':mode,'offhost_claim':grant['claim'].key})
    else:
        grant['transported']=True
    return True
