from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile,unittest
from workflow.automation.keyword_economics import normalize,integrate
from workflow.automation.acquisition_store import AcquisitionStore
from workflow.automation.acquisition_intelligence import render_acquisition

NOW=datetime(2026,10,4,tzinfo=timezone.utc)

def fixture():
    result={'schema':1,'provider':'windsor_google_ads_keyword_planner','account':'6808491878',
            'currency':'CAD','location_id':'20123','retrieved_at':NOW.isoformat(),'requests':[],'replies':[]}
    for lang,code,seed in [('French','1002','câblage structuré'),('English','1000','commercial security cameras')]:
        result['requests'].append({'connector':'google_ads','accounts':['680-849-1878'],
                 'date_from':'2025-10-01','date_to':'2026-09-30','options':{'language':code,
                    'geo_target_constants':'20123','keyword_plan_network':'GOOGLE_SEARCH','keyword_seeds':seed}})
        result['replies'].append({'status':'done','data':[{'keyword':seed,'keyword_country':'Quebec',
                 'keyword_language':lang,'avg_monthly_searches':0 if code=='1002' else 20,
                 'keyword_competition':None if code=='1002' else 'HIGH','competition_index':0 if code=='1002' else 83,
                 'keyword_average_cpc':None if code=='1002' else 5290843,
                 'top_of_page_bid_low':None if code=='1002' else 7438719,'top_of_page_bid_high':None}]})
    return result

class EconomicsTests(unittest.TestCase):
    def test_unknown_zero_bid_and_cpc_semantics(self):
        rows=normalize(fixture(),now=NOW);fr,en=rows
        self.assertEqual(fr['market_volume'],0);self.assertIsNone(fr['cpc']);self.assertEqual(fr['competition_index'],0)
        self.assertEqual(en['cpc'],5.290843);self.assertEqual(en['low_bid'],7.438719)
        self.assertIsNone(en['observed_cpc']);self.assertIn('ESTIMATE',en['metric_basis'])
        self.assertIsNone(en['date_from']);self.assertIn('EXACT EFFECTIVE',en['window'])
    def test_geography_language_account_and_token_provenance_denial(self):
        for mutate in (lambda v:v.update(location_id='2840'),
                       lambda v:v['replies'][0]['data'][0].update(keyword_country='France'),
                       lambda v:v['replies'][0]['data'][0].update(keyword_language='English'),
                       lambda v:v['requests'][0].update(accounts=['another']),
                       lambda v:v.update(access_token='UNIT_TEST_ONLY')):
            v=fixture();mutate(v)
            with self.assertRaises(ValueError):normalize(v,now=NOW)
    def test_stale_is_not_refreshed_by_rebuild_and_future_time_rejected(self):
        value=fixture();value['retrieved_at']=(NOW-timedelta(days=31)).isoformat()
        self.assertTrue(all(r['stale'] for r in normalize(value,now=NOW)))
        value['retrieved_at']=(NOW+timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):normalize(value,now=NOW)
    def test_snapshot_and_normalized_replay_no_crm_or_provider_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=AcquisitionStore(Path(tmp)/'journal.db')
            view=integrate(store,fixture(),now=NOW);before=store.summary(NOW)
            integrate(store,fixture(),now=NOW+timedelta(seconds=1));after=store.summary(NOW)
            self.assertEqual(before['counts'],after['counts']);self.assertEqual(before['facts'],after['facts'])
            self.assertEqual(before['snapshots'],after['snapshots']);self.assertEqual(after['crm_promotions'],0)
            self.assertEqual(view['provider_calls_this_rebuild'],0);self.assertEqual(view['records'],2)
            self.assertFalse(store.due('windsor_keyword_planner',NOW+timedelta(days=29)))
            self.assertTrue(store.due('windsor_keyword_planner',NOW+timedelta(days=31)))
    def test_bounded_batch_and_no_whole_universe_enrichment(self):
        value=fixture()
        for reply in value['replies']:
            row=reply['data'][0];reply['data']=[{**row,'keyword':str(i)+' '+row['keyword']} for i in range(500)]
        self.assertEqual(len(normalize(value,now=NOW)),12)
    def test_owner_view_unknown_cost_is_not_zero_and_no_roi_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            view=integrate(AcquisitionStore(Path(tmp)/'journal.db'),fixture(),now=NOW)
        html=render_acquisition({'keyword_economics':view})
        self.assertIn('CPC estimate: Unknown',html);self.assertIn('Monthly searches: 0',html)
        self.assertNotIn('CPC estimate: 0 CAD',html)

if __name__=='__main__':unittest.main()
