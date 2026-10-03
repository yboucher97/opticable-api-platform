"""Native-observation contracts; fake readers never call production providers."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from workflow.automation import customer_runtime as runtime
from workflow.automation import customer_send_control as control
from workflow.automation.today import build_today


NOW = datetime.now(timezone.utc).replace(microsecond=0)
ACTIVATED = (NOW - timedelta(hours=1)).isoformat()


def schedule_row(visit, field, *, at=NOW, source='crm_ui', actor=runtime.OWNER, value=None):
    return {'id': '901', 'record': {'id': visit['id'], 'module': {'api_name': 'Installations'}},
        'audited_time': at.isoformat(), 'source': source, 'done_by': {'id': actor},
        'field_history': [{'api_name': field, '_value': {'old': None,
            'new': visit.get(field) if value is None else value}}]}


class ScheduleProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.visit = {'id': '501', 'Installation_Status': 'Scheduled',
            'Scheduled_Date': (NOW + timedelta(days=2)).isoformat(), 'Assigned_To': 'Technician One',
            'Instructions_Notes': 'Use main entrance'}
        self.rows = [schedule_row(self.visit, field) for field in
            ('Installation_Status', 'Scheduled_Date', 'Assigned_To')]

    def proof(self, rows=None, visit=None):
        return runtime.schedule_provenance(visit or self.visit, self.rows if rows is None else rows, ACTIVATED)

    def test_unrelated_record_edits_do_not_create_another_confirmation_version(self):
        original = self.proof()
        unrelated = schedule_row(self.visit, 'Description', at=NOW + timedelta(minutes=1), value='Internal note')
        foreign = schedule_row({**self.visit, 'id': '502'}, 'Scheduled_Date', at=NOW + timedelta(minutes=1))
        self.assertTrue(original)
        self.assertEqual(self.proof([foreign, unrelated, *self.rows]), original)
        self.assertEqual(self.proof(list(reversed(self.rows))), original)

    def test_reschedule_back_to_original_time_is_a_new_human_revision(self):
        original = self.proof()
        middle = schedule_row(self.visit, 'Scheduled_Date', at=NOW + timedelta(minutes=1),
                              value=(NOW + timedelta(days=3)).isoformat())
        latest = schedule_row(self.visit, 'Scheduled_Date', at=NOW + timedelta(minutes=2))
        self.assertNotEqual(self.proof([*self.rows, middle, latest]), original)

    def test_latest_api_schedule_cannot_inherit_older_human_authority(self):
        latest = schedule_row(self.visit, 'Scheduled_Date', at=NOW + timedelta(minutes=1), source='crm_api')
        self.assertIsNone(self.proof([*self.rows, latest]))

    def test_owner_access_edit_changes_version_and_api_access_edit_denies(self):
        owner = schedule_row(self.visit, 'Instructions_Notes', at=NOW + timedelta(minutes=1))
        self.assertNotEqual(self.proof([*self.rows, owner]), self.proof())
        self.assertIsNone(self.proof([*self.rows, {**owner, 'source': 'crm_api'}]))

    def test_equal_timestamp_conflicting_logistics_requires_human_review(self):
        conflicting = schedule_row(self.visit, 'Assigned_To', value='Different technician')
        self.assertIsNone(self.proof([*self.rows, conflicting]))
        self.assertIsNone(self.proof([conflicting, *self.rows]))

    def test_missing_stale_other_owner_or_wrong_current_value_has_no_authority(self):
        invalid = [self.rows[:-1],
            [schedule_row(self.visit, field, at=NOW-timedelta(hours=2)) for field in
                ('Installation_Status', 'Scheduled_Date', 'Assigned_To')],
            [*self.rows[:-1], schedule_row(self.visit, 'Assigned_To', actor='Other owner')],
            [*self.rows[:-1], schedule_row(self.visit, 'Assigned_To', value='Different technician')]]
        for rows in invalid:
            with self.subTest(rows=rows):
                self.assertIsNone(self.proof(rows))


class FakeNative:
    def __init__(self):
        at = NOW.isoformat()
        self.records = {
            ('Deals', '103'): {'id': '103', 'Deal_Name': 'Current accepted work', 'Account_Name': {'id': '102'},
                'Contact_Name': {'id': '101'}, 'Service_Location': {'id': '104'}, 'Stage': 'Proposal',
                'Created_Time': at, 'Modified_Time': at},
            ('Contacts', '101'): {'id': '101', 'Email': 'person@customer.ca', 'Account_Name': {'id': '102'},
                'Email_Opt_Out': False, 'Modified_Time': at},
            ('Accounts', '102'): {'id': '102', 'Account_Name': 'Customer Company'},
            ('Service_Locations', '104'): {'id': '104', 'Linked_Account': {'id': '102'}, 'Modified_Time': at},
            ('CustomModule5002', '501'): {'id': '501', 'Estimate_ID': '601',
                'Account_Name': {'id': '102'}, 'Potential_Name': {'id': '103'}}}
        sent = (NOW - timedelta(days=20)).astimezone(runtime.domain.TORONTO)
        self.comments = [{'comment_id': '801', 'estimate_id': '601', 'comment_type': 'system',
            'transaction_type': 'email', 'operation_type': 'Updated', 'description': 'Estimate emailed to customer',
            'date': sent.date().isoformat(), 'time': sent.strftime('%I:%M %p')}]
        self.books = {'601': {'estimate_id': '601', 'estimate_number': 'EST-001', 'customer_id': '701',
            'zcrm_potential_id': '103', 'status': 'sent', 'created_time': (NOW-timedelta(days=21)).isoformat(),
            'expiry_date': (NOW+timedelta(days=20)).date().isoformat()}}
        self.customer = {'zcrm_account_id': '102', 'language_code': 'fr-ca'}
        self.finance = [deepcopy(self.records[('CustomModule5002', '501')])]
        self.calls = []

    def record(self, module, identifier):
        self.calls.append(('record', module, identifier))
        return deepcopy(self.records[(module, identifier)])

    def list(self, module, fields):
        self.calls.append(('list', module))
        return deepcopy(self.finance)

    def get(self, path, query=None, **kwargs):
        self.calls.append(('get', path))
        if path.startswith('/books/v3/contacts/'): return {'contact': deepcopy(self.customer)}
        if path.startswith('/books/v3/organizations/'): return {'organization': {'time_zone': 'America/Toronto'}}
        if path.endswith('/comments'): return {'comments': deepcopy(self.comments)}
        if path.startswith('/books/v3/estimates/'): return {'estimate': deepcopy(self.books[path.rsplit('/', 1)[-1]])}
        raise AssertionError('Unexpected native GET')

    def mail_search(self, query):
        self.calls.append(('mail_search', query))
        return []


class NativeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.reader = FakeNative()
        self.state = {'deals': {'103': {'contact_id': '101', 'account_id': '102', 'site_id': '104',
            'origin_path': '/en/contact'}}, 'effects': {}}
        self.sender = Mock(); self.sender.history.return_value = []
        def trusted(path, *args):
            if path == control.BASELINE: return {'modules': {}}
            if Path(path).name == 'activation.json': return {'run': 'real-internal-fixture', 'activated_at': ACTIVATED}
            if Path(path).name == 'suppression.json': return {'objects': {}, 'recipients': {}}
            raise AssertionError('Unexpected root input')
        self.trusted = patch.object(runtime, 'trusted_json', side_effect=trusted)
        self.trusted.start()
        self.addCleanup(self.trusted.stop)
        self.adapter = runtime.Adapter(self.reader, self.state, {'records': {'103': {'ownership': 'REAL_NEW'}}}, self.sender)

    def quote(self):
        return self.adapter.quote('103', self.reader.finance[0])

    def test_each_native_observation_refreshes_email_version_and_opt_out(self):
        before = self.adapter.native('103')[4]
        self.reader.records[('Contacts', '101')].update(Email='new@customer.ca', Modified_Time='new-version', Email_Opt_Out=True)
        after = self.adapter.native('103')[4]
        self.assertEqual((before['contact_email'], after['contact_email']), ('person@customer.ca', 'new@customer.ca'))
        self.assertEqual(after['contact_version'], 'new-version')
        self.assertTrue(after['opt_out'])
        self.assertLess(datetime.now(timezone.utc)-datetime.fromisoformat(after['observed_at']), timedelta(seconds=5))
        self.assertEqual(sum(call[:2] == ('record', 'Contacts') for call in self.reader.calls), 2)

    def test_quote_refreshes_native_finance_mapping_before_planning(self):
        cached = {**self.reader.finance[0], 'Estimate_ID': '999'}
        plan, source = self.adapter.quote('103', cached)
        self.assertEqual((plan['state'], source['context']['estimate_id']), ('READY', '601'))
        self.assertEqual(source['native_sent_evidence']['source'], 'BOOKS_SYSTEM_EMAIL_HISTORY')
        self.assertEqual(source['proof']['language'], 'fr')
        self.assertEqual(source['proof']['language_source'], 'native_finance')
        self.assertNotIn(('get', '/books/v3/estimates/999'), self.reader.calls)

    def test_sent_status_and_created_modified_dates_never_replace_send_history(self):
        self.reader.comments = []
        self.reader.books['601'].update(sent_time=NOW.isoformat(), date=NOW.date().isoformat(), last_modified_time=NOW.isoformat())
        with self.assertRaisesRegex(ValueError, 'No recognized native system'):
            self.quote()

    def test_native_history_with_other_transaction_identity_denies(self):
        self.reader.comments[0]['estimate_id'] = '999'
        with self.assertRaisesRegex(ValueError, 'another or missing Estimate identity'):
            self.quote()

    def add_estimate(self, *, deal='103', created=None):
        self.reader.finance.append({'id': '502', 'Estimate_ID': '602', 'Potential_Name': {'id': deal}})
        self.reader.books['602'] = {**self.reader.books['601'], 'estimate_id': '602',
            'created_time': created or (NOW-timedelta(days=19)).isoformat()}

    def test_newer_deal_estimate_suppresses_old_reminder(self):
        self.add_estimate()
        plan, source = self.quote()
        self.assertEqual(plan['state'], 'SUPPRESSED')
        self.assertTrue(source['context']['superseded'])

    def test_newer_other_deal_estimate_does_not_supersede_this_deal(self):
        self.add_estimate(deal='999')
        self.assertEqual(self.quote()[0]['state'], 'READY')
        self.assertNotIn(('get', '/books/v3/estimates/602'), self.reader.calls)

    def test_equal_created_versions_require_owner_choice(self):
        self.add_estimate(created=self.reader.books['601']['created_time'])
        with self.assertRaisesRegex(ValueError, 'Multiple Estimate versions'):
            self.quote()

    def test_wrong_books_account_denies_before_send_plan(self):
        self.reader.customer['zcrm_account_id'] = '999'
        with self.assertRaisesRegex(ValueError, 'different Account'):
            self.quote()

    def test_owner_completed_followup_task_suppresses_external_reminder(self):
        self.state['effects']['task:quote-followup:601'] = {'state': 'verified', 'provider_id': '901'}
        self.reader.records[('Tasks', '901')] = {'id': '901', 'Status': 'Completed'}
        self.assertEqual(self.quote()[0]['state'], 'SUPPRESSED')

    def test_language_uses_native_or_intake_evidence_without_name_guess(self):
        self.assertEqual(runtime.preferred_language({'language_code': 'FR_CA'}, {'origin_path': '/en/contact'}), ('fr', 'native_finance'))
        self.assertEqual(runtime.preferred_language({}, {'origin_path': '/en/contact'}), ('en', 'intake_language'))
        self.assertEqual(runtime.preferred_language({'language_code': 'de'}, {'Contact_Name': 'Jean Dupont'}), (None, None))


class NativeReaderTests(unittest.TestCase):
    def test_exact_id_and_authoritative_success_are_required(self):
        invalid = [
            {'ok': True, 'status': 200, 'data': {'data': [{'id': 'other'}]}},
            {'ok': False, 'status': 200, 'data': {'data': [{'id': '501'}]}},
            {'ok': True, 'status': 503, 'data': {'data': [{'id': '501'}]}},
            {'ok': True, 'status': 200, 'data': []}]
        for response in invalid:
            with self.subTest(response=response):
                client = Mock(); client.request.return_value = response
                with self.assertRaises(ValueError): runtime.NativeReader(client).record('Installations', '501')

    def test_suppression_search_requires_complete_bounded_results_and_recent_time(self):
        client = Mock(); client.request.return_value = {'ok': True, 'status': 200, 'data': {'data': []}}
        reader = runtime.NativeReader(client)
        self.assertEqual(reader.mail_search('sender:person@customer.ca'), [])
        query = client.request.call_args.kwargs['query']
        self.assertEqual(query['start'], 1)
        self.assertGreater(query['receivedTime'], int(datetime.now(timezone.utc).timestamp()*1000))
        client.request.return_value['data']['data'] = [{}]*100
        with self.assertRaisesRegex(ValueError, 'Complete Mail suppression'): reader.mail_search('sender:person@customer.ca')


class RuntimeStateTests(unittest.TestCase):
    def test_no_enabled_real_families_needs_no_sender_state_and_no_provider_reads(self):
        for external, scopes in [(True, []), (False, ['customer.quote.reminder'])]:
            with self.subTest(external=external), tempfile.TemporaryDirectory() as directory:
                policy = {'external_enabled': external, 'real_scopes': scopes,
                          'expires_at': (NOW+timedelta(days=30)).isoformat()}
                client = Mock()
                with patch.object(control, 'ROOT', Path(directory)), patch.object(control, 'policy', return_value=policy), \
                     patch.object(runtime, 'atomic'), patch.object(runtime, 'trusted_json', side_effect=AssertionError('State must not be loaded')), \
                     patch.object(runtime.fcntl, 'flock'), patch.object(runtime.os, 'umask'), \
                     patch('workflow.automation.customer_delivery.RootSender', side_effect=AssertionError('Sender must not be constructed')):
                    result = runtime.run(client)
                self.assertEqual((result['provider_reads'], result['sends_this_cycle'], result['plans']), (0, 0, []))
                client.request.assert_not_called()

    def test_enabled_family_missing_root_state_fails_before_any_provider_read(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            policy = {'external_enabled': True, 'real_scopes': ['customer.quote.reminder'],
                      'expires_at': (NOW+timedelta(days=30)).isoformat()}
            with patch.object(control, 'ROOT', Path(directory)), patch.object(control, 'policy', return_value=policy), \
                 patch.object(runtime, 'trusted_json', side_effect=FileNotFoundError('Root state unavailable')), \
                 patch.object(runtime.fcntl, 'flock'), patch.object(runtime.os, 'umask'), patch.object(runtime, 'atomic'):
                with self.assertRaises(FileNotFoundError): runtime.run(client)
            client.request.assert_not_called()

    def test_expiring_authority_surfaces_deliberate_renewal_attention_without_sends(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = {'external_enabled': True, 'real_scopes': [], 'expires_at': (NOW+timedelta(days=2)).isoformat()}
            with patch.object(control, 'ROOT', Path(directory)), patch.object(control, 'policy', return_value=policy), \
                 patch.object(runtime.fcntl, 'flock'), patch.object(runtime.os, 'umask'), patch.object(runtime, 'atomic'):
                result = runtime.run(Mock())
            self.assertEqual(result['attention'][0]['context'], 'Review customer automation authorization')
            self.assertEqual(result['sends_this_cycle'], 0)


class TodayCommunicationProjectionTests(unittest.TestCase):
    def test_read_only_live_projection_links_native_deal_and_excludes_test_attention(self):
        model = {'scope': 'live', 'read_only': True, 'state': 'READY', 'at': NOW.isoformat(), 'attention': [
            {'context': 'Customer email delivery issue', 'why': 'Recipient needs review',
             'next_action': 'Review contact in CRM', 'identity': '103'},
            {'context': 'Controlled test delivery', 'test_only': True, 'identity': '104'}]}
        view = build_today({}, {}, {}, {}, {'signals': []}, now=NOW, communications=model)
        self.assertEqual(view['attention_count'], 1)
        self.assertIn('/tab/Deals/103', view['sections']['Exceptions'][0]['link'])
        self.assertEqual(view['system'][-1]['state'], 'ACTION REQUIRED')
        self.assertTrue(view['read_only'])

    def test_untrusted_or_mutable_projection_is_rejected(self):
        for model in ({'scope': 'test', 'read_only': True}, {'scope': 'live', 'read_only': False}):
            with self.subTest(model=model), self.assertRaises(ValueError):
                build_today({}, {}, {}, {}, {'signals': []}, now=NOW, communications=model)


if __name__ == '__main__':
    unittest.main()
