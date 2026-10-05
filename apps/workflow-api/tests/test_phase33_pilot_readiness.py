"""Completion design/lineage fixtures; no actual Ads/CRM/provider effects."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from html import escape
from pathlib import Path
import json,tempfile,unittest
from test_phase33_ads import fixture,NOW
from test_phase9_form_receipts import HTML,DETAILS,HEADERS,MESSAGE,NOW as MAIL_NOW
from workflow.automation.ads_intelligence import build_bundle
from workflow.automation.ads_pilot import check_seal,spend_decision,GOALS
from workflow.automation.acquisition_store import digest
from workflow.automation.phase9_form_receipts import parse_notification,FormReceiptLedger
from workflow.automation.lifecycle import plan_intake,attribution
from workflow.automation.optimization_store import OptimizationStore

class PilotReadinessTests(unittest.TestCase):
    def campaign(self):
        return next(p for p in build_bundle(fixture(),NOW)['proposals'] if p['record']['proposal_type']=='GOOGLE_ADS_CAMPAIGN')['detail']
    def test_complete_all_four_campaign_variants_and_exact_local_targets(self):
        variants=[p for p in build_bundle(fixture(),NOW)['proposals'] if p['record']['proposal_type']=='GOOGLE_ADS_CAMPAIGN']
        for p in variants:
            d=p['detail'];self.assertEqual(d['locations']['include_resource_ids'],['geoTargetConstants/1002604','geoTargetConstants/1002579'])
            self.assertEqual(d['networks'],{'google_search':True,'search_partners':False,'display':False})
            for field in ['negative_preview','ad_schedule','device_policy','test_isolation','spend_guard','stop_conditions','measurement_window','rollback','graduation','future_outcomes']:
                self.assertIn(field,d)
            self.assertFalse(d['execution_authorized']);self.assertTrue(all(v is None for v in d['future_outcomes'].values()))
            self.assertFalse(d['budget']['explicitly_shared']);self.assertIsNone(d['budget']['amount_micros'])
            self.assertEqual(d['budget']['period'],'CUSTOM_PERIOD');self.assertEqual(d['budget']['flight_days'],28)
            self.assertLessEqual(d['budget']['total_amount_micros']/1e6,d['budget']['hard_ceiling_CAD'])
    def test_no_weak_goal_or_account_default_or_offline_bidding(self):
        self.assertEqual(GOALS['initial_biddable_goals'],[]);self.assertIsNone(GOALS['custom_conversion_goal'])
        self.assertIn('OFF',GOALS['offline']['target']);self.assertIn('REMOVE FROM BIDDING',GOALS['legacy_merci']['disposition'])
    def test_changed_seal_denies_without_any_authority(self):
        d=self.campaign();seal=digest(d);self.assertEqual(check_seal(d,seal)['state'],'MATCH')
        d['budget']['total_amount_micros']+=1
        self.assertEqual(check_seal(d,seal)['state'],'DENY_ALTERED_SPEC');self.assertFalse(check_seal(d,seal)['execution_authorized'])
    def test_spend_unknown_stale_invalid_and_thresholds_fail_closed(self):
        g=self.campaign()['spend_guard']
        for s,age,expected in [(None,1,'HOLD_UNKNOWN_SPEND'),(1,16,'HOLD_UNKNOWN_SPEND'),(1,float('nan'),'HOLD_UNKNOWN_SPEND'),(-1,1,'HOLD_INVALID_SPEND'),
            (float('nan'),1,'HOLD_INVALID_SPEND'),(g['warn_CAD'],1,'OWNER_WARNING'),(g['pause_CAD'],1,'PAUSE_REQUIRED'),(0,1,'OBSERVE')]:
            with self.subTest(s=s,age=age):
                r=spend_decision(s,age_minutes=age,guard=g);self.assertEqual(r['state'],expected);self.assertFalse(r['execution_authorized']);self.assertEqual(r['provider_writes'],0)
    def test_approved_and_reviewed_fixture_never_grants_writer(self):
        with tempfile.TemporaryDirectory() as t:
            store=OptimizationStore(Path(t)/'fixture.db');p=build_bundle(fixture(),NOW)['proposals'][0]
            p['record'].update(status='APPROVED',approved_by='unit:owner',approved_at=NOW.isoformat());store.record(p['record'],p['detail'])
            self.assertFalse(store.execution_allowed(store.rows()[0]))
    def test_stale_native_source_reduces_proposal_confidence(self):
        x=fixture();x['ads']['at']=(NOW-timedelta(days=8)).isoformat()
        campaigns=[p for p in build_bundle(x,NOW)['proposals'] if p['record']['proposal_type']=='GOOGLE_ADS_CAMPAIGN']
        self.assertTrue(all(p['record']['confidence']=='TENTATIVE' for p in campaigns))
    def test_test_mail_context_ids_survive_parser_immutable_receipt_crm_planning(self):
        for lang in ['fr','en']:
            body=HTML
            if lang=='en':
                for a,b in [('Nom du contact','Name of the contact'),('Entreprise','Company'),('Courriel','Email'),('Téléphone','Phone'),('Notes sur le projet','Description of your needs')]:body=body.replace(a,b)
            captured=(datetime.fromtimestamp(int(DETAILS['receivedTime'])/1000,timezone.utc)-timedelta(minutes=1)).isoformat()
            ctx={'schema':1,'language':lang,'attribution':{'first_source':'google','first_medium':'cpc','first_touch_time':captured,
                'last_source':'partner','last_medium':'referral','last_touch_time':captured,
                'google_gclid':'UNIT_ONLY_GCLID_unchanged','google_gbraid':'UNIT_ONLY_GBRAID_unchanged','google_wbraid':'UNIT_ONLY_WBRAID_unchanged',
                'origin_site':'opticable.ca','origin_path':'/'+lang+'/services/cameras/','origin_service':'Security cameras'}}
            notification=body+'<table><tr><td>OptiBrain Acquisition Context</td><td>:</td><td>'+escape(json.dumps(ctx))+'</td></tr></table>'
            r=parse_notification(message_id=MESSAGE,details=DETAILS,content={'content':notification},headers=HEADERS,now=MAIL_NOW)
            self.assertTrue(r['test_only']);self.assertEqual(r['attribution'],ctx['attribution'])
            with tempfile.TemporaryDirectory() as t:
                ledger=FormReceiptLedger(Path(t)/'fixture.db');self.assertEqual(ledger.record(r),'CREATED');self.assertEqual(ledger.record(r),'REPLAY');self.assertEqual(len(ledger.list()),1)
            fields=r['fields'];payload={'name':fields['name'],'email':r['submitted_email'],'phone':fields['phone'],'company':fields['company'],'consent':True,'attribution':r['attribution']}
            canonical={'schema':1,'source':'zoho_form_fr','origin':'https://opticable.ca','inquiry_id':r['event_id'],
                'request':payload,'submitted_email':r['submitted_email'],'occurred_at':r['occurred_at'],'payload_hash':digest(payload),'request_hash':r['raw_hash']}
            plan=plan_intake(canonical,[],[],protected_ids=set(),now=MAIL_NOW)
            # Pure planner output does not authorize this TEST/EN record for real execution.
            for native,key in [('Google_GCLID','google_gclid'),('Google_GBRAID','google_gbraid'),('Google_WBRAID','google_wbraid')]:self.assertEqual(plan['patch'][native],ctx['attribution'][key])
            self.assertEqual(attribution({'attribution':{'first_source':'later','last_source':'later'}},{'First_Source':'original'}),{'Last_Source':'later'})
