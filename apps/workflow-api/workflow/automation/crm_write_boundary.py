"""Non-serializable, single-call CRM authority for the reviewed Lead reconciler.

Workflow inputs, AI, confirm=True and provider failover never issue authority.
Legacy writers are unavailable. Only the journaled phase6 adapter enters this scope.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
import re

_AUTHORITY = ContextVar('phase6_crm_authority', default=None)
POLICY = 'phase6-sales-v1'
CANARY_POLICY = 'phase7-single-canary-v1'
LEGACY_ACTIONS = frozenset({'lifecycle.crm_upsert_lead', 'lifecycle.crm_create_followup_task',
    'lifecycle.crm_promote_lead', 'lifecycle.crm_create_meeting', 'lifecycle.crm_create_quote_review_task'})


def blocked_legacy():
    raise ValueError('Legacy CRM mutation is unavailable under Phase 6 write control')


def fingerprint(method, path, body, headers):
    return hashlib.sha256(json.dumps([method, path, body, headers or {}], sort_keys=True,
        separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def is_crm(service, path):
    return service == 'zohoapis' and (str(path).lower() == '/crm' or str(path).lower().startswith('/crm/'))


def validate_request(method, path, body, headers):
    if not isinstance(body, dict) or body.get('trigger') != [] or not isinstance(body.get('data'), list) or len(body['data']) != 1:
        raise ValueError('CRM grant requires one exact trigger-free record')
    row = body['data'][0]
    if not isinstance(row, dict): raise ValueError('Malformed CRM record')
    lead = re.fullmatch(r'/crm/v8/Leads/([0-9]{1,30})', path)
    if method == 'PUT' and lead:
        allowed = {'id','Normalized_Email','Normalized_Phone','Next_Followup_At','Service_Types'}
        if row.get('id') != lead[1] or not set(row) <= allowed or len(row) < 2 or set(body) != {'data','trigger','skip_feature_execution'} or body['skip_feature_execution'] != [{'name':'cadences'}]:
            raise ValueError('CRM Lead grant exceeds reviewed field boundary')
        if set(headers or {}) != {'If-Unmodified-Since'}: raise ValueError('Exact reviewed Lead version required')
        version = datetime.fromisoformat(headers['If-Unmodified-Since'].replace('Z','+00:00'))
        if version.tzinfo is None: raise ValueError('Reviewed version must be timezone aware')
    elif method == 'POST' and path == '/crm/v8/Tasks':
        if set(body) != {'data','trigger'} or set(row) != {'Subject','Who_Id','$se_module','Status','Due_Date'} or headers or row['$se_module'] != 'Leads' or row['Status'] != 'Not Started' or not re.fullmatch(r'[0-9]{1,30}', str(row['Who_Id'])) or not re.fullmatch(r'OptiBrain [a-z ]+ [0-9]{1,30} [a-f0-9]{16}', str(row['Subject'])):
            raise ValueError('CRM Task grant exceeds deterministic internal boundary')
        datetime.strptime(row['Due_Date'], '%Y-%m-%d')
    else:
        raise ValueError('CRM operation is outside the Phase 6 approved boundary')


@contextmanager
def reviewed_reconciler_call(client, method, path, body, headers, policy):
    if policy != POLICY or os.environ.get('OPTIBRAIN_CRM_LEAD_WRITES') != POLICY:
        raise ValueError('CRM write policy is disabled')
    validate_request(method, path, body, headers)
    if _AUTHORITY.get() is not None: raise ValueError('Nested CRM authority forbidden')
    value = {'client':client, 'hash':fingerprint(method,path,body,headers),
             'policy':POLICY, 'used':False}
    token = _AUTHORITY.set(value)
    try: yield
    finally: _AUTHORITY.reset(token)


@contextmanager
def reviewed_canary_call(client, method, path, body, headers, approval, ledger, *, now=None):
    """Scope one durably claimed Phase 7 Lead PUT to an exact provider call."""
    from .event_schema import digest
    if os.environ.get('OPTIBRAIN_CRM_CANARY') != CANARY_POLICY:
        raise ValueError('CRM canary policy is disabled')
    validate_request(method, path, body, headers)
    lead = re.fullmatch(r'/crm/v8/Leads/([0-9]{1,30})', path)
    if method != 'PUT' or lead is None or approval.policy != CANARY_POLICY or approval.lead_id != lead[1]:
        raise ValueError('CRM canary permits one approved Lead PUT only')
    reviewed = datetime.fromisoformat(headers['If-Unmodified-Since'].replace('Z', '+00:00'))
    if reviewed.astimezone(timezone.utc).isoformat() != approval.source_version:
        raise ValueError('CRM canary source version differs from approval')
    patch = {key:value for key,value in body['data'][0].items() if key != 'id'}
    if not patch or digest(patch) != approval.patch_hash:
        raise ValueError('CRM canary patch differs from approval')
    state = ledger.inspect(approval.approval_id)
    if state is None or state['state'] != 'consuming' or state['approval'] != approval:
        raise ValueError('CRM canary approval has not been durably claimed')
    if _AUTHORITY.get() is not None:
        raise ValueError('Nested CRM authority forbidden')
    value = {'client':client, 'hash':fingerprint(method,path,body,headers),
             'policy':CANARY_POLICY, 'used':False, 'expires_at':approval.expires_at,
             'ledger':ledger, 'approval':approval}
    ledger.mark_dispatch(approval, now=now)
    token = _AUTHORITY.set(value)
    try: yield
    finally: _AUTHORITY.reset(token)


def _enabled(value):
    policy = value.get('policy') if isinstance(value, dict) else None
    if policy == POLICY:
        return os.environ.get('OPTIBRAIN_CRM_LEAD_WRITES') == POLICY
    if policy == CANARY_POLICY:
        if os.environ.get('OPTIBRAIN_CRM_CANARY') != CANARY_POLICY:
            return False
        expiry = datetime.fromisoformat(value['expires_at'])
        if expiry.tzinfo is None or datetime.now(timezone.utc) >= expiry.astimezone(timezone.utc):
            return False
        state = value['ledger'].inspect(value['approval'].approval_id)
        return state is not None and state['state'] == 'dispatching' and state['approval'] == value['approval']
    return False


def require_authority(client, service, method, path, body, headers):
    if method == 'GET' or not is_crm(service,path): return
    value = _AUTHORITY.get()
    if not _enabled(value) or value.get('client') is not client or value.get('used') is not False or value.get('hash') != fingerprint(method,path,body,headers):
        raise ValueError('CRM mutation requires exact single-use reconciler authority')
    validate_request(method,path,body,headers)
    value['used'] = True  # Consumed before OAuth/provider calls; never blindly reused.


def verify_transport_authority(client, service, method, path, body, headers):
    """Recheck the consumed exact grant immediately before local/standby transport."""
    if method == 'GET' or not is_crm(service, path):
        return
    value = _AUTHORITY.get()
    if not _enabled(value) or value.get('client') is not client or value.get('used') is not True or value.get('hash') != fingerprint(method, path, body, headers):
        raise ValueError('CRM transport authority changed before the provider call')
    validate_request(method, path, body, headers)
