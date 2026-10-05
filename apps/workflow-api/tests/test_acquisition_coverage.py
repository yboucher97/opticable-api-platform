"""Coverage is broad; provider execution stays absent. Isolated fixtures only."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from test_phase30_triggers import fixture, NOW
from workflow.automation.trigger_runtime import build_queue, projection
from workflow.automation.trigger_intelligence import assess, sales_rows
from workflow.automation.prospect_universe import (ProspectStore, build_universe,
    owner_projection, render, research_contacts)
from workflow.automation.coverage_sources import primary_seeds, collect, private_triggers
from workflow.automation.trigger_sources import quebec_permits, location_geography


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=ProspectStore(Path(self.tmp.name)/'db');self.r,self.a,self.c=fixture()

    def universe(self,rows=None,seeds=(),a=None,c=None,now=NOW):
        a=a or self.a;c=c or self.c
        q=build_queue(self.store,rows if rows is not None else [self.r],a,c,now=now,crm_at=now.isoformat(),feedback={},source_health=[])
        return build_universe(self.store,q,a,c,now=now,crm_at=now.isoformat(),seeds=seeds),q

    def seed(self):
        return {'company_name':'Warehouse Operator','domain':'warehouse.test','identity_status':'SUPPORTED',
            'source_provider':'primary_company','source_record_id':'warehouse','source_url':'https://warehouse.test/about',
            'observed_at':NOW.isoformat(),'geography_class':'LAVAL','icp':'warehouse',
            'why_opticable':'Warehouse operator; no current trigger.',
            'service_fit':{'primary':[],'secondary':[],'possible':['commercial Wi-Fi'],'basis':'GENERAL ICP FIT'}}

    def test_expired_event_keeps_reusable_buyer_but_not_sales(self):
        self.r.update(status='AWARDED',trigger_type='PUBLIC TENDER')
        u,q=self.universe();p=u['records'][0]
        self.assertEqual(u['historical_organizations'],1)
        self.assertIn('HISTORICAL INTELLIGENCE',p['pools'])
        self.assertFalse(q['rows'][0]['sales_review_eligible']);self.assertEqual(sales_rows(q['rows']),[])
        self.assertIsNone(u['trigger_audits'][0]['ignore']['reason'])

    def test_three_historical_records_detect_one_repeat_buyer(self):
        rs=[{**self.r,'source_record_id':str(i),'status':'AWARDED'} for i in range(3)]
        u,q=self.universe(rs);self.assertEqual(u['funnel']['organizations'],1)
        self.assertEqual(u['repeat_buyers'],1);self.assertEqual(u['records'][0]['repeat_buyer_count'],3)
        u2,_=self.universe(rs);self.assertEqual(u2['records'][0]['repeat_buyer_count'],3)

    def test_high_fit_no_trigger_retained_and_resolved_no_contact_pool(self):
        u,q=self.universe([],seeds=[self.seed()]);p=u['records'][0]
        self.assertEqual(u['icp_only_prospects'],1);self.assertEqual(p['prospecting_status'],'NEEDS CONTACT')
        self.assertEqual(p['why_now'],'NO CURRENT TRIGGER');self.assertIsNone(p['ignore_audit']['reason'])
        self.assertFalse(p['outbound_authorized'])

    def test_unresolved_permit_is_project_not_invented_organization(self):
        self.r.pop('company_name');self.r.pop('domain');self.r.pop('company_identity')
        self.r['actors']=[];u,q=self.universe()
        self.assertEqual(u['funnel']['organizations'],0);self.assertEqual(u['unresolved_projects'],1)
        self.assertEqual(u['records'][0]['prospecting_status'],'NEEDS COMPANY RESOLUTION')

    def person(self,ident='p',**extra):
        return {'id':ident,'account':{'primary_domain':'company.test'},'email':'person@company.test',
                'email_status':'verified','title':'Operations Manager','updated_at':NOW.isoformat(),**extra}

    def test_multi_contact_valid_roles_raise_coverage_without_send(self):
        self.a['contacts']=[self.person(),self.person('p2',email='facilities@company.test',title='Facilities Manager')]
        u,_=self.universe();p=u['records'][0]
        self.assertEqual(p['contact_coverage']['valid_roles'],2)
        self.assertEqual(u['funnel']['with_contacts'],1);self.assertFalse(p['outbound_authorized'])

    def test_apollo_active_sequence_is_not_independent_future_execution(self):
        self.a['contacts']=[self.person(contact_campaign_statuses=[{'status':'active'}])]
        u,_=self.universe();p=u['records'][0]
        self.assertEqual(p['prospecting_status'],'ACTIVE APOLLO')
        self.assertEqual(p['future_outreach_state'],'COLLISION_REVIEW');self.assertFalse(p['outbound_authorized'])

    def test_customer_and_deal_context_not_cold(self):
        self.c['Accounts']=[{'id':'a','Website':'company.test','Account_Type':'customer'}]
        self.r['company_identity']['crm_account_id']='a'
        u,_=self.universe();self.assertEqual(u['records'][0]['prospecting_status'],'EXISTING CUSTOMER')
        self.c['Deals']=[{'id':'d','Account_Name':{'id':'a'},'Stage':'Negotiation'}]
        u,_=self.universe();self.assertEqual(u['records'][0]['prospecting_status'],'ACTIVE DEAL')

    def test_unsubscribe_suppresses_execution_but_retains_research(self):
        self.a['contacts']=[self.person(email_unsubscribed=True)]
        u,_=self.universe();p=u['records'][0]
        self.assertEqual(p['prospecting_status'],'SUPPRESSED');self.assertFalse(p['outbound_authorized'])
        self.assertEqual(len(self.store.records(prospects=True)),1)

    def test_foreign_and_irrelevant_records_have_explicit_ignore_reason(self):
        for geo,title,reason in [('FOREIGN','Network installation','WRONG_COUNTRY'),('MONTRÉAL','Decorative fountain','NOT_SERVICE_FIT')]:
            with self.subTest(reason=reason):
                row={**self.r,'geography_class':geo,'title':title,'source_record_id':reason}
                u,q=self.universe([row]);a=next(x for x in u['trigger_audits'] if x['trigger_id']==q['rows'][0]['trigger_id'])
                self.assertIn(reason,[x['ignore']['reason'] for x in u['trigger_audits']]);self.assertTrue(a['ignore']['source'])

    def test_historical_prospect_new_trigger_reactivates_same_identity(self):
        u,_=self.universe([{**self.r,'status':'AWARDED'}]);pid=u['records'][0]['prospect_id']
        u,_=self.universe([{**self.r,'source_record_id':'new','status':'OPEN'}])
        self.assertEqual(len(u['records']),1);self.assertEqual(u['records'][0]['prospect_id'],pid)
        self.assertEqual(u['records'][0]['current_trigger_count'],1);self.assertEqual(u['records'][0]['historical_trigger_count'],1)

    def test_owner_gc_electrician_are_separate_entities(self):
        self.r['actors']=[{'role':role,'name':role+' Co','source_actor_id':role,'source_url':self.r['source_url'],
                           'confidence':'SUPPORTED','domain':role.casefold().replace(' ','')+'.test'}
                          for role in ['PROPERTY OWNER','GENERAL CONTRACTOR','ELECTRICAL CONTRACTOR']]
        u,_=self.universe();self.assertEqual(u['funnel']['organizations'],4)
        self.assertEqual(len({p['prospect_id'] for p in u['records']}),4)

    def test_failed_lookup_recorded_and_no_immediate_retry(self):
        u,_=self.universe([],seeds=[self.seed()])
        with patch('workflow.automation.apollo_observation.ApolloReader') as reader:
            reader.return_value.read.side_effect=ValueError('Apollo read unavailable: HTTP 403')
            reader.return_value.calls=1
            cache,calls=research_contacts(self.store,u,{},SimpleNamespace(apollo={}),now=NOW)
            self.assertEqual(cache['warehouse.test']['http_status'],403)
            cache,calls=research_contacts(self.store,u,cache,SimpleNamespace(apollo={}),now=NOW+timedelta(minutes=1))
            self.assertEqual(calls,0);self.assertEqual(reader.return_value.read.call_count,1)

    def test_likely_people_retained_without_contact_coverage_or_sales(self):
        u,_=self.universe([],seeds=[self.seed()])
        with patch('workflow.automation.apollo_observation.ApolloReader') as reader:
            reader.return_value.read.return_value={'people':[{'id':'person','title':'IT Manager'}]};reader.return_value.calls=1
            cache,calls=research_contacts(self.store,u,{},SimpleNamespace(apollo={}),now=NOW)
        self.assertEqual(cache['warehouse.test']['candidates'][0]['confidence'],'LIKELY')
        q={'rows':[]};u=build_universe(self.store,q,self.a,self.c,now=NOW,crm_at=NOW.isoformat(),seeds=[self.seed()],research=cache)
        self.assertEqual(u['contact_counts']['LIKELY'],1);self.assertEqual(u['funnel']['with_contacts'],0)

    def test_retention_prevents_age_eviction_and_baseline_is_immutable(self):
        u,q=self.universe([{**self.r,'status':'AWARDED'}]);self.store.prune_triggers(NOW+timedelta(days=400))
        self.assertEqual(len(self.store.records()),1)
        rows=[{**q['rows'][0],'trigger_id':str(i),'priority_class':'IGNORE'} for i in range(125)]
        self.store.capture_baseline({'rows':rows,'trigger_count':125},now=NOW)
        self.store.capture_baseline({'rows':[]},now=NOW)
        self.assertEqual(len(self.store.baseline()),125);self.assertEqual(self.store.baseline()['0']['priority_class'],'IGNORE')

    def test_owner_projection_escaped_and_sales_gate_unchanged(self):
        self.r['company_name']='<script>alert(1)</script>'
        u,q=self.universe();v=owner_projection(u)
        self.assertNotIn('<script>',render(v));self.assertNotIn('contacts',v['rows'][0])
        self.assertEqual(bool(sales_rows(q['rows'])),bool(assess(self.r,self.a,self.c,now=NOW,crm_at=NOW.isoformat())['sales_review_eligible']))
        self.assertIn('prospect_id',v['rows'][0]);self.assertIn('why_not_ready',v)

    def test_retained_seed_rechecks_current_collision_and_does_not_slide_revisit(self):
        u,_=self.universe([],seeds=[self.seed()]);due=u['records'][0]['next_research_at']
        self.a['contacts']=[{**self.person(email='operations@warehouse.test'), 'account':{'primary_domain':'warehouse.test'},
                            'contact_campaign_statuses':[{'status':'active'}]}]
        u,_=self.universe([],now=NOW+timedelta(minutes=5))
        self.assertEqual(u['records'][0]['prospecting_status'],'ACTIVE APOLLO')
        self.assertEqual(u['records'][0]['next_research_at'],due)
        self.assertFalse(u['records'][0]['outbound_authorized'])

    def test_failed_provider_pauses_other_domains_and_day_budget_is_global(self):
        seeds=[{**self.seed(),'domain':str(i)+'.test','source_url':'https://'+str(i)+'.test/about','source_record_id':str(i)} for i in range(5)]
        u,_=self.universe([],seeds=seeds)
        with patch('workflow.automation.apollo_observation.ApolloReader') as reader:
            reader.return_value.read.side_effect=ValueError('Apollo read unavailable: HTTP 401');reader.return_value.calls=1
            cache,calls=research_contacts(self.store,u,{},SimpleNamespace(apollo={}),now=NOW)
            cache,calls=research_contacts(self.store,u,cache,SimpleNamespace(apollo={}),now=NOW+timedelta(hours=1))
            self.assertEqual(calls,0);self.assertEqual(reader.return_value.read.call_count,1)
        with patch('workflow.automation.apollo_observation.ApolloReader') as reader:
            reader.return_value.read.return_value={'people':[]};reader.return_value.calls=3
            cache,calls=research_contacts(self.store,u,{},SimpleNamespace(apollo={}),now=NOW+timedelta(days=1))
            self.assertEqual(reader.return_value.read.call_count,3)
            cache,calls=research_contacts(self.store,u,cache,SimpleNamespace(apollo={}),now=NOW+timedelta(days=1,minutes=5))
            self.assertEqual(calls,0)

    def test_resolution_health_has_explicit_denominator_and_unknown_geography_hold(self):
        seed={**self.seed(),'geography_class':'UNKNOWN'}
        u,_=self.universe([],seeds=[seed]);p=u['records'][0]
        self.assertEqual(u['coverage_health']['company_resolution'],{'numerator':1,'denominator':1})
        self.assertIn('UNKNOWN_GEOGRAPHY',p['why_not_ready']);self.assertNotEqual(p['future_outreach_state'],'OWNER_REVIEW')


class CoverageSourceTests(unittest.TestCase):
    def test_quebec_adapter_keeps_commercial_not_single_family_or_trees(self):
        reasons=['Construction bâtiment commercial','Construction bâtiment résidentiel de1à3 logements','Abattage arbre',
                 'Construction bâtiment habitation multifamilial de 9 logements et plus']
        data={'features':[{'properties':{'NUMERO_PERMIS':str(i),'DATE_DELIVRANCE':'2026-10-02','RAISON':r,'DOMAINE':'Construction'}} for i,r in enumerate(reasons)]}
        rows=quebec_permits(data,now=NOW,verified_at=NOW.isoformat(),published_at=NOW.isoformat())
        self.assertEqual(len(rows),2);self.assertTrue(all(r['company_name'] is None for r in rows))
        self.assertTrue(all(r['geography_class']=='QUÉBEC CITY' for r in rows))

    def test_french_unknown_not_quebec_and_foreign_wins(self):
        self.assertEqual(location_geography(None,None,None),'UNKNOWN')
        self.assertEqual(location_geography('Laval','QC','France'),'FOREIGN')

    def test_provider_failure_retains_prior_evidence_no_retry(self):
        class Reader:
            calls=0
            def get(self,*a,**kw):self.calls+=1;raise ValueError('Bound exceeded')
            def close(self):pass
        old={'quebec_permit':{'records':[{'source_record_id':'old'}],'observed_at':(NOW-timedelta(days=8)).isoformat()}}
        reader=Reader();rows,seeds,cache,health=collect(old,now=NOW,reader=reader)
        self.assertEqual(rows[0]['source_record_id'],'old');self.assertEqual(cache['quebec_permit']['observed_at'],old['quebec_permit']['observed_at'])
        self.assertEqual(reader.calls,4);self.assertTrue(all(h['state'] in {'BLOCKED','PARTIAL'} for h in health))

    def test_primary_history_retains_owner_and_gc_no_fake_domain(self):
        seeds=primary_seeds('saq_gc',b'August 22, 2023 Frare Gallant Laval',now=NOW)
        self.assertEqual(len(seeds),2);self.assertIsNone(seeds[1]['domain'])
        self.assertEqual({s['historical_project']['actor_role'] for s in seeds},{'PROPERTY OWNER','GENERAL CONTRACTOR'})

    def test_private_expansion_is_evidence_not_confirmed_service_need(self):
        seeds=primary_seeds('lovo','27 avril 2026 Saint-Lambert-de-Lauzon novembre 2026'.encode(),now=NOW)
        rows=private_triggers(seeds,now=NOW)
        self.assertEqual(rows[0]['status'],'ANNOUNCED');self.assertEqual(rows[0]['publish_date'],'2026-04-27T12:00:00-04:00')
        _,a,c=fixture();rated=assess(rows[0],a,c,now=NOW,crm_at=NOW.isoformat())
        self.assertFalse(rated['sales_review_eligible']);self.assertFalse(rated['service_fit']['scope_confirmed'])
