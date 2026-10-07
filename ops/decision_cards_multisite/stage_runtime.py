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
import urllib.request

ROOT = Path('/var/lib/optibrain/decision-cards-multisite/release-1.33.0')
HELPER = Path('/usr/local/lib/optibrain/phase18-19-stage-runtime.py')
BASE = '586ac2818fcc8166a40ed0f2fb5c8a0ac5708e0b'


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
    mode.add_argument('--prepare');mode.add_argument('--activate');args=parser.parse_args()
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
    h.require(release.get('sha')==sha and release.get('state')=='deployed' and release.get('api_version')=='1.33.0'
              and release.get('writers_enabled') is False, 'Exact guarded release receipt required')
    h.require(h.load(h.INTERNAL/'state.json')['effects']==prior['internal_effects']
              and h.load(h.CUSTOMER/'state.json')['effects']==prior['customer_effects'], 'Effect state changed; reconcile before resume')
    with urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=5) as response:
        h.require(response.status==200 and json.load(response).get('version')=='1.33.0','API version differs')
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
