#!/usr/bin/env python3
"""Read-only host/secret metadata inventory. Output contains no credential values."""
import argparse
import grp
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import stat
import subprocess
import tarfile
import urllib.request

from common import REPO, atomic_json, command, database_snapshot, digest, env_file, file_hash, now, require

STATE_ROOTS = ('/var/lib/opticable-workflow-api', '/var/lib/optibrain',
               '/var/lib/opticable-password-pdf', '/var/lib/opticable-omada-site',
               '/var/lib/opticable-api-platform/shared')
PACKAGES = ('python3', 'python3-venv', 'python3-pip', 'python3-boto3', 'git', 'sqlite3',
            'age', 'caddy', 'curl', 'ca-certificates', 'openssl', 'iproute2', 'systemd',
            'sudo', 'rsync', 'tar', 'xz-utils', 'logrotate', 'openssh-server', 'util-linux',
            'ufw', 'fail2ban', 'qemu-guest-agent')
SAFE_IDENTITIES = ('GITHUB_APP_ID', 'GITHUB_APP_INSTALLATION_ID', 'GITHUB_OWNER',
                   'CLOUDFLARE_ACCOUNT_ID', 'ZOHO_BOOKS_ORGANIZATION_ID', 'ZOHO_MAIL_ACCOUNT_ID',
                   'ZOHO_OAUTH_ACCOUNTS_BASE_URL', 'ZOHO_OAUTH_API_BASE_URL', 'OVH_ENDPOINT')


def probe(args, default='UNAVAILABLE'):
    try: return command(args, timeout=30)
    except Exception: return default


def metadata(path, fingerprint=False):
    p = Path(path); s = p.lstat()
    row = {'path': str(p), 'owner': pwd.getpwuid(s.st_uid).pw_name,
           'group': grp.getgrgid(s.st_gid).gr_name, 'mode': format(stat.S_IMODE(s.st_mode), '04o'),
           'size_bytes': s.st_size, 'type': 'directory' if p.is_dir() else 'file'}
    if fingerprint and p.is_file() and not p.is_symlink(): row['sha256'] = file_hash(p)
    return row


def archive_manifest(path):
    # Streaming: no extraction, duplicate archives, or secret-bearing temporary files.
    with tarfile.open(path, 'r|gz') as tar:
        for member in tar:
            if re.fullmatch(r'generation-\d{8}T\d{6}Z/manifest.json', member.name):
                require(member.size < 32 * 1024**2, 'manifest_too_large')
                return json.load(tar.extractfile(member))
    raise ValueError('archive_manifest_missing')


