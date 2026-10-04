from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,sqlite3,tempfile,unittest
import httpx
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from workflow.automation.acquisition_store import AcquisitionStore,aliases
from workflow.automation.acquisition_intelligence import market_priority,render_acquisition,language_for,intent_for
from workflow.automation.acquisition_sources import GoogleAcquisitionReader
from workflow.automation.acquisition_ingest import ingest

NOW=datetime(2026,10,3,23,tzinfo=timezone.utc)
URL='https://example.test/evidence'

class AcquisitionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=AcquisitionStore(Path(self.tmp.name)/'existing.db')
    def tearDown(self):self.tmp.cleanup()
    def record(self,kind,row,source='apollo',native='one'):
        return self.store.record(kind,row,source=source,native_id=native,url=URL,now=NOW)
    def test_same_company_three_sources_one_identity_multiple_proofs(self):
        a=self.record('COMPANY',{'name':'Company','domain':'WWW.Company.Test','apollo_organization_id':'a1'})
        b=self.record('COMPANY',{'name':'Legal company','domain':'company.test','registry_number':'1234567890'},'registry','r1')
        c=self.record('COMPANY',{'name':'New project','domain':'company.test'},'permit','p1')
        self.assertEqual(a['id'],b['id']);self.assertEqual(b['id'],c['id'])
        self.assertEqual(len(self.store.view('COMPANY')),1);self.assertEqual(len(self.store.view('COMPANY')[0]['facts']),3)
    def test_similar_names_and_distinct_units_not_merged(self):
        a=self.record('COMPANY',{'name':'Acme'},native='a');b=self.record('COMPANY',{'name':'Acme'},native='b')
        self.assertNotEqual(a['id'],b['id'])
        a=self.record('LOCATION',{'address':'1 Street','postal_code':'H1H1H1','unit':'1'},native='site1')
        b=self.record('LOCATION',{'address':'1 STREET','postal_code':'H1H 1H1','unit':'2'},native='site2')
        self.assertNotEqual(a['id'],b['id'])
    def test_email_native_identity_and_free_company_domains(self):
        a=self.record('PERSON',{'email':' P@Company.Test ','apollo_contact_id':'c1'})
        b=self.record('PERSON',{'email':'p@company.test','crm_contact_id':'42'},'crm','42')
        self.assertEqual(a['id'],b['id'])
        self.assertNotIn('domain:gmail.com',aliases('COMPANY',{'website':'gmail.com'},'one','a'))
        a=self.record('COMPANY',{'website':'https://facebook.com/company-a'},native='a')
        b=self.record('COMPANY',{'website':'https://facebook.com/company-b'},native='b')
        self.assertNotEqual(a['id'],b['id'])
    def test_conflicting_identifiers_never_silently_merge(self):
        self.record('COMPANY',{'domain':'a.test'},native='a');self.record('COMPANY',{'domain':'b.test'},native='b')
        r=self.record('COMPANY',{'domain':'a.test'},native='b')
        self.assertIn('IDENTITY CONFLICT',r['state']);self.assertEqual(len(self.store.view('COMPANY')),2)
    def test_facts_conflict_and_raw_snapshot_roundtrip(self):
        raw={'name':'Company','value':1};sid=self.store.snapshot('registry',URL,raw,NOW)
        self.store.record('COMPANY',{'domain':'company.test','status':'ACTIVE'},source='registry',native_id='r1',url=URL,now=NOW,snapshot=sid,raw=raw)
        self.record('COMPANY',{'domain':'company.test','status':'ENDING'},'apollo','a1')
        self.assertEqual({f['normalized_value']['status'] for f in self.store.view('COMPANY')[0]['facts']},{'ACTIVE','ENDING'})
        with self.store.connect() as db:
            import zlib
            self.assertEqual(json.loads(zlib.decompress(db.execute('SELECT raw FROM acquisition_snapshots').fetchone()[0])),raw)
    def test_replay_permit_one_trigger_and_no_crm_writer(self):
        r={'title':'Commercial renovation'}
        self.record('TRIGGER',r,'permit','p1');self.assertEqual(self.record('TRIGGER',r,'permit','p1')['state'],'REPLAY')
        self.assertEqual(len(self.store.view('TRIGGER')),1);self.assertEqual(self.store.summary(NOW)['crm_promotions'],0)
    def test_test_data_and_secrets_denied(self):
        for marker in ({'test_only':True},{'OptiBrain_Test':'true'},{'name':'OPTIBRAIN TEST'}):
            with self.subTest(marker=marker):self.assertEqual(self.record('COMPANY',marker)['state'],'TEST EXCLUDED')
        for value in ({'access_token':'secret'},{'nested':[{'api_key':'secret'}]}):
            with self.subTest(value=value),self.assertRaises(ValueError):self.store.snapshot('one',URL,value,NOW)
        for url in ('https://user:password@example.test/','https://example.test/?access_token=secret'):
            with self.subTest(url=url),self.assertRaises(ValueError):self.store.snapshot('one',url,{},NOW)
    def test_source_failure_isolation_cooldown_cache_and_retention(self):
        self.store.source('semrush','BLOCKED',NOW,reason='no callable tool')
        self.store.source('search_console','WORKING',NOW,cache_hit=True)
        self.assertFalse(self.store.due('semrush',NOW+timedelta(days=1)));self.assertTrue(self.store.due('search_console',NOW+timedelta(days=2)))
        for i in range(15):self.store.snapshot('one',URL,{'i':i},NOW+timedelta(days=i))
        self.store.prune(NOW+timedelta(days=15));self.assertEqual(self.store.summary(NOW)['snapshots'],12)
        self.assertEqual(self.store.summary(NOW)['source_health'][1]['state'],'BLOCKED')

