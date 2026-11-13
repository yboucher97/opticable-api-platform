"""Validate proposed standing permissions; contains no executor or credentials."""
from datetime import timedelta
import json
import re
import subprocess
import sys

from .acquisition_store import digest
from .action_evidence import stamp

ALLOWED = {
    'refresh-local-readiness': ({'optibrain-resource-sample.service'}, 45, 900),
    'restart-contained-support': ({'opticable-password-pdf.service', 'opticable-omada-site.service'}, 90, 3600),
    'exact-approved-release-rollback': ({'opticable-workflow-api.service'}, 180, 3600),
}
ACTIONS = {
    'refresh-local-readiness': [['/usr/bin/python3', '-I', '-B', '/usr/local/lib/optibrain/phase14-runtime-snapshot.py', '--current-services']],
    'restart-contained-support': [['/usr/bin/systemctl', 'restart', '{service}']],
    'exact-approved-release-rollback': [['existing-independent-supervisor', 'EXACT_CODE_CONFIG_ONCE_V1']],
}


def validate_catalog(catalog):
    if not isinstance(catalog, dict) or catalog.get('schema') != 1 or catalog.get('environment') != 'production':
        raise ValueError('Exact production repair proposal required')
    rows = catalog.get('playbooks')
    if not isinstance(rows, list) or len(rows) != len(ALLOWED) or {r.get('id') for r in rows} != set(ALLOWED):
        raise ValueError('Exact bounded playbook inventory required')
    for row in rows:
        services, timeout, cooldown = ALLOWED[row['id']]
        if (set(row.get('services', [])) != services or row.get('actions') != ACTIONS[row['id']]
                or type(row.get('maximum_attempts')) is not int or row['maximum_attempts'] != 1
                or type(row.get('execution_timeout_seconds')) is not int
                or not 1 <= row['execution_timeout_seconds'] <= timeout
                or type(row.get('cooldown_seconds')) is not int or row['cooldown_seconds'] < cooldown):
            raise ValueError('Action, service or execution budget exceeds reviewed catalog')
        for field in ('preconditions', 'success_checks', 'audit', 'prohibitions'):
            if not isinstance(row.get(field), list) or not row[field] or not all(isinstance(v, str) and v for v in row[field]):
                raise ValueError('Explicit evidence and prohibit conditions required')
        for field in ('rollback', 'escalation'):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError('Rollback and escalation behavior required')
        if row.get('approval', {}).get('maximum_permission_lifetime_seconds') != 604800:
            raise ValueError('Seven-day maximum standing permission lifetime required')
    return catalog


def check_standing_permission(catalog, playbook_id, grant, *, expected_digest, now, evidence, operation_id=None):
    """Future trusted adapter preflight only; cannot execute a proposed action.

    Caller must supply independently root-verified approval, runtime and evidence.
    Published catalog remains disabled, and no production caller is installed.
    """
    validate_catalog(catalog)
    if digest(catalog) != expected_digest:
        raise ValueError('Independently pinned exact catalog digest required')
    row = next((r for r in catalog['playbooks'] if r['id'] == playbook_id), None)
    if catalog.get('permissions_enabled') is not True or not row or row.get('enabled') is not True:
        raise ValueError('Production repair permissions remain disabled')
    start, end = stamp(grant.get('starts_at')), stamp(grant.get('expires_at'))
    if (grant.get('approved') is not True or grant.get('authority') != 'OWNER_EXACT_STANDING_REPAIR'
            or grant.get('catalog_sha256') != expected_digest or grant.get('playbook_id') != playbook_id
            or grant.get('service') not in row['services'] or start is None or end is None
            or not start <= now < end or not timedelta(0) < end-start <= timedelta(days=7)
            or grant.get('root_verified') is not True):
        raise ValueError('Fresh independently verified exact owner standing grant required')
    if (not isinstance(operation_id,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,120}',operation_id)
            or grant.get('operation_id')!=operation_id):
        raise ValueError('Separate exact authorization for this operation required')
    required = ('executor_root_pin_verified', '45_flags_off', 'protected_settings_unchanged',
                'no_inflight_business_effects', 'no_recovery_hold', 'fresh_preconditions_verified',
                'exact_configuration_checkpoint_verified', 'existing_audit_ready')
    if not all(evidence.get(k) is True for k in required):
        raise ValueError('Current independent preconditions and execution evidence required')
    return {'playbook_id': playbook_id, 'service': grant['service'],
            'maximum_attempts': 1, 'production_execution_performed': False}


