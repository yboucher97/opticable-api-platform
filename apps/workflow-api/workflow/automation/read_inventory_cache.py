"""Scheduled Lab display snapshots with changed-since reads, never write evidence.

Every module is checked each run. Daily full reads detect deletions/relationship
removal; failed or incomplete runs do not advance any cursor. Operator APIs and
central mutation preconditions use their original fresh clients. Operator display
reads may reuse one complete inventory for five minutes; source age is explicit.
"""
from datetime import datetime,timezone,timedelta
import hashlib,json,re,sqlite3
from copy import deepcopy

MODULES={'Accounts','Contacts','Deals','Services','Service_Locations'}

class ChangedInventory:
    def __init__(self,client,db_path,*,now=None):
        self.client,self.db_path=client,db_path
        self.now=now or datetime.now(timezone.utc)
        if self.now.utcoffset() is None:raise ValueError('Aware inventory cursor required')
        self.now=self.now.astimezone(timezone.utc);self.pending={};self.stats={'full_reads':0,'delta_reads':0,'unchanged':0}
        with sqlite3.connect(db_path,timeout=5) as db:
            db.execute('CREATE TABLE IF NOT EXISTS crm_display_snapshots (module TEXT PRIMARY KEY, fields_hash TEXT NOT NULL, rows_json TEXT NOT NULL, cursor_at TEXT NOT NULL, full_at TEXT NOT NULL)')
    def request(self,service,method,path,**kwargs):
        parts=path.strip('/').split('/')
        if service!='zohoapis' or method!='GET' or len(parts)!=3 or parts[:2]!=['crm','v8'] or parts[2] not in MODULES:
            raise ValueError('Display snapshot cannot authorize or execute other requests')
        query=dict(kwargs.get('query') or {})
        if set(kwargs)-{'query'} or set(query)!={'fields','per_page','page'} or query['per_page']!=200 or query['page']!=1:
            raise ValueError('Display snapshot requires a complete bounded inventory')
        module=parts[2];fields_hash=hashlib.sha256(str(query['fields']).encode()).hexdigest()
        with sqlite3.connect(self.db_path,timeout=5) as db:
            old=db.execute('SELECT fields_hash,rows_json,cursor_at,full_at FROM crm_display_snapshots WHERE module=?',(module,)).fetchone()
        full=(not old or old[0]!=fields_hash or self.now<datetime.fromisoformat(old[2])
              or self.now-datetime.fromisoformat(old[3])>=timedelta(days=1))
        headers={} if full else {'If-Modified-Since':(datetime.fromisoformat(old[2])-timedelta(minutes=1)).isoformat(timespec='seconds')}
        response=self.client.request(service,method,path,query=query,**({'headers':headers} if headers else {}))
        if response.get('ok') is not True:raise ValueError('Changed inventory read unavailable')
        self.stats['full_reads' if full else 'delta_reads']+=1
        if response.get('status')==304:
            if full:raise ValueError('Unconditional inventory returned no snapshot')
            rows=json.loads(old[1]);self.stats['unchanged']+=1
        else:
            data=response.get('data') or {}
            if response.get('status') != 204 and (not isinstance(data,dict) or 'data' not in data):
                raise ValueError('Changed inventory malformed')
            changed=data.get('data',[])
            if (not isinstance(changed,list) or (data.get('info') or {}).get('more_records')
                    or any(not isinstance(r,dict) or not re.fullmatch(r'[0-9]{1,30}',str(r.get('id',''))) for r in changed)
                    or len({str(r['id']) for r in changed})!=len(changed)):
                raise ValueError('Changed inventory incomplete or ambiguous')
            if not changed and response.get('status') not in {200,204,None}:
                raise ValueError('Changed inventory malformed')
            by_id={} if full else {str(r['id']):r for r in json.loads(old[1])}
            by_id.update({str(r['id']):r for r in changed});rows=list(by_id.values())
        if len(rows)>200:raise ValueError('Display inventory exceeds bounded view')
        self.pending[module]=(fields_hash,json.dumps(rows,sort_keys=True),self.now.isoformat(),self.now.isoformat() if full else old[3])
        return {'ok':True,'status':200,'data':{'data':deepcopy(rows),'info':{'more_records':False}},'provider_path':'scheduled_display_snapshot'}
    def commit(self):
        with sqlite3.connect(self.db_path,timeout=5) as db:
            for module,values in self.pending.items():
                db.execute('INSERT INTO crm_display_snapshots VALUES(?,?,?,?,?) ON CONFLICT(module) DO UPDATE SET '
                    'fields_hash=excluded.fields_hash,rows_json=excluded.rows_json,cursor_at=excluded.cursor_at,full_at=excluded.full_at',(module,*values))


