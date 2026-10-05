from datetime import datetime, timezone
import importlib.util
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation.today import render_activity, build_today
from workflow.automation.phase9_form_receipts import FormReceiptLedger

PATH = Path(__file__).resolve().parents[3] / 'ops/phase14/activity_snapshot.py'
spec = importlib.util.spec_from_file_location('phase32_activity', PATH)
activity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activity)


class ActivityTests(unittest.TestCase):
    def test_real_receipt_schema_separates_tests_and_quarantined_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = FormReceiptLedger(Path(directory) / 'receipts.db')
            for key, test in (('genuine', False), ('test', True), ('classified', False), ('conflict', False)):
                receipt = dict(event_id=key, provider_message_id='provider-' + key,
                    internet_message_id='internet-' + key, occurred_at='2026-10-05T12:00:00+00:00',
                    source='zoho_form', form_id='fixture', submitted_email='fixture@example.invalid',
                    reference=None, raw_hash='hash-' + key, test_only=test)
                self.assertEqual(ledger.record(receipt), 'CREATED')
                self.assertEqual(ledger.record(receipt), 'REPLAY')
            with sqlite3.connect(ledger.path) as db:
                db.execute('INSERT INTO form_test_classifications VALUES(?,?,?)',
                    ('classified', '{}', '2026-10-05T12:00:00+00:00'))
            ledger.anomaly('mailbox', 'provider-conflict', 'IMMUTABLE_RECEIPT_CONFLICT',
                {'reason':'fixture'}, datetime(2026, 10, 5, 12, tzinfo=timezone.utc), existing_event_id='conflict')
            result = activity.inquiry_counts(ledger.path)
            self.assertEqual(result['confirmed_non_test_inquiries'], 1)
            self.assertEqual(result['confirmed_test_inquiries'], 2)
            self.assertEqual(result['quarantined_conflicts'], 1)
            self.assertNotIn('email', str(result))
            self.assertEqual(len(ledger.list()), 4)

    def test_timer_configuration_alone_is_not_scheduled_proof(self):
        service = dict(ExecMainStartTimestamp='Mon 2026-10-05 12:00:00 UTC',
                       ExecMainExitTimestamp='Mon 2026-10-05 12:00:03 UTC', Result='success', ExecMainStatus='0')
        timer = dict(LastTriggerUSec='Mon 2026-10-05 11:00:00 UTC', ActiveState='active', UnitFileState='enabled')
        with patch.object(activity, 'properties', side_effect=[service, timer]):
            row = activity.job('optibrain-backup')
        self.assertEqual(row['origin'], 'MANUAL OR EXTERNAL / UNPROVEN')
        self.assertEqual(row['state'], 'COMPLETED')
        timer['LastTriggerUSec'] = 'Mon 2026-10-05 12:00:00 UTC'
        with patch.object(activity, 'properties', side_effect=[service, timer]):
            self.assertEqual(activity.job('optibrain-backup')['origin'], 'SCHEDULED')

    def test_journal_projection_excludes_pii_and_unknown_counts(self):
        rows = activity.counters('opticable-phase9-intake-receipts',
            ['not json', '{"form_mail":{"replayed":5,"created":0,"scanned":5,"name":"Private Person"},"email":"private@example.org"}'])
        self.assertEqual(rows, {'forms_scanned':5, 'forms_created':0, 'forms_replayed':5})
        self.assertNotIn('private', str(rows).lower())
        self.assertNotIn('forms_conflicts_quarantined', rows)

    def test_provider_or_database_observation_failure_is_unknown_not_zero(self):
        with patch.object(activity, 'job', side_effect=OSError('Unavailable')):
            view = activity.collect(Path('/does-not-exist'))
        self.assertEqual(view['inquiries']['state'], 'UNKNOWN')
        self.assertNotIn('confirmed_non_test_inquiries', view['inquiries'])
        self.assertTrue(all(row['state']=='UNKNOWN' for row in view['jobs']))

    def test_today_renders_local_time_and_separates_test_evidence(self):
        value = dict(schema=1, read_only=True, captured_at='2026-10-05T12:00:00+00:00',
            coverage='Latest invocation; not a 24-hour total', jobs=[dict(label='<script>', job='fixture', origin='SCHEDULED',
            started_at='2026-10-05T12:00:00+00:00', completed_at='2026-10-05T12:00:03+00:00',
            state='COMPLETED', counters={'forms_created':0})], inquiries=dict(confirmed_test_inquiries=5,
            confirmed_non_test_inquiries=0, quarantined_conflicts=0, last_acknowledged_at='2026-10-04T12:00:00+00:00'))
        today=build_today({}, {}, {}, {'actions':[]}, {'signals':[], 'activity':value})
        rendered=render_activity(today['activity'])
        self.assertIn('08:00:00 EDT',rendered)
        self.assertIn('5 TEST_ONLY',rendered)
        self.assertIn('0 non-test',rendered)
        self.assertNotIn('<script>',rendered)
        self.assertIn('&lt;script&gt;',rendered)
        self.assertIn('not GA4 conversions',rendered)
        self.assertIn('unavailable',render_activity(None))


if __name__ == '__main__':
    unittest.main()
