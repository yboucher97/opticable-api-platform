from copy import deepcopy
from datetime import datetime,timedelta,timezone
import unittest
from workflow.automation.evidence_quality import search_evidence,geography_evidence,fact
from workflow.automation.acquisition_ingest import gsc_rows
from workflow.automation.acquisition_intelligence import render_acquisition
from workflow.automation.seo_intelligence import content_opportunity,build_content
from workflow.automation.trigger_evidence import latest_releases,tender_status,assess_trigger,actors_from_release
from workflow.automation.sales_intelligence import build_sales,permit_signals,tender_signals

NOW=datetime(2026,10,4,4,tzinfo=timezone.utc)
PAGE={'url':'https://opticable.ca/en/services/commercial-wifi/','indexable_candidate':True,'service':'Commercial Wi-Fi','language':'EN','page_type':'SERVICE',
      'issues':[],'internal_links':[],'hreflang':{},'title':'Commercial Wi-Fi','content_hash':'fixture','in_sitemap':True,'crawlable':True,'redirect_chain':[]}


def trigger():
    return {'key':'signal','record_id':'o1','native_version':'20260930162400','source':'seao','company':'Buyer',
        'domain':'buyer.test','company_identity':{'confidence':'SUPPORTED','source_url':'https://buyer.test/about'},
        'identity_unresolved':False,'actors':[{'role':'BUYER','source_actor_id':'buyer-id','source_record_id':'o1','confidence':'EXACT'}],
        'current_status':'OPEN','retrieved_at':NOW.isoformat(),'last_checked':NOW.isoformat(),
        'geography':'Montréal','deadline':(NOW+timedelta(days=4)).isoformat(),'trigger':'Commercial cameras',
        'why_now':'Published tender','who':'Owner reviews procurement','fit':'CCTV','source_url':'https://seao.gouv.qc.ca/test'}


class SearchConfidenceTests(unittest.TestCase):
    def keyword(self,n):return {'query':'commercial wifi installation','language':'EN','page':PAGE['url'],
        'impressions':n,'clicks':0,'position':14,'date_from':'2026-09-01','date_to':'2026-09-28','country':'CAN'}
    def test_sparse_visibility_remains_an_opportunity_without_equal_evidence_or_high_priority(self):
        tiny=content_opportunity(self.keyword(1),[PAGE]);strong=content_opportunity(self.keyword(100),[PAGE])
        self.assertEqual(tiny['decision'],'IMPROVE EXISTING PAGE')
        self.assertEqual(tiny['evidence_confidence'],'TENTATIVE EVIDENCE')
        self.assertEqual(strong['evidence_confidence'],'STRONG EVIDENCE')
        self.assertLess(tiny['score_components']['existing_near_page_one'],strong['score_components']['existing_near_page_one'])
        self.assertNotEqual(tiny['priority'],'HIGH');self.assertIn('1 impressions',tiny['why'])
    def test_confidence_bands_and_missing_are_not_zero(self):
        for n,expected in ((None,'INSUFFICIENT'),(0,'INSUFFICIENT'),(3,'TENTATIVE'),(20,'MODERATE'),(100,'STRONG')):
            with self.subTest(n=n):self.assertTrue(search_evidence({'impressions':n})['class'].startswith(expected))
        self.assertIsNone(fact(None,'provider')['value']);self.assertEqual(fact(0,'provider')['value'],0)
        self.assertEqual(fact(None,'provider')['truth'],'UNKNOWN')
    def test_owner_sees_sample_window_and_not_just_a_high_label(self):
        item=content_opportunity(self.keyword(1),[PAGE]);view={'content_queue':[item],'measurement_health':{},'opportunities':[]}
        html=render_acquisition(view)
        for value in ('1.0 impressions','0.0 clicks','average position 14.0','2026-09-01','2026-09-28','TENTATIVE EVIDENCE','CANADA'):
            self.assertIn(value,html)
    def test_language_is_never_location_and_foreign_query_is_research_only(self):
        self.assertEqual(geography_evidence({'query':'câblage structuré','language':'FR'})['geography'],'UNKNOWN')
        query={**self.keyword(100),'query':'commercial wifi installation albuquerque','country':'CAN'}
        self.assertFalse(geography_evidence(query)['quebec_recommendation_allowed'])
        report=build_content([query],[PAGE]);self.assertEqual(report['content_queue'],[]);self.assertEqual(report['paid_opportunities'],[])
        self.assertEqual(len(report['excluded_research']),1)
    def test_mixed_country_samples_preserve_global_evidence_without_importing_foreign_counts(self):
        rows=[{'keys':['commercial wifi',PAGE['url'],country],'impressions':n,'clicks':0,'position':14} for country,n in (('can',1),('usa',100))]
        query=gsc_rows({'data':{'rows':rows},'date_from':'2026-09-01','date_to':'2026-09-28'})[0]
        self.assertEqual(query['impressions'],1);self.assertEqual(query['all_country_metrics']['impressions'],101)
        self.assertEqual(len(query['country_breakdown']),2);self.assertEqual(search_evidence(query)['class'],'TENTATIVE EVIDENCE')
    def test_independent_native_market_demand_can_corroborate_new_query(self):
        item=content_opportunity({**self.keyword(3),'market_volume':500},[])
        self.assertEqual(item['decision'],'NEW PAGE CANDIDATE');self.assertIn('market_volume',item['facts'])
        self.assertEqual(item['facts']['market_volume']['truth'],'ESTIMATE')


