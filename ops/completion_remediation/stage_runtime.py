#!/usr/bin/python3
"""Reviewed release transaction preserving existing Phase17–19 authorizations.

Snapshot before --stop both, then prepare/activate after guarded deployment.
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
import urllib.request

ROOT = Path('/var/lib/optibrain/completion-remediation-1-2')
HELPER = Path('/usr/local/lib/optibrain/phase18-19-stage-runtime.py')
BASE = '586ac2818fcc8166a40ed0f2fb5c8a0ac5708e0b'


def preserved(prior, source, helper):
    """Pure transformation: refresh reviewed code pins; preserve all authority."""
    internal = deepcopy(prior['internal_policy']);customer = deepcopy(prior['customer_policy'])
    activation = deepcopy(prior['internal_activation'])
    helper.require(set(internal['lifecycle']['real_scopes']) == helper.INTERNAL_SCOPES, 'Existing internal scope inventory differs')
    helper.require(set(customer['real_scopes']) == helper.CUSTOMER_SCOPES, 'Existing customer scope inventory differs')
    helper.require(internal['lifecycle']['enabled'] is True and customer['external_enabled'] is True,
                   'Only previously enabled authority can resume')
    helper.require(not internal['lifecycle']['test_scopes'] and customer['test_enabled'] is False
                   and not customer['test_scopes'], 'TEST authority must remain off')
    for policy, names in ((internal['lifecycle'], helper.INTERNAL_SOURCES),(customer, helper.CUSTOMER_SOURCES)):
        helper.require(set(policy['source_hashes']) == names, 'Prior code pin inventory differs')
        policy['source_hashes'] = {name:helper.digest(helper.trusted(source/'apps/workflow-api/workflow'/name)) for name in names}
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
    mode.add_argument('--snapshot',action='store_true');mode.add_argument('--stop',choices=['both'])
    mode.add_argument('--prepare');mode.add_argument('--activate');args=parser.parse_args()
    snapshot_path=ROOT/'policies-before-deploy.json'
    if args.snapshot:
        prior={'internal_policy':h.load(h.INTERNAL_POLICY),'customer_policy':h.load(h.CUSTOMER_POLICY),
               'internal_activation':h.load(h.INTERNAL/'activation.json'),'at':datetime.now(timezone.utc).isoformat()}
        h.require(not (h.INTERNAL/'HOLD.json').exists(), 'Internal HOLD requires reconciliation')
        h.require(not h.load(h.CUSTOMER/'state.json')['holds'], 'Customer HOLD requires reconciliation')
        prior['internal_effects']=h.load(h.INTERNAL/'state.json')['effects']
        prior['customer_effects']=h.load(h.CUSTOMER/'state.json')['effects']
        h.atomic(snapshot_path,prior,immutable=True);print(json.dumps({'state':'SNAPSHOT_ONLY','provider_writes':0}));return
    if args.stop:print(json.dumps(h.stop(args.stop)));return
    if args.prepare:print(json.dumps(h.prepare(args.prepare)));return
    sha=args.activate;h.exact_head(sha);h.closed();h.idle_units();source,prepared=h.manifest_matches(sha)
    prior=h.load(snapshot_path);internal,customer,activation=preserved(prior,source,h)
    now=datetime.now(timezone.utc)
    h.require(h.timestamp(internal['lifecycle']['expires_at'])>now and h.timestamp(customer['expires_at'])>now,
              'Renewal is a separate deliberate decision, never implicit in deployment')
    for filename,phase in [('R1_CHECKPOINT.json','r1')]:
        h.require(h.load(ROOT/filename).get('gate')=='PASS', 'Combined phase gate must pass')
    phase29=h.load(ROOT/'R2_CHECKPOINT.json')
    h.require(phase29.get('engineering_safe_to_deploy') is True and phase29.get('cold_outbound_enabled') is False, 'Acquisition recommendation release requires explicit safe engineering checkpoint')
    validation=h.load(ROOT/'release-validation.json')
    h.require(validation.get('passed') is True and validation.get('tests',0)>=1324
              and all(validation.get(k)==0 for k in ('failures','errors','skipped','blocked_network_attempts')), 'Full release gate required')
    expected={str(p.relative_to(source)):h.digest(h.trusted(p)) for p in (source/'apps/workflow-api/workflow').rglob('*.py')}
    h.require(validation.get('workflow_source_hashes')==expected, 'Final executable sources differ from full gate')
    release=h.load(h.RECEIPT)
    h.require(release.get('sha')==sha and release.get('state')=='deployed' and release.get('api_version')=='1.20.0'
              and release.get('writers_enabled') is False, 'Exact guarded release receipt required')
    h.require(h.load(h.INTERNAL/'state.json')['effects']==prior['internal_effects']
              and h.load(h.CUSTOMER/'state.json')['effects']==prior['customer_effects'], 'Effect state changed; reconcile before resume')
    with urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=5) as response:
        h.require(response.status==200 and json.load(response).get('version')=='1.20.0','API version differs')
    path=ROOT/('runtime-activation-'+sha+'.json');h.require(not path.exists(),'Activation already exists; review, never reset')
    receipt={'schema':1,'state':'ARMED_TIMERS_OFF_PENDING_DRY_RUN_REVIEW','sha':sha,'at':now.isoformat(),
        'internal_scopes':activation['scopes'],'customer_scopes':customer['real_scopes'],
        'internal_cutoff':activation['activated_at'],'internal_expires_at':internal['lifecycle']['expires_at'],
        'customer_cutoff':customer['activated_at'],'customer_expires_at':customer['expires_at'],
        'authority_renewed':False,'scopes_added':0,'effects_reset':False,'timers_started':0,'provider_writes':0,
        'snapshot_sha256':h.digest(h.trusted(snapshot_path)),
        'dry_run_commands':['/usr/bin/python3 -I -B '+str(p)+' --dry-run' for p in h.LAUNCHERS.values()]}
    h.atomic(ROOT/('runtime-activation-intent-'+sha+'.json'),receipt,immutable=True)
    try:
        h.atomic(h.INTERNAL/'activation.json',activation)
        h.atomic(h.INTERNAL_POLICY,internal,mode=0o640,gid=grp.getgrnam('opticable-workflow-api').gr_gid)
        h.atomic(h.CUSTOMER_POLICY,customer);h.idle_units();h.atomic(path,receipt,immutable=True)
    except Exception:
        internal['lifecycle']['enabled']=False;internal['lifecycle']['real_scopes']=[]
        h.atomic(h.INTERNAL_POLICY,internal,mode=0o640,gid=grp.getgrnam('opticable-workflow-api').gr_gid)
        h.atomic(h.CUSTOMER_POLICY,{**customer,'external_enabled':False,'test_enabled':False});raise
    print(json.dumps(receipt))


if __name__=='__main__':main()
