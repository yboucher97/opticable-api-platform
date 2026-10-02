from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from workflow.automation.models import AutomationEvent,WorkflowStep
from workflow.automation.store import AutomationStore
from workflow.automation.providers.lifecycle_mailbox import register_lifecycle_mailbox_actions
from workflow.automation.read_inventory_cache import build_lifecycle_display,DisplayInventory

NOW=datetime(2026,10,2,tzinfo=timezone.utc)


class Clock(datetime):
    when=NOW
    @classmethod
    def now(cls,tz=None):return cls.when if tz else cls.when.replace(tzinfo=None)


class Mail:
    def __init__(self):
        self.rows=[self.row('1')];self.calls=[];self.body='Verified fixture body';self.fail=False;self.incomplete=False
    @staticmethod
    def row(identity):
        return dict(messageId=identity,folderId='inbox',fromAddress='fixture@example.test',
                    receivedTime=str(int((NOW-timedelta(hours=2)).timestamp()*1000)),subject='Fixture',summary='Fixture summary')
    def request(self,service,method,path,**kwargs):
        self.calls.append((service,method,path))
        if method!='GET':raise AssertionError('Fixture must remain read-only')
        if path.endswith('/search'):
            start=kwargs['query']['start']-1;limit=kwargs['query']['limit']
            rows=self.rows[start:start+limit] if not self.incomplete else [self.row(str(start+i)) for i in range(limit)]
            return {'ok':True,'data':rows}
        if self.fail:raise ValueError('Fixture unavailable')
        return {'ok':True,'data':{'content':self.body}}


class MailReadTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.store=AutomationStore(self.root/'automation.db');self.mail=Mail();actions={}
        def ingest(event):
            fresh,identity,_=self.store.ingest_event(event)
            return SimpleNamespace(duplicate=not fresh,event_id=identity)
        self.engine=SimpleNamespace(register_action=lambda key,fn:actions.update({key:fn}),ingest=ingest)
        register_lifecycle_mailbox_actions(self.engine,self.mail,self.store)
        self.poll=actions['lifecycle.mailbox_poll']
    def run_poll(self,*,when=NOW,limit=100):
        Clock.when=when
        with patch('workflow.automation.providers.lifecycle_mailbox.datetime',Clock):
            return self.poll({'event':AutomationEvent(event_type='fixture',source='fixture').model_dump()},
                             WorkflowStep(id='poll',action='lifecycle.mailbox_poll',inputs={'limit':limit}))
    def state(self):
        with self.store._connect() as db:
            return tuple(db.execute('SELECT successful_at,full_at FROM mailbox_observation_checkpoints').fetchone())
    def test_unchanged_replay_has_zero_duplicate_events_and_one_metadata_read(self):
        first=self.run_poll();self.mail.calls=[];second=self.run_poll(when=NOW+timedelta(hours=1))
        self.assertEqual((first['accepted'],first['content_reads']),(1,1))
        self.assertEqual((second['accepted'],second['duplicates'],second['content_reads'],second['cache_hits']),(0,0,0,1))
        self.assertEqual(len(self.mail.calls),1)
    def test_delayed_reordered_unseen_message_is_discovered_once(self):
        self.run_poll();self.mail.rows.insert(0,self.mail.row('late-2'))
        value=self.run_poll(when=NOW+timedelta(hours=1))
        self.assertEqual((value['accepted'],value['content_reads'],value['cache_hits']),(1,1,1))
        self.assertEqual(self.run_poll(when=NOW+timedelta(hours=2))['accepted'],0)
    def test_metadata_change_and_daily_audit_retrieve_content_without_duplicate_intake(self):
        self.run_poll();self.mail.rows[0]['subject']='Changed metadata'
        changed=self.run_poll(when=NOW+timedelta(hours=1))
        self.assertEqual((changed['content_reads'],changed['revalidated'],changed['duplicates']),(1,1,0))
        daily=self.run_poll(when=NOW+timedelta(days=1,hours=2))
        self.assertTrue(daily['full_scan']);self.assertEqual(daily['revalidated'],1)
    def test_changed_body_is_reported_and_checkpoint_remains_unchanged(self):
        self.run_poll();before=self.state();self.mail.body='Different known content'
        result=self.run_poll(when=NOW+timedelta(days=1))
        self.assertEqual(result['failed'],1);self.assertFalse(result['checkpoint_advanced']);self.assertEqual(self.state(),before)
        with self.store._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM automation_events WHERE event_type='customer.lifecycle.email.received'").fetchone()[0],1)
    def test_failed_content_retry_preserves_cursor_and_discovers_new_message(self):
        self.run_poll();before=self.state();self.mail.rows.append(self.mail.row('2'));self.mail.fail=True
        self.assertFalse(self.run_poll(when=NOW+timedelta(hours=1))['checkpoint_advanced']);self.assertEqual(before,self.state())
        self.mail.fail=False;self.assertEqual(self.run_poll(when=NOW+timedelta(hours=2))['accepted'],1)
    def test_complete_pagination_and_overflow_fail_before_content(self):
        self.mail.rows=[self.mail.row(str(i)) for i in range(5)]
        result=self.run_poll(limit=2)
        self.assertEqual((result['search_pages'],result['accepted']),(3,5))
        self.mail.incomplete=True;self.mail.calls=[];before=self.state()
        with self.assertRaisesRegex(ValueError,'bounded'):self.run_poll(when=NOW+timedelta(hours=1),limit=2)
        self.assertEqual(before,self.state());self.assertTrue(all(p.endswith('/search') for _,_,p in self.mail.calls))
    def test_cache_loss_revalidates_and_state_loss_cannot_suppress_intake(self):
        self.run_poll()
        with self.store._connect() as db:db.execute('DELETE FROM mailbox_observation_cache')
        result=self.run_poll(when=NOW+timedelta(hours=1))
        self.assertEqual((result['accepted'],result['revalidated']),(0,1))
        with self.store._connect() as db:
            row=tuple(db.execute('SELECT * FROM mailbox_observation_cache').fetchone())
        restored=AutomationStore(self.root/'restored.db')
        from workflow.automation.mail_observation_cache import MailObservationCache
        cache=MailObservationCache(restored,row[0],now=NOW+timedelta(hours=2))
        with restored._connect() as db:db.execute('INSERT INTO mailbox_observation_cache VALUES(?,?,?,?,?,?)',row)
        cache=MailObservationCache(restored,row[0],now=NOW+timedelta(hours=2))
        self.assertFalse(cache.hit(self.mail.rows[0]))
    def test_long_gap_stops_without_calls_or_checkpoint_advance(self):
        self.run_poll();before=self.state();self.mail.calls=[]
        with self.assertRaisesRegex(ValueError,'backfill'):self.run_poll(when=NOW+timedelta(days=8))
        self.assertEqual(before,self.state());self.assertEqual(self.mail.calls,[])


