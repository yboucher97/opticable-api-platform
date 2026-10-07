"""Data-only website preparation and exact-revision readiness contracts."""
from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import timedelta
from pathlib import PurePosixPath
import re
import unicodedata
from .acquisition_store import digest, safe
from .manager_sources import stamp

STATES = set('NOT_ELIGIBLE PREPARATION_ELIGIBLE BRANCH_PENDING BRANCH_CREATED WORKTREE_CREATED PREPARING BUILDING BUILD_FAILED TESTING TEST_FAILED PREVIEW_PENDING PREVIEW_READY OWNER_REVIEW REVISION_REQUESTED APPROVED REJECTED DEFERRED STALE_BASE CONFLICTED SUPERSEDED PROVIDER_BLOCKED READY_FOR_PRODUCTION_EXECUTOR'.split())
READ_STATES = set('COMPLETE VERIFIED_EMPTY PARTIAL FAILED NOT_COLLECTED STALE BLOCKED_AUTH'.split())
TEST_CLASSES = set('BUILD LINT ROUTES FR EN FORMS GA4 ATTRIBUTION LINKS SCHEMA CANONICAL ASSETS ACCESSIBILITY RESPONSIVE SECRET_SCAN'.split())
RUN_STATES = {'NOT_RUN', 'RUNNING', 'PASS', 'FAIL'}
OWNER_STATES = {'PENDING', 'APPROVED', 'REVISION_REQUESTED', 'REJECTED', 'DEFERRED', 'STALE_APPROVAL'}
STALE_STATES = {'UNKNOWN', 'CURRENT', 'NEEDS_REBASE', 'CONFLICTED', 'SUPERSEDED'}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[a-f0-9]{64}|OPT-[0-9]{4,8})', value):
        raise ValueError('Canonical proposal ID required')
    return value


def sha(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{40}', value):
        raise ValueError('Exact full Git SHA required')
    return value


def repository_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', value) or '..' in value:
        raise ValueError('Allowlisted full repository name required')
    return value


def branch_name(proposal_id, slug):
    identifier(proposal_id)
    if not isinstance(slug, str) or len(slug)>200 or re.search(r'[\x00-\x1f\x7f;$`\\/{}\[\]~^:*?<>|&]', slug) or '..' in slug or '@{' in slug:
        raise ValueError('Unsafe branch slug')
    cleaned = unicodedata.normalize('NFKD', slug).encode('ascii','ignore').decode().lower()
    cleaned = re.sub('[^a-z0-9-]+', '-', cleaned).strip('-')
    limit = min(48, 120-len('optimization/')-len(proposal_id)-1)
    cleaned = cleaned[:limit].rstrip('-')
    if not cleaned: raise ValueError('Empty branch slug')
    return 'optimization/'+proposal_id+'-'+cleaned


def proposal_branch(value, proposal_id):
    identifier(proposal_id)
    if not isinstance(value,str) or len(value)>120 or not re.fullmatch(r'optimization/'+re.escape(proposal_id)+r'-[a-z0-9]+(?:-[a-z0-9]+)*',value):
        raise ValueError('Proposal-only branch required')
    return value


def relative_file(value):
    if not isinstance(value,str) or len(value)>200 or not re.fullmatch(r'[A-Za-z0-9_./-]+',value):
        raise ValueError('Unsafe file scope')
    parts = PurePosixPath(value).parts
    if not parts or value.startswith('/') or any(p in {'..','.'} or p.startswith('.') for p in parts) or str(PurePosixPath(value))!=value:
        raise ValueError('File traversal/configuration scope forbidden')
    if parts[0] in {'deploy','ops','dist','node_modules','venv'} or any(re.search(r'(?i)(secret|credential|wrangler|dockerfile|requirements|package\.json|lock$)',p) for p in parts):
        raise ValueError('Deployment/dependency/credential scope forbidden')
    return value


@dataclass(frozen=True)
class RepositoryState:
    repository_id: str
    provider: str
    repository_full_name: str
    default_branch: str
    production_branch: str
    last_observed_sha: str | None = None
    last_analyzed_sha: str | None = None
    last_fetch_at: str | None = None
    local_clone_path: str | None = None
    auth_mode: str = 'DISABLED'
    preview_provider: str = 'CLOUDFLARE'
    preview_project: str | None = None
    health_state: str = 'NOT_COLLECTED'
    source_at: str | None = None
    site_id: str | None = None
    production_domain: str | None = None
    production_target: str | None = None
    build_definition: str | None = None
    test_definition: str | None = None
    github_installation_access: str = 'NOT_COLLECTED'
    cloudflare_access: str = 'NOT_COLLECTED'
    production_deployment_model: str | None = None
    preview_deployment_model: str | None = None
    last_production_sha: str | None = None
    last_preview_state: str = 'NOT_COLLECTED'
    last_measured_result: dict | None = None

    def value(self):
        value=asdict(self);repository_name(self.repository_full_name)
        from .website_registry import validate_scope
        site=validate_scope(self.repository_full_name,site_id=self.site_id,preview_target=self.preview_project)
        if site:
            for field in ('production_domain','production_target','production_deployment_model','preview_deployment_model'):
                if getattr(self,field) is not None and getattr(self,field)!=site[field]:raise ValueError('Site registry identity mismatch')
        if self.repository_id != 'github:'+self.repository_full_name or self.provider!='GITHUB':raise ValueError('Repository identity mismatch')
        if self.health_state not in READ_STATES:raise ValueError('Repository health required')
        for b in (self.default_branch,self.production_branch):
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_-]{0,99}',b) or '..' in b:raise ValueError('Invalid repository branch')
        for s in (self.last_observed_sha,self.last_analyzed_sha,self.last_production_sha):
            if s is not None:sha(s)
        for at in (self.source_at,self.last_fetch_at):
            if at is not None and not stamp(at):raise ValueError('Dated repository state required')
        safe(value);return value


