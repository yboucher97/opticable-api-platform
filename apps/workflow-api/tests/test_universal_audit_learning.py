from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from workflow.automation.action_evidence import (ActionEvidence,FIELDS,envelope,validate,approval_binding,
    execute_action,rollback_action,redact)
from workflow.automation.optimization_learning import (evidence_bundle,validate_bundle,correlate,
    validate_baseline,validate_measurement_plan,classify_result,learning_confidence,relevant_learning,
    future_intelligence_contract,validate_learning)
from workflow.automation.manager_store import ManagerStore
from workflow.automation.learning_runtime import sync_learning_contract,sync_todo_lifecycle
from workflow.automation.manager_intelligence import build_manager
from test_website_preview import canonical,REPO,PID,NOW


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.j=ActionEvidence(Path(self.tmp.name)/'existing.db');self.now=datetime.now(timezone.utc)
        self.plan=envelope('audit-fixture-001','CONFIG_CHANGE',{'type':'CONFIG','identity':'fixture'},self.now,
            mutation=True,authority_class='EXPLICIT_TEST_FIXTURE',before_state={'value':1},proposed_state={'value':2},reason='Verified mismatch',
            rollback_capability='FULLY_REVERSIBLE',rollback_target={'value':1},rollback_procedure='Restore captured value after checking current version')

    def test_every_required_field_and_private_reasoning(self):
        self.assertEqual(set(self.plan),FIELDS)
        for field in FIELDS:
            with self.subTest(field=field):
                p=deepcopy(self.plan);p.pop(field)
                with self.assertRaises(ValueError):validate(p)
        with self.assertRaises(ValueError):redact({'chain_of_thought':'private'})

    def test_before_and_rollback_are_required_before_effect(self):
        for field in ('before_state','rollback_target','rollback_procedure'):
            with self.subTest(field=field):
                p=deepcopy(self.plan);p[field]=None
                self.j.plan(p,self.now)
                with self.assertRaises(ValueError):self.j.start(p['action_id'],self.now,authority_check=lambda:None)
                self.plan['action_id']+='x'
        p=deepcopy(self.plan);p['rollback_capability']='UNKNOWN'
        with self.assertRaises(ValueError):ActionEvidence.executable(p,self.now)

    def test_no_readback_http200_is_failure_and_history_is_durable(self):
        self.j.plan(self.plan,self.now);self.j.start(self.plan['action_id'],self.now,authority_check=lambda:None)
        self.assertFalse(self.j.finish(self.plan['action_id'],self.now,provider_success=True,response={'http_status':200}))
        state=self.j.get(self.plan['action_id']);self.assertEqual(state['status'],'FAILED')
        self.assertEqual(state['final_result']['stage'],'READ_AFTER_WRITE')
        self.assertEqual(state['before_state'],{'value':1})
        self.assertTrue(self.j.verify_integrity(self.plan['action_id']))
        with self.j.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM action_evidence')

    def test_readback_verifies_actual_state_and_rollback_has_own_action(self):
        state={'value':1}
        def execute():state.update(value=2);return {'success':True,'http_status':200}
        result=execute_action(self.j,self.plan,self.now,authority_check=lambda:None,execute=execute,
            readback=lambda:dict(state),verify=lambda actual,expected:actual==expected)
        self.assertTrue(result['success']);self.assertEqual(self.j.get(self.plan['action_id'])['after_state'],{'value':2})
        def restore():state.update(value=1);return {'success':True}
        rb=rollback_action(self.j,self.plan['action_id'],datetime.now(timezone.utc),reason='Guardrail regression',actor='human:owner',
            authority_check=lambda:None,execute=restore,readback=lambda:dict(state),verify=lambda actual,expected:actual==expected)
        self.assertNotEqual(rb['action_id'],self.plan['action_id']);self.assertTrue(rb['success'])
        self.assertEqual(self.j.get(self.plan['action_id'])['after_state'],{'value':2})
        self.assertTrue(any(r['event']=='ROLLBACK_RESULT' for r in self.j.timeline()))

    def test_missing_readback_must_be_a_real_documented_provider_limit(self):
        p=deepcopy(self.plan);p['readback_supported']=False
        self.j.plan(p,self.now);self.j.start(p['action_id'],self.now,authority_check=lambda:None)
        self.assertTrue(self.j.finish(p['action_id'],self.now,provider_success=True,limitation='Provider exposes no GET/status endpoint; native receipt retained'))
        self.assertEqual(self.j.get(p['action_id'])['readback']['state'],'UNAVAILABLE_DOCUMENTED')

    def test_irreversible_consequence_compensation_and_exact_owner_approval(self):
        p=deepcopy(self.plan);p.update(irreversible=True,rollback_capability='IRREVERSIBLE',approval_required=True,
            consequence='Recipient may consume email',compensating_action='Owner-approved correction email; original remains sent')
        self.j.plan(p,self.now)
        with self.assertRaises(ValueError):self.j.start(p['action_id'],self.now,authority_check=lambda:None)
        with self.assertRaises(ValueError):self.j.approve(p['action_id'],'human:owner',self.now,binding='old',expires_at=(self.now+timedelta(minutes=1)).isoformat())
        self.j.approve(p['action_id'],'human:owner',self.now,binding=approval_binding(p),expires_at=(self.now+timedelta(minutes=1)).isoformat())
        self.j.start(p['action_id'],self.now,authority_check=lambda:None)
        changed=deepcopy(p);changed['proposed_state']={'value':3}
        with self.assertRaises(ValueError):self.j.plan(changed,self.now)
        with self.assertRaises(ValueError):rollback_action(self.j,p['action_id'],self.now,reason='Undo',actor='owner',authority_check=lambda:None,execute=lambda:None,readback=lambda:None,verify=lambda a,b:True)

    def test_failure_stage_and_partial_effects_and_redaction(self):
        def bad():raise TimeoutError('Bearer PRIVATE secret=secret-value')
        with self.assertRaises(TimeoutError):execute_action(self.j,self.plan,self.now,authority_check=lambda:None,
            execute=bad,readback=lambda:None,verify=lambda a,b:False)
        failure=self.j.get(self.plan['action_id'])['final_result']
        self.assertEqual(failure['error_class'],'TimeoutError');self.assertEqual(failure['partial_effects'],'UNKNOWN')
        value=redact({'headers':{'Authorization':'Bearer private','X-Api-Key':'key'},'url':'https://user:pass@host/x?token=private',
            'message':'Bearer private password=foo','nested':[{'private_key':'private'}]})
        self.assertNotIn('private',json.dumps(value).replace('private_key','field'))
        self.assertNotIn('user:pass',str(value));self.assertNotIn('foo',str(value))

    def test_separate_authority_and_automatic_reason_and_search(self):
        called=[]
        def deny():raise PermissionError('Root policy closed')
        self.j.plan(self.plan,self.now)
        with self.assertRaises(PermissionError):self.j.start(self.plan['action_id'],self.now,authority_check=deny)
        self.assertEqual(self.j.get(self.plan['action_id'])['status'],'PLANNED')
        self.assertTrue(self.j.timeline(query='Verified mismatch',automatic=True))
        with self.assertRaises(ValueError):self.j.timeline(limit=1000)


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=ManagerStore(Path(self.tmp.name)/'phase12-autonomy.db');self.now=datetime.now(timezone.utc)
        self.item=canonical(self.store)
        self.item=self.store.website_proposal(PID)
        self.bundle=evidence_bundle(self.item['record'],self.item['detail'],self.now)
        self.measurement={'primary_metric':'qualified inquiries','secondary_metrics':[], 'guardrails':['Inquiry quality'],
            'window':'28 days after execution','minimum_evidence':'Owner reviews usable inquiry volume and lineage; sparse outcomes are inconclusive',
            'attribution_limits':'Traffic changes and seasonality; no causal claim'}
        self.baseline={'proposal_id':PID,'production_version':'a'*40,'entity':'camera-page','captured_at':self.now.isoformat(),
            'items':[{'source':'FORMS','source_at':self.now.isoformat(),'observed_at':self.now.isoformat(),'metric':'qualified inquiries','value':1,'evidence_ref':'fixture/real-baseline'}],
            'traffic_mix':{'organic':1},'business_outcomes':{'qualified':1},'tracking_completeness':'UNKNOWN'}

    def executed(self):
        j=ActionEvidence(self.store.path)
        p=envelope('learning-action-001','PAGE_CHANGE',{'type':'PAGE','identity':'camera-page'},self.now,
            mutation=True,measurable=True,approval_required=True,authority_class='EXPLICIT_OWNER_PRODUCTION_APPROVAL',proposal_id=PID,before_state={'sha':'a'*40},proposed_state={'sha':'b'*40},
            rollback_capability='FULLY_REVERSIBLE',rollback_target='a'*40,rollback_procedure='Guarded forward revert',
            baseline=self.baseline,measurement_plan=self.measurement,evidence_bundle=self.bundle,
            exact_versions={'environment':'production','proposal_revision':1,'proposal_hash':self.item['payload_hash'],'production_version':'a'*40,
                'proposed_version':'b'*40,'test_evidence':{'sha':'b'*40,'state':'PASS','reference':'fixture/tests'},
                'preview_evidence':{'sha':'b'*40,'state':'VERIFIED','reference':'fixture/preview'}})
        j.plan(p,self.now);j.approve(p['action_id'],'human:owner',self.now,binding=approval_binding(p),expires_at=(self.now+timedelta(minutes=5)).isoformat())
        execute_action(j,p,self.now,authority_check=lambda:None,execute=lambda:{'success':True},
            readback=lambda:{'sha':'b'*40},verify=lambda a,b:a==b)
        return j.get(p['action_id'])

    def value(self):
        action=self.executed();factors={k:'UNKNOWN' for k in ('sample_size','duration','data_completeness','tracking_coverage',
            'seasonality','traffic_source_changes','simultaneous_changes','repeatability','business_relevance')}
        value={'proposal_id':PID,'execution_action_id':action['action_id'],'site':'opticable.ca','service':'camera','language':'FR',
            'audience':'commercial','channel':'SEO','change_class':'COPY','baseline':self.baseline,
            'after_evidence':[{'source':'FORMS','source_at':datetime.now(timezone.utc).isoformat(),'evidence_ref':'fixture/after'}],
            'result':'INCONCLUSIVE','confidence':learning_confidence(factors),'confounders':['Traffic mix'],
            'limitations':['Small sample and missing attribution'],'lesson':'Insufficient outcome evidence; retain experiment context',
            'reuse_eligible':False,'scope':'SITE-SPECIFIC'}
        return value,action

    def test_evidence_bundle_provenance_countersearch_and_competitor_context(self):
        self.assertTrue(self.bundle['counterevidence_search'])
        for e in self.bundle['items']:self.assertTrue({'source','source_at','observed_at','completeness','evidence_class','truth_class'}<=set(e))
        broken=deepcopy(self.bundle);broken['counterevidence_search']=[]
        with self.assertRaises(ValueError):validate_bundle(broken)
        broken=deepcopy(self.bundle);broken['source_coverage']={'ga4':{'available_relevant':True,'state':'UNREVIEWED'}}
        with self.assertRaises(ValueError):validate_bundle(broken)
        r=deepcopy(self.item['record']);r['source_evidence'].append({'provider':'COMPETITOR','source_reference':'public/page','observed_at':self.now.isoformat(),'truth_class':'OBSERVED'})
        self.assertEqual(evidence_bundle(r,self.item['detail'],self.now)['items'][-1]['evidence_class'],'CONTEXT')

    def test_bounded_correlation_distinguishes_lineage_from_causality(self):
        nodes=[{'id':'campaign','kind':'CAMPAIGN','click_id_type':'gclid','keys':{'click_id':'gclid'},'evidence_ref':'ads'},
            {'id':'session','kind':'SESSION','click_id_type':'gclid','keys':{'click_id':'gclid','session_id':'s'},'evidence_ref':'ga4'},
            {'id':'form','kind':'FORM','keys':{'session_id':'s','submission_id':'f'},'evidence_ref':'forms'},
            {'id':'lead','kind':'LEAD','keys':{'submission_id':'f','lead_id':'l'},'evidence_ref':'crm'},
            {'id':'deal','kind':'DEAL','keys':{'lead_id':'l','deal_id':'d'},'evidence_ref':'crm/deal'},
            {'id':'estimate','kind':'ESTIMATE','keys':{'deal_id':'d','estimate_id':'e'},'evidence_ref':'books/estimate'},
            {'id':'invoice','kind':'INVOICE','keys':{'estimate_id':'e','invoice_id':'i'},'evidence_ref':'books/invoice'},
            {'id':'revenue','kind':'REVENUE','keys':{'invoice_id':'i'},'evidence_ref':'books/paid','measured':True}]
        result=correlate(nodes);self.assertTrue(result['revenue_lineage_verified']);self.assertFalse(result['causal_claim_allowed'])
        nodes[2]['keys']['session_id']='other';self.assertFalse(correlate(nodes)['revenue_lineage_verified'])
        nodes.extend([{'id':'query','kind':'SEARCH_QUERY','keys':{'page_url':'page'},'evidence_ref':'gsc'},
            {'id':'page','kind':'LANDING_PAGE','keys':{'page_url':'page'},'evidence_ref':'gsc'}])
        self.assertIn('WEAKLY_SUPPORTED',[e['relationship_strength'] for e in correlate(nodes)['edges']])
        with self.assertRaises(ValueError):correlate(nodes*100)

    def test_baseline_frozen_before_execution_and_measurement_required(self):
        validate_baseline(self.baseline,self.now);validate_measurement_plan(self.measurement)
        for field in self.measurement:
            with self.subTest(field=field):
                broken=deepcopy(self.measurement);broken.pop(field)
                with self.assertRaises(ValueError):validate_measurement_plan(broken)
        b=deepcopy(self.baseline);b['captured_at']=(self.now+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):validate_baseline(b,self.now)
        b=deepcopy(self.baseline);b['items'][0].pop('source_at')
        with self.assertRaises(ValueError):validate_baseline(b,self.now)

    def test_material_revision_invalidates_action_execution(self):
        action=self.executed()
        record=deepcopy(self.item['record']);record['revision']=2;record['recommended_change']='Material new copy';record['updated_at']=self.now.isoformat()
        self.store.record(record,self.item['detail'])
        p=deepcopy(action);p.update(action_id='another-action-001',status='PLANNED',started_at=None,completed_at=None,approval_record=None,after_state=None)
        j=ActionEvidence(self.store.path);j.plan(p,self.now)
        with self.assertRaises(ValueError):j.start(p['action_id'],self.now,authority_check=lambda:None)

    def test_inconclusive_creation_and_site_service_language_isolation(self):
        value,action=self.value();lid=self.store.record_learning(PID,1,datetime.now(timezone.utc),value)
        self.assertEqual(len(self.store.learning_records()),1);self.assertEqual(self.store.latest_learning(PID,1)['result'],'INCONCLUSIVE')
        ctx={k:value[k] for k in ('site','service','language','audience','channel','change_class')}
        self.assertEqual(self.store.relevant_learning(ctx)[0]['evidence_class'],'CONTEXT')
        for field,other in [('site','ai.opticable.ca'),('service','AI'),('language','EN'),('channel','ADS')]:
            with self.subTest(field=field):self.assertFalse(self.store.relevant_learning({**ctx,field:other}))
        value['reuse_eligible']=True
        with self.assertRaises(ValueError):validate_learning(value,action)

    def test_measured_negative_result_supports_counterevidence(self):
        value,action=self.value();value['result']='NEGATIVE';value['reuse_eligible']=True
        value['measurement_metric']='qualified inquiries';value['after_evidence'][0].update(metric='qualified inquiries',value=0)
        value['comparison']={'before':1,'after':0,'sufficient':True,'complete':True,'guardrail_breach':False,'higher_is_better':True}
        value['confidence']=learning_confidence({k:'ADEQUATE' for k in value['confidence']['factors']})
        self.store.record_learning(PID,1,datetime.now(timezone.utc),value)
        ctx={k:value[k] for k in ('site','service','language','audience','channel','change_class')}
        self.assertEqual(self.store.relevant_learning(ctx)[0]['evidence_class'],'COUNTEREVIDENCE')
        value['comparison']['sufficient']=False
        with self.assertRaises(ValueError):validate_learning(value,action)

    def test_unknown_context_never_establishes_reusable_equivalence(self):
        value,action=self.value()
        for field in ('site','service','language','audience','channel','change_class'):
            with self.subTest(field=field):
                unknown={**value,field:'UNKNOWN'}
                validate_learning(unknown,action)  # Inconclusive evidence remains valid history.
                context={k:unknown[k] for k in ('site','service','language','audience','channel','change_class')}
                self.assertEqual(relevant_learning([{'value':unknown}],context),[])
                with self.assertRaisesRegex(ValueError,'Unknown learning context'):
                    validate_learning({**unknown,'reuse_eligible':True},action)

    def test_no_learning_from_preview_or_approval_or_safety_self_modification(self):
        value,action=self.value();action['exact_versions']['environment']='preview'
        with self.assertRaises(ValueError):validate_learning(value,action)
        action['exact_versions']['environment']='production';value['recommended_policy_changes']={'approval_boundaries':'weaker'}
        with self.assertRaises(ValueError):validate_learning(value,action)
        value.pop('recommended_policy_changes');value['confidence']['value']='HIGH'
        with self.assertRaises(ValueError):validate_learning(value,action)
        self.assertEqual(classify_result(1,20,sufficient=False,complete=True),'INCONCLUSIVE')
        self.assertEqual(classify_result(1,20,sufficient=True,complete=False),'INCONCLUSIVE')
        self.assertEqual(classify_result(1,20,sufficient=True,complete=True,guardrail_breach=True),'MIXED')

    def test_existing_store_reuse_cards_and_todo_history(self):
        from workflow.automation.manager_runtime import sync_priorities
        input_data={'business':{'snapshot':{'observed_at':self.now.isoformat(),'leads':[{'id':'fresh-lead','Created_Time':self.now.isoformat(),'Lead_Status':'New'}]}}}
        sync_priorities(input_data,self.store,self.now)
        result=sync_learning_contract({},self.store,self.now);self.assertEqual(result['historical_learning_count'],0)
        self.assertEqual(sync_learning_contract({},self.store,self.now)['bundles_updated'],0)
        view=build_manager(input_data,self.store,self.now)
        card=view['proposals'][0]['decision_card']
        self.assertTrue(card['audit_record_id']);self.assertTrue(card['counterevidence']['search']);self.assertEqual(card['previous_relevant_learning'],[])
        self.assertEqual(card['recommended_decision']['value'],'REVISE')
        sync_todo_lifecycle(self.store,view,self.now)
        before=len(ActionEvidence(self.store.path).timeline())
        sync_todo_lifecycle(self.store,view,self.now+timedelta(minutes=1));self.assertEqual(len(ActionEvidence(self.store.path).timeline()),before)
        suppressed=deepcopy(view);suppressed['priorities']=[]
        sync_todo_lifecycle(self.store,suppressed,self.now+timedelta(minutes=2))
        sync_todo_lifecycle(self.store,suppressed,self.now+timedelta(minutes=3))
        sync_todo_lifecycle(self.store,view,self.now+timedelta(minutes=4))
        events=ActionEvidence(self.store.path).timeline()
        self.assertTrue(any(e['action_type']=='TODO_SUPPRESSED' for e in events));self.assertTrue(any(e['action_type']=='TODO_REOPENED' for e in events))

    def test_future_email_file_financial_evidence_ready_without_writers(self):
        value={'reason':'Exact source evidence','confidence':'HIGH','evidence_refs':['receipt'], 'owner_correction':None,'undo_state':'AVAILABLE',
            'original_location':'mail/attachment','destination':'drive/project','before_hash':'a'*64,'after_hash':'a'*64,
            'document_type':'INVOICE','business_entities':['CRM:ACCOUNT:1'],'rollback_procedure':'Restore original location/remove derived copy where supported'}
        future_intelligence_contract('file_move',value)
        value['after_hash']='b'*64
        with self.assertRaises(ValueError):future_intelligence_contract('file_move',value)
        match={k:value[k] for k in ('reason','confidence','evidence_refs','owner_correction','undo_state')}
        match.update(document_observed='invoice/hash',books_candidate='books/invoice/1',bank_candidate=None,
            amount_date_reference={'amount':100,'date':'2026-10-06','reference':'observed'},client_vendor='client/1',project=None,match_class='POSSIBLE',books_mutation=False)
        future_intelligence_contract('financial_match',match);match['books_mutation']=True
        with self.assertRaises(ValueError):future_intelligence_contract('financial_match',match)

class AuditRouteTests(unittest.TestCase):
    def test_owner_authentication_precedes_audit_reads_and_detail_is_private(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from types import SimpleNamespace
        from workflow.operator_manager_api import install_manager_routes
        class Verifier:
            def verify(self,token):
                if token!='valid':raise ValueError('Human identity required')
                return SimpleNamespace(actor='human:fixture')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'automation.db';store=ManagerStore(path.with_name('phase12-autonomy.db'));item=canonical(store)
            aid=item['audit_action_id'];app=FastAPI();install_manager_routes(app,verifier=Verifier(),db_path=path,origin='https://example.invalid')
            client=TestClient(app)
            self.assertEqual(client.get('/v1/operator/manager/audit').status_code,401)
            headers={'Cf-Access-Jwt-Assertion':'valid'}
            result=client.get('/v1/operator/manager/audit/'+aid,headers=headers)
            self.assertEqual(result.status_code,200);self.assertIn('no-store',result.headers['cache-control'])
            self.assertEqual(result.json()['envelope']['action_id'],aid);self.assertEqual(result.json()['history_integrity'],'PASS')
            self.assertEqual(client.get('/v1/operator/manager/audit?limit=201',headers=headers).status_code,422)
