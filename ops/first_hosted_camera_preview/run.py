#!/usr/bin/python3
"""Manual, bounded first-camera execution through the preview control plane.

No timer, generic repository/ref, arbitrary command, merge or production port.
Provider writes require this source to be the current guarded API release.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'apps/workflow-api'))
from workflow.automation.manager_store import ManagerStore
from workflow.automation.website_preview_model import RepositoryState, preparation_package
from workflow.automation.website_preview_runtime import prepare_local, reconcile
from workflow.automation.website_preview_execution import BINDING_FIELDS, PERMISSIONS, REQUIRED_TESTS, PreviewWriteBoundary, ProposalPreviewExecutor
from workflow.automation.website_preview_git import LocalGitAdapter
from workflow.automation.website_preview_github_live import ExistingPreviewApp, GitHubPreviewAdapter, PROPOSAL_ID, REPOSITORY
from workflow.automation.website_preview_cloudflare_safety import CloudflarePushSafety, PREVIEW_WORKER
from workflow.automation.website_preview_cloudflare_live import CloudflarePreviewAdapter, PreviewHTTP
from workflow.automation.website_preview_native import NativeWebsiteRunner, content_proposal, BASE, TOOLS, BROWSER, trusted_tool_file

ROOT=Path('/var/lib/optibrain/first-hosted-camera-preview')
DB=Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
CLONE=Path('/home/optibrain/remediation-main-site')
TREES=Path('/home/optibrain/worktrees/opticable-camera-preview-live')
SLUG='camera-cta-fr-live'

def local(store):
    git=LocalGitAdapter(REPOSITORY,CLONE,TREES,
        expected_remote='git@github-opticable-website:yboucher97/opticable-website.git',
        production_paths=('/home/optibrain/worktrees/opticable-website-preview',))
    return git,NativeWebsiteRunner(git,store,source_root=SOURCE)

def released():
    receipt=json.loads((Path('/var/lib/optibrain/releases/current.json')).read_text())
    head=SOURCE.parent.name
    if receipt.get('sha')!=head or receipt.get('state')!='deployed' or receipt.get('api_version') not in {'1.32.1','1.33.0'}:
        raise PermissionError('Exact guarded preview-capable release required before provider execution')
    if SOURCE != Path('/opt/optibrain-releases')/head/'source':
        raise PermissionError('Provider execution must use root-owned immutable release source')
    trusted_tool_file(Path(__file__))

def execute(command):
    if os.geteuid()!=0:raise PermissionError('Manual root execution required')
    now=datetime.now(timezone.utc);store=ManagerStore(DB);git,runner=local(store)
    if command=='prepare':
        if git.read_repo_state()['default_sha']!=BASE:raise ValueError('Current fetched local main required')
        item=store.website_proposal(PROPOSAL_ID)
        package=preparation_package(item,REPOSITORY,BASE,['sitegen.py'],[content_proposal(git)],
            sorted(REQUIRED_TESTS|{'LINT'}),['docs/first-hosted-camera-preview/owner-configuration.md'])
        repo=RepositoryState('github:'+REPOSITORY,'GITHUB',REPOSITORY,'main','main',
            last_observed_sha=BASE,last_fetch_at=now.isoformat(),local_clone_path=str(CLONE),
            auth_mode='GITHUB_APP',preview_project=PREVIEW_WORKER,health_state='COMPLETE',source_at=now.isoformat())
        store.repository_state(repo,now)
        result=prepare_local(store,git,runner,package,repo,now,slug=SLUG)
        value=store.preview(PROPOSAL_ID,now)
        return {'state':result['state'],'binding':{k:value[k] for k in BINDING_FIELDS},
            'build':value['build_state'],'tests':value['test_state'],'error':value.get('preparation_error'),
            'build_result':value.get('build_result'),'worktree':value.get('worktree_path'),'provider_writes':0}
    released()
    value=store.preview(PROPOSAL_ID,now);binding={k:value[k] for k in BINDING_FIELDS}
    safety=CloudflarePushSafety(binding['branch'])
    github=GitHubPreviewAdapter(ExistingPreviewApp.from_secure_configuration(),store=store,local_git=git,
        deployment_safety=safety)
    try:
        identity=github.verify_identity(for_write=True)
        boundary=PreviewWriteBoundary(**{k:v for k,v in binding.items() if k!='branch'},
            allowed_branch=binding['branch'],selected_repositories=tuple(identity['effective_repositories']),
            permissions=identity['effective_permissions'],verified_at=identity['observed_at'],
            free_plan_limit_accepted=True,non_main_deployment_safe=True,
            production_credentials_available=False,enabled=True)
        github.boundary=boundary
        safety.require_safe(binding)
        cloud=CloudflarePreviewAdapter(store=store,github=github,local_git=git,boundary=boundary,deployment_safety=safety)
        if command=='verify':return {'identity':identity,'builds_safety':safety.last_receipt,'target':cloud.get_project(PREVIEW_WORKER).__dict__,'provider_writes':0}
        if command=='provision':return cloud.provision(binding=binding)
        executor=ProposalPreviewExecutor(store,github,boundary,clock=lambda:datetime.now(timezone.utc))
        if command=='push':return executor.push_proposal(binding,now)
        if command=='draft':return executor.create_draft_pr(binding,now)
        if command=='ci':return github.get_workflow_status(REPOSITORY,binding['head_sha']).__dict__
        if command=='upload':
            build=runner._all(PROPOSAL_ID)
            return cloud.upload(binding,build['artifact_root'],build['artifact_sha256'])
        if command=='hosted-test':
            build=runner._all(PROPOSAL_ID);read=cloud.find_deployment_for_sha(PREVIEW_WORKER,binding['head_sha'])
            if read.state!='COMPLETE' or any(read.data.get(k)!=v for k,v in binding.items()):raise ValueError('Exact hosted tuple required')
            url=cloud.validate_preview_url(read.data['url']);http=PreviewHTTP(cloud).get(url)
            artifact=Path(build['artifact_root'])
            if http['body']!=(artifact/'fr/services/systemes-cameras-securite/index.html').read_text():raise ValueError('Hosted page differs from tested artifact')
            if http['manifest']!=json.loads((artifact/'preview-evidence.json').read_text()):raise ValueError('Hosted manifest differs')
            log=ROOT/'hosted-browser-checks.log'
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PLAYWRIGHT_BROWSERS_PATH':str(BROWSER),
                'OPTIBRAIN_PREVIEW_DIR':str(artifact),'OPTIBRAIN_PREVIEW_URL':url}
            runner._command(['/usr/bin/node',str(SOURCE/'ops/first_hosted_camera_preview/browser_checks.cjs')],SOURCE,env,log)
            result=json.loads(log.read_text().strip().splitlines()[-1])
            if result.get('passed') is not True or result.get('hosted') is not True:raise ValueError('Hosted browser validation failed')
            return {**binding,'url':url,'version':read.data['id'],'http':200,'browser':result,'state':'PASS','provider_writes':0}
        if command=='reconcile':
            proof=json.loads((ROOT/'execution-hosted-test.json').read_text())
            if proof.get('state')!='PASS' or any(proof.get(k)!=v for k,v in binding.items()):raise ValueError('Hosted exact-head tests required')
            return reconcile(store,github,cloud,PreviewHTTP(cloud),now,maximum=1,site_id='opticable.ca',git=git,expected_page='Caméras IP pour commerces et entrepôts',clock=lambda:datetime.now(timezone.utc))
        raise ValueError('Unapproved operation')
    finally:github.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','verify','provision','push','draft','ci','upload','hosted-test','reconcile'])
    args=parser.parse_args();result=execute(args.command)
    ROOT.mkdir(mode=0o700,exist_ok=True);path=ROOT/('execution-'+args.command+'.json')
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');os.chmod(path,0o600)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
