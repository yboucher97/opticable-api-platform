from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from workflow.automation.apollo_observation import ApolloReader
from workflow.automation.sales_intelligence import (email,domain,key,contact_state,collision,permit_signals,tender_signals,build_sales,render_sales,clay_decision)
from workflow.automation.sales_feedback import SalesFeedback
from workflow.automation.today import build_today
from workflow.operator_phase7_api import install_phase7_canary_routes

NOW=datetime(2026,10,3,21,tzinfo=timezone.utc)

def fixture():
    a={'at':NOW.isoformat(),'contacts_complete':True,'contacts':[
        {'id':'c1','name':'Existing prospect','email':'p@company.test','email_status':'verified',
         'contact_campaign_statuses':[{'emailer_campaign_id':'seq1','status':'active'}]}],
       'messages':[],'replies':[],'stages':[],'sequences':[{'id':'seq1','name':'Existing production sequence'}]}
    crm={'Leads':[{'id':'1','Full_Name':'Inbound','Email':'p@company.test','Lead_Status':'New'}],
         'Contacts':[{'id':'2','Email':'customer@customer.test'}],
         'Accounts':[{'id':'3','Website':'https://customer.test','Account_Name':'Customer'}],
         'Deals':[{'id':'4','Deal_Name':'Work','Stage':'Qualification','Modified_Time':NOW.isoformat()}]}
    return a,crm


class CollisionTests(unittest.TestCase):
    def test_normalization_does_not_fuzzy_merge_people_or_free_email_employers(self):
        self.assertEqual(email(' P@Company.Test '),'p@company.test')
        self.assertEqual(domain('https://www.Company.Test/path'),'company.test')
        self.assertEqual(domain('gmail.com'),'')
        self.assertEqual(email('bad value'),'')

    def test_exact_bidirectional_email_overlap_and_company_match(self):
        a,c=fixture()
        for subject in ({'email':'P@COMPANY.TEST'},{'domain':'company.test'}):
            with self.subTest(subject=subject):
                r=collision(subject,a,c,now=NOW)
                self.assertTrue(r['apollo_active']);self.assertEqual(r['outreach_owner'],'CLAUDE_APOLLO')
                self.assertFalse(r['contact_recommendation_allowed'])
        self.assertEqual(build_sales(a,c,[],now=NOW)['exact_crm_contact_overlap'],1)

    def test_customer_and_ambiguous_customer_recognized_without_merge(self):
        a,c=fixture();c['Accounts'].append({'id':'5','Website':'customer.test'})
        r=collision({'domain':'customer.test'},a,c,now=NOW)
        self.assertTrue(r['existing_customer']);self.assertTrue(r['ambiguous'])
        self.assertEqual(r['outreach_owner'],'OWNER_MANUAL')

    def test_existing_apollo_account_protects_company_even_without_saved_person(self):
        a,c=fixture();a['accounts']=[{'id':'a1','primary_domain':'other.test'}]
        r=collision({'email':'new@other.test'},a,c,now=NOW)
        self.assertEqual(r['outreach_owner'],'CLAUDE_APOLLO');self.assertEqual(r['apollo_account_matches'],['a1'])
        self.assertFalse(r['contact_recommendation_allowed'])

    def test_every_membership_status_and_prior_owner_is_conservative(self):
        for state in ('active','scheduled','paused','finished','unknown'):
            with self.subTest(state=state):
                a,c=fixture();a['contacts'][0]['contact_campaign_statuses'][0]['status']=state
                r=collision({'email':'p@company.test'},a,c,now=NOW)
                self.assertEqual(r['outreach_owner'],'CLAUDE_APOLLO');self.assertFalse(r['cold_send_allowed'])

    def test_all_suppression_states_deny_contact(self):
        for stage in ('Do Not Contact','Not Interested','Bad Data','Changed Job','Unsubscribed','Bounced'):
            with self.subTest(stage=stage):
                a,c=fixture();a['contacts'][0]['contact_stage_id']='s';a['stages']=[{'id':'s','display_name':stage}]
                self.assertTrue(collision({'email':'p@company.test'},a,c,now=NOW)['suppressed'])
        for flag in ('email_unsubscribed','person_deleted'):
            with self.subTest(flag=flag):
                a,c=fixture();a['contacts'][0][flag]=True
                self.assertTrue(collision({'email':'p@company.test'},a,c,now=NOW)['suppressed'])

    def test_activity_is_contact_bound_not_shared_membership_id_and_is_dated(self):
        a,_=fixture();c=a['contacts'][0]
        messages=[{'contact_id':'other','replied':True,'bounce':True,'status':'completed','completed_at':NOW.isoformat()}]
        self.assertFalse(contact_state(c,messages,{},now=NOW)['replied'])
        self.assertFalse(contact_state(c,messages,{},now=NOW)['suppressed'])
        for days,expected in ((1,True),(60,False),(-1,False)):
            with self.subTest(days=days):
                m={'contact_id':'c1','status':'completed','completed_at':(NOW-timedelta(days=days)).isoformat()}
                self.assertEqual(contact_state(c,[m],{},now=NOW)['recent_send'],expected)

    def test_stale_incomplete_and_unknown_identity_never_clear_outreach(self):
        for override in ({'at':(NOW-timedelta(hours=2)).isoformat()},{'contacts_complete':False},{'at':'bad'}):
            with self.subTest(override=override):
                a,c=fixture();a.update(override);r=collision({},a,c,now=NOW)
                self.assertFalse(r['apollo_fresh_complete']);self.assertFalse(r['cold_send_allowed'])

    def test_zero_credit_clay_fallback_does_not_duplicate_good_apollo_email(self):
        self.assertIn('NOT NEEDED',clay_decision(True,[]))
        self.assertIn('DEFERRED',clay_decision(False,['decision maker']))