class CRM:
    def __init__(self):
        self.calls=[];self.accounts=[{'id':'1','Account_Name':'Real fixture'},
            {'id':'2','Account_Name':'Test fixture','OptiBrain_Test':True,'Description':'OPTIBRAIN TEST — PHASE 14'}]
    def request(self,service,method,path,**kwargs):
        self.calls.append((method,path))
        return {'ok':True,'status':200,'data':{'data':self.accounts if path.endswith('/Accounts') else [],'info':{'more_records':False}}}


class DisplayTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.db=self.root/'display.db';self.crm=CRM();self.registry=self.root/'registry.json'
        self.registry.write_text(json.dumps({'records':{'Accounts':['2']}}))
    def test_lifecycle_recurring_share_five_reads_with_separate_scopes(self):
        first=build_lifecycle_display(self.crm,self.db,now=NOW)
        second=build_lifecycle_display(self.crm,self.db,scope='lab',registry_path=self.registry,now=NOW+timedelta(seconds=1))
        self.assertEqual(len(self.crm.calls),5)
        self.assertEqual([r['account'] for r in first['rows']],['Real fixture'])
        self.assertEqual([r['account'] for r in second['rows']],['Test fixture'])
        self.assertTrue(second['projection_cached']);self.assertEqual(second['projection_observed_at'],NOW.isoformat())
    def test_expired_projection_refreshes_and_daily_full_detects_deletion(self):
        build_lifecycle_display(self.crm,self.db,now=NOW)
        self.crm.accounts=[]
        second=build_lifecycle_display(self.crm,self.db,now=NOW+timedelta(days=1))
        self.assertEqual(second['sample_count'],0);self.assertEqual(len(self.crm.calls),10)
    def test_display_wrapper_refuses_mutation_before_provider_access(self):
        projection=DisplayInventory(self.crm,self.db,now=NOW)
        with self.assertRaisesRegex(ValueError,'authorize'):projection.request('zohoapis','POST','/crm/v8/Accounts',body={})
        self.assertEqual(self.crm.calls,[])


if __name__=='__main__':unittest.main()
