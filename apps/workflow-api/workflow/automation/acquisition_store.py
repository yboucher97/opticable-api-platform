"""Rebuildable acquisition evidence in the existing journal database.

These tables authorize no CRM writes, contact clearance, spend or publication.
Source snapshots and facts are independent; conflicting facts are retained.
"""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import hashlib
import json
import re
import sqlite3
import unicodedata
import zlib
from urllib.parse import urlsplit,parse_qsl
from .sales_intelligence import domain, email, live

KINDS=set('COMPANY PERSON LOCATION PROJECT TRIGGER KEYWORD SEARCH_TOPIC SERP_RESULT COMPETITOR COMPETITOR_PAGE CONTENT_TOPIC CONTENT_ASSET OPTICABLE_PAGE AD_KEYWORD AD_SEARCH_TERM AD_COMPETITOR MARKET_SEGMENT ICP SERVICE SOURCE OBSERVATION OPPORTUNITY OUTREACH_STATE SUPPRESSION SOURCE_PERFORMANCE'.split())
HEALTH=set('CONNECTED WORKING PARTIAL BLOCKED RATE_LIMITED NO_CREDITS PLAN_LIMITED AUTH_EXPIRED UNKNOWN'.split())
REFRESH={'search_console':86400,'ga4':86400,'google_ads':86400,'gbp':604800,'apollo':21600,
         'permits':86400,'seao':86400,'website':604800,'competitors':604800,'registry':2592000,
         'semrush':2592000,'ahrefs':2592000,'clay':2592000,'windsor':86400,
         'facebook_organic':604800,'instagram':604800,'linkedin_organic':604800}
REFRESH['windsor_keyword_planner']=2592000


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def normalized(value):return ' '.join(unicodedata.normalize('NFKC',str(value)).strip().casefold().split())


def safe(value):
    if isinstance(value,dict):
        for k,v in value.items():
            if re.search(r'(^|_)(access_token|refresh_token|api_key|password|authorization|cookie|secret)($|_)',k,re.I):
                raise ValueError('Credentials must never enter acquisition evidence')
            safe(v)
    elif isinstance(value,list):
        for v in value:safe(v)
    elif isinstance(value,str) and value.startswith(('https://','http://')):
        parsed=urlsplit(value)
        if parsed.username or parsed.password or any(re.search(r'token|secret|password|api[_-]?key|authorization|signature',k,re.I) for k,v in parse_qsl(parsed.query)):
            raise ValueError('Credential-bearing URLs must never enter acquisition evidence')


def aliases(kind,row,source,native_id):
    result=[source+':'+str(native_id)] if native_id else []
    if kind=='COMPANY':
        d=domain(row.get('domain') or row.get('website'))
        if d and d not in {'facebook.com','instagram.com','linkedin.com','youtube.com','linktr.ee','business.site'}:result.append('domain:'+d)
        for field in ('registry_number','apollo_organization_id','clay_company_id','crm_account_id'):
            if row.get(field):result.append(field+':'+str(row[field]))
    elif kind=='PERSON':
        e=email(row.get('email'))
        if e:result.append('email:'+e)
        for field in ('apollo_contact_id','crm_contact_id'):
            if row.get(field):result.append(field+':'+str(row[field]))
    elif kind=='KEYWORD':
        if not row.get('query') or row.get('language') not in ('FR','EN','UNKNOWN'):raise ValueError('Keyword language required')
        result.append('query:'+digest([normalized(row['query']),row['language'],row.get('geography','UNKNOWN')]))
    elif kind=='LOCATION':
        # No fuzzy street/building merge, including unit. Native site ID wins.
        if row.get('crm_site_id'):result.append('crm_site_id:'+str(row['crm_site_id']))
        if row.get('address') and row.get('postal_code'):
            result.append('address:'+digest([normalized(row['address']),normalized(row.get('unit','')),normalized(row['postal_code']).replace(' ',''),row.get('country','CA')]))
    if not result:raise ValueError('A deterministic source or business identity is required')
    return sorted(set(result))


