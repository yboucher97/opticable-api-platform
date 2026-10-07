#!/usr/bin/python3
"""Reviewed release transaction preserving existing active internal authority and closed customer policy.

Snapshot before --stop internal, then prepare/activate after guarded deployment.
Never initializes business state, renews authorization or starts a timer.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import grp
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import urllib.request

ROOT = Path('/var/lib/optibrain/learning-audit/release-1.34.1')
HELPER = Path('/usr/local/lib/optibrain/phase18-19-stage-runtime.py')
BASE = '586ac2818fcc8166a40ed0f2fb5c8a0ac5708e0b'


def audit_release(h, sha, *, finish=False):
    """The manual guarded API release has the same durable before/readback contract."""
    h.require(len(sha)==40 and all(c in '0123456789abcdef' for c in sha), 'Exact release SHA required')
    h.closed();h.idle_units()
    authorization=h.load(Path('/etc/optibrain/manual-release-authorization.json'))
    h.require(authorization.get('candidate_sha')==sha and h.timestamp(authorization['expires_at'])>datetime.now(timezone.utc),
              'Exact current manual release authorization required')
    validation=h.load(ROOT/'release-validation.json')
    h.require(validation.get('passed') is True and validation.get('tests',0)>=1700
              and all(validation.get(k)==0 for k in ('failures','errors','skipped','blocked_network_attempts')), 'Full gate required')
    root=h.RELEASES/sha;h.venv_ready(root)
    _,files=h.archive_files(sha);source=h.source_tree(root,files)
    expected={str(p.relative_to(source)):h.digest(h.trusted(p)) for p in (source/'apps/workflow-api/workflow').rglob('*.py')}
    h.require(validation['workflow_source_hashes']==expected,'Audit executable source differs from full gate')
    sys.path.insert(0,str(source/'apps/workflow-api'))
    from workflow.automation.action_evidence import ActionEvidence,envelope,approval_binding
    audit=ActionEvidence('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
    now=datetime.now(timezone.utc);action_id='deployment:'+sha
    receipt=h.load(h.RECEIPT)
    if finish:
        head=h.command([*h.GIT,'rev-parse','HEAD']).strip()
        with urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=5) as response:health=json.load(response)
        verified=head==sha and receipt.get('sha')==sha and receipt.get('state')=='deployed' and health.get('version')=='1.34.1'
        success=audit.finish(action_id,now,provider_success=receipt.get('state')=='deployed' and receipt.get('sha')==sha,
            actual_after={'release_receipt':receipt,'git_sha':head,'health':health},verified=verified,
            response={'release_receipt':str(h.RECEIPT)},
            failure=None if verified else {'stage':'EXACT_SHA_API_RELEASE','error_class':'ReleaseNotVerified',
                'provider_status':None,'safe_details':'Deployment failed or readback disagrees; preserve original and rollback receipts.',
                'partial_effects':'UNKNOWN','recovery_action':'Use guarded rollback result and reconcile code/config/venv.'})
        print(json.dumps({'action_id':action_id,'verified':success}));return
    h.require(receipt.get('sha')==authorization['baseline_sha'],'Pre-release baseline differs')
    before={'release_receipt':receipt,'git_sha':h.command([*h.GIT,'rev-parse','HEAD']).strip()}
    plan=envelope(action_id,'EXACT_SHA_API_RELEASE',{'type':'DEPLOYMENT','identity':'opticable-workflow-api'},now,
        provider='LOCAL_SYSTEMD_GIT',trigger='OWNER_AUTHORIZED_CAPABILITY_MISSION',mutation=True,approval_required=True,
        authority_class='ROOT_MANUAL_EXACT_SHA_RELEASE',before_state=before,proposed_state={'sha':sha,'api_version':'1.34.1'},
        reason='Release the reviewed universal audit and learning capability through the existing guarded release gate.',
        exact_versions={'environment':'production','production_version':authorization['baseline_sha'],'proposed_version':sha,
            'test_evidence':str(ROOT/'release-validation.json'),'preview_evidence':str(ROOT/'candidate-summary.json'),
            'ci_run_id':authorization['ci_run_id']},
        evidence_refs=[str(ROOT/'release-validation.json'),str(ROOT/'candidate-summary.json')],
        rollback_capability='REVERSIBLE_WITH_LIMITATIONS',
        rollback_target={'sha':authorization['baseline_sha'],'archive':authorization['backup_archive'],'sha256':authorization['backup_sha256']},
        rollback_procedure='Guarded gate restores previous Git SHA, manifest, env and immutable venv; restart and verify API. Preserve newer journals, credentials and effect claims.',
        known_downside='Brief API restart; additive audit history remains after code rollback.',
        provider_request={'command':'/usr/local/sbin/opticable-api-deploy-root','exact_sha':sha})
    audit.plan(plan,now);audit.approve(action_id,'OWNER_MISSION_EXACT_SHA_ROOT_RELEASE_REVIEW',now,
        binding=approval_binding(plan),expires_at=authorization['expires_at'])
    audit.start(action_id,now,authority_check=h.closed)
    print(json.dumps({'action_id':action_id,'state':'STARTED','rollback_known':True}))


def preserved(prior, source, helper):
    """Pure transformation: refresh reviewed code pins; preserve all authority."""
    internal = deepcopy(prior['internal_policy']);customer = deepcopy(prior['customer_policy'])
    activation = deepcopy(prior['internal_activation'])
    helper.require(set(internal['lifecycle']['real_scopes']) == helper.INTERNAL_SCOPES, 'Existing internal scope inventory differs')
    helper.require(internal['lifecycle']['enabled'] is True,
                   'Only previously enabled internal authority can resume')
    helper.require(customer['external_enabled'] is False and customer['test_enabled'] is False
                   and not customer['test_scopes'], 'Customer authority must remain closed')
    helper.require(not internal['lifecycle']['test_scopes'], 'TEST authority must remain off')
    policy = internal['lifecycle']
    helper.require(set(policy['source_hashes']) == helper.INTERNAL_SOURCES, 'Prior code pin inventory differs')
    policy['source_hashes'] = {name:helper.digest(helper.trusted(source/'apps/workflow-api/workflow'/name))
                             for name in helper.INTERNAL_SOURCES}
    activation['release_sha'] = source.parent.name
    return internal, customer, activation


def main():
    # Reuse the already reviewed bounded archive/ownership/install primitives.
    # Verify their bytes against the prior exact Git release before importing.
    if os.geteuid()!=0:raise ValueError('Manual root staging required')
    baseline=Path('/opt/optibrain-releases')/BASE/'source/ops/phase18_19/stage_runtime.py'
    for leaf in (HELPER,baseline):
        for parent in leaf.parents:
            info=parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
                raise ValueError('Untrusted prior helper path')
        info=leaf.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
            raise ValueError('Untrusted prior helper source')
    expected = baseline.read_bytes()
    if hashlib.sha256(HELPER.read_bytes()).digest() != hashlib.sha256(expected).digest():
        raise ValueError('Prior root staging helper differs from reviewed baseline')
    spec = importlib.util.spec_from_file_location('reviewed_stage',HELPER);h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    h.trusted(HELPER);h.EVIDENCE=ROOT
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--snapshot',action='store_true');mode.add_argument('--stop',choices=['internal'])
    mode.add_argument('--prepare');mode.add_argument('--activate')
    mode.add_argument('--audit-start');mode.add_argument('--audit-finish');args=parser.parse_args()
    snapshot_path=ROOT/'policies-before-deploy.json'
    if args.snapshot:
        prior={'internal_policy':h.load(h.INTERNAL_POLICY),'customer_policy':h.load(h.CUSTOMER_POLICY),
               'internal_activation':h.load(h.INTERNAL/'activation.json'),'at':datetime.now(timezone.utc).isoformat()}
        h.require(not (h.INTERNAL/'HOLD.json').exists(), 'Internal HOLD requires reconciliation')
        h.require(not h.load(h.CUSTOMER/'state.json')['holds'], 'Customer HOLD requires reconciliation')
        prior['internal_effects']=h.load(h.INTERNAL/'state.json')['effects']
        prior['customer_effects']=h.load(h.CUSTOMER/'state.json')['effects']
        prior['timers']={name:h.command(['/usr/bin/systemctl','show',name,'-p','ActiveState','-p','UnitFileState'])
                         for name in ('opticable-lifecycle-internal.timer','opticable-customer-communications.timer')}
        h.require('ActiveState=active' in prior['timers']['opticable-lifecycle-internal.timer']
                  and 'UnitFileState=enabled' in prior['timers']['opticable-lifecycle-internal.timer'], 'Expected active original timer')
        h.require('ActiveState=inactive' in prior['timers']['opticable-customer-communications.timer']
                  and 'UnitFileState=disabled' in prior['timers']['opticable-customer-communications.timer'], 'Customer timer must remain disabled')
        h.atomic(snapshot_path,prior,immutable=True);print(json.dumps({'state':'SNAPSHOT_ONLY','provider_writes':0}));return
    if args.stop:print(json.dumps(h.stop(args.stop)));return
    if args.audit_start or args.audit_finish:
        audit_release(h,args.audit_start or args.audit_finish,finish=bool(args.audit_finish));return
    if args.prepare:print(json.dumps(h.prepare(args.prepare)));return
    sha=args.activate;h.exact_head(sha);h.closed();h.idle_units();source,prepared=h.manifest_matches(sha)
    prior=h.load(snapshot_path);internal,customer,activation=preserved(prior,source,h)
    now=datetime.now(timezone.utc)
    h.require(h.timestamp(internal['lifecycle']['expires_at'])>now,
              'Renewal is a separate deliberate decision, never implicit in deployment')
    h.require(h.load(h.INTERNAL/'activation.json') == prior['internal_activation'],
              'Original activation changed after snapshot')
    h.require(h.load(h.CUSTOMER_POLICY) == prior['customer_policy'], 'Closed customer policy changed')
    conversion=h.load(Path('/etc/optibrain/conversion-export-control.json'))
    h.require(conversion.get('enabled') is False and all(d.get('local_enabled') is False and not d.get('allowed_event_keys') for d in conversion['destinations'].values()), 'Conversion export must remain OFF')
    validation=h.load(ROOT/'release-validation.json')
    h.require(validation.get('passed') is True and validation.get('tests',0)>=1700
              and all(validation.get(k)==0 for k in ('failures','errors','skipped','blocked_network_attempts')), 'Full release gate required')
    expected={str(p.relative_to(source)):h.digest(h.trusted(p)) for p in (source/'apps/workflow-api/workflow').rglob('*.py')}
    h.require(validation.get('workflow_source_hashes')==expected, 'Final executable sources differ from full gate')
    h.require(validation.get('runtime_sampler_sha256')==h.digest(h.trusted(source/'ops/phase14/runtime_snapshot.py')), 'Timer sampler differs from full gate')
    release=h.load(h.RECEIPT)
    h.require(release.get('sha')==sha and release.get('state')=='deployed' and release.get('api_version')=='1.34.1'
              and release.get('writers_enabled') is False, 'Exact guarded release receipt required')
    h.require(h.load(h.INTERNAL/'state.json')['effects']==prior['internal_effects']
              and h.load(h.CUSTOMER/'state.json')['effects']==prior['customer_effects'], 'Effect state changed; reconcile before resume')
    with urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=5) as response:
        h.require(response.status==200 and json.load(response).get('version')=='1.34.1','API version differs')
    path=ROOT/('runtime-activation-'+sha+'.json');h.require(not path.exists(),'Activation already exists; review, never reset')
    receipt={'schema':1,'state':'ARMED_TIMERS_OFF_PENDING_DRY_RUN_REVIEW','sha':sha,'at':now.isoformat(),
        'internal_scopes':activation['scopes'],'customer_scopes':[],'customer_authority':'CLOSED',
        'internal_cutoff':activation['activated_at'],'internal_expires_at':internal['lifecycle']['expires_at'],
        'customer_cutoff':customer['activated_at'],'customer_expires_at':customer['expires_at'],
        'authority_renewed':False,'scopes_added':0,'effects_reset':False,'timers_started':0,'provider_writes':0,
        'snapshot_sha256':h.digest(h.trusted(snapshot_path)),
        'dry_run_commands':['/usr/bin/python3 -I -B '+str(p)+' --dry-run' for p in h.LAUNCHERS.values()]}
    h.atomic(ROOT/('runtime-activation-intent-'+sha+'.json'),receipt,immutable=True)
    try:
        h.atomic(h.INTERNAL/'activation.json',activation)
        h.atomic(h.INTERNAL_POLICY,internal,mode=0o640,gid=grp.getgrnam('opticable-workflow-api').gr_gid)
        h.idle_units();h.atomic(path,receipt,immutable=True)
    except Exception:
        internal['lifecycle']['enabled']=False;internal['lifecycle']['real_scopes']=[]
        h.atomic(h.INTERNAL_POLICY,internal,mode=0o640,gid=grp.getgrnam('opticable-workflow-api').gr_gid)
        raise
    print(json.dumps(receipt))


if __name__=='__main__':main()
