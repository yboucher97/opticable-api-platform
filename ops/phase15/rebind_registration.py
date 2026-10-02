#!/usr/bin/env python3
"""Rebind read-only operator registration on a marked recovery target, never live production."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def rebind(root, sha):
    if (os.geteuid()!=0 or not re.fullmatch('[0-9a-f]{40}',sha)
            or not root.is_absolute() or root!=root.resolve()
            or not (root/'etc/optibrain-rebuild-target').is_file()):
        raise ValueError('Explicit marked recovery target and exact source required')
    repo=root/'opt/opticable-api-platform'
    actual=subprocess.check_output(['git','-c','safe.directory='+str(repo),'-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    if actual!=sha:raise ValueError('Recovery source differs from requested SHA')
    app=repo/'apps/workflow-api'
    tree=ast.parse((app/'workflow/phase7_registration.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_PINNED_SOURCES' for t in n.targets))
    sources=ast.literal_eval(node.value.args[0])
    if any(not p.startswith('workflow/') or '..' in Path(p).parts for p in sources):raise ValueError('Unsafe source set')
    p=root/'etc/optibrain/phase7-canary-registration.json'
    value=json.loads(p.read_text());value['candidate_sha']=sha;value['business_actions_enabled']=False
    for key in ('create_approval_id','create_request_hash','crm_approval_id','outbound_approval_id'):value[key]=None
    value['source_hashes']={name:hashlib.sha256((app/name).read_bytes()).hexdigest() for name in sources}
    p.write_text(json.dumps(value,indent=2)+'\n');os.chown(p,0,0);p.chmod(0o644)
    p=root/'etc/opticable-workflow-api.env'
    rows=[line for line in p.read_text().splitlines() if not line.startswith('OPTIBRAIN_PHASE7_RELEASE_SHA=')]
    p.write_text('\n'.join(rows)+'\nOPTIBRAIN_PHASE7_RELEASE_SHA='+sha+'\n');os.chown(p,0,0);p.chmod(0o600)
    digest=root/'etc/optibrain/master-runbook.sha256'
    digest.write_text(hashlib.sha256((repo/'docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md').read_bytes()).hexdigest()+'\n')
    os.chown(digest,0,0);digest.chmod(0o440)
    return dict(sha=sha,pinned_sources=len(sources),business_actions_enabled=False,approval_pins=None)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--target-root',type=Path,required=True);parser.add_argument('--sha',required=True)
    args=parser.parse_args()
    try:print(json.dumps(rebind(args.target_root,args.sha)))
    except Exception as exc:raise SystemExit('Recovery rebind refused: '+type(exc).__name__)
