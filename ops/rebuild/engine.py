"""Idempotent marked-host bootstrap. Routing and writer activation have no port."""
from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import platform
import pwd
import grp
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request

from common import (REPO, Audit, RebuildError, atomic_bytes, atomic_json, command, database_snapshot,
                    digest, env_file, file_hash, now, path_at, private_file, require, toolchain_code_hash)
from recovery import ENV_FILES, POLICY_FILES, STATE_ROOTS, selected, select_generation, stage_archive

APP_UNITS = ('opticable-workflow-api.service', 'opticable-password-pdf.service', 'opticable-omada-site.service')
BACKUP_TIMERS = ('optibrain-backup.timer', 'optibrain-phase2a-upload.timer')
RETIRED = tuple('optibrain-agent-' + n + '.' + k for n in ('dispatch', 'status', 'usage') for k in ('service', 'timer'))
NODE_VERSION = 'v22.23.3'
NODE_SHA256 = 'df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de'
NODE_URL = 'https://nodejs.org/dist/' + NODE_VERSION + '/node-' + NODE_VERSION + '-linux-x64.tar.xz'
BASE_PACKAGES = ['python3', 'python3-venv', 'python3-pip', 'python3-boto3', 'git', 'sqlite3', 'age', 'caddy',
                 'curl', 'ca-certificates', 'openssl', 'iproute2', 'systemd', 'sudo', 'rsync', 'tar',
                 'xz-utils', 'logrotate', 'openssh-server', 'util-linux', 'ufw', 'fail2ban']


def reviewed_bytes(row):
    """One hash-bound compatibility fix to the existing backup format v1 helper.

    Its recursive find may select a business document's nested manifest.json.
    Restrict the replacement helper to the generation's own root manifest.
    Current production source and installed helper remain untouched.
    """
    data=(REPO/row['source']).read_bytes()
    require(file_hash(REPO/row['source'])==row['sha256'],'reviewed_definition_hash_mismatch')
    if row.get('transform'):
        require(row['transform']=='backup-root-manifest-v1'
                and row['source']=='ops/backup/optibrain-backup.sh','unreviewed_definition_transform')
        original=b'find "${verify_dir}" -type f -name manifest.json -print -quit'
        require(data.count(original)==1,'backup_manifest_adapter_source_changed')
        data=data.replace(original,b'find "${verify_dir}" -mindepth 2 -maxdepth 2 -type f -name manifest.json -print -quit')
    import hashlib
    require(hashlib.sha256(data).hexdigest()==row.get('installed_sha256',row['sha256']),
            'reviewed_installed_definition_hash_mismatch')
    return data
SAFETY = {'OPTICABLE_AUTOMATION_ENABLED': 'false', 'OPTIBRAIN_CRM_DRIFT_ENABLED': 'false',
          'OPTIBRAIN_BUSINESS_AUTO_WRITES': '0', 'OPTIBRAIN_AUTO_TEST_TASK': '0',
          'OPTIBRAIN_AUTO_TEST_PROJECT': '0', 'OPTIBRAIN_AUTO_TEST_INTERNAL': '0',
          'OPTIBRAIN_PHASE9_FORM_ENRICHMENT': 'off', 'OPTIBRAIN_PHASE9_FORM_GO_LIVE': 'off',
          'OPTIBRAIN_CRM_LEAD_WRITES': 'off', 'OPTIBRAIN_CRM_CANARY': 'off',
          'OPTIBRAIN_LEAD_CREATE_CANARY': 'off', 'OPTIBRAIN_OUTBOUND_SENDS': 'off',
          'OPTIBRAIN_SALES_DRAFTS': 'off', 'OPTICABLE_CONNECT_STANDBY_ENABLED': 'false',
          'OPTIBRAIN_ALLOW_APOLLO_CREDIT_CONSUMPTION': 'false'}


def validate_rebuild_manifest(m):
    required = {'manifest_version', 'source_production_sha', 'api_version', 'recovery_generation', 'os',
                'architecture', 'timezone', 'users', 'groups', 'packages', 'runtime_versions', 'directories',
                'mounts', 'services', 'timers', 'database_inventory', 'secret_paths', 'provider_identities',
                'reverse_proxy', 'firewall', 'health_endpoints', 'authority_expected_restore_state',
                'recovery_sources', 'verification_suite', 'bootstrap'}
    require(required <= m.keys() and m['manifest_version'] == 1, 'incomplete_rebuild_manifest')
    require(re.fullmatch('[0-9a-f]{40}', m['source_production_sha']), 'invalid_manifest_source')
    require(m['architecture'] == 'x86_64' and m['os']['ID'].strip('"') == 'ubuntu' and m['os']['VERSION_ID'].strip('"') == '24.04', 'unsupported_manifest_os')
    require(all(v == 'OFF' for v in m['authority_expected_restore_state'].values()), 'unsafe_manifest_authority')
    require(m['database_inventory'] and m['secret_paths'] and m['services'] and m['timers'], 'empty_rebuild_inventory')
    recipe = m['bootstrap']
    require(recipe['packages'] == BASE_PACKAGES and recipe['ssh_port'] in range(1, 65536), 'unreviewed_package_or_ssh_plan')
    require(recipe.get('node_sha256') == NODE_SHA256, 'unreviewed_node_release')
    require(recipe.get('retention_policy') == 'preserve-existing', 'unapproved_retention_policy')
    for row in recipe['reviewed_files']:
        require(not Path(row['source']).is_absolute() and '..' not in Path(row['source']).parts, 'unsafe_reviewed_source')
        reviewed_bytes(row)
        require(row['destination'].startswith(('/etc/', '/usr/local/')), 'unsafe_reviewed_destination')
    return True


