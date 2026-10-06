"""Absent, empty, partial and stale sources through the shared collision callers."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from test_phase30_triggers import fixture,decision,NOW
from workflow.automation.observation_completeness import crm_context,complete,CRM_REQUIRED,APOLLO_REQUIRED
from workflow.automation.trigger_intelligence import collision_state,company_identity,sales_rows
from workflow.automation.prospect_universe import ProspectStore,build_universe
from workflow.automation.trigger_runtime import build_queue
from workflow.automation.prospect_enrichment import refresh_status
from workflow.automation.manager_sources import registry
from workflow.automation.apollo_observation import ApolloReader
from workflow.automation.sales_intelligence import build_sales
from workflow.automation.sales_conversations import relationship


class CompletenessTests(unittest.TestCase):
    def check(self,a=None,c=None):
        row,apollo,crm=fixture()
        return decision(row,a if a is not None else apollo,c if c is not None else crm)
    def test_absent_deals_never_verified_empty_even_with_complete_flag(self):
        _,a,c=fixture();c.pop('Deals')
        r=self.check(a,c);self.assertEqual(r['collision']['classification'],'UNKNOWN')
        self.assertEqual(r['collision']['module_completeness']['crm']['Deals']['state'],'NOT_COLLECTED_UNKNOWN')
        self.assertFalse(r['sales_review_eligible']);self.assertEqual(r['collision']['execution_readiness'],'HOLD')
    def test_verified_empty_deals_allowed(self):
        _,a,c=fixture();r=self.check(a,c)
        self.assertEqual(r['collision']['module_completeness']['crm']['Deals']['state'],'COMPLETE_VERIFIED_EMPTY')
        self.assertEqual(r['collision']['classification'],'NEW COMPANY')
    def test_present_array_without_independent_metadata_unknown(self):
        _,a,c=fixture();c['_modules'].pop('Deals')
        self.assertEqual(self.check(a,c)['collision']['classification'],'UNKNOWN')
    def test_failed_deals_unknown_hold(self):self.check_state('FAILED')
    def test_partial_deals_unknown_hold(self):self.check_state('PARTIAL')
    def test_not_collected_deals_unknown_hold(self):self.check_state('NOT_COLLECTED_UNKNOWN')
    def check_state(self,state):
        _,a,c=fixture();c['_modules']['Deals']={'state':state,'source_at':NOW.isoformat()}
        r=self.check(a,c);self.assertEqual(r['collision']['classification'],'UNKNOWN')
        self.assertEqual(r['collision']['execution_readiness'],'HOLD');self.assertEqual(sales_rows([r]),[])
    def test_stale_deals_unknown_even_current_crm_aggregate(self):
        _,a,c=fixture();c['_modules']['Deals']['source_at']=(NOW-timedelta(hours=3)).isoformat()
        r=self.check(a,c);self.assertEqual(r['collision']['classification'],'UNKNOWN')
        self.assertEqual(r['collision']['module_completeness']['crm']['Deals']['state'],'STALE')
    def test_future_module_unknown(self):
        _,a,c=fixture();c['_modules']['Deals']['source_at']=(NOW+timedelta(seconds=1)).isoformat()
        self.assertFalse(self.check(a,c)['collision']['crm_fresh_complete'])
    def test_positive_deal_preserved_with_another_failed_module(self):
        _,a,c=fixture();c['Accounts']=[{'id':'a','Website':'company.test'}]
        c['Deals']=[{'id':'d','Account_Name':{'id':'a'},'Stage':'Proposal'}]
        c['_modules']['Services']={'state':'FAILED'}
        r=self.check(a,c);self.assertEqual(r['collision']['classification'],'OPEN DEAL')
        self.assertEqual(r['collision']['open_deal_ids'],['d']);self.assertEqual(r['collision']['execution_readiness'],'HOLD')
        self.assertFalse(r['sales_review_eligible'])
    def test_missing_services_sites_customer_context_all_hold(self):
        for name in ('Services','Service_Locations','Customer_Context'):
            with self.subTest(name=name):
                _,a,c=fixture();c.pop(name)
                self.assertEqual(self.check(a,c)['collision']['classification'],'UNKNOWN')
    def test_every_required_crm_module_independently_required(self):
        for name in CRM_REQUIRED:
            with self.subTest(name=name):
                _,a,c=fixture();c['_modules'][name]['completeness']='PARTIAL'
                self.assertFalse(self.check(a,c)['collision']['crm_fresh_complete'])
    def test_apollo_contacts_complete_does_not_prove_other_context(self):
        for name in APOLLO_REQUIRED:
            with self.subTest(name=name):
                _,a,c=fixture();a['modules'].pop(name)
                r=self.check(a,c);self.assertEqual(r['collision']['classification'],'UNKNOWN')
                self.assertFalse(r['sales_review_eligible']);self.assertEqual(r['collision']['execution_readiness'],'HOLD')
    def test_crm_complete_apollo_incomplete(self):
        _,a,c=fixture();a['modules']['ownership']['completeness']='PARTIAL'
        r=self.check(a,c);self.assertTrue(r['collision']['crm_fresh_complete']);self.assertFalse(r['collision']['apollo_fresh_complete'])
    def test_apollo_complete_crm_incomplete(self):
        _,a,c=fixture();c['_modules']['Deals']['completeness']='PARTIAL'
        r=self.check(a,c);self.assertTrue(r['collision']['apollo_fresh_complete']);self.assertFalse(r['collision']['crm_fresh_complete'])
    def test_suppression_and_ownership_positive_survive_unknown(self):
        _,a,c=fixture();c.pop('Deals')
        a['contacts']=[{'id':'c','email':'person@company.test','email_status':'verified','email_unsubscribed':True}]
        r=self.check(a,c);self.assertEqual(r['collision']['classification'],'SUPPRESSED')
        self.assertEqual(r['collision']['execution_readiness'],'HOLD')
    def test_crm_context_legacy_missing_deals_not_synthesized(self):
        business={'schema':3,'observed_at':NOW.isoformat(),'marketing':None,'snapshot':{'accounts':[],'services':[],'sites':[],'customers':[]}}
        identities={'schema':1,'at':NOW.isoformat(),'crm':{'Accounts':[],'Leads':[],'Contacts':[]}}
        c=crm_context(business,identities)
        self.assertNotIn('Deals',c);self.assertNotIn('Deals',c['_modules'])
        _,a,_=fixture();self.assertEqual(self.check(a,c)['collision']['classification'],'UNKNOWN')
    def test_deterministic_customer_context_requires_all_native_parents(self):
        snapshot={v:[] for v in ('accounts','services','sites','customers','leads','contacts','deals')}
        business={'schema':3,'observed_at':NOW.isoformat(),'snapshot':snapshot,'marketing':{'groups':[]}}
        c=crm_context(business);self.assertEqual(c['_modules']['Customer_Context']['completeness'],'COMPLETE_VERIFIED_EMPTY')
        business['snapshot'].pop('customers');c=crm_context(business)
        self.assertEqual(c['_modules']['Customer_Context']['completeness'],'PARTIAL')
    def test_books_customer_positive_relationship_preserved(self):
        row,a,c=fixture();c['Accounts']=[{'id':'a','Website':'company.test'}];c['Customer_Context']=[{'account_id':'a'}]
        c.pop('Deals');r=self.check(a,c)
        self.assertTrue(r['collision']['existing_customer']);self.assertEqual(r['collision']['classification'],'EXISTING CUSTOMER OPPORTUNITY')
    def test_shadow_prospect_keeps_unknown_sources_pending(self):
        row,a,c=fixture();c.pop('Deals')
        with tempfile.TemporaryDirectory() as tmp:
            store=ProspectStore(Path(tmp)/'db');queue=build_queue(store,[row],a,c,now=NOW,crm_at=NOW.isoformat(),feedback={},source_health=[])
            p=build_universe(store,queue,a,c,now=NOW,crm_at=NOW.isoformat())['records'][0]
            self.assertEqual(p['collision']['classification'],'UNKNOWN');self.assertIn('UNKNOWN_COLLISION',p['why_not_ready'])
            self.assertEqual(p['CRM_state'],'UNKNOWN');self.assertFalse(p['outbound_authorized'])
    def test_enrichment_positive_account_does_not_clear_incomplete_apollo(self):
        row,a,c=fixture();c['Accounts']=[{'id':'a','Website':'company.test'}];a['modules']['replies']['completeness']='PARTIAL'
        with tempfile.TemporaryDirectory() as tmp:
            store=ProspectStore(Path(tmp)/'db');queue=build_queue(store,[row],a,c,now=NOW,crm_at=NOW.isoformat(),feedback={},source_health=[])
            p=build_universe(store,queue,a,c,now=NOW,crm_at=NOW.isoformat())['records'][0]
            p['contacts']=[{'confidence':'SUPPORTED_CURRENT','title':'Operations Manager','contact_allowed':False}]
            p['domain_confidence']='OFFICIAL';refresh_status(p)
            self.assertNotEqual(p['enrichment_readiness'],'PROSPECTING_READY');self.assertIn('UNKNOWN_COLLISION',p['why_not_ready'])
    def test_sales_review_incomplete_context_hold(self):
        row,a,c=fixture();c.pop('Deals')
        v=build_sales(a,c,[],now=NOW)
        self.assertEqual(v['execution_readiness'],'HOLD');self.assertFalse(v['module_completeness']['crm_complete'])
    def test_sales_proposal_relationship_cannot_invent_empty_clearance(self):
        self.assertIn('UNKNOWN',relationship({'email':'person@company.test'}, {})['state'])
        self.assertEqual(relationship({'email':'person@company.test'}, {})['execution_readiness'],'HOLD')
    def test_manager_partial_not_rejuvenated_by_identity_date(self):
        module={'state':'FAILED','source_at':None}
        inputs={'business':{'observed_at':NOW.isoformat(),'snapshot':{'observed_at':NOW.isoformat(),'deals':[],
                 'collection':{'state':'PARTIAL','modules':{'deals':module}}}},'sales-intelligence':{'crm_observed_at':NOW.isoformat()}}
        states={r['source_id']:r for r in registry(inputs,NOW)}
        self.assertEqual(states['crm']['data_health'],'PARTIAL');self.assertEqual(states['books']['data_health'],'PARTIAL')
    def test_apollo_failed_account_read_preserves_positive_last_good_owner(self):
        def response(req):
            if req.url.path.endswith('accounts/search'):return httpx.Response(503,json={})
            key='contacts' if req.url.path.endswith('contacts/search') else 'emailer_campaigns' if req.url.path.endswith('emailer_campaigns/search') else 'contact_stages' if req.url.path.endswith('contact_stages') else 'emailer_messages'
            return httpx.Response(200,json={key:[],'pagination':{'total_entries':0,'total_pages':0}})
        prior={'at':(NOW-timedelta(hours=7)).isoformat(),'accounts':[{'id':'a','primary_domain':'company.test'}]}
        r=ApolloReader(SimpleNamespace(api_key='fixture'),transport=httpx.MockTransport(response))
        try:a=r.workspace(previous=prior)
        finally:r.close()
        self.assertEqual(a['accounts'],prior['accounts'])
        self.assertEqual(a['modules']['accounts']['source_at'],prior['at'])
        row,_,c=fixture();checked=decision(row,a,c)['collision']
        self.assertEqual(checked['apollo_account_matches'],['a']);self.assertEqual(checked['execution_readiness'],'HOLD')
    def test_legacy_recurring_customer_subset_cannot_prove_customer_clearance(self):
        c=crm_context({'schema':3,'observed_at':NOW.isoformat(),'marketing':None,
                       'snapshot':{'accounts':[],'services':[],'sites':[],'customers':[]}})
        self.assertNotIn('Books_Customers',c['_modules'])
        self.assertEqual(c['_modules']['Customer_Context']['completeness'],'PARTIAL')
    def test_apollo_bounded_activity_without_pagination_is_partial(self):
        def response(req):
            key={'contacts/search':'contacts','accounts/search':'accounts','emailer_campaigns/search':'emailer_campaigns',
                 'emailer_messages/search':'emailer_messages','contact_stages':'contact_stages'}
            name=next(v for k,v in key.items() if req.url.path.endswith(k))
            body={name:[]}
            if name not in {'emailer_messages','contact_stages'}:body['pagination']={'total_entries':0,'total_pages':0}
            return httpx.Response(200,json=body)
        r=ApolloReader(SimpleNamespace(api_key='fixture'),transport=httpx.MockTransport(response))
        try:a=r.workspace()
        finally:r.close()
        self.assertTrue(a['contacts_complete']);self.assertEqual(a['modules']['messages']['completeness'],'PARTIAL')
        self.assertEqual(a['modules']['replies']['completeness'],'PARTIAL');self.assertEqual(a['provider_mutations'],0)
