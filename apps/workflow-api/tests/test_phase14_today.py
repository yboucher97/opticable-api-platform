from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from workflow.automation.business_autonomy import Action,BusinessJournal,Policy,decide
from workflow.automation.today import TodaySources,build_today,render_today
from workflow.operator_phase7_api import install_phase7_canary_routes

NOW=datetime(2026,10,2,tzinfo=timezone.utc)


class TodayTests(unittest.TestCase):
    def test_test_and_historical_exceptions_are_excluded_from_current_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=BusinessJournal(Path(tmp)/'actions.db')
            for i,ownership in enumerate(('TEST_ONLY','PROTECTED','UNKNOWN','REAL')):
                action=Action('crm.task.create','Leads',str(i+1),'fixture:'+str(i),{},expected_version=NOW.isoformat())
                journal.prepare(action,decide(action,ownership,Policy()))
            view=journal.view()
            self.assertEqual(view['summary']['auto_actions_today'],0)
            self.assertIn('TEST_ONLY',view['attention_scopes']);self.assertIn('HISTORICAL',view['attention_scopes'])
            today=build_today({}, {}, {},view,{'signals':[]},now=NOW)
            self.assertEqual(today['attention_count'],0)
            self.assertTrue(all(x['ownership']!='REAL' or x['attention_scope']=='RESOLVED' for x in view['actions']))
    def test_live_categories_context_due_freshness_and_escaped_drill_down(self):
        sales={'scope':'live','read_at':'Fresh fixture time','rows':[
            dict(id='1',name='<script>alert(1)</script>',priority='HIGH',followup='DUE',deadline='Today',reason='Known deadline',action='Review follow-up'),
            dict(id='2',name='Test',priority='HIGH',test_only=True,followup='DUE')]}
        lifecycle={'scope':'live','read_at':'Service fixture time','rows':[
            dict(account='Customer',maintenance_due=True,reason='Service due',action='Review maintenance',next_review='Today') ]}
        view=build_today(sales,lifecycle,{}, {'actions':[]},{'signals':[]},now=NOW)
        self.assertEqual(view['attention_count'],2)
        rendered=render_today(view)
        self.assertNotIn('<script>',rendered);self.assertIn('&lt;script&gt;',rendered)
        self.assertIn('/v1/operator/phase8/sales-queue#lead-1',rendered)
        self.assertIn('Fresh fixture time',rendered);self.assertNotIn('<form',rendered)
        with self.assertRaisesRegex(ValueError,'live'):build_today({'scope':'lab'}, {}, {},{}, {'signals':[]})
    def test_display_cache_preserves_source_time_and_does_not_cache_failed_reads(self):
        sources=TodaySources(object(),Path('/fixture/automation.db'),'1','fixture@example.test')
        with patch('workflow.automation.today.build_sales_queue',side_effect=[ValueError('incomplete'),{'scope':'live','read_at':'original'}]) as build:
            with self.assertRaises(ValueError):sources.read('sales',NOW)
            first=sources.read('sales',NOW);first['read_at']='tampered'
            self.assertEqual(sources.read('sales',NOW)['read_at'],'original')
            self.assertEqual(build.call_count,2)
    def test_today_and_system_health_authenticate_before_reads_and_remain_private(self):
        class Verifier:
            def verify(self,token):
                if token!='fixture':raise ValueError('missing')
                return SimpleNamespace(subject='fixture',actor='fixture')
        with tempfile.TemporaryDirectory() as tmp:
            app=FastAPI();path=Path(tmp)/'automation.db'
            install_phase7_canary_routes(app,verifier=Verifier(),client=object(),store=SimpleNamespace(db_path=path),
                account_id='1',from_address='fixture@example.test',allowed_origin='https://example.test',clock=lambda:NOW)
            http=TestClient(app)
            with patch.object(TodaySources,'read',return_value={'scope':'live'}) as read:
                for route in ('/v1/operator','/v1/operator/today','/v1/operator/system-health','/v1/operator/recurring','/v1/operator/marketing','/v1/operator/business'):
                    self.assertEqual(http.get(route).status_code,401)
                read.assert_not_called()
                for route in ('/v1/operator/today','/v1/operator/system-health'):
                    response=http.get(route,headers={'Cf-Access-Jwt-Assertion':'fixture'})
                    self.assertEqual(response.status_code,200)
                    self.assertIn('no-store',response.headers['cache-control'])
                    self.assertEqual(response.headers['x-frame-options'],'DENY')
                self.assertEqual(read.call_count,3)


if __name__=='__main__':unittest.main()
