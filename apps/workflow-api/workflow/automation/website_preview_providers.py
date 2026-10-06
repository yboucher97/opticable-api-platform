"""Bounded provider ports and deterministic offline adapters; no live writes."""
from copy import deepcopy
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urlsplit
import json
import re
from .manager_sources import stamp
from .acquisition_store import safe
from .website_preview_model import READ_STATES, repository_name, sha, proposal_branch


@dataclass(frozen=True)
class ReadResult:
    state: str
    data: object = None
    source_at: str | None = None
    observed_at: str | None = None
    attempted: int = 0
    successful: int = 0
    failed: int = 0
    reason: str = ''

    def validate(self):
        if not isinstance(self.reason,str) or len(self.reason)>500:raise ValueError('Bounded provider reason required')
        if self.state not in READ_STATES or any(type(n) is not int or n<0 or n>1 for n in (self.attempted,self.successful,self.failed)) or self.successful+self.failed!=self.attempted:
            raise ValueError('Invalid provider observation accounting')
        if self.state in {'COMPLETE','VERIFIED_EMPTY','PARTIAL','STALE'} and (not self.successful or not stamp(self.source_at)):
            raise ValueError('Successful data requires independent source time')
        if self.state=='VERIFIED_EMPTY' and self.data not in ([],None):raise ValueError('Empty proof inconsistent')
        if self.state in {'FAILED','BLOCKED_AUTH','NOT_COLLECTED'} and self.data is not None:raise ValueError('Failed read cannot supply success data')
        if self.attempted and not stamp(self.observed_at):raise ValueError('Attempt observation time required')
        if len(json.dumps(self.data,allow_nan=False).encode())>262144:raise ValueError('Provider response exceeds bound')
        return self

    def metadata(self):
        self.validate()
        return {k:getattr(self,k) for k in ('state','source_at','observed_at','attempted','successful','failed','reason')}


class GitHubProvider(Protocol):
    def get_repository(self, repository: str) -> ReadResult: ...
    def get_branch(self, repository: str, branch: str) -> ReadResult: ...
    def get_commit(self, repository: str, commit: str) -> ReadResult: ...
    def get_pr(self, repository: str, branch: str) -> ReadResult: ...
    def get_workflow_status(self, repository: str, commit: str) -> ReadResult: ...
    def push_proposal_branch(self, repository: str, branch: str, commit: str, proposal_id: str): ...
    def open_draft_pr(self, repository: str, branch: str, proposal_id: str): ...
    def read_webhook_event(self, event: dict): ...


class CloudflareProvider(Protocol):
    def get_project(self, project: str) -> ReadResult: ...
    def get_preview_configuration(self, project: str) -> ReadResult: ...
    def list_deployments(self, project: str) -> ReadResult: ...
    def find_deployment_for_sha(self, project: str, commit: str) -> ReadResult: ...
    def read_deployment(self, project: str, deployment_id: str) -> ReadResult: ...
    def validate_preview_url(self, url: str): ...


class DisabledProviderMutations:
    """Production adapter base: mutation methods are always disabled in this lane."""
    def push_proposal_branch(self,*args,**kwargs):raise PermissionError('OWNER ACTION / PROVIDER CONFIG REQUIRED')
    def open_draft_pr(self,*args,**kwargs):raise PermissionError('OWNER ACTION / PROVIDER CONFIG REQUIRED')


