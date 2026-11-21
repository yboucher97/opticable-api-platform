"""Exercise actual HTTP client construction through a socket-free fake transport."""
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from workflow.automation.action_evidence import ActionEvidence, approval_binding
from workflow.automation import autonomy_responses_dispatch as dispatch
from test_autonomy_pilot import NOW
from test_autonomy_responses import PROPOSAL, REQUEST, encode, response

BODY = encode(REQUEST)
PROJECT = 'proj_fixture'
KEY = 'fixture-only-secret-value'


class ResponsesDispatchTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.journal = ActionEvidence(Path(scratch.name) / 'automation.db')
        self.requests = []
        self.credential_reads = 0
        self.transport = patch.object(dispatch.httpx, 'HTTPTransport', side_effect=self.mock_transport).start()
        self.addCleanup(patch.stopall)
        patch.object(dispatch, 'PINNED_REQUEST', sha256(BODY).hexdigest()).start()
        self.bounds = patch.object(dispatch, 'cgroup_proof', return_value={}).start()
        self.plan = dispatch.dispatch_plan(BODY, PROPOSAL, NOW, source='a' * 40,
            recovery_receipt='b' * 64, project_receipt='c' * 64, organization='org-fixture', project=PROJECT)
        self.journal.plan(self.plan, NOW)
        self.expires = NOW + timedelta(minutes=1)
        self.reply = lambda _: httpx.Response(200, headers={'x-request-id': 'req_fixture'},
                                             stream=httpx.ByteStream(encode(response())))

    def mock_transport(self, **kwargs):
        self.assertEqual(kwargs, {'retries': 0, 'trust_env': False})
        return httpx.MockTransport(self.handle)

    def handle(self, req):
        self.assertEqual(self.journal.get(dispatch.ACTION_ID)['status'], 'STARTED')
        self.requests.append(req)
        return self.reply(req)

    def approve(self, actor='authorized_owner'):
        self.journal.approve(dispatch.ACTION_ID, actor, NOW, binding=approval_binding(self.plan),
                             expires_at=self.expires.isoformat())

    def credential(self):
        self.credential_reads += 1
        return KEY

    def run_attempt(self, **updates):
        values = {'body': BODY, 'expected': PROPOSAL, 'authorize': lambda _: True,
                  'credential': self.credential, 'clock': lambda: NOW}
        return dispatch.dispatch_once(self.journal, **(values | updates))

    def test_verified_and_bound_request_is_single_durable_dispatch(self):
        self.approve()
        result = self.run_attempt()
        self.assertEqual(result['state'], 'VERIFIED_INTERNAL')
        self.assertEqual(result['metering'], {'input': 406, 'output': 80, 'total': 486})
        self.assertEqual(result['provider_request_id'], 'req_fixture')
        request, = self.requests
        self.assertEqual(str(request.url), dispatch.ENDPOINT)
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.content, BODY)
        self.assertEqual(request.headers['openai-project'], PROJECT)
        self.assertEqual(request.headers['openai-organization'], 'org-fixture')
        self.assertEqual(request.headers['x-client-request-id'], result['client_request_id'])
        self.assertEqual(request.headers['authorization'], 'Bearer ' + KEY)
        plan = self.journal.get(dispatch.ACTION_ID)
        self.assertEqual(plan['status'], 'SUCCEEDED')
        self.assertEqual(plan['after_state']['metering'], result['metering'])
        self.assertNotIn(KEY, str(plan))
        with self.assertRaises(ValueError):
            self.run_attempt()
        self.assertEqual((len(self.requests), self.credential_reads), (1, 1))

    def test_missing_approval_changed_request_or_negative_authority_never_load_key(self):
        with self.assertRaises(ValueError):
            self.run_attempt()
        self.approve()
        for kwargs in ({'body': BODY + b'\n'}, {'expected': PROPOSAL | {'overdue_cents': 0}},
                       {'authorize': lambda _: False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_attempt(**kwargs)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.credential_reads, 0)
        self.assertEqual(self.journal.get(dispatch.ACTION_ID)['status'], 'PLANNED')

    def test_replaced_approval_after_external_check_stays_unstarted(self):
        self.approve()

        def replace(record):
            self.assertEqual(record['approval_record']['actor'], 'authorized_owner')
            self.approve(actor='different_principal')
            return True

        with self.assertRaisesRegex(ValueError, 'verified approval changed'):
            self.run_attempt(authorize=replace)
        self.assertEqual(self.credential_reads, 0)
        self.assertEqual(self.journal.get(dispatch.ACTION_ID)['status'], 'PLANNED')

    def test_future_dated_approval_cannot_start(self):
        self.journal.approve(dispatch.ACTION_ID, 'authorized_owner', NOW + timedelta(seconds=2),
                             binding=approval_binding(self.plan), expires_at=self.expires.isoformat())
        with self.assertRaisesRegex(ValueError, 'Owner approval is not current'):
            self.run_attempt()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.credential_reads, 0)

    def test_expiration_after_durable_reservation_requires_reconciliation_without_egress(self):
        self.approve()
        timestamps = iter([NOW, NOW, self.expires, self.expires])
        out = self.run_attempt(clock=lambda: next(timestamps))
        self.assertEqual(out['state'], 'RECONCILE_REQUIRED')
        self.assertEqual(self.requests, [])
        self.assertEqual(self.journal.get(dispatch.ACTION_ID)['status'], 'FAILED')

    def test_429_records_cooldown_and_ignores_retry_or_body(self):
        self.approve()
        self.reply = lambda _: httpx.Response(429, headers={'retry-after': '190', 'x-request-id': 'req_wait'},
                                              stream=httpx.ByteStream(b'ignored private body'))
        out = self.run_attempt()
        self.assertEqual(out['state'], 'RECONCILE_REQUIRED')
        self.assertEqual(out['http_status'], 429)
        self.assertEqual(out['cooldown_until'], (NOW + timedelta(seconds=190)).isoformat())
        self.assertEqual(out['provider_request_id'], 'req_wait')
        with self.assertRaises(ValueError):
            self.run_attempt()
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn('ignored private body', str(self.journal.get(dispatch.ACTION_ID)))

    def test_redirect_does_not_trigger_additional_request(self):
        self.approve()
        self.reply = lambda _: httpx.Response(302, headers={'location': 'https://elsewhere.example/'})
        self.assertEqual(self.run_attempt()['http_status'], 302)
        self.assertEqual(len(self.requests), 1)

    def test_timeout_keeps_correlation_and_never_retries(self):
        self.approve()

        def time_out(request):
            raise httpx.ReadTimeout('simulated private diagnostic', request=request)

        self.reply = time_out
        receipt = self.run_attempt()
        self.assertEqual(receipt['state'], 'RECONCILE_REQUIRED')
        self.assertEqual(receipt['client_request_id'], self.requests[0].headers['x-client-request-id'])
        self.assertNotIn('simulated private diagnostic', str(self.journal.get(dispatch.ACTION_ID)))
        with self.assertRaises(ValueError):
            self.run_attempt()
        self.assertEqual(len(self.requests), 1)

    def test_interruption_after_durable_start_is_held_on_restart(self):
        self.approve()

        def interrupt(_):
            raise SystemExit(70)

        self.reply = interrupt
        with self.assertRaises(SystemExit):
            self.run_attempt()
        self.journal = ActionEvidence(self.journal.path)
        self.assertEqual(self.journal.get(dispatch.ACTION_ID)['status'], 'STARTED')
        with self.assertRaises(ValueError):
            self.run_attempt()
        self.assertEqual(len(self.requests), 1)

    def test_overlong_body_rejects_without_persisting_upstream_bytes(self):
        self.approve()
        self.reply = lambda _: httpx.Response(200, stream=httpx.ByteStream(b'X' * (16 * 1024 + 1)))
        receipt = self.run_attempt()
        self.assertEqual(receipt['state'], 'RECONCILE_REQUIRED')
        self.assertEqual(receipt['http_status'], 200)
        self.assertNotIn('X' * 32, str(self.journal.get(dispatch.ACTION_ID)))
        self.assertEqual(len(self.requests), 1)
