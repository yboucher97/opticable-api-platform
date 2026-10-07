"""Explicit static preview upload to one fixed Worker; no production writer.

Reuse the owner's dedicated user credential. The provider token is account
scoped; independent transport and canonical tuple guards constrain this lane.
No Builds mutation, token creation, route, domain, DNS or secret operation exists.
"""
import base64
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .website_preview_cloudflare_safety import ACCOUNT, PREVIEW_WORKER, USER_TOKEN_PATH
from .website_preview_execution import ProposalPreviewExecutor, BINDING_FIELDS
from .website_preview_github_live import NoRedirect, _trusted_bytes, PROPOSAL_ID, REPOSITORY
from .website_preview_git import no_symlinks
from .website_preview_model import sha, proposal_branch
from .website_preview_providers import ReadResult, safe_preview_url
from .website_registry import LiveSiteScope

PREFIX = '/accounts/' + ACCOUNT
SCRIPT = PREFIX + '/workers/scripts/' + PREVIEW_WORKER
WORKER = PREFIX + '/workers/workers/' + PREVIEW_WORKER
ZONE = 'ea7b4f245feb0a98fb5534e73e761970'
PAGE = '/fr/services/systemes-cameras-securite/'
UUID = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'
PREVIEW_SCRIPT = '''export default { async fetch(request, env) {
  if (!["GET", "HEAD"].includes(request.method)) return new Response("Preview is read only", {status:405});
  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/")) return new Response("Preview has no production API", {status:404});
  // The native generator uses /index.html for the French homepage.
  if (["/fr", "/fr/"].includes(url.pathname)) url.pathname = "/";
  const response = await env.ASSETS.fetch(new Request(url, request));
  const headers = new Headers(response.headers);
  headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  headers.set("Content-Security-Policy", "form-action 'none'; frame-src 'none'; connect-src 'self'; object-src 'none'; base-uri 'self'");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("Cache-Control", "no-store");
  return new Response(response.body, {status:response.status, headers});
} };'''


class CloudflareFailure(Exception):
    def __init__(self, status, codes):
        self.status = status; self.codes = codes
        super().__init__('Cloudflare HTTP ' + str(status) + ' codes ' + str(codes))


def multipart(parts):
    boundary = 'optibrain-' + secrets.token_hex(16)
    chunks = []
    for name, content, content_type in parts:
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', name):
            raise ValueError('Safe fixed multipart name required')
        chunks.extend([('--' + boundary + '\r\nContent-Disposition: form-data; name="' + name
            + '"; filename="' + name + '"\r\nContent-Type: ' + content_type + '\r\n\r\n').encode(), content, b'\r\n'])
    chunks.append(('--' + boundary + '--\r\n').encode())
    return b''.join(chunks), 'multipart/form-data; boundary=' + boundary


