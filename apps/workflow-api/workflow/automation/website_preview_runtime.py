"""Explicit local orchestration and bounded reconciliation; no scheduler or deployer."""
from copy import deepcopy
from .website_preview_model import (preparation_package, new_preview, preview_ready, test_passes,
    approval_current, sha)
from .website_preview_providers import ReadResult, verify_deployment, validate_http
from .manager_sources import stamp


def _save(store,v,now,**changes):
    v.update(changes);v['updated_at']=now.isoformat();sequence=v.pop('sequence',None)
    v['sequence']=store.save_preview(v,expected_sequence=sequence)
    return v


def prepare_local(store,git,runner,package,repository,now,*,slug):
    item=store.website_proposal(package['proposal_id'])
    expected=preparation_package(item,package['repository'],package['base_sha'],package['allowed_files'],package['changes'],package['required_tests'],package['evidence_refs'])
    if expected!=package or repository.repository_full_name!=git.repository:raise ValueError('Canonical preparation package mismatch')
    old=store.preview(package['proposal_id'],now)
    if old and old['proposal_revision']==package['proposal_revision'] and old['semantic_hash']==package['semantic_hash'] and old.get('head_sha') and test_passes(old):
        local=git.read_worktree_state(package['proposal_id'])
        if local['head_sha']==old['head_sha'] and not local['dirty']:
            return {'state':'EXACT_REPLAY','preview':old,'expensive_work_skipped':True,'provider_writes':0}
    v=new_preview(package,repository,now,slug);_save(store,v,now,state='BRANCH_PENDING')
    try:
        git.create_proposal_branch(package,v['branch'],now);_save(store,v,now,state='BRANCH_CREATED')
        tree=git.create_proposal_worktree(package,v['branch'],now);_save(store,v,now,state='WORKTREE_CREATED',worktree_path=tree['path'])
        _save(store,v,now,state='PREPARING')
        head=git.commit_prepared_change(package,protected_scripts=runner.protected_scripts)
        _save(store,v,now,head_sha=head,state='BUILDING',build_state='RUNNING',stale_state='CURRENT')
        build=runner.run(v['proposal_id'],'BUILD')
        _save(store,v,now,build_result=build,build_state=build['state'])
        if build['state']=='FAIL':return {'state':_save(store,v,now,state='BUILD_FAILED')['state'],'preview':v,'provider_writes':0}
        _save(store,v,now,state='TESTING',test_state='RUNNING')
        for k in v['required_tests']:
            result=build if k=='BUILD' else runner.run(v['proposal_id'],k)
            v['tests'][k]=result;_save(store,v,now)
        failed=any(v['tests'][k]['state']!='PASS' for k in v['required_tests'])
        _save(store,v,now,state='TEST_FAILED' if failed else 'PREVIEW_PENDING',test_state='FAIL' if failed else 'PASS',preview_state='NOT_COLLECTED')
    except (ValueError,OSError,TimeoutError) as exc:
        _save(store,v,now,state='NOT_ELIGIBLE',preparation_error=str(exc)[:300])
        return {'state':'NOT_ELIGIBLE','preview':v,'provider_writes':0}
    return {'state':v['state'],'preview':v,'expensive_work_skipped':False,'provider_writes':0}


def _fresh(read,now):
    read.validate();at=stamp(read.source_at)
    return read.state in {'COMPLETE','VERIFIED_EMPTY'} and at and 0<=(now-at).total_seconds()<=3600


def _observed(operation,now,*args):
    try:
        read=operation(*args)
        if not isinstance(read,ReadResult):raise ValueError('Unexpected provider result')
        return read.validate()
    except PermissionError:
        return ReadResult('BLOCKED_AUTH',None,None,now.isoformat(),1,0,1,'PERMISSION_DENIED')
    except (ValueError,TypeError,KeyError,TimeoutError,OSError):
        return ReadResult('FAILED',None,None,now.isoformat(),1,0,1,'INVALID_OR_FAILED_PROVIDER_READ')


