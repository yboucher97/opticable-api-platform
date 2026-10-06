"""Additive manager evidence in the existing journal, never provider authority."""
from datetime import timedelta
import json
import sqlite3
from .optimization_store import OptimizationStore
from .acquisition_store import digest, safe

CLASSIFICATIONS = {'UNATTENDED','OWNER_INITIATED','TEST_ONLY','MANUAL_PROVIDER_ACTION',
                   'NATURAL_BUSINESS_EFFECT','AUTOMATIC_EXISTING_WORKFLOW','UNKNOWN'}
FEEDBACK = {'APPROVE','REJECT','REQUEST_REVISION','HIGHER','LOWER','NOT_RELEVANT','WAIT','NEVER'}
OUTCOMES = {'SUCCESS','NEUTRAL','REGRESSION','INSUFFICIENT_DATA','BLOCKED'}
ENTITY_TYPES = set('COMPANY PERSON LEAD CONTACT ACCOUNT DEAL CUSTOMER SERVICE_LOCATION SERVICE ESTIMATE INVOICE RECURRING_PROFILE PROJECT PERMIT TENDER TRIGGER PROSPECT CONVERSATION WEBSITE_PAGE SEARCH_QUERY KEYWORD CAMPAIGN AD_GROUP AD CREATIVE FORM REVIEW CONTENT_ASSET MARKET_OPPORTUNITY OPTIMIZATION_PROPOSAL BUSINESS_PRIORITY EXECUTION_RESULT LEARNING'.split())
TRUTH = {'PROVIDER_FACT','PUBLIC_SOURCE_FACT','USER_CONFIRMED','DERIVED_DETERMINISTICALLY','MODEL_INFERENCE','ESTIMATE','UNKNOWN'}

