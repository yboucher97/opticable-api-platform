from copy import deepcopy
from datetime import datetime, timezone
import unittest

from workflow.automation.lifecycle import site_fields
from workflow.automation.operational_lifecycle import (
    accepted_work_plan, durable_service_plan, installation_context,
    installation_progress_plan, invoice_progress_plan, normalized_site_key,
    operational_site_match, return_visit_plan, support_case_plan,
)


class OperationalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.address = {'street': '123 Example Street', 'unit': 'Suite 002',
                        'city': 'Montréal', 'province': 'QC', 'postal_code': 'H1A 1A1', 'country': 'Canada'}
        self.account = {'id': '1', 'Account_Name': 'TEST Company'}
        self.contact = {'id': '2', 'Last_Name': 'TEST Person', 'Account_Name': {'id': '1'}}
        self.site = {'id': '3', 'Name': 'TEST Site', 'Linked_Account': {'id': '1'}, **site_fields(self.address)}
        self.deal = {'id': '4', 'Deal_Name': 'TEST Project', 'Account_Name': {'id': '1'},
                     'Contact_Name': {'id': '2'}, 'Service_Location': {'id': '3'},
                     'Service_Types': 'Structured Cabling', 'Stage': 'Contract Signed'}
        self.service = {'id': '5', 'Name': 'Existing cabling system', 'Service_Type': 'Cabling Installation',
                        'Linked_Service_Location': {'id': '3'}, 'Linked_Deal': {'id': '4'},
                        'Service_Stage': 'Ready for Scheduling'}
        self.installation = {'id': '6', 'Name': 'TEST Installation', 'Linked_Service': {'id': '5'},
                             'Installation_Status': 'Requested', 'Instructions_Notes': 'Use side entrance'}
        self.estimate = {'transaction_id': '7', 'status': 'accepted', 'account_id': '1',
                         'deal_id': '4', 'site_id': '3'}
        self.entities = dict(services=[self.service], sites=[self.site], accounts=[self.account],
                             deals=[self.deal], contacts=[self.contact])
        self.context = installation_context(self.installation, **self.entities)
        self.now = datetime(2026, 10, 6, 18, tzinfo=timezone.utc)

    def accepted(self, **overrides):
        values = dict(estimate=self.estimate, deal=self.deal, account=self.account,
                      contact=self.contact, site=self.site, services=[self.service])
        return accepted_work_plan(**{**values, **overrides})

    def progress(self, **overrides):
        record = {**self.installation, 'Installation_Status': 'Completed', 'Completion_Notes': 'Tested all drops'}
        values = dict(services=[self.service], owner_trigger=True, completed_at='2026-10-06T17:30:00Z',
                      mutable_service_ids={'5'}, now=self.now)
        return installation_progress_plan(record, self.context, **{**values, **overrides})

    def invoice(self, **overrides):
        native = {'Invoice_ID': '8', 'Account_Name': {'id': '1'}, 'Potential_Name': {'id': '4'}}
        books = {'invoice_id': '8', 'invoice_number': 'TEST-8', 'status': 'sent',
                 'total': 100, 'balance': 100, 'due_date': '2026-10-05'}
        values = dict(native=native, books=books, deals=[self.deal], sites=[self.site],
                      services=[self.service], now=self.now)
        return invoice_progress_plan(**{**values, **overrides})

    def test_site_format_variations_reuse_without_fuzzy_merging(self):
        equivalent = {**self.address, 'street': '123 EXAMPLE St.', 'unit': 'Unit 2',
                      'city': 'Montreal', 'province': 'Québec', 'postal_code': 'h1a1a1', 'country': 'CA'}
        self.assertEqual(normalized_site_key(equivalent), normalized_site_key(self.address))
        self.assertEqual(operational_site_match([self.site], '1', equivalent)['decision'], 'REUSE')

    def test_minor_street_spelling_collision_requires_human(self):
        for street in ('123 Exampel Street', '123 Example North Street', '123-A Example Street'):
            with self.subTest(street=street):
                result = operational_site_match([self.site], '1', {**self.address, 'street': street})
                self.assertEqual(result['decision'], 'HUMAN')

    def test_units_distinct_and_missing_unit_does_not_reuse(self):
        for unit in ('Suite 3', 'Suite 2A'):
            with self.subTest(unit=unit):
                self.assertEqual(operational_site_match([self.site], '1', {**self.address, 'unit': unit})['decision'], 'CREATE')
        self.assertNotEqual(normalized_site_key({**self.address, 'unit': '2-A'}),
                            normalized_site_key({**self.address, 'unit': '2A'}))
        self.assertEqual(operational_site_match([self.site], '1', {**self.address, 'unit': ''})['decision'], 'HUMAN')

    def test_unit_hyphen_slash_variants_never_silently_merge(self):
        for unit, other in (('2-A', '2A'), ('5/12', '512'), ('5-12', '5 12')):
            with self.subTest(unit=unit, other=other):
                address = {**self.address, 'unit': unit}
                site = {**self.site, **site_fields(address)}
                self.assertNotEqual(normalized_site_key(address), normalized_site_key({**address, 'unit': other}))
                self.assertEqual(operational_site_match([site], '1', {**address, 'unit': other})['decision'], 'HUMAN')

    def test_other_account_never_reuses_site(self):
        self.assertEqual(operational_site_match([self.site], '9', self.address)['decision'], 'CREATE')

    def test_duplicate_or_incomplete_site_inventory_holds(self):
        for rows in ([self.site, {**self.site, 'id': '9'}], [{**self.site, 'Service_Location_Address_Zip_Postal_Code': ''}]):
            with self.subTest(rows=rows):
                self.assertEqual(operational_site_match(rows, '1', self.address)['decision'], 'HUMAN')

    def test_invalid_address_never_creates_site(self):
        for changes in ({'province': ''}, {'street': 'Example Street'}, {'country': 'USA'}, {'postal_code': ''}):
            with self.subTest(changes=changes):
                self.assertEqual(operational_site_match([], '1', {**self.address, **changes})['decision'], 'HUMAN')

    def test_durable_service_reused_across_deals_without_overwriting_old_deal(self):
        old = {**self.service, 'Linked_Deal': {'id': '99'}}
        before = deepcopy(old)
        plan = self.accepted(services=[old])
        self.assertEqual(plan['services'][0]['decision'], 'REUSE')
        self.assertEqual(old, before)
        self.assertTrue(plan['preserve_existing_service_deal'])

    def test_new_service_kind_created_but_duplicate_mapping_rejected(self):
        plan = durable_service_plan('Structured Cabling, CCTV', '3', [self.service])
        self.assertEqual([row['decision'] for row in plan['services']], ['REUSE', 'CREATE'])
        for requested in ('CCTV, CCTV', 'Something uncertain', ''):
            with self.subTest(requested=requested):
                self.assertEqual(durable_service_plan(requested, '3', [])['decision'], 'HUMAN')

    def test_generic_other_does_not_merge_distinct_services(self):
        ambiguous = {**self.service, 'Service_Type': 'Other', 'Name': 'Managed installation'}
        self.assertEqual(durable_service_plan('PTP Link', '3', [ambiguous])['decision'], 'HUMAN')
        ptp = {**ambiguous, 'Name': 'PTP Link — TEST Site'}
        plan = durable_service_plan('PTP Link, Managed Network', '3', [ptp])
        self.assertEqual([row['decision'] for row in plan['services']], ['REUSE', 'CREATE'])

    def test_duplicate_or_suppressed_service_does_not_create_another(self):
        for rows in ([self.service, {**self.service, 'id': '9'}], [{**self.service, 'Service_Stage': 'Suspended'}]):
            with self.subTest(rows=rows):
                self.assertEqual(durable_service_plan('Structured Cabling', '3', rows)['decision'], 'HUMAN')

    def test_accepted_work_requires_all_relationships_and_finance_evidence(self):
        mutations = [dict(estimate={**self.estimate, 'status': 'sent'}),
                     dict(estimate={**self.estimate, 'transaction_id': ''}),
                     dict(estimate={**self.estimate, 'account_id': '9'}),
                     dict(deal={**self.deal, 'Contact_Name': {'id': '9'}}),
                     dict(contact={**self.contact, 'Account_Name': {'id': '9'}}),
                     dict(site={**self.site, 'Linked_Account': {'id': '9'}})]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertEqual(self.accepted(**mutation)['decision'], 'HUMAN')

    def test_accepted_work_does_not_schedule_send_or_write_money(self):
        plan = self.accepted()
        self.assertEqual(plan['installation'], 'UNSCHEDULED')
        self.assertEqual(plan['contract'], 'PREPARE_ONLY')
        self.assertFalse(plan['external_sends'])
        self.assertFalse(plan['financial_writes'])
        self.assertNotIn('Amount', plan)

    def test_rejected_or_protected_accepted_work_holds(self):
        self.assertEqual(self.accepted(deal={**self.deal, 'Stage': 'Closed Lost'})['decision'], 'HUMAN')
        for protected in ({'1'}, {'3'}, {'4'}, {'5'}):
            with self.subTest(protected=protected):
                self.assertEqual(self.accepted(protected_ids=protected)['decision'], 'HUMAN')

    def test_installation_context_derived_through_service_native_links(self):
        self.assertEqual(self.context['decision'], 'PREPARE_INTERNAL')
        self.assertEqual((self.context['account_id'], self.context['deal_id'], self.context['site_id']), ('1', '4', '3'))
        self.assertEqual(self.context['service_ids'], ['5'])

    def test_installation_join_links_prove_all_services_at_same_site(self):
        camera = {**self.service, 'id': '9', 'Service_Type': 'Camera Installation'}
        link = {'Linked_Installation': {'id': '6'}, 'Linked_Service': {'id': '9'}}
        plan = installation_context(self.installation, **{**self.entities, 'services': [self.service, camera]}, links=[link])
        self.assertEqual(plan['service_ids'], ['5', '9'])
        camera['Linked_Service_Location'] = {'id': '10'}
        self.assertEqual(installation_context(self.installation, **{**self.entities, 'services': [self.service, camera]}, links=[link])['decision'], 'HUMAN')

    def test_existing_service_old_deal_needs_explicit_root_lineage(self):
        old = {**self.service, 'Linked_Deal': {'id': '99'}}
        entities = {**self.entities, 'services': [old]}
        self.assertEqual(installation_context(self.installation, **entities)['decision'], 'HUMAN')
        self.assertEqual(installation_context(self.installation, **entities, deal_id='4')['decision'], 'PREPARE_INTERNAL')

    def test_wrong_installation_account_contact_or_protected_lineage_holds(self):
        for changes in ({'contacts': [{**self.contact, 'Account_Name': {'id': '9'}}]},
                        {'deals': [{**self.deal, 'Service_Location': {'id': '9'}}]},
                        {'protected_ids': {'6'}}, {'services': []}):
            with self.subTest(changes=changes):
                self.assertEqual(installation_context(self.installation, **{**self.entities, **changes})['decision'], 'HUMAN')

    def test_scheduling_is_human_and_timezone_aware(self):
        record = {**self.installation, 'Installation_Status': 'Scheduled'}
        self.assertEqual(installation_progress_plan(record, self.context)['decision'], 'HUMAN')
        record['Scheduled_Date'] = '2026-11-03T14:00:00Z'
        plan = installation_progress_plan(record, self.context)
        self.assertEqual(plan['scheduled_local'], '2026-11-03T09:00:00-05:00')
        self.assertEqual(plan['patches'], [])
        self.assertNotIn('Assigned_To', plan)

    def test_blocked_and_return_visit_require_reason_and_never_activate(self):
        for status in ('Failed', 'Revisit Required'):
            with self.subTest(status=status):
                empty = {**self.installation, 'Installation_Status': status, 'Instructions_Notes': ''}
                self.assertEqual(installation_progress_plan(empty, self.context)['decision'], 'HUMAN')
                record = {**empty, 'Instructions_Notes': 'No access'}
                plan = installation_progress_plan(record, self.context)
                self.assertFalse(plan['activate_services'])
                self.assertEqual(plan['patches'], [])

    def test_cancelled_visit_does_not_activate_services(self):
        result = installation_progress_plan({**self.installation, 'Installation_Status': 'Cancelled'}, self.context)
        self.assertFalse(result['activate_services'])

    def test_completion_needs_owner_evidence_and_mutable_service_lineage(self):
        for changes in ({'owner_trigger': False}, {'completed_at': None}, {'mutable_service_ids': set()},
                        {'completed_at': '2026-10-07T17:30:00Z'}, {'completed_at': '2026-10-06T17:30:00'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.progress(**changes)['decision'], 'HUMAN')
        record = {**self.installation, 'Installation_Status': 'Completed', 'Completion_Notes': ''}
        self.assertEqual(installation_progress_plan(record, self.context, owner_trigger=True)['decision'], 'HUMAN')

    def test_completion_records_dates_and_billing_attention_without_financial_write(self):
        plan = self.progress()
        self.assertEqual(plan['patches'][0]['patch'], {'Service_Stage': 'Active',
                         'OptiBrain_Installed_On': '2026-10-06', 'OptiBrain_Last_Service_On': '2026-10-06'})
        self.assertEqual(plan['attention'], 'CREATE / SEND INVOICE')
        self.assertFalse(plan['financial_writes'])
        self.assertFalse(plan['external_sends'])

    def test_existing_installed_date_preserved_and_replay_is_noop(self):
        old = {**self.service, 'OptiBrain_Installed_On': '2025-01-02'}
        plan = self.progress(services=[old])
        self.assertNotIn('OptiBrain_Installed_On', plan['patches'][0]['patch'])
        current = {**old, **plan['patches'][0]['patch']}
        replay = self.progress(services=[current], mutable_service_ids=set())
        self.assertEqual(replay['patches'], [])
        self.assertEqual(plan['effect_key'], replay['effect_key'])

    def test_completion_cannot_reactivate_suppressed_service(self):
        for status in ('Cancelled', 'Suspended'):
            with self.subTest(status=status):
                self.assertEqual(self.progress(services=[{**self.service, 'Service_Stage': status}])['decision'], 'HUMAN')

    def test_existing_active_reference_service_is_read_only_on_new_visit(self):
        old = {**self.service, 'Service_Stage': 'Active', 'OptiBrain_Installed_On': '2025-01-02',
               'OptiBrain_Last_Service_On': '2025-01-02', 'Linked_Deal': {'id': '99'}}
        before = deepcopy(old)
        plan = self.progress(services=[old], mutable_service_ids=set())
        self.assertEqual(plan['decision'], 'OBSERVE')
        self.assertEqual(plan['patches'], [])
        self.assertEqual(plan['preserved_reference_service_ids'], ['5'])
        self.assertEqual(old, before)

    def test_return_visit_preserves_original_and_reuses_services(self):
        record = {**self.installation, 'Installation_Status': 'Revisit Required', 'Instructions_Notes': 'Missing equipment'}
        before = deepcopy(record)
        plan = return_visit_plan(record, self.context, transition_id='crm:transition:1', owner_trigger=True)
        self.assertEqual(plan['row']['Installation_Status'], 'Requested')
        self.assertNotIn('Scheduled_Date', plan['row'])
        self.assertFalse(plan['create_services'])
        self.assertTrue(plan['preserve_original'])
        self.assertEqual(record, before)
        visits = {plan['effect_key']: {'installation_id': '9', 'parent_installation_id': '6', 'deal_id': '4', 'service_ids': ['5']}}
        replay = return_visit_plan(record, self.context, transition_id='crm:transition:1', known_visits=visits, owner_trigger=True)
        self.assertEqual(replay['decision'], 'REUSE')
        self.assertEqual(replay['record_id'], '9')

    def test_return_visit_wrong_existing_effect_or_unverified_trigger_holds(self):
        record = {**self.installation, 'Installation_Status': 'Revisit Required'}
        self.assertEqual(return_visit_plan(record, self.context, transition_id='1')['decision'], 'HUMAN')
        plan = return_visit_plan(record, self.context, transition_id='1', owner_trigger=True)
        visits = {plan['effect_key']: {'installation_id': '9', 'parent_installation_id': '6', 'deal_id': '99', 'service_ids': ['5']}}
        self.assertEqual(return_visit_plan(record, self.context, transition_id='1', owner_trigger=True, known_visits=visits)['decision'], 'HUMAN')

    def test_invoice_native_association_and_overdue_attention(self):
        plan = self.invoice()
        self.assertEqual(plan['attention'], 'INVOICE OVERDUE')
        self.assertEqual(plan['financial_state'], 'UNPAID')
        self.assertEqual(plan['site_id'], '3')
        self.assertFalse(plan['financial_writes'])
        self.assertFalse(plan['external_sends'])

    def test_invoice_wrong_provider_or_account_deal_association_holds(self):
        books = {'invoice_id': '8', 'status': 'paid', 'total': 100, 'balance': 0}
        for changes in ({'invoice_id': '9'}, {'zcrm_potential_id': '9'}, {'zcrm_account_id': '9'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.invoice(books={**books, **changes})['decision'], 'HUMAN')
        self.assertEqual(self.invoice(deals=[{**self.deal, 'Account_Name': {'id': '9'}}])['decision'], 'HUMAN')

    def test_payment_progression_observes_books_not_zero_balance_guess(self):
        books = {'invoice_id': '8', 'status': 'paid', 'total': 100, 'balance': 0}
        paid = self.invoice(books=books)
        self.assertEqual(paid['financial_state'], 'SATISFIED')
        self.assertTrue(paid['clear_billing_attention'])
        zero = self.invoice(books={**books, 'status': 'sent'})
        self.assertEqual(zero['financial_state'], 'UNCONFIRMED')
        self.assertFalse(zero['clear_billing_attention'])
        partial = self.invoice(books={**books, 'status': 'partially_paid', 'balance': 10, 'due_date': '2026-10-10'})
        self.assertEqual(partial['financial_state'], 'PARTIAL')

    def test_bad_amount_balance_or_due_date_never_advances_financial_state(self):
        books = {'invoice_id': '8', 'status': 'sent', 'total': 100, 'balance': 100, 'due_date': '2026-10-05'}
        for changes in ({'total': 'NaN'}, {'balance': -1}, {'balance': 101}, {'due_date': 'invalid'},
                        {'status': 'paid'}, {'status': 'unknown'}, {'due_date': None}):
            with self.subTest(changes=changes):
                self.assertEqual(self.invoice(books={**books, **changes})['decision'], 'HUMAN')

    def test_invoice_existing_service_reuse_uses_root_linkage_without_reparenting(self):
        old = {**self.service, 'Linked_Deal': {'id': '99'}}
        plan = self.invoice(services=[old], service_ids=['5'])
        self.assertEqual(plan['decision'], 'OBSERVE')
        self.assertEqual(plan['service_ids'], ['5'])
        self.assertEqual(old['Linked_Deal'], {'id': '99'})
        self.assertEqual(self.invoice(services=[old], service_ids=['9'])['decision'], 'HUMAN')

    def test_invoice_protected_or_multiple_site_context_has_no_progression(self):
        self.assertEqual(self.invoice(protected_ids={'4'})['decision'], 'HUMAN')
        self.assertEqual(self.invoice(services=[{**self.service, 'Linked_Service_Location': {'id': '9'}}])['decision'], 'HUMAN')
        self.assertEqual(self.invoice(deals=[{**self.deal, 'Service_Location': {'id': 'malformed'}}])['decision'], 'HUMAN')

    def test_support_case_keeps_native_relationships_and_root_site_service_context(self):
        issue = {'subject': 'Camera image issue', 'description': 'Image is blurry', 'emergency': False}
        plan = support_case_plan(issue, self.context, source_event_id='support:1')
        self.assertEqual(plan['row']['Account_Name'], {'id': '1'})
        self.assertEqual(plan['row']['Related_To'], {'id': '2'})
        self.assertEqual(plan['row']['Deal_Name'], {'id': '4'})
        self.assertEqual(plan['support_context']['site_id'], '3')
        self.assertEqual(plan['support_context']['service_ids'], ['5'])
        self.assertNotIn('Priority', plan['row'])
        self.assertIn('TEST Site', plan['row']['Description'])
        self.assertFalse(plan['external_sends'])

    def test_support_requires_human_emergency_decision_and_protected_safety(self):
        for issue in ({'subject': 'URGENT', 'description': 'Unknown problem'},
                      {'subject': 'Normal', 'description': 'Issue', 'emergency': True}):
            with self.subTest(issue=issue):
                self.assertEqual(support_case_plan(issue, self.context, source_event_id='support:1')['decision'], 'HUMAN')
        issue = {'subject': 'Normal', 'description': 'Issue', 'emergency': False}
        self.assertEqual(support_case_plan(issue, self.context, source_event_id='support:1', protected_ids={'1'})['decision'], 'HUMAN')

    def test_support_replay_reuses_case_and_wrong_association_holds(self):
        issue = {'subject': 'Normal', 'description': 'Issue', 'emergency': False}
        plan = support_case_plan(issue, self.context, source_event_id='support:1')
        case = {'id': '9', **plan['row'], '_source_effect_key': plan['effect_key']}
        self.assertEqual(support_case_plan(issue, self.context, source_event_id='support:1', existing_cases=[case])['decision'], 'REUSE')
        wrong = {**case, 'Account_Name': {'id': '99'}}
        self.assertEqual(support_case_plan(issue, self.context, source_event_id='support:1', existing_cases=[wrong])['decision'], 'HUMAN')
        self.assertEqual(support_case_plan(issue, self.context, source_event_id='support:1', existing_cases=[case, {**case, 'id': '10'}])['decision'], 'HUMAN')


if __name__ == '__main__':
    unittest.main()
