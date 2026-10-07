"""Universal action contract in the existing immutable action journal.

Evidence never grants transport authority. Immutable plans and hash-chained
state observations share BusinessJournal's tables and checksum format.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from .acquisition_store import digest

REVERSIBILITY = {'FULLY_REVERSIBLE', 'REVERSIBLE_WITH_LIMITATIONS',
                 'COMPENSATING_ACTION_ONLY', 'IRREVERSIBLE', 'UNKNOWN'}
LAYERS = {'TECHNICAL_AUDIT', 'BUSINESS_EVENT', 'DECISION', 'RECOVERY'}
FIELDS = set('action_id action_type status created_at started_at completed_at initiator trigger '
    'target source_system provider proposal_id priority_id related_entities before_state proposed_state '
    'after_state reason business_rationale evidence_refs decision_rules pros cons risks expected_benefit '
    'known_downside confidence confidence_reason proven_facts inferences hypotheses unknowns '
    'alternatives why_selected dependencies approval_required approval_record approval_revision '
    'exact_versions provider_request provider_response readback effect_result measurement_plan '
    'rollback_capability rollback_target rollback_procedure compensating_action final_result learning_linkage '
    'authority_class automatic_rule irreversible consequence mutation measurable baseline revision '
    'readback_supported before_supported retention evidence_bundle'.split())
SECRET = re.compile(r'token|secret|password|authorization|cookie|credential|api.?key|private.?key|form_secret', re.I)
PRIVATE_REASONING = re.compile(r'chain.?of.?thought|hidden_reasoning|private_reasoning', re.I)


def redact(value, depth=0):
    """Reject private reasoning; redact nested credentials, URLs and free text."""
    if depth > 20: raise ValueError('Evidence nesting exceeds bound')
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key = str(key)
            if PRIVATE_REASONING.search(key): raise ValueError('Private model reasoning is forbidden')
            result[key] = '[REDACTED]' if SECRET.search(key) else redact(item, depth+1)
        return result
    if isinstance(value, (list, tuple)): return [redact(item, depth+1) for item in value]
    if isinstance(value, str):
        if value.startswith(('http://', 'https://')):
            parts = urlsplit(value)
            netloc = parts.netloc.rsplit('@', 1)[-1]
            value = urlunsplit((parts.scheme, netloc, parts.path,
                urlencode([(k, '[REDACTED]' if SECRET.search(k) or k.lower()=='signature' else v)
                           for k,v in parse_qsl(parts.query, keep_blank_values=True)]), ''))
        value = re.sub(r'(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9_./+=-]+', '[REDACTED]', value)
        value = re.sub(r'(?i)\b(?:password|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[^\s,;]+', '[REDACTED]', value)
        value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----', '[REDACTED]', value)
        # The pre-existing journal also scrubs environment-bound credential values.
        from .business_autonomy import BusinessJournal
        return BusinessJournal._scrub(value)
    return value


def stamp(value):
    try:
        at = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return at if at.tzinfo else None
    except (ValueError, TypeError): return None


def envelope(action_id, action_type, target, now, **values):
    when = now.isoformat()
    record = {k: None for k in FIELDS}
    record.update(action_id=action_id, action_type=action_type, target=target,
        status='PLANNED', created_at=when, initiator='OPTIBRAIN', trigger='UNKNOWN',
        source_system='OPTIBRAIN', provider='LOCAL', revision=1, mutation=False, measurable=False,
        reason='Recorded canonical action', business_rationale='See linked evidence; missing facts remain unknown.',
        confidence='UNKNOWN', confidence_reason='No measured business outcome established.',
        rollback_capability='UNKNOWN', approval_required=False, irreversible=False,
        authority_class='LOCAL_EVIDENCE_ONLY', automatic_rule='Existing local evidence rule; no provider authority.',
        readback_supported=True, before_supported=True,
        readback={'state':'NOT_RUN'}, effect_result='NOT_EXECUTED', final_result='NOT_EXECUTED',
        retention={'class':'DURABLE', 'automatic_deletion':False}, exact_versions={},
        unknowns=['Uncollected fields are explicitly unknown.'])
    for name in ('related_entities', 'evidence_refs', 'decision_rules', 'pros', 'cons', 'risks',
                 'proven_facts', 'inferences', 'hypotheses', 'alternatives', 'dependencies'):
        record[name] = []
    record.update(values)
    return validate(record)


def validate(record):
    if not isinstance(record, dict) or not FIELDS <= set(record): raise ValueError('Action Evidence Envelope required fields missing')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{8,160}', str(record['action_id'])): raise ValueError('Durable action ID required')
    for field in ('action_type', 'initiator', 'trigger', 'source_system', 'provider', 'reason', 'business_rationale', 'confidence_reason'):
        if not isinstance(record[field], str) or not record[field].strip(): raise ValueError('Action explanation required: '+field)
    if not isinstance(record['target'], dict) or not record['target'].get('type') or not record['target'].get('identity'):
        raise ValueError('Exact target type and identity required')
    if record['rollback_capability'] not in REVERSIBILITY: raise ValueError('Reversibility classification required')
    if record['status'] not in {'PLANNED','STARTED','SUCCEEDED','FAILED','BLOCKED'}: raise ValueError('Invalid action status')
    if type(record['revision']) is not int or record['revision'] < 1: raise ValueError('Exact positive action revision required')
    for field in ('mutation','measurable','approval_required','irreversible','readback_supported','before_supported'):
        if type(record[field]) is not bool: raise ValueError('Explicit action flags required')
    if record['irreversible'] != (record['rollback_capability']=='IRREVERSIBLE'): raise ValueError('Irreversible classification must agree')
    if not stamp(record['created_at']): raise ValueError('Source-aware action timestamp required')
    for field in ('started_at','completed_at'):
        if record[field] is not None and not stamp(record[field]): raise ValueError('Aware execution timestamp required')
    if record['started_at'] and stamp(record['started_at']) < stamp(record['created_at']): raise ValueError('Execution precedes plan')
    if record['completed_at'] and (not record['started_at'] or stamp(record['completed_at']) < stamp(record['started_at'])):
        raise ValueError('Completion precedes execution')
    for field in ('related_entities','evidence_refs','decision_rules','pros','cons','risks','proven_facts','inferences','hypotheses','unknowns','alternatives','dependencies'):
        if not isinstance(record[field],list):raise ValueError('Action evidence lists required: '+field)
    if not isinstance(record['exact_versions'],dict) or not isinstance(record['readback'],dict):raise ValueError('Exact versions and readback state required')
    result = redact(deepcopy(record))
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > 65536: raise ValueError('Bounded evidence references required')
    return result


def approval_binding(plan):
    return digest({k:v for k,v in plan.items() if k not in {
        'status','started_at','completed_at','approval_record','approval_revision','after_state',
        'provider_response','readback','effect_result','final_result','learning_linkage'}})


class ActionEvidence:
    def __init__(self, path): self.path = Path(path)

    @staticmethod
    def setup(db):
        # Exactly the established BusinessJournal tables, never another database.
        for sql in (
            'CREATE TABLE IF NOT EXISTS action_envelopes(action_id TEXT PRIMARY KEY,envelope_json TEXT NOT NULL,payload_hash TEXT NOT NULL,created_at TEXT NOT NULL)',
            'CREATE TABLE IF NOT EXISTS action_evidence(event_id INTEGER PRIMARY KEY AUTOINCREMENT,action_id TEXT NOT NULL,kind TEXT NOT NULL,recorded_at TEXT NOT NULL,evidence_json TEXT NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL)',
            'CREATE INDEX IF NOT EXISTS idx_action_evidence_action ON action_evidence(action_id,event_id)',
            "CREATE TRIGGER IF NOT EXISTS action_envelopes_immutable_update BEFORE UPDATE ON action_envelopes BEGIN SELECT RAISE(ABORT,'Action envelope is immutable'); END",
            "CREATE TRIGGER IF NOT EXISTS action_envelopes_immutable_delete BEFORE DELETE ON action_envelopes BEGIN SELECT RAISE(ABORT,'Action envelope is immutable'); END",
            "CREATE TRIGGER IF NOT EXISTS action_evidence_immutable_update BEFORE UPDATE ON action_evidence BEGIN SELECT RAISE(ABORT,'Action evidence is append only'); END",
            "CREATE TRIGGER IF NOT EXISTS action_evidence_immutable_delete BEFORE DELETE ON action_evidence BEGIN SELECT RAISE(ABORT,'Action evidence is append only'); END"):
            db.execute(sql)

    def connect(self, *, readonly=False):
        db = sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True, timeout=30) if readonly else sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def append(db, action_id, kind, value, now):
        value = redact(value)
        raw = json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        if len(raw.encode()) > 65536: raise ValueError('Evidence exceeds bound')
        prior = db.execute('SELECT event_hash FROM action_evidence WHERE action_id=? ORDER BY event_id DESC LIMIT 1',(action_id,)).fetchone()
        previous = prior['event_hash'] if prior else ''
        when = now.isoformat(); checksum = digest([action_id,kind,when,raw,previous])
        db.execute('INSERT INTO action_evidence(action_id,kind,recorded_at,evidence_json,previous_hash,event_hash) VALUES(?,?,?,?,?,?)',
                   (action_id,kind,when,raw,previous,checksum))

    @staticmethod
    def current(db, action_id):
        row = db.execute("SELECT evidence_json FROM action_evidence WHERE action_id=? AND kind IN ('universal_plan','universal_state') ORDER BY event_id DESC LIMIT 1",(action_id,)).fetchone()
        return json.loads(row['evidence_json']) if row else None

    @classmethod
    def plan_in(cls, db, plan, now):
        plan = validate(plan); cls.setup(db)
        row = db.execute("SELECT evidence_json FROM action_evidence WHERE action_id=? AND kind='universal_plan' ORDER BY event_id LIMIT 1",(plan['action_id'],)).fetchone()
        if row:
            if digest(json.loads(row['evidence_json'])) != digest(plan): raise ValueError('Immutable action plan conflict')
            return plan['action_id']
        raw = json.dumps(plan,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        db.execute('INSERT OR IGNORE INTO action_envelopes VALUES(?,?,?,?)',(plan['action_id'],raw,digest(plan),now.isoformat()))
        cls.append(db,plan['action_id'],'universal_plan',plan,now)
        cls.append(db,plan['action_id'],'universal_event',{'layer':'DECISION','event':'PLANNED','reason':plan['reason'],
            'proposal_id':plan['proposal_id'],'priority_id':plan['priority_id']},now)
        return plan['action_id']

    def plan(self, plan, now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE'); return self.plan_in(db,plan,now)

    def get(self, action_id):
        if not self.path.exists(): return None
        with self.connect(readonly=True) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='action_evidence'").fetchone(): return None
            return self.current(db,action_id)

    def approve(self, action_id, actor, now, *, binding, expires_at):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE'); plan = self.current(db,action_id)
            if not plan or plan['status']!='PLANNED' or binding!=approval_binding(plan) or not actor or not stamp(expires_at) or stamp(expires_at)<=now:
                raise ValueError('Approval must bind exact current action values, revision, versions, tests and preview')
            plan.update(approval_record={'actor':actor,'binding':binding,'at':now.isoformat(),'expires_at':expires_at},approval_revision=plan['revision'])
            self.append(db,action_id,'universal_state',validate(plan),now)
            self.append(db,action_id,'universal_event',{'layer':'DECISION','event':'OWNER_APPROVED','approval':plan['approval_record']},now)

    @staticmethod
    def executable(plan, now):
        if not plan or plan['status']!='PLANNED': raise ValueError('Unexecuted durable action plan required')
        if plan['mutation']:
            if plan['authority_class'] in {'LOCAL_EVIDENCE_ONLY','WORKFLOW_ORCHESTRATION','UNKNOWN'}:
                raise ValueError('Consequential mutation requires a separate explicit authority class')
            code_change=plan['target']['type'] in {'PAGE','WEBSITE_PAGE','WEBSITE','CODE','CONTENT','DEPLOYMENT'} and plan['exact_versions'].get('environment')=='production'
            if code_change:
                versions=plan['exact_versions']
                if not plan['approval_required'] or not versions.get('proposed_version') or not versions.get('test_evidence') or not versions.get('preview_evidence'):
                    raise ValueError('Production code/content requires exact owner approval, version, tests and preview evidence')
            if plan['before_supported'] and plan['before_state'] is None: raise ValueError('Before state must be captured before execution')
            if not plan['before_supported'] and not plan['unknowns']: raise ValueError('Provider before-state limitation required')
            if plan['rollback_capability']=='UNKNOWN': raise ValueError('Unknown reversibility blocks mutation')
            if plan['rollback_capability'] in {'FULLY_REVERSIBLE','REVERSIBLE_WITH_LIMITATIONS'} and (not plan['rollback_target'] or not plan['rollback_procedure']):
                raise ValueError('Rollback target and procedure required BEFORE execution')
            if plan['rollback_capability'] in {'IRREVERSIBLE','COMPENSATING_ACTION_ONLY'} and (not plan['consequence'] or not plan['compensating_action']):
                raise ValueError('Explicit consequence and compensating plan required')
            if plan['irreversible'] and not plan['approval_required']: raise ValueError('Irreversible action requires higher approval boundary')
        if plan['measurable']:
            from .optimization_learning import validate_baseline, validate_measurement_plan, validate_bundle
            validate_measurement_plan(plan['measurement_plan']);validate_baseline(plan['baseline'],now)
            validate_bundle(plan['evidence_bundle'],material=True)
            if plan['baseline']['proposal_id']!=plan['proposal_id']:raise ValueError('Baseline must bind exact proposal')
        if plan['approval_required']:
            approval = plan['approval_record'] or {}
            if approval.get('binding')!=approval_binding(plan) or plan['approval_revision']!=plan['revision'] or not stamp(approval.get('expires_at')) or stamp(approval['expires_at'])<=now:
                raise ValueError('Fresh owner approval must bind exact action revision')
        elif not plan['authority_class'] or not plan['automatic_rule']: raise ValueError('Automatic authority class and rule required')

    def start(self, action_id, now, *, authority_check):
        if not callable(authority_check): raise ValueError('Separate transport authority check required')
        authority_check()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE'); plan = self.current(db,action_id);self.executable(plan,now)
            if plan['measurable']:
                row=db.execute("SELECT revision,payload_hash FROM optimization_records WHERE kind='optibrain.optimization_proposal' AND id=? ORDER BY revision DESC LIMIT 1",(plan['proposal_id'],)).fetchone()
                versions=plan['exact_versions']
                if not row or versions.get('proposal_revision')!=row['revision'] or versions.get('proposal_hash')!=row['payload_hash']:
                    raise ValueError('Material proposal change invalidates old action approval')
                if versions.get('production_version')!=plan['baseline']['production_version']:
                    raise ValueError('Baseline must bind exact pre-execution production version')
            plan.update(status='STARTED',started_at=now.isoformat())
            self.append(db,action_id,'universal_state',validate(plan),now)
            self.append(db,action_id,'universal_event',{'layer':'TECHNICAL_AUDIT','event':'STARTED','authority_class':plan['authority_class'],
                'automatic_rule':plan['automatic_rule'],'before_state':plan['before_state'],'exact_versions':plan['exact_versions']},now)

    def finish(self, action_id, now, *, provider_success, actual_after=None, verified=False,
               response=None, limitation=None, failure=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE'); plan = self.current(db,action_id)
            if not plan or plan['status']!='STARTED': raise ValueError('Started action required')
            success = provider_success is True and (verified is True and actual_after is not None or
                not plan['readback_supported'] and isinstance(limitation,str) and bool(limitation.strip()))
            if not success and failure is None:
                failure = {'stage':'READ_AFTER_WRITE' if provider_success else 'PROVIDER_EXECUTION','error_class':'UnverifiedEffect',
                    'provider_status':None,'safe_details':'Provider acknowledgement alone is insufficient',
                    'partial_effects':'UNKNOWN','recovery_action':'Reconcile provider state; never automatically replay'}
            if failure and not {'stage','error_class','provider_status','safe_details','partial_effects','recovery_action'} <= set(failure):
                raise ValueError('Structured failure stage, class, status, effects and recovery required')
            if failure: success=False
            plan.update(status='SUCCEEDED' if success else 'FAILED',completed_at=now.isoformat(),after_state=actual_after,
                provider_response=response,readback={'state':'VERIFIED' if success and verified else 'UNAVAILABLE_DOCUMENTED' if success else 'FAILED','limitation':limitation},
                effect_result='VERIFIED' if success and verified else 'ACKNOWLEDGED_WITH_LIMITATION' if success else 'UNVERIFIED',
                final_result='SUCCESS' if success else failure)
            self.append(db,action_id,'universal_state',validate(plan),now)
            self.append(db,action_id,'universal_event',{'layer':'BUSINESS_EVENT','event':plan['status'],'target':plan['target'],
                'readback':plan['readback'],'final_result':plan['final_result']},now)
        return success

    def event(self, action_id, layer, event, value, now):
        if layer not in LAYERS: raise ValueError('Canonical evidence layer required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self.current(db,action_id): raise ValueError('Durable action required')
            self.append(db,action_id,'universal_event',{'layer':layer,'event':event,'value':value},now)

    def timeline(self, *, query='', status='', automatic=None, since=None, limit=100):
        if len(query)>100 or not 1<=limit<=200 or status not in {'','PLANNED','STARTED','SUCCEEDED','FAILED','BLOCKED'} or since and not stamp(since): raise ValueError('Bounded audit search required')
        if not self.path.exists():return []
        with self.connect(readonly=True) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='action_evidence'").fetchone():return []
            rows=db.execute("SELECT e.* FROM action_evidence e WHERE kind='universal_event' AND (? IS NULL OR recorded_at>=?) ORDER BY event_id DESC LIMIT 2000",(since,since)).fetchall()
            output=[]
            for row in rows:
                plan=self.current(db,row['action_id']);value=json.loads(row['evidence_json'])
                if not plan or status and plan['status']!=status or automatic is not None and (not plan['approval_required'])!=automatic:continue
                entry={'action_id':row['action_id'],'at':row['recorded_at'],'status':plan['status'],
                    'action_type':plan['action_type'],'target':plan['target'],'proposal_id':plan['proposal_id'],
                    'priority_id':plan['priority_id'],'reason':plan['reason'],'rollback_capability':plan['rollback_capability'],**value}
                if query and query.casefold() not in json.dumps(entry,ensure_ascii=False).casefold():continue
                output.append(entry)
                if len(output)>=limit:break
            return list(reversed(output))

    def detail(self, action_id):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{8,160}',action_id):raise ValueError('Bounded exact action identifier required')
        plan=self.get(action_id)
        if not plan:return None
        with self.connect(readonly=True) as db:
            bundle=db.execute("SELECT evidence_json FROM action_evidence WHERE action_id=? AND kind='optimization_bundle' ORDER BY event_id DESC LIMIT 1",(action_id,)).fetchone()
        return {'envelope':plan,'history_integrity':'PASS' if self.verify_integrity(action_id) else 'UNKNOWN',
            'evidence_bundle':json.loads(bundle['evidence_json'])['bundle'] if bundle else plan['evidence_bundle']}

    def verify_integrity(self, action_id):
        with self.connect(readonly=True) as db:
            previous=''
            for row in db.execute('SELECT * FROM action_evidence WHERE action_id=? ORDER BY event_id',(action_id,)):
                if row['previous_hash']!=previous or row['event_hash']!=digest([action_id,row['kind'],row['recorded_at'],row['evidence_json'],previous]):
                    raise ValueError('Action evidence hash chain invalid')
                previous=row['event_hash']
        return bool(previous)


def local_record(db, action_id, action_type, target, now, *, before, after, reason, **values):
    """Atomic local evidence transition; call inside the owner's DB transaction."""
    ActionEvidence.setup(db)
    if ActionEvidence.current(db,action_id):return action_id
    plan=envelope(action_id,action_type,target,now,before_state=before,proposed_state=after,
        reason=reason,business_rationale=reason,**values)
    ActionEvidence.plan_in(db,plan,now)
    plan.update(status='SUCCEEDED',started_at=now.isoformat(),completed_at=now.isoformat(),after_state=after,
        readback={'state':'VERIFIED','basis':'Exact durable local database row'},effect_result='VERIFIED',final_result='SUCCESS')
    ActionEvidence.append(db,action_id,'universal_state',validate(plan),now)
    ActionEvidence.append(db,action_id,'universal_event',{'layer':'BUSINESS_EVENT','event':action_type,
        'reason':reason,'target':target,'before_state':before,'after_state':after},now)
    return action_id