def package_plan(installed):
    return [p for p in BASE_PACKAGES if p not in set(installed)]


def restore_plan(m, catalog, pin='latest-verified', data_root='/var/lib/optibrain-data'):
    validate_rebuild_manifest(m)
    row = select_generation(catalog, pin, source_sha=m['source_production_sha'])
    require(row['api_version']==m['api_version'],'manifest_api_version_incompatible')
    require(data_root.startswith(('/var/lib/', '/srv/')) and not any(c.isspace() for c in data_root)
            and '..' not in Path(data_root).parts, 'unsafe_data_root')
    return {'schema': 1, 'mode': 'DRY_RUN', 'generation': row['generation'], 'source_sha': row['source_sha'],
            'api_version': row['api_version'], 'expected_databases': len(row['databases']), 'data_root': data_root,
            'packages': BASE_PACKAGES, 'services': list(APP_UNITS),
            'timers_masked': [r['name'] for r in m['timers']],
            'provider_reads_required': m['bootstrap']['required_providers'], 'authority': 'SAFE/OFF',
            'writes_performed': 0, 'dns_changes': 0, 'cutover_performed': False,
            'owner_dependency': 'Owner device decrypts selected AGE archive; transfer approved plaintext/catalog privately'}


class Host:
    """Real adapters only ever operate inside the explicitly validated new host."""
    def __init__(self, root=Path('/')):
        self.root = Path(root)

    def run(self, args, **kwargs):
        require(self.root == Path('/'), 'real_adapters_require_replacement_os')
        return command(args, **kwargs)

    def ids(self):
        return ({p.pw_name: p.pw_uid for p in pwd.getpwall()}, {g.gr_name: g.gr_gid for g in grp.getgrall()})

    def chown(self, path, uid, gid):
        os.chown(path, uid, gid)

    def same_mount(self, source, target):
        return target.stat().st_ino==source.stat().st_ino and target.stat().st_dev==source.stat().st_dev

    def ensure_users(self):
        uid, gid = self.ids()
        for name in ('optibrain', 'opticable-workflow-api', 'opticable-password-pdf', 'opticable-omada-site'):
            if name not in uid:
                args = ['useradd', '--user-group', '--create-home', '--shell', '/bin/bash' if name == 'optibrain' else '/usr/sbin/nologin']
                if name == 'optibrain': args += ['--home-dir', '/home/optibrain']
                else: args += ['--system', '--home-dir', '/var/lib/' + name]
                self.run(args + [name])
        if 'siteandpassword' not in gid: self.run(['groupadd', '--system', 'siteandpassword'])
        for name in ('opticable-workflow-api', 'opticable-password-pdf'):
            self.run(['usermod', '-a', '-G', 'siteandpassword', name])
        return self.ids()


