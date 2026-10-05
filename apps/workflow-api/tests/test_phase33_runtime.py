"""Budgets, failed-read memory, exact revisions and honest invocation origin."""
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,tempfile,unittest
from workflow.automation import ads_runtime as runtime
from workflow.automation.optimization_store import OptimizationStore
from test_phase33_ads import fixture,NOW


class AdsRuntimeTests(unittest.TestCase):
    def test_dry_run_and_independent_stop_do_not_read_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(runtime,'ROOT',root),patch('workflow.google_oauth.GoogleOAuthManager') as oauth:
                self.assertIn('DRY_RUN',runtime.observe(SimpleNamespace(dry_run=True),None,now=NOW)['state'])
                (root/'ADS_STOP').touch();self.assertEqual(runtime.observe(SimpleNamespace(dry_run=False),None,now=NOW)['state'],'DISABLED')
                oauth.assert_not_called();self.assertEqual(len(list(root.iterdir())),1)

    def seeded(self,root,*,old=False):
        x=fixture()
        if old:x['ads']['at']=(NOW-timedelta(days=8)).isoformat()
        (root/'ads-inventory.json').write_text(json.dumps(x['ads']))
        (root/'google-current.json').write_text(json.dumps(x['google']))
        (root/'keyword-economics.json').write_text(json.dumps(x['keyword_economics']))
        (root/'ads-context.json').write_text(json.dumps({'website':x['website'],'phase32_at':NOW.isoformat()}))
        return x

    def context(self,root):
        from contextlib import ExitStack
        stack=ExitStack()
        for name,value in [('ROOT',root),('DATABASE',root/'existing-journal.db'),('DISPLAY',root/'display.json')]:stack.enter_context(patch.object(runtime,name,value))
        stack.enter_context(patch.object(runtime.lc,'trusted_json',side_effect=lambda p,*_:json.loads(p.read_text())))
        stack.enter_context(patch.object(runtime.os,'chown'));stack.enter_context(patch.object(runtime.grp,'getgrnam',return_value=SimpleNamespace(gr_gid=1)))
        return stack

    def test_fresh_cache_replay_retains_counts_and_has_no_provider_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.seeded(root)
            with self.context(root),patch('workflow.google_oauth.GoogleOAuthManager') as oauth:
                first=runtime.observe(SimpleNamespace(dry_run=False),None,now=NOW,origin='MANUAL')
                second=runtime.observe(SimpleNamespace(dry_run=False),None,now=NOW+timedelta(minutes=1),origin='UNATTENDED')
                oauth.assert_not_called();self.assertEqual(first['proposal_count'],8);self.assertEqual(second['proposal_count'],8)
                self.assertEqual(second['preparation_origin'],'MANUAL')
                self.assertEqual(second['collection_origin'],'UNKNOWN')
                self.assertEqual(first['hook_count'],14);self.assertFalse(second['execution_authorized'])
                self.assertLess(len(json.dumps(second).encode()),262144)
                self.assertEqual((root/'display.json').stat().st_mode&0o777,0o640)

    def test_failed_refresh_preserves_old_evidence_and_cools_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);x=self.seeded(root,old=True)
            with self.context(root),patch('workflow.google_oauth.GoogleOAuthManager',side_effect=ValueError('token unavailable')) as oauth:
                first=runtime.observe(SimpleNamespace(dry_run=False),SimpleNamespace(google_oauth=None),now=NOW,origin='MANUAL')
                second=runtime.observe(SimpleNamespace(dry_run=False),SimpleNamespace(google_oauth=None),now=NOW+timedelta(minutes=1),origin='MANUAL')
                self.assertEqual(oauth.call_count,1);self.assertEqual(first['source_health']['last_successful_read'],x['ads']['at'])
                self.assertEqual(second['source_health']['state'],'STALE / SOURCE UNAVAILABLE')
                self.assertEqual(json.loads((root/'ads-inventory.json').read_text())['at'],x['ads']['at'])
                self.assertEqual(first['proposal_count'],8);self.assertEqual(first['inventory']['campaigns'],1)

    def test_changed_evidence_creates_revision_and_rejection_does_not_rearm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.seeded(root)
            with self.context(root):
                runtime.observe(SimpleNamespace(dry_run=False),None,now=NOW,origin='MANUAL')
                store=OptimizationStore(root/'existing-journal.db');row=store.rows()[0]
                store.review(row['record']['proposal_id'],1,row['payload_hash'],'REJECT','human:fixture',NOW)
                view=runtime.observe(SimpleNamespace(dry_run=False),None,now=NOW+timedelta(minutes=1),origin='MANUAL')
                self.assertTrue(any(r['status']=='REJECTED' for r in view['proposals']))
                context=json.loads((root/'ads-context.json').read_text());context['phase32_at']=(NOW+timedelta(seconds=1)).isoformat()
                (root/'ads-context.json').write_text(json.dumps(context))
                runtime.observe(SimpleNamespace(dry_run=False),None,now=NOW+timedelta(minutes=2),origin='MANUAL')
                current=next(r for r in store.rows() if r['record']['proposal_id']==row['record']['proposal_id'])
                self.assertEqual(current['record']['revision'],2);self.assertIsNone(current['review'])
                self.assertIsNone(current['record']['approved_by']);self.assertFalse(store.execution_allowed(current))

    def test_manual_shell_does_not_claim_an_unattended_invocation(self):
        with patch.dict(runtime.os.environ,{},clear=True):self.assertEqual(runtime.invocation_origin(),'MANUAL')
