"""Owner transparency, exact comparisons, no-op preparation and cross-site fences."""
from copy import deepcopy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch
from test_website_preview import PreviewCase,canonical,package,configured_repo,NOW,PID,REPO,PROJECT
from workflow.automation.decision_card import decision_card,validate_card,FIELDS,TECHNICAL,render_card,OPTIONS
from workflow.automation.website_registry import SITES,site_for,require_site,LiveSiteScope
from workflow.automation.website_preview_model import RepositoryState,preparation_package,new_preview,validate_preview_state
from workflow.automation.website_preview_cloudflare_live import PreviewCloudflareHTTP,CloudflarePreviewAdapter
from workflow.automation.website_preview_github_live import BoundedGitHubHTTP
from workflow.automation.manager_intelligence import build_manager
from workflow.automation.manager_runtime import sync_priorities

AI='yboucher97/opticable-ai'


class CardTests(PreviewCase):
    def test_required_fields_and_rejection_of_missing_explanation(self):
        card=decision_card(self.store.website_proposal(PID))
        self.assertTrue(FIELDS<=set(card))
        for field in FIELDS:
            bad=deepcopy(card);bad.pop(field)
            with self.subTest(field=field),self.assertRaises(ValueError):validate_card(bad)

    def test_before_after_and_technical_metadata(self):
        v=self.prepared_value();card=decision_card(self.store.website_proposal(PID),v)
        self.assertEqual(card['before_after'][0]['before'],'Original camera copy')
        self.assertEqual(card['before_after'][0]['after'],'Commercial security cameras')
        self.assertTrue(TECHNICAL<=set(card['technical']))
        self.assertEqual(card['technical']['rollback_reference'],v['base_sha'])
        self.assertEqual(card['technical']['proposal_sha'],v['head_sha'])

    def test_pros_cons_uncertainty_visible_without_expansion(self):
        card=decision_card(self.store.website_proposal(PID));html=render_card(card)
        prefix=html.split('<details>')[0]
        self.assertIn('Some technical specificity is lost',prefix)
        self.assertIn('Conversion improvement is not proven',prefix)
        self.assertIn('CONFIDENCE',prefix)
        self.assertEqual(card['recommended_decision']['value'],'REVISE')
        self.assertEqual(card['owner_options'],OPTIONS)
        self.assertEqual(set(card['proven_vs_assumed']),{'observed_fact','tested_fact','hypothesis','inference','unknown'})

    def test_confidence_reason_rollback_and_options_enforced(self):
        card=decision_card(self.store.website_proposal(PID))
        for field,value in [('confidence',{'value':'HIGH','reason':''}),('rollback',''),('pros',[]),('cons',[]),('owner_options',['APPROVE'])]:
            bad={**card,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):validate_card(bad)

    def test_legacy_hash_and_rejection_semantics_remain_stable(self):
        item=self.store.website_proposal(PID);before=item['payload_hash']
        self.assertNotIn('decision_card',item['record']);self.assertNotIn('decision_card',item['detail'])
        self.store.feedback('PROPOSAL',PID,before,'REJECT','owner',NOW)
        self.assertEqual(self.store.website_proposal(PID)['payload_hash'],before)
        self.assertEqual(self.store.website_proposal(PID)['effective_status'],'REJECTED')
        self.assertFalse(self.store.execution_allowed())

    def test_explicit_invalid_card_cannot_enter_canonical_journal(self):
        item=self.store.website_proposal(PID);r={**item['record'],'revision':2,'decision_card':{'summary':'opaque'}}
        with self.assertRaises(ValueError):self.store.record(r,item['detail'])

    def test_unknown_technical_before_state_blocks_approval(self):
        item=self.store.website_proposal(PID)
        with self.assertRaises(ValueError):self.store.feedback('PROPOSAL',PID,item['payload_hash'],'APPROVE','owner',NOW)

    def test_stale_evidence_lowers_card_confidence(self):
        item=self.store.website_proposal(PID)
        card=decision_card(item,evidence=[{**item['record']['source_evidence'][0],'freshness':'STALE'}])
        self.assertEqual(card['confidence']['value'],'LOW')
        self.assertIn('stale',card['confidence']['reason'])

    def test_superseded_preview_tests_cannot_certify_new_proposal(self):
        self.ready();prior=self.store.website_proposal(PID);preview=self.store.preview(PID,NOW)
        changed=deepcopy(prior['record']);changed['revision']+=1
        changed['business_problem']='A new independently observed requirement'
        self.store.record(changed,prior['detail'])
        card=decision_card(self.store.website_proposal(PID),preview)
        self.assertEqual(card['confidence']['value'],'LOW')
        self.assertEqual(card['proven_vs_assumed']['tested_fact'],[])
        self.assertEqual(card['technical']['preview_revision'],prior['record']['revision'])
        self.assertIn('superseded',str(card['proven_vs_assumed']['unknown']))

    def test_large_card_snapshot_retains_owner_queue_metadata(self):
        from workflow.operator_manager_api import load_manager
        state={'current_state':'WAITING_CUSTOMER','next_action':'NO_ACTION','actionability':'WAITING',
            'confidence':'HIGH','source_facts':['native'],'latest_authoritative_event':{'source':'BOOKS',
                'event_type':'QUOTE_SENT','event_at':NOW.isoformat(),'observed_at':NOW.isoformat()}}
        saved={'at':NOW.isoformat(),'active_priority_ids':[],
            'commercial_states':{str(i):state for i in range(5400)}}
        raw=json.dumps(saved).encode();formatted=json.dumps(saved,indent=2).encode()
        self.assertGreater(len(raw),1048576);self.assertLess(len(raw),2097152)
        self.assertGreater(len(formatted),2097152);self.assertLess(len(formatted),4194304)
        def bounded(path,maximum):
            if len(formatted)>maximum:raise ValueError('Snapshot exceeded reader bound')
            return json.loads(formatted)
        with patch('workflow.operator_manager_api.collect',return_value={}),patch('workflow.operator_manager_api.lc.trusted_json',side_effect=bounded):
            view=load_manager(self.store.path,NOW)
        self.assertEqual(view['state'],'CURRENT');self.assertEqual(view['projection_at'],NOW.isoformat())

    def test_escaped_full_exact_copy(self):
        card=decision_card(self.store.website_proposal(PID));card['before_after']=[{'field':'copy','before':'<script>old</script>','after':'x'*1500,'state':'EXACT'}]
        html=render_card(card);self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html);self.assertIn('x'*1500,html)

    def test_measurement_loop_requires_actual_production_tuple(self):
        value={'outcome':'SUCCESS','evidence':['receipt/metrics'],'limitations':['not randomized'],'execution_receipt':'receipt',
            'baseline_window':'28 days before','post_window':'28 days after','before_state':{'starts':2},'after_state':{'starts':3},
            'metric_result':{'metric':'quote starts','before':2,'after':3},'learning':'Observed increase; causation is uncertain',
            'execution':{'environment':'preview','proposal_id':PID,'revision':1}}
        with self.assertRaises(ValueError):self.store.learning(PID,1,NOW,value)
        value['execution']['environment']='production';self.store.learning(PID,1,NOW,value)
        card=build_manager({},self.store,NOW)['proposals'][0]['decision_card']
        self.assertEqual(card['measured_result']['metric_result']['after'],3)
        self.assertEqual(card['learning'],value['learning'])

    def test_todo_linkage_and_real_deadline_only(self):
        self.ready();sync_priorities({},self.store,NOW);v=build_manager({},self.store,NOW)
        todo=v['priorities'][0]['todo_explanation']
        self.assertEqual(todo['proposal_ids'],[PID]);self.assertIsNone(todo['deadline'])
        self.assertTrue(all(todo.get(k) for k in ['why_this_exists','latest_event','action_required','if_ignored','confidence']))
        self.store.feedback('PROPOSAL',PID,self.store.website_proposal(PID)['payload_hash'],'REQUEST_REVISION','owner',NOW)
        sync_priorities({},self.store,NOW+timedelta(seconds=1))
        self.assertIn('REVISION',build_manager({},self.store,NOW+timedelta(seconds=1))['priorities'][0]['todo_explanation']['action_required'])