class Engine:
    def __init__(self, manifest, catalog, archive, *, pin='latest-verified', data_root='/var/lib/optibrain-data',
                 host=None, migration=False):
        self.manifest = manifest; self.catalog = catalog; self.archive = Path(archive)
        self.plan = restore_plan(manifest, catalog, pin, data_root)
        self.row = select_generation(catalog, pin, source_sha=manifest['source_production_sha'])
        self.host = host or Host(); self.root = self.host.root
        self.control = path_at(self.root, '/var/lib/optibrain-rebuild')
        self.data = path_at(self.root, data_root)
        self.migration = migration
        self.audit = None

    def guard(self, *, final_sync=False):
        require(os.geteuid() == 0, 'root_required')
        osfile = path_at(self.root, '/etc/os-release')
        data = dict(r.split('=',1) for r in osfile.read_text().splitlines() if '=' in r)
        require(data.get('ID', '').strip('"') == 'ubuntu' and data.get('VERSION_ID', '').strip('"') == '24.04', 'supported_ubuntu_2404_required')
        require(platform.machine() == 'x86_64', 'supported_amd64_required')
        marker = path_at(self.root, '/etc/optibrain-rebuild-target')
        state = self.control / 'state.json'
        completed=False
        if state.exists():
            private_file(state); private_file(marker)
            saved = json.loads(state.read_text())
            completed=saved.get('completed') is True and saved.get('generation') == self.row['generation']
            require(saved['target_id'] == marker.read_text().strip(), 'rebuild_target_binding_mismatch')
            require(saved['data_root'] == str(self.data), 'data_root_changed_on_rerun')
            # A later generation must be explicit final-sync, never a casual rerun.
            require(saved.get('generation') in (None, self.row['generation']) or saved.get('pending_generation') == self.row['generation']
                    or (final_sync and saved.get('generation') and self.row['generation'] > saved['generation']),
                    'use_final_sync_for_new_generation')
        else:
            # Marker alone NEVER permits rewriting a production machine.
            sentinels = ['/etc/optibrain', '/var/lib/optibrain/releases/current.json',
                         '/var/lib/opticable-workflow-api/output/automation/automation.db']
            require(not any(path_at(self.root, p).exists() for p in sentinels), 'existing_production_host_refused')
            unitdir = path_at(self.root, '/etc/systemd/system')
            require(not any(unitdir.glob('opticable-*.service')), 'existing_application_units_refused')
            require(not self.data.exists() or all(p.name=='lost+found' and p.is_dir() and not any(p.iterdir()) for p in self.data.iterdir()), 'existing_data_root_refused')
            proxy = path_at(self.root, '/etc/caddy/Caddyfile')
            require(not proxy.exists() or proxy.read_text().startswith('# The Caddyfile is an easy way'), 'existing_proxy_refused')
        require(not self.archive.is_symlink() and self.archive.is_file(), 'private_plaintext_archive_required')
        private_file(self.archive)
        require(file_hash(self.archive) == self.row['plaintext_sha256'], 'archive_hash_mismatch')
        required_free=2*1024**3 if completed else max(8*1024**3,4*self.row.get('expanded_bytes',0)+2*self.row.get('plaintext_bytes',0)+3*1024**3)
        require(shutil.disk_usage(self.root).free >= required_free, 'replacement_storage_below_bootstrap_backup_headroom')
        return marker, state

    def write(self, name, content, mode=0o600):
        path = path_at(self.root, name)
        data = content if isinstance(content, bytes) else content.encode()
        if path.exists() and path.read_bytes() == data:
            require(stat.S_IMODE(path.stat().st_mode) == mode and path.stat().st_uid == self.host.ids()[0]['root'], 'existing_managed_file_permissions_changed')
            return False
        atomic_bytes(path, data, mode); self.host.chown(path, 0, 0)
        return True

    @contextmanager
    def operation(self, name, before, proposed):
        with self.audit.step(name, str(self.root), before, proposed) as readback:
            yield readback

    def claim(self, marker, state):
        self.control.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(self.control.stat().st_uid == 0 and not self.control.stat().st_mode & 0o077, 'untrusted_rebuild_control')
        self.audit = Audit(self.control / 'actions.db', {'application_sha':self.row['source_sha'],
            'recovery_generation':self.row['generation'], 'manifest_sha256':digest(self.manifest),
            'toolchain_code_sha256':toolchain_code_hash()})
        if not state.exists():
            with self.operation('claim_target', {'fresh':True}, {'state':'REBUILD_ONLY'}) as result:
                import uuid
                target_id = uuid.uuid4().hex
                atomic_bytes(marker, (target_id + '\n').encode())
                atomic_json(state, {'target_id':target_id,'data_root':str(self.data),'generation':None,'completed':False})
                require(marker.read_text().strip() == json.loads(state.read_text())['target_id'], 'target_readback_failed')
                result.update(target_id=target_id, routing_authority=False)

    @contextmanager
    def locked(self, *, final_sync=False):
        marker,state=self.guard(final_sync=final_sync)
        self.control.mkdir(mode=0o700,parents=True,exist_ok=True)
        require(self.control.stat().st_uid==0 and not self.control.stat().st_mode & 0o077,'untrusted_rebuild_control')
        lock_path=path_at(self.root,'/var/lib/optibrain-rebuild/operation.lock')
        if lock_path.exists(): private_file(lock_path)
        fd=os.open(lock_path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a') as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise RebuildError('another_rebuild_operation_running')
            # Recheck target binding after taking the lock.
            marker,state=self.guard(final_sync=final_sync)
            self.claim(marker,state)
            atomic_json(self.control/'manifest.json',self.manifest)
            yield state

    def safety(self):
        with self.operation('safe_authority', {'policies':'fresh or previous closed generation'}, {'writers':'OFF','schedulers':'MASKED'}) as result:
            self.write('/etc/optibrain/rebuild-safety.env', ''.join(k+'='+v+'\n' for k,v in SAFETY.items()))
            policies = {'mutation-control.json':{'schema':1,'test_writes_enabled':False,'allowed_actions':[],
                    'real_canary_allowed':False,'lifecycle':{'enabled':False,'real_scopes':[],'test_scopes':[]}},
                'customer-communication-control.json':{'schema':1,'external_enabled':False,'test_enabled':False,'real_scopes':[]},
                'conversion-export-control.json':{'schema':1,'enabled':False,'destinations':{},'validated_families':{},'release_sha':None}}
            conversion=path_at(self.root,'/etc/optibrain/conversion-export-control.json')
            if conversion.exists():
                policies['conversion-export-control.json']=self.closed_conversion(json.loads(conversion.read_text()))
            for name, value in policies.items():
                self.write('/etc/optibrain/' + name, json.dumps(value,sort_keys=True)+'\n', 0o644 if name!='conversion-export-control.json' else 0o600)
            timers = [r['name'] for r in self.manifest['timers'] if r['name'].startswith(('opticable-', 'optibrain-'))]
            blocked = timers + list(RETIRED) + ['opticable-lifecycle-internal.service', 'opticable-customer-communications.service',
                         'opticable-phase12-test-runner.service', 'opticable-phase9-intake-receipts.service',
                         'opticable-phase10-service-events.service'] + list(APP_UNITS)
            installed=self.host.run(['systemctl','list-unit-files','--no-legend','--no-pager']).splitlines()
            names={line.split()[0] for line in installed if line.split()}
            stop=[u for u in blocked+['caddy.service'] if u in names]
            if stop: self.host.run(['systemctl','stop',*stop],timeout=360)
            for unit in blocked:
                path = self.root / 'etc/systemd/system' / unit
                if path.is_symlink():
                    require(os.readlink(path) == '/dev/null', 'unexpected_unit_symlink')
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.exists():
                        saved = path.with_name(path.name + '.rebuild-disabled')
                        require(not saved.exists() or saved.read_bytes() == path.read_bytes(), 'unit_preservation_conflict')
                        if not saved.exists(): path.rename(saved)
                        else: path.unlink()
                    path.symlink_to('/dev/null')
            self.host.run(['systemctl','daemon-reload'])
            result.update(writers='OFF',masks=len(blocked),verified=self.verify_safety())

    def verify_safety(self):
        policy = json.loads(path_at(self.root, '/etc/optibrain/mutation-control.json').read_text())
        customer = json.loads(path_at(self.root, '/etc/optibrain/customer-communication-control.json').read_text())
        conversion = json.loads(path_at(self.root, '/etc/optibrain/conversion-export-control.json').read_text())
        flags = env_file(path_at(self.root, '/etc/optibrain/rebuild-safety.env'))
        require(not policy.get('test_writes_enabled') and not policy.get('real_canary_allowed')
            and not policy.get('lifecycle',{}).get('enabled') and not policy.get('lifecycle',{}).get('real_scopes')
            and customer.get('external_enabled') is False and customer.get('test_enabled') is False
            and conversion.get('enabled') is False and all(not d.get('local_enabled') for d in conversion.get('destinations',{}).values()), 'authority_not_safe')
        require(all(flags.get(k) == v for k,v in SAFETY.items()), 'safety_environment_changed')
        require(not path_at(self.root, '/etc/optibrain/authorize-persistent-codex-development').exists(), 'persistent_development_authorized')
        return 'SAFE/OFF'

    @staticmethod
    def closed_conversion(value):
        spec=importlib.util.spec_from_file_location('rebuild_conversion_authority',REPO/'ops/phase15/recovery_authority.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.reset_conversion_authority(value)

    def install_packages(self):
        with self.operation('packages', {'installed':self.host.run(['dpkg-query','-W','-f=${binary:Package}\n'])}, {'required':BASE_PACKAGES}) as result:
            installed = self.host.run(['dpkg-query','-W','-f=${binary:Package}\n']).splitlines()
            missing = package_plan(installed)
            if missing:
                # Package postinst must not start Caddy while restore is incomplete.
                policy = path_at(self.root, '/usr/sbin/policy-rc.d')
                previous = policy.read_bytes() if policy.exists() else None
                previous_mode = stat.S_IMODE(policy.stat().st_mode) if policy.exists() else 0o755
                self.write('/usr/sbin/policy-rc.d', '#!/bin/sh\nexit 101\n', 0o755)
                try:
                    self.host.run(['apt-get','update'], timeout=600)
                    self.host.run(['apt-get','install','-y','--no-install-recommends',*missing], timeout=1200,
                        env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'})
                finally:
                    if previous is None: policy.unlink()
                    else: atomic_bytes(policy, previous, previous_mode)
            require(not package_plan(self.host.run(['dpkg-query','-W','-f=${binary:Package}\n']).splitlines()), 'packages_readback_failed')
            result.update(installed_required=BASE_PACKAGES)

    def install_node(self):
        with self.operation('node_runtime', {'required':NODE_VERSION}, {'sha256':NODE_SHA256}) as result:
            if shutil.which('node'):
                require(self.host.run(['node','--version']) == NODE_VERSION, 'different_node_runtime_requires_review')
            else:
                with tempfile.TemporaryDirectory(dir=self.control, prefix='node-') as temporary:
                    path = Path(temporary) / 'node.tar.xz'
                    with urllib.request.urlopen(NODE_URL, timeout=60) as source, path.open('wb') as dest:
                        shutil.copyfileobj(source, dest, 1024*1024)
                    require(path.stat().st_size < 100*1024**2 and file_hash(path) == NODE_SHA256, 'node_artifact_hash_mismatch')
                    self.host.run(['tar','-xJf',path,'-C','/usr/local','--strip-components=1','--no-same-owner'], timeout=120)
                require(self.host.run(['/usr/local/bin/node','--version']) == NODE_VERSION, 'node_readback_failed')
            self.host.run(['npm','--version'])
            node=path_at(self.root,'/usr/bin/node')
            if not node.exists(): node.symlink_to('/usr/local/bin/node')
            result.update(version=NODE_VERSION, artifact_sha256=NODE_SHA256)

    def users_directories(self):
        with self.operation('users_directories', {'named_identities':'existing or absent'}, {'service_users':'least privilege'}) as result:
            uid, gid = self.host.ensure_users()
            dirs = {'/etc/optibrain':(0,0,0o755),'/var/lib/optibrain-rebuild':(0,0,0o700),
                    '/opt/optibrain-releases':(0,0,0o755),'/var/backups/optibrain':(0,0,0o700),
                    '/var/log/optibrain':(0,0,0o700),'/run/optibrain-readiness':(0,0,0o755),
                    '/var/lib/opticable-api-platform':(0,0,0o755)}
            for name in ('opticable-workflow-api','opticable-password-pdf','opticable-omada-site'):
                dirs['/var/lib/'+name] = (uid[name],gid[name],0o750)
            dirs['/var/lib/optibrain'] = (0,0,0o700)
            dirs['/var/lib/opticable-api-platform/shared'] = (uid['opticable-workflow-api'],gid['siteandpassword'],0o2770)
            for name,(owner,group,mode) in dirs.items():
                path=path_at(self.root,name);path.mkdir(parents=True,exist_ok=True)
                self.host.chown(path,owner,group);path.chmod(mode)
                require(stat.S_IMODE(path.stat().st_mode)==mode, 'directory_mode_readback_failed')
            self.data.mkdir(mode=0o700,parents=True,exist_ok=True)
            self.host.chown(self.data,0,0);self.data.chmod(0o700)
            self.host.run(['timedatectl','set-timezone',self.manifest['timezone']])
            require(self.host.run(['timedatectl','show','-p','Timezone','--value'])==self.manifest['timezone'],
                    'timezone_readback_failed')
            result.update(names=sorted(uid.keys()), directories=len(dirs),data_root=str(self.data))

    def stage(self):
        destination = self.data / 'generations' / self.row['generation']
        with self.operation('restore_staging', {'generation':self.row['generation']}, {'databases':'all verified before promotion'}) as result:
            if (destination / 'verified.json').exists():
                saved=json.loads((destination/'verified.json').read_text())
                require(saved['plaintext_sha256']==self.row['plaintext_sha256'], 'staging_generation_conflict')
                for name, expected in self.row['expected_knowledge'].items():
                    require(database_snapshot(destination/name)==expected, 'staging_changed_on_rerun')
                from recovery import manifest_from_archive
                manifest=manifest_from_archive(self.archive)
                from recovery import validate_manifest
                validate_manifest(manifest,self.row)
            else:
                require(not destination.exists(), 'incomplete_staging_retained_inspect_before_retry')
                manifest, snapshots=stage_archive(self.archive,self.row,destination)
            result.update(generation=self.row['generation'],databases=len(self.row['databases']),snapshot_verified=True)
        return destination,manifest

    def source_runtime(self, staged):
        with self.operation('exact_source_runtime', {'source':'not promoted'}, {'sha':self.row['source_sha']}) as result:
            sha=self.row['source_sha']; repo=path_at(self.root,'/opt/opticable-api-platform')
            bundle=staged/'state/var/lib/optibrain/recovery-source/current.bundle'
            if not repo.exists():
                if bundle.is_file():
                    self.host.run(['git','init',self.control/'bundle-verification'])
                    self.host.run(['git','-C',self.control/'bundle-verification','bundle','verify',bundle])
                    self.host.run(['git','clone','--no-checkout',bundle,repo],timeout=180)
                else:
                    self.host.run(['git','clone','--no-checkout','https://github.com/yboucher97/opticable-api-platform.git',repo],timeout=300)
                self.host.run(['git','-C',repo,'checkout','--detach',sha])
            require(self.host.run(['git','-c','safe.directory='+str(repo),'-C',repo,'rev-parse','HEAD'])==sha, 'exact_source_checkout_mismatch')
            require(not self.host.run(['git','-c','safe.directory='+str(repo),'-C',repo,'diff','HEAD','--']), 'source_tracked_files_dirty')
            uid,gid=self.host.ids()
            # Backup invokes Git as engineering; services cannot edit this checkout.
            self.host.run(['chown','-R','optibrain:optibrain',repo],timeout=120)
            self.host.run(['chmod','-R','a+rX',repo],timeout=120)
            release=path_at(self.root,'/opt/optibrain-releases/'+sha)
            release.mkdir(mode=0o755,parents=True,exist_ok=True)
            for app,envname in [('workflow-api','venv'),('password-pdf-service','pdf-venv')]:
                requirements=repo/'apps'/app/'requirements.txt'; venv=release/envname
                receipt=release/(envname+'.json')
                expected={'requirements_sha256':file_hash(requirements),'source_sha':sha}
                if receipt.exists():
                    require(json.loads(receipt.read_text())==expected and (venv/'bin/python').exists(), 'venv_receipt_mismatch')
                else:
                    self.host.run(['python3','-m','venv',venv],timeout=180)
                    self.host.run([venv/'bin/python','-m','pip','install','--no-cache-dir','-r',requirements],timeout=900)
                    self.host.run([venv/'bin/python','-m','pip','check'],timeout=60)
                    atomic_json(receipt,expected)
                self.host.run(['chmod','-R','a+rX',venv],timeout=60)
                link=repo/'apps'/app/'.venv'
                if link.is_symlink(): require(link.resolve()==venv.resolve(), 'venv_link_conflict')
                else:
                    require(not link.exists(), 'venv_destination_conflict');link.symlink_to(venv)
            omada=repo/'apps/omada-site-service'; stamp=release/'omada.json'
            expected={'lock_sha256':file_hash(omada/'package-lock.json'),'source_sha':sha}
            if stamp.exists(): require(json.loads(stamp.read_text())==expected and (omada/'dist/server.js').is_file(), 'omada_receipt_mismatch')
            else:
                self.host.run(['npm','ci','--ignore-scripts','--cache',self.control/'npm-cache'],timeout=600,cwd=omada,
                    env={**os.environ,'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD':'1','ELECTRON_SKIP_BINARY_DOWNLOAD':'1'})
                self.host.run(['npm','run','build'],timeout=180,cwd=omada)
                atomic_json(stamp,expected)
            self.host.run(['chmod','-R','a+rX',omada/'node_modules',omada/'dist'],timeout=60)
            self.host.run(['chown','-R','root:root',release],timeout=60)
            result.update(sha=sha,python_dependencies='verified',omada='built',source_bundle_used=bundle.is_file())

    def install_definitions(self):
        with self.operation('reviewed_system_definitions', {'units':'masked'}, {'reviewed_hashes':'exact'}) as result:
            checked=[]
            for row in self.manifest['bootstrap']['reviewed_files']:
                destination=row['destination']; path=self.root/destination.lstrip('/')
                data=reviewed_bytes(row)
                if path.is_symlink() and os.readlink(path)=='/dev/null':
                    destination += '.rebuild-disabled'
                self.write(destination,data,int(row['mode'],8))
                require(file_hash(self.root/destination.lstrip('/'))==row.get('installed_sha256',row['sha256']), 'installed_definition_hash_mismatch')
                if row['destination'].endswith('.service'): checked.append(str(self.root/destination.lstrip('/')))
            # Final env overrides cannot be replaced by archived execution flags.
            for unit in APP_UNITS + tuple(r['name'] for r in self.manifest['services'] if r['name'].startswith(('opticable-','optibrain-')) and r['name'].endswith('.service') and 'agent-' not in r['name']):
                self.write('/etc/systemd/system/'+unit+'.d/98-rebuild-data.conf',
                           '[Unit]\nRequiresMountsFor='+' '.join(STATE_ROOTS)+'\n',0o644)
                if unit.startswith(('optibrain-backup','optibrain-phase2a')): continue
                self.write('/etc/systemd/system/'+unit+'.d/99-rebuild-safety.conf',
                           '[Service]\nEnvironmentFile=/etc/optibrain/rebuild-safety.env\n',0o644)
            with tempfile.TemporaryDirectory(dir=self.control,prefix='unit-review-') as temporary:
                reviewed=[]
                for item in checked:
                    p=Path(item);name=p.name.removesuffix('.rebuild-disabled')
                    copy=Path(temporary)/name;shutil.copyfile(p,copy);reviewed.append(copy)
                    dropins=self.root/'etc/systemd/system'/(name+'.d')
                    if dropins.exists():shutil.copytree(dropins,Path(temporary)/(name+'.d'))
                self.host.run(['systemd-analyze','verify',*reviewed],timeout=60)
            self.host.run(['systemctl','restart','systemd-journald.service'])
            result.update(definitions=len(self.manifest['bootstrap']['reviewed_files']), hashes='PASS',syntax='PASS')

    def promote(self,staged,manifest):
        with self.operation('promote_verified_state', {'generation':'staged','business_services':'masked'}, {'generation':self.row['generation']}) as result:
            uid,gid=self.host.ids()
            # Preflight ALL selected name ownership before any durable promotion.
            rows=[r for r in manifest['source_metadata'] if selected(r['source_path'])]
            require(all(r['owner'] in uid and r['group'] in gid for r in rows),'restore_named_owner_missing')
            for r in rows:
                if not r['source_path'].startswith('/var/lib/'): continue
                path=path_at(staged,'/'+r['backup_path'])
                if r['type']=='directory': path.mkdir(mode=0o700,parents=True,exist_ok=True)
                require(path.exists(),'durable_staged_file_missing')
                self.host.chown(path,uid[r['owner']],gid[r['group']]);path.chmod(int(r['mode'],8))
            # Online core snapshot replaces the skipped raw live DB metadata.
            core=staged/'state/var/lib/opticable-workflow-api/output/automation/automation.db'
            core.parent.mkdir(parents=True,exist_ok=True)
            if not core.exists(): shutil.copyfile(staged/'database/automation.db',core)
            self.host.chown(core,uid['opticable-workflow-api'],gid['opticable-workflow-api']);core.chmod(0o600)
            mounts=[]
            for canonical in STATE_ROOTS:
                source=path_at(staged,'/state'+canonical)
                require(source.is_dir(),'durable_root_missing')
                target=path_at(self.root,canonical);target.mkdir(parents=True,exist_ok=True)
                current=self.host.run(['findmnt','-rn','-M',target,'-o','SOURCE'],timeout=10) if os.path.ismount(target) else ''
                # mountpoint sources on Linux can contain filesystem subpaths; compare via inode.
                same=self.host.same_mount(source,target)
                if not same:
                    require(not current, 'different_live_generation_mounted')
                    require(not any(target.iterdir()),'durable_destination_not_empty')
                    self.host.run(['mount','--bind',source,target])
                require(self.host.same_mount(source,target),'bind_mount_readback_failed')
                mounts.append(str(source)+' '+canonical+' none bind 0 0')
            fstab=path_at(self.root,'/etc/fstab'); base=fstab.read_text() if fstab.exists() else ''
            begin='# BEGIN OPTIBRAIN REBUILD\n';end='# END OPTIBRAIN REBUILD\n'
            if begin in base:
                require(end in base,'invalid_managed_fstab');base=base.split(begin)[0]+base.split(end,1)[1]
            self.write('/etc/fstab',base.rstrip()+'\n'+begin+'\n'.join(mounts)+'\n'+end,0o644)
            for r in rows:
                if not r['source_path'].startswith('/etc/'): continue
                path=path_at(self.root,r['source_path'])
                if r['type']=='directory':path.mkdir(parents=True,exist_ok=True)
                else:
                    self.write(r['source_path'],(staged/r['backup_path']).read_bytes(),int(r['mode'],8))
                    require(file_hash(path)==file_hash(staged/r['backup_path']),'config_hash_readback_failed')
                self.host.chown(path,uid[r['owner']],gid[r['group']]);path.chmod(int(r['mode'],8))
            native_conversion=next((r for r in manifest['source_metadata'] if r['source_path']=='/etc/optibrain/conversion-export-control.json'),None)
            if native_conversion:
                reset=self.closed_conversion(json.loads((staged/native_conversion['backup_path']).read_text()))
                self.write('/etc/optibrain/conversion-export-control.json',json.dumps(reset,sort_keys=True)+'\n')
            for name,expected in self.row['expected_knowledge'].items():
                canonical='/var/lib/opticable-workflow-api/output/automation/automation.db' if name=='database/automation.db' else '/'+name.removeprefix('state/')
                require(database_snapshot(path_at(self.root,canonical))==expected,'promoted_knowledge_mismatch')
            result.update(generation=self.row['generation'], databases=len(self.row['databases']),mounts=len(mounts),history_preserved=True)

    def proxy_firewall(self):
        with self.operation('private_proxy_firewall_ssh', {'public_traffic':'old host'}, {'test_bind':'127.0.0.1:8080','ports':[self.manifest['bootstrap']['ssh_port'],80,443]}) as result:
            production=(REPO/'ops/rebuild/reviewed/caddy/opticable-api-platform.caddy').read_text()
            host=self.manifest['reverse_proxy']['production_host']
            require(production.startswith(host+' {'),'reviewed_proxy_host_mismatch')
            self.write('/etc/caddy/optibrain-production.caddy',production,0o644)
            self.write('/etc/caddy/Caddyfile',production.replace(host+' {','http://127.0.0.1:8080 {',1),0o644)
            self.host.run(['caddy','validate','--config','/etc/caddy/Caddyfile'],timeout=60)
            port=self.manifest['bootstrap']['ssh_port']
            # Preserve provisioning access. No copying SSH host keys or authorized_keys.
            self.host.run(['ufw','allow',str(port)+'/tcp'])
            for p in (80,443): self.host.run(['ufw','allow',str(p)+'/tcp'])
            self.host.run(['ufw','default','deny','incoming']);self.host.run(['ufw','default','allow','outgoing'])
            self.host.run(['ufw','--force','enable'])
            # OpenSSH takes the first value: place this before cloud-init files,
            # then verify the effective configuration, not syntax alone.
            self.write('/etc/ssh/sshd_config.d/00-optibrain-rebuild.conf','PasswordAuthentication no\nPubkeyAuthentication yes\n',0o644)
            self.verify_ssh()
            # Existing root key login stays usable until a named admin has logged in.
            self.host.run(['systemctl','reload','ssh.service'])
            self.host.run(['systemctl','enable','fail2ban.service'])
            result.update(proxy='VALID',private_origin='127.0.0.1:8080',firewall=self.host.run(['ufw','status']),ssh_host_keys='FRESH')

    def verify_ssh(self):
        self.host.run(['sshd','-t'])
        flags=dict(line.split(None,1) for line in self.host.run(['sshd','-T']).splitlines() if ' ' in line)
        require(flags.get('passwordauthentication')=='no' and flags.get('pubkeyauthentication')=='yes',
                'effective_ssh_key_only_policy_failed')
        return {'password_authentication':'OFF','public_key_authentication':'ON',
                'host_keys':'fresh; not copied','provisioning_access':'preserved'}

    def rebind(self):
        with self.operation('safe_release_registration', {'old_approval_pins':'archived'}, {'business_actions_enabled':False}) as result:
            spec=importlib.util.spec_from_file_location('rebuild_rebind',REPO/'ops/phase15/rebind_registration.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            result.update(module.rebind(self.root,self.row['source_sha']))
            current={'schema':1,'type':'optibrain.release','state':'recovery_contained','sha':self.row['source_sha'],
                     'api_version':self.row['api_version'],'recovery_generation':self.row['generation'],'writers_enabled':False,'at':now()}
            atomic_json(path_at(self.root,'/var/lib/optibrain/releases/current.json'),current)

    def boot_contained(self):
        with self.operation('contained_boot', {'apps':'masked'}, {'apps':'local read-only health'}) as result:
            require(self.verify_safety()=='SAFE/OFF','unsafe_before_boot')
            for unit in APP_UNITS:
                path=self.root/'etc/systemd/system'/unit
                if path.is_symlink():
                    require(os.readlink(path)=='/dev/null','unexpected_app_mask');path.unlink()
                    path.with_name(path.name+'.rebuild-disabled').rename(path)
            self.host.run(['systemctl','daemon-reload'])
            for unit in APP_UNITS:
                self.host.run(['systemctl','enable',unit]);self.host.run(['systemctl','start',unit])
                require(self.host.run(['systemctl','is-active',unit])=='active','contained_service_failed')
            self.host.run(['systemctl','start','caddy.service'])
            # Package-start inhibition is gone and the reviewed jails are active.
            self.host.run(['systemctl','start','fail2ban.service'])
            result.update(apps='active',authority=self.verify_safety(),business_timers='MASKED')

    def verify(self):
        with self.locked() as state:
            saved=json.loads(state.read_text())
            require(saved.get('generation')==self.row['generation'],'restore_required_before_verify')
            from verification import verify_host
            try:report=verify_host(self,run_providers=True,run_backup=False)
            except BaseException as exc:
                saved['completed']=False;atomic_json(state,saved);self.failure(exc);raise
            if not report['ready_for_owner_cutover']:
                self.safety();report['authority']=self.verify_safety()
            saved['completed']=report['ready_for_owner_cutover'];atomic_json(state,saved)
            atomic_json(self.control/'result.json',report)
            return report

    def failure(self,exc):
        containment='UNKNOWN'
        try:self.safety();containment=self.verify_safety()
        except Exception:pass
        report={'schema':1,'type':'optibrain.rebuild.result','at':now(),'ready_for_owner_cutover':False,'authority':containment,
            'mode':'MIGRATION_VALIDATION' if self.migration else 'DISASTER_RESTORE',
            'generation':self.row['generation'],'source_sha':self.row['source_sha'],'api_version':self.row['api_version'],
            'checks':{},'owner_approval':None,'last_backup':None,'last_restore_test':None,
            'last_full_rebuild_test':None,'recovery_confidence':'CRITICAL FAILURE; CUTOVER DENIED',
            'blocker':str(exc) if isinstance(exc,RebuildError) else type(exc).__name__,
            'dns_changes':0,'production_migration':0,'owner_control_center':'NOT BUILT'}
        atomic_json(self.control/'result.json',report)
        return report

    def run(self):
        with self.locked() as state:
            return self.apply(state)

    def apply(self,state):
        """Caller holds the shared restore/verify/final-sync lock."""
        try:
            saved=json.loads(state.read_text())
            if saved.get('completed') and saved.get('generation')==self.row['generation']:
                from verification import verify_host
                report=verify_host(self,run_providers=True,run_backup=False)
                if not report['ready_for_owner_cutover']:
                    self.safety();report['authority']=self.verify_safety()
                saved['completed']=report['ready_for_owner_cutover'];atomic_json(state,saved)
                atomic_json(self.control/'result.json',report)
                return report
            # Mask before downloads; repeatable denial after every interrupted phase.
            self.safety();self.install_packages();self.install_node();self.users_directories()
            staged,manifest=self.stage();self.source_runtime(staged);self.install_definitions()
            self.promote(staged,manifest);self.safety();self.rebind();self.proxy_firewall();self.boot_contained()
            from verification import verify_host
            report=verify_host(self,run_providers=True,run_backup=True)
            if not report['ready_for_owner_cutover']:
                self.safety();report['authority']=self.verify_safety()
            saved=json.loads(state.read_text());saved.update(generation=self.row['generation'],pending_generation=None,completed=report['ready_for_owner_cutover'])
            atomic_json(state,saved);atomic_json(self.control/'result.json',report)
            return report
        except BaseException as exc:
            # Do not erase staging or evidence. Contain only this replacement.
            self.failure(exc)
            raise
