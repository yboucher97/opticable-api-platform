from datetime import datetime, timezone
import unittest
from workflow.automation.lifecycle import (email,phone,next_followup,plan_intake,
    site_match,finance_relationship,reminder_due,accepted_plan,attribution)
from workflow.automation.lifecycle_control import digest

class LifecyclePlanTests(unittest.TestCase):
    def receipt(self):
        request={'name':'TEST Person','email':' Person@Opticable.ca ','phone':'(514) 555-0116',
            'company':'TEST ONLY Company','service':'Structured Cabling','consent':True,
            'attribution':{'first_source':'google','first_campaign':'original','last_source':'google','last_campaign':'original'}}
        return dict(schema=1,source='ai_website',origin='https://ai.opticable.ca',inquiry_id='test-inquiry-1',
            request=request,payload_hash=digest(request),request_hash='a'*64,submitted_email='person@opticable.ca',occurred_at='2026-10-02T17:00:00Z')
    def test_normalization_and_business_deadline(self):
        self.assertEqual(email(' Person@Opticable.ca '),'person@opticable.ca')
        self.assertEqual(phone('(514) 555-0116'),'+15145550116')
        self.assertEqual(next_followup('2026-10-02T17:00:00Z'),'2026-10-05T10:00:00-04:00')
    def test_new_receipt_plan_and_cutoff(self):
        r=self.receipt()
        plan=plan_intake(r,[],[],protected_ids=set(),activation_at='2026-10-02T16:59:59Z')
        self.assertEqual(plan['decision'],'CREATE');self.assertEqual(plan['patch']['Normalized_Email'],'person@opticable.ca')
        self.assertNotIn('Lead_Status',plan['patch'])
        self.assertEqual(plan_intake(r,[],[],protected_ids=set(),activation_at='2026-10-02T17:00:01Z')['decision'],'INELIGIBLE')
    def test_protected_existing_identity_no_writes(self):
        r=self.receipt()
        for module in ('Lead','Contact'):
            rows=[{'id':'999','Email':'person@opticable.ca'}]
            p=plan_intake(r,rows if module=='Lead' else [],rows if module=='Contact' else [],protected_ids={'999'})
            self.assertEqual(p['decision'],'HUMAN');self.assertNotIn('patch',p)
    def test_ambiguous_exact_matches_need_human(self):
        p=plan_intake(self.receipt(),[{'id':'1','Email':'person@opticable.ca'},{'id':'2','Phone':'+15145550116'}],[],protected_ids=set())
        self.assertEqual(p['decision'],'HUMAN')
    def test_shared_phone_does_not_overwrite_different_person_email(self):
        p=plan_intake(self.receipt(),[{'id':'1','Email':'different@opticable.ca','Phone':'+15145550116'}],[],protected_ids=set())
        self.assertEqual(p['decision'],'HUMAN');self.assertNotIn('patch',p)
    def test_native_click_ids_captured_without_new_financial_fields(self):
        r=self.receipt();r['request']['attribution'].update(google_gclid='TEST_GCLID',google_gbraid='TEST_GBRAID',google_wbraid='TEST_WBRAID',meta_fbclid='TEST_FBCLID',microsoft_msclkid='TEST_MSCLKID');r['payload_hash']=digest(r['request'])
        p=plan_intake(r,[],[],protected_ids=set())
        self.assertEqual(p['patch']['Google_GCLID'],'TEST_GCLID');self.assertEqual(p['click_ids']['microsoft_msclkid'],'TEST_MSCLKID')
        self.assertNotIn('Microsoft_MSCLKID',p['patch'])
    def test_missing_site_address_blocks_new_site_creation(self):
        p=site_match([{'id':'10','Linked_Account':{'id':'1'},'Service_Location_Address':''}],'1','123 TEST Street Montréal QC H1A1A1')
        self.assertEqual(p['decision'],'HUMAN')
    def test_structured_site_reuses_province_and_postal_variations_but_not_units(self):
        from workflow.automation.lifecycle import SITE_FIELDS,site_fields
        address={'street':'123 TEST Avenue','unit':'Unit 1','city':'Montréal','province':'Quebec','postal_code':'H1A 1A1','country':'Canada'}
        site={'id':'10','Linked_Account':{'id':'1'},**site_fields(address)}
        self.assertEqual(site_match([site],'1',{**address,'province':'QC','postal_code':'H1A1A1'})['decision'],'REUSE')
        self.assertEqual(site_match([site],'1',{**address,'unit':'Unit 2'})['decision'],'CREATE')
        self.assertEqual(site_match([site],'1',{**address,'postal_code':''})['decision'],'HUMAN')
        self.assertNotIn('Service_Location_Address',site_fields(address))
    def test_old_unprotected_lead_not_retroactively_eligible(self):
        p=plan_intake(self.receipt(),[{'id':'1','Email':'person@opticable.ca','Created_Time':'2026-10-01T00:00:00Z'}],[],protected_ids=set(),activation_at='2026-10-02T16:00:00Z')
        self.assertEqual(p['decision'],'HUMAN')
    def test_missing_optional_location_does_not_clear_existing_city(self):
        p=plan_intake(self.receipt(),[],[],protected_ids=set())
        self.assertNotIn('City',p['patch'])
    def test_returning_identity_preserves_first_updates_last(self):
        r=self.receipt();r['request']['attribution'].update(first_campaign='changed',last_campaign='returning');r['payload_hash']=digest(r['request'])
        p=plan_intake(r,[{'id':'1','Email':'person@opticable.ca','First_Campaign':'original'}],[],protected_ids=set())
        self.assertEqual(p['decision'],'UPDATE');self.assertNotIn('First_Campaign',p['patch']);self.assertEqual(p['patch']['Last_Campaign'],'returning')
    def test_payload_tampering_and_origin_confusion_denied(self):
        for change in ('payload','origin'):
            r=self.receipt()
            if change=='payload':r['request']['company']='different'
            else:r['origin']='https://untrusted.example'
            with self.subTest(change=change),self.assertRaises(ValueError):plan_intake(r,[],[],protected_ids=set())
    def test_crm_touch_timestamp_is_provider_compatible(self):
        self.assertEqual(attribution({'attribution':{'last_touch_time':'2026-10-02T18:00:01.123456Z'}})['Last_Touch_Time'],'2026-10-02T18:00:01+00:00')
    def test_sites_do_not_fuzzy_merge_or_cross_accounts(self):
        sites=[{'id':'10','Linked_Account':{'id':'1'},'Service_Location_Address':'123 TEST Street, Montréal, QC H1A 1A1, Unit 2'}]
        self.assertEqual(site_match(sites,'1','123 test street Montréal QC H1A 1A1 Unit 2')['decision'],'REUSE')
        self.assertEqual(site_match(sites,'2',sites[0]['Service_Location_Address'])['decision'],'CREATE')
        self.assertEqual(site_match(sites,'1','123 TEST Street, Montréal, QC H1A 1A1, Unit 3')['decision'],'CREATE')
        self.assertEqual(site_match(sites,'1','Montréal')['decision'],'HUMAN')
    def test_finance_uses_native_id_and_associations(self):
        record={'Estimate_ID':'40','Account_Name':{'id':'1'},'Potential_Name':{'id':'2'}}
        books={'estimate_id':'40','estimate_number':'TEST-1','status':'accepted','total':0}
        deals=[{'id':'2','Account_Name':{'id':'1'}}];sites=[{'id':'3','Linked_Account':{'id':'1'}}];services=[{'id':'4','Linked_Deal':{'id':'2'},'Linked_Service_Location':{'id':'3'}}]
        p=finance_relationship(record,books,'estimate',deals,sites,services)
        self.assertEqual(p['decision'],'OBSERVE');self.assertEqual(p['site_id'],'3');self.assertFalse(p['financial_writes'])
        with self.assertRaises(ValueError):finance_relationship(record,{**books,'estimate_id':'41'},'estimate',deals,sites,services)
        self.assertEqual(finance_relationship({**record,'Potential_Name':None},books,'estimate',deals,sites,services)['decision'],'HUMAN')
    def test_multi_site_finance_and_wrong_account_need_human(self):
        record={'Invoice_ID':'40','Account_Name':{'id':'1'},'Potential_Name':{'id':'2'}}
        books={'invoice_id':'40','status':'sent'};deals=[{'id':'2','Account_Name':{'id':'1'}}];sites=[{'id':'3','Linked_Account':{'id':'1'}}]
        for services in ([{'id':'4','Linked_Deal':{'id':'2'},'Linked_Service_Location':{'id':'3'}},{'id':'5','Linked_Deal':{'id':'2'},'Linked_Service_Location':{'id':'6'}}],[]):
            self.assertEqual(finance_relationship(record,books,'invoice',deals,sites,services)['decision'],'HUMAN')
    def test_quote_stop_conditions_and_internal_only(self):
        arguments=dict(estimate_status='sent',due_at='2026-10-02T12:00:00Z',now='2026-10-02T13:00:00Z')
        self.assertEqual(reminder_due(**arguments),{'decision':'INTERNAL_TASK','external_send':False})
        for condition in ({'estimate_status':'accepted'},{'estimate_status':'declined'},{'replied':True},{'suppressed':True},{'deal_closed':True}):
            with self.subTest(condition=condition):self.assertEqual(reminder_due(**{**arguments,**condition})['decision'],'STOP')
    def test_accepted_scope_never_invents_services_or_schedule(self):
        p=accepted_plan('CCTV, Structured Cabling',account_id='1',deal_id='2',site_id='3')
        self.assertEqual(p['decision'],'PREPARE_INTERNAL');self.assertEqual(len(p['services']),2)
        self.assertEqual(p['installation'],'UNSCHEDULED');self.assertEqual(p['contract'],'PREPARE_ONLY');self.assertFalse(p['financial_writes'])
        for value in ('','Something uncertain','CCTV, CCTV'):
            with self.subTest(value=value):self.assertEqual(accepted_plan(value,account_id='1',deal_id='2',site_id='3')['decision'],'HUMAN')