def reconcile(store,github,cloudflare,http,now,*,maximum=3,git=None,expected_page='Security cameras',canonical_url='https://opticable.ca/fr/services/systemes-cameras-securite/'):
    """Callable by the existing infrastructure later. Stop denied reads, never retry."""
    if type(maximum) is not int or not 1<=maximum<=3:raise ValueError('Reconciliation bound required')
    results=[]
    for item in store.rows():
        if item['record']['target_system']!='WEBSITE':continue
        v=store.preview(item['record']['proposal_id'],now)
        if not v or v['owner_status'] in {'REJECTED','DEFERRED','REVISION_REQUESTED'} or v['stale_state']=='SUPERSEDED':continue
        if len(results)>=maximum:break
        v=deepcopy(v);repo=v['repository'];reads=v.setdefault('provider_reads',{})
        default=_observed(github.get_branch,now,repo,v['base_ref']);reads['default_branch']=default.metadata()
        if not _fresh(default,now) or not isinstance(default.data,dict) or default.data.get('repository')!=repo or default.data.get('branch')!=v['base_ref']:
            v['last_verified_at']=None
            _save(store,v,now,state='PROVIDER_BLOCKED' if default.state=='BLOCKED_AUTH' else 'STALE_BASE',stale_state='UNKNOWN',preview_state='BLOCKED_AUTH' if default.state=='BLOCKED_AUTH' else 'NOT_COLLECTED')
            results.append(v);continue
        try:current=sha(default.data.get('sha'))
        except ValueError:
            _save(store,v,now,state='PROVIDER_BLOCKED',preview_state='FAILED',stale_state='UNKNOWN');results.append(v);continue
        if current!=v['base_sha']:
            stale='NEEDS_REBASE'
            if git:
                try:stale=git.compare_base(v['proposal_id'],current)
                except ValueError:pass # A not-yet-fetched object is never current.
            _save(store,v,now,stale_state=stale,state={'CONFLICTED':'CONFLICTED','SUPERSEDED':'SUPERSEDED'}.get(stale,'STALE_BASE'),preview_state='STALE',last_verified_at=None)
            results.append(v);continue
        v['stale_state']='CURRENT'
        head=_observed(github.get_branch,now,repo,v['branch']);reads['proposal_branch']=head.metadata()
        if not _fresh(head,now) or not isinstance(head.data,dict) or head.data.get('repository')!=repo or head.data.get('branch')!=v['branch']:
            _save(store,v,now,state='PROVIDER_BLOCKED' if head.state=='BLOCKED_AUTH' else 'PREVIEW_PENDING',preview_state='BLOCKED_AUTH' if head.state=='BLOCKED_AUTH' else 'NOT_COLLECTED',last_verified_at=None)
            results.append(v);continue
        if head.data.get('sha')!=v['head_sha']:
            _save(store,v,now,state='PREPARATION_ELIGIBLE',preview_state='STALE',build_state='NOT_RUN',test_state='NOT_RUN',tests={},build_result={},last_verified_at=None,owner_status='STALE_APPROVAL')
            results.append(v);continue
        # No unchanged-source rebuild, repeated clone or validation within a fresh receipt.
        if preview_ready(v,now):
            results.append({**v,'expensive_work_skipped':True});continue
        if not test_passes(v):
            _save(store,v,now,state='BUILD_FAILED' if v['build_state']=='FAIL' else 'TEST_FAILED' if v['test_state']=='FAIL' else 'PREPARATION_ELIGIBLE',last_verified_at=None)
            results.append(v);continue
        pr=_observed(github.get_pr,now,repo,v['branch']);reads['pull_request']=pr.metadata()
        workflow=_observed(github.get_workflow_status,now,repo,v['head_sha']);reads['workflow']=workflow.metadata()
        # Missing PR is an honest empty result; fake/local preparation does not require one.
        if pr.state=='COMPLETE':
            p=pr.data
            if not isinstance(p,dict) or p.get('repository')!=repo or p.get('head_sha')!=v['head_sha'] or p.get('branch')!=v['branch'] or p.get('base_ref')!=v['base_ref'] or p.get('draft') is not True or type(p.get('number')) is not int:
                _save(store,v,now,state='PROVIDER_BLOCKED',preview_state='FAILED',last_verified_at=None);results.append(v);continue
            v['pr_number']=p['number']
        if pr.state not in {'COMPLETE','VERIFIED_EMPTY'} or not _fresh(workflow,now):
            _save(store,v,now,state='PROVIDER_BLOCKED' if 'BLOCKED_AUTH' in {pr.state,workflow.state} else 'PREVIEW_PENDING',preview_state='BLOCKED_AUTH' if 'BLOCKED_AUTH' in {pr.state,workflow.state} else 'PARTIAL',last_verified_at=None)
            results.append(v);continue
        w=workflow.data
        if not isinstance(w,dict) or w.get('repository')!=repo or w.get('head_sha')!=v['head_sha'] or w.get('branch')!=v['branch'] or not all(w.get('checks',{}).get(k)=='PASS' for k in v['required_tests']):
            _save(store,v,now,state='PREVIEW_PENDING',preview_state='PARTIAL',last_verified_at=None);results.append(v);continue
        project=_observed(cloudflare.get_project,now,v['preview_project']);reads['cloudflare_project']=project.metadata()
        config=_observed(cloudflare.get_preview_configuration,now,v['preview_project']);reads['cloudflare_configuration']=config.metadata()
        if not _fresh(project,now) or not _fresh(config,now):
            blocked='BLOCKED_AUTH' in {project.state,config.state}
            reads['cloudflare']=config.metadata() if config.state=='BLOCKED_AUTH' else project.metadata()
            _save(store,v,now,state='PROVIDER_BLOCKED' if blocked else 'PREVIEW_PENDING',preview_state='BLOCKED_AUTH' if blocked else 'NOT_COLLECTED',last_verified_at=None)
            results.append(v);continue
        if not isinstance(project.data,dict) or project.data.get('project')!=v['preview_project'] or not isinstance(config.data,dict) or config.data.get('project')!=v['preview_project'] or config.data.get('environment')!='preview' or config.data.get('isolated') is not True or config.data.get('production_routes') is not False:
            _save(store,v,now,state='PROVIDER_BLOCKED',preview_state='FAILED',last_verified_at=None);results.append(v);continue
        deployment=_observed(cloudflare.find_deployment_for_sha,now,v['preview_project'],v['head_sha']);reads['cloudflare']=deployment.metadata()
        if not _fresh(deployment,now):
            _save(store,v,now,state='PROVIDER_BLOCKED' if deployment.state=='BLOCKED_AUTH' else 'PREVIEW_PENDING',preview_state=deployment.state,last_verified_at=None)
            results.append(v);continue
        if deployment.state=='VERIFIED_EMPTY':
            _save(store,v,now,state='PREVIEW_PENDING',preview_state='VERIFIED_EMPTY',last_verified_at=None);results.append(v);continue
        try:
            d=verify_deployment(v,deployment.data,now)
            if d['state']!='success':
                _save(store,v,now,state='PREVIEW_PENDING' if d['state']=='building' else 'PROVIDER_BLOCKED',preview_state='PREVIEW_PENDING' if d['state']=='building' else 'FAILED',last_verified_at=None)
                results.append(v);continue
            readback=_observed(cloudflare.read_deployment,now,v['preview_project'],d['id']);reads['deployment_readback']=readback.metadata()
            if not _fresh(readback,now):
                _save(store,v,now,state='PROVIDER_BLOCKED' if readback.state=='BLOCKED_AUTH' else 'PREVIEW_PENDING',preview_state=readback.state,last_verified_at=None)
                results.append(v);continue
            if verify_deployment(v,readback.data,now)!=d:raise ValueError('Deployment changed during verification')
            cloudflare.validate_preview_url(d['url']);v.update(deployment=d,preview_deployment_id=d['id'],preview_url=d['url'])
            h=validate_http(v,cloudflare,http,now,expected_page=expected_page,canonical_url=canonical_url,require_forms='FORMS' in v['required_tests'])
            _save(store,v,now,state='OWNER_REVIEW',preview_state='PREVIEW_READY',http_validation=h,last_verified_at=now.isoformat())
        except (ValueError,KeyError,TypeError,TimeoutError) as exc:
            _save(store,v,now,state='PROVIDER_BLOCKED',preview_state='FAILED',preview_error=str(exc)[:300],last_verified_at=None)
        results.append(v)
    return {'state':'RECONCILED','proposals':results,'provider_writes':0,'scheduler_installed':False}