class PreviewCloudflareHTTP:
    """Fixed account/target with an independent endpoint and payload backstop."""
    def __init__(self, *, maximum=100, scope=None):
        self.scope=scope or LiveSiteScope("opticable.ca",PROPOSAL_ID,3)
        site=self.scope.value();self.preview_worker=site["preview_target"]
        self.script=PREFIX+"/workers/scripts/"+self.preview_worker;self.worker=PREFIX+"/workers/workers/"+self.preview_worker
        if type(maximum) is not int or not 1 <= maximum <= 100: raise ValueError('Bounded budget required')
        self.maximum = maximum; self.calls = []; self.denied = False
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, *, body=None, raw=None, content_type=None, upload_token=None):
        reads = {'/user/tokens/verify', PREFIX, PREFIX+'/workers/scripts', PREFIX+'/workers/subdomain',
            PREFIX+'/workers/domains', self.worker, self.script+'/settings', self.script+'/versions', self.script+'/deployments',
            self.script+'/subdomain', '/zones/'+ZONE+'/workers/routes'}
        valid_read = path in reads or bool(re.fullmatch(re.escape(self.script+'/versions/')+UUID, path))
        creates = method == 'POST' and path == PREFIX+'/workers/workers'
        if creates and body != {'name':self.preview_worker,'subdomain':{'enabled':False,'previews_enabled':True},'observability':{'enabled':False}}:
            raise ValueError('Only isolated empty Worker provisioning permitted')
        subdomain = method == 'POST' and path == self.script+'/subdomain'
        if subdomain and body != {'enabled':True,'previews_enabled':True}: raise ValueError('Preview-only subdomain required')
        assets = method == 'POST' and path == self.script+'/assets-upload-session'
        if assets and (not isinstance(body,dict) or set(body)!={'manifest'} or not 1<=len(body['manifest'])<=5000):
            raise ValueError('Bounded assets manifest required')
        bucket = method == 'POST' and path == PREFIX+'/workers/assets/upload?base64=true' and upload_token is not None
        version = method == 'PUT' and path == self.script and raw is not None
        if not (method=='GET' and valid_read or creates or subdomain or assets or bucket or version):
            raise ValueError('Endpoint outside isolated preview authority')
        if self.denied: raise PermissionError('Earlier provider denial; no retry')
        if len(self.calls)>=self.maximum: raise ValueError('Preview request budget exhausted')
        payload = json.dumps(body,separators=(',',':')).encode() if body is not None else raw
        if payload is not None and len(payload)>64*1024*1024: raise ValueError('Upload size exceeds bound')
        # Zone inventory is read-only and uses the existing account credential.
        # The separate user credential alone authorizes isolated Worker writes.
        credential_path = Path('/etc/optibrain/cloudflare-test-token') if path == '/zones/'+ZONE+'/workers/routes' else USER_TOKEN_PATH
        credential = upload_token or _trusted_bytes(credential_path,256).decode('ascii').strip()
        if not isinstance(credential,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{20,16384}',credential):
            raise PermissionError('Credential encoding invalid')
        self.calls.append({'method':method,'endpoint':path,'body_bytes':len(payload or b'')})
        request = Request('https://api.cloudflare.com/client/v4'+path,data=payload,method=method,
            headers={'Authorization':'Bearer '+credential,'Content-Type':content_type or 'application/json',
                'User-Agent':'OptiBrain-Isolated-Preview'})
        try: response = self.opener.open(request,timeout=30)
        except HTTPError as error: response = error
        with response:
            status=response.code; data=response.read(1048577)
            source=parsedate_to_datetime(response.headers['Date']).astimezone(timezone.utc).isoformat()
        if len(data)>1048576: raise ValueError('Provider response exceeds bound')
        value=json.loads(data); codes=[e.get('code') for e in value.get('errors') or []]
        self.calls[-1].update(http=status,success=value.get('success'),error_codes=codes)
        if status in (401,403): self.denied=True
        if not 200<=status<300 or value.get('success') is not True: raise CloudflareFailure(status,codes)
        # Deployment history only needs the newest page; all containment lists must be complete.
        info=value.get('result_info') or {}
        if path!=self.script+'/deployments' and info.get('total_pages',1)!=1:
            raise ValueError('Containment inventory incomplete')
        return value['result'], source


def artifact_files(root):
    root=no_symlinks(root); records={}; total=0
    if not root.is_dir(): raise ValueError('Built artifact required')
    for path in sorted(root.rglob('*')):
        no_symlinks(path)
        if path.is_dir(): continue
        if not path.is_file() or path.stat().st_size>25*1024*1024: raise ValueError('Unsafe/oversize asset')
        name=path.relative_to(root).as_posix()
        if any(p.startswith('.') for p in path.relative_to(root).parts) or name in {'_redirects','_headers'}:
            raise ValueError('Hidden/deployment asset forbidden')
        data=path.read_bytes(); total+=len(data)
        records['/'+name]={'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)}
        if total>256*1024*1024 or len(records)>5000: raise ValueError('Artifact bound exceeded')
    if not records: raise ValueError('Empty artifact')
    digest=hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return records,digest


class CloudflarePreviewAdapter:
    def __init__(self, *, transport=None, clock=None, store=None, github=None, local_git=None,
                 boundary=None, deployment_safety=None, scope=None, audit=None):
        self.scope=scope or LiveSiteScope("opticable.ca",PROPOSAL_ID,3)
        site=self.scope.value();self.preview_worker=site["preview_target"];self.repository=site["repository"];self.proposal_id=self.scope.proposal_id
        self.script=PREFIX+"/workers/scripts/"+self.preview_worker;self.worker=PREFIX+"/workers/workers/"+self.preview_worker
        self.page="/fr/" if self.scope.site_id=="ai.opticable.ca" else PAGE
        self.transport=transport or PreviewCloudflareHTTP(scope=self.scope); self.clock=clock or (lambda:datetime.now(timezone.utc))
        if getattr(self.transport,'scope',self.scope)!=self.scope:raise ValueError('Cloudflare transport site scope differs')
        self.store=store; self.github=github; self.local_git=local_git; self.boundary=boundary
        self.deployment_safety=deployment_safety; self.last_source=None
        from .action_evidence import ActionEvidence
        self.audit=audit or (ActionEvidence(store.path) if store else None)
        self.audit_action_id=None

    def _project(self,project):
        if project!=self.preview_worker: raise ValueError('Only isolated preview Worker allowed')

    def _call(self,method,path,**args):
        if method!='GET':
            if not self.audit or not self.audit_action_id or self.audit.get(self.audit_action_id)['status']!='STARTED':
                raise PermissionError('Durable started universal action required for preview mutation')
            self.audit.event(self.audit_action_id,'TECHNICAL_AUDIT','PROVIDER_REQUEST',
                {'method':method,'path':path,'body_keys':list((args.get('body') or {}).keys()),'raw_bytes':len(args.get('raw') or b'')},self.clock())
        result,self.last_source=self.transport.request(method,path,**args)
        if method!='GET':self.audit.event(self.audit_action_id,'TECHNICAL_AUDIT','PROVIDER_RESPONSE',
            {'method':method,'path':path,'source_at':self.last_source,'object_id':result.get('id') if isinstance(result,dict) else None},self.clock())
        return result

    def _observe(self,operation):
        now=self.clock().isoformat()
        try:
            data=operation(); return ReadResult('VERIFIED_EMPTY' if data==[] else 'COMPLETE',data,
                self.last_source,self.clock().isoformat(),1,1,0).validate()
        except CloudflareFailure as error:
            return ReadResult('BLOCKED_AUTH' if error.status in (401,403) else 'FAILED',None,None,now,1,0,1,
                'HTTP_'+str(error.status)+'_CODES_'+str(error.codes)).validate()
        except (ValueError,KeyError,TypeError,PermissionError,OSError):
            return ReadResult('FAILED',None,None,now,1,0,1,'INVALID_PREVIEW_PROVIDER_READ').validate()

    def get_project(self,project):
        self._project(project)
        def read():
            worker=self._call('GET',self.worker)
            if worker.get('name')!=self.preview_worker: raise ValueError('Worker name differs')
            return {'project':self.preview_worker,'account':ACCOUNT,'worker_id':worker['id'],'environment':'preview'}
        return self._observe(read)

    def _configuration(self):
        worker=self._call('GET',self.worker)
        if worker.get('name')!=self.preview_worker: raise ValueError('Wrong Worker')
        references=worker.get('references') or {}
        if references.get('routes') or references.get('domains'): raise ValueError('Worker routes/domains forbidden')
        routes=self._call('GET','/zones/'+ZONE+'/workers/routes')
        domains=self._call('GET',PREFIX+'/workers/domains')
        if any(r.get('script')==self.preview_worker for r in routes) or any(d.get('service')==self.preview_worker for d in domains):
            raise ValueError('Preview route/domain present')
        versions=self._versions()
        bindings=[]
        if versions:
            detail=self._call('GET',self.script+'/versions/'+versions[0]['id'])
            bindings=(detail.get('resources',{}).get('bindings') or [])
            if bindings != [{'type':'assets','name':'ASSETS'}]:
                raise ValueError('Production/external binding forbidden')
            settings=self._call('GET',self.script+'/settings')
            if settings.get('bindings') != [{'type':'assets','name':'ASSETS'}]:
                raise ValueError('Unsafe Worker settings bindings')
        return {'project':self.preview_worker,'environment':'preview','non_production_proof':True,
            'isolated':True,'production_routes':False,
            'worker_id':worker['id'],'routes':[],'domains':[],'bindings':bindings,'version_count':len(versions),
            'production_secrets_copied':False,'production_bindings_copied':False}

    def get_preview_configuration(self,project):
        self._project(project); return self._observe(self._configuration)

    def _versions(self):
        value=self._call('GET',self.script+'/versions'); items=value.get('items') if isinstance(value,dict) else value
        if not isinstance(items,list) or len(items)>1: raise ValueError('Exactly-one initial version bound')
        for v in items:
            if not re.fullmatch(UUID,v.get('id','')): raise ValueError('Version identity invalid')
        return items

    def list_deployments(self,project):
        self._project(project); return self._observe(lambda:self._versions())

    def _deployment(self,version):
        data=self._call('GET',self.script+'/versions/'+version)
        if data.get('id')!=version: raise ValueError('Version readback differs')
        metadata=data.get('metadata') or {}; annotations=data.get('annotations') or {}
        binding=json.loads(annotations.get('workers/message',''))
        if set(binding)!=set(BINDING_FIELDS) or binding['proposal_id']!=self.proposal_id or binding['repository']!=self.repository or type(binding['proposal_revision']) is not int or binding['proposal_revision']!=self.scope.proposal_revision or not re.fullmatch('[a-f0-9]{64}',binding['proposal_hash']):
            raise ValueError('Canonical deployment annotation required')
        sha(binding['head_sha']);sha(binding['base_sha']);proposal_branch(binding['branch'],self.proposal_id)
        if self.store:
            current=self.store.preview(self.proposal_id,self.clock())
            if not current or any(current.get(k)!=binding[k] for k in BINDING_FIELDS):raise ValueError('Deployment canonical tuple differs')
        if annotations.get('workers/tag')!=binding.get('head_sha'): raise ValueError('Source SHA annotations differ')
        sub=self._call('GET',PREFIX+'/workers/subdomain')
        if sub.get('subdomain')!='yboucher': raise ValueError('Account subdomain differs')
        config=self._configuration()
        enabled=self._call('GET',self.script+'/subdomain')
        if enabled.get('enabled') is not True or enabled.get('previews_enabled') is not True:raise ValueError('Version URL not enabled on isolated target')
        url='https://'+version[:8]+'-'+self.preview_worker+'.yboucher.workers.dev'+self.page
        return {**binding,'id':version,'project':self.preview_worker,'environment':'preview','non_production_proof':True,
            'state':'success','source_at':metadata['created_on'],'url':url,'account':ACCOUNT,'configuration':config}

    def find_deployment_for_sha(self,project,commit):
        self._project(project)
        from .website_preview_model import sha
        sha(commit)
        def read():
            versions=self._versions()
            if not versions: return []
            value=self._deployment(versions[0]['id'])
            return value if value.get('head_sha')==commit else []
        return self._observe(read)

    def read_deployment(self,project,deployment_id):
        self._project(project)
        if not re.fullmatch(UUID,deployment_id): raise ValueError('Exact version required')
        return self._observe(lambda:self._deployment(deployment_id))

    def validate_preview_url(self,url):
        if not isinstance(url,str): raise ValueError('Preview URL required')
        from urllib.parse import urlsplit
        host=urlsplit(url).hostname
        if not host or not re.fullmatch(r'[a-f0-9]{8}-'+self.preview_worker+r'\.yboucher\.workers\.dev',host):
            raise ValueError('Immutable isolated hostname required')
        return safe_preview_url(url,(host,),('opticable.ca','www.opticable.ca','ai.opticable.ca'))

    def _audited(self,binding,operation,before,execute,readback):
        from .action_evidence import envelope,execute_action
        from .acquisition_store import digest
        if not self.audit:raise PermissionError('Existing durable preview audit journal required')
        now=self.clock();aid=digest(['cloudflare-preview',operation,binding])
        plan=envelope(aid,operation,{'type':'PREVIEW_WORKER','identity':self.preview_worker},now,
            mutation=True,provider='CLOUDFLARE',proposal_id=binding['proposal_id'],before_state=before,proposed_state=binding,
            reason='Isolated exact-version website preview for owner review',business_rationale='Only bounded non-production configuration/assets are permitted by the existing guard',
            authority_class='EXISTING_PREVIEW_SCOPE',automatic_rule='Root configuration, exact tested tuple and independent containment checks',
            exact_versions={**binding,'environment':'preview'},rollback_capability='COMPENSATING_ACTION_ONLY',
            consequence='Preview URL/version may be externally consumed; production is unchanged',
            compensating_action='Owner may disable/archive isolated preview after checking usage; retain version and action history')
        def run():
            self.audit_action_id=aid
            try:return {'success':True,'result':execute()}
            finally:self.audit_action_id=None
        return execute_action(self.audit,plan,now,authority_check=lambda:None,execute=run,readback=readback,
            verify=lambda actual,expected:actual is not None,clock=self.clock)

    def provision(self,*,binding):
        self._guard(binding,require_ci=False)
        workers=self._call('GET',PREFIX+'/workers/scripts')
        if any(w.get('id')==self.preview_worker for w in workers):return self._configuration()
        self._audited(binding,'PREVIEW_WORKER_PROVISION',{'exists':False},
            lambda:self._provision(binding=binding),self._configuration)
        return self._configuration()

    def _provision(self,*,binding):
        # The public entrypoint has verified exact prepared tests and root scope.
        workers=self._call('GET',PREFIX+'/workers/scripts')
        if any(w.get('id')==self.preview_worker for w in workers):
            return self._configuration()
        self._call('POST',PREFIX+'/workers/workers',body={'name':self.preview_worker,
            'subdomain':{'enabled':False,'previews_enabled':True},'observability':{'enabled':False}})
        return self._configuration()

    def _guard(self,binding,*,require_ci=True):
        if os.geteuid()!=0 or not all([self.store,self.github,self.local_git,self.boundary,self.deployment_safety]):
            raise PermissionError('Explicit root-configured preview execution required')
        ProposalPreviewExecutor(self.store,self.github,self.boundary)._prepared(binding,self.clock())
        self.deployment_safety.require_safe(binding)
        state=self.local_git.read_worktree_state(binding['proposal_id'])
        if state['dirty'] or state['head_sha']!=binding['head_sha']: raise ValueError('Local source differs')
        main=self.github.get_branch(binding['repository'],'main')
        if main.state!='COMPLETE' or main.data['sha']!=binding['base_sha']: raise ValueError('Stale website base')
        if require_ci:
            ref=self.github.get_branch(binding['repository'],binding['branch']); pr=self.github.get_pr(binding['repository'],binding['branch'])
            ci=self.github.get_workflow_status(binding['repository'],binding['head_sha'])
            no_op=self.scope.site_id=='ai.opticable.ca' and self.store.preview(binding['proposal_id'],self.clock())['package'].get('no_op') is True and binding['head_sha']==binding['base_sha']
            valid_pr=pr.state=='VERIFIED_EMPTY' if no_op else (pr.state=='COMPLETE' and pr.data.get('draft') is True and pr.data.get('state')=='open' and pr.data.get('base_ref')=='main' and pr.data.get('auto_merge') is None and pr.data.get('head_sha')==binding['head_sha'])
            if ref.state!='COMPLETE' or ref.data['sha']!=binding['head_sha'] or not valid_pr:
                raise PermissionError('Exact remote ref and draft required')
            if ci.state!='COMPLETE' or ci.data.get('head_sha')!=binding['head_sha'] or ci.data.get('checks',{}).get('validate')!='PASS':
                raise PermissionError('Exact-head native CI required')

    def upload(self,binding,artifact_root,artifact_digest):
        self._guard(binding)
        if artifact_files(artifact_root)[1]!=artifact_digest:raise ValueError('Tested artifact changed')
        manifest=json.loads((Path(artifact_root)/'preview-evidence.json').read_text())
        if any(manifest.get(k)!=v for k,v in binding.items()):raise ValueError('Artifact tuple differs')
        before=self._configuration()
        if before['version_count']:return self._upload(binding,artifact_root,artifact_digest)
        result={}
        def execute():
            result.update(self._upload(binding,artifact_root,artifact_digest));return result
        def readback():
            read=self.find_deployment_for_sha(self.preview_worker,binding['head_sha'])
            if read.state!='COMPLETE' or any(read.data.get(k)!=v for k,v in binding.items()):raise ValueError('Exact version readback failed')
            return read.data
        self._audited(binding,'PREVIEW_UPLOAD',before,execute,readback)
        return result

    def _upload(self,binding,artifact_root,artifact_digest):
        files,digest=artifact_files(artifact_root)
        if digest!=artifact_digest: raise ValueError('Tested artifact changed')
        manifest=json.loads((Path(artifact_root)/'preview-evidence.json').read_text())
        if any(manifest.get(k)!=v for k,v in binding.items()): raise ValueError('Artifact tuple differs')
        config=self._configuration()
        if config['version_count']:
            existing=self.find_deployment_for_sha(self.preview_worker,binding['head_sha'])
            if existing.state=='COMPLETE' and all(existing.data.get(k)==v for k,v in binding.items()):
                return {'state':'EXACT_REPLAY','deployment':existing.data,'provider_writes':0}
            raise ValueError('Existing unrelated version; no overwrite')
        cloud_manifest={}; by_hash={}
        for name,record in files.items():
            path=Path(artifact_root)/name.lstrip('/'); raw=path.read_bytes()
            h=hashlib.sha256(base64.b64encode(raw)+path.suffix.lstrip('.').encode()).hexdigest()[:32]
            cloud_manifest[name]={'hash':h,'size':record['size']}; by_hash[h]=path
        session=self._call('POST',self.script+'/assets-upload-session',body={'manifest':cloud_manifest})
        buckets=session.get('buckets'); token=session.get('jwt')
        if not isinstance(buckets,list) or len(buckets)>30 or not isinstance(token,str): raise ValueError('Upload session invalid')
        completion=token if not buckets else None
        for bucket in buckets:
            if not isinstance(bucket,list) or not bucket or any(h not in by_hash for h in bucket): raise ValueError('Unknown upload bucket')
            parts=[(h,base64.b64encode(by_hash[h].read_bytes()),mimetypes.guess_type(str(by_hash[h]))[0] or 'application/octet-stream') for h in bucket]
            raw,ctype=multipart(parts)
            result=self._call('POST',PREFIX+'/workers/assets/upload?base64=true',raw=raw,content_type=ctype,upload_token=token)
            if result.get('jwt'): completion=result['jwt']
        if not completion: raise ValueError('Asset completion proof absent')
        # Recheck source, identity, CI and containment immediately before code upload.
        self._guard(binding)
        if artifact_files(artifact_root)[1]!=digest or self._configuration()['version_count']!=0:
            raise ValueError('Artifact/target changed before upload')
        metadata={'main_module':'preview.js','compatibility_date':'2026-10-06',
            'bindings':[{'type':'assets','name':'ASSETS'}],
            'assets':{'jwt':completion,'config':{'html_handling':'auto-trailing-slash','not_found_handling':'404-page','run_worker_first':True}},
            'annotations':{'workers/tag':binding['head_sha'],'workers/message':json.dumps(binding,sort_keys=True,separators=(',',':'))}}
        script=PREVIEW_SCRIPT
        if self.scope.site_id=='ai.opticable.ca':
            script=script.replace('if (["/fr", "/fr/"].includes(url.pathname)) url.pathname = "/";', '')
        raw,ctype=multipart([('metadata',json.dumps(metadata).encode(),'application/json'),('preview.js',script.encode(),'application/javascript+module')])
        self._call('PUT',self.script,raw=raw,content_type=ctype)
        self._call('POST',self.script+'/subdomain',body={'enabled':True,'previews_enabled':True})
        read=self.find_deployment_for_sha(self.preview_worker,binding['head_sha'])
        if read.state!='COMPLETE' or any(read.data.get(k)!=v for k,v in binding.items()): raise ValueError('Exact version readback failed')
        return {'state':'UPLOADED','deployment':read.data,'artifact_sha256':digest,'provider_writes':1}


class PreviewHTTP:
    def __init__(self,provider): self.provider=provider; self.reads=[]; self.opener=build_opener(NoRedirect())
    def get(self,url):
        self.provider.validate_preview_url(url)
        if len(self.reads)>=8: raise ValueError('Bounded preview HTTP budget')
        self.reads.append(url)
        request=Request(url,headers={'User-Agent':'Mozilla/5.0 OptiBrain-Preview-Verification'})
        with self.opener.open(request,timeout=15) as response:
            if response.status!=200 or response.url!=url: raise ValueError('Preview status/redirect unsafe')
            raw=response.read(262145)
        if len(raw)>262144: raise ValueError('Page exceeds bound')
        from urllib.parse import urlsplit
        origin='https://'+urlsplit(url).netloc
        with self.opener.open(Request(origin+'/preview-evidence.json',headers={'User-Agent':'Mozilla/5.0 OptiBrain-Preview-Verification'}),timeout=15) as response:
            if response.status!=200 or response.url!=origin+'/preview-evidence.json': raise ValueError('Manifest redirect/status unsafe')
            manifest=json.loads(response.read(16385))
        return {'status':200,'body':raw.decode('utf-8'),'final_url':url,'redirects':[],'manifest':manifest}
