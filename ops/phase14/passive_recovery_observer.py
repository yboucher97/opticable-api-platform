#!/usr/bin/python3
"""Fixed passive integration; never dispatches a repair or imports the live API."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import resource
import stat
import subprocess
import sys
import tempfile
import urllib.request

POLICY = Path('/etc/optibrain/recovery-passive.json')
RUNTIME = Path('/usr/local/lib/optibrain-recovery')
STATUS = Path('/var/lib/optibrain/autonomous-operations/passive-recovery/status.json')
AUDIT = Path('/var/lib/optibrain/autonomous-operations/operations-audit.jsonl')
SOURCE = Path('/opt/opticable-api-platform')
SERVICES = {
    'opticable-workflow-api.service': 'http://127.0.0.1:8100/v1/system/health',
    'opticable-password-pdf.service': 'http://127.0.0.1:8000/health',
    'opticable-omada-site.service': 'http://127.0.0.1:3210/api/health',
    'caddy.service': None,
}


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def trusted(path, *, directory=False, owner=0):
    path = Path(path)
    for parent in [*reversed(path.parents), path]:
        s = parent.lstat()
        if parent.is_symlink() or s.st_uid != owner or s.st_mode & 0o022:
            raise ValueError('Untrusted recovery path: ' + str(parent))
    s = path.lstat()
    if directory and not stat.S_ISDIR(s.st_mode):
        raise ValueError('Recovery directory required')
    if not directory and (not stat.S_ISREG(s.st_mode) or s.st_nlink != 1):
        raise ValueError('Single protected regular file required')
    return s


def read_json(path, limit=2*1024**2):
    trusted(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        if os.fstat(stream.fileno()).st_size > limit:
            raise ValueError('Bounded observation required')
        return json.load(stream)


def verify_runtime(root, policy):
    trusted(root, directory=True)
    manifest = read_json(root/'manifest.json')
    if (canonical(manifest) != policy['manifest_sha256'] or manifest.get('main_api_included') is not False
            or manifest.get('source_sha') != policy['runtime_source_sha']):
        raise ValueError('Independent exact runtime pin mismatch')
    dependencies=read_json(root/'dependencies.json')
    if canonical(dependencies)!=policy['dependencies_sha256']:
        raise ValueError('Independent dependency pin mismatch')
    actual = set()
    for p in root.rglob('*'):
        trusted(p, directory=p.is_dir())
        if p.is_file():actual.add(p.relative_to(root).as_posix())
    expected={**manifest['files'],**dependencies['files']}
    if actual != set(expected) | {'manifest.json','dependencies.json','passive_child.py'}:
        raise ValueError('Recovery executable inventory changed')
    for name, expected in expected.items():
        p = root/name
        if p.stat().st_mode & 0o222 or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('Recovery executable content/mode changed')
    if any((root/name).stat().st_mode & 0o222 for name in ('manifest.json','dependencies.json')):
        raise ValueError('Recovery manifest must be read-only')
    if hashlib.sha256((root/'passive_child.py').read_bytes()).hexdigest()!=policy['passive_child_sha256']:
        raise ValueError('Restricted child entrypoint changed')
    return manifest


def evaluate(observation):
    """Unavailability is an observed failure; it never becomes execution authority."""
    failures = [name for name, row in observation['services'].items() if row.get('healthy') is not True]
    return dict(schema=1, mode='PASSIVE_ONLY', observed_at=observation['observed_at'],
        state='ACTION_REQUIRED' if failures or not observation['source_matches_registration'] else 'VERIFIED',
        unhealthy_services=failures, source_sha=observation['source_sha'],
        source_matches_registration=observation['source_matches_registration'],
        services=observation['services'], simulation=observation.get('simulation', False),
        production_repairs_enabled=False, rollback_enabled=False, restart_enabled=False,
        business_mutations=0, database_restores=0, notification_sends=0)


def independent_runtime(root):
    nobody = pwd.getpwnam('nobody')
    result=subprocess.run(['/usr/bin/systemctl','start','--wait','optibrain-passive-recovery-verifier.service'],
        stdin=subprocess.DEVNULL,capture_output=True,timeout=25,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
    if result.returncode:raise ValueError('Independent restricted runtime failed')
    value=read_json(STATUS.parent/'runtime-result.json',8192)
    at=dt.datetime.fromisoformat(value['observed_at'])
    if not (value['runtime_imported'] and not value['api_imported'] and value['uid']==nobody.pw_uid
            and value['production_scope_refused'] and value['network_denied']
            and 0<=(dt.datetime.now(dt.timezone.utc)-at).total_seconds()<30):
        raise ValueError('Independent runtime capability checks failed')
    return value


def audit(event, **details):
    trusted(AUDIT)
    fd = os.open(AUDIT, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
    with os.fdopen(fd,'a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        stream.write(json.dumps(dict(at=dt.datetime.now(dt.timezone.utc).isoformat(),
            event=event, mode='PASSIVE_ONLY', **details), sort_keys=True)+'\n')
        stream.flush();os.fsync(stream.fileno())


def observe(simulate=False):
    if os.geteuid() != 0:raise PermissionError('Protected passive observation requires root verification')
    policy = read_json(POLICY,16384)
    if (policy.get('mode') != 'PASSIVE_ONLY' or policy.get('production_repairs_enabled') is not False
            or policy.get('rollback_enabled') is not False or policy.get('restart_enabled') is not False):
        raise ValueError('Passive-only policy required')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=policy['observer_sha256']:
        raise ValueError('Observer code pin changed')
    verify_runtime(RUNTIME,policy)
    unit=Path('/etc/systemd/system/optibrain-passive-recovery-verifier.service')
    trusted(unit)
    if hashlib.sha256(unit.read_bytes()).hexdigest()!=policy['verifier_unit_sha256']:
        raise ValueError('Restricted verification service changed')
    audit('PASSIVE_RECOVERY_OBSERVATION_STARTED',simulation=simulate)
    runtime = independent_runtime(RUNTIME)
    sha = subprocess.check_output(['/usr/bin/git','-c','safe.directory='+str(SOURCE),'-C',str(SOURCE),'rev-parse','HEAD'],
        text=True,timeout=5,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}).strip()
    registered = read_json(Path('/etc/optibrain/phase7-canary-registration.json'),16384)['candidate_sha']
    observed = {'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(), 'source_sha':sha,
        'source_matches_registration':sha==registered,'services':{},'simulation':simulate}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for unit,url in SERVICES.items():
        text = subprocess.check_output(['/usr/bin/systemctl','show',unit,'-p','ActiveState','-p','MainPID','-p','Result'],text=True,timeout=5)
        row = dict(line.split('=',1) for line in text.splitlines() if '=' in line)
        row['healthy'] = row.get('ActiveState')=='active' and row.get('Result')=='success'
        if url:
            try:
                if simulate and unit=='opticable-workflow-api.service':raise ConnectionError('PROCESS_LOCAL_SIMULATION')
                with opener.open(url,timeout=3) as response:
                    body=json.loads(response.read(65537))
                    row['http_status']=response.status
                    row['healthy']=row['healthy'] and response.status==200 and (body.get('status')=='ok' or body.get('ok') is True)
            except Exception as exc:row.update(healthy=False,error_type=type(exc).__name__)
        observed['services'][unit]=row
    result = evaluate(observed);result['independent_runtime']=runtime
    result['recovery_reference'] = policy['recovery_reference']
    if not simulate:
        trusted(STATUS.parent,directory=True)
        fd,name=tempfile.mkstemp(prefix='.passive-',dir=STATUS.parent)
        try:
            with os.fdopen(fd,'w') as stream:
                os.fchmod(stream.fileno(),0o600);json.dump(result,stream,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(name,STATUS)
            directory=os.open(STATUS.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            if os.path.exists(name):os.unlink(name)
    audit('PASSIVE_RECOVERY_OBSERVATION_FINISHED',simulation=simulate,state=result['state'],status_sha256=canonical(result),repairs=0)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['observe'])
    parser.add_argument('--simulate-api-unavailable',action='store_true')
    args=parser.parse_args()
    print(json.dumps(observe(args.simulate_api_unavailable),sort_keys=True))


if __name__=='__main__':main()