def preparation_package(item, repository, base_sha, allowed_files, changes, required_tests, evidence_refs):
    r=item['record'];identifier(r['proposal_id']);repository_name(repository);sha(base_sha)
    if r['target_system']!='WEBSITE' or r['target_object'].get('system')!='WEBSITE' or r['target_object'].get('entity_type') not in {'WEBSITE_PAGE','LANDING_PAGE'} or type(r['revision']) is not int or r['revision']<1:raise ValueError('Website page proposal required')
    mapped=item['detail'].get('repository')
    if mapped!=repository:raise ValueError('Canonical repository mapping required')
    from .website_registry import validate_scope
    validate_scope(repository,page=r.get('target_url_or_record'),site_id=item['detail'].get('site_id'))
    no_op=r.get('proposal_type')=='SITE_PREVIEW_VERIFICATION' and item['detail'].get('no_op') is True and item['detail'].get('base_sha')==base_sha
    if not isinstance(allowed_files,list) or not (0 if no_op else 1)<=len(allowed_files)<=30 or len(set(allowed_files))!=len(allowed_files):raise ValueError('Bounded file scope required')
    for f in allowed_files:relative_file(f)
    if not isinstance(required_tests,list) or not required_tests or not set(required_tests)<=TEST_CLASSES or len(set(required_tests))!=len(required_tests):raise ValueError('Required test classes invalid')
    if not isinstance(changes,list) or not (0 if no_op else 1)<=len(changes)<=30:raise ValueError('Structured changes required')
    if no_op and (allowed_files or changes):raise ValueError('No-op verification must have zero source changes')
    for c in changes:
        if not isinstance(c,dict) or set(c)!={'path','before','after'} or c['path'] not in allowed_files or not all(isinstance(c[k],str) for k in ('before','after')) or not c['before'] or c['before']==c['after']:
            raise ValueError('Exact scoped text replacement required')
    if not isinstance(evidence_refs,list) or not evidence_refs or len(evidence_refs)>30:raise ValueError('Bounded evidence references required')
    for f in evidence_refs:relative_file(f)
    result={'proposal_id':r['proposal_id'],'proposal_revision':r['revision'],'proposal_hash':item['payload_hash'],
            'repository':repository,'base_sha':base_sha,'allowed_files':allowed_files,'changes':deepcopy(changes),
            'required_tests':sorted(required_tests),'evidence_refs':evidence_refs}
    safe(result)
    if no_op:result['no_op']=True
    if len(str(result).encode())>131072:raise ValueError('Preparation package exceeds bound')
    result['semantic_hash']=digest([r['proposal_id'],repository,base_sha,allowed_files,changes,sorted(required_tests)])
    return result


