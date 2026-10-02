"""Small per-job transport counters. No URLs, payloads, tokens or business IDs.

Metrics are expendable observations, never mutation/ownership evidence. History
is capped at 30 days/10,000 rows per existing store; action journals are untouched.
"""
from collections import Counter
from contextvars import ContextVar
from datetime import datetime,timezone,timedelta
import json,logging,re,sqlite3
from threading import Lock
from time import monotonic

CURRENT = ContextVar('optibrain_provider_usage',default=None)
KINDS = ('crm_get','crm_write','mail_get','mail_mutation','forms_get','forms_mutation',
         'sign_get','sign_mutation','books_get','books_write','other_zoho',
         'cloudflare','github','r2','google','oauth_refresh')
LOG = logging.getLogger(__name__)

def call_kind(provider,method,path=''):
    method=method.upper()
    if provider=='zohoapis' and path.startswith('/crm/'):
        kind='crm_get' if method=='GET' else 'crm_write'
    elif provider=='zohoapis' and path.startswith('/books/'):
        kind='books_get' if method=='GET' else 'books_write'
    elif provider=='mail':kind='mail_get' if method=='GET' else 'mail_mutation'
    elif provider in {'forms','sign'}:kind=provider+('_get' if method=='GET' else '_mutation')
    elif provider in {'cloudflare','github','r2','google','oauth_refresh'}:kind=provider
    else:kind='other_zoho'
    return kind

def record_call(provider,method,path=''):
    scope=CURRENT.get()
    if scope is None:return
    kind=call_kind(provider,method,path)
    with scope.lock:
        scope.counts[kind]+=1
        scope.methods[kind+('::read' if method.upper() in {'GET','HEAD'} else '::write')]+=1
        if provider=='mail' and path.endswith('/content'):scope.details['mail_content_get']+=1
        if provider=='zohoapis' and path.endswith('/actions/watch'):scope.details['crm_watch_get']+=1

def record_response(provider,method,path,status):
    scope=CURRENT.get()
    if scope is None:return
    with scope.lock:
        key=call_kind(provider,method,path)
        scope.outcomes[key+('::ok' if 200<=status<300 or status==304 else '::failed')]+=1
        scope.last_response[key]='ok' if 200<=status<300 or status==304 else 'failed'

def mail_observation_failed(count):
    scope=CURRENT.get()
    if scope is not None:
        with scope.lock:scope.details['mail_observation_failed']+=count

def measured(db_path,job):
    """Account authenticated route work; rejected identities make no calls."""
    from functools import wraps
    import inspect
    def decorate(fn):
        @wraps(fn)
        async def route(*args,**kwargs):
            with ProviderUsage(db_path,job):
                return await fn(*args,**kwargs)
        route.__signature__=inspect.signature(fn,eval_str=True)
        return route
    return decorate

class ProviderUsage:
    def __init__(self,db_path,job,*,runs_per_day=0,soft_budget=20,persist_empty=True):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',job):raise ValueError('Invalid metric job name')
        self.db_path,self.job,self.runs_per_day,self.soft_budget=db_path,job,runs_per_day,soft_budget
        self.persist_empty=persist_empty
        self.counts=Counter();self.methods=Counter();self.details=Counter();self.outcomes=Counter();self.last_response={}
        self.lock=Lock();self.started=monotonic();self.summary=None
    def __enter__(self):
        self.token=CURRENT.set(self);return self
    def __exit__(self,kind,value,tb):
        CURRENT.reset(self.token)
        counts={k:self.counts[k] for k in KINDS};total=sum(counts.values())
        self.summary={'schema':2,'job':self.job,'status':'failed' if kind or self.details['mail_observation_failed'] or 'failed' in self.last_response.values() else 'success','calls':counts,
            'calls_by_method':dict(self.methods),'details':dict(self.details),'outcomes':dict(self.outcomes),'last_response':self.last_response,
            'calls_run':total,'calls_hour_estimate':total*self.runs_per_day/24,
            'calls_day_estimate':total*self.runs_per_day,'soft_budget':self.soft_budget,
            'budget_exceeded':total>self.soft_budget,'duration_ms':int((monotonic()-self.started)*1000)}
        (LOG.warning if self.summary['budget_exceeded'] else LOG.info)('provider_usage %s',json.dumps(self.summary,sort_keys=True))
        if self.db_path is None or not total and not self.persist_empty:return False
        try:
            with sqlite3.connect(self.db_path,timeout=0.5) as db:
                db.execute('CREATE TABLE IF NOT EXISTS provider_usage (id INTEGER PRIMARY KEY, job TEXT NOT NULL, recorded_at TEXT NOT NULL, summary_json TEXT NOT NULL)')
                db.execute('CREATE INDEX IF NOT EXISTS idx_provider_usage_time ON provider_usage(recorded_at)')
                now=datetime.now(timezone.utc)
                db.execute('INSERT INTO provider_usage(job,recorded_at,summary_json) VALUES(?,?,?)',
                    (self.job,now.isoformat(),json.dumps(self.summary,sort_keys=True)))
                db.execute('DELETE FROM provider_usage WHERE recorded_at<?',((now-timedelta(days=30)).isoformat(),))
                db.execute('DELETE FROM provider_usage WHERE id NOT IN (SELECT id FROM provider_usage ORDER BY id DESC LIMIT 10000)')
        except (OSError,sqlite3.Error):
            # A monitoring write must never mask an execution outcome or turn an
            # ordinary soft budget overrun into an application shutdown.
            LOG.warning('provider_usage persistence unavailable for job=%s',self.job)
        return False