class PublicSignalsTests(unittest.TestCase):
    def test_permit_event_is_replay_stable_and_not_invented_company(self):
        r={'id_permis':'permit1','date_emission':'2026-09-28','description_type_batiment':'Commercial',
           'code_type_base_demande':'CO','nature_travaux':'Nouveau commerce','emplacement':'1 Test Street'}
        result=permit_signals([r,r],now=NOW)
        self.assertEqual(len(result),1);self.assertTrue(result[0]['identity_unresolved'])
        self.assertFalse(result[0]['contact_allowed']);self.assertEqual(result,permit_signals([r],now=NOW))

    def test_noncommercial_stale_and_irrelevant_permits_filtered(self):
        for r in ({'date_emission':'2020-01-01'},{'description_type_batiment':'Residential'},{'nature_travaux':'abattage'}):
            with self.subTest(r=r):
                base={'id_permis':'1','date_emission':'2026-09-28','description_type_batiment':'Commercial','code_type_base_demande':'CO'}
                self.assertEqual(permit_signals([{**base,**r}],now=NOW),[])

    def test_latest_tender_version_and_closed_or_unrelated_are_not_prospects(self):
        r={'ocid':'o1','id':'1','date':NOW.isoformat(),'buyer':{'name':'Public buyer'},
           'tender':{'status':'active','title':'Modernisation vidéosurveillance','tenderPeriod':{'endDate':(NOW+timedelta(days=2)).isoformat()}}}
        newer={**r,'id':'2'}
        self.assertEqual(tender_signals([r,newer],now=NOW)[0]['native_version'],'2')
        self.assertEqual(tender_signals([r,{**newer,'tender':{**r['tender'],'status':'closed'}}],now=NOW),[])
        for t in ({'status':'closed'},{'title':'Caméra Laue'},{'tenderPeriod':{'endDate':NOW.isoformat()}}):
            with self.subTest(t=t):self.assertEqual(tender_signals([{**r,'tender':{**r['tender'],**t}}],now=NOW),[])