class BoundedFake:
    def __init__(self, fixtures, now, *, max_reads=20):
        if type(max_reads) is not int or not 1<=max_reads<=30:raise ValueError('Read budget must be 1..30')
        self.fixtures=deepcopy(fixtures);self.now=now;self.max_reads=max_reads;self.reads=[];self.writes=[]

    def _read(self, key):
        at=self.now.isoformat()
        if len(self.reads)>=self.max_reads:return ReadResult('NOT_COLLECTED',reason='READ_BUDGET_EXHAUSTED').validate()
        self.reads.append(key)
        v=self.fixtures.get(key)
        if v is None:return ReadResult('VERIFIED_EMPTY',[],at,at,1,1,0).validate()
        if isinstance(v,ReadResult):return v.validate()
        if isinstance(v,dict) and v.get('http_status') in (401,403):return ReadResult('BLOCKED_AUTH',None,None,at,1,0,1,'HTTP '+str(v['http_status'])).validate()
        if isinstance(v,dict) and v.get('timeout'):return ReadResult('FAILED',None,None,at,1,0,1,'TIMEOUT').validate()
        if isinstance(v,dict) and v.get('http_status',200)>=400:return ReadResult('FAILED',None,None,at,1,0,1,'PROVIDER_ERROR').validate()
        if isinstance(v,dict) and 'read_state' in v:
            state=v['read_state'];data=v.get('data');source=v.get('source_at')
            if state in {'FAILED','BLOCKED_AUTH','NOT_COLLECTED'}:
                return ReadResult(state,None,None,at,1,0,1,'FIXTURE_'+state).validate()
        else:state='VERIFIED_EMPTY' if v==[] else 'COMPLETE';data=v;source=at
        try:return ReadResult(state,deepcopy(data),source,at,1,1,0).validate()
        except (ValueError,TypeError):return ReadResult('FAILED',None,None,at,1,0,1,'UNEXPECTED_PROVIDER_RESPONSE').validate()


class FakeGitHubProvider(BoundedFake,DisabledProviderMutations):
    def __init__(self, repository, fixtures, now, *, allow_fake_mutations=False, max_reads=20):
        super().__init__(fixtures,now,max_reads=max_reads);self.repository=repository_name(repository);self.allow_fake_mutations=allow_fake_mutations

    def _repo(self,repository):
        if repository!=self.repository:raise ValueError('Unallowed repository')
    def get_repository(self,repository):self._repo(repository);return self._read('repository')
    def get_branch(self,repository,branch):self._repo(repository);return self._read('branch:'+branch)
    def get_commit(self,repository,commit):self._repo(repository);sha(commit);return self._read('commit:'+commit)
    def get_pr(self,repository,branch):self._repo(repository);return self._read('pr:'+branch)
    def get_workflow_status(self,repository,commit):self._repo(repository);sha(commit);return self._read('workflow:'+commit)
    def read_webhook_event(self,event):self._repo(event['repository']);return deepcopy(event)
    def push_proposal_branch(self,repository,branch,commit,proposal_id):
        self._repo(repository);proposal_branch(branch,proposal_id);sha(commit)
        if not self.allow_fake_mutations:return super().push_proposal_branch()
        self.writes.append(('FAKE_ONLY_PUSH',branch,commit));return {'state':'SIMULATED','provider_writes':0}
    def open_draft_pr(self,repository,branch,proposal_id):
        self._repo(repository);proposal_branch(branch,proposal_id)
        if not self.allow_fake_mutations:return super().open_draft_pr()
        self.writes.append(('FAKE_ONLY_DRAFT_PR',branch));return {'state':'SIMULATED','draft':True,'number':1,'provider_writes':0}


class FakeCloudflareProvider(BoundedFake):
    def __init__(self, project, fixtures, now, *, allowed_hosts=(), production_hosts=(), max_reads=20):
        super().__init__(fixtures,now,max_reads=max_reads);self.project=project;self.allowed_hosts=tuple(allowed_hosts);self.production_hosts=tuple(production_hosts)
    def _project(self,project):
        if project!=self.project:raise ValueError('Unallowed Cloudflare project')
    def get_project(self,project):self._project(project);return self._read('project')
    def get_preview_configuration(self,project):self._project(project);return self._read('configuration')
    def list_deployments(self,project):
        self._project(project);r=self._read('deployments')
        if r.state in {'COMPLETE','VERIFIED_EMPTY'} and (not isinstance(r.data,list) or len(r.data)>20):
            return ReadResult('FAILED',None,None,r.observed_at,1,0,1,'UNEXPECTED_PROVIDER_RESPONSE')
        return r
    def find_deployment_for_sha(self,project,commit):
        self._project(project);sha(commit);return self._read('sha:'+commit)
    def read_deployment(self,project,deployment_id):self._project(project);return self._read('deployment:'+deployment_id)
    def validate_preview_url(self,url):return safe_preview_url(url,self.allowed_hosts,self.production_hosts)


