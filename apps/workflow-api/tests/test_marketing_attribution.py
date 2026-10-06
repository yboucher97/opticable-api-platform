from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest
from workflow.automation.marketing_attribution import build_marketing, acquisition, conversion_plan, outcome, render_marketing
from workflow.automation.lifecycle import attribution
from workflow.automation.business_observation import NativeReader, collect_marketing


def fixture():
    return {'observed_at':'2026-10-03T04:00:00+00:00',
        'accounts':[{'id':'1'}], 'contacts':[{'id':'2','Account_Name':{'id':'1'},'First_Source':'google'}],
        'leads':[{'id':'3','First_Source':'google','First_Campaign':'acquisition','Last_Source':'referral',
            'Last_Campaign':'returning','Lead_Status':'Qualified','$converted':True,
            '$converted_detail':{'contact':'2','account':'1','deal':'4'}}],
        'deals':[{'id':'4','Account_Name':{'id':'1'},'Contact_Name':{'id':'2'},'Stage':'Closed Won',
            'First_Source':'google','First_Campaign':'acquisition','Last_Source':'referral'}],
        'sites':[{'id':'5','Linked_Account':{'id':'1'}}],
        'services':[{'id':'6','Linked_Service_Location':{'id':'5'},'Linked_Deal':{'id':'4'}}],
        'finance_estimates':[{'id':'7','Estimate_ID':'8','Account_Name':{'id':'1'},'Potential_Name':{'id':'4'}}],
        'books_estimate_index':{'8':{'estimate_id':'8','customer_id':'9','status':'accepted'}},
        'customers':[{'contact_id':'9','zcrm_account_id':'1'}],
        'finance_invoices':[{'id':'10','Invoice_ID':'11','Account_Name':{'id':'1'},'Potential_Name':{'id':'4'}}],
        'books_invoices':[{'invoice_id':'11','customer_id':'9','total':'200','balance':'0','status':'paid','currency_code':'CAD'}],
        'profiles':[], 'generated':{}}