def owner_package(item,value,now):
    r=item['record']
    return {'WHY':r['business_problem'],'EVIDENCE':r['source_evidence']+value['evidence_refs'],
        'CURRENT':{'page':r['target_url_or_record'],'repository':value['repository'],'base_sha':value['base_sha']},
        'PROPOSED':{'change':r['recommended_change'],'proposal_id':value['proposal_id'],'revision':value['proposal_revision'],'head_sha':value['head_sha']},
        'PREVIEW':{'state':value['preview_state'],'url':value.get('preview_url') if preview_ready(value,now) else None,'provider_reads':value['provider_reads']},
        'TESTS':{'build':value.get('build_result'), 'required':value['required_tests'],'results':value['tests']},
        'RISK':r['risk'],'APPROVAL STATUS':value['owner_status'],'production_action':False}


def manager_projection(item,value,now):
    if not value:return {'state':'NOT_ELIGIBLE','preview_state':'NOT_COLLECTED','owner_status':'PENDING','message':'No preview prepared','verified_url':None}
    ready=preview_ready(value,now);approved=approval_current(value,now) and value['owner_status']=='APPROVED'
    state=value['state']
    if value['owner_status']=='STALE_APPROVAL':state='STALE_APPROVAL'
    if value['preview_state']=='PREVIEW_READY' and not ready and state not in {'STALE_BASE','CONFLICTED','SUPERSEDED','STALE_APPROVAL'}:state='STALE_PREVIEW'
    return {**{k:value.get(k) for k in ('repository','base_sha','head_sha','branch','build_state','test_state','preview_state','stale_state','owner_status','proposal_revision')},
        'state':state,'verified_url':value.get('preview_url') if ready else None,'provider_blocked':value['preview_state']=='BLOCKED_AUTH',
        'approval_bound':approved,'execution_authorized':False,'review_package':owner_package(item,value,now)}


def priority_action(projected):
    if projected.get('owner_status') in {'REJECTED','DEFERRED','APPROVED'}:return None
    if projected.get('owner_status')=='REVISION_REQUESTED':return 'REVISION REQUESTED'
    if projected.get('provider_blocked'):return 'PROVIDER ACCESS REQUIRED'
    if projected.get('stale_state') in {'NEEDS_REBASE','CONFLICTED','SUPERSEDED'} or projected.get('state') in {'STALE_PREVIEW','STALE_APPROVAL'}:return 'STALE PREVIEW'
    if projected.get('verified_url'):return 'REVIEW PREVIEW'
    return None
