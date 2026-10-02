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
CREATE_POLICY = 'phase7-single-lead-create-v1'
PHASE8_TEST_TASK_POLICY = 'phase8-single-test-task-v1'
PHASE8_TEST_LEAD = '5062683000007880001'
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
        relation = row.get('What_Id')
        if set(body) != {'data','trigger'} or set(row) != {'Subject','What_Id','$se_module','Status','Due_Date'} or headers or row['$se_module'] != 'Leads' or row['Status'] != 'Not Started' or not isinstance(relation,dict) or set(relation) != {'id'} or not re.fullmatch(r'[0-9]{1,30}', str(relation['id'])) or not re.fullmatch(r'OptiBrain [a-z ]+ [0-9]{1,30} [a-f0-9]{16}', str(row['Subject'])):
            raise ValueError('CRM Task grant exceeds deterministic internal boundary')
        datetime.strptime(row['Due_Date'], '%Y-%m-%d')
    else:
        raise ValueError('CRM operation is outside the Phase 6 approved boundary')


def validate_create_request(method, path, body, headers):
    """Separate fixed-module create boundary; never broadens the Phase 6 writer."""
    from .phase7_lead_create import canonical_payload
    if method != 'POST' or path != '/crm/v8/Leads' or headers:
        raise ValueError('Lead create grant permits only exact CRM v8 Leads POST')
    if (not isinstance(body, dict) or set(body) != {'data', 'trigger', 'skip_feature_execution'}
            or body.get('trigger') != []
            or body.get('skip_feature_execution') != [{'name':'cadences'}]):
        raise ValueError('Lead create request envelope is invalid')
    rows = body.get('data')
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError('Lead create requires one exact record')
    if body != canonical_payload(rows[0]):
        raise ValueError('Lead create body is not canonical')


def validate_phase8_test_task(method, path, body, headers):
    """Separate exact controlled-Lead Task boundary; date only is Zoho's Task due field."""
    if method != 'POST' or path != '/crm/v8/Tasks' or headers:
        raise ValueError('Phase 8 task permits only CRM Tasks POST')
    if not isinstance(body, dict) or set(body) != {'data', 'trigger'} or body['trigger'] != []:
        raise ValueError('Phase 8 task requires a trigger-free envelope')
    rows = body['data']
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError('Phase 8 task requires exactly one record')
    row = rows[0]
    if (set(row) != {'Subject', 'What_Id', '$se_module', 'Status', 'Due_Date'}
            or row['What_Id'] != {'id': PHASE8_TEST_LEAD} or row['$se_module'] != 'Leads'
            or row['Status'] != 'Not Started'
            or not re.fullmatch(r'TEST ONLY — OPTIBRAIN PHASE 8 — '
                                + PHASE8_TEST_LEAD + r' — [0-9a-f]{16}', str(row['Subject']))):
        raise ValueError('Phase 8 task escaped controlled identity')
    datetime.strptime(row['Due_Date'], '%Y-%m-%d')


@contextmanager
def reviewed_phase8_test_task_call(client, body, *, payload_hash):
    """One process-local, single-use grant pinned to an exact reviewed payload hash."""
    if os.geteuid() != 0 or os.environ.get('OPTIBRAIN_PHASE8_TEST_TASK') != PHASE8_TEST_TASK_POLICY:
        raise ValueError('Phase 8 test task policy is disabled')
    if not re.fullmatch(r'[0-9a-f]{64}', str(payload_hash)) or fingerprint(
            'POST', '/crm/v8/Tasks', body, None) != payload_hash:
        raise ValueError('Phase 8 test task payload changed')
    validate_phase8_test_task('POST', '/crm/v8/Tasks', body, None)
    if _AUTHORITY.get() is not None:
        raise ValueError('Nested CRM authority forbidden')
    value = {'client': client, 'hash': payload_hash, 'policy': PHASE8_TEST_TASK_POLICY,
             'used': False}
    token = _AUTHORITY.set(value)
    try: yield
    finally: _AUTHORITY.reset(token)


