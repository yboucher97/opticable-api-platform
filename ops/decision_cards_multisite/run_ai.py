#!/usr/bin/python3
"""One exact no-op AI preview; no production, content, DNS or communications port."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import tempfile

SOURCE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SOURCE/'apps/workflow-api'))
from workflow.automation.manager_store import ManagerStore
from workflow.automation.ads_intelligence import proposal,evidence
from workflow.automation.website_registry import LiveSiteScope,SITES
from workflow.automation.website_preview_ai_native import NativeAISiteRunner,BASE,REPO,PID,CHECKS
from workflow.automation.website_preview_model import RepositoryState,preparation_package
from workflow.automation.website_preview_runtime import prepare_local,reconcile
from workflow.automation.website_preview_git import LocalGitAdapter
from workflow.automation.website_preview_execution import BINDING_FIELDS,PreviewWriteBoundary,ProposalPreviewExecutor
from workflow.automation.website_preview_github_live import ExistingPreviewApp,GitHubPreviewAdapter
from workflow.automation.website_preview_cloudflare_safety import CloudflarePushSafety
from workflow.automation.website_preview_cloudflare_live import CloudflarePreviewAdapter,PreviewHTTP
from workflow.automation.website_preview_native import TOOLS,BROWSER,trusted_tool_file

ROOT=Path('/var/lib/optibrain/decision-cards-multisite')
DB=Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
TARGET=SITES['ai.opticable.ca']['preview_target']
SCOPE=LiveSiteScope('ai.opticable.ca',PID,1)


def released():
    receipt=json.loads(Path('/var/lib/optibrain/releases/current.json').read_text())
    if SOURCE!=Path('/opt/optibrain-releases')/SOURCE.parent.name/'source' or receipt.get('sha')!=SOURCE.parent.name or receipt.get('state')!='deployed' or receipt.get('api_version')!='1.33.0':
        raise PermissionError('Exact guarded 1.33.0 immutable release required')
    trusted_tool_file(Path(__file__))


def prepare(store):
    now=datetime.now(timezone.utc);record_file=ROOT/'ai-canonical-preparation.json'
    if record_file.exists():item=json.loads(record_file.read_text())
    else:
        r=proposal('LANDING_PAGE','AI loss prevention','FR',[evidence('WEBSITE','AI main / Pages deployment exact SHA '+BASE,now.isoformat())],now,
            {'target_url':'https://ai.opticable.ca/fr/'},problem='AI site preview capability has not been proven end-to-end.',
            change='Verify unchanged current AI source in one isolated non-production preview.')
        r.update(proposal_id=PID,proposal_type='SITE_PREVIEW_VERIFICATION',
            target_object={'system':'WEBSITE','entity_type':'WEBSITE_PAGE','entity_id':'https://ai.opticable.ca/fr/'},
            affected_files_or_records=[],rollback_reference=BASE,
            owner_action_required='Review no-op preview evidence; no website production change is proposed.',
            risk='Preview may fail to reproduce production behavior; production leads and analytics must remain disabled.',
            expected_benefit='Prove isolated review capability; no conversion benefit or content improvement is claimed.')
        item={'record':r,'detail':{'site_id':'ai.opticable.ca','repository':REPO,'base_sha':BASE,'no_op':True,
            'current_state':'Next.js static export on Cloudflare Pages at '+BASE,
            'provider_configuration_affected':'Only the separate '+TARGET+' target; zero production route/domain/DNS changes.',
            'indirect_changes':'Generated preview receives noindex, visible preview marker, disabled Forms and disabled GA. Source content remains identical.',
            'pros':['Independent review of exact current AI source','No marketing content change'],
            'cons':['Preview intentionally disables real submissions and analytics; native behavior is tested with intercepted fixtures.']}}
        record_file.write_text(json.dumps(item,ensure_ascii=False,indent=2)+'\n');record_file.chmod(0o600)
    store.record(item['record'],item['detail'])
    git=LocalGitAdapter(REPO,ROOT/'ai-source',ROOT/'ai-worktrees',expected_remote='https://github.com/'+REPO+'.git')
    runner=NativeAISiteRunner(git,store,source_root=SOURCE)
    package=preparation_package(store.website_proposal(PID),REPO,BASE,[],[],sorted(CHECKS),['docs/decision-cards-multisite/implementation.md'])
    site=SITES['ai.opticable.ca']
    repo=RepositoryState('github:'+REPO,'GITHUB',REPO,'main','main',last_observed_sha=BASE,
        last_fetch_at=now.isoformat(),preview_project=TARGET,health_state='COMPLETE',source_at=now.isoformat(),
        auth_mode='GITHUB_APP',site_id=site['site_id'],production_domain=site['production_domain'],
        production_target=site['production_target'],build_definition=site['build_definition'],test_definition=site['test_definition'],
        github_installation_access='VERIFIED_EXISTING_APP_REPOSITORY_RESTRICTED',cloudflare_access='VERIFIED_EXISTING_USER_AND_ACCOUNT_READ',
        production_deployment_model=site['production_deployment_model'],preview_deployment_model=site['preview_deployment_model'],
        last_production_sha=BASE,last_preview_state='PREPARING')
    store.repository_state(repo,now)
    result=prepare_local(store,git,runner,package,repo,now,slug='ai-no-op-preview')
    return store,git,runner,result


def execute(command):
    if os.geteuid()!=0:raise PermissionError('Manual root execution required')
    if command=='local-fixture':
        with tempfile.TemporaryDirectory(prefix='optibrain-ai-native-fixture-') as tmp:
            store,git,runner,result=prepare(ManagerStore(Path(tmp)/'fixture.db'))
            return {'state':result['state'],'native':runner._all(PID),'fixture_only':True,'canonical_database_changed':False,'provider_writes':0}
    released();store,git,runner,result=prepare(ManagerStore(DB))
    if command=='prepare':return {'state':result['state'],'provider_writes':0}
    now=datetime.now(timezone.utc);value=store.preview(PID,now);binding={k:value[k] for k in BINDING_FIELDS}
    safety=CloudflarePushSafety(binding['branch'],scope=SCOPE)
    github=GitHubPreviewAdapter(ExistingPreviewApp.from_secure_configuration(),store=store,local_git=git,deployment_safety=safety,scope=SCOPE)
    try:
        identity=github.verify_identity(for_write=True)
        boundary=PreviewWriteBoundary(**{k:v for k,v in binding.items() if k!='branch'},allowed_branch=binding['branch'],
            selected_repositories=tuple(identity['effective_repositories']),permissions=identity['effective_permissions'],
            verified_at=identity['observed_at'],free_plan_limit_accepted=True,non_main_deployment_safe=True,
            production_credentials_available=False,enabled=True)
        github.boundary=boundary
        safety.require_safe(binding)
        cloud=CloudflarePreviewAdapter(store=store,github=github,local_git=git,boundary=boundary,deployment_safety=safety,scope=SCOPE)
        if command=='provision':return cloud.provision(binding=binding)
        if command=='push':return ProposalPreviewExecutor(store,github,boundary,clock=lambda:datetime.now(timezone.utc)).push_proposal(binding,now)
        if command=='ci':return github.get_workflow_status(REPO,BASE).__dict__
        if command=='upload':
            build=runner._all(PID);return cloud.upload(binding,build['artifact_root'],build['artifact_sha256'])
        if command=='hosted-test':
            build=runner._all(PID);read=cloud.find_deployment_for_sha(TARGET,BASE)
            if read.state!='COMPLETE' or any(read.data.get(k)!=v for k,v in binding.items()):raise ValueError('Exact AI hosted tuple required')
            http=PreviewHTTP(cloud).get(read.data['url'])
            if http['body']!=(Path(build['artifact_root'])/'fr/index.html').read_text():raise ValueError('Hosted AI bytes differ')
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PLAYWRIGHT_BROWSERS_PATH':str(BROWSER),
                'OPTIBRAIN_PREVIEW_DIR':build['artifact_root'],'OPTIBRAIN_PREVIEW_URL':read.data['url']}
            log=ROOT/'ai-hosted-browser.log';runner._command(['/usr/bin/node',str(SOURCE/'ops/decision_cards_multisite/ai_browser_checks.cjs')],SOURCE,env,log)
            browser=json.loads(log.read_text().strip().splitlines()[-1])
            if not browser.get('passed'):raise ValueError('Hosted AI browser tests failed')
            return {**binding,'url':read.data['url'],'state':'PASS','browser':browser,'provider_writes':0}
        if command=='reconcile':
            proof=json.loads((ROOT/'ai-hosted-test.json').read_text())
            if proof['state']!='PASS' or any(proof.get(k)!=v for k,v in binding.items()):raise ValueError('Exact hosted tests required')
            return reconcile(store,github,cloud,PreviewHTTP(cloud),now,site_id='ai.opticable.ca',maximum=1,
                git=git,expected_page='Stoppez les pertes',canonical_url='https://ai.opticable.ca/fr/',clock=lambda:datetime.now(timezone.utc))
    finally:github.close()
    raise ValueError('Unknown operation')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['local-fixture','prepare','provision','push','ci','upload','hosted-test','reconcile'])
    args=parser.parse_args();result=execute(args.command)
    path=ROOT/('ai-'+args.command+'.json');path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)
    print(json.dumps({k:v for k,v in result.items() if k not in {'native','proposals'}},ensure_ascii=False))
