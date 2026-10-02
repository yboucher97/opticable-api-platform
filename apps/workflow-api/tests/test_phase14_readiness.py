from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from workflow.automation.store import AutomationStore
from workflow.automation.delta_sync import DeltaSync
from workflow.automation.provider_usage import ProviderUsage,record_call,record_response
from workflow.automation.readiness import build_readiness,age_seconds

NOW=datetime(2026,10,2,tzinfo=timezone.utc)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.store=AutomationStore(self.root/'automation.db')
        DeltaSync(self.store).initialize('zoho_crm','fixture','Leads',cursor=NOW.isoformat())
        self.native={'native_subscription_status':'verified','native_subscription_last_verified_at':NOW.isoformat()}
    def summary(self):
        return build_readiness(self.store,self.native,api_version='fixture',auth_configured=True,
                               runtime_path=self.root/'runtime.json',now=NOW)
    def test_http_liveness_does_not_hide_failed_checkpoint(self):
        with self.store._connect() as db:
            db.execute("UPDATE automation_sync_checkpoints SET status='failed',last_error='authentication_failed'")
        view=self.summary();by={s['name']:s for s in view['signals']}
        self.assertEqual(by['API']['state'],'OK')
        self.assertEqual(by['Delta checkpoint']['state'],'ACTION REQUIRED')
        self.assertEqual(view['state'],'ACTION REQUIRED')
    def test_missing_runtime_is_unknown_and_summary_has_no_side_effect(self):
        with self.store._connect() as db:before=db.execute('SELECT COUNT(*) FROM automation_audit').fetchone()[0]
        self.assertEqual(next(s for s in self.summary()['signals'] if s['name']=='Backup')['state'],'UNKNOWN')
        with self.store._connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM automation_audit').fetchone()[0],before)
    def test_native_drift_and_expiry_are_visible(self):
        self.native['native_subscription_status']='configuration_drift'
        self.assertEqual(next(s for s in self.summary()['signals'] if s['name']=='Native watch')['state'],'ACTION REQUIRED')
    def test_future_naive_and_stale_runtime_are_unknown(self):
        self.assertIsNone(age_seconds('2026-10-02T00:00:00',NOW))
        self.assertIsNone(age_seconds((NOW+timedelta(seconds=1)).isoformat(),NOW))
        (self.root/'runtime.json').write_text(json.dumps({'schema':1,'captured_at':(NOW-timedelta(hours=2)).isoformat(),'signals':[]}))
        self.assertIsNone(self.summary()['deployment_sha'])
    def test_provider_categories_methods_and_response_failures_are_counted(self):
        with ProviderUsage(self.root/'usage.db','fixture') as usage:
            for service,method,path in [('zohoapis','GET','/books/v3/invoices'),('sign','GET','/requests'),
                     ('forms','GET','/forms'),('cloudflare','PUT','/workers'),('github','GET','/repos'),('r2','HEAD',''),('mail','GET','/message/content')]:
                record_call(service,method,path)
            record_response('mail','GET','/message/content',401)
        self.assertEqual(usage.summary['calls_run'],7)
        self.assertEqual(usage.summary['calls']['books_get'],1)
        self.assertEqual(usage.summary['calls_by_method']['cloudflare::write'],1)
        self.assertEqual(usage.summary['details']['mail_content_get'],1)
        self.assertEqual(usage.summary['status'],'failed')
        self.assertNotIn('/message/',json.dumps(usage.summary))
    def test_usage_without_store_keeps_in_memory_observation(self):
        with ProviderUsage(None,'fixture') as usage:record_call('sign','GET','/fixture')
        self.assertEqual(usage.summary['calls']['sign_get'],1)


if __name__=='__main__':unittest.main()
