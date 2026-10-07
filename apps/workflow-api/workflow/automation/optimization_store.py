"""Shared proposal/priority/asset persistence, never an execution authority.

Immutable revisions and domain details share the existing research database.
Local review is additive; no provider client, writer, approval grant or scheduler.
"""
from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import json
import sqlite3
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from .acquisition_store import digest, safe

SCHEMA = Path(__file__).resolve().parents[4]/'docs/optibrain-optimization.schema.json'
KINDS = {'optibrain.optimization_proposal':'proposal_id',
         'optibrain.business_priority':'priority_id', 'optibrain.optimization_asset':'asset_id'}
REVIEW = {'REVIEWED':'OWNER_REVIEW','REJECT':'REJECTED','RESEARCH':'RESEARCHING'}


@lru_cache(maxsize=1)
def validator():
    schema=json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema,format_checker=FormatChecker())


def validate(record):
    safe(record)
    try: validator().validate(record)
    except ValidationError as exc: raise ValueError('Shared optimization contract rejected record') from exc
    return record


class OptimizationStore:
    def __init__(self,path): self.path=Path(path)

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS optimization_records (
                kind TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
                payload_hash TEXT NOT NULL, record TEXT NOT NULL, detail TEXT NOT NULL,
                PRIMARY KEY(kind,id,revision));
            CREATE TABLE IF NOT EXISTS optimization_reviews (
                id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, revision INTEGER NOT NULL,
                payload_hash TEXT NOT NULL, choice TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL);
            ''')
            from .action_evidence import ActionEvidence
            ActionEvidence.setup(db)
            with db: yield db
        finally: db.close()

    def record(self,record,detail=None,*,revision=None):
        validate(record);detail=deepcopy(detail or {});safe(detail)
        if record['type'] in {'optibrain.optimization_proposal','optibrain.business_priority'}:
            from .decision_card import decision_card
            card=decision_card({'record':record,'detail':detail})
        kind=record['type'];identifier=record[KINDS[kind]];revision=record.get('revision',revision or 1)
        raw=json.dumps(record,sort_keys=True,ensure_ascii=False,allow_nan=False)
        details=json.dumps(detail,sort_keys=True,ensure_ascii=False,allow_nan=False)
        if len(raw.encode())+len(details.encode())>262144: raise ValueError('Optimization revision exceeds bound')
        fingerprint=digest([record,detail])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT * FROM optimization_records WHERE kind=? AND id=? AND revision=?',(kind,identifier,revision)).fetchone()
            if prior:
                if prior['payload_hash']!=fingerprint: raise ValueError('Immutable optimization revision conflict')
                return {'state':'EXACT_REPLAY','payload_hash':fingerprint,'provider_writes':0}
            latest=db.execute('SELECT max(revision) FROM optimization_records WHERE kind=? AND id=?',(kind,identifier)).fetchone()[0]
            if latest is not None and revision!=latest+1: raise ValueError('Consecutive optimization revision required')
            if latest is None and revision!=1: raise ValueError('Initial optimization revision must be one')
            if latest is not None and (record.get('approved_at') or record.get('approved_by')):
                raise ValueError('A changed revision cannot inherit approval')
            db.execute('INSERT INTO optimization_records VALUES (?,?,?,?,?,?)',(kind,identifier,revision,fingerprint,raw,details))
            from .action_evidence import local_record, stamp
            from datetime import datetime, timezone
            now=datetime.now(timezone.utc)
            previous=db.execute('SELECT payload_hash FROM optimization_records WHERE kind=? AND id=? AND revision<? ORDER BY revision DESC LIMIT 1',(kind,identifier,revision)).fetchone()
            local_record(db,digest(['optimization',kind,identifier,revision,fingerprint]),'OPTIMIZATION_REVISION',
                {'type':kind,'identity':identifier},now,before={'payload_hash':previous['payload_hash']} if previous else {'exists':False},
                after={'revision':revision,'payload_hash':fingerprint},reason=record.get('business_problem') or record.get('why') or 'Shared canonical asset revision',
                proposal_id=record.get('proposal_id'),priority_id=record.get('priority_id'),
                evidence_refs=record.get('source_evidence',[]),exact_versions={'revision':revision,'payload_hash':fingerprint},
                pros=card['pros'] if kind!='optibrain.optimization_asset' else [],
                cons=card['cons'] if kind!='optibrain.optimization_asset' else [],
                risks=card['risks'] if kind!='optibrain.optimization_asset' else [],
                expected_benefit=record.get('expected_benefit') or record.get('business_impact'),
                known_downside=card['cons'][0] if kind!='optibrain.optimization_asset' else None,
                confidence=record.get('confidence','UNKNOWN'),
                confidence_reason=card['confidence']['reason'] if kind!='optibrain.optimization_asset' else 'Asset performance is unmeasured')
        return {'state':'RECORDED','payload_hash':fingerprint,'provider_writes':0}

    def rows(self,kind='optibrain.optimization_proposal'):
        if kind not in KINDS: raise ValueError('Unsupported optimization record type')
        with self.connect() as db:
            rows=db.execute('''SELECT r.* FROM optimization_records r WHERE kind=? AND revision=(
                SELECT max(revision) FROM optimization_records n WHERE n.kind=r.kind AND n.id=r.id) ORDER BY id''',(kind,)).fetchall()
            result=[]
            for row in rows:
                item={'record':json.loads(row['record']),'detail':json.loads(row['detail']),'payload_hash':row['payload_hash']}
                from .action_evidence import ActionEvidence
                aid=digest(['optimization',kind,row['id'],row['revision'],row['payload_hash']])
                item['audit_action_id']=aid if ActionEvidence.current(db,aid) else None
                review=db.execute('SELECT choice,at FROM optimization_reviews WHERE proposal_id=? AND revision=? AND payload_hash=? ORDER BY at DESC,rowid DESC LIMIT 1',
                                  (row['id'],row['revision'],row['payload_hash'])).fetchone()
                item['review']=dict(review) if review else None
                item['effective_status']=REVIEW[review['choice']] if review else item['record'].get('status')
                if kind=='optibrain.optimization_proposal' and review is None:
                    rejected=db.execute("SELECT r.record,r.detail FROM optimization_reviews v JOIN optimization_records r ON r.kind=? AND r.id=v.proposal_id AND r.revision=v.revision WHERE v.proposal_id=? AND v.choice='REJECT' ORDER BY v.at DESC,v.rowid DESC LIMIT 1",(kind,row['id'])).fetchone()
                    if rejected:
                        from .manager_intelligence import semantic_evidence
                        if semantic_evidence(json.loads(rejected['record']),json.loads(rejected['detail']))==semantic_evidence(item['record'],item['detail']):
                            item['effective_status']='REJECTED'
                # Shared local intent is visible in every domain surface. It
                # never changes canonical records or grants transport authority.
                if kind=='optibrain.optimization_proposal' and db.execute("SELECT 1 FROM sqlite_master WHERE name='manager_feedback'").fetchone():
                    f=db.execute("SELECT * FROM manager_feedback WHERE kind='PROPOSAL' AND target=? ORDER BY at DESC,rowid DESC LIMIT 1",(row['id'],)).fetchone()
                    if f:
                        from .manager_intelligence import semantic_evidence
                        value=json.loads(f['value'])
                        same=f['version']==row['payload_hash']
                        repeat=f['choice'] in {'REJECT','NOT_RELEVANT','WAIT'} and value.get('semantic_evidence')==semantic_evidence(item['record'],item['detail'])
                        if same or repeat or f['choice']=='NEVER':
                            item['effective_status']={'APPROVE':'APPROVED','REJECT':'REJECTED','REQUEST_REVISION':'RESEARCHING'}.get(f['choice'],f['choice'])
                if kind in {'optibrain.optimization_proposal','optibrain.business_priority'}:
                    from .decision_card import decision_card
                    item['decision_card']=decision_card(item)
                result.append(item)
            return result

    def review(self,identifier,revision,fingerprint,choice,actor,now):
        if choice not in REVIEW or not actor or len(actor)>200 or now.tzinfo is None:
            raise ValueError('Local review only; execution approval unavailable')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM optimization_records WHERE kind=? AND id=? ORDER BY revision DESC LIMIT 1',('optibrain.optimization_proposal',identifier)).fetchone()
            if not row or row['revision']!=revision or row['payload_hash']!=fingerprint:
                raise ValueError('Fresh exact revision review required')
            eid=digest([identifier,revision,fingerprint,choice,actor,now.isoformat()])
            db.execute('INSERT OR IGNORE INTO optimization_reviews VALUES (?,?,?,?,?,?,?)',
                       (eid,identifier,revision,fingerprint,choice,actor,now.isoformat()))
        return {'state':REVIEW[choice],'provider_writes':0,'execution_authorized':False}

    def execution_allowed(self,*args,**kwargs):
        # Approval records, recovered records and simulated status never arm Ads.
        return False