def execute_action(journal, plan, now, *, authority_check, execute, readback, verify, clock=None):
    """Single execution gateway for new adapters; existing authority stays independent."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    journal.plan(plan,now);journal.start(plan['action_id'],now,authority_check=authority_check)
    stage='PROVIDER_EXECUTION'
    try:
        response=execute()
        if not isinstance(response,dict) or response.get('success') is not True:raise ValueError('Provider did not acknowledge success')
        stage='READ_AFTER_WRITE';actual=readback() if plan['readback_supported'] else None
        verified=bool(plan['readback_supported'] and verify(actual,plan['proposed_state']))
        success=journal.finish(plan['action_id'],clock(),provider_success=True,actual_after=actual,verified=verified,
            response=response,limitation=plan['unknowns'][0] if not plan['readback_supported'] and plan['unknowns'] else None)
        return {'action_id':plan['action_id'],'success':success,'after_state':actual}
    except Exception as exc:
        journal.finish(plan['action_id'],clock(),provider_success=False,failure={
            'stage':stage,'error_class':type(exc).__name__,'provider_status':getattr(exc,'status_code',None),
            'safe_details':type(exc).__name__,'partial_effects':'UNKNOWN',
            'recovery_action':'Read-only reconciliation; retain original action and record recovery separately'})
        raise


def rollback_action(journal, original_id, now, *, reason, actor, authority_check, execute, readback, verify):
    original=journal.get(original_id)
    if not original or original['rollback_capability'] not in {'FULLY_REVERSIBLE','REVERSIBLE_WITH_LIMITATIONS'} or not original['rollback_target'] or not original['rollback_procedure']:
        raise ValueError('Verified reversible original action required')
    aid=digest(['rollback',original_id,now.isoformat(),reason])
    plan=envelope(aid,'ROLLBACK',original['target'],now,initiator=actor,trigger=original_id,
        before_state=original['after_state'],proposed_state=original['before_state'],reason=reason,
        business_rationale=original['rollback_procedure'],evidence_refs=[original_id],
        rollback_capability='COMPENSATING_ACTION_ONLY',mutation=True,authority_class='EXPLICIT_RECOVERY',
        automatic_rule='Separate incident authority required',consequence='Restore previous state; later external progress may conflict',
        compensating_action='Retain history and reconcile conflicts with owner',provider=original['provider'])
    result=execute_action(journal,plan,now,authority_check=authority_check,execute=execute,readback=readback,verify=verify)
    journal.event(aid,'RECOVERY','ROLLBACK_RESULT',{'rollback_action_id':aid,'original_action_id':original_id,
        'reason':reason,'target':original['rollback_target'],'expected_restored_state':original['before_state'],
        'actual_restored_state':result['after_state'],'verification':result['success']},datetime.now(timezone.utc))
    journal.event(original_id,'RECOVERY','ROLLBACK_LINK',{'rollback_action_id':aid},datetime.now(timezone.utc))
    return result
