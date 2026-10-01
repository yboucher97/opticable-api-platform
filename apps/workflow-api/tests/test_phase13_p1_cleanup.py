from pathlib import Path
from datetime import timedelta
import json,os,sqlite3,tempfile,unittest
from unittest.mock import patch

from workflow.automation.phase9_form_receipts import FormReceiptLedger,collect_form_mail
from workflow.automation.read_inventory_cache import ChangedInventory
from workflow.automation.provider_usage import ProviderUsage,record_call
from workflow.automation.job_runtime import job_lock
from workflow.automation.operations import _batch
from test_phase9_form_receipts import NOW,DETAILS,HEADERS,HTML,MESSAGE


class Mail:
    def __init__(self):self.messages=[MESSAGE];self.calls=[];self.fail=False
    def request(self,service,method,path,**kwargs):
        self.calls.append((service,method,path,kwargs))
        if path.endswith('/search'):
            data=[{'messageId':m,'folderId':'777','fromAddress':DETAILS['fromAddress']} for m in self.messages]
        elif path.endswith('/details'):
            data={**DETAILS,'messageId':path.split('/')[-2]}
        elif path.endswith('/content'):
            if self.fail:raise ValueError('fixture outage')
            data={'content':HTML}
        else:
            headers={**HEADERS,'Message-ID':[f'<{path.split("/")[-2]}@public.zohoforms.com>']}
            data={'headerContent':headers}
        return {'ok':True,'data':{'data':data}}


class CleanupTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
    def test_mail_known_replay_cost_and_exactly_one_new_receipt(self):
        ledger=FormReceiptLedger(self.root/'forms.db');mail=Mail()
        first=collect_form_mail(mail,ledger,now=NOW);self.assertEqual(first['created'],1)
        mail.calls=[];second=collect_form_mail(mail,ledger,now=NOW+timedelta(minutes=5))
        self.assertEqual((second['created'],second['cache_hits'],len(mail.calls)),(0,1,1))
        mail.messages.append('99999999');mail.calls=[]
        third=collect_form_mail(mail,ledger,now=NOW+timedelta(minutes=10))
        self.assertEqual((third['created'],len(mail.calls),len(ledger.list())),(1,4,2))
        self.assertTrue(all(method=='GET' for _,method,_,_ in mail.calls))
    def test_mail_daily_revalidation_and_failed_checkpoint_preservation(self):
        ledger=FormReceiptLedger(self.root/'forms.db');mail=Mail();collect_form_mail(mail,ledger,now=NOW)
        state=ledger.poll_state('1083319000000008002');mail.fail=True
        with self.assertRaises(ValueError):collect_form_mail(mail,ledger,now=NOW+timedelta(days=1))
        self.assertEqual(ledger.poll_state('1083319000000008002'),state)
        mail.fail=False;mail.calls=[];result=collect_form_mail(mail,ledger,now=NOW+timedelta(days=1))
        self.assertEqual((result['created'],result['replayed'],len(mail.calls)),(0,1,4))
        self.assertTrue(result['full_scan'])
    def test_mail_changed_metadata_bypasses_cache(self):
        ledger=FormReceiptLedger(self.root/'forms.db');mail=Mail();collect_form_mail(mail,ledger,now=NOW)
        with ledger._connect() as db:db.execute("UPDATE mail_message_cache SET metadata_hash='changed'")
        mail.calls=[];collect_form_mail(mail,ledger,now=NOW+timedelta(minutes=5));self.assertEqual(len(mail.calls),4)
    def test_mail_long_gap_requires_backfill_without_advance(self):
        ledger=FormReceiptLedger(self.root/'forms.db');mail=Mail();collect_form_mail(mail,ledger,now=NOW)
        before=ledger.poll_state('1083319000000008002')
        with self.assertRaisesRegex(ValueError,'backfill'):collect_form_mail(mail,ledger,now=NOW+timedelta(days=40))
        self.assertEqual(ledger.poll_state('1083319000000008002'),before)
    def test_mail_retention_never_prunes_receipts(self):
        ledger=FormReceiptLedger(self.root/'forms.db');mail=Mail();collect_form_mail(mail,ledger,now=NOW)
        with ledger._connect() as db:db.execute("UPDATE mail_message_cache SET seen_at='2000-01-01T00:00:00+00:00'")
        ledger.complete_poll('1083319000000008002',NOW,full_scan=True)
        with ledger._connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM mail_message_cache').fetchone()[0],0)
        self.assertEqual(len(ledger.list()),1)
    def test_usage_categories_budgets_retention_and_no_payload(self):
        path=self.root/'usage.db'
        with ProviderUsage(path,'fixture-job',runs_per_day=24,soft_budget=2) as usage:
            for service,method,p in [('zohoapis','GET','/crm/v8/Leads'),('zohoapis','PUT','/crm/v8/Leads'),('mail','GET','/mail'),('mail','POST','/mail'),('cloudflare','GET',''),('github','GET',''),('zohoapis','GET','/books/v3/invoices')]:record_call(service,method,p)
        self.assertTrue(usage.summary['budget_exceeded']);self.assertEqual(usage.summary['calls_day_estimate'],168)
        with sqlite3.connect(path) as db:
            self.assertNotIn('/crm/',db.execute('SELECT summary_json FROM provider_usage').fetchone()[0])
            db.execute("INSERT INTO provider_usage(job,recorded_at,summary_json) VALUES('old','2000-01-01','{}')")
        with ProviderUsage(path,'fixture-job'):pass
        with sqlite3.connect(path) as db:self.assertEqual(db.execute("SELECT count(*) FROM provider_usage WHERE job='old'").fetchone()[0],0)
    def test_usage_failure_does_not_mask_original_exception(self):
        with self.assertRaisesRegex(ValueError,'business failure'):
            with ProviderUsage(self.root/'missing'/'usage.db','fixture'):raise ValueError('business failure')
    def test_job_lock_overlap_stale_path_and_symlink(self):
        path=self.root/'job.lock'
        with job_lock(path) as first:
            self.assertTrue(first)
            with job_lock(path) as second:self.assertFalse(second)
        with job_lock(path) as next_run:self.assertTrue(next_run)
        other=self.root/'other.lock';other.symlink_to(path)
        with self.assertRaises(OSError):
            with job_lock(other):pass
    def test_inventory_delta_304_daily_full_and_no_write_authority(self):
        class CRM:
            calls=[];response={'ok':True,'status':200,'data':{'data':[{'id':'1','Name':'old'}],'info':{'more_records':False}}}
            def request(self,*args,**kwargs):self.calls.append(kwargs);return self.response
        client=CRM();path=self.root/'life.db';query={'fields':'id,Name','per_page':200,'page':1}
        snap=ChangedInventory(client,path,now=NOW);snap.request('zohoapis','GET','/crm/v8/Services',query=query);snap.commit()
        client.response={'ok':True,'status':304};snap=ChangedInventory(client,path,now=NOW+timedelta(hours=1))
        self.assertEqual(snap.request('zohoapis','GET','/crm/v8/Services',query=query)['data']['data'][0]['Name'],'old');snap.commit()
        self.assertIn('If-Modified-Since',client.calls[-1]['headers'])
        self.assertNotIn('.',client.calls[-1]['headers']['If-Modified-Since'])
        client.response={'ok':True,'status':200,'data':{'data':[{'id':'1','Name':'new'}]}}
        snap=ChangedInventory(client,path,now=NOW+timedelta(hours=2));self.assertEqual(snap.request('zohoapis','GET','/crm/v8/Services',query=query)['data']['data'][0]['Name'],'new');snap.commit()
        client.response={'ok':True,'status':204};snap=ChangedInventory(client,path,now=NOW+timedelta(days=1));self.assertEqual(snap.request('zohoapis','GET','/crm/v8/Services',query=query)['data']['data'],[]);self.assertNotIn('headers',client.calls[-1]);snap.commit()
        with self.assertRaisesRegex(ValueError,'authorize'):snap.request('zohoapis','PUT','/crm/v8/Services',body={})
    def test_inventory_partial_failure_never_advances_saved_cursor(self):
        class CRM:
            def request(self,*args,**kwargs):return {'ok':True,'status':200,'data':{'data':[{'id':'1'}],'info':{'more_records':True}}}
        path=self.root/'life.db';snap=ChangedInventory(CRM(),path,now=NOW)
        with self.assertRaises(ValueError):snap.request('zohoapis','GET','/crm/v8/Services',query={'fields':'id','per_page':200,'page':1})
        with sqlite3.connect(path) as db:self.assertEqual(db.execute('SELECT count(*) FROM crm_display_snapshots').fetchone()[0],0)
    def test_operations_batch_chunks_and_rejects_partial_duplicate_extra(self):
        class CRM:
            calls=0;mode='good'
            def request(self,*args,**kwargs):
                self.calls+=1;ids=kwargs['query']['ids'].split(',');rows=[{'id':i} for i in ids]
                if self.mode=='partial':rows=rows[:-1]
                if self.mode=='duplicate':rows[-1]=rows[0]
                if self.mode=='extra':rows.append({'id':'9999'})
                return {'ok':True,'data':{'data':rows,'info':{'more_records':False}}}
        crm=CRM();self.assertEqual(len(_batch(crm,'Accounts',[str(i) for i in range(1,202)])),201);self.assertEqual(crm.calls,3)
        for mode in ['partial','duplicate','extra']:
            crm.mode=mode
            with self.subTest(mode=mode),self.assertRaises(ValueError):_batch(crm,'Accounts',['1','2'])

    def test_actual_transport_counter_excludes_pretransport_denials(self):
        import httpx
        from unittest.mock import Mock
        from workflow.config import ZohoGatewaySettings
        from workflow.zoho_gateway import ZohoGatewayClient
        oauth=Mock();oauth.status.return_value.configured=True;oauth.status.return_value.connected=True
        oauth.access_token.return_value='fixture'
        client=ZohoGatewayClient(ZohoGatewaySettings(base_url='https://example.invalid',api_key='fixture',timeout_seconds=1,standby_enabled=False),oauth)
        response=httpx.Response(200,json={'data':[]})
        with ProviderUsage(self.root/'transport.db','fixture') as usage,patch('workflow.zoho_gateway.httpx.request',return_value=response) as http:
            client.request('zohoapis','GET','/crm/v8/Leads')
            with self.assertRaises(ValueError):client.request('zohoapis','POST','/crm/v8/Leads',body={},reason='fixture',confirm=True)
            http.assert_called_once()
        self.assertEqual(usage.summary['calls']['crm_get'],1)
        self.assertEqual(usage.summary['calls']['crm_write'],0)
        self.assertEqual(usage.summary['calls_run'],1)

    def test_metric_count_cap_leaves_authoritative_history_untouched(self):
        path=self.root/'cap.db'
        with ProviderUsage(path,'fixture'):pass
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE business_history (evidence TEXT)')
            db.execute("INSERT INTO business_history VALUES('retain forever')")
            db.executemany('INSERT INTO provider_usage(job,recorded_at,summary_json) VALUES(?,?,?)',
                [('fixture',NOW.isoformat(),'{}')]*10001)
        with ProviderUsage(path,'fixture'):pass
        with sqlite3.connect(path) as db:
            self.assertLessEqual(db.execute('SELECT count(*) FROM provider_usage').fetchone()[0],10000)
            self.assertEqual(db.execute('SELECT evidence FROM business_history').fetchone()[0],'retain forever')

if __name__=='__main__':unittest.main()