class MarketDecisionTests(unittest.TestCase):
    def base(self):return {'service':'Commercial Wi-Fi','intent':'TRANSACTIONAL','geography':'Laval','recurring_potential':True,'market_volume':None,'cpc':None,'seo_difficulty':None,'contact_coverage':None,'paid_competition':None}
    def test_large_company_market_little_search_prefers_shadow_outbound(self):
        r=market_priority({**self.base(),'market_volume':0,'addressable_companies':200})
        self.assertEqual(r['channels'][0],'OUTBOUND — SHADOW RESEARCH');self.assertNotIn('SEO',r['channels']);self.assertFalse(r['cold_send_allowed'])
    def test_high_search_weak_organic_seo_plus_future_paid(self):
        r=market_priority({**self.base(),'market_volume':2000,'cpc':20,'position':35})
        self.assertIn('SEO',r['channels']);self.assertIn('GOOGLE ADS — OWNER REVIEW',r['channels'])
    def test_information_lower_than_commercial_and_unknown_metrics_not_invented(self):
        a=market_priority({**self.base(),'market_volume':3000});b=market_priority({**self.base(),'market_volume':3000,'intent':'INFORMATIONAL'})
        self.assertGreater(a['score'],b['score']);self.assertIsNone(a['cpc']);self.assertIn('cpc',a['missing_data'])
    def test_apollo_owner_prevents_competing_outbound_recommendation(self):
        r=market_priority({**self.base(),'addressable_companies':100,'outreach_owner':'CLAUDE_APOLLO'})
        self.assertFalse(any(c.startswith('OUTBOUND') for c in r['channels']));self.assertFalse(r['crm_promote_allowed'])
    def test_real_feedback_gradual_and_test_partial_excluded(self):
        base={**self.base(),'market_volume':1000}
        for o in ({'truth':'PARTIAL','test_only':False,'eligible_opportunities':100,'won':50},{'truth':'PROVEN','test_only':True,'eligible_opportunities':100,'won':50}):
            with self.subTest(o=o):self.assertEqual(market_priority(base,outcomes=o)['outcome_weight'],0)
        self.assertGreater(market_priority(base,outcomes={'truth':'PROVEN','test_only':False,'eligible_opportunities':100,'won':20})['outcome_weight'],.5)
    def test_fr_en_and_commercial_intent_independent(self):
        self.assertEqual(language_for('câblage structuré Laval'),'FR');self.assertEqual(language_for('commercial security cameras'),'EN')
        self.assertEqual(language_for('wifi'),'UNKNOWN');self.assertEqual(intent_for('shoplifting statistics'),'IRRELEVANT')