class MarketingTests(unittest.TestCase):
    def group(self, view, source='google'):
        return next(r for r in view['groups'] if r['source']==source)
    def test_a_google_like_full_native_finance_lineage(self):
        r=build_marketing(fixture());g=self.group(r)
        self.assertEqual([g[k] for k in ('leads','qualified_leads','deals','estimates','accepted_estimates')],[1]*5)
        self.assertEqual(g['invoice_value'],{'CAD':'200'});self.assertEqual(g['paid_invoice_value'],{'CAD':'200'})
        self.assertFalse(r['external_conversion_upload']);self.assertFalse(r['financial_writes'])
    def test_b_organic_referral_lifecycle(self):
        for source in ('google organic','referral','yellow pages','linkedin','instagram','direct'):
            with self.subTest(source=source):
                s=fixture()
                for row in s['leads']+s['deals']:row['First_Source']=source
                self.assertEqual(self.group(build_marketing(s),source)['invoice_value'],{'CAD':'200'})
    def test_c_first_touch_preserved_returning_last_updates(self):
        old={'First_Source':'google','First_Campaign':'original','Last_Source':'google'}
        patch=attribution({'attribution':{'first_source':'meta','first_campaign':'new','last_source':'meta','last_campaign':'new'}},old)
        self.assertNotIn('First_Source',patch);self.assertNotIn('First_Campaign',patch);self.assertEqual(patch['Last_Source'],'meta')
        self.assertEqual(acquisition({**old,**patch})['source'],'google')
    def test_d_cross_site_origin_does_not_replace_acquisition(self):
        row={'First_Source':'google','First_Site':'ai.opticable.ca','Last_Source':'referral','Last_Site':'opticable.ca'}
        self.assertEqual(acquisition(row)['source'],'google');self.assertEqual(acquisition(row)['last_source'],'referral')
    def test_e_recurring_revenue_retains_original_service_deal(self):
        s=fixture();s['profiles']=[{'recurring_invoice_id':'12','customer_id':'9'}]
        s['books_invoices'][0]['recurring_invoice_id']='12';s['generated']={'12':deepcopy(s['books_invoices'])}
        s['books_invoices'].append({**s['books_invoices'][0],'invoice_id':'13','total':'200'})
        g=self.group(build_marketing(s));self.assertEqual(g['leads'],1);self.assertEqual(g['recurring_invoice_value'],{'CAD':'400'})
    def test_f_replayed_outcomes_stable_no_external_upload(self):
        a=build_marketing(fixture());b=build_marketing(fixture());self.assertEqual(a,b)
        self.assertEqual(len({x['key'] for x in a['outcomes']}),len(a['outcomes']))
        self.assertTrue(all(x['external_upload'] is False for x in a['outcomes']))
    def test_native_account_conflict_never_assigns_revenue(self):
        s=fixture();s['customers'][0]['zcrm_account_id']='90';r=build_marketing(s)
        self.assertEqual(self.group(r)['invoice_value'],{});self.assertIn('Invoice customer/Account needs reconciliation',r['problems'])
    def test_no_deal_link_never_uses_only_account_campaign(self):
        s=fixture();s['finance_invoices'][0]['Potential_Name']=None
        self.assertEqual(self.group(build_marketing(s),'UNATTRIBUTED')['invoice_value'],{'CAD':'200'})
    def test_multiple_campaigns_under_customer_not_guessed(self):
        s=fixture();s['deals'].append({**s['deals'][0],'id':'14','First_Source':'meta'})
        s['finance_invoices'][0]['Potential_Name']=None
        self.assertEqual(self.group(build_marketing(s),'UNATTRIBUTED')['invoice_value'],{'CAD':'200'})
    def test_conflicting_native_deal_denied(self):
        s=fixture();s['books_invoices'][0]['zcrm_potential_id']='90';r=build_marketing(s)
        self.assertEqual(self.group(r)['invoice_value'],{});self.assertIn('Invoice Deal association conflicts',r['problems'])
    def test_duplicate_finance_identity_denied(self):
        s=fixture();s['finance_invoices'].append({**s['finance_invoices'][0],'id':'14'})
        with self.assertRaises(ValueError):build_marketing(s)
    def test_invoice_currency_not_combined(self):
        s=fixture();s['books_invoices'].append({**s['books_invoices'][0],'invoice_id':'13','currency_code':'USD','zcrm_potential_id':'4'})
        self.assertEqual(self.group(build_marketing(s))['invoice_value'],{'CAD':'200','USD':'200'})
    def test_partial_balance_not_called_cash_or_paid_revenue(self):
        s=fixture();s['books_invoices'][0].update(balance='100',status='partially_paid')
        g=self.group(build_marketing(s));self.assertEqual(g['paid_invoice_value'],{});self.assertEqual(g['invoice_value'],{'CAD':'200'})
    def test_draft_and_void_excluded(self):
        for status in ('draft','void'):
            with self.subTest(status=status):
                s=fixture();s['books_invoices'][0]['status']=status
                self.assertEqual(self.group(build_marketing(s))['invoice_value'],{})
    def test_missing_currency_denies_reporting(self):
        s=fixture();s['books_invoices'][0].pop('currency_code')
        with self.assertRaises(ValueError):build_marketing(s)
    def test_test_account_propagates_all_counts_and_value(self):
        s=fixture();s['accounts'][0]['OptiBrain_Test']=True;r=build_marketing(s)
        self.assertEqual(r['groups'],[]);self.assertEqual(r['outcomes'],[]);self.assertEqual(r['customer_value'],[])
    def test_test_deal_excludes_financial_descendants(self):
        s=fixture();s['deals'][0]['OptiBrain_Test']=True;r=build_marketing(s)
        self.assertTrue(all(not g['invoice_value'] and g['estimates']==0 for g in r['groups']))
    def test_test_books_customer_excludes_unmarked_estimate(self):
        s=fixture();s['customers'][0]['contact_name']='OPTIBRAIN TEST — A';r=build_marketing(s)
        self.assertEqual(self.group(r)['estimates'],0);self.assertEqual(self.group(r)['invoice_value'],{})
    def test_no_raw_urls_email_or_click_id_in_render(self):
        s=fixture();s['leads'][0].update(First_Source='owner@example.test',First_Campaign='https://x.test/?email=owner@example.test',Google_GCLID='PRIVATECLICK')
        html=render_marketing(build_marketing(s));self.assertNotIn('owner@example',html);self.assertNotIn('PRIVATECLICK',html)
    def test_spend_unavailable_not_zero_roas(self):
        r=build_marketing(fixture());self.assertTrue(all(g['spend'] is None and g['roas'] is None for g in r['groups']))
    def test_contact_consent_not_advertising_consent(self):
        row={'id':'3','Google_GCLID':'SYNTHETIC','consent':True,'Outcome_Time':'2026-10-03T00:00:00Z'}
        r=conversion_plan(row,'qualified_lead',destination={'verified':True,'conversion_action':'123'},consent={'contact':True})
        self.assertEqual(r['readiness'],'PARTIAL');self.assertFalse(r['external_upload'])
    def test_ready_plan_still_has_no_transport_authority(self):
        r=conversion_plan({'id':'3','Google_GCLID':'SYNTHETIC','Outcome_Time':'2026-10-03T00:00:00Z'},'qualified_lead',
            destination={'verified':True,'conversion_action':'123'},consent={'ad_user_data':'GRANTED','recorded_at':'2026-10-03T00:00:00Z'})
        self.assertEqual(r['readiness'],'READY_FOR_REVIEW');self.assertFalse(r['external_upload']);self.assertFalse(r['contains_pii'])
    def test_test_conversion_never_exported(self):
        self.assertEqual(conversion_plan({'id':'3','OptiBrain_Test':True},'qualified_lead')['readiness'],'EXCLUDED')
    def test_customer_won_one_event_across_multiple_deals(self):
        s=fixture();s['deals'].append({**s['deals'][0],'id':'14'})
        self.assertEqual(sum(x['kind']=='customer_won' for x in build_marketing(s)['outcomes']),1)
    def test_read_plan_no_mutation_of_snapshot(self):
        s=fixture();before=deepcopy(s);build_marketing(s);self.assertEqual(s,before)


