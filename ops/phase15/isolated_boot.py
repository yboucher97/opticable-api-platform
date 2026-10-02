#!/usr/bin/env python3
"""Actual isolated API boot, anonymous denial and local authenticated read checks."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import time
import urllib.error
import urllib.request


def get(route,key=None,method='GET'):
    headers={'X-API-Key':key} if key else {}
    req=urllib.request.Request('http://127.0.0.1:8100'+route,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=3) as response:
            body=response.read()
            return response.status,json.loads(body) if response.headers.get('content-type','').startswith('application/json') else {}
    except urllib.error.HTTPError as exc:return exc.code,{}


def main():
    start=time.monotonic()
    if os.geteuid()!=0 or not Path('/etc/optibrain-rebuild-target').is_file():raise ValueError('Marked recovery target required')
    links=json.loads(subprocess.check_output(['ip','-j','link'],text=True))
    if any(link['ifname']!='lo' for link in links):raise ValueError('External interfaces present; isolated boot forbidden')
    if subprocess.check_output(['ip','route','show'],text=True).strip():raise ValueError('External route present')
    audit=Path('/run/optibrain-isolated');audit.mkdir(mode=0o700,exist_ok=True)
    user=pwd.getpwnam('opticable-workflow-api');os.chown(audit,user.pw_uid,user.pw_gid)
    attempts=audit/'network-attempts';attempts.write_text('');os.chown(attempts,user.pw_uid,user.pw_gid)
    flags=dict(line.split('=',1) for line in Path('/etc/optibrain/rebuild-safety.env').read_text().splitlines())
    env=dict(PATH='/usr/local/bin:/usr/bin:/bin',LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1',**flags)
    env.update(SITE_WORKFLOW_OUTPUT_ROOT='/var/lib/opticable-workflow-api/output',
               OPTICABLE_AUTOMATION_ROOT='/var/lib/opticable-workflow-api/output/automation',
               OPTICABLE_AUTOMATION_WORKFLOWS_DIR='/etc/optibrain/phase13-observe-workflows',
               ZOHO_OAUTH_CREDENTIALS_PATH='/run/optibrain-isolated/no-provider-oauth.json')
    registration=json.loads(Path('/etc/optibrain/phase7-canary-registration.json').read_text())
    env.update(OPTIBRAIN_PHASE7_REGISTRATION=registration['mode'],OPTIBRAIN_PHASE7_RELEASE_SHA=registration['candidate_sha'])
    checks={}
    version=None
    for configured in (True,False):
        key=secrets.token_hex(32) if configured else None
        if configured:env['SITE_WORKFLOW_API_KEY']=key
        else:env.pop('SITE_WORKFLOW_API_KEY',None)
        with (audit/('api-configured.log' if configured else 'api-missing-key.log')).open('w') as log:
            process=subprocess.Popen(['runuser','-u','opticable-workflow-api','--',
                '/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python','-I',
                '/opt/opticable-api-platform/ops/phase15/isolated_api.py'],env=env,
                cwd='/opt/opticable-api-platform/apps/workflow-api',stdout=log,stderr=log)
            try:
                for _ in range(100):
                    if process.poll() is not None:raise ValueError('Contained API exited')
                    try:
                        status,health=get('/v1/system/health')
                        if status==200:break
                    except OSError:pass
                    time.sleep(0.1)
                else:raise ValueError('Contained API failed to start')
                version=health['version'];prefix='configured' if configured else 'missing_key'
                for route in ('/v1/system/readiness','/v1/automation/workflows','/v1/operator/today','/v1/operator/system-health'):
                    status,_=get(route);checks[prefix+':'+route]=status
                    if status not in (401,403):raise ValueError('Authentication failed open')
                if configured:
                    for route in ('/v1/system/readiness','/v1/automation/execution-health'):
                        status,_=get(route,key);checks['authenticated:'+route]=status
                        if status!=200:raise ValueError('Authenticated local read failed')
                    if get('/v1/system/readiness','invalid-key')[0]!=401:raise ValueError('Invalid key accepted')
                    status,_=get('/v1/workflows/site-and-password',key,method='POST')
                    checks['legacy_writer_denied']=status
                    if status!=403:raise ValueError('Legacy writer not denied')
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
    policy=json.loads(Path('/etc/optibrain/mutation-control.json').read_text())
    if policy['test_writes_enabled'] is not False or policy['real_canary_allowed'] is not False:raise ValueError('Recovery writers enabled')
    count=len(attempts.read_text().splitlines())
    if count:raise ValueError('Unexpected external network attempt')
    result=dict(schema=1,at=datetime.now(timezone.utc).isoformat(),boot='PASS',api_version=version,
                auth_fail_closed='PASS',checks=checks,elapsed_seconds=round(time.monotonic()-start,3),
                provider_mutation_attempts=0,ovh_mutation_attempts=0,external_network_attempts=count,
                provider_credentials_in_process=False,interfaces=['lo'],writers_enabled=False)
    Path('/var/lib/optibrain/isolated-boot-receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('Isolated boot refused: '+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__))
