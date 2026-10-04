from html import escape
import json,sqlite3,tempfile,unittest
from pathlib import Path
from test_phase9_form_receipts import HTML,DETAILS,HEADERS,NOW,MESSAGE
from workflow.automation.phase9_form_receipts import parse_notification,FormReceiptLedger

class InlineContextTests(unittest.TestCase):
    def body(self,lang='fr',context=None):
        body=HTML
        if lang=='en':
            for a,b in [('Nom du contact','Name of the contact'),('Entreprise','Company'),('Courriel','Email'),('Téléphone','Phone'),('Notes sur le projet','Description of your needs')]:body=body.replace(a,b)
        ctx=context or {'schema':1,'language':lang,'attribution':{'first_source':'google','last_source':'referral','first_landing_url':'https://opticable.ca/contact/?utm_source=google&test=1','google_gclid':'TEST_ONLY_CLICK'}}
        raw=escape(json.dumps(ctx));url=escape(ctx.get('attribution',{}).get('first_landing_url',''))
        if url:raw=raw.replace(url,'<a href="https://untrusted.invalid/">'+url+'</a>')
        return body+'<div><span><zspan>'+raw+'</zspan></span><br></div>'
    def parse(self,body):
        return parse_notification(message_id=MESSAGE,details=DETAILS,content={'content':body},headers=HEADERS,now=NOW)
    def test_real_inline_merge_shape_and_linkified_urls_both_languages(self):
        for lang in ('fr','en'):
            with self.subTest(lang=lang):
                receipt=self.parse(self.body(lang));self.assertEqual(receipt['language'],lang)
                self.assertEqual(receipt['attribution']['first_landing_url'],'https://opticable.ca/contact/?utm_source=google&test=1')
                self.assertEqual(receipt['attribution']['google_gclid'],'TEST_ONLY_CLICK')
                self.assertTrue(receipt['test_only'])
    def test_respondent_table_notes_are_not_searched_for_context(self):
        fake=escape(json.dumps({'schema':1,'language':'fr','attribution':{'first_source':'invented'}}))
        receipt=self.parse(HTML.replace('TEST ONLY synthetic project','TEST ONLY <zspan>'+fake+'</zspan>'))
        self.assertEqual(receipt['attribution'],{})
    def test_conflicts_malformed_and_private_fields_fail_closed(self):
        bodies=[self.body()+self.body(context={'schema':1,'language':'fr','attribution':{'first_source':'different'}}),HTML+'<zspan>{"schema":1,broken}</zspan>',self.body(context={'schema':1,'language':'en','attribution':{}}),self.body(context={'schema':1,'language':'fr','attribution':{'email':'private@example.org'}})]
        for body in bodies:
            with self.subTest(body=body[-100:]),self.assertRaises(ValueError):self.parse(body)
    def test_inline_and_labelled_context_must_agree(self):
        ctx={'schema':1,'language':'fr','attribution':{'first_source':'same'}};body=self.body(context=ctx)
        row='<tr><td>OptiBrain Acquisition Context</td><td>:</td><td>'+escape(json.dumps(ctx))+'</td></tr>'
        self.assertEqual(self.parse(body.replace('</table>',row+'</table>'))['attribution'],ctx['attribution'])
        with self.assertRaises(ValueError):self.parse(body.replace('</table>',row.replace('same','different')+'</table>'))
    def test_upgrade_preserves_original_receipt_and_replays_projection_once(self):
        current=self.parse(self.body());original={**current,'fields':dict(current['fields']),'attribution':{},'campaign':None,'attribution_confidence':'FORM_NOTIFICATION_ONLY'};original['fields'].pop('acquisition_context')
        with tempfile.TemporaryDirectory() as t:
            ledger=FormReceiptLedger(Path(t)/'receipt.db');self.assertEqual(ledger.record(original),'CREATED');self.assertEqual(ledger.record(current),'REPLAY');self.assertEqual(ledger.record(current),'REPLAY')
            row=ledger.list()[0];self.assertEqual(json.loads(row['original_evidence_json']),original);self.assertEqual(json.loads(row['evidence_json']),current)
            with sqlite3.connect(ledger.path) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM form_context_projections').fetchone()[0],1)
                with self.assertRaises(sqlite3.DatabaseError):db.execute('UPDATE form_context_projections SET recorded_at="later"')
            with self.assertRaises(ValueError):ledger.record({**current,'raw_hash':'0'*64})
            changed={**current,'attribution':{'first_source':'different'}}
            with self.assertRaises(ValueError):ledger.record(changed)