class UnifiedSalesTests(unittest.TestCase):
    def test_reply_first_inbound_next_and_no_task_universe(self):
        a,c=fixture();a['replies']=[{'contact_id':'c1','replied':True,'reply_class':'willing_to_meet'}]
        view=build_sales(a,c,[],now=NOW)
        self.assertEqual([r['kind'] for r in view['rows'][:2]],['apollo_reply','inbound_lead'])
        self.assertEqual(view['tasks_created'],0)
        self.assertIn('existing Apollo',view['rows'][1]['action'])
        self.assertTrue(all(r['contact_allowed'] is False for r in view['rows']))

    def test_test_records_permanently_lost_and_dnc_never_surface(self):
        a,c=fixture();c['Leads']=[{'id':'x','OptiBrain_Test':True},{'id':'y','Company':'TEST ONLY Company'},
                                {'id':'z','Lead_Status':'Do Not Contact'}]
        c['Deals']=[{'id':'l','Stage':'Closed Lost'},{'id':'t','OptiBrain_Test':True}]
        self.assertEqual(build_sales(a,c,[],now=NOW)['rows'],[])

    def test_customer_renewals_and_native_estimates_share_sales_view(self):
        a,c=fixture()
        view=build_sales(a,c,[],now=NOW,recurring={'attention':[{'context':'Customer renewal','why':'Renewal due','next_action':'Review renewal'}]},
                         estimates=[{'id':'e1','deal_id':'4','status':'accepted','title':'Accepted Estimate'}])
        self.assertEqual({r['kind'] for r in view['rows']},{'inbound_lead','deal','estimate','customer_attention'})

    def test_existing_apollo_lead_today_does_not_prompt_duplicate_followup(self):
        a,c=fixture();v=build_sales(a,c,[],now=NOW)
        t=build_today({'rows':[{'id':'1','name':'Inbound','followup':'DUE','action':'Email now'}]}, {}, {},{}, {'signals':[]},now=NOW,sales_intelligence=v)
        self.assertIn('existing Apollo',t['sections']['Follow-ups due'][0]['next_action'])
        self.assertNotIn('Email now',str(t))

    def test_html_escapes_all_provider_content_and_blocks_untrusted_links(self):
        a,c=fixture();c['Leads'][0]['Full_Name']='<script>bad</script>'
        v=build_sales(a,c,[],now=NOW);v['rows'][0]['link']='javascript:bad'
        h=render_sales(v);self.assertNotIn('<script>',h);self.assertNotIn('javascript:',h);self.assertIn('&lt;script&gt;',h)

    def test_feedback_idempotent_sticky_dnc_and_never_grants_provider_authority(self):
        a,c=fixture();row=build_sales(a,c,[],now=NOW)['rows'][0]
        with tempfile.TemporaryDirectory() as tmp:
            ledger=SalesFeedback(Path(tmp)/'existing.db')
            for choice in ('DO NOT CONTACT','DO NOT CONTACT','GOOD'):
                result=ledger.record(row,row['version'],choice,'owner',NOW)
                self.assertEqual(result['provider_writes'],0)
            with sqlite3.connect(ledger.path) as db:self.assertEqual(db.execute('select count(*) from sales_shadow_feedback').fetchone()[0],2)
            self.assertEqual(ledger.latest()[row['key']]['choice'],'DO NOT CONTACT')
            self.assertNotIn(row['key'],[r['key'] for r in build_sales(a,c,[],now=NOW,feedback=ledger.latest())['rows']])
            with self.assertRaises(ValueError):ledger.record(row,'wrong','GOOD','owner',NOW)

    def test_sales_auth_precedes_projection_reads_and_feedback_requires_exact_origin(self):
        class Verifier:
            def verify(self,token):
                if token!='human':raise ValueError('No human')
                return SimpleNamespace(actor='owner',subject='owner')
        a,c=fixture();view=build_sales(a,c,[],now=NOW);row=view['rows'][0]
        with tempfile.TemporaryDirectory() as tmp:
            read_patch=patch('workflow.automation.today.read_internal_attention',return_value=view);read=read_patch.start();self.addCleanup(read_patch.stop)
            app=FastAPI();install_phase7_canary_routes(app,verifier=Verifier(),client=object(),store=SimpleNamespace(db_path=Path(tmp)/'automation.db'),
                       account_id='1',from_address='fixture@example.test',allowed_origin='https://example.test',clock=lambda:NOW)
            client=TestClient(app)
            with patch('workflow.automation.today.read_internal_attention',return_value=view):
                self.assertEqual(client.get('/v1/operator/sales').status_code,401);read.assert_not_called()
                headers={'Cf-Access-Jwt-Assertion':'human'}
                self.assertEqual(client.get('/v1/operator/sales',headers=headers).status_code,200)
                url='/v1/operator/sales/review/'+row['key']
                data={'version':row['version'],'choice':'GOOD'}
                self.assertEqual(client.post(url,data=data,headers=headers).status_code,403)
                self.assertEqual(client.post(url,data=data,headers={**headers,'Origin':'https://example.test'}).status_code,200)
                self.assertEqual(client.post(url,data={'version':'wrong','choice':'GOOD'},headers={**headers,'Origin':'https://example.test'}).status_code,409)


