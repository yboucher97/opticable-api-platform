"""Private command-center adapter over the existing Review backend and journal.

No provider clients, scheduler, database setup, forwarding-header trust or offline
business cache. Every route (including assets/errors) needs a verified Access
human JWT. Staging uses a distinct test issuer/key and cannot record decisions.
"""
from dataclasses import dataclass,field
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI,Request
from fastapi.responses import Response,JSONResponse
from workflow.operator_access import AccessIdentityVerifier

COOKIE='__Host-optibrain'
ASSETS=Path(__file__).with_name('command_center_assets')
SECTIONS=('overview','sales','marketing','content','review','files','system','settings')


@dataclass(frozen=True)
class Config:
    origin: str
    team_domain: str
    audience: str
    owner_emails: tuple[str,...]
    mode: str='staging'
    editorial_writes: bool=False
    session_seconds: int=1200
    absolute_seconds: int=28800
    member_roles: dict=field(default_factory=dict)

    def __post_init__(self):
        u=urlsplit(self.origin)
        if u.scheme!='https' or not u.hostname or u.path or u.query or u.fragment or u.username or u.password:
            raise ValueError('Exact HTTPS origin required')
        if self.mode not in ('staging','production') or not 1<=self.session_seconds<=1200 or not 1<=self.absolute_seconds<=28800:
            raise ValueError('Bounded session configuration required')
        if self.mode=='production' and (self.origin!='https://app.opticable.ca' or self.team_domain!='https://opticable.cloudflareaccess.com'):
            raise ValueError('Exact approved production host and issuer required')
        if self.mode=='staging' and (self.editorial_writes or not u.hostname in ('localhost','127.0.0.1')):
            raise ValueError('Staging is loopback and cannot record editorial decisions')
        if set(self.member_roles)&set(self.owner_emails) or any(v not in ('viewer','reviewer') for v in self.member_roles.values()):
            raise ValueError('Explicit separate future role bindings required')


def read_projection(path, maximum=1048576):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>maximum:return {}
    try:return json.loads(p.read_text())
    except (OSError,ValueError):return {}


def item_card(item):
    keys=('id','sha256','logical_path','title','category','language','service','platform','registered_at','approval_separation','execution_scope','queue')
    return {k:item.get(k) for k in keys}


def package_card(package):
    return {k:package.get(k) for k in ('id','key','title','score','decision','freshness','pending_items','member_count','status','manifest_sha256','approval_scope','execution_enabled')}


class Sessions:
    """Bounded volatile sessions; cookies alone never authenticate the origin."""
    def __init__(self,config,clock=time.time):
        self.config=config;self.clock=clock;self.values={};self.revoked={};self.lock=threading.RLock()

    def prune(self):
        now=self.clock()
        self.values={k:v for k,v in self.values.items() if v['expires']>now}
        self.revoked={k:v for k,v in self.revoked.items() if v>now}

    def current(self,request,principal,csrf=False):
        with self.lock:
            self.prune();token=request.cookies.get(COOKIE,'');v=self.values.get(sha256(token.encode()).hexdigest())
            if not v or v['subject']!=principal.subject or v['email']!=principal.email:raise PermissionError('Current owner session required')
            if csrf and not hmac.compare_digest(request.headers.get('x-optibrain-csrf',''),v['csrf']):raise PermissionError('Current CSRF required')
            return v

    def issue(self,principal,previous=None):
        with self.lock:
            self.prune()
            if len(self.values)>=128:raise PermissionError('Session capacity reached')
            now=self.clock();token=secrets.token_urlsafe(32);key=sha256(token.encode()).hexdigest()
            created=previous['created'] if previous else now
            until=min(now+self.config.session_seconds,created+self.config.absolute_seconds,principal.expires_at)
            if until<=now:raise PermissionError('Primary identity expired')
            v={'subject':principal.subject,'email':principal.email,'csrf':secrets.token_urlsafe(32),'created':created,'expires':until}
            self.values[key]=v;return token,v