class DisplayInventory:
    """Read projection only. Reuse all five modules together or refresh together."""
    def __init__(self,client,db_path,*,now=None,max_age=300):
        from pathlib import Path
        self.client,self.db_path=client,db_path
        self.now=now or datetime.now(timezone.utc)
        self.cached={};self.refresh=None;self.observed_at=None
        if self.now.utcoffset() is None:raise ValueError('Aware display clock required')
        try:
            with sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True,timeout=1) as db:
                rows=db.execute('SELECT module,fields_hash,rows_json,cursor_at,full_at FROM crm_display_snapshots').fetchall()
            cursors={row[3] for row in rows}
            if ({r[0] for r in rows}!=MODULES or len(cursors)!=1
                    or any(not timedelta(0)<=self.now-datetime.fromisoformat(r[3])<=timedelta(seconds=max_age)
                           or not timedelta(0)<=self.now-datetime.fromisoformat(r[4])<timedelta(days=1) for r in rows)):
                return
            for row in rows:
                value=json.loads(row[2])
                if not isinstance(value,list) or len(value)>200 or any(not isinstance(v,dict) for v in value):return
            self.cached={r[0]:r for r in rows};self.observed_at=next(iter(cursors))
        except (OSError,sqlite3.Error,ValueError,TypeError):pass

    def request(self,service,method,path,**kwargs):
        module=path.strip('/').split('/')[-1]
        query=dict(kwargs.get('query') or {})
        if (service!='zohoapis' or method!='GET' or path!='/crm/v8/'+module or module not in MODULES
                or set(kwargs)!={'query'} or set(query)!={'fields','per_page','page'}
                or query['page']!=1 or query['per_page']!=200):
            raise ValueError('Display projection cannot authorize other requests')
        old=self.cached.get(module)
        fields_hash=hashlib.sha256(str(query['fields']).encode()).hexdigest()
        if old and old[1]==fields_hash and self.refresh is None:
            return {'ok':True,'status':200,'data':{'data':json.loads(old[2]),'info':{'more_records':False}},'provider_path':'shared_read_projection'}
        self.cached={};self.observed_at=self.now.isoformat()
        if self.refresh is None:self.refresh=ChangedInventory(self.client,self.db_path,now=self.now)
        return self.refresh.request(service,method,path,**kwargs)

    def commit(self):
        if self.refresh:
            if set(self.refresh.pending)!=MODULES:raise ValueError('Complete display projection required')
            self.refresh.commit()


def build_lifecycle_display(client,db_path,*,scope='live',now=None,registry_path=None):
    from .customer_lifecycle import build_customer_lifecycle,_local,ACCOUNT_FIELDS,CONTACT_FIELDS,DEAL_FIELDS
    from .service_inventory import LOCATION_FIELDS,SERVICE_FIELDS
    projection=DisplayInventory(client,db_path,now=now)
    fields={'Accounts':ACCOUNT_FIELDS,'Contacts':CONTACT_FIELDS,'Deals':DEAL_FIELDS,
            'Service_Locations':LOCATION_FIELDS,'Services':SERVICE_FIELDS}
    if projection.cached and any(projection.cached[module][1]!=hashlib.sha256(value.encode()).hexdigest() for module,value in fields.items()):
        projection.cached={}
    view=build_customer_lifecycle(projection,scope=scope,now=projection.now,
                                  **({'registry_path':registry_path} if registry_path is not None else {}))
    projection.commit()
    view['projection_observed_at']=projection.observed_at
    view['projection_cached']=projection.refresh is None
    view['read_at']=_local(projection.observed_at)
    return view
