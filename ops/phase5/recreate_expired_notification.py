#!/usr/bin/env python3
"""Plan or explicitly approve recreation of the one expired native channel.

Default is read-only, including the existing Desired State journal. Never erase
or relabel the old ambiguous renewal as successful. The apply path requires a
fresh private root approval and an exact, already reachable NEW hold receiver.
"""
import argparse
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'apps/workflow-api'))
from workflow.automation.action_evidence import ActionEvidence, envelope, approval_binding
from workflow.automation.desired_journal import DesiredJournal, resource_key
from workflow.automation.desired_state import DesiredStateController, DesiredStateDocument, DesiredStateRegistry
from workflow.automation.event_schema import digest
from workflow.automation.intake_hold import IntakeHoldPolicy
from workflow.automation.mutation_control import technical_admin_call
from workflow.automation.reconcilers.zoho_notification import ZohoCrmNotificationReconciler

CHANNEL = '5062683202609281'
PATH = '/crm/v8/actions/watch'


def require(value, reason):
    if not value:
        raise ValueError(reason)


class ReadOnlyStore:
    def __init__(self, path):
        self.db_path = Path(path).resolve()

    def _connect(self):
        db = sqlite3.connect(self.db_path.as_uri()+'?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        return db


def prior_review(journal, key, now):
    prior = journal.last(key, ('started', 'verified', 'manual'))
    require(prior is not None and prior['action'] in {'started', 'manual'}, 'No matching ambiguous configuration intent')
    meta = prior['metadata']
    expected = meta.get('native_expected') or {}
    expiry = datetime.fromisoformat(expected['expiry'].replace('Z', '+00:00'))
    require(meta.get('provider') == 'zoho_crm' and meta.get('kind') == 'notification'
            and expected.get('channel_id') == CHANNEL and meta.get('action') in {'create', 'update'}
            and expiry.tzinfo is not None and expiry < now, 'Only expired exact native configuration may be reviewed')
    return prior


class ReviewedExpiredJournal(DesiredJournal):
    """One approved supersession; every original row/effect remains unchanged."""
    def __init__(self, store, key, prior_sha256):
        super().__init__(store)
        self.key, self.prior_sha256 = key, prior_sha256

    def unresolved(self, target):
        if target == self.key:
            prior = self.last(target, ('started', 'verified', 'manual'))
            if prior and digest(prior) == self.prior_sha256:
                prior_review(self, target, datetime.now(timezone.utc))
                return False
        return super().unresolved(target)


def controller(client, store):
    registry = DesiredStateRegistry()
    registry.register('zoho_crm', 'notification', ZohoCrmNotificationReconciler(client))
    return DesiredStateController(registry, store)


def proposal(client, store, document, expiry):
    os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY'] = expiry
    control = controller(client, store)
    key = resource_key(document.resources[0])
    prior = prior_review(control.journal, key, datetime.now(timezone.utc))
    plan = control.plan(document)
    require(plan.summary == {'create': 1} and plan.changes[0].current is None, 'Exact channel absence and fresh CREATE plan required')
    require(prior['metadata']['native_expected']['configuration_hash'] == plan.changes[0].desired['configuration_hash'],
            'Notification authentication or destination changed')
    return {'status': 'READY_FOR_APPROVAL', 'phase': 'CRM_NOTIFICATION_RECREATE_ONLY',
            'prior_intent_sha256': digest(prior), 'prior_intended_expiry': prior['metadata']['native_expected']['expiry'],
            'provider_before_sha256': digest(None), 'new_expiry': expiry,
            'plan_hash': plan.plan_hash, 'plan': plan.model_dump(mode='json'),
            'old_manual_result_preserved': True, 'provider_mutations': 0,
            'execution_prerequisite': 'Owner approval and NEW public/private hold receiver verified; one POST only'}


def approved_file(path, proposed, *, candidate_sha, now):
    require(os.geteuid() == 0, 'Root-only explicit approval')
    for parent in list(path.parents)[:-1]:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022, 'Untrusted approval parent')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 16384, 'Private root approval required')
        raw = stream.read()
    value = json.loads(raw)
    issued = datetime.fromisoformat(value['approved_at'])
    until = datetime.fromisoformat(value['expires_at'])
    require(value.get('approved') is True and value.get('phase') == proposed['phase']
            and value.get('candidate_sha') == candidate_sha and issued <= now < until
            and until-issued <= timedelta(hours=1), 'Exact fresh owner approval required')
    for key in ('prior_intent_sha256', 'provider_before_sha256', 'new_expiry', 'plan_hash'):
        require(value.get(key) == proposed[key], 'Owner approval differs from proposal')
    require(value.get('receiver_hold_verified') is True, 'Receiver verification approval required')
    return value, hashlib.sha256(raw.encode()).hexdigest()