def collect(output):
    require(os.geteuid() == 0, 'root_read_only_inventory_required')
    values = env_file('/etc/opticable-workflow-api.env')
    release = json.loads(Path('/var/lib/optibrain/releases/current.json').read_text())
    recovery = json.loads(Path('/var/lib/optibrain/phase2a/state.json').read_text())
    archive = Path('/var/backups/optibrain/optibrain-backup-' + recovery['generation'] + '.tar.gz')
    manifest = archive_manifest(archive)
    require(recovery.get('verification_status') == 'download_hash_verified', 'recovery_unverified')
    require(file_hash(archive) == recovery['source_sha256'], 'recovery_hash_mismatch')
    sha = probe(['git', '-c', 'safe.directory=/opt/opticable-api-platform', '-C', '/opt/opticable-api-platform', 'rev-parse', 'HEAD'])
    require(sha == release['sha'] == manifest['production_git_sha'], 'release_recovery_mismatch')
    with urllib.request.urlopen('http://127.0.0.1:8100/v1/system/health', timeout=15) as response:
        health = json.load(response)
    require(health['version'] == release['api_version'] == manifest['application_version'], 'api_version_mismatch')
    unit_names = probe(['systemctl', 'list-unit-files', '--no-legend', '--no-pager']).splitlines()
    services, timers = [], []
    for line in unit_names:
        parts = line.split()
        if not parts: continue
        name = parts[0]
        if not (name.startswith(('opticable-', 'optibrain-')) or name in ('caddy.service', 'caddy-api.service', 'fail2ban.service', 'ufw.service', 'ssh.service', 'ssh.socket')):
            continue
        properties = ('Type', 'Description', 'User', 'Group', 'ExecStart', 'WorkingDirectory', 'EnvironmentFiles',
                      'After', 'Requires', 'Wants', 'Restart', 'ActiveState', 'UnitFileState', 'Result',
                      'FragmentPath', 'DropInPaths', 'LastTriggerUSec', 'NextElapseUSecRealtime',
                      'TimersCalendar', 'TimersMonotonic', 'Triggers', 'ExecMainStartTimestamp', 'ExecMainExitTimestamp')
        raw = probe(['systemctl', 'show', name, *['-p' + x for x in properties]], '')
        data = dict(r.split('=', 1) for r in raw.splitlines() if '=' in r)
        data.update(name=name, classification='RETIRED / MASKED' if parts[1] == 'masked' or name == 'caddy-api.service'
                    else 'TIMER-DRIVEN' if name.endswith('.timer') else 'ONESHOT' if data.get('Type') == 'oneshot' else 'ACTIVE REQUIRED')
        data['authority_relationship'] = 'BACKUP ONLY' if name.startswith('optibrain-backup') or name.startswith('optibrain-phase2a') else 'NO AUTHORITY' if data['classification'] == 'RETIRED / MASKED' else 'ROOT POLICY + EXACT RELEASE + OFF-HOST CLAIMS'
        data['expected_restore_state'] = 'MASKED' if name.endswith('.timer') or any(x in name for x in ('lifecycle-internal', 'customer-communications', 'test-runner', 'agent-')) else 'CONTAINED'
        data['health_check'] = '/v1/system/health' if name == 'opticable-workflow-api.service' else 'systemctl show Result + exact unit hash'
        files = [data.get('FragmentPath', '')] + data.get('DropInPaths', '').split()
        data['definition_hashes'] = {p: file_hash(p) for p in files if p and Path(p).is_file() and p != '/dev/null'}
        (timers if name.endswith('.timer') else services).append(data)
    # All OS timers are also inventoried; only OptiBrain timers have a restore policy.
    all_timers = probe(['systemctl', 'list-timers', '--all', '--no-pager'])
    db_paths = set()
    for root in STATE_ROOTS:
        for p in Path(root).rglob('*.db'):
            if '/phase2a/' not in str(p): db_paths.add(p)
    databases = []
    for p in sorted(db_paths):
        row = metadata(p); row['snapshot'] = database_snapshot(p)
        row.update(criticality='HISTORICAL' if '/var/lib/optibrain/' in str(p) else 'CRITICAL',
                   encryption='root-only local filesystem; AGE encrypted off-host',
                   backup='existing online SQLite backup API', restore='verified staging -> atomic generation promotion')
        databases.append(row)
    secret_paths = {Path('/etc/' + name + '.env') for name in ('opticable-workflow-api', 'opticable-password-pdf', 'opticable-omada-site')}
    for root in ('/etc/optibrain', '/var/lib/opticable-api-platform/shared', '/var/lib/opticable-workflow-api/output/integrations'):
        for p in Path(root).rglob('*'):
            if p.is_file() and (p.suffix in ('.env', '.pem', '.key', '.token') or re.search(r'oauth|credentials|token|deploy-ed25519$', p.name)):
                secret_paths.add(p)
    secrets = []
    backup_paths = {x['source_path'] for x in manifest['source_metadata'] if x['type'] == 'file'}
    for p in sorted(secret_paths):
        if not p.is_file(): continue
        row = metadata(p, True)
        row.update(consumer='API/root reviewed provider clients; PDF shared OAuth; backup/uploader where named',
                   recovery_source='selected AGE-encrypted recovery' if str(p) in backup_paths else 'OWNER ACTION REQUIRED',
                   rotation='preserve current binding; read verification first; never overwrite a newer rotation')
        if p.suffix == '.env':
            row['key_names'] = sorted(set(re.findall(r'^\s*(?:export )?([A-Za-z_][A-Za-z0-9_]*)\s*=', p.read_text(), re.M)))
        secrets.append(row)
    usage = shutil.disk_usage('/')
    du = probe(['du', '-x', '-B1', '--max-depth=1', '/home/optibrain', '/var/lib/optibrain', '/var/backups/optibrain', '/opt', '/var/tmp', '/tmp', '/var/log'])
    config_files = ('/etc/caddy/Caddyfile', '/etc/caddy/conf.d/opticable-api-platform.caddy',
                    '/etc/systemd/journald.conf.d/30-optibrain-retention.conf', '/etc/optibrain/backup.conf',
                    '/etc/optibrain/phase2a.conf', '/etc/ssh/sshd_config.d/99-optibrain-hardening.conf')
    result = dict(manifest_version=1, generated_at=now(), source_production_sha=sha, api_version=health['version'],
        main_sha=probe(['git', '-c', 'safe.directory=' + str(REPO), '-C', REPO, 'rev-parse', 'origin/main']),
        repository='https://github.com/yboucher97/opticable-api-platform.git', release_metadata=release,
        recovery_generation=recovery['generation'], recovery_sources={**recovery, 'local_archive': str(archive),
            'database_count': len(manifest['sqlite_databases']), 'source_bundle': '/var/lib/optibrain/recovery-source/current.bundle',
            'owner_identity_on_host': False, 'offline_decryption_this_generation': recovery.get('offline_restore_verified', False)},
        os=dict(line.split('=',1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line),
        architecture=platform.machine(), kernel=platform.release(), hostname=platform.node(),
        timezone=probe(['timedatectl', 'show', '-p', 'Timezone', '--value']),
        cpu=probe(['lscpu', '-J']), ram=probe(['free', '-b']),
        storage={'total_bytes':usage.total,'used_bytes':usage.used,'free_bytes':usage.free,'critical':usage.free < 2*1024**3,
                 'df_h':probe(['df','-h']),'df_i':probe(['df','-i']), 'controlled_directory_sizes':du,
                 'backup_staging_bytes':probe(['du','-sx','-B1','/var/backups/optibrain']),
                 'worktree_count':len(probe(['git','-c','safe.directory=/opt/opticable-api-platform','-C','/opt/opticable-api-platform','worktree','list']).splitlines())},
        mounts=probe(['findmnt','-J']), disk_layout=probe(['lsblk','-J','-o','NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS']),
        users=[{'name':p.pw_name,'uid':p.pw_uid,'gid':p.pw_gid,'home':p.pw_dir,'shell':p.pw_shell} for p in pwd.getpwall()],
        groups=[{'name':g.gr_name,'gid':g.gr_gid,'members':g.gr_mem} for g in grp.getgrall()],
        sudo_configuration=[metadata(p,True) for p in [Path('/etc/sudoers'),*Path('/etc/sudoers.d').glob('*')] if p.is_file()],
        packages=probe(['dpkg-query','-W','-f=${binary:Package}\t${Version}\n']), required_packages=list(PACKAGES),
        runtime_versions={n:probe(args) for n,args in {'python':['python3','--version'],'node':['node','--version'],
            'npm':['npm','--version'],'git':['git','--version'],'caddy':['caddy','version'],'codex':['codex','--version']}.items()},
        directories=[metadata(p) for p in STATE_ROOTS if Path(p).exists()],
        system_config=[metadata(p,True) for p in config_files if Path(p).is_file()],
        services=services,timers=timers,all_host_timers=all_timers,database_inventory=databases,secret_paths=secrets,
        provider_identities={k:values[k] for k in SAFE_IDENTITIES if k in values},
        submodules=probe(['git','-c','safe.directory=/opt/opticable-api-platform','-C','/opt/opticable-api-platform','submodule','status']),
        reverse_proxy={'production_host':'optibrain.opticable.ca','initial_test_bind':'127.0.0.1:8080',
            'backend_ports':[8100,8000,3210], 'configuration':'/etc/caddy/conf.d/opticable-api-platform.caddy'},
        firewall=probe(['ufw','status','verbose']),fail2ban=probe(['fail2ban-client','status']),
        ssh=probe(['sshd','-T']).splitlines(),
        authority_expected_restore_state={k:'OFF' for k in ('customer','customer_timer','internal','books','ads','outreach','conversion_uploads','production_website','persistent_development','english_real')},
        health_endpoints=['/v1/system/health','/v1/system/readiness','/v1/operator/manager?format=json'],
        verification_suite=['source','sqlite_integrity','foreign_keys','snapshot_counts_ids_hashes','audit_chain','permissions',
            'systemd','proxy','private_health','provider_reads','backup_download_readback','storage','authority'],
        unexpected_production_writes=0,secret_values_printed=0)
    atomic_json(output,result)
    return {'output':str(output),'sha':sha,'generation':recovery['generation'],'databases':len(databases),'secrets':len(secrets),'free_bytes':usage.free}


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try: print(json.dumps(collect(args.output)))
    except Exception as exc: raise SystemExit('Inventory failed: '+type(exc).__name__)
