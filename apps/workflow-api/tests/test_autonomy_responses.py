"""New protocol and one-attempt receipt checks using synthetic bytes only."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from workflow.automation.autonomy_pilot import Pilot, Task
from workflow.automation.autonomy_responses import MAX_REQUEST_BYTES, MODEL, review_response, validate_request
from workflow.automation.operational_recovery import DevelopmentScope, RULE
from test_autonomy_pilot import NOW, sample

REQUEST = {
    'model': MODEL, 'service_tier': 'default', 'background': False, 'store': False, 'stream': False,
    'parallel_tool_calls': False, 'tools': [], 'tool_choice': 'none', 'max_output_tokens': 512,
    'reasoning': {'effort': 'none'}, 'input': 'Synthetic invoice fixture only',
    'instructions': 'Summarize the synthetic record.',
    'text': {'format': {'type': 'json_schema', 'strict': True, 'name': 'receipt', 'schema': {}}},
}
PROPOSAL = {'selected': [{'id': 'FN02', 'version': 'a' * 64}], 'overdue_cents': 125,
            'conditional_quote_cents': 0, 'currency': 'CAD', 'disposition': 'PREPARE_INTERNAL'}


def encode(value):
    return json.dumps(value, separators=(',', ':')).encode()


def response():
    return {'object': 'response', 'id': 'resp_local_fixture', 'status': 'completed', 'model': MODEL,
            'service_tier': 'default', 'output': [{'type': 'message', 'status': 'completed',
                'role': 'assistant', 'content': [{'type': 'output_text', 'text': encode(PROPOSAL).decode()}]}],
            'usage': {'input_tokens': 406, 'output_tokens': 80, 'total_tokens': 486,
                'input_tokens_details': {'cached_tokens': 5}, 'output_tokens_details': {'reasoning_tokens': 0}}}


class ResponsesContractTests(unittest.TestCase):
    def test_request_requires_exact_bytes_and_rejects_other_authority_even_with_valid_hash(self):
        pinned = encode(REQUEST)
        checksum = sha256(pinned).hexdigest()
        validate_request(pinned, checksum)
        with self.assertRaises(ValueError):
            validate_request(pinned + b'\n', checksum)
        cases = (
            encode(REQUEST | {'previous_response_id': 'unapproved'}),
            encode(REQUEST | {'tools': [{'type': 'web_search'}]}),
            encode(REQUEST | {'background': True}),
            encode(REQUEST | {'store': 0}),
            encode(REQUEST | {'service_tier': 'auto'}),
            encode(REQUEST | {'model': 'another-model'}),
            encode(REQUEST | {'max_output_tokens': 513}),
            encode(REQUEST | {'text': {'format': {'type': 'text'}}}),
            pinned[:-1] + b',"stream":false}',
            b' ' * MAX_REQUEST_BYTES + pinned,
        )
        for body in cases:
            with self.subTest(body=body[:42]), self.assertRaises(ValueError):
                validate_request(body, sha256(body).hexdigest())

    def test_completed_response_is_independently_verified_with_conservative_cost(self):
        raw = encode(response())
        result = review_response(raw, PROPOSAL)
        self.assertEqual(result, {'response_id': 'resp_local_fixture',
            'response_sha256': sha256(raw).hexdigest(),
            'proposal_sha256': 'b3aec9316a14710baaf4535ecc23e07005656c504f542e86d55dc202a8eae22c',
            'input_tokens': 406, 'output_tokens': 80, 'total_tokens': 486,
            'uncached_rate_upper_usd_micros': 665})

    def test_drift_incomplete_tool_and_bad_metering_rejected(self):
        for update in ({'model': 'other'}, {'service_tier': 'priority'}, {'status': 'incomplete'},
                       {'id': 'malformed'}, {'incomplete_details': {'reason': 'max_output_tokens'}},
                       {'output': [{'type': 'web_search_call'}]},
                       {'usage': {'input_tokens': 2, 'output_tokens': 513, 'total_tokens': 515}},
                       {'usage': {'input_tokens': 2, 'output_tokens': 1, 'total_tokens': 4}},
                       {'usage': {'input_tokens': 2, 'output_tokens': 1, 'total_tokens': 3,
                                  'output_tokens_details': {'reasoning_tokens': 2}}},
                       {'error': {'code': 'bad_request'}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                review_response(encode(response() | update), PROPOSAL)
        for content in ({'type': 'refusal', 'refusal': 'fixture refusal'},
                        {'type': 'output_text', 'text': '{"overdue_cents":125,"overdue_cents":125}'},
                        {'type': 'output_text', 'text': encode(PROPOSAL | {'overdue_cents': True}).decode()}):
            changed = response()
            changed['output'][0]['content'] = [content]
            with self.subTest(content=content), self.assertRaises(ValueError):
                review_response(encode(changed), PROPOSAL)


class ResponsesLedgerTests(unittest.TestCase):
    def run_fixture(self, reply):
        with tempfile.TemporaryDirectory() as temp:
            scope = DevelopmentScope(Path(temp).resolve())
            scope.write('.optibrain-development.json', encode({
                'environment': 'isolated-development', 'production_allowed': False, 'rule': RULE,
                'root': str(scope.root), 'issued_at': NOW.isoformat(),
                'expires_at': (NOW + timedelta(hours=1)).isoformat(),
            }))
            tasks = (Task('live-model', 90, lane='model'), Task('response-fixture', 80), Task('read-only-work', 70))
            body = encode(REQUEST)
            pinned = sha256(body).hexdigest()
            pilot = Pilot(scope, tasks, goal='Responses contract proof', source='a' * 40, input_hash=pinned)
            counts = []
            raw = None

            def fixture():
                nonlocal raw
                validate_request(body, pinned)
                counts.append('fixture')
                raw = encode(reply)
                return {'response_sha256': sha256(raw).hexdigest()}

            def independent(result):
                reviewed = review_response(raw, deepcopy(PROPOSAL))
                return {'passed': reviewed['response_sha256'] == result['response_sha256'],
                        'check': 'separate exact proposal and usage verification', 'reviewed': reviewed}

            def read_only():
                counts.append('independent')
                return {'source': 'synthetic-read'}

            handlers = {'response-fixture': fixture, 'read-only-work': read_only}
            reviewers = {'response-fixture': independent,
                         'read-only-work': lambda r: {'passed': r == {'source': 'synthetic-read'}, 'check': 'exact source'}}
            first = pilot.run(sample, handlers, reviewers, clock=lambda: NOW)
            # Restart with another controller over the same unchanged plan. The first receipts are final.
            again = Pilot(scope, tasks, goal='Responses contract proof', source='a' * 40, input_hash=pinned)
            second = again.run(sample, handlers, reviewers, clock=lambda: NOW)
            self.assertEqual(first['results'], second['results'])
            self.assertEqual(counts, ['fixture', 'independent'])
            self.assertEqual(first['model_turns'], 0)
            self.assertEqual(first['results']['live-model']['state'], 'APPROVAL_REQUIRED')
            self.assertEqual(first['results']['read-only-work']['state'], 'COMPLETED')
            return first['results']['response-fixture']

    def test_verified_fixture_survives_replay_with_one_marker(self):
        checkpoint = self.run_fixture(response())
        self.assertEqual(checkpoint['state'], 'COMPLETED')
        self.assertTrue(checkpoint['checkpoint']['review']['passed'])

    def test_rejected_quality_check_stays_failed_and_independent_work_continues(self):
        wrong = response()
        wrong['output'][0]['content'][0]['text'] = encode(PROPOSAL | {'overdue_cents': 0}).decode()
        self.assertEqual(self.run_fixture(wrong)['state'], 'FAILED')
