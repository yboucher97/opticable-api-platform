#!/usr/bin/env python3
"""Independent, bounded read-only migration watchdog probes. No business writes."""
import json,os,shutil,subprocess,sys,time
from pathlib import Path
from urllib.request import Request,urlopen
from common import atomic_json,env_file,require
from durable_migration import Control,load_profile,watchdog,profile_binding


def check(profile):
    result={'checked_epoch':time.time(),'status':'PASS','issues':[],'timed_maintenance_ready':False,
            'timed_maintenance_blockers':['native_forms_new_submission_hold_not_approved_or_applied','source_reboot_fence_and_stage_rollback_not_armed','maintenance_scope_approvals_missing','stage_adapter_review_and_binding_required']}
    def probe(name,fn):
        try:result[name]=fn()
        except Exception as e:result[name]={'status':'BLOCKED','error':type(e).__name__};result['issues'].append(name+'_failed')
    def source():
        command=['/usr/bin/ssh','-i','/etc/optibrain/migration/source-probe-key','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/etc/optibrain/migration/source-known-hosts','-o','ConnectTimeout=10','optibrain@148.113.249.7','status']
        p=subprocess.run(command,capture_output=True,text=True,timeout=30);require(p.returncode==0,'source_probe_failed');v=json.loads(p.stdout)
        require(v['host']==profile['source']['host'] and v['production_sha']==profile['production_sha'],'source_identity_changed')
        if v.get('fenced') and not v.get('freeze_transition'):
            require(all(v['services'][u] in ('inactive','failed') for u in v['services'] if u!='caddy.service'),'fenced_source_writer_active')
        elif not v.get('freeze_transition'):
            require(v['API'].get('ok') is True or v['API'].get('status')=='ok','source_api_unhealthy')
            require(all(s=='active' for s in v['services'].values()),'source_services_unhealthy')
        if v['root_free_bytes']<256*1024**2:result['issues'].append('source_disk_critical')
        if v['root_free_bytes']<64*1024**2:result['issues'].append('source_disk_emergency')
        return v
    probe('source',source)
    env=env_file('/etc/opticable-workflow-api.env')
    def target():
        require(os.uname().nodename==profile['target']['host'],'target_identity_changed')
        key=env[env.get('SITE_WORKFLOW_API_KEY_ENV','SITE_WORKFLOW_API_KEY')]
        control=Control('/var/lib/optibrain-rebuild/actions.db',profile['execution_id'])
        for stage in ('TARGET_SYNCHRONIZED','INTAKE_RELEASED'):
            attempt=control.attempt(stage)
            if attempt and attempt.get('state')=='ATTEMPTED' and time.time()<attempt.get('deadline_epoch',0):
                unit=subprocess.check_output(['systemctl','show',attempt['unit'],'-p','ActiveState','--value'],text=True).strip()
                if unit in ('active','activating'):
                    return {'host':os.uname().nodename,'API':{'status':'approved_isolated_maintenance'},'root_free_bytes':shutil.disk_usage('/').free,'all_45_flags_off':None,'active_reviewed_stage':stage}
        with urlopen(Request('http://127.0.0.1:8100/v1/system/health',headers={'X-API-Key':key}),timeout=10) as response:h=json.load(response)
        require(h.get('ok') is True or h.get('status')=='ok','target_api_unhealthy')
        free=shutil.disk_usage('/').free
        state=Control('/var/lib/optibrain-rebuild/actions.db',profile['execution_id']).state() or {}
        minimum=12*1024**3 if 'TARGET_SYNCHRONIZED' in state.get('completed_stages',[]) else 48*1024**3
        if free<minimum:result['issues'].append('target_capacity_below_final_sync_budget')
        sys.path.insert(0,'/opt/optibrain-rebuild-toolchain/migration-20261027/ops/rebuild')
        from engine import APP_UNITS,SAFETY
        flags={}
        for unit in APP_UNITS:
            pid=subprocess.check_output(['systemctl','show',unit,'-p','MainPID','--value'],text=True).strip();require(pid!='0','target_service_inactive')
            values=dict(x.split(b'=',1) for x in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0') if b'=' in x)
            flags[unit]=all(values.get(k.encode(),b'').decode()==v for k,v in SAFETY.items())
        require(all(flags.values()),'target_automation_authority_changed')
        return {'host':os.uname().nodename,'API':{'ok':h.get('ok') is True or h.get('status')=='ok','version':h.get('version')},'root_free_bytes':free,'all_45_flags_off':all(flags.values())}
    probe('target',target)
    def edge():
        sys.path.insert(0,'/opt/opticable-api-platform/apps/workflow-api');os.environ.update(env)
        from workflow.config import load_settings
        from workflow.cloudflare_api import CloudflareApiClient
        c=CloudflareApiClient(load_settings().cloudflare)
        prefix='/accounts/81d07d311d1b51e5e04b451d1f254850/queues/31c6f7026fe142d8959a09613b87c5dd'
        def get(path):
            v=c.request(path)['data'];require(v.get('success') is True,'edge_read_failed');return v['result']
        queue=get(prefix);metrics=get(prefix+'/metrics');dns=get('/zones/ea7b4f245feb0a98fb5534e73e761970/dns_records/8f10227bdeaa87597fd71cf7d499f133')
        require(queue['queue_id']=='31c6f7026fe142d8959a09613b87c5dd','queue_identity_changed')
        state=Control('/var/lib/optibrain-rebuild/actions.db',profile['execution_id']).state() or {}
        expected='15.235.100.76' if state.get('authority')=='NEW' else '148.113.249.7'
        if dns.get('content')!=expected:result['issues'].append('dns_authority_mismatch')
        if queue.get('settings',{}).get('delivery_paused') and not state.get('hold_started_epoch'):result['issues'].append('untracked_queue_hold')
        oldest=metrics.get('oldest_message_timestamp_ms',0)
        if metrics.get('backlog_count',0)>0:
            if not oldest:result['issues'].append('queue_age_unverified')
            elif time.time()-oldest/1000+3600>=queue.get('settings',{}).get('message_retention_period',0):result['issues'].append('queue_retention_risk')
        return {'queue_id':queue['queue_id'],'queue_settings':queue.get('settings',{}),'metrics':metrics,'oldest_message_age_seconds':max(0,time.time()-metrics.get('oldest_message_timestamp_ms',0)/1000) if metrics.get('oldest_message_timestamp_ms') else 0,'DNS':{k:dns.get(k) for k in ['name','content','proxied','ttl']}}
    probe('edge',edge)
    def backups():
        units={}
        for u in ['optibrain-backup.service','optibrain-phase2a-upload.service']:
            rows=subprocess.check_output(['systemctl','show',u,'-p','Result,ExecMainStatus,ExecMainExitTimestamp'],text=True)
            units[u]=dict(x.split('=',1) for x in rows.splitlines() if '=' in x)
            require(units[u].get('Result')=='success' and units[u].get('ExecMainStatus')=='0','target_backup_service_failed')
        journal=Path('/var/lib/optibrain/phase2a/audit.jsonl')
        require(journal.stat().st_size<10*1024**2,'backup_audit_read_limit')
        rows=[json.loads(line) for line in journal.read_text().splitlines()]
        generations=[r for r in rows if r.get('event')=='generation_verified']
        require(bool(generations),'offhost_backup_verification_missing')
        last=generations[-1];generation=last['generation']
        from datetime import datetime
        require(0<=time.time()-datetime.fromisoformat(last['time']).timestamp()<36*3600,'offhost_backup_verification_stale')
        matches=[r for r in rows if r.get('event')=='download_hash_verified' and str(r.get('key','')).endswith('/'+generation+'.tar.gz.age')]
        require(bool(matches),'encrypted_archive_full_readback_missing')
        for unit in ['optibrain-backup.timer','optibrain-phase2a-upload.timer']:
            require(subprocess.check_output(['systemctl','is-active',unit],text=True).strip()=='active','backup_timer_inactive')
        return {'services':units,'verified_generation':generation,'verification_at':last['time'],
                'encrypted_archive_sha256':matches[-1]['sha256'],'offhost_full_readback_record':True,
                'protects_current_source':False,'journal_sha256':__import__('hashlib').sha256(journal.read_bytes()).hexdigest()}
    probe('backups',backups)
    result['issues']=sorted(set(result['issues']))
    # The documented nearly-full source is usable only with RAM capture and >=64MiB.
    hard=[x for x in result['issues'] if x!='source_disk_critical']
    result['status']='PASS' if not hard else 'BLOCKED'
    if profile.get('version',1)==2:
        blockers=list(hard)
        try:
            from migration_adapters import Live
            live=Live(profile);source=live.source('status')
            require(source.get('persistent_fence_installed'),'source_fence_missing')
            try:proof=live.current_proofs()
            except Exception:
                refreshed=subprocess.run(['/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python','-B',str(Path(__file__).with_name('migration_window.py'))],capture_output=True,timeout=120)
                require(refreshed.returncode==0,'safe_window_verification_failed');proof=live.current_proofs()
            require(proof.get('rollback') and proof.get('reboot_fence'),'rollback_or_fence_fixture_missing')
            require(not (live.c.state() or {}).get('notification_failure'),'notification_failure_unresolved')
        except Exception as e:blockers.append(str(e) if isinstance(e,ValueError) else type(e).__name__)
        result['timed_maintenance_blockers']=sorted(set(blockers))
        result['timed_maintenance_ready']=not blockers

    return result


def main():
    p=load_profile('/etc/optibrain/migration/profile.json');c=Control('/var/lib/optibrain-rebuild/actions.db',p['execution_id'])
    value=check(p);atomic_json('/var/lib/optibrain-rebuild/migration-health.json',value)
    w=watchdog(c,p,value)
    if p.get('version',1)==2:
        from migration_adapters import Live,conditional_rollback
        state=c.state() or {}
        try:Live(p).source('heartbeat',extra={'window_complete':state.get('status')=='COMPLETE','new_intake_exposed':('INTAKE_RELEASED' in state.get('completed_stages',[]))})
        except Exception:pass  # Separate source supervisor still retains the reboot fence.
        if any(x in w['issues'] for x in ('hold_rollback_review_due','CRITICAL_hold_limit_reached')) or state.get('status')=='FAILED' and state.get('hold_started_epoch'):
            try:conditional_rollback(p)
            except Exception as e:c.transition({'status':'REQUIRES_OWNER','blocker':'conditional_rollback_blocked:'+str(e),'rollback':'Keep existing hold/fence; no blind resume or authority reversal'},'rollback_blocked')

    # Send meaningful, deduplicated incidents; never routine heartbeat messages.
    incidents=[]
    if 'source_disk_critical' in value['issues']:incidents.append(('CRITICAL','source-disk-critical'))
    for issue in value['issues']:
        if issue.endswith('_failed') or issue in ['source_disk_emergency','queue_retention_risk','queue_age_unverified','dns_authority_mismatch','untracked_queue_hold']:incidents.append(('CRITICAL','health:'+issue))
    if any('hold_' in x for x in w['issues']):incidents.append(('CRITICAL','hold-deadline'))
    if 'runner_heartbeat_stale' in w['issues']:incidents.append(('BLOCKED','runner-heartbeat-stale'))
    state=c.state() or {}
    if state.get('status')=='REQUIRES_OWNER':incidents.append(('BLOCKED','requires-owner:'+__import__('hashlib').sha256(str(state.get('blocker')).encode()).hexdigest()[:12]))
    if state.get('status')=='FAILED':incidents.append(('CRITICAL','runner-failed:'+str(state.get('current_stage'))))
    if state.get('status') in ['ROLLING_BACK','ROLLED_BACK']:incidents.append(('ROLLBACK','rollback:'+str(state.get('status'))))
    if state.get('status')=='COMPLETE' and state.get('authority')=='NEW' and value['status']=='PASS':incidents.append(('SUCCESS','verified-complete'))
    if not state.get('notification_test',{}).get('state')=='DELIVERED':incidents=[]
    if incidents:
        from owner_notifications import notify
        for kind,incident in incidents:
            try:notify(c,p,'/etc/optibrain/migration/owner-notification-policy.json',kind,incident)
            except Exception as e:
                if (c.state() or {}).get('notification_failure')!=type(e).__name__:c.transition({'notification_failure':type(e).__name__},'notification_failure')
    sealing=subprocess.run(['/usr/bin/python3','-B',str(Path(__file__).with_name('migration_checkpoint.py'))],capture_output=True,text=True,timeout=90)
    if sealing.returncode!=0:
        if (c.state() or {}).get('checkpoint_failure')!='OffhostCheckpointFailed':c.transition({'checkpoint_failure':'OffhostCheckpointFailed'},'checkpoint_failed')
    # Publish only meaningful checkpoints, never one report per heartbeat.
    with c.connect() as db:marker=db.execute('SELECT max(event_id) FROM action_evidence').fetchone()[0]
    sync=Path('/var/lib/optibrain-rebuild/migration-report-sync.json')
    previous=json.loads(sync.read_text()) if sync.exists() else {}
    template=Path('/recovery/migration-preparation/autonomous-20261101/owner-status.txt')
    if template.exists() and previous.get('canonical_event_id')!=marker:
        from common import atomic_bytes
        import pwd,hashlib
        receipt=Path('/var/lib/optibrain-rebuild/migration-offhost.json')
        text=template.read_text()+'\nLATEST DURABLE CONTROL CHECKPOINT (America/Toronto timestamps)\n'+json.dumps(c.state(),indent=2,sort_keys=True)+'\nCURRENT INDEPENDENT HEALTH\n'+json.dumps(value,indent=2,sort_keys=True)+'\nOFF-HOST CONTROL READBACK\n'+(receipt.read_text() if receipt.exists() else 'BLOCKED')+'\n'
        data=text.encode();require(len(data)<=65536,'owner_report_size_limit')
        owner=pwd.getpwnam('optibrain')
        for name in ['optibrain-migration-progress-20261101.txt','optibrain-autonomous-migration-20261101.txt','optibrain-executor-completion-20261101.txt']:
            path=Path('/home/optibrain')/name;atomic_bytes(path,data,0o600);os.chown(path,owner.pw_uid,owner.pw_gid)
        cmd=['/usr/bin/ssh','-i','/etc/optibrain/migration/source-probe-key','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/etc/optibrain/migration/source-known-hosts','-o','ConnectTimeout=10','optibrain@148.113.249.7','publish-report']
        published=subprocess.run(cmd,input=data,capture_output=True,timeout=20)
        require(published.returncode==0,'source_owner_report_publish_failed')
        proof=json.loads(published.stdout);require(proof.get('status')=='PASS' and proof.get('report_sha256')==hashlib.sha256(data).hexdigest(),'source_owner_report_readback_failed')
        atomic_json(sync,{'canonical_event_id':marker,'report_sha256':proof['report_sha256'],'at':time.time(),'source_and_target_files':'PASS'})
    print(json.dumps({'status':value['status'],'issues':value['issues'],'watchdog':w,'control_offhost_status':'PASS' if sealing.returncode==0 else 'BLOCKED'}))

if __name__=='__main__':main()