def exercise_playbook(scope, catalog, permit, *, now, fault='', supervisor=None, timeout=None):
    """Execute the proposed semantics only on private development fixture files.

    This cannot run systemctl or select a production path. Actual production
    catalog/standing grants stay disabled. Existing supervisor, derived-status
    playbook, immutable journal and locks are reused.
    """
    from .operational_recovery import DevelopmentScope, RecoveryCoordinator, DerivedStatus, recovery_holds
    from .action_evidence import envelope
    if not isinstance(scope,DevelopmentScope):raise ValueError('Explicit isolated fixture scope required')
    scope.verify(now);validate_catalog(catalog)
    if catalog.get('permissions_enabled') is not False:raise ValueError('Exercise only the disabled proposal')
    identity=permit.get('operation_id');kind=permit.get('playbook_id');service=permit.get('service')
    end=stamp(permit.get('expires_at'))
    if (permit.get('authority')!='OWNER_ISOLATED_EXPERIMENT' or not isinstance(identity,str)
            or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,120}',identity) or kind not in ALLOWED
            or service not in ALLOWED[kind][0] or end is None or not now<end<=now+timedelta(hours=1)
            or fault not in {'','fail','stall'}):
        raise ValueError('Exact fresh non-production operation permit required')
    row=next(r for r in catalog['playbooks'] if r['id']==kind)
    timeout=row['execution_timeout_seconds'] if timeout is None else timeout
    if type(timeout) not in (int,float) or not 0<timeout<=row['execution_timeout_seconds']:
        raise ValueError('Bounded fixture timeout required')
    coordinator=RecoveryCoordinator(scope,now=now);audit=coordinator.audit
    aid='playbook-exercise:'+digest(identity)[:32];binding=digest(permit)
    with scope.lock():
        prior=audit.get(aid)
        if prior:
            if prior['exact_versions']['permit_sha256']!=binding:raise ValueError('Operation binding changed')
            return {'state':'AMBIGUOUS_NO_RETRY' if prior['status']=='STARTED' else 'ALREADY_FINAL',
                    'executed':False,'production_execution_performed':False}
        if recovery_holds(audit):return {'state':'RECOVERY_HOLD','executed':False}
        with audit.connect(readonly=True) as db:
            rows=db.execute("SELECT created_at FROM action_envelopes WHERE json_extract(envelope_json,'$.action_type')='PLAYBOOK_EXERCISE' AND json_extract(envelope_json,'$.target.identity')=?",(service,)).fetchall()
        if any((now-stamp(r[0])).total_seconds()<row['cooldown_seconds'] for r in rows):
            return {'state':'COOLDOWN','executed':False}
        plan=envelope(aid,'PLAYBOOK_EXERCISE',{'type':'DEVELOPMENT_FIXTURE','identity':service},now,
            exact_versions={'environment':'isolated-development','permit_sha256':binding},
            before_state={'production_effects':0},proposed_state={'playbook':kind})
        audit.plan(plan,now);audit.start(aid,now,authority_check=lambda:scope.verify(now))
    result={};verified=False;ambiguous=False
    try:
        if kind=='refresh-local-readiness':
            source=scope.path('observations/readiness.json')
            if source.stat().st_size>4096:raise ValueError('Fixture observation exceeds bound')
            expected=json.loads(source.read_text());playbook=DerivedStatus(scope,{'expected':expected},aid)
            before=playbook.describe();playbook.execute(before)
            if fault:scope.write('derived/status.json',b'{"invalid":true}\n')
            verified=playbook.verify();result=playbook.after()
            if not verified and before['exists']:
                scope.write('evidence/'+aid+'.invalid',playbook.path.read_bytes())
                old=scope.path(playbook.preimage).read_bytes();scope.write('derived/status.json',old)
                result['prior_snapshot_restored']=playbook.path.read_bytes()==old
        elif kind=='restart-contained-support':
            state=scope.path('services/'+service+'.json');state.parent.mkdir(mode=0o700,exist_ok=True)
            code='''import json,sys,time,os
from pathlib import Path
os.umask(0o077);p=Path(sys.argv[1]);fault=sys.argv[2]
if fault=='stall':time.sleep(2)
v=json.loads(p.read_text()) if p.exists() else {'starts':0}
v.update(starts=v['starts']+1,healthy=fault!='fail');p.write_text(json.dumps(v))
sys.exit(0 if v['healthy'] else 2)
'''
            process=subprocess.run([sys.executable,'-I','-B','-c',code,str(state),fault],
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},capture_output=True,timeout=timeout)
            result=json.loads(state.read_text());verified=process.returncode==0 and result['healthy'] is True
        else:
            if supervisor is None or supervisor.scope.root!=scope.root:
                raise ValueError('Existing exact isolated recovery supervisor required')
            result=supervisor.deploy(now=now);verified=result['state']=='ROLLED_BACK' and supervisor.data_probe()['healthy'] is True
    except subprocess.TimeoutExpired:
        ambiguous=True;result={'error_type':'TimeoutExpired','effect':'UNKNOWN'}
    except Exception as exc:result={'error_type':type(exc).__name__}
    audit.finish(aid,now,provider_success=verified,verified=verified,actual_after=result)
    audit.event(aid,'RECOVERY','PLAYBOOK_EXERCISE_OUTCOME',
        {'playbook':kind,'tests':['independent fixture readback'],'verified':verified,
         'outcome':result,'production_effects':0},now)
    if not verified:coordinator._incident(digest(identity)[:32],
        'REPAIR_VERIFICATION_UNAVAILABLE' if ambiguous else 'RECOVERY_FAILED',aid,now)
    return {'state':'VERIFIED' if verified else 'FAILED','executed':True,'result':result,
            'production_execution_performed':False}
