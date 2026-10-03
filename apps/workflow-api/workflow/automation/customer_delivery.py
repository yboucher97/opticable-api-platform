"""Root-owned, bounded Mail delivery with immutable intent and no send retries.

The provider has no documented idempotency key. A conditional off-host claim
therefore permits one POST only; every existing or uncertain claim permits GET
reconciliation only. Losing local state cannot reset counters or permit sends.
"""
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape
import json
import os
from pathlib import Path
import re
import stat

from . import customer_send_control as control
from .lifecycle_control import LifecycleEffect, LifecycleJournal, digest, trusted_json
from .remote_effects import RemoteEffects

SENT_FOLDER = '1083319000000008022'
_ID = re.compile(r'[0-9]{1,30}')
_INTERNET_ID = re.compile(r'<[^<>\s]{1,250}@[^<>\s]{1,250}>')


def aware(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Customer delivery timestamp requires an offset')
    return result


def atomic(path, value):
    temporary = path.with_name('.' + path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True, ensure_ascii=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def immutable(path, value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    if len(raw) > 262144: raise ValueError('Customer proof exceeds its bounded size')
    try: fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if digest(trusted_json(path, 262144)) != digest(value):
            raise ValueError('Immutable customer proof conflicts with original')
        return
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)


def initialize_state(*, root=None):
    """Explicit manual preparation, before activation; never called by the timer.

    A lost previously initialized store must be restored and reconciled. This
    helper refuses extant effect authority instead of silently starting again.
    """
    if os.geteuid() != 0: raise ValueError('Root customer preparation required')
    root = Path(root) if root is not None else control.ROOT
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('Private root-owned customer state required')
    path = root / 'state.json'
    if path.exists(): raise ValueError('Customer state already exists; preserve it')
    for name in ('authorizations', 'sources'):
        directory = root / name
        if directory.exists() and any(directory.iterdir()):
            raise ValueError('Prior customer evidence exists; restore, never reset')
        directory.mkdir(mode=0o700, exist_ok=True)
    immutable(path, {'schema': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                     'effects': {}, 'holds': {}})


def decorate(plan):
    if plan.get('state') != 'READY': return plan
    message = {'fromAddress': control.SENDER, 'toAddress': plan['recipient'],
        'subject': plan['subject'], 'content': plan['body'], 'mailFormat': 'plaintext'}
    if 'message' in plan and plan['message'] != message:
        raise ValueError('Communication message conflicts with its pure plan')
    return {**plan, 'message': message}


def envelope(plan):
    return {'service': 'mail', 'method': 'POST',
        'path': '/api/accounts/' + control.MAIL_ACCOUNT + '/messages',
        'body': plan['message'], 'headers': {}, 'query': {}, 'content_type': 'application/json'}


def addresses(value):
    if value in (None, '', 'Not Provided'): return []
    return [address.casefold() for _, address in getaddresses([unescape(str(value))]) if address]


def plain(value):
    """Normalize Zoho's HTML representation of our strictly plaintext templates."""
    if not isinstance(value, str): raise ValueError('Full provider Mail content unavailable')
    if re.search(r'<\s*(script|style)\b', value, re.I):
        raise ValueError('Unexpected active markup in Sent content')
    value = re.sub(r'(?i)<br\s*/?>|</(?:p|div)>', '\n', value)
    value = unescape(re.sub(r'<[^>]*>', '', value)).replace('\r\n', '\n').replace('\r', '\n')
    value = '\n'.join(line.strip() for line in value.splitlines()).strip()
    return re.sub(r'\n{3,}', '\n\n', value)


def provider_data(response, expected):
    if (not isinstance(response, dict) or response.get('ok') is not True
            or response.get('status') != 200):
        raise ValueError('Authoritative Mail read failed')
    outer = response.get('data')
    if (not isinstance(outer, dict) or outer.get('status', {}).get('code') != 200
            or not isinstance(outer.get('data'), expected)):
        raise ValueError('Mail response has ambiguous shape')
    return outer['data']


def acknowledged_id(response):
    if not isinstance(response, dict) or response.get('ok') is not True or response.get('status') not in (200, 201):
        return None
    outer = response.get('data') or {}
    if not isinstance(outer, dict) or outer.get('status', {}).get('code') not in (200, 201): return None
    data = outer.get('data') or {}
    identity = str(data.get('messageId') or '') if isinstance(data, dict) else ''
    return identity if _ID.fullmatch(identity) else None


class RootSender:
    """One runner cycle; its caller holds the root customer runtime FLOCK."""
    def __init__(self, client, refresh, *, root=None, journal=None, remote=None):
        if os.geteuid() != 0: raise ValueError('Root customer sender required')
        if not callable(refresh): raise ValueError('Native eligibility refresh is required')
        self.root = Path(root) if root is not None else control.ROOT
        self.client = client; self.refresh = refresh
        self.state = trusted_json(self.root / 'state.json', 4194304)
        if (set(self.state) != {'schema', 'created_at', 'effects', 'holds'} or self.state['schema'] != 1
                or not isinstance(self.state['effects'], dict) or not isinstance(self.state['holds'], dict)):
            raise ValueError('Customer state is invalid; restore, never reset')
        self.journal = journal or LifecycleJournal('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
        self.remote = remote or RemoteEffects.root_store()
        self.effects_this_cycle = 0; self.inflight = None

    initialize = staticmethod(initialize_state)

    def save(self): atomic(self.root / 'state.json', self.state)

    def history(self):
        rows = []
        for action_id, item in self.state['effects'].items():
            if action_id == self.inflight: continue
            rows.append({'family': item['family'], 'object_id': item['object_id'],
                'effect_key': item['effect_key'], 'status': item['state'],
                'sent_at': item.get('sent_at'), 'provider_message_id': item.get('provider_id'),
                'sequence': item.get('sequence'), 'schedule_version': item.get('schedule_version'),
                'mode': item['mode']})
        return rows

    def hold(self, family, action_id, reason):
        self.state['holds'].setdefault(family, {})[action_id] = {
            'at': datetime.now(timezone.utc).isoformat(), 'reason': reason}
        self.save()

    def _fresh_plan(self, original):
        refreshed = decorate(self.refresh())
        if (refreshed.get('state') != 'READY' or refreshed.get('family') != original['family']
                or refreshed.get('idempotency_key') != original['idempotency_key']
                or refreshed.get('message') != original['message']
                or refreshed.get('mode') != original['mode']
                or refreshed.get('expected_native_bindings') != original.get('expected_native_bindings')
                or refreshed.get('object_id') != original.get('object_id')):
            return None
        return refreshed

    def send(self, plan, source, *, now=None, lost_ack=False):
        now = aware(now or datetime.now(timezone.utc)); plan = decorate(plan)
        if plan.get('state') != 'READY': return {'state': plan.get('state', 'HUMAN'), 'sent': False}
        policy = control.policy(); mode = plan.get('mode'); family = plan.get('family')
        if mode not in ('TEST_ONLY', 'REAL_NEW') or family not in control.SCOPES:
            raise ValueError('Unknown customer ownership or family')
        permitted = policy['test_scopes' if mode == 'TEST_ONLY' else 'real_scopes']
        if family not in permitted or policy['test_enabled' if mode == 'TEST_ONLY' else 'external_enabled'] is not True:
            return {'state': 'SUPPRESSED', 'sent': False, 'reason': 'Customer family is OFF'}
        if lost_ack and mode != 'TEST_ONLY': raise ValueError('Failure injection is TEST_ONLY')
        operation = envelope(plan); control.validate_envelope(operation, plan, mode)
        key = str(plan.get('idempotency_key') or '')
        if not key or len(key) > 512: raise ValueError('Stable business-version effect key required')
        effect = LifecycleEffect('customer-v1:' + mode + ':' + key, operation,
                                 target_module='CustomerCommunication', target_id=str(plan['object_id']))
        prior = self.state['effects'].get(effect.action_id)
        if prior:
            if prior['payload_hash'] != effect.payload_hash:
                self.hold(family, effect.action_id, 'Stable customer key changed payload; reconcile')
                raise ValueError('Customer effect payload changed; no send retry')
            if prior['state'] == 'verified':
                return {'state': 'VERIFIED_REPLAY', 'sent': False, 'provider_message_id': prior['provider_id'], 'action_id': effect.action_id}
            return self.reconcile(effect.action_id, now=now)
        if self.state['holds'].get(family): return {'state': 'HOLD', 'sent': False, 'reason': 'This customer family requires reconciliation'}
        attempted = sum(item['family'] == family and item['mode'] == mode for item in self.state['effects'].values())
        if attempted >= policy['per_family_limit'] or self.effects_this_cycle >= policy['per_cycle_limit']:
            return {'state': 'BOUNDED', 'sent': False, 'reason': 'Customer verification limit reached'}
        fresh = self._fresh_plan(plan)
        if fresh is None: return {'state': 'SUPPRESSED', 'sent': False, 'reason': 'Native eligibility changed before claim'}
        frozen = {**source, 'plan': plan}
        if frozen.get('proof', {}).get('mode') != mode:
            raise ValueError('Customer source ownership differs from plan')
        control.validate_source(frozen, mode, family)
        source_key = digest(frozen)
        source_path = self.root / 'sources' / (source_key + '.json')
        immutable(source_path, frozen)
        auth_path = self.root / 'authorizations' / (effect.action_id + '.json')
        immutable(auth_path, {'schema': 1, 'action_id': effect.action_id,
            'payload_hash': effect.payload_hash, 'policy_hash': digest(policy), 'scope': family,
            'mode': mode, 'source_key': source_key, 'source_hash': digest(frozen),
            'expires_at': min(now + timedelta(minutes=2), aware(policy['expires_at'])).isoformat()})
        self.journal.intent(effect)
        self.state['effects'][effect.action_id] = {'family': family, 'mode': mode,
            'effect_key': key, 'object_id': str(plan['object_id']), 'payload_hash': effect.payload_hash,
            'source_key': source_key, 'envelope': operation, 'state': 'attempted',
            'attempted_at': now.isoformat(), 'sequence': plan.get('sequence'),
            'schedule_version': plan.get('schedule_version')}
        self.save(); self.effects_this_cycle += 1; self.inflight = effect.action_id
        revoked = [False]
        def refresh():
            current = self._fresh_plan(plan)
            if current is None:
                revoked[0] = True
                return {'state': 'SUPPRESSED', 'family': family}
            return current
        try:
            claim = self.remote.claim(effect)
            self.journal.append(effect, 'attempted', {'scope': family, 'mode': mode, 'source_key': source_key,
                'offhost_claim': claim.key, 'fresh': claim.fresh})
            if not claim.fresh: return self.reconcile(effect.action_id, now=now)
            with control.exact_send(self.client, effect, claim, self.journal, mode=mode,
                    scope=family, authorization_path=auth_path, refresh=refresh):
                response = self.client.request('mail', 'POST', operation['path'], body=operation['body'],
                    reason='Scoped operational customer communication', confirm=True)
            provider_id = acknowledged_id(response)
            self.journal.append(effect, 'customer_ack', {'provider_message_id': provider_id})
            if lost_ack:
                self.journal.append(effect, 'test_lost_ack', {'provider_success': bool(provider_id)})
                provider_id = None
            if provider_id:
                self.state['effects'][effect.action_id]['acknowledged_id'] = provider_id
                self.save()
            return self.reconcile(effect.action_id, now=datetime.now(timezone.utc))
        except Exception as exc:
            if revoked[0]:
                self.state['effects'][effect.action_id]['state'] = 'suppressed'; self.save()
                self.journal.append(effect, 'not_attempted', {'reason': 'Native eligibility revoked before HTTP transport'})
                return {'state': 'SUPPRESSED', 'sent': False, 'action_id': effect.action_id}
            self.journal.append(effect, 'customer_outcome_uncertain', {'error_type': type(exc).__name__, 'resend_allowed': False})
            return self.reconcile(effect.action_id, now=datetime.now(timezone.utc))
        finally: self.inflight = None

    def _get(self, path, query=None, expected=dict):
        return provider_data(self.client.request('mail', 'GET', path, query=query or {}), expected)

    def _sent_match(self, identity, item, now):
        if not _ID.fullmatch(str(identity)): raise ValueError('Exact Sent identity required')
        base = '/api/accounts/' + control.MAIL_ACCOUNT + '/folders/' + SENT_FOLDER + '/messages/' + str(identity)
        details = self._get(base + '/details')
        desired = item['envelope']['body']
        if (str(details.get('messageId')) != str(identity) or str(details.get('folderId')) != SENT_FOLDER
                or addresses(details.get('fromAddress')) != [control.SENDER]
                or addresses(details.get('toAddress')) != [desired['toAddress'].casefold()]
                or addresses(details.get('ccAddress')) or addresses(details.get('bccAddress'))
                or details.get('subject') != desired['subject']):
            return None
        stamp = datetime.fromtimestamp(int(details.get('receivedTime') or details.get('receivedtime')) / 1000, timezone.utc)
        attempted = aware(item['attempted_at'])
        if not attempted - timedelta(seconds=5) <= stamp <= min(attempted + timedelta(minutes=5), now + timedelta(minutes=2)):
            return None
        content = self._get(base + '/content').get('content')
        if isinstance(content, dict): content = content.get('content')
        if plain(content) != plain(desired['content']): return None
        raw = self._get(base + '/header', {'raw': 'false'}).get('headerContent')
        if not isinstance(raw, dict): raise ValueError('Sent headers unavailable')
        headers = {k.casefold(): values[0] for k, values in raw.items()
                   if isinstance(values, list) and len(values) == 1 and isinstance(values[0], str)}
        if (addresses(headers.get('from')) != [control.SENDER]
                or addresses(headers.get('to')) != [desired['toAddress'].casefold()]
                or addresses(headers.get('cc')) or addresses(headers.get('bcc'))): return None
        internet_id = headers.get('message-id', '')
        if not _INTERNET_ID.fullmatch(internet_id): raise ValueError('Sent Internet Message-ID unavailable')
        date = parsedate_to_datetime(headers.get('date', ''))
        if not date or date.tzinfo is None or abs((date - stamp).total_seconds()) > 120:
            raise ValueError('Sent timestamp evidence disagrees')
        return {'provider_message_id': str(identity), 'internet_message_id': internet_id,
                'sent_at': stamp.isoformat(), 'recipient': desired['toAddress'],
                'content_hash': digest(desired), 'delivery_status': details.get('mailDeliveryStatus')}

    def reconcile(self, action_id, *, now=None):
        """Read-only even when the scope is OFF/expired or a family is held."""
        now = aware(now or datetime.now(timezone.utc))
        item = self.state['effects'][action_id]
        effect = LifecycleEffect('customer-v1:' + item['mode'] + ':' + item['effect_key'],
            item['envelope'], target_module='CustomerCommunication', target_id=item['object_id'])
        if effect.action_id != action_id or effect.payload_hash != item['payload_hash']:
            raise ValueError('Frozen customer intent changed; no reconciliation guess')
        self.journal.intent(effect)
        try:
            original = self.remote.get(effect, 'claim')
            if not original: raise ValueError('Independent off-host claim is unavailable')
            attempted = aware(item['attempted_at'])
            # Date filters use mailbox-local days; UTC midnight can otherwise
            # exclude a just-sent Canadian evening message after a lost ACK.
            # Widen only the search window; exact aware attempt timestamps,
            # metadata, full content and headers still determine the effect.
            start = (attempted - timedelta(days=1)).strftime('%d-%b-%Y')
            end = (attempted + timedelta(days=2)).strftime('%d-%b-%Y')
            recipient = item['envelope']['body']['toAddress']
            subject = item['envelope']['body']['subject']
            query = 'sender:' + control.SENDER + '::to:' + recipient + '::fromDate:' + start + '::toDate:' + end + '::inclspamtrash:true'
            candidates = set(); seen = set()
            for page in range(3):
                rows = self._get('/api/accounts/' + control.MAIL_ACCOUNT + '/messages/search',
                    {'searchKey': query, 'start': page * 200 + 1, 'limit': 200,
                     'receivedTime': int((now + timedelta(minutes=2)).timestamp() * 1000), 'includeto': 'true'}, list)
                for row in rows:
                    identity = str(row.get('messageId') or '')
                    if not _ID.fullmatch(identity) or identity in seen:
                        raise ValueError('Sent search is incomplete or overlapping')
                    seen.add(identity)
                    if str(row.get('folderId')) != SENT_FOLDER or row.get('subject') != subject: continue
                    stamp = datetime.fromtimestamp(int(row.get('receivedTime') or row.get('receivedtime')) / 1000, timezone.utc)
                    if attempted - timedelta(seconds=5) <= stamp <= attempted + timedelta(minutes=5):
                        candidates.add(identity)
                if len(rows) < 200: break
            else: raise ValueError('Sent search exceeds bounded reconciliation')
            if item.get('acknowledged_id'): candidates.add(item['acknowledged_id'])
            if len(candidates) > 8: raise ValueError('Exact Sent candidate bound exceeded')
            matches = [proof for identity in sorted(candidates) if (proof := self._sent_match(identity, item, now))]
            if len(matches) != 1:
                reason = 'Duplicate exact Sent effects' if matches else 'Provider effect not yet independently located'
                item['state'] = 'uncertain'; self.hold(item['family'], action_id, reason)
                self.journal.append(effect, 'customer_reconciliation', {'matches': len(matches),
                    'provider_message_ids': [p['provider_message_id'] for p in matches], 'resend_allowed': False})
                return {'state': 'DUPLICATE' if matches else 'HOLD', 'sent': False,
                        'action_id': action_id, 'resend_allowed': False, 'matches': len(matches)}
            proof = matches[0]
            self.remote.complete(effect, proof['provider_message_id'])
            self.journal.append(effect, 'customer_verified', proof)
            item.update(state='verified', provider_id=proof['provider_message_id'], sent_at=proof['sent_at'], verification=proof)
            held = self.state['holds'].get(item['family'], {})
            held.pop(action_id, None)
            if not held: self.state['holds'].pop(item['family'], None)
            self.save()
            return {'state': 'VERIFIED', 'sent': True, 'action_id': action_id,
                    'provider_message_id': proof['provider_message_id'], 'resend_allowed': False}
        except Exception as exc:
            item['state'] = 'uncertain'; self.hold(item['family'], action_id,
                'Provider reconciliation unavailable: ' + type(exc).__name__)
            self.journal.append(effect, 'customer_reconciliation_unavailable', {'error_type': type(exc).__name__, 'resend_allowed': False})
            return {'state': 'HOLD', 'sent': False, 'action_id': action_id, 'resend_allowed': False}