def safe_preview_url(url,allowed_hosts,production_hosts):
    if not isinstance(url,str) or len(url)>2048 or re.search(r'[\x00-\x20\\]',url):raise ValueError('Unsafe preview URL')
    p=urlsplit(url)
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or p.query or p.fragment or p.hostname not in allowed_hosts or p.hostname in production_hosts:
        raise ValueError('HTTPS explicit non-production hostname required')
    if p.netloc not in {p.hostname,p.hostname+':443'} or any(x in p.path for x in ('..','%')):raise ValueError('Preview URL normalization required')
    return url


class FakeHTTP:
    def __init__(self, responses, *, max_reads=8):
        if not 1<=max_reads<=8:raise ValueError('HTTP budget invalid')
        self.responses=deepcopy(responses);self.max_reads=max_reads;self.reads=[]
    def get(self,url):
        if len(self.reads)>=self.max_reads:raise TimeoutError('HTTP budget exhausted')
        self.reads.append(url)
        result=deepcopy(self.responses.get(url,{'status':404,'body':''}))
        if len(json.dumps(result).encode())>262144:raise ValueError('HTTP response exceeds bound')
        return result


class PageEvidence(HTMLParser):
    def __init__(self):
        super().__init__();self.form=False;self.cta=False;self.noindex=False;self.canonical=[];self.text=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form' or tag=='iframe' and a.get('data-preview-form')=='present':self.form=True
        if tag=='a' and a.get('data-preview-cta')=='quote':self.cta=True
        if tag=='meta' and a.get('name','').lower()=='robots' and 'noindex' in a.get('content','').lower():self.noindex=True
        if tag=='link' and a.get('rel')=='canonical':self.canonical.append(a.get('href'))
    def handle_data(self,data):self.text.append(data)


def validate_http(value, provider, http, now, *, expected_page, canonical_url, require_forms=False, require_cta=True, require_marker=True):
    url=provider.validate_preview_url(value['preview_url']);response=http.get(url)
    if response.get('status')!=200 or response.get('redirects') or response.get('final_url',url)!=url:raise ValueError('Successful preview GET without redirect required')
    page=PageEvidence();page.feed(response.get('body',''))
    if expected_page not in ' '.join(page.text) or page.canonical!=[canonical_url] or not page.noindex or (require_forms and not page.form) or (require_cta and not page.cta):
        raise ValueError('Expected preview content/canonical/noindex/Forms/CTA missing')
    keys=('proposal_id','proposal_revision','repository','branch','head_sha','base_sha')
    manifest=response.get('manifest')
    if require_marker and (not isinstance(manifest,dict) or any(manifest.get(k)!=value[k] for k in keys)):
        raise ValueError('Exact proposal manifest required')
    return {**{k:value[k] for k in keys},'state':'PASS','url':url,'observed_at':now.isoformat(),
        'content_digest':__import__('hashlib').sha256(response['body'].encode()).hexdigest(),
        'manifest_digest':__import__('hashlib').sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest(),
        'forms_checked':require_forms,'cta_checked':require_cta,'canonical':canonical_url,'noindex':True}


def verify_deployment(value, deployment, now):
    keys=('proposal_id','proposal_revision','repository','branch','head_sha','base_sha')
    if not isinstance(deployment,dict) or any(deployment.get(k)!=value[k] for k in keys):raise ValueError('Deployment exact proposal/ref/SHA mismatch')
    safe(deployment)
    if deployment.get('environment')!='preview' or deployment.get('non_production_proof') is not True or deployment.get('project')!=value['preview_project'] or deployment.get('branch')==value['production_branch'] or not deployment.get('id'):
        raise ValueError('Explicit isolated non-production proof required')
    created=stamp(deployment.get('source_at'))
    if not created or not 0<=(now-created).total_seconds()<=86400:raise ValueError('Stale/unverified deployment')
    if deployment.get('state') not in {'success','building','failure'}:raise ValueError('Unexpected deployment state')
    return deepcopy(deployment)
