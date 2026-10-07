"""Offline isolated-upload containment; never real credentials or network."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation.website_preview_cloudflare_live import (
    PreviewCloudflareHTTP, CloudflarePreviewAdapter, CloudflareFailure,
    artifact_files, multipart, PREFIX, SCRIPT, WORKER, ZONE, PREVIEW_WORKER, PREVIEW_SCRIPT,
)
from workflow.automation.website_preview_native import preview_markup, Page
from workflow.automation.website_preview_providers import PageEvidence
from workflow.automation.website_preview_execution import BINDING_FIELDS
from workflow.automation.website_preview_github_live import PROPOSAL_ID, REPOSITORY
import test_website_preview_execution as execution_tests

NOW=datetime.now(timezone.utc)
VERSION='12345678-1234-1234-1234-123456789012'

class Transport:
    def __init__(self):
        self.calls=[]
        self.values={WORKER:{'id':'a'*32,'name':PREVIEW_WORKER,'references':{'routes':[],'domains':[]}},
            '/zones/'+ZONE+'/workers/routes':[],PREFIX+'/workers/domains':[],
            SCRIPT+'/versions':{'items':[]},SCRIPT+'/settings':{'bindings':[{'type':'assets','name':'ASSETS'}]},SCRIPT+'/subdomain':{'enabled':True,'previews_enabled':True},
            PREFIX+'/workers/subdomain':{'subdomain':'yboucher'}}
    def request(self,method,path,**args):
        self.calls.append((method,path,args));value=self.values[path]
        if isinstance(value,Exception):raise value
        return deepcopy(value),NOW.isoformat()

class CloudflareTests(unittest.TestCase):
    def setUp(self):
        self.transport=Transport();self.adapter=CloudflarePreviewAdapter(transport=self.transport,clock=lambda:NOW)

    def test_transport_rejects_production_routes_dns_secrets_builds_and_other_account_before_credentials(self):
        http=PreviewCloudflareHTTP()
        for method,path in [('PUT',PREFIX+'/workers/scripts/opticable-website'),('PATCH',PREFIX+'/builds/triggers/legacy'),
                ('DELETE',SCRIPT),('POST',SCRIPT+'/secrets'),('POST','/zones/'+ZONE+'/workers/routes'),
                ('POST',PREFIX+'/workers/domains'),('PUT','/accounts/'+'b'*32+'/workers/scripts/'+PREVIEW_WORKER)]:
            with self.subTest(path=path),self.assertRaises(ValueError):http.request(method,path,raw=b'disallowed')
        self.assertFalse(http.calls)

    def test_only_exact_empty_target_create_and_subdomain_payloads_allowed(self):
        http=PreviewCloudflareHTTP()
        for path,body in [(PREFIX+'/workers/workers',{'name':'opticable-website'}),
                (PREFIX+'/workers/workers',{'name':PREVIEW_WORKER,'routes':['opticable.ca/*']}),
                (SCRIPT+'/subdomain',{'enabled':True,'previews_enabled':False})]:
            with self.assertRaises(ValueError):http.request('POST',path,body=body)
        self.assertFalse(http.calls)

    def test_complete_empty_target_proof_and_wrong_project_rejected(self):
        value=self.adapter.get_preview_configuration(PREVIEW_WORKER)
        self.assertEqual(value.state,'COMPLETE');self.assertTrue(value.data['isolated'])
        self.assertFalse(value.data['production_routes']);self.assertEqual(value.data['version_count'],0)
        count=len(self.transport.calls)
        with self.assertRaises(ValueError):self.adapter.get_project('opticable-website')
        self.assertEqual(len(self.transport.calls),count)

    def test_routes_domains_bindings_secrets_and_multiple_versions_fail_closed(self):
        for path,value in [('/zones/'+ZONE+'/workers/routes',[{'script':PREVIEW_WORKER}]),
                (PREFIX+'/workers/domains',[{'service':PREVIEW_WORKER,'hostname':'opticable.ca'}]),
                (SCRIPT+'/versions',{'items':[{'id':VERSION},{'id':'abcdefab-1234-1234-1234-123456789012'}]})]:
            with self.subTest(path=path):
                t=Transport();t.values[path]=value
                self.assertEqual(CloudflarePreviewAdapter(transport=t).get_preview_configuration(PREVIEW_WORKER).state,'FAILED')
        for binding in [{'type':'secret_text','name':'SECRET'},{'type':'kv_namespace','name':'KV'},
                {'type':'d1','name':'DB'},{'type':'service','name':'PRODUCTION'},{'type':'assets','name':'OTHER'}]:
            with self.subTest(binding=binding):
                t=Transport();t.values[SCRIPT+'/versions']={'items':[{'id':VERSION}]}
                t.values[SCRIPT+'/versions/'+VERSION]={'resources':{'bindings':[binding]}}
                self.assertEqual(CloudflarePreviewAdapter(transport=t).get_preview_configuration(PREVIEW_WORKER).state,'FAILED')

    def test_auth_error_never_claimed_as_empty(self):
        self.transport.values[WORKER]=CloudflareFailure(403,[10000])
        read=self.adapter.get_project(PREVIEW_WORKER)
        self.assertEqual(read.state,'BLOCKED_AUTH');self.assertIsNone(read.data)

    def test_exact_version_tuple_sha_annotation_and_immutable_url(self):
        binding={'proposal_id':PROPOSAL_ID,'repository':REPOSITORY,'proposal_revision':3,'proposal_hash':'d'*64,'branch':'optimization/'+PROPOSAL_ID+'-camera','base_sha':'a'*40,'head_sha':'b'*40}
        self.transport.values[SCRIPT+'/versions']={'items':[{'id':VERSION}]}
        self.transport.values[SCRIPT+'/versions/'+VERSION]={'id':VERSION,'metadata':{'created_on':NOW.isoformat()},
            'annotations':{'workers/tag':binding['head_sha'],'workers/message':json.dumps(binding)},'resources':{'bindings':[{'type':'assets','name':'ASSETS'}]}}
        read=self.adapter.find_deployment_for_sha(PREVIEW_WORKER,binding['head_sha'])
        self.assertEqual(read.state,'COMPLETE');self.assertEqual(read.data['head_sha'],binding['head_sha'])
        self.adapter.validate_preview_url(read.data['url'])
        self.transport.values[SCRIPT+'/versions/'+VERSION]['annotations']['workers/tag']='c'*40
        self.assertEqual(self.adapter.read_deployment(PREVIEW_WORKER,VERSION).state,'FAILED')

    def test_hostname_redirect_query_and_production_variants_rejected(self):
        for url in ['https://opticable.ca/','http://12345678-'+PREVIEW_WORKER+'.yboucher.workers.dev/',
                'https://12345678-'+PREVIEW_WORKER+'.yboucher.workers.dev.evil.test/',
                'https://12345678-'+PREVIEW_WORKER+'.yboucher.workers.dev/?redirect=production']:
            with self.assertRaises(ValueError):self.adapter.validate_preview_url(url)

    def test_artifact_digest_detects_changes_hidden_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'index.html').write_text('first');before=artifact_files(root)[1]
            (root/'index.html').write_text('second');self.assertNotEqual(before,artifact_files(root)[1])
            (root/'_redirects').write_text('production')
            with self.assertRaises(ValueError):artifact_files(root)
            (root/'_redirects').unlink();(root/'secret').symlink_to(root/'index.html')
            with self.assertRaises(ValueError):artifact_files(root)

    def test_wrapper_has_no_production_provider_and_disables_mutation_and_indexing(self):
        self.assertIn('status:405',PREVIEW_SCRIPT);self.assertIn('noindex',PREVIEW_SCRIPT)
        self.assertIn("form-action 'none'",PREVIEW_SCRIPT)
        for text in ['opticable.ca','KV','D1','R2','SERVICE','SECRET']:self.assertNotIn(text,PREVIEW_SCRIPT)

    def test_preview_keeps_actual_contact_reference_and_disables_embedded_provider_loading(self):
        markup=preview_markup('<body><a href="/fr/contact/?origin_service=security-camera-systems">Demander une soumission</a><iframe src="https://forms.zohopublic.com/example"></iframe></body>')
        page=PageEvidence();page.feed(markup);self.assertTrue(page.form);self.assertTrue(page.cta)
        self.assertNotIn('iframe src=',markup);self.assertIn('data-preview-original-src=',markup)
        self.assertIn('preventDefault()',markup)

    def test_missing_root_or_preparation_blocks_before_provider_calls(self):
        with patch('workflow.automation.website_preview_cloudflare_live.os.geteuid',return_value=1000):
            with self.assertRaises(PermissionError):self.adapter.provision(binding={})
        self.assertFalse(self.transport.calls)

    def test_multipart_forbids_header_injection(self):
        with self.assertRaises(ValueError):multipart([('x\r\nAuthorization',b'','text/plain')])
        raw,ctype=multipart([('metadata',b'{}','application/json')])
        self.assertIn(b'{}',raw);self.assertIn('boundary=',ctype)

class GuardTests(execution_tests.ExecutionTests):
    # Inherit and retain the canonical cross-repo/ref/revision/SHA tests.
    def test_cloudflare_foreign_tuple_is_rejected_before_network(self):
        adapter=CloudflarePreviewAdapter(transport=Transport(),clock=lambda:datetime.fromisoformat(self.boundary.verified_at),store=self.store,
            github=self.provider,local_git=object(),boundary=self.boundary,deployment_safety=object())
        for key,value in [('repository','foreign/repo'),('branch','main'),('head_sha','c'*40),('proposal_revision',99)]:
            bad={**self.binding,key:value}
            with patch('workflow.automation.website_preview_cloudflare_live.os.geteuid',return_value=0),self.assertRaises((ValueError,PermissionError)):
                adapter.provision(binding=bad)
        self.assertFalse(adapter.transport.calls)

class UploadTests(unittest.TestCase):
    def test_one_exact_upload_and_replay_creates_no_second_version(self):
        t=Transport();binding={'proposal_id':PROPOSAL_ID,'repository':REPOSITORY,'proposal_revision':3,'proposal_hash':'d'*64,'branch':'optimization/'+PROPOSAL_ID+'-camera','base_sha':'a'*40,'head_sha':'b'*40}
        class Writes(Transport):
            def request(self,method,path,**args):
                if method=='POST' and path==SCRIPT+'/assets-upload-session':
                    self.calls.append((method,path,args));return {'jwt':'MEMORY_SESSION','buckets':[]},NOW.isoformat()
                if method=='PUT' and path==SCRIPT:
                    self.calls.append((method,path,args));self.values[SCRIPT+'/versions']={'items':[{'id':VERSION}]}
                    self.values[SCRIPT+'/versions/'+VERSION]={'id':VERSION,'metadata':{'created_on':NOW.isoformat()},
                        'annotations':{'workers/tag':binding['head_sha'],'workers/message':json.dumps(binding)},'resources':{'bindings':[{'type':'assets','name':'ASSETS'}]}}
                    return {'id':PREVIEW_WORKER},NOW.isoformat()
                if method=='POST' and path==SCRIPT+'/subdomain':
                    self.calls.append((method,path,args));return {'enabled':True,'previews_enabled':True},NOW.isoformat()
                return super().request(method,path,**args)
        t=Writes();adapter=CloudflarePreviewAdapter(transport=t,clock=lambda:NOW)
        with tempfile.TemporaryDirectory() as directory,patch.object(adapter,'_guard') as guard:
            from workflow.automation.action_evidence import ActionEvidence
            audit_directory=tempfile.TemporaryDirectory();self.addCleanup(audit_directory.cleanup)
            adapter.audit=ActionEvidence(Path(audit_directory.name)/'audit.db')
            root=Path(directory);(root/'index.html').write_text('camera');(root/'preview-evidence.json').write_text(json.dumps(binding))
            digest=artifact_files(root)[1]
            result=adapter.upload(binding,root,digest)
            self.assertEqual(result['state'],'UPLOADED');self.assertEqual(guard.call_count,2)
            replay=adapter.upload(binding,root,digest);self.assertEqual(replay['provider_writes'],0)
            self.assertEqual(sum(m=='PUT' for m,_,_ in t.calls),1)
            self.assertTrue(all(p.startswith(PREFIX) or p.startswith('/zones/'+ZONE) for _,p,_ in t.calls))
            raw=next(a['raw'] for m,p,a in t.calls if m=='PUT');self.assertIn(PREVIEW_SCRIPT.encode(),raw)
            self.assertNotIn(b'opticable.ca',raw)

    def test_wrong_digest_or_manifest_fails_before_assets_or_code_write(self):
        for kind in ['digest','manifest']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);binding={k:'x' for k in BINDING_FIELDS};(root/'index.html').write_text('camera')
                (root/'preview-evidence.json').write_text(json.dumps({**binding,'head_sha':'wrong'} if kind=='manifest' else binding))
                t=Transport();adapter=CloudflarePreviewAdapter(transport=t)
                with patch.object(adapter,'_guard'),self.assertRaises(ValueError):
                    adapter.upload(binding,root,'wrong' if kind=='digest' else artifact_files(root)[1])
                self.assertFalse(t.calls)
