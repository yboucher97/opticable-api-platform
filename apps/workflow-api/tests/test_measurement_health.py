from datetime import datetime,timezone
import unittest
from workflow.automation.measurement_health import collection_health

NOW=datetime(2026,10,4,tzinfo=timezone.utc)
def report(date,host='opticable.ca'):
    return {'state':'WORKING','data':{'rows':[{'dimensionValues':[{'value':x} for x in (date,'page_view',host)],'metricValues':[{'value':'1'}]}]}}

class CollectionHealthTests(unittest.TestCase):
    def test_auth_is_separate_from_collection_and_zero_is_not_assumed(self):
        h=collection_health({'state':'WORKING','data':{'rows':[]}},now=NOW)
        self.assertEqual(h['auth_status'],'GREEN');self.assertEqual(h['collection_status'],'NO RECENT DATA')
        self.assertIsNone(h['last_observed_data']);self.assertIn('do not prove zero',h['coverage_notes'])
    def test_production_freshness_and_toronto_boundary(self):
        h=collection_health(report('20261003'),now=NOW)
        self.assertEqual(h['collection_status'],'FRESH');self.assertEqual(h['latest_events']['page_view'],'2026-10-03')
        self.assertEqual(h['site_status']['opticable.ca']['status'],'FRESH')
        self.assertEqual(h['site_status']['ai.opticable.ca']['status'],'NO RECENT DATA')
        self.assertIsNone(collection_health(report('20261004'),now=NOW)['last_observed_data'])
    def test_stale_and_preview_exclusion(self):
        self.assertEqual(collection_health(report('20260723'),now=NOW)['collection_status'],'NO RECENT DATA')
        self.assertIsNone(collection_health(report('20261003','localhost'),now=NOW)['last_observed_data'])
    def test_failed_refresh_preserves_dates_and_auth_problem(self):
        h=collection_health(report('20261003'),now=NOW,attempt={'state':'AUTH EXPIRED'})
        self.assertEqual(h['auth_status'],'AUTH EXPIRED');self.assertEqual(h['last_observed_data'],'2026-10-03')
