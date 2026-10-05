"""Per-message isolation, immutable provenance and restart/concurrency regression."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation.phase9_form_receipts import (
    ACCOUNT_ID, FormReceiptLedger, collect_form_mail, parse_notification, reconcile_form_crm)
from workflow.automation.readiness import forms_poll_signal,provider_read_signal
from test_phase9_form_receipts import NOW,DETAILS,HEADERS,HTML


class Mail:
    def __init__(self, ids=('101',), changed=(), malformed=()):
        self.ids=ids;self.changed=changed;self.malformed=malformed;self.calls=[]
    def request(self,service,method,path,**kwargs):
        assert service=='mail' and method=='GET'
        self.calls.append(path)
        if path.endswith('/search'):
            data=[{'messageId':m,'folderId':'777','fromAddress':DETAILS['fromAddress']} for m in self.ids]
        else:
            m=path.split('/')[-2]
            if path.endswith('/details'):data={**DETAILS,'messageId':m}
            elif path.endswith('/content'):
                body=HTML.replace('Warehouse','Changed') if m in self.changed else HTML
                data={'content':'<p>broken</p>' if m in self.malformed else body}
            else:data={'headerContent':{**HEADERS,'Message-ID':[f'<{m}@public.zohoforms.com>']}}
        return {'ok':True,'data':{'data':data}}


def receipt(m='101'):
    return parse_notification(message_id=m,details={**DETAILS,'messageId':m},
        content={'content':HTML},headers={**HEADERS,'Message-ID':[f'<{m}@public.zohoforms.com>']},now=NOW)


class PollingReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.ledger=FormReceiptLedger(self.root/'phase9-form-receipts.db')
        self.ledger.initialize()
    def rows(self,table):
        with self.ledger._connect() as db:return [tuple(r) for r in db.execute('SELECT * FROM '+table)]
    def test_new_duplicate_restart_and_attribution_unchanged(self):
        mail=Mail();first=collect_form_mail(mail,self.ledger,now=NOW)
        self.assertEqual(first['created'],1);original=self.rows('form_receipts')
        second=collect_form_mail(mail,self.ledger,now=NOW+timedelta(minutes=5))
        self.assertEqual(second['replayed'],1);self.assertEqual(second['created'],0)
        self.assertEqual(self.rows('form_receipts'),original)
        self.assertEqual(collect_form_mail(mail,FormReceiptLedger(self.ledger.path),now=NOW+timedelta(days=1))['replayed'],1)
        self.assertEqual(self.rows('form_receipts'),original)
        self.assertEqual(self.rows('form_provider_matches'),[])
    def test_combined_legacy_defaults_and_test_exclusion_are_additive(self):
        current=receipt();old={**current,'test_only':False};old.pop('language');old.pop('attribution')
        self.ledger.record(old);original=self.rows('form_receipts')
        result=collect_form_mail(Mail(),self.ledger,now=NOW)
        self.assertEqual(result['replayed'],1);self.assertEqual(result['conflicts_quarantined'],0)
        row=self.ledger.list()[0]
        self.assertTrue(row['test_only']);self.assertEqual(json.loads(row['evidence_json']),current)
        self.assertEqual(json.loads(row['original_evidence_json']),old)
        self.assertEqual(self.rows('form_receipts'),original)
        self.assertEqual(len(self.rows('form_parse_projections')),1)
    def test_valid_conflict_valid_continues_without_overwrite(self):
        self.ledger.record(receipt('102'));original=self.rows('form_receipts')
        out=collect_form_mail(Mail(('101','102','103'),changed=('102',)),self.ledger,now=NOW)
        self.assertEqual((out['created'],out['conflicts_quarantined']),(2,1))
        self.assertIn(original[0],self.rows('form_receipts'))
        self.assertEqual(len(self.rows('form_message_anomalies')),1)
        self.assertEqual(self.rows('form_provider_matches'),[])
        row=next(r for r in self.ledger.list() if r['provider_message_id']=='102')
        self.assertTrue(row['quarantined'])
        self.assertIsNotNone(self.ledger.poll_state(ACCOUNT_ID))
    def test_conflict_first_then_valid(self):
        self.ledger.record(receipt('101'))
        out=collect_form_mail(Mail(('101','102'),changed=('101',)),self.ledger,now=NOW)
        self.assertEqual((out['created'],out['conflicts_quarantined']),(1,1))
    def test_malformed_then_valid_isolated(self):
        out=collect_form_mail(Mail(('101','102'),malformed=('101',)),self.ledger,now=NOW)
        self.assertEqual((out['created'],out['invalid_messages']),(1,1))
        self.assertEqual(len(self.rows('form_receipts')),1)
    def test_bad_metadata_then_valid_isolated(self):
        mail=Mail(('bad','102'));out=collect_form_mail(mail,self.ledger,now=NOW)
        self.assertEqual((out['created'],out['invalid_messages']),(1,1))
    def test_poison_cooldown_daily_scan_and_deduplicated_revisit(self):
        self.ledger.record(receipt());mail=Mail(changed=('101',))
        collect_form_mail(mail,self.ledger,now=NOW);original=self.rows('form_message_anomalies')
        mail.calls=[];out=collect_form_mail(mail,self.ledger,now=NOW+timedelta(days=1))
        self.assertTrue(out['full_scan']);self.assertEqual(len(mail.calls),1)
        self.assertEqual(out['conflicts_quarantined'],1)
        mail.calls=[];collect_form_mail(mail,self.ledger,now=NOW+timedelta(days=15))
        self.assertEqual(len(mail.calls),4);self.assertEqual(self.rows('form_message_anomalies'),original)
    def test_concurrent_same_receipt_serializes_uniqueness(self):
        current=receipt()
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:FormReceiptLedger(self.ledger.path).record(current),range(2)))
        self.assertEqual(sorted(results),['CREATED','REPLAY'])
        self.assertEqual(len(self.rows('form_receipts')),1)
    def test_concurrent_polls_one_receipt(self):
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:collect_form_mail(Mail(),FormReceiptLedger(self.ledger.path),now=NOW),range(2)))
        self.assertEqual(sum(r['created'] for r in results),1)
        self.assertEqual(len(self.rows('form_receipts')),1)
        self.assertEqual(len(self.rows('form_poll_events')),4)
    def test_provider_failure_aborts_without_anomaly_or_cursor_advance(self):
        collect_form_mail(Mail(),self.ledger,now=NOW);old=self.ledger.poll_state(ACCOUNT_ID)
        class Failed:
            def request(self,*args,**kwargs):return {'ok':False,'status':503}
        with self.assertRaises(ValueError):collect_form_mail(Failed(),self.ledger,now=NOW+timedelta(minutes=5))
        self.assertEqual(self.ledger.poll_state(ACCOUNT_ID),old)
        self.assertEqual(self.rows('form_message_anomalies'),[])
        self.assertEqual(self.rows('form_poll_events')[-1][2],'FAILED')
    def test_database_failure_aborts_no_false_success(self):
        with patch.object(self.ledger,'record',side_effect=sqlite3.OperationalError('fixture outage')):
            with self.assertRaises(sqlite3.OperationalError):collect_form_mail(Mail(),self.ledger,now=NOW)
        self.assertIsNone(self.ledger.poll_state(ACCOUNT_ID));self.assertEqual(self.rows('form_message_anomalies'),[])
        self.assertEqual(self.rows('form_poll_events')[-1][2],'FAILED')
    def test_quarantined_receipt_never_matches_crm(self):
        self.ledger.record(receipt());collect_form_mail(Mail(changed=('101',)),self.ledger,now=NOW)
        class NoCRM:
            def request(self,*args,**kwargs):raise AssertionError('quarantined reconciliation')
        self.assertEqual(reconcile_form_crm(NoCRM(),self.ledger)['pending'],0)
    def test_all_evidence_tables_remain_immutable(self):
        old=receipt();old.pop('language');old.pop('attribution');self.ledger.record(old)
        collect_form_mail(Mail(),self.ledger,now=NOW)
        collect_form_mail(Mail(changed=('101',)),self.ledger,now=NOW+timedelta(days=1))
        for table,column in [('form_receipts','source'),('form_parse_projections','recorded_at'),
                             ('form_message_anomalies','observed_at'),('form_poll_events','observed_at')]:
            with self.subTest(table=table),self.ledger._connect() as db:
                with self.assertRaises(sqlite3.IntegrityError):db.execute(f"UPDATE {table} SET {column}='changed'")
                with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM '+table)
    def test_mail_read_success_distinct_from_failed_intake(self):
        with self.ledger._connect() as db:
            db.execute('CREATE TABLE provider_usage(id INTEGER PRIMARY KEY,recorded_at TEXT,summary_json TEXT)')
            db.execute('INSERT INTO provider_usage VALUES(1,?,?)',(NOW.isoformat(),json.dumps({
                'status':'failed','calls':{'mail_get':4},'last_response':{'mail_get':'ok'}})))
        self.ledger.poll_event('fixture','FAILED',ACCOUNT_ID,NOW,{'replayed':2,'provider_reads':4})
        self.assertEqual(provider_read_signal(self.root,'Mail reads','mail_get',NOW,7200)['state'],'OK')
        self.assertEqual(forms_poll_signal(self.root,NOW)['state'],'ACTION REQUIRED')
    def test_same_internet_identity_different_provider_id_is_conflict(self):
        self.ledger.record(receipt())
        other={**receipt(),'provider_message_id':'999'}
        from workflow.automation.phase9_form_receipts import ImmutableReceiptConflict
        with self.assertRaises(ImmutableReceiptConflict):self.ledger.record(other)
        self.assertEqual(len(self.rows('form_receipts')),1)
    def test_fr_en_touch_and_click_context_not_advanced_by_replay(self):
        from test_form_inline_context import InlineContextTests
        context={'first_source':'google','last_source':'referral','first_medium':'cpc','last_medium':'referral',
            'first_campaign':'first','last_campaign':'last','first_term':'wifi','last_content':'cta',
            'google_gclid':'TEST_GCLID','google_gbraid':'TEST_GBRAID','google_wbraid':'TEST_WBRAID',
            'meta_fbclid':'TEST_FBCLID','msclkid':'TEST_MSCLKID'}
        for lang in ('fr','en'):
            with self.subTest(language=lang):
                helper=InlineContextTests();current=helper.parse(helper.body(lang,{'schema':1,'language':lang,'attribution':context}))
                ledger=FormReceiptLedger(self.root/(lang+'.db'));ledger.record(current)
                before=[dict(r) for r in ledger.list()]
                self.assertEqual(ledger.record(current),'REPLAY');self.assertEqual(ledger.list(),before)
                self.assertEqual(json.loads(ledger.list()[0]['evidence_json'])['attribution'],context)
    def test_quarantined_enrichment_does_not_read_or_write_crm(self):
        from workflow.automation.phase9_form_enrichment import enrich_form_leads,POLICY
        self.ledger.record(receipt())
        self.ledger.link_test_lead(receipt()['event_id'],{'id':'123456','Email':receipt()['submitted_email'],
            'OptiBrain_Test':True,'Description':'OPTIBRAIN TEST — PHASE 9\nSynthetic'}, {'123456'})
        collect_form_mail(Mail(changed=('101',)),self.ledger,now=NOW)
        class NoProvider:
            def request(self,*args,**kwargs):raise AssertionError('quarantined provider effect')
        with patch.dict('os.environ',{'OPTIBRAIN_PHASE9_FORM_ENRICHMENT':POLICY}):
            self.assertEqual(enrich_form_leads(NoProvider(),self.ledger,go_live=(NOW-timedelta(days=1)).isoformat())['eligible'],0)
        self.assertEqual(self.rows('form_enrichment_journal'),[])
    def test_legacy_defaults_and_inline_context_combine_without_losing_proof(self):
        from test_form_inline_context import InlineContextTests
        current=InlineContextTests().parse(InlineContextTests().body())
        original={**current,'fields':dict(current['fields']),'campaign':None,
                  'attribution_confidence':'FORM_NOTIFICATION_ONLY','test_only':False}
        original['fields'].pop('acquisition_context');original.pop('language');original.pop('attribution')
        self.ledger.record(original);before=self.rows('form_receipts')
        self.assertEqual(self.ledger.record(current),'REPLAY')
        self.assertEqual(self.rows('form_receipts'),before)
        self.assertEqual(json.loads(self.ledger.list()[0]['evidence_json']),current)