class TriggerEvidenceTests(unittest.TestCase):
    def test_latest_amendment_wins_even_when_original_publication_date_stays_old(self):
        old={'ocid':'o','id':'20260923115156','date':'2026-09-23T11:51:56Z'}
        new={**old,'id':'20260930162400'}
        self.assertEqual(latest_releases([new,old])['o']['id'],new['id'])
        self.assertEqual(latest_releases([{'ocid':'o','id':'9'},{'ocid':'o','id':'10'}])['o']['id'],'10')
    def test_closed_cancelled_expired_and_stale_never_reach_sales(self):
        for changes in ({'deadline':NOW.isoformat()},{'current_status':'CANCELLED'},{'last_checked':(NOW-timedelta(days=5)).isoformat()},{'native_version':None}):
            with self.subTest(changes=changes):
                r=assess_trigger({**trigger(),**changes},now=NOW)
                self.assertFalse(r['sales_review_eligible'])
                self.assertFalse(any(x['kind']=='trigger' for x in build_sales({'at':NOW.isoformat(),'contacts_complete':True},{},[r],now=NOW)['rows']))
        self.assertEqual(tender_status({'status':'active','tenderPeriod':{'endDate':NOW.isoformat()}},NOW),'CLOSED')
    def test_named_applicant_or_likely_actor_cannot_become_an_exact_target(self):
        r=trigger();r['actors']=[{'role':'APPLICANT','confidence':'LIKELY','source_actor_id':'p','source_record_id':'o'}]
        r=assess_trigger(r,now=NOW);self.assertTrue(r['identity_unresolved']);self.assertEqual(r['recommendation_state'],'RESEARCH NEEDED')
    def test_native_owner_and_gc_are_distinct_evidence_not_one_assumed_sales_contact(self):
        row=trigger();row['actors']=[{'role':role,'name':name,'confidence':'EXACT','source_actor_id':name,'source_record_id':'p'} for role,name in (('PROPERTY OWNER','Owner Co'),('GENERAL CONTRACTOR','GC Co'))]
        result=assess_trigger(row,now=NOW);self.assertEqual(len(result['actors']),2);self.assertFalse(result['contact_allowed'])
        self.assertEqual({a['role'] for a in result['actors']},{'PROPERTY OWNER','GENERAL CONTRACTOR'})
    def test_apollo_collision_and_existing_customer_relationship_stay_protected(self):
        a={'at':NOW.isoformat(),'contacts_complete':True,'contacts':[{'id':'c','email':'p@buyer.test','email_status':'verified','contact_campaign_statuses':[{'status':'active'}]}]}
        view=build_sales(a,{},[trigger()],now=NOW)
        item=next(r for r in view['rows'] if r['kind']=='trigger')
        self.assertEqual(item['outreach_owner'],'CLAUDE_APOLLO');self.assertIn('existing Apollo',item['action']);self.assertFalse(item['contact_allowed'])
        c={'Accounts':[{'id':'a','Website':'buyer.test'}]}
        item=next(r for r in build_sales({'at':NOW.isoformat(),'contacts_complete':True},c,[trigger()],now=NOW)['rows'] if r['kind']=='trigger')
        self.assertTrue(item['existing_customer']);self.assertEqual(item['outreach_owner'],'OWNER_MANUAL')
    def test_unresolved_permit_stays_out_of_sales_and_replay_is_one_signal(self):
        r={'id_permis':'1','date_emission':'2026-09-28','description_type_batiment':'Commercial','code_type_base_demande':'CO','nature_travaux':'Nouveau commerce'}
        signals=permit_signals([r,r],now=NOW,retrieved_at=NOW.isoformat());self.assertEqual(len(signals),1)
        v=build_sales({'at':NOW.isoformat(),'contacts_complete':True},{},signals,now=NOW)
        self.assertEqual(v['research_held'],1);self.assertEqual(v['rows'],[])
    def test_suppression_denies_even_resolved_current_trigger_review(self):
        a={'at':NOW.isoformat(),'contacts_complete':True,'contacts':[{'id':'c','email':'p@buyer.test','email_status':'verified','email_unsubscribed':True}]}
        self.assertEqual(build_sales(a,{},[trigger()],now=NOW)['rows'],[])


if __name__=='__main__':unittest.main()
