"""Exercise read-only launch binding with synthetic authority and transport."""
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from workflow.automation.action_evidence import ActionEvidence, approval_binding
from workflow.automation.autonomy_pilot import LEASE_SECONDS, digest
from workflow.automation import autonomy_responses_dispatch as sender
from workflow.automation import autonomy_responses_launcher as launcher
from workflow.automation.operational_recovery import DevelopmentScope, RULE
from workflow.automation.store import AutomationStore
from test_autonomy_pilot import NOW, sample
from test_autonomy_responses import PROPOSAL, REQUEST, encode, response

SOURCE = 'a' * 40
BODY = encode(REQUEST)
PAYLOAD = sha256(BODY).hexdigest()


def evidence(scope, now, *, source=SOURCE, expected=PROPOSAL, request_sha256=PAYLOAD, project_changes=None):
    """Build only synthetic launch inputs for exact binding checks."""
    expires = (now + timedelta(minutes=2)).isoformat()
    recovery = encode({'result': 'SIGNED_RECEIPT_MATCH', 'signed_receipt_sha256': 'b' * 64,
                       'generation': '20261121T024014Z', 'independent_review': True})
    project = encode({'model': launcher.MODEL, 'service_tier': 'global_standard',
                      'hard_limit_enforced': True, 'automatic_reload': False, 'funding_verified': True,
                      'restricted_identity_verified': True, 'hard_monthly_usd_micros': 1_000_000,
                      'input_usd_cents_per_million': 75, 'output_usd_cents_per_million': 450,
                      'organization': 'org-fixture', 'project': 'proj_fixture', 'verified_at': now.isoformat()
                      } | (project_changes or {}))
    runtime = encode({'launcher_review': 'PASS', 'egress': launcher.ENDPOINT, 'external_wall_seconds': 60,
                      'scope': str(scope.root), 'source': source})
    owner = encode({'schema': 1, 'owner': 'synthetic_owner', 'starts_at': now.isoformat(),
                    'expires_at': expires, 'source': source, 'scope': str(scope.root),
                    'recovery_sha256': sha256(recovery).hexdigest(),
                    'project_sha256': sha256(project).hexdigest(),
                    'runtime_sha256': sha256(runtime).hexdigest(), 'request_sha256': request_sha256,
                    'expected_sha256': digest(expected), 'endpoint': launcher.ENDPOINT,
                    'model': launcher.MODEL, 'limits': launcher._LIMITS})
    return {'owner': owner, 'expected_owner_sha256': sha256(owner).hexdigest(), 'recovery': recovery,
            'project': project, 'runtime': runtime}, expires


class ResponsesLauncherTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.scope = DevelopmentScope(Path(temp.name).resolve())
        self.scope.write('.optibrain-development.json', encode({
            'environment': 'isolated-development', 'production_allowed': False, 'rule': RULE,
            'root': str(self.scope.root), 'issued_at': NOW.isoformat(),
            'expires_at': (NOW + timedelta(hours=1)).isoformat(),
        }))
        self.inputs, self.expires = evidence(self.scope, NOW)
        self.addCleanup(patch.stopall)
        patch.object(sender, 'PINNED_REQUEST', PAYLOAD).start()
        patch.object(launcher, 'PINNED_REQUEST', PAYLOAD).start()
        patch.object(launcher, '_checkout_source', return_value=SOURCE).start()
        patch.object(sender, 'cgroup_proof', return_value={}).start()

    def run_task(self, evidence=None, **changes):
        kwargs = {'sample': sample, 'body': BODY, 'expected': PROPOSAL, 'clock': lambda: NOW,
                  'credential': lambda: self.fail('credential loaded before exact authority')}
        return launcher.run_reviewed_launch(self.scope, **((evidence or self.inputs) | kwargs | changes))

    def test_changed_packet_or_expected_result_cannot_create_attempt(self):
        bad_inputs = (
            self.inputs | {'owner': self.inputs['owner'] + b' '},
            self.inputs | {'project': self.inputs['project'] + b' '},
            self.inputs | {'expected_owner_sha256': ''},
        )
        for bad in bad_inputs:
            with self.subTest(fields=list(bad)), self.assertRaises(ValueError):
                self.run_task(bad)
        with self.assertRaisesRegex(ValueError, 'reviewed expected result'):
            self.run_task(expected=PROPOSAL | {'overdue_cents': 0})
        self.assertFalse(self.scope.path('automation.db').exists())

    def test_disabled_hard_limit_reload_and_stale_project_evidence_refused(self):
        for changed in ({'hard_limit_enforced': False}, {'automatic_reload': True},
                        {'verified_at': (NOW - timedelta(minutes=16)).isoformat()},
                        {'input_usd_cents_per_million': 99}):
            unfit, _ = evidence(self.scope, NOW, project_changes=changed)
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'project billing'):
                self.run_task(unfit)

    def test_current_owner_packet_and_source_are_both_required(self):
        with self.assertRaisesRegex(ValueError, 'not current'):
            self.run_task(clock=lambda: NOW + timedelta(minutes=3))
        with patch.object(launcher, '_checkout_source', return_value='e' * 40), self.assertRaisesRegex(
                ValueError, 'Executing source'):
            self.run_task()

    def stage_approval(self, owner):
        self.assertEqual(self.run_task()['reason'], 'independent_owner_approval_missing')
        journal = ActionEvidence(self.scope.path('automation.db'))
        plan = sender.dispatch_plan(BODY, PROPOSAL, NOW, source=SOURCE,
            recovery_receipt=sha256(self.inputs['recovery']).hexdigest(),
            project_receipt=sha256(self.inputs['project']).hexdigest(),
            organization='org-fixture', project='proj_fixture')
        journal.plan(plan, NOW)
        journal.approve(sender.ACTION_ID, owner, NOW, binding=approval_binding(plan), expires_at=self.expires)

    def test_other_journal_principal_does_not_load_credential(self):
        self.stage_approval('someone_else')
        self.assertEqual(self.run_task()['reason'], 'independent_authority_not_current')

    def test_matching_local_approval_drives_one_fake_exchange_only(self):
        self.stage_approval('synthetic_owner')
        sent = []

        def reply(req):
            sent.append(req.content)
            return httpx.Response(200, stream=httpx.ByteStream(encode(response())))

        with patch.object(sender.httpx, 'HTTPTransport', return_value=httpx.MockTransport(reply)):
            result = self.run_task(credential=lambda: 'offline-fixture-key-value')
            self.assertEqual(self.run_task(), result)
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertEqual(sent, [BODY])

    def test_expired_launch_can_reopen_existing_verified_checkpoint_offline(self):
        self.stage_approval('synthetic_owner')
        sent = []

        def reply(req):
            sent.append(req.content)
            return httpx.Response(200, stream=httpx.ByteStream(encode(response())))

        with patch.object(sender.httpx, 'HTTPTransport', return_value=httpx.MockTransport(reply)):
            with patch.object(AutomationStore, 'complete_claimed_action', side_effect=SystemExit(70)):
                with self.assertRaises(SystemExit):
                    self.run_task(credential=lambda: 'offline-fixture-key-value')
        now = NOW + timedelta(seconds=LEASE_SECONDS + 1)
        self.assertGreater(now, NOW + timedelta(minutes=2))
        result = launcher.recover_reviewed_checkpoint(self.scope, body=BODY, expected=PROPOSAL, clock=lambda: now)
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertEqual(result['checkpoint']['recovery']['kind'], 'verified_provider_journal')
        self.assertEqual(sent, [BODY])
