#!/usr/bin/env python3
"""Manual read-only, aggregate inspection. Credentials remain in private process memory."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import urllib.request

ROOT = Path('/opt/opticable-api-platform')


def run(*args):
    return subprocess.check_output(args, text=True, timeout=30).strip()


def api_environment():
    pid = run('systemctl', 'show', 'opticable-workflow-api', '-p', 'MainPID', '--value')
    if not pid.isdigit() or pid == '0':
        raise ValueError('API process absent')
    for entry in Path('/proc/' + pid + '/environ').read_bytes().split(b'\0'):
        if b'=' in entry:
            key, value = entry.split(b'=', 1)
            os.environ[key.decode()] = value.decode()
    os.environ['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'


def inspect(protected=False, ovh=False):
    if os.geteuid() != 0:
        raise ValueError('Manual root inspection required')
    sys.dont_write_bytecode = True
    api_environment()
    sys.path.insert(0, str(ROOT / 'apps/workflow-api'))
    from workflow.config import load_settings
    from workflow.automation.business_autonomy import Policy
    settings = load_settings()
    value = dict(schema=1, at=datetime.now(timezone.utc).isoformat(), reads_only=True, provider_mutations=0)
    value['sha'] = run('git', '-c', 'safe.directory=' + str(ROOT), '-C', str(ROOT), 'rev-parse', 'HEAD')
    value['release'] = json.loads(Path('/var/lib/optibrain/releases/current.json').read_text())
    value['policy'] = json.loads(Path('/etc/optibrain/mutation-control.json').read_text())
    value['automatic_mutations'] = Policy.from_environment().automatic_mutations
    value['development_authorization'] = Path('/etc/optibrain/authorize-persistent-codex-development').exists()
    value['endpoints'] = {}
    for name, route in [('health','/v1/system/health'), ('readiness','/v1/system/readiness')]:
        req = urllib.request.Request('http://127.0.0.1:8100' + route,
            headers={'X-API-Key': os.environ[settings.api.api_key_env]})
        with urllib.request.urlopen(req, timeout=15) as response:
            value['endpoints'][name] = json.load(response)
    units = ('opticable-workflow-api.service','opticable-password-pdf.service','opticable-omada-site.service','caddy.service',
             'optibrain-backup.timer','optibrain-phase2a-upload.timer','opticable-phase9-intake-receipts.timer',
             'opticable-phase10-service-events.timer','opticable-phase12-test-runner.timer')
    units += tuple(f'optibrain-agent-{n}.{k}' for n in ('dispatch','status','usage') for k in ('service','timer'))
    value['units'] = {u: dict(line.split('=',1) for line in run('systemctl','show',u,'-p','ActiveState',
        '-p','UnitFileState','-p','Result','-p','ExecMainStatus').splitlines() if '=' in line) for u in units}
    value['database_checks'] = {}
    for dbpath in sorted(settings.automation.db_path.parent.glob('*.db')):
        with sqlite3.connect(dbpath.as_uri() + '?mode=ro', uri=True, timeout=5) as db:
            db.execute('PRAGMA query_only=ON')
            value['database_checks'][dbpath.name] = db.execute('PRAGMA integrity_check').fetchone()[0]
    journal = settings.automation.db_path.with_name('phase12-autonomy.db')
    with sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        value['real_action_successes'] = db.execute("SELECT COUNT(*) FROM actions WHERE ownership='REAL' AND state='succeeded'").fetchone()[0]
    if protected:
        from workflow.zoho_gateway import ZohoGatewayClient
        from workflow.zoho_oauth import ZohoOAuthManager
        client = ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
        baseline = json.loads(Path('/etc/optibrain/protected-runtime-versions.json').read_text())
        summary = dict(records=0, missing=0, modified=0, test_spoof=0, calls=0, modules={})
        for module, data in baseline['modules'].items():
            versions = data['protected_versions']
            if not versions:
                continue
            rows = []
            for page in range(1,6):
                summary['calls'] += 1
                read = client.request('zohoapis','GET','/crm/v8/' + module,
                    query={'fields':'id,Modified_Time,OptiBrain_Test','per_page':200,'page':page})['data']
                rows.extend(read.get('data') or [])
                if not read.get('info',{}).get('more_records'):
                    break
            else:
                raise ValueError('Protected baseline pagination incomplete')
            current = {str(row['id']):row for row in rows}
            counts = dict(records=len(versions),missing=sum(k not in current for k in versions),
                modified=sum(k in current and current[k].get('Modified_Time') != v for k,v in versions.items()),
                test_spoof=sum(k in current and current[k].get('OptiBrain_Test') is True for k in versions))
            summary['modules'][module] = counts
            for key in counts:
                summary[key] += counts[key]
        summary['unchanged'] = summary['records'] == 123 and not any(summary[k] for k in ('missing','modified','test_spoof'))
        value['protected'] = summary
    if ovh:
        from workflow.ovh_api import OvhApiClient
        data = OvhApiClient(settings.ovh).request('/vps/vps-214ba8cd.vps.ovh.ca')['data']
        value['ovh'] = {k:data.get(k) for k in ('name','state','zone')}
        value['ovh']['endpoint'] = settings.ovh.endpoint
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--protected', action='store_true', help='GET-only 123-record version comparison')
    parser.add_argument('--ovh', action='store_true', help='One read-only direct VPS inventory call')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        os.umask(0o077)
        result = inspect(args.protected, args.ovh)
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write('\n')
        print(json.dumps({'sha':result['sha'],'protected':result.get('protected'), 'saved':str(args.output)}))
    except Exception as exc:
        raise SystemExit('Read-only inspection failed: ' + type(exc).__name__)
