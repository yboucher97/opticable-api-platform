"""Exact readiness-only adapter; no installed caller or production grants.

The future protected entry point must independently verify the root policy/grant.
The adapter reuses ActionEvidence for an immutable operation claim and outcome.
It never controls systemd, credentials, queues, databases or application code.
"""
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import tempfile

from .acquisition_store import digest
from .action_evidence import envelope, stamp

ARGV=('/usr/bin/python3','-I','-B','/usr/local/lib/optibrain/phase14-runtime-snapshot.py','--current-services')
SERVICE='optibrain-resource-sample.service'
RELEASE='b0b94f118a22e0dfcbee8d3f729f67d618cf99da'
SIGNALS={'Timers','Backup','Off-host backup','Disk','DB health','Growth','Safety flags','Deployment','Credential refresh'}


def validate_authority(policy, grant, evidence, operation_id, now, *, require_stale=True):
    if (not isinstance(operation_id,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,120}',operation_id)
            or policy.get('enabled') is not True or grant.get('approved') is not True
            or policy.get('authority')!='ROOT_REVIEWED_READINESS_ADAPTER_V1'
            or grant.get('authority')!='OWNER_EXACT_READINESS_REFRESH'
            or grant.get('operation_id')!=operation_id or grant.get('service')!=SERVICE
            or grant.get('playbook_id')!='refresh-local-readiness'
            or grant.get('argv')!=list(ARGV) or grant.get('maximum_attempts')!=1
            or grant.get('execution_timeout_seconds')!=45 or grant.get('cooldown_seconds')!=900
            or grant.get('policy_sha256')!=digest(policy)
            or grant.get('source_sha')!=RELEASE or policy.get('source_sha')!=RELEASE):
        raise ValueError('Exact independently verified readiness-only operation approval required')
    start,end=stamp(grant.get('starts_at')),stamp(grant.get('expires_at'))
    if not start or not end or not start<=now<end or not timedelta(0)<end-start<=timedelta(hours=1):
        raise ValueError('Readiness approval expired or outside the one-hour maximum')
    required=('root_policy_verified','root_grant_verified','runtime_pin_verified','45_flags_off',
        '76_settings_unchanged','no_inflight_business_effects','no_recovery_hold','audit_integrity_verified',
        'sampler_idle','configuration_checkpoint_verified')
    if (not all(evidence.get(k) is True for k in required)
            or evidence.get('source_sha')!=RELEASE
            or evidence.get('configuration_checkpoint_sha256')!=grant.get('configuration_checkpoint_sha256')
            or evidence.get('sampler_identity_sha256')!=grant.get('sampler_identity_sha256')):
        raise ValueError('Trusted current root evidence and installed release required')
    if require_stale and evidence.get('observations_stale') is not True:
        raise ValueError('Refresh requires demonstrably stale local observations')
    observed=stamp(evidence.get('observed_at'))
    if not observed or not timedelta(0)<=now-observed<=timedelta(seconds=30):
        raise ValueError('Current precondition evidence required')


def run_exact(argv):
    """The sole production effect: fixed provider-free snapshot projection."""
    if tuple(argv)!=ARGV:raise ValueError('Only the exact readiness command is executable')
    def limits():
        resource.setrlimit(resource.RLIMIT_CPU,(10,10))
        resource.setrlimit(resource.RLIMIT_AS,(256*1024**2,256*1024**2))
        resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024**2,8*1024**2))
        resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
    child=subprocess.Popen(list(ARGV),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},start_new_session=True,preexec_fn=limits)
    try:
        out,err=child.communicate(timeout=45)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid,signal.SIGKILL);child.communicate()
        raise TimeoutError('Readiness attempt exceeded 45 seconds; no retry') from None
    if len(out)>8192 or len(err)>8192 or child.returncode:
        raise ValueError('Readiness command did not complete successfully')
    return json.loads(out)


def valid_snapshot(value, evidence, completed_at):
    at=stamp(value.get('captured_at'))
    signals=value.get('signals',[])
    return (at is not None and timedelta(0)<=completed_at-at<=timedelta(seconds=45)
        and value.get('deployment_sha')==RELEASE and value.get('provider_calls')==0 and value.get('mutations')==0
        and value.get('resource_observed_at')==evidence['resource_observed_at']
        and isinstance(signals,list) and len(signals)==len(SIGNALS) and all(isinstance(v,dict) for v in signals)
        and {v.get('name') for v in signals}==SIGNALS
        and all(v.get('state') in {'OK','UNKNOWN','DEGRADED','ACTION REQUIRED'} for v in signals)
        and all(v.get('state')=='OK' for v in signals if v.get('name') in {'Safety flags','Deployment'}))


