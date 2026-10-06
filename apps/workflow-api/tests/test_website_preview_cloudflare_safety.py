"""No-network production-trigger containment and canonical-token tests."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from workflow.automation.website_preview_cloudflare_safety import (
    ACCOUNT, USER_TOKEN_PATH, CloudflareBuildsReadHTTP, CloudflareReadFailure,
    CloudflarePushSafety, ProductionBoundaryFailure, unsafe_triggers,
)
from workflow.automation.website_preview_github_live import REPOSITORY_ID
from test_website_preview import NOW, PID, REPO
import test_website_preview_execution as execution_tests


WORKER={'id':'opticable-website','tag':'e3fc5eaa3a46499893264f7805709d8e'}
TRIGGER={'trigger_uuid':'0a7fcf36-1a8a-4adf-8c04-03a7b517938d',
    'trigger_name':'Deploy non-production branches','external_script_id':WORKER['tag'],
    'branch_includes':['*'],'branch_excludes':['main'],'deploy_command':'npx wrangler versions upload',
    'repo_connection':{'provider_type':'github','repo_id':str(REPOSITORY_ID),
        'provider_account_name':'yboucher97','repo_name':'opticable-website','deleted_on':None}}


class Transport:
    def __init__(self):
        self.calls=[];self.workers=[deepcopy(WORKER)]
        self.triggers={WORKER['tag']:[deepcopy(TRIGGER)]}
        self.account={'id':ACCOUNT};self.active=True

    def read(self,path):
        self.calls.append(path)
        if path=='/user/tokens/verify':value={'status':'active' if self.active else 'expired'}
        elif path=='/accounts/'+ACCOUNT:value=self.account
        elif path.endswith('/workers/scripts'):value=self.workers
        elif '/builds/workers/' in path:value=self.triggers[path.split('/')[-2]]
        else:raise AssertionError('Unexpected endpoint')
        return deepcopy(value),NOW.isoformat()


class PushSafetyTests(unittest.TestCase):
    def setUp(self):
        execution_tests.ExecutionTests.setUp(self)
        self.transport=Transport()
        self.guard=CloudflarePushSafety(self.binding['branch'],transport=self.transport,clock=lambda:NOW)

    def test_actual_non_main_version_upload_is_unsafe_even_without_live_deploy(self):
        with self.assertRaises(ProductionBoundaryFailure) as raised:self.guard.require_safe(self.binding)
        self.assertEqual(raised.exception.blockers[0]['trigger_uuid'],TRIGGER['trigger_uuid'])
        self.assertFalse(self.guard.last_receipt['safe']);self.assertEqual(self.guard.last_receipt['provider_mutations'],0)
        self.assertIn('versions upload',raised.exception.blockers[0]['deploy_command'])

    def test_minimum_exclusion_blocks_proposals_without_affecting_main_or_other_refs(self):
        trigger=self.transport.triggers[WORKER['tag']][0]
        trigger['branch_excludes']=['main','optimization/*']
        self.assertTrue(self.guard.require_safe(self.binding)['safe'])
        self.assertEqual(TRIGGER['branch_excludes'],['main'])
        # Production-only trigger does not match an optimization ref.
        production={**deepcopy(TRIGGER),'branch_includes':['main'],'branch_excludes':[]}
        self.assertEqual(unsafe_triggers(WORKER,[production],self.binding['branch']),[])

    def test_unexpected_worker_or_second_automatic_preview_also_blocks_exact_one_upload(self):
        for name in ['opticable-website','opticable-optimization-preview','unrelated-worker']:
            with self.subTest(name=name):
                worker={**WORKER,'id':name}
                self.assertEqual(len(unsafe_triggers(worker,[TRIGGER],self.binding['branch'])),1)

    def test_wrong_repository_ref_revision_hash_sha_fail_before_provider_reads(self):
        for change in [{'repository':'evil/repo'},{'proposal_id':'f'*64},{'branch':'main'},
                {'branch':'master'},{'branch':self.binding['branch']+'-other'},
                {'proposal_revision':True},{'head_sha':'bad'},{'base_sha':'bad'},{'proposal_hash':'bad'}]:
            with self.subTest(change=change),self.assertRaises(ValueError):self.guard.require_safe({**self.binding,**change})
        self.assertFalse(self.transport.calls)

    def test_inactive_token_wrong_account_incomplete_duplicate_or_wrong_tag_fail(self):
        cases=['inactive','account','workers','duplicate','tag','repository','unknown-pattern','missing-filter']
        for kind in cases:
            transport=Transport();guard=CloudflarePushSafety(self.binding['branch'],transport=transport,clock=lambda:NOW)
            trigger=transport.triggers[WORKER['tag']][0]
            if kind=='inactive':transport.active=False
            elif kind=='account':transport.account={'id':'f'*32}
            elif kind=='workers':transport.workers=[]
            elif kind=='duplicate':transport.workers*=2;trigger['branch_excludes'].append('optimization/*')
            elif kind=='tag':trigger['external_script_id']='f'*32
            elif kind=='repository':trigger['repo_connection']['repo_name']='other'
            elif kind=='unknown-pattern':trigger['branch_includes']=['opt[imization]/*']
            elif kind=='missing-filter':trigger.pop('branch_excludes')
            with self.subTest(kind=kind),self.assertRaises((ValueError,PermissionError)):guard.require_safe(self.binding)

    def test_foreign_repository_trigger_can_be_ignored_only_with_consistent_identity(self):
        trigger=deepcopy(TRIGGER);trigger['repo_connection']['repo_id']='1'
        self.assertEqual(unsafe_triggers(WORKER,[trigger],self.binding['branch']),[])
        trigger['repo_connection']['repo_id']=str(REPOSITORY_ID);trigger['repo_connection']['provider_account_name']='evil'
        with self.assertRaises(ValueError):unsafe_triggers(WORKER,[trigger],self.binding['branch'])

    def test_complete_inventory_required_and_safe_cache_expires_in_30_seconds(self):
        second={'id':'other','tag':'f'*32};self.transport.workers.append(second);self.transport.triggers[second['tag']]=[]
        self.transport.triggers[WORKER['tag']][0]['branch_excludes'].append('optimization/*')
        receipt=self.guard.require_safe(self.binding)
        self.assertEqual(receipt['workers_checked'],['opticable-website','other']);self.assertTrue(receipt['inventory_complete'])
        calls=len(self.transport.calls);self.guard.require_safe(self.binding);self.assertEqual(len(self.transport.calls),calls)
        self.guard.clock=lambda:NOW+timedelta(seconds=31)
        self.transport.triggers[WORKER['tag']][0]['branch_excludes']=['main']
        with self.assertRaises(ProductionBoundaryFailure):self.guard.require_safe(self.binding)
        self.assertGreater(len(self.transport.calls),calls)


class CloudflareTransportTests(unittest.TestCase):
    def response(self,data,status=200):
        class Response:
            code=status;headers={'Date':'Tue, 06 Oct 2026 06:00:00 GMT'}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return json.dumps(data).encode()
        return Response()

    def test_canonical_existing_user_token_only_and_no_mutation_surface(self):
        for path in [Path('/etc/optibrain/cloudflare-test-token'),Path('/etc/optibrain/website-preview/cloudflare-trigger-read.token')]:
            with self.subTest(path=path),self.assertRaises(ValueError):CloudflareBuildsReadHTTP(token_path=path)
        transport=CloudflareBuildsReadHTTP()
        for endpoint in ['/accounts/'+'f'*32,'/user/tokens','/accounts/'+ACCOUNT+'/builds/triggers/x',
                '/accounts/'+ACCOUNT+'/workers/scripts/opticable-website/versions','https://evil.test/']:
            with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):transport.read(endpoint)
        for method in ['write','request','create_token','update_trigger','upload_worker','deploy']:self.assertFalse(hasattr(transport,method))
        self.assertFalse(transport.calls)

    def test_safe_observations_have_status_success_codes_and_no_token(self):
        transport=CloudflareBuildsReadHTTP();data={'success':True,'errors':[],'result':{'status':'active'}}
        with patch('workflow.automation.website_preview_cloudflare_safety._trusted_bytes',return_value=b'FAKE_USER_TOKEN_MEMORY_ONLY_123456'),\
                patch.object(transport.opener,'open',return_value=self.response(data)):
            result,source=transport.read('/user/tokens/verify')
        self.assertEqual(result,{'status':'active'});self.assertEqual(transport.calls[0]['http'],200)
        self.assertTrue(transport.calls[0]['success']);self.assertEqual(transport.calls[0]['error_codes'],[])
        self.assertNotIn('FAKE_USER_TOKEN',json.dumps(transport.calls))

    def test_auth_denial_never_means_empty_and_is_not_retried(self):
        data={'success':False,'errors':[{'code':12006,'message':'Raw provider prose omitted'}],'result':None}
        transport=CloudflareBuildsReadHTTP()
        with patch('workflow.automation.website_preview_cloudflare_safety._trusted_bytes',return_value=b'FAKE_USER_TOKEN_MEMORY_ONLY_123456'),\
                patch.object(transport.opener,'open',return_value=self.response(data,401)) as network:
            with self.assertRaises(CloudflareReadFailure) as failure:transport.read('/user/tokens/verify')
            self.assertEqual(failure.exception.codes,[12006])
            with self.assertRaises(PermissionError):transport.read('/user/tokens/verify')
            self.assertEqual(network.call_count,1)

    def test_inventory_pagination_and_request_budget_fail_closed(self):
        transport=CloudflareBuildsReadHTTP(maximum=1)
        data={'success':True,'result':[],'errors':[],'result_info':{'total_count':2,'total_pages':2}}
        with patch('workflow.automation.website_preview_cloudflare_safety._trusted_bytes',return_value=b'FAKE_USER_TOKEN_MEMORY_ONLY_123456'),\
                patch.object(transport.opener,'open',return_value=self.response(data)):
            with self.assertRaises(ValueError):transport.read('/accounts/'+ACCOUNT+'/workers/scripts')
        with self.assertRaises(ValueError):transport.read('/user/tokens/verify')
