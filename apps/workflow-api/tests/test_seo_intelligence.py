from datetime import datetime,timezone,timedelta
from pathlib import Path
import json,tempfile,time,unittest
from workflow.automation.seo_intelligence import (page_inventory,technical_audit,content_opportunity,repurpose,build_content,own_url,enrich)
from workflow.automation.acquisition_store import AcquisitionStore

NOW=datetime(2026,10,3,23,tzinfo=timezone.utc)
URL='https://opticable.ca/en/services/commercial-wifi-installation/'

def raw(url=URL,*,lang='en-CA',service='Commercial Wi-Fi installation'):
    return {'url':url,'status':200,'robots_allowed':True,'in_sitemap':True,'retrieved_at':NOW.isoformat(),
        'html':f'''<html lang="{lang}"><head><title>{service}</title><meta name="description" content="Commercial site assessment and network design"><meta name="robots" content="index,follow"><link rel="canonical" href="{url}"><link rel="alternate" hreflang="{lang}" href="{url}"><script type="application/ld+json">{{"@type":"Service"}}</script><script>private tracking code excluded</script></head><body><main><h1>{service}</h1><h2>Coverage</h2><p>{'Real equipment and site assessment. '*80}</p><a href="/en/contact/">Request quote</a><a href="tel:+15145551234">Call</a></main></body></html>'''}

class WebsiteInventoryTests(unittest.TestCase):
    def test_metadata_structure_language_links_cta_and_no_fake_indexing(self):
        p=page_inventory(raw());self.assertEqual(p['language'],'EN');self.assertEqual(len(p['h1']),1)
        self.assertEqual(p['service'],'Commercial Wi-Fi');self.assertTrue(p['cta']['phone']);self.assertTrue(p['cta']['quote'])
        self.assertTrue(p['indexable_candidate']);self.assertIsNone(p['indexed']);self.assertEqual(p['structured_data'][0]['@type'],'Service')
        self.assertNotIn('private tracking',p['content_excerpt']);self.assertEqual(p['issues'],[])
    def test_noindex_http_errors_and_empty_responses_are_not_crawlable_content(self):
        for changes in ({'status':404},{'robots_allowed':False},{'html':''}):
            with self.subTest(changes=changes):self.assertFalse(page_inventory({**raw(),**changes})['crawlable'])
        r=raw();r['x_robots_tag']='noindex';self.assertFalse(page_inventory(r)['indexable_candidate'])
    def test_invalid_jsonld_missing_metadata_canonical_conflict(self):
        r=raw();r['html']=r['html'].replace('{"@type":"Service"}','{bad}').replace('<title>Commercial Wi-Fi installation</title>','').replace('href="'+URL+'"','href="https://opticable.ca/other/"',1)
        p=page_inventory(r);self.assertIn('Invalid JSON-LD',p['issues']);self.assertIn('Missing title',p['issues']);self.assertIn('Canonical points elsewhere — inspect intent',p['issues'])
    def test_duplicate_diagnostics_and_normal_redirect_alias_distinct(self):
        a=page_inventory(raw());b=page_inventory(raw('https://opticable.ca/en/second/'))
        self.assertTrue(any(r['issue']=='Duplicate title' for r in technical_audit([a,b])['issues']))
        b['redirect_chain']=[{'to':URL}];self.assertFalse(any(r['issue']=='Duplicate title' for r in technical_audit([a,b])['issues']))
    def test_service_index_not_a_specific_service_page(self):
        p=page_inventory(raw('https://opticable.ca/en/services/'));self.assertEqual(p['page_type'],'SERVICE INDEX');self.assertIsNone(p['service'])
    def test_hreflang_reciprocity_and_orphan_scope_is_bounded(self):
        a=page_inventory(raw());b=page_inventory(raw('https://opticable.ca/fr/services/wifi/',lang='fr-CA'))
        a['hreflang']['fr-CA']=b['url'];report=technical_audit([a,b])
        self.assertTrue(any('reciprocity' in i['issue'] for i in report['issues']));self.assertIn('bounded',report['orphan_scope'])
    def test_crawler_url_boundaries(self):
        for u in ('http://opticable.ca/','https://evil.test/','https://opticable.ca.evil.test/','https://user:pass@opticable.ca/','https://opticable.ca:bad/'):
            with self.subTest(url=u):self.assertFalse(own_url(u))
        self.assertTrue(own_url(URL))