def apply_approved(client, store, document, proposed, approval, approval_sha):
    control = controller(client, store)
    key = resource_key(document.resources[0])
    control.journal = ReviewedExpiredJournal(store, key, proposed['prior_intent_sha256'])
    fresh = proposal(client, store, document, proposed['new_expiry'])
    require(fresh == proposed, 'Native configuration changed before approval execution')
    plan = control.plan(document)
    destination, token, when, channel = control.registry.resolve(document.resources[0]).configuration(document.resources[0])
    body = {'watch': [{'channel_id': channel, 'events': ['Leads.create', 'Leads.edit'],
        'notify_url': destination, 'token': token, 'channel_expiry': when.isoformat(),
        'notify_on_related_action': False, 'return_affected_field_values': False}]}
    audit = ActionEvidence(store.db_path)
    aid = 'native-recreate:' + approval_sha
    require(audit.get(aid) is None, 'Approval already used; GET-only reconciliation required')
    now = datetime.now(timezone.utc)
    record = envelope(aid, 'EXPIRED_NATIVE_NOTIFICATION_RECREATE', {'type': 'CONFIGURATION', 'identity': PATH}, now,
        provider='zoho_crm_notification', mutation=True, approval_required=True, approval_record=approval,
        exact_versions={'owner_phase': 'CRM_NOTIFICATION_RECREATE_ONLY', 'owner_approval_sha256': approval_sha},
        before_state={'channel_absent': True, 'expired_manual_intent_sha256': proposed['prior_intent_sha256']},
        proposed_state=body, reason='Explicit owner-approved supersession of expired missing configuration',
        business_rationale='Capture new native notifications into isolated durable hold; no business record writes',
        rollback_capability='COMPENSATING_ACTION_ONLY',
        consequence='Provider will emit new notifications to the approved durable hold receiver',
        compensating_action='Keep receiving into hold; separately approve exact subscription disable or allow expiry; retain every receipt',
        authority_class='OWNER_EXACT_NATIVE_CONFIGURATION', automatic_rule='One approved POST; no automatic retry')
    audit.plan(record, now)
    audit.approve(aid, 'owner-private-approval-receipt', now, binding=approval_binding(record), expires_at=approval['expires_at'])
    audit.start(aid, now, authority_check=lambda: None)
    audit.event(aid, 'TECHNICAL_AUDIT', 'EXPIRED_ABSENCE_REVIEW',
                {'prior_intent_sha256': proposed['prior_intent_sha256'], 'old_result': 'MANUAL_PRESERVED'}, now)
    with technical_admin_call(client, 'zoho_crm_notification', 'POST', PATH, body, audit=audit, action_id=aid):
        results = control.apply(document, plan, actor='owner-approved-expired-native-recreation', low_risk_additive_only=True)
    success = len(results) == 1 and results[0].status == 'completed'
    after = control.registry.resolve(document.resources[0]).read(document.resources[0])
    success = success and after == plan.changes[0].desired
    audit.finish(aid, datetime.now(timezone.utc), provider_success=success, actual_after=after,
                 verified=success and after == plan.changes[0].desired,
                 response={'results': [r.model_dump(mode='json') for r in results]})
    return {'status': 'PASS' if success else 'BLOCKED_MANUAL_NO_RETRY', 'action_id': aid,
            'results': [r.model_dump(mode='json') for r in results], 'old_manual_result_preserved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--expiry', required=True)
    parser.add_argument('--approval', type=Path)
    args = parser.parse_args()
    from workflow.config import load_settings
    from workflow.zoho_oauth import ZohoOAuthManager
    from workflow.zoho_gateway import ZohoGatewayClient
    settings = load_settings()
    document = DesiredStateDocument.model_validate_json((ROOT/'apps/workflow-api/config/automation/desired-state/zoho-crm-notification.template.json').read_text())
    with tempfile.TemporaryDirectory(prefix='native-config-read-auth-') as temporary:
        auth = replace(settings.zoho_oauth, credentials_path=Path(temporary)/'zoho.json', access_cache_path=Path(temporary)/'cache.json')
        for source, dest in [(settings.zoho_oauth.credentials_path, auth.credentials_path),
                (ZohoOAuthManager(settings.zoho_oauth).cache_path, auth.access_cache_path)]:
            if source.is_file():shutil.copyfile(source, dest);dest.chmod(0o600)
        client = ZohoGatewayClient(replace(settings.zoho_gateway, standby_enabled=False), ZohoOAuthManager(auth))
        proposed = proposal(client, ReadOnlyStore(args.database), document, args.expiry)
        if not args.approval:
            print(json.dumps(proposed));return
        require(socket.gethostname() == 'vps-f8e9b20e' and Path('/etc/optibrain-rebuild-target').is_file(), 'Only marked NEW target may apply')
        policy = IntakeHoldPolicy.from_environment(execution_enabled=settings.automation.enabled)
        require(policy.enabled and args.database.resolve() == settings.automation.db_path, 'Canonical NEW hold database required')
        candidate = subprocess.check_output(['git', '-c', 'safe.directory='+str(ROOT), '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
        deployed = subprocess.check_output(['git', '-c', 'safe.directory=/opt/opticable-api-platform', '-C', '/opt/opticable-api-platform', 'rev-parse', 'HEAD'], text=True).strip()
        require(candidate == deployed, 'Reviewed candidate must be the deployed application source')
        approval, sha = approved_file(args.approval, proposed, candidate_sha=candidate, now=datetime.now(timezone.utc))
        import httpx
        headers = {'X-API-Key': os.environ[settings.api.api_key_env]}
        for base in ('http://127.0.0.1:8100', 'https://optibrain.opticable.ca'):
            response = httpx.get(base+'/v1/automation/event-health', headers=headers, timeout=15, follow_redirects=False)
            response.raise_for_status();health=response.json()['intake_hold']
            require(health['mode'] == 'hold-v1' and health['capture_available'], 'Live NEW hold receiver not ready')
        from workflow.automation.store import AutomationStore
        print(json.dumps(apply_approved(client, AutomationStore(args.database), document, proposed, approval, sha)))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'BLOCKED', 'error_type': type(exc).__name__, 'automatic_retry': False}))
        raise SystemExit(1)