@contextmanager
def reviewed_create_call(client, body, approval, ledger, *, now=None):
    """One durable transport grant after human approval and exact preflight."""
    from .phase7_lead_create import request_hash
    from .outbound_approval import _clock, _aware
    policy = os.environ.get('OPTIBRAIN_LEAD_CREATE_CANARY')
    pinned = os.environ.get('OPTIBRAIN_LEAD_CREATE_APPROVAL_ID')
    if policy != CREATE_POLICY or pinned != approval.approval_id or approval.policy != CREATE_POLICY:
        raise ValueError('Lead create canary policy or pin is disabled')
    validate_create_request('POST', '/crm/v8/Leads', body, None)
    if request_hash(body['data'][0]) != approval.payload_hash:
        raise ValueError('Lead create payload differs from approval')
    state = ledger.inspect(approval.approval_id)
    if state is None or state['state'] != 'consuming' or state['approval'] != approval:
        raise ValueError('Lead create approval has not been claimed')
    current = _clock(now)
    if not _aware(approval.approved_at, field='approved_at') <= current < _aware(approval.expires_at, field='expires_at'):
        raise ValueError('Lead create approval expired before dispatch')
    if _AUTHORITY.get() is not None:
        raise ValueError('Nested CRM authority forbidden')
    ledger.dispatch(approval)
    value = {'client':client, 'hash':fingerprint('POST','/crm/v8/Leads',body,None),
             'policy':CREATE_POLICY, 'used':False, 'expires_at':approval.expires_at,
             'ledger':ledger, 'approval':approval}
    token = _AUTHORITY.set(value)
    try: yield
    finally: _AUTHORITY.reset(token)


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
    from .phase9_form_enrichment import POLICY as FORM_POLICY
    if policy == FORM_POLICY:
        return os.environ.get('OPTIBRAIN_PHASE9_FORM_ENRICHMENT') == FORM_POLICY
    from .test_lab_boundary import POLICY as LAB_POLICY
    if policy == LAB_POLICY:
        return os.geteuid() == 0 and os.environ.get('OPTIBRAIN_PHASE8_TEST_LAB') == LAB_POLICY
    if policy == POLICY:
        return os.environ.get('OPTIBRAIN_CRM_LEAD_WRITES') == POLICY
    if policy == PHASE8_TEST_TASK_POLICY:
        return os.geteuid() == 0 and os.environ.get('OPTIBRAIN_PHASE8_TEST_TASK') == PHASE8_TEST_TASK_POLICY
    if policy == CANARY_POLICY:
        if (os.environ.get('OPTIBRAIN_CRM_CANARY') != CANARY_POLICY
                or os.environ.get('OPTIBRAIN_CRM_CANARY_APPROVAL_ID') != value['approval'].approval_id):
            return False
        expiry = datetime.fromisoformat(value['expires_at'])
        if expiry.tzinfo is None or datetime.now(timezone.utc) >= expiry.astimezone(timezone.utc):
            return False
        state = value['ledger'].inspect(value['approval'].approval_id)
        return state is not None and state['state'] == 'dispatching' and state['approval'] == value['approval']
    if policy == CREATE_POLICY:
        if (os.environ.get('OPTIBRAIN_LEAD_CREATE_CANARY') != CREATE_POLICY
                or os.environ.get('OPTIBRAIN_LEAD_CREATE_APPROVAL_ID') != value['approval'].approval_id):
            return False
        expiry = datetime.fromisoformat(value['expires_at'])
        if expiry.tzinfo is None or datetime.now(timezone.utc) >= expiry.astimezone(timezone.utc):
            return False
        state = value['ledger'].inspect(value['approval'].approval_id)
        return state is not None and state['state'] == 'dispatching' and state['approval'] == value['approval']
    return False


def require_authority(client, service, method, path, body, headers):
    if method == 'GET' or not is_crm(service,path): return
    from .lifecycle_control import check_crm_authority
    if check_crm_authority(client,method,path,body,headers): return
    value = _AUTHORITY.get()
    if not _enabled(value) or value.get('client') is not client or value.get('used') is not False or value.get('hash') != fingerprint(method,path,body,headers):
        raise ValueError('CRM mutation requires exact single-use reconciler authority')
    from .test_lab_boundary import POLICY as LAB_POLICY, validate_lab_request
    from .phase9_form_enrichment import POLICY as FORM_POLICY, validate_form_request
    if value['policy'] == LAB_POLICY:
        validate_lab_request(method,path,body,headers)
    elif value['policy'] == FORM_POLICY:
        validate_form_request(method,path,body,headers,value)
    elif value['policy'] == PHASE8_TEST_TASK_POLICY:
        validate_phase8_test_task(method,path,body,headers)
    elif value['policy'] == CREATE_POLICY:
        validate_create_request(method,path,body,headers)
    else:
        validate_request(method,path,body,headers)
    value['used'] = True  # Consumed before OAuth/provider calls; never blindly reused.


def verify_transport_authority(client, service, method, path, body, headers):
    """Recheck the consumed exact grant immediately before local/standby transport."""
    if method == 'GET' or not is_crm(service, path):
        return
    from .lifecycle_control import check_crm_authority
    if check_crm_authority(client,method,path,body,headers,recheck=True): return
    value = _AUTHORITY.get()
    if not _enabled(value) or value.get('client') is not client or value.get('used') is not True or value.get('hash') != fingerprint(method, path, body, headers):
        raise ValueError('CRM transport authority changed before the provider call')
    from .test_lab_boundary import POLICY as LAB_POLICY, validate_lab_request
    from .phase9_form_enrichment import POLICY as FORM_POLICY, validate_form_request
    if value['policy'] == LAB_POLICY:
        validate_lab_request(method,path,body,headers)
    elif value['policy'] == FORM_POLICY:
        validate_form_request(method,path,body,headers,value)
    elif value['policy'] == PHASE8_TEST_TASK_POLICY:
        validate_phase8_test_task(method,path,body,headers)
    elif value['policy'] == CREATE_POLICY:
        validate_create_request(method, path, body, headers)
    else:
        validate_request(method, path, body, headers)