class FixedGoogleReadTests(unittest.TestCase):
    def test_only_fixed_reports_and_byte_request_budgets(self):
        seen=[]
        def handler(req):
            seen.append(req);return httpx.Response(200,json={'rows':[]})
        reader=GoogleAcquisitionReader('test-token',transport=httpx.MockTransport(handler),limit=2)
        try:
            reader.read('ads_campaigns',now=NOW);reader.read('gsc_queries',now=NOW)
            with self.assertRaises(ValueError):reader.read('uploadConversions',now=NOW)
            with self.assertRaises(ValueError):reader.read('ads_customer',now=NOW)
        finally:reader.close()
        self.assertTrue(json.loads(seen[0].content)['query'].startswith('SELECT'))
        self.assertNotIn('test-token',json.dumps({'result':'public evidence'}))
    def test_provider_denial_does_not_represent_empty_success(self):
        r=GoogleAcquisitionReader('test',transport=httpx.MockTransport(lambda req:httpx.Response(429)))
        try:self.assertEqual(r.read('gsc_sites',now=NOW)['state'],'RATE LIMITED')
        finally:r.close()

class AcquisitionIntegrationTests(unittest.TestCase):
    def test_owner_route_auth_precedes_reads_and_has_no_execution_method(self):
        from workflow.operator_phase7_api import install_phase7_canary_routes
        class Verifier:
            def verify(self,token):
                if token!='human':raise ValueError('Human identity required')
                return SimpleNamespace(actor='owner',subject='owner')
        with tempfile.TemporaryDirectory() as tmp:
            with patch('workflow.automation.today.read_internal_attention',return_value={'schema':1,'at':NOW.isoformat(),'scope':'live','read_only':True,'source_health':[]}) as read:
                app=FastAPI();install_phase7_canary_routes(app,verifier=Verifier(),client=object(),store=SimpleNamespace(db_path=Path(tmp)/'journal.db'),account_id='1',from_address='fixture@example.test',allowed_origin='https://example.test',clock=lambda:NOW)
                client=TestClient(app)
                for headers in ({},{'X-API-Key':'workflow-key'}):
                    with self.subTest(headers=headers):self.assertEqual(client.get('/v1/operator/acquisition',headers=headers).status_code,401)
                read.assert_not_called()
                r=client.get('/v1/operator/acquisition',headers={'Cf-Access-Jwt-Assertion':'human'})
                self.assertEqual(r.status_code,200);self.assertIn('no-store',r.headers['cache-control'])
                self.assertEqual(client.post('/v1/operator/acquisition',headers={'Cf-Access-Jwt-Assertion':'human'}).status_code,405)

    def test_pipeline_zero_leads_replay_and_escaped_private_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=AcquisitionStore(Path(tmp)/'journal.db')
            inputs={'schema':1,'at':NOW.isoformat(),'apollo':{'at':NOW.isoformat(),'contacts_complete':True,'contacts':[],'accounts':[{'id':'test1','name':'OPTIBRAIN TEST ONLY'}]},
                    'gsc':[{'query':'commercial wifi installation','page':'https://opticable.ca/en/services/commercial-wifi-installation/','impressions':100,'clicks':1,'position':14}],
                    'signals':[{'key':'permit1','source':'montreal_permit','record_id':'p1','trigger':'<script>Renovation</script>','why_now':'Commercial permit','source_url':URL,'fit':'structured cabling'}]}
            a=ingest(store,inputs,now=NOW);b=ingest(store,inputs,now=NOW)
            self.assertEqual(a['counts'],b['counts']);self.assertEqual(a['facts'],b['facts']);self.assertEqual(a['counts']['TRIGGER'],1)
            self.assertFalse(a['cold_outbound_enabled']);self.assertEqual(a['crm_promotions'],0)
            html=render_acquisition(a);self.assertNotIn('<script>',html);self.assertIn('Market-based priorities',html)
