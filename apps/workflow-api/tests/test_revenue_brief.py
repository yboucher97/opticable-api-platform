from copy import deepcopy
from datetime import datetime
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from workflow.automation.phase9_form_receipts import FormReceiptLedger
from workflow.automation.revenue_brief import brief, classify_crm, receipt_inquiries, message_identity, draft_queue, quote_groups, current_drafts
from workflow.automation.finance_links import resolve_finance
from workflow.automation.measurement import populations

from test_marketing_attribution import fixture


NOW = datetime.fromisoformat('2026-11-20T08:00:00-05:00')


class RevenueBriefTests(unittest.TestCase):
    def test_nested_existing_observer_metadata_and_future_dates(self):
        s = fixture()
        s['collection'] = {'modules': {'books_invoices': {'state': 'COMPLETE', 'source_at': NOW.isoformat()}}}
        s['books_invoices'][0].update(status='overdue', balance='12.25', due_date='2026-11-19')
        r = brief({'snapshot': s}, {}, [], now=NOW)
        self.assertEqual(r['overdue_by_currency'], {'CAD': '12.25'})
        self.assertEqual(r['overdue_invoices'][0]['days_overdue'], 1)
        s['collection']['modules']['books_invoices']['source_at'] = '2026-11-21T08:00:00-05:00'
        self.assertEqual(brief({'snapshot': s}, {}, [], now=NOW)['overdue_by_currency'], {})

    def test_identical_invoice_amounts_do_not_merge_native_tickets(self):
        s = fixture()
        row = s['books_invoices'][0]
        row.update(status='overdue', balance='287.44', reference_number='ticket-1')
        s['books_invoices'].append({**row, 'invoice_id': '111', 'reference_number': 'ticket-2'})
        result = brief({'snapshot': s}, {}, [], now=NOW)
        self.assertEqual(len(result['overdue_invoices']), 2)

    def test_quote_customer_group_never_adds_unknown_alternatives_or_currencies(self):
        row = {'customer_id': '9', 'currency': 'CAD', 'status': 'sent', 'total': '100', 'id': '11'}
        result = quote_groups([row, {**row, 'id': '12', 'total': '125'},
                               {**row, 'id': '13', 'currency': 'USD', 'total': '300'},
                               {**row, 'id': '14', 'status': 'invoiced', 'total': '500'}])
        self.assertEqual([r['largest_single_quote'] for r in result], ['125', '300'])
        self.assertTrue(all(r['combined_conversion_value'] is None for r in result))
        self.assertIsNone(quote_groups([{**row, 'total': None}])[0]['largest_single_quote'])

    def test_converted_historical_real_lead_is_not_active_pipeline(self):
        r = classify_crm({}, {'Leads': [{'id': '1', 'Last_Name': 'Historic',
             'Lead_Status': 'Qualified', '$converted_detail': {'account': '2'}}]},
             {'Leads': {'1': 'Native account evidence'}}, today=NOW.date())
        self.assertTrue(r['Leads']['records'][0]['converted'])
        self.assertFalse(r['Leads']['records'][0]['include_in_real_pipeline'])

    def test_message_identity_ignores_rounded_numeric_content_ids(self):
        exact = '1795174333401162600'
        self.assertEqual(message_identity(exact, {'messageId': exact}), exact)
        for bad in [int(exact), int(exact) + 1, '1795174333401162601']:
            with self.assertRaises(ValueError):
                message_identity(exact, {'messageId': bad})

    def test_drafts_have_stable_approval_identity_and_no_send_authority(self):
        row = {'kind': 'collection', 'source_ids': ['11', '12'], 'subject': 'Review',
               'body_fr': 'Bonjour', 'body_en': 'Hello', 'recipient': 'owner@example.test'}
        first = draft_queue([row, {**row, 'source_ids': ['12', '11']}])
        self.assertEqual(len(first), 1)
        revised = draft_queue([{**row, 'body_fr': 'Bonjour à nouveau'}])[0]
        self.assertEqual(first[0]['id'], revised['id'])
        self.assertNotEqual(first[0]['content_sha256'], revised['content_sha256'])
        self.assertFalse(first[0]['sent'])
        self.assertFalse(first[0]['provider_draft_created'])

    def test_new_payment_or_source_version_suppresses_collection_draft(self):
        row = {'invoice_id': '11', 'status': 'overdue', 'balance': '10', 'last_modified_time': 'v1'}
        draft = {'kind': 'collection', 'source_ids': ['11'], 'source_versions': {'11': 'v1'}}
        live = {'invoices': {'11': row}, 'estimates': {}}
        sources = {'books_invoices': {'current': True}}
        self.assertEqual(len(current_drafts([draft], live, sources)), 1)
        for changes in [{'last_modified_time': 'v2'}, {'balance': '0'}, {'status': 'paid'}]:
            with self.subTest(changes=changes):
                altered = {'invoices': {'11': {**row, **changes}}, 'estimates': {}}
                self.assertEqual(current_drafts([draft], altered, sources), [])
        self.assertEqual(current_drafts([draft], live, {}), [])

    def test_self_lead_duplicates_do_not_merge_shared_mailbox_contacts(self):
        leads = [{'id': str(i), 'First_Name': 'Owner', 'Last_Name': 'Person',
                  'Company': 'Internal', 'Email': 'owner@example.test'} for i in (1, 2, 3)]
        contacts = [{'id': str(i), 'Full_Name': name, 'Account_Name': {'id': '9'},
                     'Email': 'billing@example.test'} for i, name in [(4, 'Person A'), (5, 'Person B')]]
        r = classify_crm({}, {'Leads': leads, 'Contacts': contacts}, {}, today=NOW.date())
        self.assertEqual(r['Leads']['counts'], {'DUPLICATE': 3})
        self.assertEqual(r['Contacts']['counts'], {'NEEDS VERIFICATION': 2})

    def test_real_evidence_keeps_stale_crm_visible_without_recognizing_revenue(self):
        row = {'id': '1', 'Deal_Name': 'Real job', 'Stage': 'Quote Accepted',
               'Modified_Time': '2026-01-01T10:00:00-05:00'}
        r = classify_crm({}, {'Deals': [row]}, {'Deals': {'1': 'Exact customer email'}}, today=NOW.date())
        result = r['Deals']['records'][0]
        self.assertEqual(result['classification'], 'REAL')
        self.assertTrue(result['stale_crm'])
        self.assertEqual(result['revenue_recognition'], 'NOT_ESTABLISHED_BY_CRM_CLASSIFICATION')

    def test_current_balance_and_actual_payments_are_independent(self):
        snapshot = fixture()
        snapshot['base_currency'] = 'CAD'
        snapshot['books_invoices'][0].update(status='overdue', balance='5840.73',
                                             last_modified_time='native-version')
        snapshot['payments'] = [
            {'payment_id': '53', 'customer_id': '9', 'date': '2026-11-03',
             'payment_status': 'paid', 'bcy_amount': '620.87', 'bcy_refunded_amount': '0'},
            {'payment_id': '54', 'customer_id': '9', 'date': '2026-11-20',
             'payment_status': 'failed', 'bcy_amount': '5840.73', 'bcy_refunded_amount': '0'},
        ]
        observation = {'snapshot': snapshot, 'collection': {'modules': {
            key: {'state': 'COMPLETE', 'source_at': NOW.isoformat()}
            for key in ('books_invoices', 'books_estimate_index', 'payments')}}}
        review = {'observed_at': NOW.isoformat(), 'invoices': {'11': {
            'version': 'old', 'verification': 'previous evidence'}}}
        before = deepcopy(observation)
        report = brief(observation, review, [], now=NOW)
        self.assertEqual(report['overdue_by_currency'], {'CAD': '5840.73'})
        self.assertIsNone(report['overdue_invoices'][0]['verification'])
        self.assertEqual(report['outcomes']['books_recorded_payments']['today']['count'], 0)
        self.assertEqual(report['outcomes']['books_recorded_payments']['month_to_date']['gross'], '620.87')
        self.assertEqual(observation, before)

    def test_stale_data_is_visible_but_never_counted_as_current(self):
        snapshot = fixture()
        snapshot['books_invoices'][0].update(status='overdue', balance='1.05')
        observation = {'snapshot': snapshot, 'collection': {'modules': {
            'books_invoices': {'state': 'COMPLETE', 'source_at': '2026-11-19T23:00:00-05:00'}}}}
        result = brief(observation, {'observed_at': '2026-11-17T00:00:00-05:00',
                                    'top_actions': ['Old action']}, [], now=NOW)
        self.assertEqual(result['top_actions'], [])
        self.assertFalse(result['overdue_invoices'][0]['source_current'])
        self.assertEqual(result['overdue_by_currency'], {})
        self.assertEqual(result['outcomes']['books_recorded_payments'], {})

    def test_crm_test_lineage_stage_and_duplicate_remain_review_only(self):
        snapshot = {
            'accounts': [{'id': '1'}, {'id': '2', 'OptiBrain_Test': True}],
            'customers': [{'contact_id': '3', 'zcrm_account_id': '1', 'contact_persons': [
                {'zcrm_contact_id': '10'}, {'zcrm_contact_id': '13'}]}],
        }
        crm = {
            'Deals': [{'id': '4', 'Deal_Name': 'Unmarked', 'Stage': 'Closed Won',
                       'Account_Name': {'id': '2'}},
                      {'id': '5', 'Deal_Name': 'Old', 'Stage': 'Quote Accepted',
                       'Modified_Time': '2026-04-01T09:00:00-04:00'},
                      {'id': '6', 'Deal_Name': 'Unverified win', 'Stage': 'Closed Won'}],
            'Contacts': [{'id': str(i), 'Full_Name': 'Same Contact', 'Account_Name': {'id': '1'},
                          'Email': 'same@example.test'} for i in (10, 11)] + [
                             {'id': '13', 'Full_Name': 'Different person', 'Account_Name': {'id': '1'}}],
            'Tasks': [{'id': '8', 'Subject': 'Follow up', 'What_Id': {'id': '4'}, '$se_module': 'Deals'}],
        }
        result = classify_crm(snapshot, crm, {'Deals': {'4': 'does not override TEST'}}, today=NOW.date())
        self.assertEqual(result['Deals']['counts'], {'TEST': 1, 'STALE': 1, 'NEEDS VERIFICATION': 1})
        self.assertFalse(any(r['include_in_real_pipeline'] for r in result['Deals']['records']))
        self.assertEqual(result['Tasks']['counts'], {'TEST': 1})
        self.assertEqual(result['Contacts']['counts'], {'DUPLICATE': 2, 'REAL': 1})

    def test_receipt_suppression_and_scope_questions(self):
        def receipt(rid, company, *, test=False, quarantine=False):
            return {'event_id': rid, 'provider_message_id': rid, 'occurred_at': NOW.isoformat(),
                    'test_only': test, 'quarantined': quarantine,
                    'evidence_json': json.dumps({'fields': {'company': company,
                                                            'timeline': 'immédiat',
                                                            'service': 'Wi-Fi, intercom'}})}
        candidates = receipt_inquiries([receipt('10', 'OPTIBRAIN TEST — Demo'),
                                        receipt('11', 'Test', test=True),
                                        receipt('12', 'Quarantined', quarantine=True),
                                        receipt('13', 'Reviewed vendor pitch'),
                                        receipt('14', 'Actual customer')], {'13'})
        self.assertEqual([r['id'] for r in candidates], ['14'])
        self.assertTrue(candidates[0]['urgent'])
        self.assertIn('intercom', candidates[0]['next_action'])

    def test_receipt_readonly_does_not_initialize(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'receipts.db'
            ledger = FormReceiptLedger(path)
            with self.assertRaises(sqlite3.OperationalError):
                ledger.list(read_only=True)
            self.assertFalse(path.exists())
            ledger.initialize()
            before = path.read_bytes()
            self.assertEqual(ledger.list(read_only=True), [])
            self.assertEqual(path.read_bytes(), before)

    def test_conflicting_finance_parents_never_attribute_even_to_same_deal(self):
        snapshot = fixture()
        invoice = snapshot['books_invoices'][0]
        invoice['estimate_id'] = '8'
        estimate = snapshot['books_estimate_index']['8']
        snapshot['books_estimate_index']['18'] = {**estimate, 'estimate_id': '18', 'invoice_ids': ['11']}
        result = resolve_finance(invoice, 'invoices', populations(snapshot)[0])
        self.assertTrue(result['conflict'])
        self.assertEqual(result['deal_id'], '')

    def test_recurring_customer_disagreement_withholds_direct_attribution(self):
        snapshot = fixture()
        invoice = snapshot['books_invoices'][0]
        invoice['recurring_invoice_id'] = '80'
        snapshot['profiles'] = [{'recurring_invoice_id': '80', 'customer_id': '90'}]
        result = resolve_finance(invoice, 'invoices', populations(snapshot)[0])
        self.assertTrue(result['conflict'])
        self.assertEqual(result['deal_id'], '')
