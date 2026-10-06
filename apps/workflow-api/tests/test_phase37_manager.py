"""Owner consolidation, stale evidence, local intent and zero provider transport."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
import json,sqlite3,tempfile,unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from workflow.automation.manager_store import ManagerStore
from workflow.automation.manager_sources import registry,evidence_health
from workflow.automation.manager_runtime import refresh,sync_events,sync_priorities,ref,key
from workflow.automation.manager_intelligence import build_manager,proposals,priorities,render_manager
from workflow.automation.manager_preparation import prepare,prepare_forms
from workflow.automation.manager_forms import models,preview
from workflow.automation.ads_intelligence import proposal
from workflow.automation.ads_runtime import persist
from workflow.operator_manager_api import install_manager_routes
from workflow.operator_access import AccessPrincipal

NOW=datetime(2026,10,6,1,tzinfo=timezone.utc)

def inputs():
    at=NOW.isoformat()
    return {'acquisition-intelligence':{'at':at,'source_health':[{'source':'search_console','state':'WORKING','observed_at':at}],
        'content_queue_count':1,'content_queue':[{'id':'query-id','service':'Commercial Wi-Fi','language':'FR','existing_page':'https://opticable.ca/fr/services/wifi/',
            'why':'Observed commercial query','why_now':'Dated organic visibility','target_query':'wifi commercial','search_sample':{'observed_at':at,'impressions':11},
            'icp':'Business buyer','geography':'QUÉBEC'}]},'status':{'captured_at':at,'signals':[
            {'name':'Internal automation','enabled':True,'configured':12,'expires_at':'2026-11-01T22:09:41+00:00'},
            {'name':'Customer communication','enabled':True,'configured':4,'expires_at':'2026-11-02T02:46:00+00:00'}],
            'activity':{'jobs':[]}},'business':{'at':at,'observed_at':at,'snapshot':{'observed_at':at,'leads':[]}}}


def ad(store):
    ev={'provider':'GOOGLE_ADS','source_reference':'inventory','observed_at':NOW.isoformat(),
        'valid_until':(NOW+timedelta(days=7)).isoformat(),'freshness':'CURRENT','confidence':'MODERATE','truth_class':'NATIVE_MEASURED','limitations':[]}
    r=proposal('GOOGLE_ADS_CAMPAIGN','Security cameras','FR',[ev],NOW,{},problem='No active serving campaign',change='Review FR camera pilot')
    store.record(r,{'draft':'Unsent campaign spec'});return store.rows()[0]

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'phase12-autonomy.db';self.store=ManagerStore(self.path);self.store.setup()
    def tearDown(self):self.tmp.cleanup()
    def test_a_new_genuine_quote_event_and_priority(self):
        i=inputs();i['business']['snapshot']['leads']=[{'id':'native-lead','Created_Time':NOW.isoformat(),'Lead_Status':'New'}]
        refresh(i,self.store,NOW);v=build_manager(i,self.store,NOW)
        self.assertTrue(any(e['value']['kind']=='LEAD' for e in v['events']))
        self.assertTrue(any('inquiry' in p['what'] for p in v['today']))
        self.assertTrue(all(e['value']['classification']=='NATURAL_BUSINESS_EFFECT' for e in v['events'] if e['value']['kind']=='LEAD'))
    def test_b_apollo_hot_reply_owner_unchanged(self):
        i=inputs();i['sales-conversations']={'conversations':[{'conversation_id':'c','company':'Customer','urgency':'HOT','next_best_action':'REPLY','draft':{'body':'Quote clarification'},'current_owner':'APOLLO_CLAUDE'}]}
        v=build_manager(i,self.store,NOW);self.assertEqual(v['sections']['sales']['attention_count'],1)
        self.assertIn('CLAUDE_APOLLO',v['sections']['sales']['ownership']);self.assertFalse(v['execution_authorized'])
    def test_c_website_actual_draft_and_no_publication(self):
        p=prepare(inputs(),self.store,NOW);self.assertEqual(len(p['created']),1)
        row=self.store.rows()[0];self.assertTrue(row['detail']['draft']['copy']);self.assertTrue(row['detail']['draft']['faq'])
        self.assertFalse(any(r['publication_allowed'] for r in row['detail']['repurposing']))
        self.assertEqual(row['record']['target_system'],'WEBSITE');self.assertIsNone(row['detail']['repository_branch'])
    def test_d_ads_review_never_mutates(self):
        row=ad(self.store);v=proposals(self.store,registry(inputs(),NOW),NOW)
        self.assertEqual(v[0]['domain'],'ads');self.assertFalse(v[0]['execution_authorized']);self.assertFalse(self.store.execution_allowed())
    def test_e_customer_trigger_keeps_exact_account(self):
        i=inputs();i['trigger-intelligence']={'at':NOW.isoformat(),'rows':[{'key':'t','company_id':'company','company_name':'Customer','priority_class':'ACT NOW','description':'Verified project',
            'observed_at':NOW.isoformat(),'collision':{'crm_account_ids':['native-account'],'existing_customer':True}}]}
        v=refresh(i,self.store,NOW);self.assertIn('CRM:ACCOUNT:native-account',v['crosswalk'].values())
    def test_f_stale_source_and_confidence(self):
        ad(self.store);future=NOW+timedelta(days=9);v=proposals(self.store,registry(inputs(),future),future)
        self.assertEqual(v[0]['readiness'],'NEEDS_REFRESH');self.assertEqual(v[0]['confidence'],'INSUFFICIENT')
        self.assertEqual(next(s for s in registry(inputs(),future) if s['source_id']=='search_console')['data_health'],'STALE')
    def test_g_duplicate_signal_exact_crosswalk(self):
        i=inputs();i['business']['snapshot']['leads']=[{'id':'lead','Created_Time':NOW.isoformat(),'Lead_Status':'New'}]
        ids=sync_priorities(i,self.store,NOW);r=deepcopy(self.store.rows('optibrain.business_priority')[0]['record'])
        r.update(priority_id='b'*64,domain='SALES_INTELLIGENCE',targets=[ref('OUTREACH','CONVERSATION','conversation')],what='Hot conversation')
        self.store.record(r);cross={key(ref('OUTREACH','CONVERSATION','conversation')):key(ref('CRM','LEAD','lead'))}
        ps=priorities(self.store,[],registry(i,NOW),NOW,crosswalk=cross)
        self.assertEqual(len(ps),1);self.assertEqual(len(ps[0]['priority_ids']),2)
    def test_h_reject_survives_identical_refresh(self):
        prepare(inputs(),self.store,NOW);r=self.store.rows()[0]
        self.store.feedback('PROPOSAL',r['record']['proposal_id'],r['payload_hash'],'REJECT','owner',NOW,reason='Not relevant',conditions='New demand evidence')
        x=prepare(inputs(),self.store,NOW+timedelta(hours=1));self.assertFalse(x['created'])
        p=proposals(self.store,registry(inputs(),NOW),NOW)[0];self.assertEqual(p['status'],'REJECTED');self.assertEqual(p['feedback']['reason'],'Not relevant')
    def test_i_approve_ads_records_intent_only(self):
        r=ad(self.store);x=self.store.feedback('PROPOSAL',r['record']['proposal_id'],r['payload_hash'],'APPROVE','owner',NOW)
        self.assertFalse(x['execution_authorized']);self.assertEqual(x['provider_writes'],0)
        p=proposals(self.store,[],NOW)[0];self.assertEqual(p['status'],'APPROVED');self.assertEqual(p['approval'],'OWNER_INTENT_ONLY')
    def test_j_expiry_surfaces_before_deadline_no_renewal(self):
        i=inputs();self.assertFalse(sync_priorities(i,self.store,NOW))
        future=NOW+timedelta(days=14);i['status']['captured_at']=future.isoformat();ids=sync_priorities(i,self.store,future)
        self.assertGreaterEqual(len(ids),2);self.assertTrue(all('Review' in r['record']['what'] for r in self.store.rows('optibrain.business_priority')))
        self.assertEqual(i['status']['signals'][0]['expires_at'],'2026-11-01T22:09:41+00:00')
    def test_k_margin_unknown(self):
        v=build_manager({},self.store,NOW);self.assertEqual(v['sections']['finance']['profitability']['state'],'UNKNOWN')
    def test_l_empty_brief_no_invented_actions(self):
        v=build_manager({},self.store,NOW);self.assertFalse(v['today']);self.assertFalse(v['brief']['what_changed']);self.assertTrue(v['brief']['empty_day'])
    def test_m_failure_isolated_source_health(self):
        i=inputs();i['acquisition-intelligence']['source_health'].append({'source':'apollo','state':'PROVIDER_ERROR','reason':'HTTP503','observed_at':NOW.isoformat()})
        v=build_manager(i,self.store,NOW)
        self.assertEqual(next(s for s in v['sources'] if s['source_id']=='apollo')['data_health'],'PROVIDER_ERROR')
        self.assertEqual(next(s for s in v['sources'] if s['source_id']=='search_console')['data_health'],'GREEN')
    def test_n_unchanged_run_no_duplicate_drafts_events(self):
        first=refresh(inputs(),self.store,NOW);counts=self.store.counts();second=refresh(inputs(),self.store,NOW)
        self.assertEqual(first['proposal_counts'],second['proposal_counts']);self.assertEqual(counts,self.store.counts())
        self.assertEqual(second['refresh']['events_added'],0);self.assertFalse(second['preparation']['created'])
    def test_approval_cannot_transfer_changed_revision(self):
        r=ad(self.store);self.store.feedback('PROPOSAL',r['record']['proposal_id'],r['payload_hash'],'APPROVE','owner',NOW)
        new=deepcopy(r['record']);new.update(revision=2,recommended_change='Changed budget');self.store.record(new,{'draft':'Changed'})
        self.assertNotEqual(proposals(self.store,[],NOW)[0]['status'],'APPROVED')
    def test_never_suppresses_changed_idea(self):
        r=ad(self.store);self.store.feedback('PROPOSAL',r['record']['proposal_id'],r['payload_hash'],'NEVER','owner',NOW)
        new=deepcopy(r['record']);new.update(revision=2,recommended_change='Changed');self.store.record(new,{'draft':'Changed'})
        self.assertEqual(proposals(self.store,[],NOW)[0]['status'],'NEVER')
    def test_activity_no_apollo_attribution_no_replay(self):
        self.store.receipt('forms','run',NOW,{'origin':'SCHEDULED','state':'COMPLETED','counters':{'forms_created':2}})
        self.store.receipt('forms','run',NOW,{'origin':'SCHEDULED','state':'COMPLETED','counters':{'forms_created':2}})
        self.assertEqual(self.store.activity(NOW)['1d']['completed_counters']['forms_created'],2)
    def test_results_require_real_comparison_evidence(self):
        r=ad(self.store)
        with self.assertRaises(ValueError):self.store.learning(r['record']['proposal_id'],1,NOW,{'outcome':'SUCCESS','evidence':['approval'],'limitations':['small sample']})
        self.store.learning(r['record']['proposal_id'],1,NOW,{'outcome':'INSUFFICIENT_DATA','evidence':['No execution'], 'limitations':['No paid outcomes']})
        self.assertEqual(self.store.counts()['learning'],1)
    def test_form_unknowns_and_verified_gap_preview(self):
        forms=models();self.assertIsNone(forms[0]['required_fields']);self.assertIsNone(preview(forms[0]))
        f={**forms[0],'design_verified':True,'attribution_fields':[]};p=preview(f)
        self.assertFalse(p['replace_production']);self.assertEqual(p['provider_writes'],0);self.assertTrue(p['mapping'])
    def test_verified_form_gap_creates_shared_local_proposal(self):
        form={**models()[0],'observed_at':NOW.isoformat(),'design_verified':True,'attribution_fields':[]}
        result=prepare_forms({'forms':{'models':[form]}},self.store,NOW)
        self.assertEqual(len(result['created']),1);self.assertEqual(self.store.rows()[0]['record']['target_system'],'ZOHO_FORM')
        self.assertFalse(prepare_forms({'forms':{'models':[form]}},self.store,NOW)['created'])
    def test_machine_schema_validates_real_manager(self):
        from jsonschema import Draft202012Validator,FormatChecker
        schema=json.loads((Path(__file__).resolve().parents[3]/'docs/optibrain-manager.schema.json').read_text())
        Draft202012Validator(schema,format_checker=FormatChecker()).validate(refresh(inputs(),self.store,NOW))
    def test_render_untrusted_text_escaped(self):
        v=build_manager({},self.store,NOW);v['sections']['sales']['ownership']='<script>alert(1)</script>'
        html=render_manager(v);self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html)
    def test_restore_preserves_feedback_without_authority(self):
        r=ad(self.store);self.store.feedback('PROPOSAL',r['record']['proposal_id'],r['payload_hash'],'APPROVE','owner',NOW)
        target=Path(self.tmp.name)/'restored.db'
        with sqlite3.connect(self.path) as db,sqlite3.connect(target) as copied:db.backup(copied)
        recovered=ManagerStore(target);self.assertEqual(recovered.counts()['feedback'],1);self.assertFalse(recovered.execution_allowed())
    def test_registry_covers_provider_and_auth_data_separation(self):
        r=registry(inputs(),NOW);self.assertTrue({'crm','books','forms','ga4','google_ads','holo','cloudflare','github'} <= {s['source_id'] for s in r})
        optional=next(s for s in r if s['source_id']=='holo');self.assertFalse(optional['required'])
        gbp=next(s for s in r if s['source_id']=='gbp');self.assertEqual(gbp['authentication_health'],'BLOCKED');self.assertEqual(gbp['data_health'],'INTENTIONALLY_OPTIONAL')

class ManagerRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'automation.db';self.verifier=SimpleNamespace(verify=self.verify)
        app=FastAPI();install_manager_routes(app,verifier=self.verifier,db_path=self.path,origin='https://owner.invalid',clock=lambda:NOW);self.client=TestClient(app)
    def tearDown(self):self.tmp.cleanup()
    def verify(self,token):
        if token!='fixture':raise ValueError('Identity required')
        return SimpleNamespace(actor='owner')
    def test_auth_and_no_execution_route(self):
        self.assertEqual(self.client.get('/v1/operator/manager').status_code,401)
        self.assertEqual(self.client.post('/v1/operator/manager/execute').status_code,404)
    def test_json_bounded_machine_state(self):
        with patch('workflow.operator_manager_api.collect',return_value={}):
            r=self.client.get('/v1/operator/manager?format=json',headers={'Cf-Access-Jwt-Assertion':'fixture'})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['schema'],1);self.assertIn('no-store',r.headers['cache-control'])
        self.assertLess(len(r.content),100000)
    def test_feedback_origin_hash_and_approval_intent(self):
        store=ManagerStore(self.path.with_name('phase12-autonomy.db'));r=ad(store)
        body={'kind':'PROPOSAL','target':r['record']['proposal_id'],'version':r['payload_hash'],'choice':'APPROVE'}
        h={'Cf-Access-Jwt-Assertion':'fixture','Origin':'https://owner.invalid'}
        self.assertEqual(self.client.post('/v1/operator/manager/feedback',json=body,headers={**h,'Origin':'https://evil.invalid'}).status_code,403)
        self.assertEqual(self.client.post('/v1/operator/manager/feedback',json={**body,'version':'f'*64},headers=h).status_code,409)
        reply=self.client.post('/v1/operator/manager/feedback',json=body,headers=h);self.assertEqual(reply.status_code,200);self.assertFalse(reply.json()['execution_authorized'])
    def test_oversized_and_extra_fields_denied(self):
        h={'Cf-Access-Jwt-Assertion':'fixture','Origin':'https://owner.invalid'}
        self.assertEqual(self.client.post('/v1/operator/manager/feedback',json={'extra':'x'*10000},headers=h).status_code,413)