class SiteTests(PreviewCase):
    def test_observer_refresh_preserves_scoped_preview_and_new_evidence_stales_it(self):
        from workflow.automation.ads_runtime import persist
        self.ready();prior=self.store.website_proposal(PID)
        incoming=deepcopy(prior);incoming['detail'].pop('repository')
        incoming['record']['status']='PREVIEW_READY'
        persist({'proposals':[incoming],'priorities':[],'assets':[]},self.store)
        current=self.store.website_proposal(PID)
        self.assertEqual(current['payload_hash'],prior['payload_hash'])
        self.assertEqual(self.store.preview(PID,NOW)['preview_state'],'PREVIEW_READY')
        incoming=deepcopy(incoming);incoming['record']['business_problem']='New independently observed business problem'
        persist({'proposals':[incoming],'priorities':[],'assets':[]},self.store)
        current=self.store.website_proposal(PID)
        self.assertEqual(current['record']['revision'],prior['record']['revision']+1)
        self.assertEqual(current['detail']['repository'],REPO)
        self.assertEqual(self.store.preview(PID,NOW)['stale_state'],'SUPERSEDED')

    def test_preserving_release_updates_only_code_pins(self):
        import importlib.util
        from pathlib import Path
        from test_camera_release_preservation import PreservationTests
        path=Path(__file__).resolve().parents[3]/'ops/decision_cards_multisite/stage_runtime.py'
        spec=importlib.util.spec_from_file_location('decision_stage',path);stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
        fixture=PreservationTests();prior=fixture.fixture();before=deepcopy(prior)
        internal,customer,activation=stage.preserved(prior,Path('/immutable/new/source'),fixture.helper())
        self.assertEqual(prior,before);self.assertEqual(customer,before['customer_policy'])
        internal['lifecycle']['source_hashes']=before['internal_policy']['lifecycle']['source_hashes'];activation['release_sha']='old'
        self.assertEqual(internal,before['internal_policy']);self.assertEqual(activation,before['internal_activation'])

    def test_both_sites_and_distinct_production_architectures(self):
        self.assertEqual(SITES['opticable.ca']['repository'],REPO)
        self.assertEqual(SITES['ai.opticable.ca']['repository'],AI)
        self.assertNotEqual(SITES['opticable.ca']['production_deployment_model'],SITES['ai.opticable.ca']['production_deployment_model'])
        self.assertEqual(len({s['preview_target'] for s in SITES.values()}),2)

    def test_wrong_repository_and_page_rejected(self):
        with self.assertRaises(ValueError):site_for(repository=AI,page='https://opticable.ca/fr/')
        with self.assertRaises(ValueError):site_for(repository=REPO,page='https://ai.opticable.ca/en/')
        with self.assertRaises(ValueError):require_site('opticable.ca',AI,PROJECT)

    def test_wrong_preview_target_rejected_before_any_transport(self):
        v=self.prepared_value();v['preview_project']='opticable-ai-optimization-preview'
        with self.assertRaises(ValueError):validate_preview_state(v)
        with self.assertRaises(ValueError):RepositoryState('github:'+AI,'GITHUB',AI,'main','main',preview_project=PROJECT).value()

    def test_ai_transport_has_independent_endpoint_backstop(self):
        scope=LiveSiteScope('ai.opticable.ca','a'*64,1)
        cloud=PreviewCloudflareHTTP(scope=scope);git=BoundedGitHubHTTP(scope=scope)
        with self.assertRaises(ValueError):cloud.request('PUT','/accounts/81d07d311d1b51e5e04b451d1f254850/workers/scripts/'+PROJECT,raw=b'x')
        with self.assertRaises(ValueError):git.request('GET','/repos/'+REPO,'unused')
        self.assertEqual(cloud.calls,[]);self.assertEqual(git.calls,[])
        adapter=CloudflarePreviewAdapter(scope=scope)
        with self.assertRaises(ValueError):adapter.validate_preview_url('https://12345678-opticable-optimization-preview.yboucher.workers.dev/fr/')

    def test_manager_always_represents_both_sites_without_invented_sha(self):
        v=build_manager({},self.store,NOW);sites=v['sections']['websites']['sites']
        self.assertEqual([s['site_id'] for s in sites],list(SITES))
        self.assertTrue(all(s['production_sha'] is None for s in sites))
        self.assertTrue(all(s['health']=='NOT_COLLECTED' for s in sites))

    def test_no_op_package_is_exact_zero_change_and_cannot_be_spoofed(self):
        item=self.store.website_proposal(PID);r=deepcopy(item['record'])
        r.update(proposal_id='a'*64,proposal_type='SITE_PREVIEW_VERIFICATION',target_url_or_record='https://ai.opticable.ca/fr/',
            target_object={'system':'WEBSITE','entity_type':'WEBSITE_PAGE','entity_id':'https://ai.opticable.ca/fr/'})
        d={'site_id':'ai.opticable.ca','repository':AI,'base_sha':'b'*40,'no_op':True}
        self.store.record(r,d);item=self.store.website_proposal('a'*64)
        p=preparation_package(item,AI,'b'*40,[],[],['BUILD','FR','EN','CANONICAL','ASSETS'],['evidence/ai.json'])
        self.assertTrue(p['no_op']);self.assertEqual(p['changes'],[])
        with self.assertRaises(ValueError):preparation_package(item,AI,'c'*40,[],[],['BUILD'],['evidence/ai.json'])
        with self.assertRaises(ValueError):preparation_package(item,AI,'b'*40,['page.html'],[{'path':'page.html','before':'old','after':'new'}],['BUILD'],['evidence/ai.json'])
        card=decision_card(item);self.assertEqual(card['before_after'][0]['state'],'NO_CHANGE')
        self.assertEqual(card['site'],'ai.opticable.ca')