class AcquisitionStore:
    def __init__(self,path):self.path=str(path);self.initialized=False

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5);db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        if not self.initialized:db.executescript('''
        CREATE TABLE IF NOT EXISTS acquisition_entities(id TEXT PRIMARY KEY,kind TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS acquisition_aliases(kind TEXT NOT NULL,alias TEXT NOT NULL,entity TEXT NOT NULL REFERENCES acquisition_entities(id),PRIMARY KEY(kind,alias));
        CREATE TABLE IF NOT EXISTS acquisition_snapshots(id TEXT PRIMARY KEY,source TEXT NOT NULL,source_url TEXT NOT NULL,retrieved_at TEXT NOT NULL,effective_from TEXT,effective_to TEXT,raw BLOB NOT NULL,raw_bytes INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS acquisition_facts(id TEXT PRIMARY KEY,entity TEXT NOT NULL REFERENCES acquisition_entities(id),source TEXT NOT NULL,source_record_id TEXT NOT NULL,source_url TEXT NOT NULL,retrieved_at TEXT NOT NULL,observed_at TEXT,effective_date TEXT,raw_value TEXT NOT NULL,normalized_value TEXT NOT NULL,confidence TEXT NOT NULL,cost_class TEXT NOT NULL,snapshot TEXT REFERENCES acquisition_snapshots(id));
        CREATE INDEX IF NOT EXISTS acquisition_facts_entity ON acquisition_facts(entity,retrieved_at);
        CREATE TABLE IF NOT EXISTS acquisition_conflicts(id TEXT PRIMARY KEY,kind TEXT NOT NULL,aliases TEXT NOT NULL,entities TEXT NOT NULL,at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS acquisition_sources(source TEXT PRIMARY KEY,state TEXT NOT NULL,at TEXT NOT NULL,observed_at TEXT,reason TEXT NOT NULL,refresh_seconds INTEGER NOT NULL,request_count INTEGER NOT NULL,cost_class TEXT NOT NULL,credits REAL,last_query TEXT,cache_hits INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS acquisition_timeseries(id TEXT PRIMARY KEY,source TEXT NOT NULL,provider_date TEXT NOT NULL,raw TEXT NOT NULL,snapshot_proof TEXT NOT NULL,retrieved_at TEXT NOT NULL);
        ''')
        self.initialized=True
        try:
            with db:yield db
        finally:db.close()

    def snapshot(self,source,url,raw,now,*,effective_from=None,effective_to=None):
        safe(raw);safe(url)
        if not source or not url.startswith('https://') or now.tzinfo is None:raise ValueError('Source provenance required')
        blob=json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()
        if len(blob)>2097152:raise ValueError('Snapshot exceeds 2 MiB; use bounded chunks')
        sid=digest([source,effective_from,effective_to,hashlib.sha256(blob).hexdigest()])
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO acquisition_snapshots VALUES (?,?,?,?,?,?,?,?)',
                       (sid,source,url,now.isoformat(),effective_from,effective_to,zlib.compress(blob),len(blob)))
        return sid

    def record(self,kind,row,*,source,native_id,url,now,snapshot=None,observed_at=None,
               effective_date=None,confidence='DIRECTLY OBSERVED',cost_class='NO PAID ENRICHMENT',raw=None):
        if kind not in KINDS or now.tzinfo is None or not url.startswith('https://'):raise ValueError('Invalid acquisition fact')
        safe(url);safe(row);safe(raw if raw is not None else row)
        if not live(row):return {'state':'TEST EXCLUDED','provider_writes':0}
        candidates=aliases(kind,row,source,native_id)
        with self.connect() as db:
            hits={r['entity'] for a in candidates for r in db.execute('SELECT entity FROM acquisition_aliases WHERE kind=? AND alias=?',(kind,a))}
            if len(hits)>1:
                cid=digest([kind,candidates,sorted(hits)])
                db.execute('INSERT OR IGNORE INTO acquisition_conflicts VALUES (?,?,?,?,?)',(cid,kind,json.dumps(candidates),json.dumps(sorted(hits)),now.isoformat()))
                return {'state':'IDENTITY CONFLICT — HUMAN REVIEW','id':cid,'provider_writes':0}
            eid=next(iter(hits)) if hits else digest([kind,candidates[0]])
            db.execute('INSERT OR IGNORE INTO acquisition_entities VALUES (?,?,?)',(eid,kind,now.isoformat()))
            for a in candidates:db.execute('INSERT OR IGNORE INTO acquisition_aliases VALUES (?,?,?)',(kind,a,eid))
            raw_text=json.dumps(raw if raw is not None else row,sort_keys=True,ensure_ascii=False)
            text=json.dumps(row,sort_keys=True,ensure_ascii=False)
            if len(text.encode())>65536 or len(raw_text.encode())>131072:raise ValueError('Record exceeds acquisition byte bound')
            fid=digest([eid,source,str(native_id),snapshot,effective_date,text])
            before=db.total_changes
            db.execute('INSERT OR IGNORE INTO acquisition_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (fid,eid,source,str(native_id or ''),url,now.isoformat(),observed_at,effective_date,raw_text,text,confidence,cost_class,snapshot))
            return {'state':'RECORDED' if db.total_changes>before else 'REPLAY','id':eid,'fact':fid,'provider_writes':0}

    def source(self,source,state,now,*,observed_at=None,reason='',requests=0,cost_class='EXISTING ACCESS',credits=None,query=None,cache_hit=False):
        state=state.replace(' ','_')
        if state not in HEALTH or now.tzinfo is None:raise ValueError('Invalid source health')
        with self.connect() as db:
            prior=db.execute('SELECT cache_hits FROM acquisition_sources WHERE source=?',(source,)).fetchone()
            db.execute('INSERT OR REPLACE INTO acquisition_sources VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (source,state,now.isoformat(),observed_at,reason,REFRESH.get(source,86400),requests,cost_class,credits,query,(prior['cache_hits'] if prior else 0)+int(cache_hit)))

    def due(self,source,now):
        with self.connect() as db:row=db.execute('SELECT * FROM acquisition_sources WHERE source=?',(source,)).fetchone()
        if not row:return True
        at=datetime.fromisoformat(row['at'])
        return (now-at).total_seconds()>=row['refresh_seconds']

    def timeseries(self,source,provider_date,raw,snapshot,now):
        safe(raw)
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',provider_date):raise ValueError('Provider daily date required')
        # Immutable metric variants retain corrections instead of silently merging.
        with self.connect() as db:db.execute('INSERT OR IGNORE INTO acquisition_timeseries VALUES (?,?,?,?,?,?)',
            (digest([source,provider_date,raw]),source,provider_date,json.dumps(raw,sort_keys=True),snapshot,now.isoformat()))

    def view(self,kind=None):
        with self.connect() as db:
            records=[]
            for e in db.execute('SELECT * FROM acquisition_entities'+(' WHERE kind=?' if kind else '')+' ORDER BY id',(kind,) if kind else ()):
                facts=[{**dict(r),'raw_value':json.loads(r['raw_value']),'normalized_value':json.loads(r['normalized_value'])} for r in db.execute('SELECT * FROM acquisition_facts WHERE entity=? ORDER BY retrieved_at,id',(e['id'],))]
                records.append({**dict(e),'facts':facts})
            return records

    def summary(self,now):
        with self.connect() as db:
            counts={r['kind']:r['n'] for r in db.execute('SELECT kind,count(*) n FROM acquisition_entities GROUP BY kind')}
            health=[]
            for r in db.execute('SELECT * FROM acquisition_sources ORDER BY source'):
                value=dict(r);at=datetime.fromisoformat(value['observed_at'] or value['at'])
                value['stale']=(now-at).total_seconds()>value['refresh_seconds']
                health.append(value)
            return {'counts':counts,'source_health':health,
                'snapshots':db.execute('SELECT count(*) FROM acquisition_snapshots').fetchone()[0],
                'facts':db.execute('SELECT count(*) FROM acquisition_facts').fetchone()[0],
                'identity_conflicts':db.execute('SELECT count(*) FROM acquisition_conflicts').fetchone()[0],
                'daily_history_rows':db.execute('SELECT count(*) FROM acquisition_timeseries').fetchone()[0],
                'provider_writes':0,'crm_promotions':0,'cold_outbound_enabled':False}

    def prune(self,now):
        # Keep up to 12 snapshots/source within 90 days. Facts referencing old
        # snapshots retire together. Current snapshot remains reconstructable;
        # prior immutable phase receipts remain in normal recovery archives.
        cutoff=(now-timedelta(days=90)).isoformat()
        with self.connect() as db:
            for source in [r[0] for r in db.execute('SELECT DISTINCT source FROM acquisition_snapshots')]:
                rows=db.execute('SELECT id,retrieved_at FROM acquisition_snapshots WHERE source=? ORDER BY retrieved_at DESC,id',(source,)).fetchall()
                for n,row in enumerate(rows):
                    if n>=12 or n>0 and row['retrieved_at']<cutoff:
                        db.execute('DELETE FROM acquisition_facts WHERE snapshot=?',(row['id'],));db.execute('DELETE FROM acquisition_snapshots WHERE id=?',(row['id'],))
            # Never retain empty historical entities as current opportunities.
            empty=[r[0] for r in db.execute('SELECT id FROM acquisition_entities WHERE id NOT IN (SELECT entity FROM acquisition_facts)')]
            for eid in empty:
                db.execute('DELETE FROM acquisition_aliases WHERE entity=?',(eid,));db.execute('DELETE FROM acquisition_entities WHERE id=?',(eid,))
            db.execute('''DELETE FROM acquisition_facts AS old WHERE snapshot IS NULL AND retrieved_at < ?
                AND EXISTS (SELECT 1 FROM acquisition_facts AS newer WHERE newer.entity=old.entity AND newer.source=old.source
                AND (newer.retrieved_at>old.retrieved_at OR newer.retrieved_at=old.retrieved_at AND newer.id>old.id))''',((now-timedelta(days=365)).isoformat(),))
            db.execute('DELETE FROM acquisition_timeseries WHERE provider_date < ?',((now-timedelta(days=730)).date().isoformat(),))
