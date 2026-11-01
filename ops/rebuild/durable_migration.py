#!/usr/bin/env python3
"""Durable operator orchestration in the existing recovery Action Evidence DB.

No business event storage. No implicit approval. Commands and independent
readbacks must be root-owned, hash-pinned, explicitly bound in the owner package.
A crash after an effect intent reconciles before any retry; uncertain provider
writes are never retried. Installing the observer profile grants no maintenance.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid
from zoneinfo import ZoneInfo
from common import Audit, RebuildError, atomic_json, atomic_bytes, digest, file_hash, private_file, require, trusted_manifest

SCOPES = ('queue_hold','native_forms_maintenance','source_freeze_final_sync',
          'new_only_intake_release','worker_hold_deployment','dns_cutover',
          'crm_notification_recreation','safe_queue_observer_resume')
STAGES = ('PREPARED','APPROVED','QUEUE_HELD','SOURCE_FROZEN','RECOVERY_VERIFIED',
          'TARGET_SYNCHRONIZED','PRIVATE_VERIFIED','CUTOVER','INTAKE_VERIFIED','COMPLETE')
TERMINAL = {'COMPLETE','FAILED','ROLLED_BACK'}
TORONTO = ZoneInfo('America/Toronto')


def timestamp():
    return datetime.now(timezone.utc)


def stamp():
    return timestamp().astimezone(TORONTO).isoformat()


class Control:
    def __init__(self, database, run_id):
        require(bool(run_id) and all(c.isalnum() or c in '-_' for c in run_id), 'invalid_execution_id')
        self.path, self.run_id = Path(database), run_id
        self.audit = Audit(self.path)
        self.canonical = importlib.import_module(self.audit.store.__class__.__module__)
        with self.connect() as db:
            self.audit.store.setup(db)
            db.execute('CREATE TABLE IF NOT EXISTS migration_executions(execution_id TEXT PRIMARY KEY, state_json TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS migration_attempts(execution_id TEXT, stage TEXT, attempt INTEGER, state_json TEXT NOT NULL, PRIMARY KEY(execution_id,stage,attempt))')
            db.execute('CREATE TABLE IF NOT EXISTS migration_alerts(execution_id TEXT, incident TEXT, state_json TEXT NOT NULL, PRIMARY KEY(execution_id,incident))')
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def state(self):
        with self.connect() as db:
            r = db.execute('SELECT state_json FROM migration_executions WHERE execution_id=?',(self.run_id,)).fetchone()
            return json.loads(r[0]) if r else None

    def transition(self, changes, event):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state_json FROM migration_executions WHERE execution_id=?',(self.run_id,)).fetchone()
            before = json.loads(row[0]) if row else None
            after = {**(before or {}), **changes, 'execution_id':self.run_id,'updated_at':stamp()}
            db.execute('INSERT OR REPLACE INTO migration_executions VALUES(?,?)',(self.run_id,json.dumps(after,sort_keys=True)))
            if event:
                self.canonical.local_record(db, 'migration:'+self.run_id+':'+uuid.uuid4().hex,
                    'migration.'+event, {'type':'RECOVERY','identity':self.run_id}, timestamp(),
                    before=before, after=after, reason='Durable migration control; preserve evidence and exact authority',
                    exact_versions={'profile_sha256':after.get('profile_sha256')},
                    evidence_refs=after.get('evidence',[]))
            return after

    def heartbeat(self, who):
        return self.transition({who+'_heartbeat_epoch':time.time()}, None)

    @contextmanager
    def exclusive(self):
        with self.path.with_name('migration-runner.lock').open('a') as f:
            try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise RebuildError('runner_already_active')
            yield

    def attempt(self, stage):
        with self.connect() as db:
            row = db.execute('SELECT state_json FROM migration_attempts WHERE execution_id=? AND stage=? ORDER BY attempt DESC LIMIT 1',(self.run_id,stage)).fetchone()
            return json.loads(row[0]) if row else None

    def save_attempt(self, stage, value):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT state_json FROM migration_attempts WHERE execution_id=? AND stage=? AND attempt=?',(self.run_id,stage,value['attempt'])).fetchone()
            db.execute('INSERT OR REPLACE INTO migration_attempts VALUES(?,?,?,?)',(self.run_id,stage,value['attempt'],json.dumps(value,sort_keys=True)))
            self.canonical.local_record(db,'migration:'+self.run_id+':attempt:'+uuid.uuid4().hex,
                'migration.stage_attempt',{'type':'RECOVERY','identity':stage},timestamp(),
                before=json.loads(old[0]) if old else None,after=value,
                reason='Persist intent before transport; verify independently before completion')

    def alert_intent(self, incident, body_sha256):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT state_json FROM migration_alerts WHERE execution_id=? AND incident=?',(self.run_id,incident)).fetchone()
            if old:return json.loads(old[0]),False
            row={'state':'ATTEMPTED','at':stamp(),'body_sha256':body_sha256,'incident':incident}
            db.execute('INSERT INTO migration_alerts VALUES(?,?,?)',(self.run_id,incident,json.dumps(row)))
            return row,True

    def save_alert(self, incident, value):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE migration_alerts SET state_json=? WHERE execution_id=? AND incident=?',(json.dumps(value,sort_keys=True),self.run_id,incident))
        self.transition({'last_notification':value},'notification_readback')


def load_profile(path):
    trusted_manifest(path)
    p=json.loads(Path(path).read_text())
    require(p['version']==1 and p['source']=={'host':'vps-214ba8cd','ip':'148.113.249.7'} and
            p['target']=={'host':'vps-f8e9b20e','ip':'15.235.100.76'},'identity_binding_failed')
    require(p['hold_max_seconds']==3600 and p['rollback_review_seconds']==2700,'hold_policy_invalid')
    require(set(p['scopes'])==set(SCOPES),'eight_separate_scopes_required')
    require(p['business_automation']=='OFF','business_authority_forbidden')
    return p


def pinned_command(spec):
    argv=spec['argv']; require(isinstance(argv,list) and argv and all(isinstance(a,str) for a in argv),'invalid_command')
    require(bool(spec.get('files')),'pinned_code_required')
    for path, checksum in spec['files'].items():
        trusted_manifest(path);require(file_hash(path)==checksum,'code_hash_changed')
    require(argv[0] in spec['files'] or argv[0] in ['/usr/bin/python3','/usr/bin/bash','/usr/bin/systemd-run','/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python'],'unbound_executable')
    if argv[0].endswith(('python3','python','bash')):
        require(any(a in spec['files'] for a in argv[1:]),'script_hash_required')
    return argv


def verify_receipt(value, profile, stage, inputs, *, now_epoch=None):
    epoch=time.time() if now_epoch is None else now_epoch
    require(isinstance(value,dict) and value.get('status')=='PASS','independent_readback_failed')
    require(value.get('execution_id')==profile['execution_id'] and value.get('stage')==stage,'readback_wrong_execution')
    require(value.get('input_sha256')==inputs and value.get('source')==profile['source'] and value.get('target')==profile['target'],'readback_identity_mismatch')
    require(isinstance(value.get('output_sha256'),str) and len(value['output_sha256'])==64 and
            all(c in '0123456789abcdef' for c in value['output_sha256']),'output_hash_required')
    require(isinstance(value.get('evidence'),list) and bool(value['evidence']) and
            'before_state' in value and 'after_state' in value,'verification_evidence_required')
    require(0<=epoch-value.get('verified_epoch',0)<=120,'stale_stage_readback')
    return value


def approvals(profile, path, *, epoch=None):
    private_file(path)
    a=json.loads(Path(path).read_text());epoch=time.time() if epoch is None else epoch
    require(a.get('execution_id')==profile['execution_id'] and a.get('profile_sha256')==digest(profile),'approval_profile_changed')
    require(a.get('owner_authorization_reference') and a.get('owner_authorization_sha256'),'actual_owner_authorization_required')
    require(isinstance(a.get('issued_epoch'),(int,float)) and isinstance(a.get('expires_epoch'),(int,float)),'owner_approval_not_issued')
    require(a['issued_epoch']<=epoch<a['expires_epoch']<=a['issued_epoch']+86400,'approval_expired_or_unbounded')
    for scope in SCOPES:
        v=a.get('scopes',{}).get(scope,{})
        require(v.get('approved') is True and v.get('binding_sha256')==digest(profile['scopes'][scope]),'owner_scope_required:'+scope)
    return a


class Runner:
    def __init__(self, profile, control, approval_path, health_path):
        self.p,self.c,self.approval_path,self.health_path=profile,control,approval_path,Path(health_path)

    def block(self, reason):
        old=self.c.state() or {}
        if old.get('status')=='REQUIRES_OWNER' and old.get('blocker')==reason:return old
        return self.c.transition({'status':'REQUIRES_OWNER','blocker':reason,'next_resumable_stage':old.get('next_resumable_stage','APPROVED')},'requires_owner')

    def gates(self):
        s=self.c.state(); require(s['profile_sha256']==digest(self.p),'profile_changed')
        require(s.get('notification_test',{}).get('state')=='DELIVERED','owner_notification_delivery_unverified')
        require(time.time()-s.get('watchdog_heartbeat_epoch',0)<90,'independent_watchdog_not_current')
        h=json.loads(self.health_path.read_text())
        require(0<=time.time()-h.get('checked_epoch',0)<90,'health_evidence_stale')
        require(h.get('timed_maintenance_ready') is True,'premaintenance_gates_blocked')
        require(self.p.get('execution_enabled') is True,'reviewed_execution_profile_not_armed')
        require(self.p.get('rollback_verified') is True,'rollback_not_verified')
        require(self.p.get('source_reboot_fence_verified') is True,'source_reboot_fence_missing')
        approvals(self.p,self.approval_path)

    def readback(self, step, inputs):
        argv=pinned_command(step['verify'])
        env={**os.environ,'OPTIBRAIN_MIGRATION_EXECUTION_ID':self.p['execution_id'],'OPTIBRAIN_MIGRATION_INPUT_SHA256':inputs}
        r=subprocess.run(argv,capture_output=True,text=True,timeout=45,env=env)
        require(r.returncode==0,'readback_command_failed')
        return verify_receipt(json.loads(r.stdout),self.p,step['stage'],inputs)

    def execute(self, step, inputs, attempt):
        require(step.get('reviewed') is True,'stage_adapter_not_reviewed')
        require(step.get('retry') in ['NEVER','IDEMPOTENT_LOCAL'],'invalid_retry_class')
        require(0<int(step['timeout_seconds'])<=900,'unbounded_stage_timeout')
        argv=pinned_command(step['execute']);pinned_command(step['verify'])
        unit='optibrain-migration-step-'+digest([self.p['execution_id'],step['stage'],attempt])[:24]
        value={'attempt':attempt,'stage':step['stage'],'state':'ATTEMPTED','at':stamp(),
            'input_sha256':inputs,'command_sha256':digest(step['execute']),
            'approval_reference':file_hash(self.approval_path),'unit':unit,'deadline_epoch':time.time()+step['timeout_seconds']}
        self.c.save_attempt(step['stage'],value) # fsynced before any external effect
        envargs=['--setenv=OPTIBRAIN_MIGRATION_EXECUTION_ID='+self.p['execution_id'],
                 '--setenv=OPTIBRAIN_MIGRATION_INPUT_SHA256='+inputs]
        # Host transient unit: restore bind mounts must affect host, not a private mount namespace.
        launch=['/usr/bin/systemd-run','--quiet','--wait','--collect','--unit='+unit,
                '--property=Type=exec','--property=RuntimeMaxSec='+str(step['timeout_seconds']),
                '--property=TimeoutStopSec=30','--property=UMask=0077',*envargs,'--',*argv]
        with subprocess.Popen(launch,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as proc:
            while proc.poll() is None:
                self.c.heartbeat('runner');time.sleep(5)
        # Exit code is deliberately not accepted as completion.
        return self.readback(step,inputs)

    def tick(self):
        with self.c.exclusive():
            state=self.c.state()
            if not state:
                self.c.transition({'status':'PREPARED','completed_stages':['PREPARED'],'current_stage':'PREPARED',
                    'next_resumable_stage':'APPROVED','profile_sha256':digest(self.p),'source':self.p['source'],
                    'target':self.p['target'],'authority':'OLD','evidence':[],
                    'rollback':'Before target intake: approved source restore/readback, then approved queue resume. After target writes: preserve NEW and reconcile; never overwrite with OLD.'},'prepared')
            self.c.heartbeat('runner');state=self.c.state()
            if state['status'] in TERMINAL:return state
            require(state['profile_sha256']==digest(self.p),'profile_changed')
            pending=next((s for s in STAGES if s not in state['completed_stages']),None)
            pending_step=next((s for s in self.p['steps'] if s['stage']==pending),None)
            prior=self.c.attempt(pending) if pending_step else None
            if prior:
                # Reconciliation is read-only and remains allowed after approval expiry.
                # A lost DNS/queue ACK must not prevent its own independent readback.
                try:observed=self.readback(pending_step,prior['input_sha256'])
                except Exception:observed=None
                if observed:return self.complete(state,pending,observed,prior)
            try:self.gates()
            except (RebuildError,FileNotFoundError,json.JSONDecodeError) as e:return self.block(str(e) if isinstance(e,RebuildError) else type(e).__name__)
            if state.get('hold_started_epoch') and time.time()-state['hold_started_epoch']>=2700:
                return self.block('hold_deadline_review_required_no_blind_resume')
            done=state['completed_stages']
            if 'APPROVED' not in done:
                return self.c.transition({'status':'APPROVED','current_stage':'APPROVED','completed_stages':done+['APPROVED'],'blocker':None},'approved')
            todo=[s for s in STAGES if s not in done]
            if not todo:return state
            stage=todo[0];step=next((s for s in self.p['steps'] if s['stage']==stage),None)
            if not step:return self.block('stage_adapter_unbound:'+stage)
            inputs=digest({'profile':digest(self.p),'previous_verified_output':state.get('last_output_sha256'), 'stage':stage})
            old=self.c.attempt(stage)
            if old:
                require(old['input_sha256']==inputs,'attempt_inputs_changed')
                try:receipt=self.readback(step,inputs)
                except Exception:
                    # No blind retries after ambiguous external effects, even after reboot.
                    if step.get('retry')!='IDEMPOTENT_LOCAL':return self.block('uncertain_effect_reconcile_only:'+stage)
                    if old['attempt']>=3:return self.block('bounded_retries_exhausted:'+stage)
                    if time.time()<old.get('retry_after_epoch',0):return self.c.state()
                    receipt=None
            else:receipt=None
            if receipt is None:
                attempt=(old['attempt']+1) if old else 1
                try:receipt=self.execute(step,inputs,attempt)
                except Exception as e:
                    row=self.c.attempt(stage) or {'attempt':attempt,'input_sha256':inputs}
                    row.update(state='UNVERIFIED',error=type(e).__name__,retry_after_epoch=time.time()+[5,20,60][attempt-1])
                    self.c.save_attempt(stage,row)
                    if step.get('retry')=='IDEMPOTENT_LOCAL' and attempt<3:
                        return self.c.transition({'status':'BLOCKED','blocker':'safe_local_retry_pending:'+stage},'retry_pending')
                    return self.block('uncertain_effect_reconcile_only:'+stage)
            return self.complete(state,stage,receipt,self.c.attempt(stage) or {'attempt':0})

    def complete(self,state,stage,receipt,row):
        row.update(state='VERIFIED',readback=receipt);self.c.save_attempt(stage,row)
        changes={'status':stage,'current_stage':stage,'completed_stages':state['completed_stages']+[stage],
            'next_resumable_stage':STAGES[STAGES.index(stage)+1] if stage!='COMPLETE' else None,
            'last_output_sha256':receipt['output_sha256'],'evidence':receipt['evidence'],'blocker':None}
        if stage=='QUEUE_HELD':
            # Use the original effect intent as a conservative hold start. Reboot or
            # late readback cannot extend the owner's 60-minute maintenance limit.
            require(bool(row.get('at')),'original_hold_intent_timestamp_required')
            changes['hold_started_epoch']=min(time.time(),datetime.fromisoformat(row['at']).timestamp())
        if stage=='CUTOVER':changes['authority']='NEW'
        return self.c.transition(changes,'stage_verified')



def watchdog(control, profile, health):
    state=control.state() or {};epoch=time.time();issues=[]
    if epoch-state.get('runner_heartbeat_epoch',0)>90:issues.append('runner_heartbeat_stale')
    if epoch-health.get('checked_epoch',0)>90:issues.append('health_probe_stale')
    if health.get('status')!='PASS':issues.extend(health.get('issues',['health_probe_failed']))
    starts=[state[k] for k in ['hold_started_epoch','forms_hold_started_epoch'] if state.get(k)]
    held=min(starts) if starts else None
    if held and 'INTAKE_VERIFIED' not in state.get('completed_stages',[]):
        age=epoch-held
        if age>=3600:issues.append('CRITICAL_hold_limit_reached')
        elif age>=2700:issues.append('hold_rollback_review_due')
    # The watchdog never resumes a queue or restarts a writer by timer alone.
    value={'at':stamp(),'issues':sorted(set(issues)),'stage':state.get('current_stage'),
           'automatic_recovery':'Local runner systemd Restart=on-failure only; provider reconciliation requires exact approved adapter'}
    control.heartbeat('watchdog')
    if value['issues']!=(state.get('watchdog') or {}).get('issues',[]):
        control.transition({'watchdog':value},'watchdog_incident')
    return value


def report(control, path):
    state=control.state() or {}
    text='OPTIBRAIN AUTONOMOUS MIGRATION\n'+json.dumps(state,indent=2,sort_keys=True)+'\n'
    atomic_bytes(path,text.encode(),0o600)
    return state


def main():
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['runner','watchdog','status'])
    a.add_argument('--profile',required=True);a.add_argument('--database',default='/var/lib/optibrain-rebuild/actions.db')
    a.add_argument('--approvals',default='/etc/optibrain/migration/owner-approvals.json')
    a.add_argument('--health',default='/var/lib/optibrain-rebuild/migration-health.json')
    a.add_argument('--report',default='/var/lib/optibrain-rebuild/migration-status.txt');a.add_argument('--once',action='store_true')
    args=a.parse_args();require(os.geteuid()==0,'root_required');require(os.uname().nodename=='vps-f8e9b20e','replacement_only')
    p=load_profile(args.profile);c=Control(args.database,p['execution_id'])
    if args.mode=='status':print(json.dumps(report(c,args.report)));return
    if args.mode=='watchdog':
        try:h=json.loads(Path(args.health).read_text())
        except Exception:h={'status':'BLOCKED','issues':['health_probe_unavailable']}
        print(json.dumps(watchdog(c,p,h)));report(c,args.report);return
    runner=Runner(p,c,args.approvals,args.health)
    while True:
        try:runner.tick()
        except Exception as e:c.transition({'status':'FAILED','blocker':type(e).__name__},'runner_failure')
        report(c,args.report)
        if args.once:break
        time.sleep(15)

if __name__=='__main__':main()