class ContentDecisionTests(unittest.TestCase):
    def test_high_commercial_missing_page_new_brief_not_publication(self):
        r=content_opportunity({'query':'commercial wifi installation','language':'EN','market_volume':1000},[])
        self.assertEqual(r['decision'],'NEW PAGE CANDIDATE');self.assertFalse(r['publication_allowed'])
    def test_position_fourteen_improve_existing_not_duplicate(self):
        p=page_inventory(raw());r=content_opportunity({'query':'commercial wifi installation','language':'EN','page':URL,'impressions':100,'position':14},[p])
        self.assertEqual(r['decision'],'IMPROVE EXISTING PAGE');self.assertEqual(r['existing_page'],URL);self.assertIn('existing_near_page_one',r['score_components'])
    def test_existing_language_counterpart_does_not_substitute_wrong_language(self):
        r=content_opportunity({'query':'installation wifi commercial','language':'FR'},[page_inventory(raw())])
        self.assertEqual(r['decision'],'NEW PAGE CANDIDATE');self.assertIsNone(r['existing_page'])
    def test_fallback_page_does_not_borrow_other_language_or_url_ranking(self):
        p=page_inventory(raw());other='https://opticable.ca/fr/services/installation-wifi-commercial/'
        r=content_opportunity({'query':'commercial wifi installation','language':'EN','page':other,'position':14,'impressions':100},[p])
        self.assertEqual(r['existing_page'],URL);self.assertIsNone(r['selected_page_position'])
        self.assertNotIn('existing_near_page_one',r['score_components']);self.assertIn('different',r['evidence']['metric_scope'])
    def test_generic_informational_volume_not_priority_over_commercial(self):
        a=content_opportunity({'query':'commercial wifi installation','language':'EN','market_volume':100},[])
        b=content_opportunity({'query':'what is wifi','language':'EN','market_volume':1000000},[])
        self.assertGreater(a['score'],b['score']);self.assertEqual(b['decision'],'LOWER PRIORITY EDUCATION')
    def test_little_search_large_company_market_no_seo_page(self):
        r=content_opportunity({'query':'managed network','language':'EN','market_volume':0,'addressable_companies':200},[])
        self.assertEqual(r['decision'],'NO SEO PAGE — OUTBOUND RESEARCH');self.assertFalse(r['publication_allowed'])
    def test_query_variants_one_existing_page_brief_replay_stable(self):
        p=page_inventory(raw());q=[{'query':s,'impressions':50,'position':14,'page':URL} for s in ('commercial wifi installation','commercial wireless solutions')]
        a=build_content(q,[p]);b=build_content(q,[p]);self.assertEqual(len(a['content_queue']),1);self.assertEqual(a,b)
        self.assertEqual(sum(a['keyword_universe']['languages'].values()),a['keyword_universe']['count'])
    def test_repurpose_only_owner_proven_facts_and_no_sends(self):
        brief=content_opportunity({'query':'commercial wifi installation','language':'EN'},[]);r=repurpose(brief)
        self.assertEqual(len(r['assets']),6);self.assertTrue(all(a['state']=='BRIEF — NOT PUBLISHED' for a in r['assets']));self.assertIn('unverified',r['false_claim_guard'])
    def test_paid_coordination_no_campaign_writer_and_missing_cpc_unknown(self):
        r=build_content([{'query':'commercial wifi installation','page':URL,'impressions':100,'position':35}],[page_inventory(raw())])
        self.assertIsNone(r['paid_opportunities'][0]['cpc']);self.assertFalse(r['paid_opportunities'][0]['changes_allowed']);self.assertIn('future paid',r['paid_opportunities'][0]['reason'])
    def test_bounded_inventory_performance_no_network(self):
        pages=[page_inventory(raw('https://opticable.ca/en/page-'+str(i)+'/')) for i in range(135)]
        at=time.monotonic();r=technical_audit(pages);self.assertEqual(r['pages_analyzed'],135);self.assertLess(time.monotonic()-at,1)
    def test_enrich_persists_each_page_and_native_index_proof_without_claiming_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=AcquisitionStore(Path(tmp)/'journal.db');inputs={'website':{'at':NOW.isoformat(),'pages':[raw()]},'market_research':{'at':NOW.isoformat(),'reads':{'gsc_inspect_wifi_en':{'state':'WORKING','data':{'inspectionResult':{'indexStatusResult':{'verdict':'PASS','userCanonical':URL,'googleCanonical':URL}}}}}}}
            v={'queries':[{'query':'commercial wifi installation','page':URL,'impressions':50,'position':14}],'competitors':[]}
            r=enrich(store,inputs,v,now=NOW);self.assertEqual(r['technical_seo']['indexed_verified'],1)
            self.assertEqual(len(store.view('OPTICABLE_PAGE')),1);self.assertGreater(len(store.view('CONTENT_TOPIC')),0)
            store.prune(NOW);self.assertEqual(len(store.view('OPTICABLE_PAGE')),1)
    def test_corrected_daily_metrics_preserved_and_old_history_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=AcquisitionStore(Path(tmp)/'journal.db')
            for value in (1,1,2):s.timeseries('search_console','2026-10-01',{'clicks':value},'snapshot-proof',NOW)
            self.assertEqual(s.summary(NOW)['daily_history_rows'],2)
            s.prune(NOW+timedelta(days=740));self.assertEqual(s.summary(NOW)['daily_history_rows'],0)