class ApolloReaderTests(unittest.TestCase):
    def test_fixed_read_allowlist_has_no_outreach_enrichment_or_custom_path_escape(self):
        requests=[]
        reader=ApolloReader(SimpleNamespace(api_key='fixture'),transport=httpx.MockTransport(lambda r:(requests.append((r.method,r.url.path)) or httpx.Response(200,json={}))))
        for kind,params in (('send',{}),('contacts',{'email':'target'}),('contacts',{'page':21})):
            with self.subTest(kind=kind,params=params):
                with self.assertRaises(ValueError):reader.read(kind,**params)
        self.assertEqual(requests,[]);reader.read('contacts',page=1);reader.close()
        self.assertEqual(requests,[('POST','/api/v1/contacts/search')])

    def test_incomplete_or_changing_inventory_fails_closed(self):
        for body in ({'pagination':{'total_entries':2001}}, {'pagination':{'total_entries':2,'total_pages':1},'contacts':[{'id':'one'}]}):
            with self.subTest(body=body):
                reader=ApolloReader(SimpleNamespace(api_key='fixture'),transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body)))
                with self.assertRaises(ValueError):reader.workspace()
                reader.close()

    def test_provider_error_never_leaks_response_or_token(self):
        reader=ApolloReader(SimpleNamespace(api_key='private-fixture'),transport=httpx.MockTransport(lambda r:httpx.Response(403,text='private-fixture')))
        with self.assertRaisesRegex(ValueError,'HTTP 403') as exc:reader.read('labels')
        self.assertNotIn('private-fixture',str(exc.exception));reader.close()

    def test_read_budget_does_not_retry_unknown_response(self):
        reader=ApolloReader(SimpleNamespace(api_key='fixture'),limit=1,transport=httpx.MockTransport(lambda r:httpx.Response(200,json={})))
        reader.read('labels')
        with self.assertRaises(ValueError):reader.read('labels')
        reader.close()


class SalesRuntimeTests(unittest.TestCase):
    def test_cached_shadow_projects_without_provider_calls_or_new_business_store(self):
        from workflow.automation import sales_observation_runtime as runtime
        a,c=fixture()
        snapshot={v:c.get(k,[]) for k,v in {'Leads':'leads','Contacts':'contacts','Accounts':'accounts','Deals':'deals','Cases':'cases'}.items()}
        saved={'observed_at':NOW.isoformat(),'snapshot':snapshot}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'apollo.json').write_text(json.dumps(a))
            (root/'crm.json').write_text(json.dumps({'at':NOW.isoformat(),'crm':c}))
            (root/'permits.json').write_text(json.dumps({'at':NOW.isoformat(),'records':[]}))
            def trusted(path,*args):
                return saved if path.name=='business-observation.json' else json.loads(path.read_text())
            with patch.object(runtime,'ROOT',root),patch.object(runtime.lc,'trusted_json',side_effect=trusted),patch.object(runtime,'ApolloReader') as reader:
                v=runtime.observe(SimpleNamespace(dry_run=True),SimpleNamespace(apollo=None),now=NOW)
                reader.assert_not_called();self.assertEqual(v['cold_outbound'],'OFF');self.assertEqual(v['tasks_created'],0)
                (root/'STOP').touch()
                self.assertEqual(runtime.observe(SimpleNamespace(dry_run=True),None,now=NOW)['state'],'DISABLED')
                reader.assert_not_called()

    def test_stale_crm_snapshot_is_not_displayed_as_current_collision_evidence(self):
        from workflow.automation import sales_observation_runtime as runtime
        a,c=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'apollo.json').write_text(json.dumps(a))
            def trusted(path,*args):
                return {'observed_at':(NOW-timedelta(days=1)).isoformat(),'snapshot':{}} if path.name=='business-observation.json' else json.loads(path.read_text())
            with patch.object(runtime,'ROOT',root),patch.object(runtime.lc,'trusted_json',side_effect=trusted):
                with self.assertRaisesRegex(ValueError,'CRM observation stale'):
                    runtime.observe(SimpleNamespace(dry_run=True),SimpleNamespace(apollo=None),now=NOW)