def new_preview(package, repository, now, slug):
    value=repository.value();pid=package['proposal_id']
    if package['repository']!=value['repository_full_name']:raise ValueError('Wrong repository')
    at=now.isoformat()
    return {'proposal_id':pid,'proposal_revision':package['proposal_revision'],'proposal_hash':package['proposal_hash'],
        'repository':package['repository'],'base_ref':value['default_branch'],'production_branch':value['production_branch'],
        'base_sha':package['base_sha'],'branch':branch_name(pid,slug),'head_sha':None,'worktree_path':None,'pr_number':None,
        'preview_provider':value['preview_provider'],'preview_project':value['preview_project'],'preview_deployment_id':None,
        'preview_url':None,'build_state':'NOT_RUN','test_state':'NOT_RUN','tests':{},'required_tests':package['required_tests'],
        'preview_state':'NOT_COLLECTED','stale_state':'UNKNOWN','owner_status':'PENDING','state':'PREPARATION_ELIGIBLE',
        'created_at':at,'updated_at':at,'last_verified_at':None,'rollback_base':package['base_sha'],
        'evidence_refs':package['evidence_refs'],'production_impact':'NONE','semantic_hash':package['semantic_hash'],
        'package':deepcopy(package),'provider_reads':{},'deployment':None,'http_validation':None,'approval':None}


def test_passes(value):
    head=value.get('head_sha')
    return bool(head and value.get('build_state')=='PASS' and value.get('build_result',{}).get('head_sha')==head and
        value.get('test_state')=='PASS' and value.get('required_tests') and all(
        value.get('tests',{}).get(k,{}).get('state')=='PASS' and value['tests'][k].get('head_sha')==head
        for k in value['required_tests']))


def preview_ready(value, now):
    """Recompute instead of trusting persisted READY flags or imported report text."""
    from .website_registry import validate_scope
    try:validate_scope(value['repository'],preview_target=value.get('preview_project'),site_id=value.get('site_id'))
    except (ValueError,KeyError):return False
    if not test_passes(value) or value.get('stale_state')!='CURRENT' or value.get('production_impact')!='NONE':return False
    last=stamp(value.get('last_verified_at'))
    if not last or not 0<=(now-last).total_seconds()<=3600:return False
    d=value.get('deployment') or {};h=value.get('http_validation') or {}
    keys=('proposal_id','proposal_revision','repository','branch','head_sha','base_sha')
    if any(d.get(k)!=value.get(k) or h.get(k)!=value.get(k) for k in keys):return False
    return bool(d.get('environment')=='preview' and d.get('non_production_proof') is True and d.get('state')=='success' and
        d.get('branch')!=value.get('production_branch') and value.get('head_sha') and
        d.get('project')==value.get('preview_project') and d.get('id')==value.get('preview_deployment_id') and
        d.get('url')==value.get('preview_url') and h.get('url')==value.get('preview_url') and h.get('state')=='PASS' and
        value.get('provider_reads',{}).get('cloudflare',{}).get('state')=='COMPLETE' and value.get('preview_state')=='PREVIEW_READY')


def approval_binding(value):
    bound={k:value.get(k) for k in ('proposal_id','proposal_revision','proposal_hash','repository','base_sha','branch','head_sha',
        'required_tests','tests','build_result','preview_deployment_id','preview_url','deployment','http_validation','semantic_hash')}
    # Re-reading identical evidence renews verification freshness without
    # silently changing the owner's material evidence tuple.
    for k in ('deployment','http_validation'):
        if isinstance(bound[k],dict):bound[k]={field:v for field,v in bound[k].items() if field not in {'source_at','observed_at'}}
    return digest(bound)