class Projection:
    def __init__(self,review,clock=time.time):self.review=review;self.clock=clock;self.cached=None;self.until=0;self.signature=None;self.lock=threading.RLock()
    def queue(self):
        with self.lock:
            p=self.review.artifacts.parent/'latest-cycle.json'
            signature=p.stat().st_mtime_ns if p.exists() else None
            if self.cached is None or self.clock()>=self.until or signature!=self.signature:
                self.cached=self.review.queue(datetime.fromtimestamp(self.clock(),timezone.utc));self.until=self.clock()+15;self.signature=signature
            return self.cached
    def clear(self):
        with self.lock:self.cached=None


def create_app(review,config,*,key_resolver=None,clock=time.time,readiness='/run/optibrain-readiness/status.json'):
    # Resolver injection is a Python-only test seam. No HTTP/config key override.
    verifier=AccessIdentityVerifier(team_domain=config.team_domain,audience=config.audience,allowed_emails=tuple(config.owner_emails)+tuple(config.member_roles),key_resolver=key_resolver)
    sessions=Sessions(config,clock);projection=Projection(review,clock)
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    app.state.sessions=sessions;app.state.projection=projection
    canonical=urlsplit(config.origin).netloc
    csp="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; manifest-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; worker-src 'none'"
    headers={'Cache-Control':'private, no-store, max-age=0','Pragma':'no-cache','Vary':'Cookie, Cf-Access-Jwt-Assertion, Sec-Fetch-Site, Sec-Fetch-Mode, Sec-Fetch-Dest',
        'X-Robots-Tag':'noindex, nofollow, noarchive, nosnippet','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
        'X-Frame-Options':'DENY','Content-Security-Policy':csp,'Permissions-Policy':'camera=(), microphone=(), geolocation=(), payment=()',
        'Strict-Transport-Security':'max-age=31536000' if config.mode=='production' else 'max-age=0'}

    def error(status,message):return JSONResponse({'error':message},status_code=status,headers=headers)

    @app.middleware('http')
    async def boundary(request,call_next):
        raw=request.scope.get('raw_path',b'').decode('latin1')
        for name in (b'host',b'cf-access-jwt-assertion',b'origin',b'content-length',b'cookie',b'sec-fetch-site',b'sec-fetch-mode',b'sec-fetch-dest'):
            if sum(k.lower()==name for k,v in request.scope['headers'])>1:return error(400,'Ambiguous request headers')
        if request.headers.get('host','').lower()!=canonical or request.url.scheme!='https':return error(403,'Canonical HTTPS origin required')
        if any(x in raw.lower() for x in ('%2f','%5c','%2e','\\','//')):return error(404,'Unknown route')
        if request.headers.get('origin') not in (None,config.origin):return error(403,'Same-origin request required')
        # An SSO return is a cross-site document navigation, not an API call.
        # These headers narrow the exception; the signed owner JWT below still
        # authenticates every request. No iframe, alternate path or mutation.
        destination=request.headers.get('sec-fetch-dest')
        if destination in ('iframe','frame','object','embed','fencedframe'):return error(403,'Embedded navigation denied')
        cross_site=request.headers.get('sec-fetch-site')=='cross-site'
        owner_entry=(request.method=='GET' and raw=='/' and
                     request.headers.get('sec-fetch-mode')=='navigate' and destination=='document')
        if cross_site and not owner_entry:return error(403,'Cross-site request denied')
        if request.headers.get('upgrade'):return error(403,'Protocol upgrade is not enabled')
        token=request.headers.get('cf-access-jwt-assertion','')
        try:
            principal=verifier.verify(token)
            if not principal.expires_at or principal.expires_at<=clock():return error(401,'Primary identity expired')
            if cross_site and principal.email not in config.owner_emails:return error(403,'Owner permission required')
            request.state.principal=principal;request.state.token_hash=sha256(token.encode()).hexdigest()
            with sessions.lock:
                sessions.prune()
                if request.state.token_hash in sessions.revoked:return error(401,'Signed out; sign in again through Access')
        except PermissionError:return error(403,'Owner permission required')
        except ValueError:return error(401,'Verified human Access identity required')
        if request.method not in ('GET','HEAD','POST'):return error(405,'Method not enabled')
        if request.method=='POST':
            if request.headers.get('origin')!=config.origin:return error(403,'Same-origin POST required')
            if request.headers.get('content-type')!='application/json':return error(415,'JSON request required')
            if request.headers.get('transfer-encoding'):return error(400,'Chunked mutations are not accepted')
            try:size=int(request.headers.get('content-length','0'))
            except ValueError:return error(400,'Invalid request size')
            if not 0<size<=8192:return error(413,'Bounded request required')
            body=await request.body()
            if len(body)!=size or len(body)>8192:return error(400,'Request length mismatch')
        try:response=await call_next(request)
        except Exception:return error(503,'Private view unavailable; source and journal were preserved')
        for k,v in headers.items():
            if k=='Content-Security-Policy' and response.headers.get(k):continue
            response.headers[k]=v
        return response

    def principal(request):return request.state.principal
    def role(email):return 'owner' if email in config.owner_emails else config.member_roles[email]
    def current(request,csrf=False):return sessions.current(request,principal(request),csrf)
    def session_view(value,identity):
        # Expiry metadata only; never send the Access token or its binding data.
        return {'csrf':value['csrf'],'expires_at':min(value['expires'],identity.expires_at),
            'identity_expires_at':identity.expires_at,'absolute_expires_at':value['created']+config.absolute_seconds,
            'email':value['email'],'role':role(value['email']),'mode':config.mode,
            'editorial_writes':config.editorial_writes,'external_execution':False}
    def session_response(token,value,identity):
        response=JSONResponse(session_view(value,identity))
        response.set_cookie(COOKIE,token,max_age=max(1,int(value['expires']-clock())),secure=True,httponly=True,samesite='strict',path='/')
        return response

    @app.exception_handler(PermissionError)
    async def denied(request,error_value):return error(403,'Current owner session and CSRF required')

    @app.get('/auth/session')
    def session(request:Request):
        v=current(request)
        return session_view(v,principal(request))

    @app.post('/auth/login')
    def login(request:Request):
        try:
            v=current(request)
            return session_view(v,principal(request))
        except PermissionError:
            token,v=sessions.issue(principal(request));return session_response(token,v,principal(request))

    @app.post('/auth/renew')
    def renew(request:Request):
        # Rotate atomically; two callers cannot consume the same predecessor.
        with sessions.lock:
            old=current(request,True);token,v=sessions.issue(principal(request),old)
            sessions.values.pop(sha256(request.cookies.get(COOKIE,'').encode()).hexdigest(),None)
        return session_response(token,v,principal(request))

    @app.post('/auth/logout')
    def logout(request:Request):
        current(request,True)
        with sessions.lock:
            if len(sessions.revoked)>=256:raise PermissionError('Logout capacity reached')
            sessions.values.pop(sha256(request.cookies.get(COOKIE,'').encode()).hexdigest(),None)
            sessions.revoked[request.state.token_hash]=principal(request).expires_at
        response=JSONResponse({'signed_out':True,'logout_url':config.origin+'/cdn-cgi/access/logout' if config.mode=='production' else None})
        response.delete_cookie(COOKIE,path='/',secure=True,httponly=True,samesite='strict')
        response.headers['Clear-Site-Data']='"cache", "storage"'
        return response

    @app.get('/api/overview')
    def overview(request:Request):
        current(request);q=projection.queue();o=q['operational']
        return {'at':q['at'],'registered_items':q['registered_items'],'package_count':q['package_count'],
            'decisions':q['top_decisions'],'completed':o['completed_internal'],'attention':o['top_attention'],
            'weekly':o['weekly'],'summary':q['completed_summary'],'mode':config.mode,'external_execution':False}

    @app.get('/api/sales')
    def sales(request:Request):
        current(request);o=projection.queue()['operational']
        return {k:o[k] for k in ('captured_at','cases','blocked','external_actions_completed')}

    @app.get('/api/marketing')
    def marketing(request:Request):
        current(request);q=projection.queue();a=read_projection(review.artifacts.parent/'latest-cycle.json').get('analysis',{})
        return {'weekly':q['operational']['weekly'],'gsc':a.get('gsc',{}),'evidence':a.get('evidence',[]),'limitations':a.get('limitations',[])}

    @app.get('/api/packages')
    def packages(request:Request,page:int=1,limit:int=10,q:str='',kind:str=''):
        current(request)
        if page<1 or not 1<=limit<=10 or len(q)>150:return error(422,'Bounded pagination required')
        rows=[p for p in projection.queue()['packages'] if q.casefold() in (p['title']+' '+p['key']).casefold()]
        if kind=='content':rows=[p for p in rows if p['key'].startswith('campaign:') or any('calendar' in i['logical_path'] for i in p['items'])]
        elif kind:return error(422,'Unknown package kind')
        return {'total':len(rows),'page':page,'limit':limit,'items':[package_card(p) for p in rows[(page-1)*limit:page*limit]]}

    @app.get('/api/packages/{identity}')
    def package(request:Request,identity:str):
        current(request);p=next((p for p in projection.queue()['packages'] if p['id']==identity),None)
        if not p:return error(404,'Unknown package')
        return {**package_card(p),'items':[item_card(i) for i in p['items']]}

    @app.get('/api/artifacts')
    def artifacts(request:Request,page:int=1,limit:int=12,q:str='',category:str=''):
        current(request)
        if page<1 or not 1<=limit<=24 or len(q)>150:return error(422,'Bounded pagination required')
        queue=projection.queue();rows=[i for p in queue['packages'] for i in p['items']]
        rows.sort(key=lambda i:i['queue']['rank'])
        rows=[i for i in rows if q.casefold() in (i['title']+' '+i['logical_path']).casefold() and (not category or i['category']==category)]
        return {'total':len(rows),'page':page,'limit':limit,'items':[item_card(i) for i in rows[(page-1)*limit:page*limit]]}

    @app.get('/api/artifacts/{identity}')
    def artifact(request:Request,identity:str):
        current(request)
        try:item,raw=review.item(identity)
        except (ValueError,OSError):return error(409,'Exact registered file unavailable or changed')
        text=raw.decode('utf-8',errors='replace') if item['path'].endswith(('.txt','.json','.md','.svg')) and len(raw)<=131072 else None
        return {**item_card(item),'text':text,'bytes':len(raw),'history':review.history(item),'external_execution':False}

    @app.get('/api/artifacts/{identity}/download')
    def download(request:Request,identity:str):
        current(request)
        try:item,raw=review.item(identity)
        except (ValueError,OSError):return error(409,'Exact registered file unavailable or changed')
        name=re.sub(r'[^A-Za-z0-9._-]','_',Path(item['logical_path']).name)[:120]
        response=Response(raw,media_type='application/octet-stream',headers={'Content-Disposition':'attachment; filename="'+name+'"'})
        response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
        return response

    @app.post('/api/review/decisions')
    async def decision(request:Request):
        v=current(request,True);person=principal(request)
        if role(person.email) not in ('owner','reviewer'):raise PermissionError('Editorial reviewer permission required')
        identity={'actor':person.actor,'expires_at':datetime.fromtimestamp(min(v['expires'],person.expires_at),timezone.utc)}
        try:
            body=await request.json();now=datetime.fromtimestamp(clock(),timezone.utc)
            if not isinstance(body,dict):raise ValueError('Object required')
            if config.editorial_writes:
                value=review.decision(body,identity,now,trusted_actor=person.actor);projection.clear();return value
            item=review.validate_decision(body,identity,now,trusted_actor=person.actor)
            return {'preview_only':True,'recorded':False,'choice':body['choice'],'artifact_sha256':item['sha256'],
                    'scope':item['execution_scope'],'execution_authorized':False}
        except (ValueError,TypeError,KeyError):return error(409,'Invalid, stale or conflicting exact editorial request')

    @app.get('/api/system')
    def system(request:Request):
        current(request);value=read_projection(readiness);latest=read_projection(review.artifacts.parent/'latest-cycle.json')
        return {'captured_at':value.get('captured_at'),'deployment_sha':value.get('deployment_sha'),
            'signals':value.get('signals',[]),'storage':latest.get('storage',{}),'mode':config.mode,
            'provider_calls':0,'admin_actions':False,'retention_approval':'DEFERRED','monitor_access':'REJECTED_AS_WRITTEN'}

    @app.get('/api/settings')
    def settings(request:Request):
        current(request)
        return {'role':role(principal(request).email),'team_access':bool(config.member_roles),'editorial_writes':config.editorial_writes,'external_execution':False,
            'generation_limits':{'daily_marketing_items':2,'rolling_seven_day_marketing_items':10,'active_pending_items':30,
                'disposable_gib':2,'minimum_free_gib':25},'preferences_editable':False,
            'note':'Existing approved analysis continues. Preference changes require their applicable exact approval.'}

    def existing_proposals():
        # Existing immutable evidence only. No setup, drafts or action creation.
        with sqlite3.connect(review.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            rows=db.execute("SELECT action_id,evidence_json,event_hash FROM action_evidence WHERE kind='business_send_review_proposal' ORDER BY event_id DESC LIMIT 100").fetchall()
        from review import digest
        seen=set();values=[]
        for identity,raw,proof in rows:
            if identity in seen:continue
            seen.add(identity);v=json.loads(raw)
            if digest(v['payload'])!=v['payload_sha256']:raise ValueError('Stored proposal payload identity changed')
            values.append({'id':identity,'event_hash':proof,'proposal':v})
        return values

    @app.get('/api/proposals')
    def proposals(request:Request):
        current(request);values=existing_proposals()
        return {'total':len(values),'execution_available':False,'items':[{'id':v['id'],'language':v['proposal'].get('language'),
            'subject':v['proposal']['payload'].get('subject'),'to':v['proposal']['payload'].get('to'),
            'payload_sha256':v['proposal']['payload_sha256'],'semantic_operation_key':v['proposal'].get('semantic_operation_key')} for v in values]}

    @app.get('/api/proposals/{identity}')
    def proposal(request:Request,identity:str):
        current(request);value=next((v for v in existing_proposals() if v['id']==identity),None)
        if not value:return error(404,'Unknown existing proposal')
        return {**value,'execution_available':False,'note':'Inspection only. Current conversation,contact,suppression and exact external authorization remain separate prerequisites.'}

    @app.get('/assets/{name}')
    def asset(name:str):
        allowed={'app.css':'text/css','app.js':'application/javascript','session.js':'application/javascript','icon.svg':'image/svg+xml','manifest.webmanifest':'application/manifest+json'}
        if name not in allowed:return error(404,'Unknown asset')
        return Response((ASSETS/name).read_bytes(),media_type=allowed[name])

    @app.get('/')
    def shell():return Response((ASSETS/'index.html').read_bytes(),media_type='text/html')

    class RejectWebSockets:
        def __init__(self,app):self.app=app
        async def __call__(self,scope,receive,send):
            if scope['type']=='websocket':
                await send({'type':'websocket.close','code':4403});return
            await self.app(scope,receive,send)
    app.add_middleware(RejectWebSockets)
    # No wildcard file serving, public health/debug routes, WS or admin transport.
    return app
