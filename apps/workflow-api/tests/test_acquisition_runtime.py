from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,tempfile,unittest
from workflow.automation import acquisition_runtime as runtime
from workflow.automation.acquisition_store import AcquisitionStore

NOW=datetime(2026,10,3,23,tzinfo=timezone.utc)


class AcquisitionRuntimeTests(unittest.TestCase):
    def fixture(self,root,old=False):
        at=(NOW-timedelta(days=3) if old else NOW).isoformat()
        google={'at':at,'reads':{'gsc_queries':{'state':'WORKING','observed_at':at,'data':{'rows':[
            {'keys':['commercial wifi installation','https://opticable.ca/en/services/commercial-wifi-installation/'],
             'impressions':12,'clicks':0,'position':14}]}}}}
        (root/'inputs.json').write_text(json.dumps({'schema':1,'at':NOW.isoformat(),'google':google}))
        saved={'apollo.json':{'at':NOW.isoformat(),'contacts_complete':True,'contacts':[],'accounts':[]},
               'crm.json':{'at':NOW.isoformat(),'crm':{}},'permits.json':{'at':NOW.isoformat(),'records':[]},
               'public-triggers.json':{'at':NOW.isoformat(),'signals':[]}}
        def trusted(path,*args):return saved[path.name] if path.name in saved else json.loads(path.read_text())
        return trusted

    def test_dry_run_and_independent_stop_do_not_read_provider_or_write_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);trusted=self.fixture(root,old=True)
            with patch.object(runtime,'ROOT',root),patch.object(runtime.lc,'trusted_json',side_effect=trusted),patch.object(runtime,'AcquisitionStore') as store,patch('workflow.google_oauth.GoogleOAuthManager') as oauth:
                r=runtime.observe(SimpleNamespace(dry_run=True),None,now=NOW)
                self.assertIn('DRY_RUN',r['state']);oauth.assert_not_called();store.assert_not_called()
                (root/'STOP').touch();self.assertEqual(runtime.observe(SimpleNamespace(dry_run=True),None,now=NOW)['state'],'DISABLED')
                self.assertFalse((root/'view.json').exists())

    def test_fresh_cache_has_no_provider_calls_and_replay_keeps_facts_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);trusted=self.fixture(root);db=root/'existing-journal.db';display=root/'display.json'
            with patch.object(runtime,'ROOT',root),patch.object(runtime,'DATABASE',db),patch.object(runtime,'DISPLAY',display),patch.object(runtime.lc,'trusted_json',side_effect=trusted),patch.object(runtime.os,'chown'),patch.object(runtime.grp,'getgrnam',return_value=SimpleNamespace(gr_gid=1)),patch('workflow.google_oauth.GoogleOAuthManager') as oauth:
                first=runtime.observe(SimpleNamespace(dry_run=False),None,now=NOW)
                second=runtime.observe(SimpleNamespace(dry_run=False),None,now=NOW+timedelta(minutes=1))
                oauth.assert_not_called();self.assertEqual(first['facts'],second['facts']);self.assertEqual(first['counts'],second['counts'])
                self.assertEqual(first['crm_promotions'],0);self.assertEqual(display.stat().st_mode&0o777,0o640)
                self.assertNotIn('queries',json.loads(display.read_text()))

    def test_provider_failure_retains_old_proof_and_cools_down_without_hiding_staleness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);trusted=self.fixture(root,old=True);db=root/'existing-journal.db'
            with patch.object(runtime,'ROOT',root),patch.object(runtime,'DATABASE',db),patch.object(runtime,'DISPLAY',root/'display.json'),patch.object(runtime.lc,'trusted_json',side_effect=trusted),patch.object(runtime.os,'chown'),patch.object(runtime.grp,'getgrnam',return_value=SimpleNamespace(gr_gid=1)),patch('workflow.google_oauth.GoogleOAuthManager',side_effect=ValueError('grant unavailable')) as oauth:
                first=runtime.observe(SimpleNamespace(dry_run=False),SimpleNamespace(google_oauth=None),now=NOW)
                health=next(r for r in first['source_health'] if r['source']=='search_console')
                self.assertEqual(health['state'],'PARTIAL');self.assertTrue(health['stale'])
                self.assertEqual(health['observed_at'],(NOW-timedelta(days=3)).isoformat())
                fact=AcquisitionStore(db).view('KEYWORD')[0]['facts'][0]
                self.assertEqual(fact['observed_at'],health['observed_at'])
                runtime.observe(SimpleNamespace(dry_run=False),SimpleNamespace(google_oauth=None),now=NOW+timedelta(minutes=1))
                self.assertEqual(oauth.call_count,1)
