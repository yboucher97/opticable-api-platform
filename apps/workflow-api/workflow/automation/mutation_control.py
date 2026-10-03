"""Fail-closed transport authority, independent of workflow flags and approvals.

Only an exact central TEST_ONLY Task action may reach business write transport.
Root administrative calls are separate, explicit, one-use technical authority.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from time import monotonic

CONTROL = Path('/etc/optibrain/mutation-control.json')
_ACTION = ContextVar('optibrain_central_action', default=None)
_ADMIN = ContextVar('optibrain_technical_admin', default=None)
_EXECUTABLE = re.compile(r'/(functions|custom_functions|customfunctions|customapi|custom|execute|invoke)(/|$)', re.I)


def fingerprint(provider, method, path, body, headers=None):
    return hashlib.sha256(json.dumps([provider, method, path, body, headers or {}],
        sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def read_control():
    for parent in list(CONTROL.parents)[:-1]:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Untrusted mutation-control parent')
    fd = os.open(CONTROL, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise ValueError('Untrusted mutation-control file')
        if info.st_size > 4096:
            raise ValueError('Mutation-control file is unbounded')
        with os.fdopen(fd) as handle:
            fd = -1
            value = json.load(handle)
    finally:
        if fd >= 0: os.close(fd)
    if (set(value) != {'schema', 'test_writes_enabled', 'allowed_actions', 'real_canary_allowed'}
            or value['schema'] != 1 or type(value['test_writes_enabled']) is not bool
            or value['allowed_actions'] != ['crm.task.create']
            or value['real_canary_allowed'] is not False):
        raise ValueError('Invalid mutation-control policy; real authority is forbidden')
    return value


def safe_read(service, path, headers=None):
    if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
            or any(c in path for c in ('%', '?', '#', '\\', '\r', '\n'))
            or any(p in {'.', '..'} for p in path.split('/'))
            or _EXECUTABLE.search(path)
            or any(str(k).casefold().strip() in {'x-http-method-override', 'x-method-override'} for k in (headers or {}))):
        raise ValueError('Executable or noncanonical provider read path is forbidden')
    if service == 'creator':
        raise ValueError('Unaudited Creator execution surface is unavailable')


@contextmanager
def action_scope(action, journal, ownership):
    if _ACTION.get() is not None:
        raise ValueError('Nested business-action authority forbidden')
    value = {'action': action, 'journal': journal, 'ownership': ownership,
             'client': None, 'claim': None, 'hash': None, 'used': False}
    token = _ACTION.set(value)
    try: yield
    finally: _ACTION.reset(token)


def bind_task_claim(action, client, body, claim):
    from .remote_effects import FreshClaim
    value = _ACTION.get()
    if (not value or value['action'] != action or value['ownership'] != 'TEST_ONLY'
            or not isinstance(claim, FreshClaim) or claim.action_id != action.action_id
            or claim.payload_hash != action.payload_hash or not claim.fresh):
        raise ValueError('Exact fresh off-host Task claim required')
    value.update(client=client, claim=claim,
                 hash=fingerprint('zohoapis', 'POST', '/crm/v8/Tasks', body))


def require_business_transport(client, service, method, path, body, headers=None, *, recheck=False,
                               content_type='application/json', query=None):
    if method == 'GET':
        safe_read(service, path, headers)
        return
    from .lifecycle_control import check_transport
    if check_transport(client,service,method,path,body,headers,recheck=recheck,
                       content_type=content_type,query=query):
        return
    from .customer_send_control import check_transport as check_customer_transport
    if check_customer_transport(client,service,method,path,body,headers,recheck=recheck,
                               content_type=content_type,query=query):
        return
    from .conversion_export import check_transport as check_conversion_transport
    if check_conversion_transport(client,service,method,path,body,headers,recheck=recheck,
                                  content_type=content_type,query=query):
        return
    try:
        control = read_control()  # Missing/corrupt/untrusted policy is a denial.
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('Universal mutation authority is unavailable') from exc
    if not control['test_writes_enabled']:
        raise ValueError('Universal business-write kill switch is OFF')
    value = _ACTION.get()
    if (os.geteuid() != 0 or not value or value['ownership'] != 'TEST_ONLY'
            or value['client'] is not client or value['used'] is not recheck
            or value['hash'] != fingerprint(service, method, path, body, headers)):
        raise ValueError('Provider mutation requires exact central TEST_ONLY authority')
    action = value['action']
    entry = value['journal'].get(action.action_id)
    if (action.action_type not in control['allowed_actions'] or action.target_module != 'Leads'
            or action.provider != 'zoho_crm' or service != 'zohoapis' or method != 'POST'
            or path != '/crm/v8/Tasks' or headers or not entry
            or entry['state'] != 'attempted' or entry['payload_hash'] != action.payload_hash
            or not value['claim'] or not value['claim'].fresh):
        raise ValueError('Central action changed or executor is forbidden')
    if not recheck:
        value['used'] = True
        value['journal'].record_evidence(action.action_id, 'transport_intent',
            {'service': service, 'method': method, 'path': path, 'body': body,
             'offhost_claim': value['claim'].key})


def record_business_response(response):
    from .customer_send_control import GRANT as CUSTOMER_GRANT
    customer=CUSTOMER_GRANT.get()
    if customer and customer['used']:
        customer['journal'].append(customer['effect'],'provider_response',response)
        return
    from .lifecycle_control import GRANT
    grant=GRANT.get()
    if grant and grant['used']:
        grant['journal'].append(grant['effect'],'provider_response',response)
        return
    value = _ACTION.get()
    if value and value['used']:
        value['journal'].record_evidence(value['action'].action_id, 'provider_response', response)


@contextmanager
def technical_admin_call(client, provider, method, path, body=None):
    """Root CLI only; never issuable by runtime API/workflow inputs."""
    if os.geteuid() != 0 or provider not in {'cloudflare', 'github'} or method == 'GET' or _ADMIN.get():
        raise ValueError('Explicit root technical administration required')
    value = {'client': client, 'hash': fingerprint(provider, method, path, body),
             'deadline': monotonic() + 120, 'used': False}
    token = _ADMIN.set(value)
    try: yield
    finally: _ADMIN.reset(token)


def require_technical_admin(client, provider, method, path, body=None):
    if method == 'GET': return
    value = _ADMIN.get()
    if (os.geteuid() != 0 or not value or value['client'] is not client or value['used']
            or monotonic() >= value['deadline']
            or value['hash'] != fingerprint(provider, method, path, body)):
        raise ValueError('Runtime provider administration is forbidden')
    value['used'] = True