def owner_receipt(value, actor, now, *, expiry=None):
    if not actor or len(actor)>200 or not preview_ready(value,now):raise ValueError('Verified exact preview required for approval')
    expiry=expiry or now+timedelta(hours=24)
    if expiry.tzinfo is None or not now<expiry<=now+timedelta(days=7):raise ValueError('Bounded future approval expiry required')
    return {'binding':approval_binding(value),'actor':actor,'at':now.isoformat(),'expires_at':expiry.isoformat(),
        'proposal_revision':value['proposal_revision'],'head_sha':value['head_sha'],'execution_authorized':False}


def approval_current(value, now):
    a=value.get('approval') or {};expires=stamp(a.get('expires_at'))
    return bool(a.get('binding')==approval_binding(value) and expires and now<expires and preview_ready(value,now))


def validate_preview_state(v):
    from .website_registry import validate_scope
    validate_scope(v['repository'],preview_target=v.get('preview_project'),site_id=v.get('site_id'))
    checks=v.get('tests',{})
    if not isinstance(checks,dict) or not set(checks)<=TEST_CLASSES:raise ValueError('Known independent test classes required')
    # SECRET_SCAN is a fixed enum label, not a credential field. Inspect its
    # result fields through the unchanged acquisition credential guard.
    safe({**v,'tests':[{'test_class':k,'result':result} for k,result in checks.items()]})
    identifier(v['proposal_id']);repository_name(v['repository']);sha(v['base_sha']);proposal_branch(v['branch'],v['proposal_id'])
    if v.get('head_sha') is not None:sha(v['head_sha'])
    if v.get('state') not in STATES or v.get('stale_state') not in STALE_STATES or v.get('owner_status') not in OWNER_STATES or v.get('build_state') not in RUN_STATES or v.get('test_state') not in RUN_STATES or v.get('production_impact')!='NONE':
        raise ValueError('Preview state outside contract')
    if not v.get('required_tests') or not set(v['required_tests'])<=TEST_CLASSES:raise ValueError('Required checks missing')
    if not stamp(v.get('created_at')) or not stamp(v.get('updated_at')):raise ValueError('Preview timestamps required')
    if len(str(v).encode())>262144:raise ValueError('Preview state exceeds bound')
    return v


def handoff_contract(value, now, *, authority_receipt, idempotency_key):
    """Interface only: no implementation can deploy from this module."""
    expiry=stamp(authority_receipt.get('expires_at'))
    if not approval_current(value,now) or value.get('owner_status')!='APPROVED' or not expiry or now>=expiry:
        raise ValueError('Fresh approval and separate authority required')
    if authority_receipt.get('head_sha')!=value['head_sha'] or authority_receipt.get('proposal_id')!=value['proposal_id'] or authority_receipt.get('proposal_revision')!=value['proposal_revision'] or authority_receipt.get('binding')!=approval_binding(value) or not authority_receipt.get('receipt_id') or authority_receipt.get('scope')!='PRODUCTION_EXECUTOR':
        raise ValueError('Exact scoped authority receipt required')
    if not re.fullmatch('[a-f0-9]{64}',idempotency_key):raise ValueError('Idempotency digest required')
    sha(value['rollback_base'])
    from .website_registry import site_for
    site=site_for(repository=value['repository'])
    return {'state':'READY_FOR_PRODUCTION_EXECUTOR','proposal_id':value['proposal_id'],'proposal_revision':value['proposal_revision'],
        'site_id':site['site_id'] if site else None,'repository':value['repository'],'preview_target':value['preview_project'],
        'head_sha':value['head_sha'],'base_sha':value['base_sha'],'binding':approval_binding(value),'approval':value['approval'],
        'authority_receipt':deepcopy(authority_receipt),'idempotency_key':idempotency_key,'rollback_reference':value['rollback_base'],
        'current_base_required':True,'conflict_free_required':True,'read_after_write_required':True,'execution_authorized':False}
