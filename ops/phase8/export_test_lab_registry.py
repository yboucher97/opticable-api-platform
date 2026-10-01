#!/usr/bin/env python3
"""Publish minimal read-only Test Lab lookup for the production queue."""
import json,os,grp
from pathlib import Path

SOURCE=Path('/var/lib/optibrain/phase8/test-lab/registry.json')
TARGET=Path('/etc/optibrain/phase8-test-lab-registry.json')

def main():
    if os.geteuid()!=0:raise SystemExit('Root required')
    source=json.loads(SOURCE.read_text())
    if source.get('schema')!=1:raise ValueError('Invalid root Test Lab registry')
    public={'schema':1,
            'records':{module:source['records'][module] for module in ('Leads','Contacts','Accounts','Deals','Tasks')},
            'scenarios':{name:{key:value[key] for key in ('lead_id','email','mail') if key in value}
                         for name,value in source['scenarios'].items()}}
    temporary=TARGET.with_name('.'+TARGET.name+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o640)
    with os.fdopen(fd,'w') as handle:
        json.dump(public,handle,indent=2,sort_keys=True);handle.write('\n');handle.flush();os.fsync(handle.fileno())
    os.chown(temporary,0,grp.getgrnam('opticable-workflow-api').gr_gid)
    os.replace(temporary,TARGET)
    print(TARGET,'Lead IDs',len(public['records']['Leads']))

if __name__=='__main__':main()
