from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from workflow.automation.autonomy_model_rehearsal import ModelRehearsal
from workflow.automation.codex_fixture_protocol import billing_blockers, fixture_reply
from workflow.automation.operational_recovery import DevelopmentScope, RULE

import test_autonomy_model_rehearsal as prior
from test_autonomy_pilot import NOW, quota, sample


def transcript(proposal=None, *, before=None, usage=None):
    if proposal is None:
        proposal = json.dumps(prior.EXPECTED)
    lines = [
        {'type': 'thread.started', 'thread_id': 'synthetic-thread'},
        {'type': 'turn.started'},
        *(before or []),
        {'type': 'item.completed', 'item': {'id': 'item_1', 'type': 'agent_message', 'text': proposal}},
        {'type': 'turn.completed', 'usage': usage if usage is not None else {
            'input_tokens': 600, 'cached_input_tokens': 100, 'output_tokens': 250, 'reasoning_output_tokens': 50}},
    ]
    return {'status': 200, 'seconds': 12,
            'stdout_jsonl': '\n'.join(json.dumps(row, ensure_ascii=False) for row in lines) + '\n'}


class ProtocolTests(unittest.TestCase):
    def test_accepted_transcript_extracts_exact_proposal_and_counts_subsets_once(self):
        parsed, usage = fixture_reply(transcript(before=[
            {'type': 'item.completed', 'item': {'id': 'reasoning', 'type': 'reasoning', 'text': 'fixture only'}}]))
        self.assertEqual(parsed['proposal'], prior.EXPECTED)
        self.assertEqual(parsed['tokens'], 850)
        self.assertEqual(usage['cached_input_tokens'], 100)
        self.assertEqual(usage['reasoning_output_tokens'], 50)

    def test_tool_use_duplicate_output_and_missing_completion_are_refused(self):
        for event in ({'type': 'item.started', 'item': {'id': 'cmd', 'type': 'command_execution'}},
                      {'type': 'item.completed', 'item': {'id': 'more', 'type': 'agent_message', 'text': '{}'}},
                      {'type': 'turn.failed', 'error': {'message': 'fixture failure'}},
                      {'type': 'turn.started'}):
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    fixture_reply(transcript(before=[event]))
        partial = transcript()
        partial['stdout_jsonl'] = '\n'.join(partial['stdout_jsonl'].splitlines()[:-1])
        with self.assertRaises(ValueError):
            fixture_reply(partial)

    def test_unverified_usage_or_oversized_trace_is_refused(self):
        samples = (
            transcript(usage={'input_tokens': 1, 'cached_input_tokens': 2, 'output_tokens': 3}),
            transcript(usage={'input_tokens': True, 'cached_input_tokens': 0, 'output_tokens': 3}),
            transcript(usage={'input_tokens': 1, 'output_tokens': 3}),
            {'stdout_jsonl': 'x' * 25000},
        )
        for value in samples:
            with self.assertRaises(ValueError):
                fixture_reply(value)

    def test_untrusted_duplicate_json_becomes_invalid_proposal_in_metered_turn(self):
        parsed, usage = fixture_reply(transcript('{"selected":[],"selected":[]}'))
        self.assertIsNone(parsed['proposal'])
        self.assertEqual(usage['input_tokens'], 600)

    def test_account_quota_and_prompt_assertions_cannot_authorize_credit_overflow(self):
        for available in (True, False, None):
            evidence = {'existing_credit_availability': available, 'provider_enforced_included_only': True,
                        'automatic_reload_setting': 'VERIFIED_DISABLED', 'usedPercent': 2}
            report = billing_blockers(evidence)
            self.assertEqual(report['state'], 'BLOCKED_SCOPE_AND_BILLING')
            self.assertEqual(report['model_turns_started'], 0)
            self.assertEqual('credits_available_for_automatic_overflow' in report['reasons'], available is True)

    def test_invalid_content_repair_and_incomplete_turn_nonreplay_in_ledger(self):
        with TemporaryDirectory() as tmp:
            scope = DevelopmentScope(Path(tmp).resolve())
            scope.write('.optibrain-development.json', json.dumps({
                'environment': 'isolated-development', 'production_allowed': False, 'rule': RULE,
                'root': str(scope.root), 'issued_at': NOW.isoformat(),
                'expires_at': (NOW + timedelta(hours=2)).isoformat(),
            }).encode())
            incomplete = transcript()
            incomplete['stdout_jsonl'] = '\n'.join(incomplete['stdout_jsonl'].splitlines()[:-1])
            replies = (transcript('{"invented":true}'), incomplete, transcript())

            def invoke(when):
                lane = ModelRehearsal(scope, source='a' * 40, evidence=prior.proof_rows(), fixtures=replies)
                return lane.run(lambda: sample(when), quota(when, 15, NOW + timedelta(hours=1)), clock=lambda: when)
            first = invoke(NOW)
            review = first['results']['model-fixture-1']['checkpoint']['review']
            self.assertFalse(review['candidate_accepted'])
            self.assertEqual(review['assessment']['state'], 'REPAIR_REQUIRED')
            self.assertEqual(review['assessment']['simulated_tokens'], 850)
            when = NOW + timedelta(seconds=1)
            second = invoke(when)
            hold = second['results']['model-fixture-2']['checkpoint']['review']['assessment']
            self.assertEqual(hold['state'], 'HUMAN_ACTION_REQUIRED')
            third = invoke(when)
            self.assertEqual(third['results']['model-fixture-3']['reason'], 'previous_attempt_is_terminal')
            self.assertEqual(second['results']['model-fixture-2'], third['results']['model-fixture-2'])
            self.assertEqual(third['results']['deterministic-evidence']['state'], 'COMPLETED')
            self.assertEqual(third['model_turns'], 0)
