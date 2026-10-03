from datetime import datetime, timezone
import unittest

from workflow.automation.customer_finance_evidence import estimate_sent_at


class EstimateNativeSendHistoryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self.sent = {'comment_id': '10', 'estimate_id': '20', 'comment_type': 'system',
                     'transaction_type': 'email', 'operation_type': 'Updated',
                     'description': 'Devis envoyé par e-mail par OWNER à CONTROLLED_RECIPIENT',
                     'date': '2026-05-29', 'time': '11:26 AM'}

    def plan(self, history=None, timezone='US/Eastern', **overrides):
        return estimate_sent_at([self.sent] if history is None else history,
                                timezone, estimate_id='20', now=self.now, **overrides)

    def test_actual_native_french_system_email_descriptor_and_timezone(self):
        result = self.plan()
        self.assertEqual(result['decision'], 'OBSERVE')
        self.assertEqual(result['sent_at'], '2026-05-29T11:26:00-04:00')
        self.assertEqual(result['cadence_anchor_at'], '2026-05-29T11:27:00-04:00')
        self.assertEqual(result['precision'], 'MINUTE')
        self.assertFalse(result['financial_writes'])

    def test_english_send_and_emailed_and_french_courriel_equivalents(self):
        for description in ('Estimate emailed to CONTROLLED_RECIPIENT', 'Estimate has been sent to CONTROLLED_RECIPIENT',
                            'Estimate email sent by OWNER', 'Soumission envoyée par courriel à CONTROLLED_RECIPIENT'):
            with self.subTest(description=description):
                self.assertEqual(self.plan([{**self.sent, 'description': description}])['decision'], 'OBSERVE')

    def test_created_modified_viewed_and_marked_sent_are_not_send_timestamps(self):
        for description in ('Estimate created', 'Estimate modified', 'Estimate viewed by client',
                            'Le client a consulté le devis', 'Estimate marked as sent', 'Customer says email sent'):
            with self.subTest(description=description):
                self.assertEqual(self.plan([{**self.sent, 'description': description}])['decision'], 'HUMAN')

    def test_free_form_comment_and_wrong_operation_or_transaction_cannot_claim_send(self):
        for change in ({'comment_type': 'user'}, {'operation_type': 'Added'}, {'transaction_type': 'estimate'}):
            with self.subTest(change=change):
                self.assertEqual(self.plan([{**self.sent, **change}])['decision'], 'HUMAN')

    def test_view_after_send_does_not_delay_send_anchor(self):
        viewed = {**self.sent, 'comment_id': '11', 'description': 'Le client a consulté le devis', 'time': '4:14 PM'}
        self.assertEqual(self.plan([viewed, self.sent])['sent_at'], '2026-05-29T11:26:00-04:00')

    def test_real_owner_resend_resets_anchor_to_latest_actual_send(self):
        resent = {**self.sent, 'comment_id': '11', 'date': '2026-06-01', 'time': '3:04 PM'}
        self.assertEqual(self.plan([self.sent, resent])['sent_at'], '2026-06-01T15:04:00-04:00')

    def test_wrong_estimate_missing_identity_or_time_cannot_supply_anchor(self):
        for change in ({'estimate_id': '21'}, {'comment_id': ''}, {'date': 'bad'}, {'time': ''}, {'time': '25:00 PM'},
                       {'date': '2027-01-01'}, {'time': '11:26'}, {'time': '11:26:12 AM'}):
            with self.subTest(change=change):
                self.assertEqual(self.plan([{**self.sent, **change}])['decision'], 'HUMAN')

    def test_dst_ambiguous_and_nonexistent_local_send_times_require_human(self):
        for date, time in (('2026-11-01', '1:30 AM'), ('2026-03-08', '2:30 AM')):
            with self.subTest(date=date):
                self.assertEqual(self.plan([{**self.sent, 'date': date, 'time': time}])['decision'], 'HUMAN')

    def test_invalid_missing_timezone_and_incomplete_history_require_human(self):
        for timezone in ('Invalid/Zone', '', None):
            with self.subTest(timezone=timezone):
                self.assertEqual(self.plan(timezone=timezone)['decision'], 'HUMAN')
        for history in ([], None, {}, [self.sent] * 201, ['malformed']):
            with self.subTest(history=history):
                self.assertEqual(estimate_sent_at(history, 'US/Eastern', estimate_id='20', now=self.now)['decision'], 'HUMAN')

    def test_duplicate_system_history_identity_must_not_have_conflicting_time(self):
        self.assertEqual(self.plan([self.sent, self.sent])['decision'], 'OBSERVE')
        changed = {**self.sent, 'time': '12:26 PM'}
        self.assertEqual(self.plan([self.sent, changed])['decision'], 'HUMAN')


if __name__ == '__main__':
    unittest.main()