class ReadinessRefreshAdapter:
    def __init__(self, scope, audit, *, target, policy, grant, evidence, command=run_exact, clock):
        self.scope,self.audit,self.target=scope,audit,Path(target)
        self.policy,self.grant,self.evidence,self.command,self.clock=policy,grant,evidence,command,clock

    def execute(self, operation_id):
        now=self.clock();evidence=self.evidence()
        validate_authority(self.policy,self.grant,evidence,operation_id,now)
        action='readiness-refresh:'+digest(operation_id)[:32]
        with self.scope.lock():
            previous=self.audit.get(action)
            if previous:
                self.audit.verify_integrity(action)
                return {'state':'ALREADY_FINAL' if previous['status']!='STARTED' else 'AMBIGUOUS_NO_RETRY','executed':False}
            with self.audit.connect(readonly=True) as db:
                attempts=db.execute("SELECT action_id,created_at FROM action_envelopes WHERE json_extract(envelope_json,'$.action_type')='EXACT_READINESS_REFRESH'").fetchall()
            if any(self.audit.get(r['action_id'])['status']=='STARTED' for r in attempts):
                return {'state':'AMBIGUOUS_PRIOR_OPERATION_HOLD','executed':False}
            if any(stamp(r['created_at']) is None or now<stamp(r['created_at']) for r in attempts):
                return {'state':'CLOCK_OR_HISTORY_HOLD','executed':False}
            if any(0<=(now-stamp(r['created_at'])).total_seconds()<900 for r in attempts):
                return {'state':'COOLDOWN','executed':False}
            before=self.target.read_bytes() if self.target.exists() else None
            if before is not None and len(before)>2*1024**2:raise ValueError('Bounded derived preimage required')
            before_hash=hashlib.sha256(before).hexdigest() if before is not None else None
            self.scope.write('evidence/'+action+'.before',before or b'')
            plan=envelope(action,'EXACT_READINESS_REFRESH',{'type':'DERIVED_STATUS','identity':SERVICE},now,
                mutation=True,authority_class='EXACT_OWNER_OPERATION',exact_versions={'grant_sha256':digest(self.grant),'source_sha':RELEASE},
                rollback_capability='REVERSIBLE_WITH_LIMITATIONS',rollback_target='only exact prior derived status',
                rollback_procedure='Restore verified preimage only if current output hash is owned by this attempt; ambiguity holds',
                before_state={'sha256':before_hash},proposed_state={'argv':list(ARGV),'maximum_attempts':1})
            self.audit.plan(plan,now);self.audit.start(action,now,authority_check=lambda:validate_authority(self.policy,self.grant,self.evidence(),operation_id,self.clock()))
        verified=False;restored=False;ambiguous=False;after_hash=None;error=None
        try:
            output=self.command(ARGV)
            after=self.target.read_bytes();after_hash=hashlib.sha256(after).hexdigest()
            actual=json.loads(after);fresh=self.evidence();completed=self.clock()
            validate_authority(self.policy,self.grant,fresh,operation_id,completed,require_stale=False)
            if (fresh['sampler_invocation_id']!=evidence['sampler_invocation_id']
                    or fresh['resource_observed_at']!=evidence['resource_observed_at']):
                ambiguous=True;raise ValueError('Concurrent existing sampler/source change; preserve newer output')
            verified=valid_snapshot(actual,evidence,completed) and output.get('sampled_at')==actual['captured_at'] and output.get('signals')==len(SIGNALS)
            if not verified:raise ValueError('Independent readiness verification failed')
        except Exception as exc:
            error=type(exc).__name__
            ambiguous=ambiguous or isinstance(exc,TimeoutError)
            # Archive only derived output. Never overwrite newer/unknown changes.
            current=self.target.read_bytes() if self.target.exists() else None
            if not ambiguous and after_hash and current is not None and hashlib.sha256(current).hexdigest()==after_hash:
                self.scope.write('evidence/'+action+'.invalid',current)
                if before is not None:
                    self._restore(before);restored=self.target.read_bytes()==before
                else:
                    self.target.unlink();restored=True
            else:ambiguous=True
        result={'verified':verified,'prior_derived_snapshot_restored':restored,'ambiguous':ambiguous,
            'error_type':error,'before_sha256':before_hash,'after_sha256':after_hash,'business_mutations':0,'database_restores':0}
        self.audit.finish(action,self.clock(),provider_success=verified,verified=verified,actual_after=result)
        self.audit.event(action,'RECOVERY','READINESS_REFRESH_OUTCOME',dict(result,tests=['independent fixed-command output and file readback'],escalation='existing-owner-operations' if not verified else None),self.clock())
        if not verified:
            self.audit.event(action,'RECOVERY','AUTONOMY_HOLD',{'reason_code':'AMBIGUOUS_READINESS_EFFECT' if ambiguous else 'READINESS_VERIFICATION_FAILED','blocks_autonomy':True},self.clock())
        return {'state':'VERIFIED' if verified else 'FAILED','executed':True,**result}

    def _restore(self, data):
        fd,name=tempfile.mkstemp(prefix='.readiness-restore-',dir=self.target.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                os.fchmod(stream.fileno(),0o644);stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(name,self.target)
            fd=os.open(self.target.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:
            if os.path.exists(name):os.unlink(name)
