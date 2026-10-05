"""Shadow Ads intelligence, shared contract, isolation and owner review proof."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import json,tempfile,unittest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from workflow.automation.ads_intelligence import assess,build_bundle,classify_term,render_proposal
from workflow.automation.ads_sources import AdsInventoryReader,queries,ENDPOINT
from workflow.automation.optimization_store import OptimizationStore,validate
from workflow.automation.ads_runtime import persist
from workflow.automation.today import build_today
from workflow.automation.store import AutomationStore
from workflow.operator_phase7_api import install_phase7_canary_routes
from workflow.operator_access import AccessPrincipal

NOW=datetime(2026,10,5,21,tzinfo=timezone.utc)


def fixture():
    read=lambda data:{'state':'WORKING','observed_at':NOW.isoformat(),'complete':True,'data':{'results':data},'date_from':'2026-07-07','date_to':'2026-10-04'}
    a={'schema':1,'at':NOW.isoformat(),'reads':{'customer':read([{'customer':{'currencyCode':'CAD'}}]),
       'campaigns':read([{'campaign':{'id':'1','status':'REMOVED'}}]),'performance_90d':read([]),
       'performance_history':read([{'campaign':{'id':'1'},'metrics':{'clicks':'1','costMicros':'5000000','conversions':0,'impressions':'20'}}]),
       'search_terms_history':read([{'campaign':{'id':'1'},'searchTermView':{'searchTerm':'home security camera'},'metrics':{'costMicros':'5000000','clicks':'1','impressions':'1'}}])}}
    # Native scope request/response is identical to the trusted cache contract.
    request=lambda lang,seeds:{'connector':'google_ads','accounts':['680-849-1878'],'options':{'language':lang,'geo_target_constants':'20123','keyword_plan_network':'GOOGLE_SEARCH','keyword_seeds':seeds}}
    e={'schema':1,'provider':'windsor_google_ads_keyword_planner','account':'6808491878','currency':'CAD','location_id':'20123','retrieved_at':NOW.isoformat(),
       'requests':[request('1002','cablage structuré'),request('1000','commercial security cameras')],
       'replies':[{'status':'done','data':[{'keyword':'cablage structuré','keyword_country':'Quebec','keyword_language':'French','keyword_average_cpc':4000000,'avg_monthly_searches':70,'keyword_competition':'MEDIUM'}]},
                  {'status':'done','data':[{'keyword':'commercial security cameras','keyword_country':'Quebec','keyword_language':'English','keyword_average_cpc':5000000,'avg_monthly_searches':20,'keyword_competition':'HIGH'}]}]}
    google={'reads':{'gsc_queries':{'state':'WORKING','observed_at':NOW.isoformat(),'date_from':'2026-09-02','date_to':'2026-10-03','data':{'rows':[
        {'keys':['commercial security cameras','https://opticable.ca/en/services/security-camera-systems/','can'],'impressions':30,'clicks':0,'position':29},
        {'keys':['camera installation paris','https://opticable.ca/en/','fra'],'impressions':900,'clicks':2,'position':5}]}}}}
    return {'ads':a,'keyword_economics':e,'google':google,'phase32_at':NOW.isoformat(),
            'website':{'https://opticable.ca/en/services/security-camera-systems/':{'readiness':'EXISTING PAGE + QUOTE ROUTE; MOBILE/PERFORMANCE REUSE PHASE32'}}}


class AdsIntelligenceTests(unittest.TestCase):
    def test_a_camera_preview_contains_actual_structure_and_separate_confidence(self):
        b=build_bundle(fixture(),NOW);r=next(p for p in b['proposals'] if p['record']['proposal_type']=='GOOGLE_ADS_CAMPAIGN' and p['detail']['service']=='Security cameras' and p['detail']['language']=='EN')
        validate(r['record']);d=r['detail'];self.assertEqual(d['type'],'SEARCH');self.assertFalse(d['execution_authorized'])
        self.assertEqual(d['ad_groups'][0]['keywords'][0]['estimated_cpc'],5)
        self.assertEqual(d['expected_economics']['illustrative_28_day_clicks'],84)
        self.assertIsNone(d['expected_economics']['CPA']);self.assertEqual(r['record']['confidence'],'MODERATE')
        self.assertEqual(d['locations']['presence'],'PRESENCE');self.assertFalse(d['broad_match'])
        for p in b['proposals']+b['priorities']+b['assets']:validate(p['record'])

    def test_b_one_impression_and_no_economics_remain_tentative(self):
        x=fixture();x.pop('keyword_economics');x['google']['reads']['gsc_queries']['data']['rows'][0]['impressions']=1
        op=assess(x,NOW)['opportunities'][0];self.assertEqual(op['confidence'],'TENTATIVE')
        self.assertEqual(op['organic']['query_samples'][0]['sample_confidence'],'TENTATIVE')
        self.assertIsNone(op['cpc_range']['low']);self.assertEqual(op['organic']['impressions'],1)

    def test_c_consumer_query_negative_never_generic_camera_exclusion(self):
        self.assertEqual(classify_term('home security camera'),'NEGATIVE CANDIDATE')
        self.assertEqual(classify_term('eufy camera'),'NEGATIVE CANDIDATE')
        self.assertEqual(classify_term('commercial camera installation'),'HIGH INTENT')
        self.assertEqual(classify_term('Hikvision commercial camera installation'),'HIGH INTENT')
        self.assertEqual(classify_term('owner@example.com 5145550101'),'PRIVATE QUERY — OMITTED')

    def test_d_missing_landing_page_is_explicit_launch_dependency(self):
        x=fixture();x['website']={};b=build_bundle(x,NOW)
        camera=next(p['detail'] for p in b['proposals'] if p['record']['proposal_type']=='GOOGLE_ADS_CAMPAIGN')
        self.assertEqual(camera['launch_state'],'LANDING PAGE REVIEW REQUIRED')
        self.assertEqual(len([p for p in b['proposals'] if p['record']['proposal_type']=='LANDING_PAGE']),2)

    def test_e_ai_does_not_force_paid_campaign_or_savings(self):
        b=build_bundle(fixture(),NOW);ai=next(o for o in b['intelligence']['opportunities'] if o['service']=='AI loss prevention')
        self.assertEqual(ai['channels'][0],'CONTENT');self.assertIsNone(ai['cpc_range']['low'])
        self.assertFalse(any(p['detail'].get('service')=='AI loss prevention' for p in b['proposals']))
        self.assertTrue(any(a['record']['service']=='AI loss prevention' for a in b['assets']))

    def test_f_historical_bad_intent_produces_cleanup_not_mutation(self):
        b=build_bundle(fixture(),NOW);inv=b['intelligence']['inventory']
        self.assertEqual(inv['performance_history']['cost'],5);self.assertEqual(len(inv['negative_candidates']),1)
        self.assertEqual(inv['negative_candidates'][0]['query'],'home security camera')
        self.assertTrue(any(p['record']['proposal_type']=='GOOGLE_ADS_CLEANUP' for p in b['proposals']))

    def test_g_unknown_cpc_and_zero_volume_remain_distinct(self):
        x=fixture();r=x['keyword_economics']['replies'][1]['data'][0];r.pop('keyword_average_cpc');r['avg_monthly_searches']=0
        op=assess(x,NOW)['opportunities'][0]
        self.assertEqual(op['economics'][0]['market_volume'],0);self.assertIsNone(op['economics'][0]['cpc'])

    def test_h_cache_unavailable_stale_and_wrong_geography_never_fabricate(self):
        for mode in ['missing','stale','wrong']:
            with self.subTest(mode=mode):
                x=fixture()
                if mode=='missing':x.pop('keyword_economics')
                if mode=='stale':x['keyword_economics']['retrieved_at']=(NOW-timedelta(days=31)).isoformat()
                if mode=='wrong':x['keyword_economics']['location_id']='wrong'
                a=assess(x,NOW);self.assertIsNone(a['opportunities'][0]['cpc_range']['low'])
                self.assertNotEqual(a['economics_state'],'CACHED — CURRENT')
                self.assertEqual(a['opportunities'][0]['organic']['impressions'],30)

    def test_i_approved_fixture_cannot_execute_and_changed_revision_rejects_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=OptimizationStore(Path(tmp)/'research.db');p=deepcopy(build_bundle(fixture(),NOW)['proposals'][0]);r=p['record']
            r.update(status='APPROVED',approved_by='human:fixture',approved_at=NOW.isoformat())
            store.record(r,p['detail']);self.assertFalse(store.execution_allowed(r))
            self.assertFalse(store.execution_allowed({'status':'EXECUTING'}))
            r['revision']=2
            with self.assertRaisesRegex(ValueError,'inherit approval'):store.record(r,p['detail'])

    def test_j_rejected_revision_and_learning_evidence_remain_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=OptimizationStore(Path(tmp)/'research.db');p=build_bundle(fixture(),NOW)['proposals'][0]
            store.record(p['record'],p['detail']);saved=store.rows()[0]
            store.review(saved['record']['proposal_id'],1,saved['payload_hash'],'REJECT','human:fixture',NOW)
            row=store.rows()[0];self.assertEqual(row['effective_status'],'REJECTED');self.assertEqual(row['record'],saved['record'])
            self.assertFalse(store.execution_allowed(row))

    def test_k_language_assets_are_independent_and_within_native_limits(self):
        b=build_bundle(fixture(),NOW)
        p=[r for r in b['proposals'] if r['record']['proposal_type']=='GOOGLE_ADS_CAMPAIGN'];self.assertEqual(len(p),4)
        self.assertEqual({r['detail']['language'] for r in p},{'FR','EN'})
        for r in p:
            ad=r['detail']['ad_groups'][0]['responsive_search_ad']
            self.assertTrue(all(len(s)<=30 for s in ad['headlines']));self.assertTrue(all(len(s)<=90 for s in ad['descriptions']))
            self.assertTrue(all(k['match_types']==['EXACT','PHRASE'] for k in r['detail']['ad_groups'][0]['keywords']))

    def test_l_strong_organic_considers_incremental_value(self):
        x=fixture();x['google']['reads']['gsc_queries']['data']['rows'][0]['position']=3
        r=assess(x,NOW)['opportunities'][0];self.assertEqual(r['channels'][0],'SEO')
        self.assertIn('incremental',r['reasons'][-1])

    def test_shared_revision_replay_conflict_concurrency_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=OptimizationStore(Path(tmp)/'research.db');p=build_bundle(fixture(),NOW)['proposals'][0]
            store.rows()  # Initialize schema before race.
            with ThreadPoolExecutor(max_workers=2) as pool:
                states=list(pool.map(lambda _:store.record(p['record'],p['detail'])['state'],range(2)))
            self.assertEqual(sorted(states),['EXACT_REPLAY','RECORDED']);self.assertEqual(len(store.rows()),1)
            changed=deepcopy(p);changed['detail']['objective']='Changed'
            with self.assertRaisesRegex(ValueError,'Immutable'):store.record(changed['record'],changed['detail'])
            bundle=build_bundle(fixture(),NOW);persist(bundle,store)
            with store.connect() as db:first=db.execute('SELECT count(*) FROM optimization_records').fetchone()[0]
            persist(build_bundle(fixture(),NOW+timedelta(minutes=1)),store)
            with store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM optimization_records').fetchone()[0],first)

    def test_native_transport_is_fixed_reporting_only_and_bounded(self):
        calls=[]
        def handle(request):
            calls.append(request);self.assertEqual(str(request.url),ENDPOINT)
            self.assertEqual(request.method,'POST');self.assertTrue(json.loads(request.content)['query'].startswith('SELECT '))
            return httpx.Response(200,json={'results':[]})
        r=AdsInventoryReader('fixture',transport=httpx.MockTransport(handle),max_calls=1)
        self.addCleanup(r.close);self.assertEqual(r.read('campaigns',now=NOW)['state'],'WORKING')
        with self.assertRaises(ValueError):r.read('mutate',now=NOW)
        with self.assertRaises(ValueError):r.read('keywords',now=NOW)
        self.assertEqual(len(calls),1)

    def test_failed_source_is_not_empty_success_and_pagination_is_partial(self):
        for status in [401,403,429]:
            with self.subTest(status=status):
                r=AdsInventoryReader('fixture',transport=httpx.MockTransport(lambda _:httpx.Response(status,json={'error':{}})))
                try:self.assertNotEqual(r.read('campaigns',now=NOW)['state'],'WORKING')
                finally:r.close()
        r=AdsInventoryReader('fixture',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'results':[],'nextPageToken':'more'})))
        try:self.assertFalse(r.read('keywords',now=NOW)['complete'])
        finally:r.close()

    def test_today_priorities_require_live_read_only_and_do_not_execute(self):
        b=build_bundle(fixture(),NOW)
        view=build_today({},{},{},{},{},now=NOW,ads_intelligence={'scope':'live','read_only':True,'priorities':[p['record'] for p in b['priorities']]})
        self.assertEqual(len(view['sections']['Approvals']),3)
        self.assertTrue(all('no execution' in r['next_action'] for r in view['sections']['Approvals']))


class AdsOperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'automation.db';self.store=AutomationStore(self.db)
        self.optimization=OptimizationStore(self.db.with_name('phase12-autonomy.db'))
        p=build_bundle(fixture(),NOW)['proposals'][0];p['record']['business_problem']='<script>bad()</script>'
        self.optimization.record(p['record'],p['detail']);self.row=self.optimization.rows()[0]
        verifier=SimpleNamespace(verify=lambda token:AccessPrincipal(subject='owner',email='fixture@example.invalid',actor='human:fixture') if token=='fixture' else self.denied())
        provider=SimpleNamespace(request=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('No provider effect permitted')))
        app=FastAPI();install_phase7_canary_routes(app,verifier=verifier,client=provider,store=self.store,
            account_id='12345',from_address='fixture@example.invalid',allowed_origin='https://owner.example',clock=lambda:NOW)
        self.client=TestClient(app);self.auth={'Cf-Access-Jwt-Assertion':'fixture'}
    def denied(self):raise ValueError('unauthenticated')

    def test_authenticated_preview_escaped_and_private(self):
        path='/v1/operator/acquisition?proposal_id='+self.row['record']['proposal_id']
        self.assertEqual(self.client.get(path).status_code,401)
        r=self.client.get(path,headers=self.auth);self.assertEqual(r.status_code,200)
        self.assertIn('&lt;script&gt;',r.text);self.assertNotIn('<script>bad()',r.text)
        self.assertIn('no-store',r.headers['cache-control']);self.assertIn('Complete preview',r.text)

    def test_review_origin_exact_hash_rejection_and_no_approval_grant(self):
        path='/v1/operator/acquisition/proposal/'+self.row['record']['proposal_id']+'/review'
        data={'revision':'1','payload_hash':self.row['payload_hash'],'choice':'REVIEWED'}
        self.assertEqual(self.client.post(path,data=data,headers=self.auth).status_code,403)
        headers={**self.auth,'Origin':'https://owner.example'}
        self.assertEqual(self.client.post(path,data={**data,'payload_hash':'stale'},headers=headers).status_code,409)
        self.assertEqual(self.client.post(path,data={**data,'choice':'APPROVED'},headers=headers).status_code,409)
        self.assertEqual(self.client.post(path,data=data,headers=headers).status_code,200)
        self.assertFalse(self.optimization.execution_allowed(self.optimization.rows()[0]))


class AdsReleaseTests(unittest.TestCase):
    def test_release_preserves_all_previous_authority(self):
        import importlib.util
        import test_phase20_release_preservation as previous
        root=Path(__file__).resolve().parents[3]
        spec=importlib.util.spec_from_file_location('phase33_stage',root/'ops/phase33/stage_runtime.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
        t=previous.ReleasePreservationTests();prior=t.fixture();saved=deepcopy(prior)
        i,c,a=stage.preserved(prior,Path('/immutable/new/source'),t.helper())
        self.assertEqual(prior,saved)
        for x,y in ((i['lifecycle'],saved['internal_policy']['lifecycle']),(c,saved['customer_policy'])):
            for k in ('enabled','external_enabled','real_scopes','test_scopes','activated_at','expires_at'):
                if k in y:self.assertEqual(x[k],y[k])
        self.assertEqual(a['run'],saved['internal_activation']['run'])