class MarketingCollectionTests(unittest.TestCase):
    def test_converted_leads_requested_and_only_get(self):
        class C:
            def request(self,provider,method,path,query):
                assert method=='GET'
                if path=='/crm/v8/Leads':assert query['converted']=='both'
                key='estimates' if path=='/books/v3/estimates' else 'invoices' if path=='/books/v3/invoices' else 'contacts' if path=='/books/v3/contacts' else 'data'
                return {'ok':True,'status':200,'data':{key:[],'code':0,'info':{'more_records':False},'page_context':{'has_more_page':False}}}
        s=collect_marketing(NativeReader(C()),{'customers':[],'generated':{}})
        self.assertEqual(s['books_invoices'],[]);self.assertEqual(s['provider_reads'],7)
    def test_missing_customer_denies_financial_snapshot(self):
        class C:
            def request(self,provider,method,path,query):
                key='estimates' if path.endswith('/estimates') else 'invoices' if path.endswith('/invoices') else 'contacts' if path=='/books/v3/contacts' else 'data'
                return {'ok':True,'status':200,'data':{key:[{'invoice_id':'11'}] if key=='invoices' else [],'code':0,'info':{'more_records':False},'page_context':{'has_more_page':False}}}
        with self.assertRaises(ValueError):collect_marketing(NativeReader(C()),{'customers':[],'generated':{}})


if __name__=='__main__':unittest.main()
