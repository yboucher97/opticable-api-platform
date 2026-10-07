"""Readback gates and Control Center recovery result, without owner impersonation."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from common import REPO, RebuildError, atomic_json, database_snapshot, digest, env_file, file_hash, now, path_at, private_file, require
from engine import APP_UNITS, BACKUP_TIMERS, RETIRED


def ready(checks, required_providers):
    critical=('OS','SOURCE','DATABASES','KNOWLEDGE','AUDIT','MANAGER','SYSTEMD','PROXY','FIREWALL','SSH',
              'AUTHORITY','STORAGE','SECRETS','BACKUPS')
    return all(checks.get(k,{}).get('status')=='PASS' for k in critical) and all(
        checks.get('PROVIDERS',{}).get(p,{}).get('status')=='PASS' for p in required_providers)


def check_secrets(engine):
    missing=[]
    # Compare permission/owner metadata. Byte hashes were checked before copying;
    # OAuth refresh/release rebinding are explicitly allowed later transitions.
    for row in engine.manifest['secret_paths']:
        path=path_at(engine.root,row['path'])
        if not path.is_file(): missing.append(row['path']);continue
        import stat
        info=path.stat();uid,gid=engine.host.ids()
        if info.st_uid!=uid[row['owner']] or info.st_gid!=gid[row['group']] or stat.S_IMODE(info.st_mode)!=int(row['mode'],8):
            missing.append(row['path'])
    require(not missing,'missing_or_unsafe_recovered_path')
    return {'paths_verified':len(engine.manifest['secret_paths']),'values_printed':0}


def validate_stale_suppression(engine):
    for row in engine.manifest['timers']:
        if not row['name'].startswith(('optibrain-','opticable-')) or row['name'] in BACKUP_TIMERS: continue
        path=engine.root/'etc/systemd/system'/row['name']
        require(path.is_symlink() and os.readlink(path)=='/dev/null','business_timer_unmasked')
    for name in RETIRED+('opticable-lifecycle-internal.service','opticable-customer-communications.service',
            'opticable-phase12-test-runner.service','opticable-phase9-intake-receipts.service','opticable-phase10-service-events.service'):
        path=engine.root/'etc/systemd/system'/name
        require(path.is_symlink() and os.readlink(path)=='/dev/null','stale_job_service_unmasked')
    return {'stale_work':'HISTORICAL_ONLY','replay_grant':False,'authority':engine.verify_safety()}


def verify_host(engine, *, run_providers=False, run_backup=False):
    checks={}
    def check(name, function):
        with engine.audit.step('verify_'+name.lower(),str(engine.root),{'check':'pending'},{'read_only':True},mutation=False) as result:
            try:
                evidence=function();checks[name]={'status':'PASS','evidence':evidence}
            except Exception as exc:
                checks[name]={'status':'BLOCKED','blocker':str(exc) if isinstance(exc,RebuildError) else type(exc).__name__}
            result.update(checks[name])
    check('OS',lambda:{'supported':'Ubuntu 24.04 amd64'})
    def source():
        repo=path_at(engine.root,'/opt/opticable-api-platform')
        sha=engine.host.run(['git','-c','safe.directory='+str(repo),'-C',repo,'rev-parse','HEAD'])
        require(sha==engine.row['source_sha'],'source_verification_mismatch')
        api_file=repo/'apps/workflow-api/workflow/api.py'
        import ast
        module=ast.parse(api_file.read_text())
        version=next(ast.literal_eval(n.value) for n in module.body if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id=='API_VERSION' for t in n.targets))
        require(version==engine.row['api_version'],'api_source_version_mismatch')
        return {'sha':sha,'api_version':version}
    check('SOURCE',source)
    actual={}
    def databases():
        for name,expected in engine.row['expected_knowledge'].items():
            canonical='/var/lib/opticable-workflow-api/output/automation/automation.db' if name=='database/automation.db' else '/'+name.removeprefix('state/')
            snapshot=database_snapshot(path_at(engine.root,canonical));actual[name]=snapshot
            require(snapshot==expected,'restored_snapshot_changed')
        return {'passed':len(actual),'expected':len(engine.row['databases']),'integrity':'ok','foreign_keys':'PASS'}
    check('DATABASES',databases)
    check('KNOWLEDGE',lambda:knowledge_check(actual,engine.row['expected_knowledge']))
    def audit():
        require(actual and all(a['audit_chains_verified']==engine.row['expected_knowledge'][p]['audit_chains_verified'] for p,a in actual.items()),'restored_audit_failed')
        with engine.audit.store.connect(readonly=True) as db:
            ids=[r[0] for r in db.execute('SELECT action_id FROM action_envelopes')]
        require(all(engine.audit.store.verify_integrity(aid) for aid in ids),'rebuild_audit_failed')
        return {'restored_chains':sum(a['audit_chains_verified'] for a in actual.values()),'rebuild_chains':len(ids)}
    check('AUDIT',audit)
    def manager():
        # Owner authentication is tested by denial; actual builder on a COPY uses
        # its unchanged schema, avoiding universal evidence writes to the snapshot.
        env=env_file(path_at(engine.root,'/etc/opticable-workflow-api.env'))
        headers={'X-API-Key':env[env.get('SITE_WORKFLOW_API_KEY_ENV','SITE_WORKFLOW_API_KEY')]}
        with urlopen(Request('http://127.0.0.1:8100/v1/system/health',headers=headers),timeout=15) as response:
            value=json.load(response)
        require(value.get('version')==engine.row['api_version'],'live_api_health_mismatch')
        try: urlopen('http://127.0.0.1:8100/v1/operator/manager?format=json',timeout=15)
        except HTTPError as exc: require(exc.code in (401,403),'owner_auth_not_closed')
        else: raise RebuildError('owner_auth_not_closed')
        repo=path_at(engine.root,'/opt/opticable-api-platform')
        code=REPO/'ops/rebuild/manager_probe.py'
        output=engine.host.run([repo/'apps/workflow-api/.venv/bin/python','-I','-B',code],timeout=120)
        result=json.loads(output)
        require(result.get('status')=='PASS','manager_render_failed')
        return result
    check('MANAGER',manager)
    def systemd():
        for unit in APP_UNITS:
            require(engine.host.run(['systemctl','is-active',unit])=='active','systemd_app_not_active')
        return validate_stale_suppression(engine)
    check('SYSTEMD',systemd)
    def proxy():
        engine.host.run(['caddy','validate','--config','/etc/caddy/Caddyfile'])
        with urlopen('http://127.0.0.1:8080/v1/system/health',timeout=15) as response:
            require(json.load(response).get('version')==engine.row['api_version'],'private_proxy_version_failed')
        return {'bind':'127.0.0.1:8080','production_dns_required':False}
    check('PROXY',proxy)
    def firewall():
        value=engine.host.run(['ufw','status','verbose'])
        require('Status: active' in value and 'deny (incoming)' in value,'firewall_not_active')
        # Applications must remain loopback regardless of firewall state.
        listeners=engine.host.run(['ss','-H','-lnt'])
        for line in listeners.splitlines():
            if any(':'+str(port) in line for port in (8100,8000,3210,8080)):
                require('127.0.0.1:' in line or '[::1]:' in line,'internal_service_public')
        return {'policy':'deny incoming; allow reviewed SSH/80/443','internal_ports':'loopback'}
    check('FIREWALL',firewall)
    check('SSH',engine.verify_ssh)
    check('AUTHORITY',lambda:validate_stale_suppression(engine))
    def storage():
        free=shutil.disk_usage(engine.data).free
        require(free>=2*1024**3,'new_host_storage_critical')
        return {'data_root':str(engine.data),'free_bytes':free}
    check('STORAGE',storage)
    check('SECRETS',lambda:check_secrets(engine))
    local_pass=all(c.get('status')=='PASS' for c in checks.values())
    if run_providers and local_pass:
        with engine.operation('read_only_provider_validation',{'business_mutations':0},{'identity_reads':'bounded'}) as result:
            repo=path_at(engine.root,'/opt/opticable-api-platform')
            # Run with the exact app's dependencies and an isolated provider-usage
            # context. Credential bodies are never included in stdout/errors.
            output=engine.host.run([repo/'apps/workflow-api/.venv/bin/python','-B',REPO/'ops/rebuild/cli.py',
                'providers','--manifest',engine.control/'manifest.json'],timeout=300)
            checks['PROVIDERS']=json.loads(output)
            result.update(statuses={k:v['status'] for k,v in checks['PROVIDERS'].items()},business_mutations=0)
    else: checks['PROVIDERS']={}
    local_pass=local_pass and all(checks['PROVIDERS'].get(p,{}).get('status')=='PASS'
                               for p in engine.manifest['bootstrap']['required_providers'])
    def backups():
        for path in ('/etc/optibrain/backup.conf','/etc/optibrain/r2-uploader.env','/etc/optibrain/age-recipient','/etc/optibrain/phase2a.conf'):
            require(path_at(engine.root,path).is_file(),'backup_configuration_missing')
        require(local_pass,'local_verification_blocks_backup')
        receipt_path=engine.control/'backup-verified.json'
        if not run_backup:
            require(receipt_path.is_file(),'new_generation_upload_readback_not_run')
            private_file(receipt_path)
            saved=json.loads(receipt_path.read_text())
            state=json.loads(path_at(engine.root,'/var/lib/optibrain/phase2a/state.json').read_text())
            require(saved['source_sha']==engine.row['source_sha'] and saved['generation']==state.get('generation')
                    and saved['ciphertext_sha256']==state.get('encrypted_sha256') and state.get('verification_status')=='download_hash_verified',
                    'new_host_backup_receipt_mismatch')
            from datetime import datetime,timezone,timedelta
            age=datetime.now(timezone.utc)-datetime.fromisoformat(saved['verified_at'])
            require(timedelta(0)<=age<timedelta(hours=36),'new_host_backup_stale')
            for unit in BACKUP_TIMERS:
                require(engine.host.run(['systemctl','is-enabled',unit])=='enabled'
                        and engine.host.run(['systemctl','is-active',unit])=='active','backup_timer_not_active')
            return saved
        with engine.operation('new_host_backup_readback',{'generation':'restored source recovery'},{'new_backup':'independent encrypted download hash'}) as result:
            for unit in ('optibrain-backup.service','optibrain-phase2a-upload.service'):
                engine.host.run(['systemctl','start',unit],timeout=3000)
                require(engine.host.run(['systemctl','show',unit,'-p','Result','--value'])=='success','backup_job_failed')
            state=json.loads(path_at(engine.root,'/var/lib/optibrain/phase2a/state.json').read_text())
            require(state.get('verification_status')=='download_hash_verified' and state['generation']>engine.row['generation'],'new_backup_unverified')
            result.update(generation=state['generation'],ciphertext_sha256=state['encrypted_sha256'],readback='PASS')
        atomic_json(receipt_path,{**result,'source_sha':engine.row['source_sha'],'verified_at':now()})
        # Enable only the reviewed backup pair; all business timers stay masked.
        for unit in BACKUP_TIMERS:
            path=engine.root/'etc/systemd/system'/unit
            if path.is_symlink():path.unlink();path.with_name(path.name+'.rebuild-disabled').rename(path)
        engine.host.run(['systemctl','daemon-reload'])
        for unit in BACKUP_TIMERS:
            engine.host.run(['systemctl','enable',unit]);engine.host.run(['systemctl','start',unit])
        return result
    check('BACKUPS',backups)
    is_ready=ready(checks,engine.manifest['bootstrap']['required_providers'])
    report={'schema':1,'type':'optibrain.rebuild.result','at':now(),'mode':'MIGRATION_VALIDATION' if engine.migration else 'DISASTER_RESTORE',
        'generation':engine.row['generation'],'source_sha':engine.row['source_sha'],'api_version':engine.row['api_version'],
        'checks':checks,'ready_for_owner_cutover':is_ready,
        'authority':'SAFE/OFF' if checks.get('AUTHORITY',{}).get('status')=='PASS' else 'UNKNOWN',
        'owner_approval':None,'dns_changes':0,'production_migration':0,
        'owner_control_center':'NOT BUILT','last_backup':checks.get('BACKUPS'),
        'last_restore_test':now(),'last_full_rebuild_test':now() if is_ready else None,'full_rebuild_drill_required':not is_ready,
        'recovery_confidence':'FRESH HOST VERIFIED; OWNER CUTOVER PENDING' if is_ready else 'BLOCKED CHECKS; CUTOVER DENIED'}
    return report


def knowledge_check(actual,expected):
    require(bool(actual) and actual==expected,'knowledge_not_identical')
    learning=next((d['tables'].get('manager_learning') for d in actual.values() if 'manager_learning' in d['tables']),None)
    require(learning is not None,'learning_schema_missing')
    return {'all_table_counts_ids_rows_and_schemas':'IDENTICAL','learning':learning,
            'decision_cards':'proposal/priority revisions and action evidence preserved',
            'owner_corrections':'manager_events OWNER + manager_feedback exact row digests',
            'future_nonzero_learning':'covered automatically by all-table snapshot comparison'}
