"""Offline authenticated-response and write-boundary tests for the live port."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from workflow.automation.website_preview_github_live import (
    APP_ID, INSTALLATION_ID, REPOSITORY_ID,
    READ_PERMISSIONS, PERMISSIONS, ExistingPreviewApp, GitHubPreviewAdapter,
    BoundedGitHubHTTP, ProviderFailure, BudgetExhausted, NoRedirect,
)
from workflow.automation.website_preview_runtime import reconcile
from workflow.automation.website_preview_providers import FakeGitHubProvider, FakeCloudflareProvider, FakeHTTP
from test_website_preview import NOW, PID, REPO, provider_fixtures
import test_website_preview_execution as execution_tests


class Transport:
    def __init__(self):
        self.calls = []; self.responses = {}; self.tokens = []
        repo = {'id':REPOSITORY_ID,'full_name':REPO,'private':True,'default_branch':'main'}
        self.responses = {
            ('GET','/app'):{'id':APP_ID,'name':'OptiBrain Production'},
            ('GET','/app/installations/'+str(INSTALLATION_ID)):{'id':INSTALLATION_ID,'app_id':APP_ID,
                'account':{'login':'yboucher97'},'repository_selection':'all','suspended_at':None},
            ('GET','/installation/repositories?per_page=2'):{'total_count':1,'repositories':[repo]},
            ('GET','/repos/'+REPO):repo,
            ('GET','/repos/'+REPO+'/git/ref/heads/main'):{'ref':'refs/heads/main','object':{'sha':'a'*40,'type':'commit'}},
        }
        self.overrides = {}

    def request(self, method, path, credential, body=None):
        self.calls.append((method,path,deepcopy(body)))
        if path.endswith('/access_tokens'):
            self.tokens.append(dict(body['permissions']))
            data={'token':'ghs_FAKE_MEMORY_ONLY_123456789','expires_at':(NOW+timedelta(hours=1)).isoformat(),
                'permissions':deepcopy(body['permissions'])}
            data.update(self.overrides)
            return 201,data,NOW.isoformat()
        result=self.responses.get((method,path),ProviderFailure(404))
        if isinstance(result,Exception):raise result
        return 200,deepcopy(result),NOW.isoformat()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.transport=Transport()
        self.adapter=GitHubPreviewAdapter(ExistingPreviewApp(),transport=self.transport,clock=lambda:NOW)
        self.jwt_patch=patch.object(self.adapter,'_jwt',return_value='fake-app-jwt')
        self.jwt_patch.start();self.addCleanup(self.jwt_patch.stop)

    def test_existing_broad_app_mints_only_selected_repository_and_read_permissions(self):
        proof=self.adapter.verify_identity()
        self.assertEqual(proof['app_id'],APP_ID);self.assertEqual(proof['installation_id'],INSTALLATION_ID)
        self.assertEqual(proof['installation_repository_selection'],'all')
        self.assertEqual(proof['effective_repositories'],[REPO]);self.assertEqual(proof['effective_permissions'],READ_PERMISSIONS)
        body=next(c[2] for c in self.transport.calls if c[1].endswith('/access_tokens'))
        self.assertEqual(body,{'repository_ids':[REPOSITORY_ID],'permissions':READ_PERMISSIONS})
        self.assertNotIn('ghs_FAKE',json.dumps(proof));self.assertFalse(proof['installation_tokens_persisted'])
        self.adapter.close();self.assertFalse(self.adapter._tokens)

    def test_write_capability_verification_still_downscopes_token_and_creates_no_branch(self):
        proof=self.adapter.verify_identity(for_write=True)
        self.assertEqual(proof['effective_permissions'],PERMISSIONS)
        self.assertEqual(len([c for c in self.transport.calls if c[0]=='POST']),1)
        self.assertEqual(self.transport.tokens,[PERMISSIONS])

    def test_cache_is_memory_only_and_tokens_refresh_before_expiry(self):
        self.adapter.verify_identity();self.adapter.get_repository(REPO);self.assertEqual(len(self.transport.tokens),1)
        self.adapter.clock=lambda:NOW+timedelta(minutes=59,seconds=30)
        self.transport.overrides['expires_at']=(NOW+timedelta(hours=2)).isoformat()
        self.adapter.verify_identity();self.assertEqual(len(self.transport.tokens),2)

    def test_wrong_repository_and_malicious_refs_fail_before_authentication(self):
        for branch in ['master','refs/heads/main','optimization/evil','optimization/'+PID+'-x;whoami','optimization/'+PID+'-../x']:
            with self.subTest(branch=branch),self.assertRaises(ValueError):self.adapter.get_branch(REPO,branch)
        with self.assertRaises(ValueError):self.adapter.get_repository('yboucher97/opticable-api-platform')
        for method in [self.adapter.push_proposal_branch,self.adapter.open_draft_pr]:
            with self.assertRaises(ValueError):
                if method==self.adapter.push_proposal_branch:method(REPO,'main','b'*40,PID)
                else:method(REPO,'main',PID)
        self.assertFalse(self.transport.calls)

    def test_missing_branch_requires_authenticated_repository_proof(self):
        branch='optimization/'+PID+'-camera'
        result=self.adapter.get_branch(REPO,branch)
        self.assertEqual(result.state,'VERIFIED_EMPTY');result.validate()
        self.transport.responses[('GET','/repos/'+REPO)]=ProviderFailure(404)
        self.assertEqual(self.adapter.get_branch(REPO,branch).state,'FAILED')

    def test_repo_private_scope_permission_lifetime_and_installation_mismatches_fail(self):
        cases=[('scope',{'total_count':2,'repositories':[]}),('permissions',{'permissions':{**READ_PERMISSIONS,'administration':'read'}}),
            ('expiry',{'expires_at':(NOW+timedelta(days=1)).isoformat()}),('installation',{'id':INSTALLATION_ID,'app_id':APP_ID,'account':{'login':'evil'}})]
        for kind,override in cases:
            with self.subTest(kind=kind):
                transport=Transport();adapter=GitHubPreviewAdapter(ExistingPreviewApp(),transport=transport,clock=lambda:NOW)
                if kind=='scope':transport.responses[('GET','/installation/repositories?per_page=2')]=override
                elif kind=='installation':transport.responses[('GET','/app/installations/'+str(INSTALLATION_ID))]=override
                else:transport.overrides=override
                with patch.object(adapter,'_jwt',return_value='fake'),self.assertRaises(PermissionError):adapter.verify_identity()
                self.assertFalse(adapter._tokens)

    def test_401_403_stop_without_retry_and_never_become_empty(self):
        for status in [401,403]:
            with self.subTest(status=status):
                transport=Transport();transport.responses[('GET','/app')]=ProviderFailure(status)
                adapter=GitHubPreviewAdapter(ExistingPreviewApp(),transport=transport,clock=lambda:NOW)
                with patch.object(adapter,'_jwt',return_value='fake'):
                    self.assertEqual(adapter.get_repository(REPO).state,'BLOCKED_AUTH')
                    count=len(transport.calls);self.assertEqual(adapter.get_repository(REPO).state,'BLOCKED_AUTH')
                    self.assertEqual(len(transport.calls),count)

    def test_no_merge_deletion_force_or_dispatch_surface(self):
        for name in ['merge','delete_branch','force_push','dispatch_workflow','deploy_production']:
            self.assertFalse(hasattr(self.adapter,name))
        self.assertFalse(self.transport.calls)

    def test_transport_independently_rejects_dangerous_endpoints_and_broad_auth(self):
        transport=BoundedGitHubHTTP();base='/repos/'+REPO
        paths=[('DELETE',base+'/git/refs/heads/main'),('PATCH',base+'/git/refs/heads/main'),
            ('PUT',base+'/pulls/1/merge'),('POST',base+'/actions/workflows/deploy.yml/dispatches'),
            ('GET','/repos/yboucher97/opticable-api-platform'),('GET',base+'?x=\nAuthorization:')]
        for method,path in paths:
            with self.subTest(path=path),self.assertRaises(ValueError):transport.request(method,path,'fake')
        for body in [{},{'repository_ids':[REPOSITORY_ID],'permissions':{**PERMISSIONS,'secrets':'write'}},
            {'repository_ids':[REPOSITORY_ID,123],'permissions':PERMISSIONS}]:
            with self.subTest(body=body),self.assertRaises(ValueError):
                transport.request('POST','/app/installations/'+str(INSTALLATION_ID)+'/access_tokens','fake',body)
        self.assertFalse(transport.calls)

    def test_transport_bounds_response_redirect_and_request_budget(self):
        transport=BoundedGitHubHTTP(max_requests=1);transport.calls=[('GET','/app')]
        with self.assertRaises(BudgetExhausted):transport.request('GET','/app','fake')
        with self.assertRaises(ValueError):NoRedirect().redirect_request(None,None,302,'',{},'https://evil.test/')
        class Response:
            headers={'Date':'Tue, 06 Oct 2026 06:00:00 GMT'};status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return b'x'*n
        transport=BoundedGitHubHTTP()
        with patch.object(transport.opener,'open',return_value=Response()),self.assertRaises(ValueError):
            transport.request('GET','/app','fake')

    def test_wrong_app_key_path_or_ids_rejected_without_network(self):
        for app in [ExistingPreviewApp(app_id=1),ExistingPreviewApp(installation_id=1),
                ExistingPreviewApp(private_key_path=Path('/tmp/other.pem'))]:
            with self.subTest(app=app),self.assertRaises(ValueError):GitHubPreviewAdapter(app,transport=self.transport)
        self.assertFalse(self.transport.calls)

    def test_native_ci_bound_to_exact_head_job_and_branch_without_fake_test_classes(self):
        branch='optimization/'+PID+'-camera';head='b'*40
        path='/repos/'+REPO+'/actions/runs?head_sha='+head+'&event=pull_request&per_page=10'
        run={'id':1,'head_sha':head,'head_branch':branch,'event':'pull_request','path':'.github/workflows/measurement-validation.yml',
            'status':'completed','conclusion':'success','html_url':'https://github.com/example/run/1','repository':{'full_name':REPO}}
        self.transport.responses[('GET',path)]={'total_count':1,'workflow_runs':[run]}
        jobs='/repos/'+REPO+'/actions/runs/1/jobs?per_page=20&filter=latest'
        self.transport.responses[('GET',jobs)]={'total_count':1,'jobs':[{'name':'validate','head_sha':head,'status':'completed','conclusion':'success'}]}
        result=self.adapter.get_workflow_status(REPO,head)
        self.assertEqual(result.data['checks'],{'validate':'PASS'});self.assertEqual(result.data['head_sha'],head)
        self.transport.responses[('GET',jobs)]['jobs'][0]['head_sha']='c'*40
        self.assertEqual(self.adapter.get_workflow_status(REPO,head).data['checks'],{'validate':'FAIL'})
        self.transport.responses[('GET',path)]['total_count']=11
        self.assertEqual(self.adapter.get_workflow_status(REPO,head).state,'FAILED')


class LiveReconciliationTests(unittest.TestCase):
    setUp = execution_tests.ExecutionTests.setUp

    def test_live_reconciliation_requires_a_real_draft_and_actual_native_ci(self):
        value=deepcopy(self.value)
        # Use retained provider fixtures to isolate the live reconciliation gate.
        g,c,h=provider_fixtures(value)
        g['pr:'+value['branch']]={'repository':REPO,'branch':value['branch'],'head_sha':value['head_sha'],
            'base_ref':'main','number':1,'draft':True,'state':'open','auto_merge':None}
        github=FakeGitHubProvider(REPO,g,NOW);github.requires_draft_pr=True;github.required_ci_checks=('validate',)
        github.fixtures['pr:'+value['branch']].update(state='open',auto_merge=None)
        github.fixtures['workflow:'+value['head_sha']]['checks']={'validate':'PASS'}
        cloudflare=FakeCloudflareProvider(value['preview_project'],c,NOW,allowed_hosts=['camera-isolated.example.test'])
        result=reconcile(self.store,github,cloudflare,FakeHTTP(h),NOW)
        self.assertEqual(result['proposals'][0]['preview_state'],'PREVIEW_READY')
        for prior in [[],{**g['pr:'+value['branch']],'state':'closed'},{**g['pr:'+value['branch']],'auto_merge':{}}]:
            self.store.save_preview(self.value)
            github=FakeGitHubProvider(REPO,{**g,'pr:'+value['branch']:prior},NOW);github.requires_draft_pr=True;github.required_ci_checks=('validate',)
            result=reconcile(self.store,github,cloudflare,FakeHTTP(h),NOW)
            self.assertNotEqual(result['proposals'][0]['preview_state'],'PREVIEW_READY')


class LiveWriteTests(unittest.TestCase):
    def setUp(self):
        execution_tests.ExecutionTests.setUp(self)
        self.transport=Transport()
        self.local=Mock(repository=REPO)
        self.local.read_worktree_state.return_value={**self.binding,'path':self.tmp.name,'dirty':False}
        self.source_before=self.value['package']['changes'][0]['before']
        self.source_after=self.value['package']['changes'][0]['after']
        def git(path,*args):
            if args[:2]==('diff','--name-only'):return 'page.html\n'
            if args==('show',self.binding['base_sha']+':page.html'):return self.source_before
            if args==('show',self.binding['head_sha']+':page.html'):return self.source_after
            raise AssertionError('Unexpected local Git operation')
        self.local._git.side_effect=git
        self.adapter=GitHubPreviewAdapter(ExistingPreviewApp(),transport=self.transport,clock=lambda:NOW,
            store=self.store,local_git=self.local,boundary=self.boundary,deployment_safety=Mock())
        for method in [patch.object(self.adapter,'_jwt',return_value='fake-app-jwt'),
                patch('workflow.automation.website_preview_github_live.os.geteuid',return_value=0)]:
            method.start();self.addCleanup(method.stop)
        self.ref='/repos/'+REPO+'/git/ref/heads/'+self.binding['branch']

    def remote(self,head='b'*40):
        self.transport.responses[('GET',self.ref)]={'ref':'refs/heads/'+self.binding['branch'],
            'object':{'sha':head,'type':'commit'}}

    def push(self):
        return self.adapter.push_proposal_branch(REPO,self.binding['branch'],self.binding['head_sha'],PID)

    def test_only_exact_source_and_sha_use_non_force_refspec_and_ephemeral_credentials(self):
        def upload(argv,**kwargs):
            self.assertEqual(argv[-1],self.binding['head_sha']+':refs/heads/'+self.binding['branch'])
            self.assertEqual(argv[-2],'https://github.com/'+REPO+'.git')
            self.assertFalse(any('force' in a or 'ghs_FAKE' in a for a in argv))
            self.assertFalse(kwargs['shell'])
            self.assertIn('GIT_CONFIG_VALUE_0',kwargs['env'])
            self.assertNotIn('CLOUDFLARE_API_TOKEN',kwargs['env'])
            self.remote();return SimpleNamespace(returncode=0)
        with patch('workflow.automation.website_preview_github_live.subprocess.run',side_effect=upload) as run:
            receipt=self.push();self.assertEqual(receipt['remote_sha'],self.binding['head_sha'])
            self.assertEqual(receipt['provider_writes'],1)
            self.assertEqual(self.push()['provider_writes'],0);self.assertEqual(run.call_count,1)
        self.assertIn(PERMISSIONS,self.transport.tokens)
        self.assertNotIn('ghs_FAKE',json.dumps(receipt))

    def test_local_dirty_wrong_sha_unrelated_or_wrong_source_fails_before_remote_calls(self):
        original=deepcopy(self.local.read_worktree_state.return_value)
        for bad in [{'dirty':True},{'head_sha':'c'*40},{'proposal_revision':2},{'branch':'main'}]:
            self.local.read_worktree_state.return_value={**original,**bad}
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.push()
        self.local.read_worktree_state.return_value=original
        for output in ['wrangler.jsonc\n','Unreviewed source']:
            self.local._git.side_effect=None;self.local._git.return_value=output
            with self.subTest(output=output),self.assertRaises(ValueError):self.push()
        self.assertFalse(self.transport.calls)

    def test_unallowlisted_ref_wrong_sha_id_and_unconfigured_writes_fail_before_auth(self):
        for branch,head,pid in [('main','b'*40,PID),('master','b'*40,PID),
                (self.binding['branch']+'-other','b'*40,PID),(self.binding['branch'],'c'*40,PID),
                (self.binding['branch'],'b'*40,'f'*64)]:
            with self.subTest(branch=branch,head=head,pid=pid),self.assertRaises((ValueError,PermissionError)):
                self.adapter.push_proposal_branch(REPO,branch,head,pid)
        self.adapter.boundary=None
        with self.assertRaises(PermissionError):self.push()
        self.assertFalse(self.transport.calls)

    def test_existing_mismatch_and_failed_readback_never_get_overwritten_or_retried(self):
        self.remote('c'*40)
        with patch('workflow.automation.website_preview_github_live.subprocess.run') as run:
            with self.assertRaises(ValueError):self.push()
            run.assert_not_called()
        self.transport.responses.pop(('GET',self.ref))
        with patch('workflow.automation.website_preview_github_live.subprocess.run',return_value=SimpleNamespace(returncode=0)) as run:
            with self.assertRaises(ValueError):self.push()
            self.assertEqual(run.call_count,1)

    def test_missing_or_unsafe_cloudflare_trigger_proof_stops_before_github_auth(self):
        safety=self.adapter.deployment_safety
        self.adapter.deployment_safety=None
        with self.assertRaises(PermissionError):self.push()
        self.adapter.deployment_safety=safety
        safety.require_safe.side_effect=PermissionError('Production Worker upload trigger matches')
        with self.assertRaises(PermissionError):self.push()
        self.assertFalse(self.transport.calls)

    def test_draft_creation_fixed_base_exact_head_readback_and_no_auto_merge(self):
        self.remote()
        query='/repos/'+REPO+'/pulls?state=all&head=yboucher97%3A'+self.binding['branch'].replace('/','%2F')+'&per_page=2'
        self.transport.responses[('GET',query)]=[]
        original=self.transport.request
        def request(method,path,credential,body=None):
            if method=='POST' and path=='/repos/'+REPO+'/pulls':
                self.assertTrue(body['draft']);self.assertEqual(body['base'],'main')
                self.assertEqual(body['head'],self.binding['branch'])
                self.assertIn(self.binding['head_sha'],body['body'])
                pr={'number':1,'draft':True,'state':'open','auto_merge':None,'html_url':'https://github.com/'+REPO+'/pull/1',
                    'head':{'repo':{'full_name':REPO},'ref':self.binding['branch'],'sha':self.binding['head_sha']},
                    'base':{'repo':{'full_name':REPO},'ref':'main'}}
                self.transport.responses[('POST',path)]=pr
                self.transport.responses[('GET',query)]=[pr]
            return original(method,path,credential,body)
        self.transport.request=request
        receipt=self.adapter.open_draft_pr(REPO,self.binding['branch'],PID)
        self.assertEqual(receipt['number'],1)
        with self.assertRaises(ValueError):self.adapter.open_draft_pr(REPO,self.binding['branch'],PID)
        self.assertEqual(len([c for c in self.transport.calls if c[:2]==('POST','/repos/'+REPO+'/pulls')]),1)
