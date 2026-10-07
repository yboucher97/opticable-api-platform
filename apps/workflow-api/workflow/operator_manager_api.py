"""Existing owner authentication, same-origin feedback, no execution routes."""
from datetime import datetime,timezone
from pathlib import Path
import json,re
from urllib.parse import parse_qs
from fastapi import Header,HTTPException,Request
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.concurrency import run_in_threadpool
from .automation.manager_store import ManagerStore
from .automation.manager_runtime import collect,DISPLAY
from .automation.manager_intelligence import build_manager,render_manager
from .automation import lifecycle_control as lc


def load_manager(path,now):
    store=ManagerStore(path);inputs=collect();saved={}
    try:saved=lc.trusted_json(DISPLAY,4194304)
    except (OSError,ValueError):pass
    view=build_manager(inputs,store,now,active_ids=saved.get('active_priority_ids',[]),crosswalk=saved.get('crosswalk',{}))
    for k in ('preparation','intake','forms','brief_id','refresh'):view[k]=saved.get(k)
    view['projection_at']=saved.get('at');view['state']='CURRENT' if saved else 'PARTIAL — WAITING MANAGER OBSERVER'
    # Display freshness is distinct from each provider's original observation.
    from .automation.manager_sources import stamp
    at=stamp(saved.get('at'))
    if at and (now-at).total_seconds()>900:view['state']='STALE — MANAGER REFRESH EXPECTED'
    view['priorities']=view['priorities'][:50];view['proposals']=view['proposals'][:50]
    return view


def install_manager_routes(app,*,verifier,db_path,origin,clock=None):
    now=clock or (lambda:datetime.now(timezone.utc));path=Path(db_path).with_name('phase12-autonomy.db')
    headers={'Cache-Control':'private, no-store, max-age=0','Pragma':'no-cache','Referrer-Policy':'no-referrer',
        'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
        'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"}
    def identity(token):
        try:return verifier.verify(token)
        except PermissionError:raise HTTPException(status_code=403,detail='Operator not authorized')
        except ValueError:raise HTTPException(status_code=401,detail='Verified human identity required')

    @app.get('/v1/operator/manager',tags=['operator'])
    async def manager(format:str='html',q:str='',domain:str='',status:str='',
        cf_access_jwt_assertion:str|None=Header(default=None,alias='Cf-Access-Jwt-Assertion')):
        identity(cf_access_jwt_assertion)
        if format not in {'html','json'} or max(map(len,(q,domain,status)))>100:raise HTTPException(status_code=422,detail='Bounded html/json query required')
        view=await run_in_threadpool(load_manager,path,now())
        if format=='json':
            if q or domain or status:view['proposals']=[p for p in view['proposals'] if (not q or q.casefold() in str(p).casefold()) and (not domain or p['domain']==domain) and (not status or status in {p['status'],p['readiness']})]
            return JSONResponse(view,headers=headers)
        return HTMLResponse(render_manager(view,query=q,domain=domain,status=status),headers=headers)

    @app.post('/v1/operator/manager/feedback',tags=['operator'])
    async def feedback(request:Request,cf_access_jwt_assertion:str|None=Header(default=None,alias='Cf-Access-Jwt-Assertion')):
        person=identity(cf_access_jwt_assertion)
        if request.headers.get('origin')!=origin or request.headers.get('sec-fetch-site') not in {None,'same-origin','none'}:
            raise HTTPException(status_code=403,detail='Same-origin owner intent required')
        mime=request.headers.get('content-type','').split(';')[0]
        if mime not in {'application/json','application/x-www-form-urlencoded'}:raise HTTPException(status_code=415,detail='Bounded owner feedback required')
        body=b''
        async for chunk in request.stream():
            body+=chunk
            if len(body)>8192:raise HTTPException(status_code=413,detail='Feedback exceeds bound')
        try:
            if mime=='application/json':fields=json.loads(body)
            else:
                values=parse_qs(body.decode('ascii'),strict_parsing=True,max_num_fields=7,keep_blank_values=True)
                if any(len(v)!=1 for v in values.values()):raise ValueError('Duplicate field')
                fields={k:v[0] for k,v in values.items()}
            required={'kind','target','version','choice'}
            if not isinstance(fields,dict) or not required<=set(fields) or set(fields)-required-{'reason','category','conditions'} or not all(isinstance(v,str) for v in fields.values()):raise ValueError('Exact feedback required')
            if any(not re.fullmatch('[0-9a-f]{64}',fields[k]) for k in ('target','version')):raise ValueError('Exact identifiers required')
            result=await run_in_threadpool(ManagerStore(path).feedback,fields['kind'],fields['target'],fields['version'],fields['choice'],person.actor,now(),
                reason=fields.get('reason',''),category=fields.get('category',''),conditions=fields.get('conditions',''))
        except (ValueError,UnicodeError):raise HTTPException(status_code=409,detail='Fresh exact local review required; no execution authority')
        if mime=='application/json':return JSONResponse(result,headers=headers)
        return HTMLResponse('<p>Owner intent saved. Provider execution still requires separate authority.</p><a href="/v1/operator/manager">Business Manager</a>',headers=headers)

    @app.post('/v1/operator/manager/correction',tags=['operator'])
    async def correction(request:Request,cf_access_jwt_assertion:str|None=Header(default=None,alias='Cf-Access-Jwt-Assertion')):
        person=identity(cf_access_jwt_assertion)
        if request.headers.get('origin')!=origin or request.headers.get('sec-fetch-site') not in {None,'same-origin','none'}:
            raise HTTPException(status_code=403,detail='Same-origin owner correction required')
        if request.headers.get('content-type','').split(';')[0]!='application/json':
            raise HTTPException(status_code=415,detail='JSON owner fact required')
        body=b''
        async for chunk in request.stream():
            body+=chunk
            if len(body)>4096:raise HTTPException(status_code=413,detail='Correction exceeds bound')
        try:
            fields=json.loads(body)
            required={'kind','target','version','event_type','reason_code'}
            if not isinstance(fields,dict) or set(fields)!=required or not all(isinstance(v,str) for v in fields.values()):raise ValueError('Exact assertion required')
            if any(not re.fullmatch('[0-9a-f]{64}',fields[k]) for k in ('target','version')):raise ValueError('Exact revision required')
            result=await run_in_threadpool(ManagerStore(path).correct_fact,fields['kind'],fields['target'],fields['version'],fields['event_type'],person.actor,now(),reason_code=fields['reason_code'])
        except (ValueError,TypeError,UnicodeError):raise HTTPException(status_code=409,detail='Fresh exact commercial correction required')
        return JSONResponse(result,headers=headers)
