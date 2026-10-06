"""Offline integration and adversarial controls, using only temporary Git repos."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import hmac
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from workflow.automation.acquisition_store import digest
from workflow.automation.ads_intelligence import proposal, evidence
from workflow.automation.manager_store import ManagerStore
from workflow.automation.optimization_store import OptimizationStore
from workflow.automation.manager_intelligence import build_manager, render_manager
from workflow.automation.manager_runtime import sync_priorities
from workflow.automation.website_preview_model import (RepositoryState, branch_name, relative_file, preparation_package,
    new_preview, preview_ready, approval_current, approval_binding, handoff_contract, STATES)
from workflow.automation.website_preview_git import LocalGitAdapter, ApprovedScript, ApprovedBuildRunner, file_hash
from workflow.automation.website_preview_providers import (FakeGitHubProvider, FakeCloudflareProvider, FakeHTTP, ReadResult,
    safe_preview_url, verify_deployment, validate_http)
from workflow.automation.website_preview_runtime import prepare_local, reconcile, manager_projection
from workflow.automation.website_preview_import import import_website_report
from workflow.automation.website_preview_events import HMACVerifier, handle_webhook

NOW=datetime(2026,10,6,6,tzinfo=timezone.utc)
PID='49d2893d1498325eb5ae8f5a7304d1e3d199d03afcb4c6d0383dd7ed6ab32c17'
REPO='yboucher97/opticable-website'
PROJECT='opticable-optimization-preview'
HOST='camera-isolated.example.test'
URL='https://'+HOST+'/camera/'
CANONICAL='https://opticable.ca/fr/services/systemes-cameras-securite/'
FIXTURES=Path(__file__).parent/'fixtures/website-preview'


def git(path,*args):
    return subprocess.run(['git','-c','core.hooksPath=/dev/null','-C',str(path),*args],check=True,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}).stdout.strip()


def canonical(store,*,revision=1,repository=REPO):
    r=proposal('LANDING_PAGE','Security cameras','FR',[evidence('WEBSITE','camera-local',NOW.isoformat())],NOW,
        {'target_url':CANONICAL},problem='Commercial intent needs a scoped camera-copy review',change='Review commercial camera copy')
    r.update(proposal_id=PID,revision=revision,target_object={'system':'WEBSITE','entity_type':'WEBSITE_PAGE','entity_id':CANONICAL},
        rollback_reference='Retain original base SHA',status='PROPOSED')
    detail={'repository':repository,'draft':{'heading':'Cameras','copy':'Commercial security cameras','cta':'Quote','faq':[], 'links':[]}}
    store.record(r,detail);return next(p for p in store.rows() if p['record']['proposal_id']==PID)


def configured_repo(base,path=None):
    return RepositoryState('github:'+REPO,'GITHUB',REPO,'main','main',base,None,NOW.isoformat(),
        str(path) if path else None,'LOCAL_FIXTURE','CLOUDFLARE',PROJECT,'COMPLETE',NOW.isoformat())


def package(store,base,*,before='Original camera copy',after='Commercial security cameras',tests=None):
    return preparation_package(store.website_proposal(PID),REPO,base,['page.html'],
        [{'path':'page.html','before':before,'after':after}],tests if tests is not None else ['BUILD','FR','FORMS'],['evidence/camera.json'])


def provider_fixtures(v,now=NOW):
    gh={'branch:main':{'repository':REPO,'branch':'main','sha':v['base_sha']},
        'repository':{'repository':REPO,'default_branch':'main'},
        'branch:'+v['branch']:{'repository':REPO,'branch':v['branch'],'sha':v['head_sha']},
        'workflow:'+v['head_sha']:{'repository':REPO,'head_sha':v['head_sha'],'branch':v['branch'],'checks':{k:'PASS' for k in v['required_tests']}}}
    d={k:v[k] for k in ('proposal_id','proposal_revision','repository','branch','head_sha','base_sha')}
    d.update(id='fake-immutable-version-1',project=PROJECT,environment='preview',non_production_proof=True,state='success',url=URL,source_at=now.isoformat())
    cf={'project':{'project':PROJECT},'configuration':{'project':PROJECT,'environment':'preview','isolated':True,'production_routes':False},
        'sha:'+v['head_sha']:d,'deployment:'+d['id']:d,'deployments':[d]}
    body='<html><title>Security cameras</title><meta name="robots" content="noindex,nofollow"><link rel="canonical" href="'+CANONICAL+'"><form></form><a data-preview-cta="quote" href="#quote">Quote</a></html>'
    response={'status':200,'body':body,'manifest':{k:v[k] for k in ('proposal_id','proposal_revision','repository','branch','head_sha','base_sha')}}
    return gh,cf,{URL:response}


class PreviewCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('No network allowed'));self.network.start();self.addCleanup(self.network.stop)
        self.store=ManagerStore(self.root/'journal.db');canonical(self.store)
    def prepared_value(self):
        p=package(self.store,'a'*40);v=new_preview(p,configured_repo('a'*40),NOW,'Caméras commerciales')
        v.update(head_sha='b'*40,stale_state='CURRENT',build_state='PASS',test_state='PASS',state='PREVIEW_PENDING')
        result={'state':'PASS','head_sha':v['head_sha'],'command_class':'BUILD','duration_seconds':1,'exit_code':0,'artifact_location':'fixture.log','warnings':[]}
        v['build_result']=result;v['tests']={k:{**result,'command_class':k} for k in v['required_tests']}
        self.store.save_preview(v);return v
    def ready(self):
        v=self.prepared_value();g,c,h=provider_fixtures(v)
        self.reconcile_fixtures(g,c,h);return self.store.preview(PID,NOW)
    def reconcile_fixtures(self,g,c,h,*,now=NOW,git_adapter=None):
        gp=FakeGitHubProvider(REPO,g,now);cp=FakeCloudflareProvider(PROJECT,c,now,allowed_hosts=[HOST],production_hosts=['opticable.ca','www.opticable.ca'])
        http=FakeHTTP(h);r=reconcile(self.store,gp,cp,http,now,git=git_adapter)
        self.assertEqual(gp.writes,[]);self.assertEqual(cp.writes,[]);self.assertEqual(r['provider_writes'],0)
        return r,gp,cp,http


class ModelTests(PreviewCase):
    def test_branch_normalization_traceability_bound(self):
        name=branch_name(PID,'Caméras commerciales avec CTA '+('x'*100))
        self.assertTrue(name.startswith('optimization/'+PID+'-cameras-commerciales'))
        self.assertLessEqual(len(name),120)
        self.assertEqual(branch_name(PID,'Caméras commerciales'),branch_name(PID,'Cameras commerciales'))
    def test_branch_injection(self):
        for slug in ('../main','a;touch x','$(id)','a`id`','a\nmain','a\x00','refs/heads/main','a@{x}','--','a|x','a&&x','a\\x','a^x','a~1','a:main'):
            with self.subTest(slug=slug),self.assertRaises(ValueError):branch_name(PID,slug)
    def test_proposal_spoof(self):
        for value in ('unknown','a'*63,'../main',PID+'x',PID.upper()):
            with self.subTest(pid=value),self.assertRaises(ValueError):branch_name(value,'camera')
    def test_scope_traversal_and_configuration(self):
        for f in ('../page.html','/tmp/page.html','a/../page.html','a//b','./page.html','.git/config','.github/workflows/build.yml','wrangler.toml','deploy/run.py','ops/key','credentials.txt','package.json','requirements.txt','a\nb'):
            with self.subTest(path=f),self.assertRaises(ValueError):relative_file(f)
    def test_package_untrusted_command_and_wrong_repo(self):
        item=self.store.website_proposal(PID)
        for change in ({'path':'page.html','command':'rm -rf /'},{'path':'other.html','before':'a','after':'b'}):
            with self.subTest(change=change),self.assertRaises(ValueError):preparation_package(item,REPO,'a'*40,['page.html'],[change],['FR'],['evidence/a.json'])
        with self.assertRaises(ValueError):preparation_package(item,'evil/repo','a'*40,['page.html'],[{'path':'page.html','before':'a','after':'b'}],['FR'],['evidence/a.json'])
    def test_website_package_cannot_target_a_commercial_object(self):
        item=deepcopy(self.store.website_proposal(PID))
        item['record']['target_object']={'system':'BOOKS','entity_type':'ESTIMATE','entity_id':'quote'}
        with self.assertRaises(ValueError):
            preparation_package(item,REPO,'a'*40,['page.html'],[{'path':'page.html','before':'a','after':'b'}],['BUILD'],['evidence/camera.json'])

    def test_required_test_sets(self):
        for tests in ([],['EXECUTE'],['FR','FR']):
            with self.subTest(tests=tests),self.assertRaises(ValueError):package(self.store,'a'*40,tests=tests)
        self.assertEqual(package(self.store,'a'*40,tests=['FR'])['required_tests'],['FR'])
    def test_repository_source_reuses_shared_database(self):
        r=configured_repo('a'*40);self.store.repository_state(r,NOW)
        self.assertEqual(self.store.repository_states(),[r.value()])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM acquisition_entities WHERE kind="SOURCE"').fetchone()[0],1)
        self.store.repository_state(r,NOW);self.assertEqual(len(self.store.repository_states()),1)
    def test_repository_mismatch_and_timestamps(self):
        for r in (replace(configured_repo('a'*40),repository_id='github:evil/repo'),replace(configured_repo('a'*40),source_at='yesterday'),replace(configured_repo('a'*40),last_observed_sha='short')):
            with self.subTest(repo=r),self.assertRaises(ValueError):r.value()
    def test_old_proposals_load_without_preview_or_migration(self):
        old=OptimizationStore(self.store.path);self.assertEqual(len(old.rows()),1)
        before=old.rows()[0]['payload_hash'];v=build_manager({},self.store,NOW)
        self.assertEqual(v['proposals'][0]['website_preview']['message'],'No preview prepared')
        self.assertEqual(before,old.rows()[0]['payload_hash'])
    def test_canonical_revision_and_repo_storage_boundary(self):
        v=self.prepared_value()
        for changes in ({'proposal_id':'c'*64},{'proposal_revision':2},{'proposal_hash':'x'*64},{'repository':'evil/repo'}):
            wrong={**v,**changes}
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.store.save_preview(wrong)
    def test_immutable_observations_optimistic_concurrency(self):
        v=self.prepared_value();v['state']='TESTING'
        self.store.save_preview(v,expected_sequence=1)
        with self.assertRaises(ValueError):self.store.save_preview({**v,'state':'TEST_FAILED'},expected_sequence=1)
        self.assertEqual(self.store.preview(PID,NOW)['state'],'TESTING')
    def test_additive_schema_rollback_on_copy(self):
        self.prepared_value()
        with self.store.connect() as db:db.execute('DROP TABLE website_preview_observations');db.execute('DROP TABLE website_preview_webhooks')
        self.assertEqual(len(OptimizationStore(self.store.path).rows()),1);self.assertIsNone(self.store.preview(PID,NOW))
    def test_new_revision_supersedes_previous_preparation(self):
        self.prepared_value();canonical(self.store,revision=2)
        v=self.store.preview(PID,NOW);self.assertEqual(v['stale_state'],'SUPERSEDED');self.assertFalse(preview_ready(v,NOW))
    def test_secret_scan_class_does_not_allow_credential_fields(self):
        v=self.prepared_value();v['tests']['SECRET_SCAN']={'state':'PASS','head_sha':v['head_sha']}
        self.store.save_preview(v)
        for field in ('api_key','access_token','secret'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.store.save_preview({**v,'tests':{'SECRET_SCAN':{'state':'PASS',field:'never-store-this'}}})


class ProviderTests(PreviewCase):
    def test_live_reconciliation_uses_operator_time_after_each_read(self):
        from dataclasses import replace
        v=self.prepared_value();g,c,h=provider_fixtures(v);current=[NOW]
        github=FakeGitHubProvider(REPO,g,NOW,max_reads=30)
        cloud=FakeCloudflareProvider(v['preview_project'],c,NOW,allowed_hosts=[HOST],production_hosts=['opticable.ca'],max_reads=30)
        for provider in (github,cloud):
            original=provider._read
            def later(key,original=original):
                current[0]+=timedelta(seconds=2)
                result=original(key)
                return replace(result,source_at=current[0].isoformat(),observed_at=current[0].isoformat())
            provider._read=later
        reconcile(self.store,github,cloud,FakeHTTP(h),NOW,clock=lambda:current[0])
        value=self.store.preview(PID,current[0])
        self.assertTrue(preview_ready(value,current[0]));self.assertEqual(value['last_verified_at'],current[0].isoformat())

    def test_exact_sha_preview_ready_and_owner_package(self):
        v=self.ready();self.assertTrue(preview_ready(v,NOW));p=manager_projection(self.store.website_proposal(PID),v,NOW)
        self.assertEqual(p['verified_url'],URL)
        self.assertEqual(set(p['review_package']),{'WHY','EVIDENCE','CURRENT','PROPOSED','PREVIEW','TESTS','RISK','APPROVAL STATUS','production_action'})
    def test_preview_success_building_failure_missing(self):
        for state,expected in (('success','PREVIEW_READY'),('building','PREVIEW_PENDING'),('failure','FAILED'),('missing','VERIFIED_EMPTY')):
            with self.subTest(state=state):
                v=self.prepared_value();g,c,h=provider_fixtures(v)
                if state=='missing':c['sha:'+v['head_sha']]=[]
                else:c['sha:'+v['head_sha']]['state']=state;c['deployment:fake-immutable-version-1']['state']=state
                self.reconcile_fixtures(g,c,h);self.assertEqual(self.store.preview(PID,NOW)['preview_state'],expected)
    def test_cloudflare_401_403_are_blocked_not_empty(self):
        for status in (401,403):
            with self.subTest(status=status):
                v=self.prepared_value();g,c,h=provider_fixtures(v);c['configuration']={'http_status':status}
                _,_,cp,http=self.reconcile_fixtures(g,c,h)
                actual=self.store.preview(PID,NOW);self.assertEqual(actual['preview_state'],'BLOCKED_AUTH');self.assertEqual(actual['state'],'PROVIDER_BLOCKED')
                self.assertEqual(actual['provider_reads']['cloudflare']['failed'],1);self.assertIsNone(actual['provider_reads']['cloudflare']['source_at']);self.assertEqual(len(cp.reads),2);self.assertFalse(http.reads)
    def test_permission_denied_deployment_readback(self):
        v=self.prepared_value();g,c,h=provider_fixtures(v);c['deployment:fake-immutable-version-1']={'http_status':401}
        self.reconcile_fixtures(g,c,h);self.assertEqual(self.store.preview(PID,NOW)['preview_state'],'BLOCKED_AUTH')
    def test_failure_timeout_not_collected_not_empty(self):
        for fixture,expected in (({'timeout':True},'FAILED'),({'http_status':500},'FAILED'),({'read_state':'NOT_COLLECTED','data':None,'source_at':None},'NOT_COLLECTED')):
            with self.subTest(fixture=fixture):
                cp=FakeCloudflareProvider(PROJECT,{'configuration':fixture},NOW);r=cp.get_preview_configuration(PROJECT)
                self.assertEqual(r.state,expected);self.assertIsNone(r.data)
        cp=FakeCloudflareProvider(PROJECT,{},NOW,max_reads=1);cp.get_project(PROJECT);r=cp.get_project(PROJECT)
        self.assertEqual(r.state,'NOT_COLLECTED');self.assertEqual(r.attempted,0)
    def test_read_bounds_accounting_and_partial(self):
        at=NOW.isoformat();v=ReadResult('PARTIAL',[{'id':'partial'}],at,at,1,1,0);v.validate()
        for r in (ReadResult('COMPLETE',[],None,at,1,1,0),ReadResult('BLOCKED_AUTH',[],None,at,1,0,1),ReadResult('VERIFIED_EMPTY',[1],at,at,1,1,0)):
            with self.subTest(result=r),self.assertRaises(ValueError):r.validate()
        cp=FakeCloudflareProvider(PROJECT,{'deployments':[{}]*21},NOW);self.assertEqual(cp.list_deployments(PROJECT).state,'FAILED')
    def test_wrong_missing_sha_branch_proposal_repo_environment(self):
        cases=[{'head_sha':'c'*40},{'head_sha':None},{'branch':'optimization/wrong'},{'branch':'main'},{'proposal_id':'d'*64},{'proposal_revision':2},
            {'repository':'evil/repo'},{'base_sha':'d'*40},{'environment':'production'},{'environment':None},{'non_production_proof':False},{'project':'opticable-website'},{'source_at':(NOW-timedelta(days=2)).isoformat()}]
        for change in cases:
            with self.subTest(change=change):
                v=self.prepared_value();g,c,h=provider_fixtures(v);c['sha:'+v['head_sha']].update(change)
                self.reconcile_fixtures(g,c,h);actual=self.store.preview(PID,NOW)
                self.assertFalse(preview_ready(actual,NOW));self.assertIsNone(manager_projection(self.store.website_proposal(PID),actual,NOW)['verified_url'])
    def test_unexpected_provider_response(self):
        for data in ('unexpected',7,{'unexpected':'field'}):
            with self.subTest(data=data):
                v=self.prepared_value();g,c,h=provider_fixtures(v);c['sha:'+v['head_sha']]=data
                self.reconcile_fixtures(g,c,h);self.assertFalse(preview_ready(self.store.preview(PID,NOW),NOW))
        v=self.prepared_value();g,c,h=provider_fixtures(v);c['sha:'+v['head_sha']]['access_token']='never-persist'
        self.reconcile_fixtures(g,c,h)
        self.assertEqual(self.store.preview(PID,NOW)['preview_state'],'FAILED')
        with self.store.connect() as db:
            self.assertFalse(any('never-persist' in row['value'] for row in db.execute('SELECT value FROM website_preview_observations')))
    def test_port_exception_records_failure_and_preserves_independent_proposal(self):
        first=self.prepared_value();item=self.store.website_proposal(PID);second_id='f'*64
        r=deepcopy(item['record']);r['proposal_id']=second_id;self.store.record(r,item['detail'])
        second=deepcopy(first);second['proposal_id']=second_id;second['proposal_hash']=next(i for i in self.store.rows() if i['record']['proposal_id']==second_id)['payload_hash']
        second['branch']=branch_name(second_id,'Camera CTA');self.store.save_preview(second)
        g,c,h=provider_fixtures(first);g2,c2,h2=provider_fixtures(second);g.update(g2);c.update(c2);h.update(h2)
        # Both proposals share this fixture head, so the first fails its
        # workflow identity; the second still completes independently.
        gp=FakeGitHubProvider(REPO,g,NOW);cp=FakeCloudflareProvider(PROJECT,c,NOW,allowed_hosts=[HOST]);http=FakeHTTP(h)
        original=gp.get_branch
        def denied(repo,branch):
            if branch==first['branch']:raise PermissionError('fake denied')
            return original(repo,branch)
        with patch.object(gp,'get_branch',side_effect=denied):result=reconcile(self.store,gp,cp,http,NOW)
        self.assertEqual(len(result['proposals']),2)
        self.assertEqual(self.store.preview(PID,NOW)['preview_state'],'BLOCKED_AUTH')
        self.assertTrue(preview_ready(self.store.preview(second_id,NOW),NOW))
    def test_project_configuration_explicit_isolation(self):
        for change in ({'environment':'production'},{'environment':None},{'isolated':False},{'production_routes':True},{'project':'production'}):
            with self.subTest(change=change):
                v=self.prepared_value();g,c,h=provider_fixtures(v);c['configuration'].update(change)
                self.reconcile_fixtures(g,c,h);self.assertFalse(preview_ready(self.store.preview(PID,NOW),NOW))
    def test_preview_host_spoof_https_and_credentials(self):
        for url in ('http://'+HOST,'https://opticable.ca','https://'+HOST+'.evil.test','https://evil@'+HOST,'https://'+HOST+':444',
            'https://'+HOST+'/?token=a','https://'+HOST+'/#a','https://'+HOST+'/../a','https://'+HOST+'/%2e','https://'+HOST+'\\evil','https://'+HOST+'/a\n'):
            with self.subTest(url=url),self.assertRaises(ValueError):safe_preview_url(url,[HOST],['opticable.ca'])
    def test_redirect_to_production_and_http_failures(self):
        for change in ({'status':302,'redirects':['https://opticable.ca']},{'status':200,'final_url':'https://opticable.ca'},
            {'status':500},{'status':200,'redirects':[URL+'else']}):
            with self.subTest(change=change):
                v=self.prepared_value();g,c,h=provider_fixtures(v);h[URL].update(change)
                self.reconcile_fixtures(g,c,h);self.assertFalse(preview_ready(self.store.preview(PID,NOW),NOW))
    def test_page_forms_cta_canonical_marker(self):
        for old,new in (('<form></form>',''),('data-preview-cta="quote"',''),('noindex,nofollow','index'),(CANONICAL,'https://evil.test'),('Security cameras','Wrong page')):
            with self.subTest(old=old):
                v=self.prepared_value();g,c,h=provider_fixtures(v);h[URL]['body']=h[URL]['body'].replace(old,new)
                self.reconcile_fixtures(g,c,h);self.assertFalse(preview_ready(self.store.preview(PID,NOW),NOW))
        v=self.prepared_value();g,c,h=provider_fixtures(v);h[URL]['manifest']['head_sha']='e'*40
        self.reconcile_fixtures(g,c,h);self.assertFalse(preview_ready(self.store.preview(PID,NOW),NOW))
    def test_wrong_workflow_sha_and_required_checks(self):
        for change in ({'head_sha':'f'*40},{'branch':'main'},{'repository':'evil/repo'},{'checks':{'BUILD':'PASS'}}):
            with self.subTest(change=change):
                v=self.prepared_value();g,c,h=provider_fixtures(v);g['workflow:'+v['head_sha']].update(change)
                self.reconcile_fixtures(g,c,h);self.assertFalse(preview_ready(self.store.preview(PID,NOW),NOW))
    def test_workflow_and_default_branch_denied(self):
        for key in ('branch:main','workflow'):
            with self.subTest(key=key):
                v=self.prepared_value();g,c,h=provider_fixtures(v);g['workflow:'+v['head_sha'] if key=='workflow' else key]={'http_status':403}
                self.reconcile_fixtures(g,c,h);self.assertEqual(self.store.preview(PID,NOW)['preview_state'],'BLOCKED_AUTH')
    def test_default_branch_change_stale_and_no_downstream_reads(self):
        v=self.prepared_value();g,c,h=provider_fixtures(v);g['branch:main']['sha']='c'*40
        _,gp,cp,http=self.reconcile_fixtures(g,c,h)
        actual=self.store.preview(PID,NOW);self.assertEqual(actual['stale_state'],'NEEDS_REBASE');self.assertEqual(actual['state'],'STALE_BASE')
        self.assertEqual(len(gp.reads),1);self.assertEqual(cp.reads,[]);self.assertEqual(http.reads,[])
    def test_branch_change_invalidates_old_checks(self):
        v=self.prepared_value();g,c,h=provider_fixtures(v);g['branch:'+v['branch']]['sha']='c'*40
        self.reconcile_fixtures(g,c,h);actual=self.store.preview(PID,NOW)
        self.assertEqual(actual['tests'],{});self.assertEqual(actual['build_state'],'NOT_RUN');self.assertFalse(preview_ready(actual,NOW))
    def test_unchanged_fresh_preview_skips_expensive_work(self):
        v=self.ready();g,c,h=provider_fixtures(v);r,gp,cp,http=self.reconcile_fixtures(g,c,h)
        self.assertTrue(r['proposals'][0]['expensive_work_skipped']);self.assertEqual(len(gp.reads),2);self.assertFalse(cp.reads);self.assertFalse(http.reads)
    def test_fake_mutations_disabled_default_and_proposal_only(self):
        v=self.prepared_value();p=FakeGitHubProvider(REPO,{},NOW)
        with self.assertRaises(PermissionError):p.push_proposal_branch(REPO,v['branch'],v['head_sha'],PID)
        with self.assertRaises(PermissionError):p.open_draft_pr(REPO,v['branch'],PID)
        p=FakeGitHubProvider(REPO,{},NOW,allow_fake_mutations=True)
        self.assertEqual(p.push_proposal_branch(REPO,v['branch'],v['head_sha'],PID)['provider_writes'],0)
        self.assertTrue(p.open_draft_pr(REPO,v['branch'],PID)['draft'])
        with self.assertRaises(ValueError):p.push_proposal_branch(REPO,'main',v['head_sha'],PID)
        with self.assertRaises(ValueError):p.get_repository('evil/repo')
    def test_http_and_reconciliation_budgets(self):
        with self.assertRaises(ValueError):reconcile(self.store,None,None,None,NOW,maximum=4)
        h=FakeHTTP({},max_reads=1);h.get(URL)
        with self.assertRaises(TimeoutError):h.get(URL)


class ApprovalManagerTests(PreviewCase):
    def approve(self):
        v=self.ready();item=self.store.website_proposal(PID)
        self.store.feedback('PROPOSAL',PID,item['payload_hash'],'APPROVE','owner',NOW)
        return self.store.preview(PID,NOW)
    def test_approved_exact_sha_no_deployment(self):
        v=self.approve();self.assertEqual(v['owner_status'],'APPROVED');self.assertTrue(approval_current(v,NOW))
        view=build_manager({},self.store,NOW);p=view['proposals'][0]
        self.assertEqual(p['status'],'APPROVED');self.assertEqual(p['approval'],'EXACT_PREVIEW_OWNER_INTENT');self.assertFalse(self.store.execution_allowed())
    def test_approval_not_available_without_verified_preview(self):
        self.prepared_value();item=self.store.website_proposal(PID)
        with self.assertRaises(ValueError):self.store.feedback('PROPOSAL',PID,item['payload_hash'],'APPROVE','owner',NOW)
    def test_material_changes_invalidate_approval(self):
        changes=[{'head_sha':'c'*40},{'base_sha':'c'*40},{'tests':{}},{'required_tests':['FR']},{'preview_deployment_id':'changed'},
            {'preview_url':'https://other.example.test/'},{'http_validation':{}},{'semantic_hash':'x'*64},{'stale_state':'NEEDS_REBASE'}]
        for change in changes:
            with self.subTest(change=change):
                v=self.approve();v.pop('sequence');v.update(change);self.store.save_preview(v)
                current=self.store.preview(PID,NOW);self.assertEqual(current['owner_status'],'STALE_APPROVAL');self.assertFalse(approval_current(current,NOW))
    def test_approval_revision_and_expiry(self):
        self.approve();canonical(self.store,revision=2);v=self.store.preview(PID,NOW)
        self.assertEqual(v['owner_status'],'STALE_APPROVAL');self.assertEqual(v['state'],'SUPERSEDED')
    def test_readiness_receipt_ages_out(self):
        v=self.approve();future=NOW+timedelta(hours=2)
        self.assertFalse(preview_ready(v,future));self.assertFalse(approval_current(v,future));self.assertEqual(self.store.preview(PID,future)['owner_status'],'STALE_APPROVAL')
    def test_same_material_preview_reverification_preserves_unexpired_owner_binding(self):
        v=self.approve();future=NOW+timedelta(hours=2);g,c,h=provider_fixtures(v)
        self.reconcile_fixtures(g,c,h,now=future)
        self.assertTrue(approval_current(self.store.preview(PID,future),future))
        self.assertEqual(self.store.preview(PID,future)['owner_status'],'APPROVED')
    def test_approval_receipt_expiry_even_with_fresh_preview(self):
        v=self.approve();future=NOW+timedelta(hours=25);g,c,h=provider_fixtures(v,now=future)
        self.reconcile_fixtures(g,c,h,now=future)
        self.assertEqual(self.store.preview(PID,future)['owner_status'],'STALE_APPROVAL')
    def test_concurrent_preview_change_rejects_owner_receipt(self):
        self.ready();item=self.store.website_proposal(PID)
        original=self.store.preview
        def raced(*args):
            value=original(*args);changed=deepcopy(value);changed['state']='PREVIEW_PENDING';self.store.save_preview(changed)
            return value
        with patch.object(self.store,'preview',side_effect=raced),self.assertRaises(ValueError):
            self.store.feedback('PROPOSAL',PID,item['payload_hash'],'APPROVE','owner',NOW)
    def test_owner_revise_reject_defer(self):
        for choice,state in (('REQUEST_REVISION','REVISION_REQUESTED'),('REJECT','REJECTED'),('WAIT','DEFERRED')):
            with self.subTest(choice=choice):
                self.ready();item=self.store.website_proposal(PID);self.store.feedback('PROPOSAL',PID,item['payload_hash'],choice,'owner',NOW)
                v=self.store.preview(PID,NOW);self.assertEqual(v['owner_status'],state)
                self.assertEqual(build_manager({},self.store,NOW)['proposals'][0]['status'],state)
    def test_production_executor_contract_only(self):
        v=self.approve();auth={'expires_at':(NOW+timedelta(minutes=30)).isoformat(),'head_sha':v['head_sha'],'proposal_id':PID,
            'proposal_revision':1,'binding':approval_binding(v),'receipt_id':'external-receipt','scope':'PRODUCTION_EXECUTOR'}
        h=handoff_contract(v,NOW,authority_receipt=auth,idempotency_key=digest('handoff'))
        self.assertFalse(h['execution_authorized']);self.assertTrue(h['read_after_write_required']);self.assertEqual(h['rollback_reference'],v['base_sha'])
        for change in ({'expires_at':NOW.isoformat()},{'head_sha':'e'*40},{'proposal_revision':2},{'scope':'PREVIEW_ONLY'},{'binding':'bad'}):
            with self.subTest(change=change),self.assertRaises(ValueError):handoff_contract(v,NOW,authority_receipt={**auth,**change},idempotency_key=digest('handoff'))
    def test_manager_rendering_all_required_states(self):
        for state,build,tests,preview,stale in (('PREPARATION_ELIGIBLE','NOT_RUN','NOT_RUN','NOT_COLLECTED','CURRENT'),
            ('BUILD_FAILED','FAIL','NOT_RUN','NOT_COLLECTED','CURRENT'),('TEST_FAILED','PASS','FAIL','NOT_COLLECTED','CURRENT'),
            ('PREVIEW_PENDING','PASS','PASS','PREVIEW_PENDING','CURRENT'),('PROVIDER_BLOCKED','PASS','PASS','BLOCKED_AUTH','CURRENT'),
            ('STALE_BASE','PASS','PASS','STALE','NEEDS_REBASE')):
            with self.subTest(state=state):
                v=self.prepared_value();v.update(state=state,build_state=build,test_state=tests,preview_state=preview,stale_state=stale)
                self.store.save_preview(v);view=build_manager({},self.store,NOW);page=render_manager(view)
                self.assertEqual(view['proposals'][0]['website_preview']['build_state'],build);self.assertIn(state,page)
                self.assertIn(v['base_sha'],page);self.assertIn(v['head_sha'],page)
        v=self.ready();self.assertIn(URL,render_manager(build_manager({},self.store,NOW)))
    def test_priority_today_in_existing_model(self):
        self.ready();sync_priorities({},self.store,NOW);v=build_manager({},self.store,NOW)
        self.assertTrue(any(p['next_action']=='REVIEW PREVIEW' for p in v['today']))
        self.assertEqual(len(self.store.rows('optibrain.business_priority')),1)
        item=self.store.website_proposal(PID);self.store.feedback('PROPOSAL',PID,item['payload_hash'],'APPROVE','owner',NOW)
        self.assertFalse(build_manager({},self.store,NOW)['today'])
    def test_provider_stale_revision_priorities(self):
        cases=[('PROVIDER_BLOCKED','BLOCKED_AUTH','CURRENT','PROVIDER ACCESS REQUIRED'),('STALE_BASE','STALE','NEEDS_REBASE','STALE PREVIEW')]
        for state,preview,stale,action in cases:
            with self.subTest(state=state):
                v=self.prepared_value();v.update(state=state,preview_state=preview,stale_state=stale);self.store.save_preview(v)
                sync_priorities({},self.store,NOW);view=build_manager({},self.store,NOW)
                self.assertTrue(any(p['next_action']==action for p in view['priorities']))
                # Undated provider/stale verification retains the current
                # lifecycle-aware Today rule; it is not an urgent sales task.
                self.assertFalse(view['today'])
    def test_revision_requested_owner_priority(self):
        self.ready();item=self.store.website_proposal(PID)
        self.store.feedback('PROPOSAL',PID,item['payload_hash'],'REQUEST_REVISION','owner',NOW)
        sync_priorities({},self.store,NOW)
        self.assertTrue(any(p['next_action']=='REVISION REQUESTED' for p in build_manager({},self.store,NOW)['today']))
    def test_ready_preview_preserves_sent_commercial_truth_and_shared_today(self):
        from workflow.automation.lifecycle_projection import fact, ref
        from workflow.automation.lifecycle_truth import context_key
        self.ready()
        inputs={'business':{'snapshot':{'observed_at':NOW.isoformat(),'leads':[{'id':'lead','Created_Time':NOW.isoformat()}]}}}
        sync_priorities(inputs,self.store,NOW)
        row=deepcopy(next(i['record'] for i in self.store.rows('optibrain.business_priority') if i['record']['domain']=='MANAGER'))
        context=ref('BOOKS','ESTIMATE','Noveco-EST-1132')
        row.update(priority_id='e'*64,domain='SALES_INTELLIGENCE',targets=[context],
                   what='Finish Noveco quote',next_action='FINISH_QUOTE')
        self.store.record(row)
        sent=fact(context,'QUOTE_SENT','OWNER',None,NOW.isoformat(),NOW.isoformat(),['retained-owner-correction'],
                  truth_class='OWNER_VERIFIED_FACT',time_basis='ASSERTION_AT')
        self.store.record_business_fact(sent,NOW)
        before=self.store.business_facts()
        view=build_manager(inputs,self.store,NOW)
        commercial=next(p for p in view['priorities'] if p['priority_id']=='e'*64)
        self.assertEqual((commercial['status'],commercial['next_action'],commercial['actionability']),('SUPERSEDED','NO_ACTION','WAITING'))
        self.assertEqual(view['commercial_states'][context_key(context)]['current_state'],'SENT_RESPONSE_UNKNOWN')
        self.assertNotIn('e'*64,[p['priority_id'] for p in view['today']])
        website=next(p for p in view['today'] if p['next_action']=='REVIEW PREVIEW')
        self.assertEqual(website['targets'][0]['system'],'WEBSITE')
        self.assertNotIn('lifecycle',website)
        self.assertEqual([p['priority_id'] for p in view['today']],[p['id'] for p in view['brief']['top_priorities']])
        self.assertEqual(before,self.store.business_facts())

    def test_manager_escapes_owner_evidence(self):
        v=self.prepared_value();v['provider_reads']={'cloudflare':{'reason':'<script>alert(1)</script>'}};self.store.save_preview(v)
        page=render_manager(build_manager({},self.store,NOW));self.assertNotIn('<script>alert(1)</script>',page)


class EventImportTests(PreviewCase):
    def event(self,**overrides):
        body=json.dumps({'repository':{'full_name':REPO},'command':'touch /tmp/never'}).encode();key=b'local-test-key-32bytes-long-never-live'
        args={'signature':'sha256='+hmac.new(key,body,hashlib.sha256).hexdigest(),'event_id':'delivery-0001','kind':'push','allowed_repositories':{REPO},'now':NOW}
        args.update(overrides);return handle_webhook(self.store,HMACVerifier(key),body,**args)
    def test_valid_signed_payload_no_command_replay(self):
        self.assertEqual(self.event()['state'],'ACCEPTED')
        with self.assertRaises(ValueError):self.event()
        with self.store.connect() as db:
            row=db.execute('SELECT value FROM website_preview_webhooks').fetchone();self.assertNotIn('command',row[0])
    def test_invalid_signature_repo_event_delivery(self):
        for overrides in ({'signature':'sha256='+'0'*64},{'allowed_repositories':{'evil/repo'}},{'kind':'deployment'},{'event_id':'../bad'}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):self.event(**overrides)
    def test_all_event_types_and_size_bound(self):
        for kind in ('push','pull_request','workflow_run'):self.assertEqual(self.event(kind=kind,event_id='delivery-'+kind.replace('_','-'))['state'],'ACCEPTED')
        with self.assertRaises(ValueError):handle_webhook(self.store,HMACVerifier(b'x'*32),b'x'*65537,signature='bad',event_id='delivery-big',kind='push',allowed_repositories={REPO},now=NOW)
    def test_camera_report_preserves_sha_distinctions_and_auth_block(self):
        fixture=json.loads((FIXTURES/'camera.json').read_text());canonical(self.store,revision=2)
        p=package(self.store,fixture['base_sha'],tests=fixture['required_tests']);v=new_preview(p,configured_repo(fixture['base_sha']),NOW,'Camera CTA')
        v=import_website_report((FIXTURES/'camera-website-report.json').read_bytes(),v,expected_proposal_id=PID,expected_repository=REPO,now=NOW)
        self.store.save_preview(v);self.assertEqual(v['original_proposal_sha'],fixture['proposal_sha']);self.assertEqual(v['head_sha'],fixture['prepared_tested_sha'])
        self.assertEqual(v['preview_state'],'BLOCKED_AUTH');self.assertEqual(v['imported_evidence']['local_build_state'],'PASS');self.assertEqual(v['imported_evidence']['local_test_state'],'PASS')
        self.assertEqual(v['imported_evidence']['owner_review'],'BLOCKED');self.assertFalse(preview_ready(v,NOW));self.assertNotEqual(v['head_sha'],fixture['evidence_final_head'])
        sync_priorities({},self.store,NOW);page=render_manager(build_manager({},self.store,NOW));self.assertIn('BLOCKED_AUTH',page);self.assertIn('PROVIDER ACCESS REQUIRED',page)
    def test_real_camera_mapping_preserves_history_and_blocks_hosted_review(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('camera_import',Path(__file__).resolve().parents[3]/'ops/preview_control_plane/import_camera.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        native=deepcopy(self.store.website_proposal(PID))
        native['record'].update(revision=2,target_object={'system':'WEBSITE','entity_type':'LANDING_PAGE','entity_id':PID})
        native['detail'].pop('repository')
        self.store.record(native['record'],native['detail'])
        before=self.store.website_proposal(PID)
        result=module.import_camera(self.store,(FIXTURES/'camera-website-report.json').read_bytes(),NOW,before['payload_hash'])
        self.assertEqual(result['proposal_revision'],3)
        self.assertEqual(result['source_proposal_revision'],2)
        self.assertFalse(result['preview_ready'])
        v=self.store.preview(PID,NOW)
        self.assertEqual(v['preview_state'],'BLOCKED_AUTH')
        self.assertEqual(v['build_state'],'NOT_RUN')
        self.assertEqual(v['test_state'],'NOT_RUN')
        self.assertIsNone(v['preview_project'])
        with self.store.connect() as db:
            row=db.execute('SELECT payload_hash FROM optimization_records WHERE id=? AND revision=2',(PID,)).fetchone()
        self.assertEqual(row[0],before['payload_hash'])
        current=self.store.website_proposal(PID)
        with self.assertRaises(ValueError):self.store.feedback('PROPOSAL',PID,current['payload_hash'],'APPROVE','owner',NOW)
        self.assertEqual(module.import_camera(self.store,(FIXTURES/'camera-website-report.json').read_bytes(),NOW,before['payload_hash'])['state'],'EXACT_REPLAY')

    def test_report_rejects_spoof_oversize_revision(self):
        fixture=json.loads((FIXTURES/'camera.json').read_text());canonical(self.store,revision=2)
        p=package(self.store,fixture['base_sha']);v=new_preview(p,configured_repo(fixture['base_sha']),NOW,'Camera')
        raw=json.loads((FIXTURES/'camera-website-report.json').read_text())
        for change in ({'repository':'evil/repo'},{'production_affected':True},{'schema':99}):
            with self.subTest(change=change),self.assertRaises(ValueError):import_website_report(json.dumps({**raw,**change}).encode(),v,expected_proposal_id=PID,expected_repository=REPO,now=NOW)
        with self.assertRaises(ValueError):import_website_report(b'x'*131073,v,expected_proposal_id=PID,expected_repository=REPO,now=NOW)


class GitIntegrationTests(PreviewCase):
    def setUp(self):
        super().setUp();self.clone=self.root/'clone';self.clone.mkdir();git(self.clone,'init','-b','main')
        git(self.clone,'config','user.name','Local Test');git(self.clone,'config','user.email','test@localhost')
        git(self.clone,'remote','add','origin','file://'+str(self.root/'fixture-remote.git'))
        (self.clone/'page.html').write_text('Original camera copy\n');(self.clone/'other.txt').write_text('Original other\n')
        (self.clone/'checks.py').write_text('from pathlib import Path\nimport sys\nsys.exit(1 if "FAIL" in Path("page.html").read_text() else 0)\n')
        (self.clone/'fail.py').write_text('raise SystemExit(1)\n')
        git(self.clone,'add','.');git(self.clone,'commit','-m','Initial website fixture');self.base=git(self.clone,'rev-parse','HEAD')
        self.git=LocalGitAdapter(REPO,self.clone,self.root/'proposals',expected_remote='file://'+str(self.root/'fixture-remote.git'))
        self.package=package(self.store,self.base);self.repo=configured_repo(self.base,self.clone)
        self.runner=ApprovedBuildRunner(self.git,tuple(ApprovedScript(k,'checks.py',file_hash(self.clone/'checks.py')) for k in self.package['required_tests']))
    def prepare(self):
        r=prepare_local(self.store,self.git,self.runner,self.package,self.repo,NOW,slug='Camera CTA')
        self.assertEqual(r['state'],'PREVIEW_PENDING',r);return r['preview']
    def advance(self,file,content):
        (self.clone/file).write_text(content);git(self.clone,'add','--',file);git(self.clone,'commit','-m','Main advanced');return git(self.clone,'rev-parse','HEAD')
    def test_end_to_end_temporary_git_fake_providers_manager_approval(self):
        v=self.prepare();self.assertNotEqual(v['head_sha'],self.base);self.assertEqual(git(self.clone,'rev-parse','HEAD'),self.base)
        self.assertEqual(self.git.compare_base(PID,self.base),'CURRENT')
        g,c,h=provider_fixtures(v);self.reconcile_fixtures(g,c,h,git_adapter=self.git)
        item=self.store.website_proposal(PID);self.store.feedback('PROPOSAL',PID,item['payload_hash'],'APPROVE','owner',NOW)
        self.assertTrue(self.store.preview(PID,NOW)['approval']);self.assertEqual(build_manager({},self.store,NOW)['proposals'][0]['status'],'APPROVED')
    def test_idempotent_branch_worktree_and_preparation(self):
        v=self.prepare();b=self.git.create_proposal_branch(self.package,v['branch'],NOW);w=self.git.create_proposal_worktree(self.package,v['branch'],NOW)
        self.assertEqual(b['path'],w['path']);second=prepare_local(self.store,self.git,self.runner,self.package,self.repo,NOW,slug='Camera CTA')
        self.assertTrue(second['expensive_work_skipped']);self.assertEqual(second['preview']['head_sha'],v['head_sha'])
    def test_new_main_nonconflicting_stale(self):
        self.prepare();new=self.advance('other.txt','New main other\n')
        self.assertEqual(self.git.mark_stale(PID,new),'NEEDS_REBASE');self.assertFalse(self.git.detect_conflict(PID,new))
    def test_merge_conflict_isolated_detection(self):
        self.prepare();new=self.advance('page.html','Conflicting main camera\n')
        self.assertEqual(self.git.compare_base(PID,new),'CONFLICTED');self.assertTrue(self.git.detect_conflict(PID,new))
        self.assertEqual(git(self.clone,'status','--porcelain'),'');self.assertEqual((self.clone/'page.html').read_text(),'Conflicting main camera\n')
    def test_superseded_main_contains_proposal(self):
        v=self.prepare();git(self.clone,'merge','--ff-only',v['branch'])
        self.assertEqual(self.git.compare_base(PID,v['head_sha']),'SUPERSEDED')
    def test_existing_worktree_collision(self):
        branch=branch_name(PID,'Camera');self.git.create_proposal_branch(self.package,branch,NOW)
        target=self.git._target(PID);target.mkdir(parents=True);(target/'user.txt').write_text('Preserve')
        with self.assertRaises(ValueError):self.git.create_proposal_worktree(self.package,branch,NOW)
        self.assertEqual((target/'user.txt').read_text(),'Preserve')
    def test_duplicate_branch_not_adopted(self):
        branch=branch_name(PID,'Camera');git(self.clone,'branch',branch)
        with self.assertRaises(ValueError):self.git.create_proposal_branch(self.package,branch,NOW)
    def test_invalid_branch_targets(self):
        for branch in ('main','../main','optimization/other-camera','optimization/'+PID+'-a;id','refs/heads/main'):
            with self.subTest(branch=branch),self.assertRaises(ValueError):self.git.create_proposal_branch(self.package,branch,NOW)
    def test_missing_repo_wrong_repo_dirty_repo(self):
        with self.assertRaises(ValueError):LocalGitAdapter(REPO,self.root/'missing',self.root/'safe',expected_remote='missing')
        with self.assertRaises(ValueError):LocalGitAdapter(REPO,self.clone,self.root/'safe',expected_remote='evil-remote')
        (self.clone/'untracked').write_text('owner changes')
        with self.assertRaises(ValueError):self.git.create_proposal_branch(self.package,branch_name(PID,'Camera'),NOW)
        self.assertEqual((self.clone/'untracked').read_text(),'owner changes')
    def test_production_arbitrary_traversal_symlink_paths(self):
        for root in (self.clone,self.clone/'proposal',self.root/'proposals'/'..'/'escape'):
            with self.subTest(root=root),self.assertRaises(ValueError):LocalGitAdapter(REPO,self.clone,root,expected_remote=self.git.expected_remote)
        with self.assertRaises(ValueError):LocalGitAdapter(REPO,self.clone,self.root/'private',expected_remote=self.git.expected_remote,production_paths=[self.clone])
        link=self.root/'link';link.symlink_to(self.git.root,target_is_directory=True)
        with self.assertRaises(ValueError):LocalGitAdapter(REPO,self.clone,link,expected_remote=self.git.expected_remote)
    def test_cross_repo_worktree_and_proposal_path_spoof(self):
        self.prepare();r=self.git._read_record(PID);r['repository']='evil/repo';self.git._save_record(r)
        with self.assertRaises(ValueError):self.git.read_worktree_state(PID)
    def test_other_repo_worktree_replacement(self):
        v=self.prepare();path=Path(v['worktree_path']);git(self.clone,'worktree','remove',str(path));path.mkdir();git(path,'init','-b',v['branch'])
        git(path,'config','user.name','Wrong Repo');git(path,'config','user.email','wrong@localhost');(path/'a').write_text('wrong')
        git(path,'add','.');git(path,'commit','-m','wrong')
        with self.assertRaises(ValueError):self.git.read_worktree_state(PID)
    def test_dirty_worktree_no_overwrite(self):
        v=self.prepare();path=Path(v['worktree_path']);(path/'page.html').write_text('Owner uncommitted change')
        with self.assertRaises(ValueError):self.git.commit_prepared_change(self.package)
        self.assertEqual((path/'page.html').read_text(),'Owner uncommitted change')
        self.assertFalse(self.git.archive_eligibility(PID,'REJECTED')['eligible'])
    def test_proposal_revision_reuses_path_new_sha_checks(self):
        first=self.prepare();canonical(self.store,revision=2)
        p=package(self.store,self.base,before='Commercial security cameras',after='Revised commercial cameras')
        second=prepare_local(self.store,self.git,self.runner,p,self.repo,NOW,slug='Camera CTA')['preview']
        self.assertEqual(second['proposal_revision'],2);self.assertEqual(second['worktree_path'],first['worktree_path']);self.assertNotEqual(second['head_sha'],first['head_sha'])
        self.assertEqual(second['tests']['FR']['head_sha'],second['head_sha']);self.assertIsNone(second['approval'])
    def test_stale_base_preparation_denied(self):
        self.advance('other.txt','Updated')
        r=prepare_local(self.store,self.git,self.runner,self.package,self.repo,NOW,slug='Camera')
        self.assertEqual(r['state'],'NOT_ELIGIBLE');self.assertEqual(self.git.read_repo_state()['default_sha'],git(self.clone,'rev-parse','HEAD'))
    def test_build_failure_and_test_failure(self):
        for failure in ('BUILD','FR'):
            with self.subTest(failure=failure):
                runner=ApprovedBuildRunner(self.git,tuple(ApprovedScript(k,'fail.py' if k==failure else 'checks.py',file_hash(self.clone/('fail.py' if k==failure else 'checks.py'))) for k in self.package['required_tests']))
                result=prepare_local(self.store,self.git,runner,self.package,self.repo,NOW,slug='Camera CTA')
                self.assertEqual(result['state'],'BUILD_FAILED' if failure=='BUILD' else 'TEST_FAILED');self.assertFalse(preview_ready(result['preview'],NOW))
    def test_malicious_build_definition_command_injection(self):
        for definition in ({'command_class':'BUILD','command':'sh -c id'},['sh','-c','id'],ApprovedScript('BUILD','../evil.py','a'*64),ApprovedScript('BUILD','checks.py','wrong')):
            with self.subTest(definition=definition),self.assertRaises(ValueError):ApprovedBuildRunner(self.git,(definition,))
        self.prepare()
        with self.assertRaises(ValueError):self.runner.run(PID,'BUILD; touch /tmp/no')
    def test_pinned_script_change_and_scope_denied(self):
        v=self.prepare();path=Path(v['worktree_path']);(path/'checks.py').write_text('raise SystemExit(0)')
        git(path,'add','checks.py');git(path,'commit','-m','unapproved build change')
        with self.assertRaises(ValueError):self.runner.run(PID,'BUILD')
    def test_git_filters_and_hooks_disabled(self):
        marker=self.root/'hook-ran';hooks=self.git.common/'hooks';hooks.mkdir(exist_ok=True);hook=hooks/'pre-commit'
        hook.write_text('#!/bin/sh\ntouch '+str(marker)+'\n');hook.chmod(0o700)
        self.prepare();self.assertFalse(marker.exists())
        git(self.clone,'config','filter.evil.clean','touch /tmp/no')
        with self.assertRaises(ValueError):self.git.read_repo_state()
    def test_git_package_hash_scope_repo_spoof(self):
        for change in ({'repository':'evil/repo'},{'proposal_id':'e'*64},{'semantic_hash':'bad'}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.git.create_proposal_branch({**self.package,**change},branch_name(PID,'Camera'),NOW)
    def test_fetch_observation_incremental_no_clone(self):
        gp=FakeGitHubProvider(REPO,{'branch:main':{'repository':REPO,'branch':'main','sha':self.base}},NOW)
        r=self.git.fetch_state_from_adapter(gp);self.assertFalse(r['change_detected']);self.assertFalse(r['clone_required'])
        gp=FakeGitHubProvider(REPO,{'branch:main':{'repository':REPO,'branch':'main','sha':'a'*40}},NOW)
        self.assertTrue(self.git.fetch_state_from_adapter(gp)['change_detected'])
    def test_archive_is_eligibility_only(self):
        v=self.prepare();self.assertTrue(self.git.archive_eligibility(PID,'REJECTED')['eligible']);self.assertFalse(self.git.archive_eligibility(PID,'APPROVED')['eligible'])
        self.assertTrue(Path(v['worktree_path']).exists());self.assertFalse(self.git.archive_eligibility(PID,'REJECTED')['deleted'])
    def test_active_worktree_bound_and_another_proposal_collision(self):
        self.prepare();second={**self.package,'proposal_id':'c'*64}
        second['semantic_hash']=digest([second['proposal_id'],REPO,self.base,second['allowed_files'],second['changes'],second['required_tests']])
        self.git.max_worktrees=1;branch=branch_name(second['proposal_id'],'Another camera')
        self.git.create_proposal_branch(second,branch,NOW)
        with self.assertRaises(ValueError):self.git.create_proposal_worktree(second,branch,NOW)
        self.assertEqual(self.git.read_worktree_state(PID)['proposal_id'],PID)
    def test_camera_all_required_classes_local_proof(self):
        fixture=json.loads((FIXTURES/'camera.json').read_text())
        self.package=package(self.store,self.base,tests=fixture['required_tests'])
        self.runner=ApprovedBuildRunner(self.git,tuple(ApprovedScript(k,'checks.py',file_hash(self.clone/'checks.py')) for k in self.package['required_tests']))
        v=self.prepare();self.assertEqual(set(v['tests']),set(fixture['required_tests']))
        self.assertTrue(all(t['state']=='PASS' and t['head_sha']==v['head_sha'] for t in v['tests'].values()))
    def test_source_symlink_and_pinned_script_edits_denied(self):
        branch=branch_name(PID,'Camera CTA');self.git.create_proposal_branch(self.package,branch,NOW)
        r=self.git.create_proposal_worktree(self.package,branch,NOW);path=Path(r['path'])
        outside=self.root/'outside';outside.write_text('Original camera copy')
        (path/'page.html').unlink();(path/'page.html').symlink_to(outside)
        git(path,'add','page.html');git(path,'commit','-m','Symlink source fixture')
        with self.assertRaises(ValueError):self.git.commit_prepared_change(self.package)
        self.assertEqual(outside.read_text(),'Original camera copy')
    def test_protected_build_script_cannot_be_prepared(self):
        branch=branch_name(PID,'Camera CTA');self.git.create_proposal_branch(self.package,branch,NOW)
        self.git.create_proposal_worktree(self.package,branch,NOW)
        p=preparation_package(self.store.website_proposal(PID),REPO,self.base,['checks.py'],
            [{'path':'checks.py','before':'sys.exit','after':'print'}],['BUILD'],['evidence/camera.json'])
        with self.assertRaises(ValueError):self.git.commit_prepared_change(p,protected_scripts=self.runner.protected_scripts)
    def test_reconciliation_uses_conflict_model(self):
        v=self.prepare();new=self.advance('page.html','Conflicting main copy');g,c,h=provider_fixtures(v);g['branch:main']['sha']=new
        self.reconcile_fixtures(g,c,h,git_adapter=self.git);self.assertEqual(self.store.preview(PID,NOW)['stale_state'],'CONFLICTED')


if __name__=='__main__':unittest.main()
