#!/usr/bin/env python3
"""Portable document/config/unit coverage and non-mutating bootstrap validation."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[2]


def validate():
    issues=[]
    register=json.loads((ROOT/'docs/optibrain-documentation-register.json').read_text())
    rows=register['documents'];indexed={row['path'] for row in rows}
    docs={str(p.relative_to(ROOT)) for p in (ROOT/'docs').rglob('*') if p.suffix in ('.md','.json')}
    docs.update(subprocess.check_output(['git','-C',str(ROOT),'ls-files','*.md'],text=True).splitlines())
    if docs!=indexed:issues.append('document coverage differs: '+str(sorted(docs^indexed)))
    allowed={'AUTHORITATIVE CURRENT','RECOVERY','SECURITY / CONTROL','AUDIT EVIDENCE','HISTORICAL','SUPERSEDED','OBSOLETE'}
    links=0
    for row in rows:
        p=ROOT/row['path']
        if not p.is_file() or row['classification'] not in allowed:issues.append('invalid document classification/path: '+row['path'])
        if row.get('superseded_by') and not (ROOT/row['superseded_by']).is_file():issues.append('missing superseder')
        if not row['current'] or p.suffix!='.md':continue
        for value in re.findall(r'\[[^\]]*\]\(([^)]+)\)',p.read_text()):
            if value.startswith(('https://','http://','#','mailto:')):continue
            path=unquote(value.split('#',1)[0]);links+=1
            if not (p.parent/path).exists():issues.append('broken current link: '+row['path']+' -> '+path)
    inventory=json.loads((ROOT/'docs/optibrain-configuration-register.json').read_text())
    required={'location','owner','secret','source_of_truth','deployed','restored','verified','backed_up','purpose'}
    for row in inventory['configuration_items']:
        if not required<=row.keys() or any(row[k] in ('UNKNOWN',None,'') for k in required):issues.append('incomplete config inventory')
    required_secrets={'purpose','provider','storage','consumer','rotation','recovery_requirement','owner_held_offline','backed_up'}
    for row in inventory['secret_references']:
        if not required_secrets<=row.keys() or 'value' in row:issues.append('incomplete/unsafe secret reference')
    runtime=(ROOT/'docs/OPTIBRAIN_RUNTIME_CONTRACT.md').read_text()
    spec=importlib.util.spec_from_file_location('bootstrap_check',ROOT/'ops/phase15/bootstrap.py')
    bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
    for name in bootstrap.APP+bootstrap.TIMERS:
        if name not in runtime or not (ROOT/'ops/phase15/systemd'/(name+'.service')).is_file():issues.append('runtime service missing: '+name)
    for name in bootstrap.TIMERS:
        if not (ROOT/'ops/phase15/systemd'/(name+'.timer')).is_file():issues.append('runtime timer missing')
    for p in (ROOT/'ops/phase15/systemd').glob('*.service'):
        for path in re.findall(r'/opt/opticable-api-platform/([^\s]+\.py)',p.read_text()):
            if not (ROOT/path).is_file():issues.append('unit references absent source: '+path)
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);(root/'etc').mkdir();(root/'etc/os-release').write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
        before=sorted(str(p.relative_to(root)) for p in root.rglob('*'))
        check=bootstrap.check(root)
        if check['writes_performed'] or before!=sorted(str(p.relative_to(root)) for p in root.rglob('*')):issues.append('bootstrap CHECK changed target')
    recovery=(ROOT/'docs/OPTIBRAIN_RECOVERY_GUIDE.md').read_text()
    for name in ('ff91b86f3a4f9491158c7e7bcd067ca9cb06bb29b6a424d22dc0c9d31c82d7ba',
                 '36960a90e9d3348266485d08bd0be4d737cf6654ff123a2541a89f856375e84c',
                 '20261002T123816Z','OPTIBRAIN-GOLDEN-PHASE14-PRE-PHASE15-20261002'):
        if name not in recovery:issues.append('golden recovery reference missing')
    if len(register['primary_documents'])!=10:issues.append('primary set changed')
    return dict(passed=not issues,documents=len(rows),primary_documents=10,current_links=links,
                configuration_sources=len(inventory['configuration_items']),secret_references=len(inventory['secret_references']),
                bootstrap_check='PASS',unknown_documents=0,issues=issues)


if __name__=='__main__':
    value=validate();print(json.dumps(value,sort_keys=True));raise SystemExit(0 if value['passed'] else 1)