class ManagerStore(OptimizationStore):
    def setup(self):
        if getattr(self,'manager_initialized',False):return
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS manager_events (
              id TEXT PRIMARY KEY, source TEXT NOT NULL, native_id TEXT NOT NULL,
              version TEXT NOT NULL, observed_at TEXT, recorded_at TEXT NOT NULL, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS manager_event_time ON manager_events(recorded_at);
            CREATE TABLE IF NOT EXISTS manager_feedback (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL, version TEXT NOT NULL,
              choice TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS manager_feedback_target ON manager_feedback(kind,target,at);
            CREATE TABLE IF NOT EXISTS manager_links (
              id TEXT PRIMARY KEY, left_ref TEXT NOT NULL, relationship TEXT NOT NULL,
              right_ref TEXT NOT NULL, truth_class TEXT NOT NULL, evidence TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS manager_briefs (
              id TEXT PRIMARY KEY, day TEXT NOT NULL, input_version TEXT NOT NULL, at TEXT NOT NULL, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS manager_learning (
              id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, revision INTEGER NOT NULL,
              outcome TEXT NOT NULL, at TEXT NOT NULL, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS manager_receipts (
              id TEXT PRIMARY KEY, job TEXT NOT NULL, at TEXT NOT NULL, value TEXT NOT NULL);
            ''')

        self.manager_initialized=True

    def put_event(self,source,native_id,version,observed_at,now,value):
        value=dict(value)
        value.setdefault('invocation_origin','UNKNOWN')
        value.setdefault('effect_class','TEST_ONLY' if value.get('classification')=='TEST_ONLY' else 'NATURAL_BUSINESS_EFFECT' if value.get('classification')=='NATURAL_BUSINESS_EFFECT' else 'NONE')
        value.setdefault('execution_owner','CLAUDE_APOLLO' if source=='APOLLO_MAIL' else 'SOURCE_PROVIDER' if source in {'CRM','BOOKS','ZOHO_FORMS'} else 'OPTIBRAIN_LOCAL')
        safe(value)
        if value.get('classification') not in CLASSIFICATIONS or value.get('truth_class') not in TRUTH:
            raise ValueError('Event classification/provenance required')
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)
        if len(raw.encode())>8192:raise ValueError('Bounded event references required')
        key=digest([source,native_id,version]);self.setup()
        with self.connect() as db:
            before=db.total_changes
            db.execute('INSERT OR IGNORE INTO manager_events VALUES (?,?,?,?,?,?,?)',
                       (key,source,native_id,version,observed_at,now.isoformat(),raw))
            added=db.total_changes>before
        return added

    def events(self,*,limit=50):
        self.setup()
        with self.connect() as db:
            return [{**dict(r),'value':json.loads(r['value'])} for r in db.execute(
                'SELECT * FROM manager_events ORDER BY recorded_at DESC,id LIMIT ?', (min(100,max(1,limit)),))]

    def feedback(self,kind,target,version,choice,actor,now,*,reason='',category='',conditions=''):
        if kind not in {'PROPOSAL','PRIORITY'} or choice not in FEEDBACK or not actor or now.tzinfo is None:
            raise ValueError('Exact local owner feedback required')
        if max(map(len,(reason,category,conditions,actor)))>1000:raise ValueError('Feedback exceeds bound')
        rows=self.rows('optibrain.optimization_proposal' if kind=='PROPOSAL' else 'optibrain.business_priority')
        item=next((r for r in rows if r['record'].get('proposal_id' if kind=='PROPOSAL' else 'priority_id')==target),None)
        if not item or item['payload_hash']!=version:raise ValueError('Fresh exact revision required')
        if kind=='PRIORITY' and choice in {'APPROVE','REQUEST_REVISION'}:raise ValueError('Proposal required')
        r=item['record']
        if choice=='APPROVE' and (not r.get('preview_location') or not r.get('measurement_plan') or not r.get('rollback_reference')):
            raise ValueError('Preview, measurement and rollback required before approval intent')
        from .manager_intelligence import semantic_evidence
        self.setup();evidence={'semantic_evidence':semantic_evidence(r,item['detail']),'reason':reason,'category':category,'reconsideration_conditions':conditions,
            'evidence_hash':digest([r.get('source_evidence'),item['detail']]),
            'proposal_revision':r.get('revision'),'source_evidence':r.get('source_evidence',[])}
        key=digest([kind,target,version,choice,actor,now.isoformat(),evidence])
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO manager_feedback VALUES (?,?,?,?,?,?,?,?)',
                (key,kind,target,version,choice,actor,now.isoformat(),json.dumps(evidence)))
        return {'state':choice,'execution_authorized':False,'provider_writes':0,'feedback_id':key}

    def feedback_latest(self):
        self.setup()
        with self.connect() as db:
            rows=db.execute('SELECT * FROM manager_feedback ORDER BY at,rowid').fetchall()
        return {(r['kind'],r['target']):{**dict(r),'value':json.loads(r['value'])} for r in rows}

    def link(self,left,relationship,right,truth,evidence):
        if any(r.get('entity_type') not in ENTITY_TYPES or not r.get('entity_id') or not r.get('system') for r in (left,right)) or truth not in TRUTH:
            raise ValueError('Normalized, proven relationship required')
        safe(evidence);self.setup();key=digest([left,relationship,right,truth,evidence])
        with self.connect() as db:db.execute('INSERT OR IGNORE INTO manager_links VALUES (?,?,?,?,?,?)',
            (key,json.dumps(left,sort_keys=True),relationship,json.dumps(right,sort_keys=True),truth,json.dumps(evidence)))

    def receipt(self,job,invocation,now,value):
        safe(value);self.setup()
        with self.connect() as db:db.execute('INSERT OR IGNORE INTO manager_receipts VALUES (?,?,?,?)',
            (digest([job,invocation]),job,now.isoformat(),json.dumps(value)))

    def activity(self,now):
        self.setup();result={}
        with self.connect() as db:
            for days in (1,7):
                rows=db.execute('SELECT value FROM manager_receipts WHERE at>=? AND at<=?',
                    ((now-timedelta(days=days)).isoformat(),now.isoformat())).fetchall()
                totals={};origins={}
                for row in rows:
                    v=json.loads(row['value']);origins[v.get('origin','UNKNOWN')]=origins.get(v.get('origin','UNKNOWN'),0)+1
                    if v.get('state')=='COMPLETED':
                        for k,n in v.get('counters',{}).items():
                            if type(n) is int and n>=0:totals[k]=totals.get(k,0)+n
                result[str(days)+'d']={'observed_receipts':len(rows),'completed_counters':totals,'origins':origins,
                    'coverage':'Retained observed invocations only; collection begins with Phase37. No reconstruction of missing runs.'}
        return result

    def brief(self,day,input_version,now,value):
        safe(value);self.setup();key=digest([day,input_version])
        with self.connect() as db:db.execute('INSERT OR IGNORE INTO manager_briefs VALUES (?,?,?,?,?)',
            (key,day,input_version,now.isoformat(),json.dumps(value)))
        return key

    def learning(self,proposal_id,revision,now,value):
        """Import verified executor/results evidence; never derive an execution from approval."""
        safe(value)
        if value.get('outcome') not in OUTCOMES or not value.get('evidence') or not value.get('limitations'):
            raise ValueError('Evidence-backed result and limitations required')
        if value['outcome'] not in {'BLOCKED','INSUFFICIENT_DATA'} and (not value.get('execution_receipt') or not value.get('baseline_window') or not value.get('post_window')):
            raise ValueError('Execution receipt and comparison windows required')
        item=next((p for p in self.rows() if p['record']['proposal_id']==proposal_id and p['record']['revision']==revision),None)
        if not item:raise ValueError('Exact current proposal required')
        self.setup();key=digest([proposal_id,revision,value])
        with self.connect() as db:db.execute('INSERT OR IGNORE INTO manager_learning VALUES (?,?,?,?,?,?)',
            (key,proposal_id,revision,value['outcome'],now.isoformat(),json.dumps(value)))
        return key

    def counts(self):
        self.setup()
        with self.connect() as db:return {n:db.execute('SELECT count(*) FROM manager_'+n).fetchone()[0]
            for n in ('events','links','feedback','briefs','learning','receipts')}

    def usage(self,now):
        self.setup();totals={};jobs={};count=0
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='provider_usage'").fetchone():
                for row in db.execute('SELECT job,summary_json FROM provider_usage WHERE recorded_at>=? AND recorded_at<=? LIMIT 10000',
                    ((now-timedelta(days=7)).isoformat(),now.isoformat())):
                    v=json.loads(row['summary_json']);count+=1;jobs[row['job']]=jobs.get(row['job'],0)+1
                    for k,n in v.get('calls',{}).items():
                        if type(n) is int and n>=0:totals[k]=totals.get(k,0)+n
        return {'window':'7d','observed_metric_receipts':count,'provider_calls':totals,'jobs':jobs,
            'coverage':'Existing per-job metrics only; uninstrumented reads, invoices and model cost UNKNOWN'}
