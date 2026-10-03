from copy import deepcopy
import unittest
from test_marketing_attribution import fixture
from workflow.automation.measurement import audit_lineage, populations, finance_link
from workflow.automation.marketing_attribution import build_marketing, acquisition, conversion_plan


class MeasurementTests(unittest.TestCase):
    def test_exact_native_finance_and_protected_read_only(self):
        s=fixture();before=deepcopy(s);a=audit_lineage(s,protected={'Accounts':{'1'}})
        self.assertEqual(a['coverage']['invoices']['deal_linked'],1)
        self.assertEqual(a['coverage']['invoices']['protected_account_references'],1)
        self.assertEqual(a['financial_links']['invoices']['11']['site_ids'],['5'])
        self.assertEqual(s,before);self.assertFalse(a['historical_mutations'])
    def test_missing_deal_does_not_borrow_only_customer_deal(self):
        s=fixture();s['finance_invoices'][0]['Potential_Name']=None
        a=audit_lineage(s);self.assertEqual(a['coverage']['invoices']['deal_linked'],0)
        self.assertEqual(a['coverage']['invoices']['classifications'],{'LINKABLE WITH SAFE EXISTING ID':1})
    def test_exact_invoice_estimate_relation_can_supply_deal(self):
        s=fixture();s['finance_invoices'][0]['Potential_Name']=None;s['books_invoices'][0]['estimate_id']='8'
        self.assertEqual(audit_lineage(s)['coverage']['invoices']['deal_linked'],1)
    def test_estimate_different_customer_is_quarantined(self):
        s=fixture();s['books_invoices'][0]['estimate_id']='8';s['books_estimate_index']['8']['customer_id']='99'
        a=audit_lineage(s);self.assertEqual(a['coverage']['invoices']['classifications'],{'AMBIGUOUS':1})
        self.assertEqual(a['financial_links']['invoices']['11']['account_id'],'')
    def test_wrong_site_parent_not_authoritative(self):
        s=fixture();s['sites'][0]['Linked_Account']={'id':'99'}
        self.assertTrue(audit_lineage(s)['financial_links']['invoices']['11']['conflict'])
    def test_test_exclusion_closes_all_relationships(self):
        for node in ('accounts','leads','deals'):
            with self.subTest(node=node):
                s=fixture();s[node][0]['OptiBrain_Test']=True
                self.assertEqual(audit_lineage(s)['coverage']['invoices']['total'],0)
    def test_recurring_no_native_site_link_remains_unlinked(self):
        s=fixture();s['profiles']=[{'recurring_invoice_id':'12','customer_id':'9'}]
        self.assertEqual(audit_lineage(s)['coverage']['recurring_profiles']['unlinked'],1)
    def test_paid_organic_and_google_ads_not_grouped_together(self):
        s=fixture();s['leads'][0]['First_Medium']='cpc';s['leads'].append({**s['leads'][0],'id':'13','First_Medium':'organic'})
        self.assertEqual(len({g['medium'] for g in build_marketing(s)['groups']}),3) # Deal's unrecorded medium stays unknown.
    def test_missing_source_never_assumed_direct(self):
        self.assertEqual(acquisition({})['source'],'UNATTRIBUTED')
    def test_export_identity_version_stable_replay_stays_off(self):
        row={'id':'3','Google_GCLID':'SYNTHETIC','Outcome_Time':'2026-10-03T01:00:00Z'}
        a=conversion_plan(row,'qualified_lead');b=conversion_plan(row,'qualified_lead')
        self.assertEqual(a['key'],b['key']);self.assertEqual(a['version'],1);self.assertFalse(a['external_upload'])
    def test_contact_consent_and_wrong_timing_cannot_export(self):
        a=conversion_plan({'id':'3','Google_GCLID':'TEST','Created_Time':'2026-10-03'},'qualified_lead',
                          destination={'verified':True,'conversion_action':'1'},consent={'contact':True})
        self.assertEqual(a['readiness'],'PARTIAL');self.assertEqual(len(a['reasons']),2)
    def test_url_and_private_ids_not_in_source(self):
        a=acquisition({'First_Source':'https://example.test/?email=private@example.test','First_Medium':'person@example.test'})
        self.assertEqual(a['source'],'UNATTRIBUTED');self.assertEqual(a['medium'],'Not recorded')
