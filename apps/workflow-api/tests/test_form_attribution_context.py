from html import escape
import json,tempfile,unittest
from pathlib import Path
from test_phase9_form_receipts import HTML,DETAILS,HEADERS,NOW,MESSAGE
from workflow.automation.phase9_form_receipts import parse_notification,FormReceiptLedger,controlled_test_identity
from workflow.automation.lifecycle import attribution,plan_intake
from workflow.automation.lifecycle_control import digest

class FormAttributionContextTests(unittest.TestCase):
    def receipt(self,lang='fr',context=None):
        html=HTML
        if lang=='en':
            for a,b in [('Nom du contact','Name of the contact'),('Entreprise','Company'),('Courriel','Email'),('Téléphone','Phone'),('Notes sur le projet','Description of your needs')]:html=html.replace(a,b)
        if context is None:
            context={'schema':1,'language':lang,'attribution':{**{p+k:v for p in ('first_','last_') for k,v in {'source':'google','medium':'cpc','campaign':'fixture','campaign_id':'test-id','content':'test-content','term':'cabling','site':'https://opticable.ca','touch_time':'2026-10-01T02:00:00+00:00'}.items()},'google_gclid':'TEST_ONLY_GCLID','google_gbraid':'TEST_ONLY_GBRAID','google_wbraid':'TEST_ONLY_WBRAID','meta_fbclid':'TEST_ONLY_FBCLID','msclkid':'TEST_ONLY_MSCLKID','origin_site':'opticable.ca','origin_path':f'/{lang}/contact/','origin_service':'Structured Cabling'}}
        html=html.replace('</table>','<tr><td>OptiBrain Acquisition Context</td><td>:</td><td>'+escape(json.dumps(context))+'</td></tr></table>')
        return parse_notification(message_id=MESSAGE,details=DETAILS,content={'content':html},headers=HEADERS,now=NOW)
    def test_both_languages_persist_provider_context_and_replay(self):
        for lang in ('fr','en'):
            with self.subTest(lang=lang),tempfile.TemporaryDirectory() as tmp:
                r=self.receipt(lang);ledger=FormReceiptLedger(Path(tmp)/'receipt.db')
                self.assertEqual(r['language'],lang);self.assertEqual(r['campaign'],'fixture')
                self.assertEqual(ledger.record(r),'CREATED');self.assertEqual(ledger.record(r),'REPLAY')
                self.assertEqual(r['attribution']['msclkid'],'TEST_ONLY_MSCLKID')
                a=attribution({'attribution':r['attribution']},{'First_Source':'referral','First_Campaign':'original'})
                self.assertNotIn('First_Source',a);self.assertNotIn('First_Campaign',a);self.assertEqual(a['Last_Source'],'google')
                payload={'name':'Test Person','email':r['submitted_email'],'phone':'5145550187','service':'Structured Cabling','attribution':r['attribution'],'consent':True}
                source={'schema':1,'source':'zoho_form','origin':'https://opticable.ca','inquiry_id':r['event_id'],'submitted_email':r['submitted_email'],'occurred_at':r['occurred_at'],'request':payload,'payload_hash':digest(payload),'request_hash':r['raw_hash']}
                plan=plan_intake(source,[],[],protected_ids=set(),now=NOW)
                self.assertEqual(plan['patch']['Google_GCLID'],'TEST_ONLY_GCLID');self.assertEqual(plan['patch']['Last_Campaign'],'fixture')
    def test_absent_ids_are_not_fabricated(self):
        r=self.receipt(context={'schema':1,'language':'fr','attribution':{'first_source':'referral'}})
        self.assertNotIn('google_gclid',r['attribution'])
    def test_language_mismatch_and_unapproved_fields_fail(self):
        for context in ({'schema':1,'language':'en','attribution':{}},{'schema':1,'language':'fr','attribution':{'email':'someone@example.org'}}):
            with self.assertRaises(ValueError):self.receipt(context=context)
    def test_controlled_remediation_notification_is_test_only_and_never_a_generic_domain_exemption(self):
        fields={'company':'OPTIBRAIN TEST — REMEDIATION 1–2','notes':'TEST ONLY ob-r1-20261004-form-fr'}
        self.assertTrue(controlled_test_identity('logs@opticable.ca',fields))
        for address,value in [('customer@opticable.ca',fields),('logs@opticable.ca',{**fields,'notes':'real job'}),('logs@opticable.ca',{**fields,'company':'Customer'})]:
            with self.subTest(address=address,value=value):self.assertFalse(controlled_test_identity(address,value))
