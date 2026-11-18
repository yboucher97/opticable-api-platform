"""Synthetic keys/identities/journals only; no production JWTs or owner actions."""
from datetime import datetime,timedelta,timezone
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest

HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parents[1]/'apps/workflow-api'))
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import jwt
from workflow.automation.acquisition_store import AcquisitionStore
from workflow.automation.action_evidence import ActionEvidence
from review import Review
from review import digest
from command_center import Config,COOKIE,create_app

KEY=rsa.generate_private_key(public_exponent=65537,key_size=2048)
ISSUER='https://unit-test.cloudflareaccess.com'
AUDIENCE='unit-test-command-center-audience'
EMAIL='owner@example.test'


class CommandCenterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.assets=self.root/'artifacts';self.assets.mkdir();self.db=self.root/'existing.db';store=AcquisitionStore(self.db)
        with ActionEvidence(self.db).connect() as db:ActionEvidence.setup(db)
        self.now=time.time();when=datetime.fromtimestamp(self.now,timezone.utc)
        for i in range(91):
            text=f'Synthetic private draft {i} <script>untrusted</script>';h=sha256(text.encode()).hexdigest();(self.assets/(h+'.txt')).write_text(text)
            store.record('CONTENT_ASSET',{'path':h+'.txt','logical_path':f'business-work/response-draft/test-{i%16}/en/draft/{i}.txt','sha256':h,
                'source_evidence':[{'observed_at':when.isoformat()}],'scope':'live','status':'DRAFT_ONLY'},source='platform:business_autopilot',native_id=h,url='https://example.test/',now=when)
        self.review=Review(self.db,self.assets)
        self.config=Config('https://localhost:8877',ISSUER,AUDIENCE,(EMAIL,))
        self.app=create_app(self.review,self.config,key_resolver=lambda token:KEY.public_key(),clock=lambda:self.now,readiness=self.root/'absent')
        self.client=TestClient(self.app,base_url=self.config.origin);self.addCleanup(self.client.close)
        self.token=self.make_token();self.client.headers['Cf-Access-Jwt-Assertion']=self.token

    def make_token(self,**fields):
        now=int(time.time());claims={'iss':ISSUER,'aud':[AUDIENCE],'sub':'synthetic-unit-owner','email':EMAIL,'type':'app','iat':now-1,'nbf':now-1,'exp':now+3600,**fields}
        return jwt.encode(claims,KEY,algorithm='RS256',headers={'kid':'synthetic-key'})

    def post(self,path,data=None,csrf=None,**headers):
        h={'Origin':self.config.origin,**({'X-Optibrain-CSRF':csrf} if csrf else {}),**headers}
        return self.client.post(path,json=data if data is not None else {},headers=h)

    def login(self):
        r=self.post('/auth/login');self.assertEqual(r.status_code,200,r.text);return r.json()['csrf']

    def test_all_routes_assets_json_errors_and_alternate_paths_need_identity(self):
        self.client.headers.pop('Cf-Access-Jwt-Assertion')
        for path in ['/','/assets/app.js','/assets/session.js','/assets/app.css','/assets/icon.svg','/assets/manifest.webmanifest','/api/overview','/api/artifacts','/api/system','/api/settings','/docs','/debug','/does-not-exist']:
            r=self.client.get(path);self.assertEqual(r.status_code,401,path);self.assertIn('no-store',r.headers['cache-control']);self.assertIn('noindex',r.headers['x-robots-tag'])

    def test_wrong_audience_issuer_signature_alg_expiry_and_service_id_denied(self):
        for fields in [{'aud':['wrong']},{'iss':'https://other.cloudflareaccess.com'},{'exp':int(time.time())-120},{'sub':'','email':None},{'type':'org'},{'email':'team@example.test'}]:
            self.client.headers['Cf-Access-Jwt-Assertion']=self.make_token(**fields)
            self.assertIn(self.client.get('/').status_code,(401,403),fields)
        token=self.make_token();self.client.headers['Cf-Access-Jwt-Assertion']=token[:-12]+'invalid-sign';self.assertEqual(self.client.get('/').status_code,401)
        self.client.headers['Cf-Access-Jwt-Assertion']=jwt.encode({'sub':'synthetic-unit-owner','email':EMAIL},'fake-key',algorithm='HS256',headers={'kid':'synthetic-key'});self.assertEqual(self.client.get('/').status_code,401)

    def test_identity_headers_and_shared_api_key_never_authenticate(self):
        self.client.headers.pop('Cf-Access-Jwt-Assertion')
        r=self.client.get('/',headers={'Cf-Access-Authenticated-User-Email':EMAIL,'X-Owner':EMAIL,'X-API-Key':'not-human','X-Forwarded-For':'127.0.0.1'})
        self.assertEqual(r.status_code,401)

    def test_host_https_origin_and_forwarded_headers_are_not_authority(self):
        self.assertEqual(self.client.get('/',headers={'Host':'evil.test','X-Forwarded-Host':'localhost:8877'}).status_code,403)
        self.assertEqual(self.client.get('http://localhost:8877/',headers={'X-Forwarded-Proto':'https'}).status_code,403)
        self.assertEqual(self.client.get('/',headers={'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.client.get('/',headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)
        self.assertEqual(self.client.get('/',headers={'X-Forwarded-Host':'evil.test','Forwarded':'host=evil.test'}).status_code,200)

    def test_api_requires_session_even_with_a_valid_jwt(self):
        self.assertEqual(self.client.get('/api/overview').status_code,403);self.login();self.assertEqual(self.client.get('/api/overview').status_code,200)

    def test_only_signed_owner_can_return_through_cross_site_document_navigation(self):
        headers={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
        r=self.client.get('/',headers=headers);self.assertEqual(r.status_code,200)
        self.assertIn('Sec-Fetch-Site',r.headers['vary']);self.assertIn('no-store',r.headers['cache-control'])
        self.assertIn("frame-ancestors 'none'",r.headers['content-security-policy'])
        self.client.headers.pop('Cf-Access-Jwt-Assertion');self.assertEqual(self.client.get('/',headers=headers).status_code,401)
        for fields in [{'email':'other@example.test'},{'aud':['other']},{'iss':'https://other.test'},
                       {'exp':int(time.time())-120},{'type':'org'}]:
            self.client.headers['Cf-Access-Jwt-Assertion']=self.make_token(**fields)
            self.assertIn(self.client.get('/',headers=headers).status_code,(401,403))
        self.client.headers['Cf-Access-Jwt-Assertion']=self.token[:-10]+'forged'
        self.assertEqual(self.client.get('/',headers=headers).status_code,401)

    def test_cross_site_exception_does_not_allow_api_mutations_or_embedding(self):
        self.login();headers={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
        for path in ['/api/overview','/auth/session','/assets/session.js','/auth/renew','/api/review/decisions']:
            self.assertEqual(self.client.get(path,headers=headers).status_code,403,path)
            self.assertEqual(self.post(path,{},**headers).status_code,403,path)
        self.assertEqual(self.client.head('/',headers=headers).status_code,403)
        for mode,destination in [('cors','document'),('navigate','iframe'),('navigate','object'),('navigate','embed'),('navigate','empty')]:
            self.assertEqual(self.client.get('/',headers={**headers,'Sec-Fetch-Mode':mode,'Sec-Fetch-Dest':destination}).status_code,403)
        self.assertEqual(self.client.get('/',headers={**headers,'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.client.get('/',headers={'Sec-Fetch-Site':'same-origin','Sec-Fetch-Dest':'iframe'}).status_code,403)
        self.assertEqual(self.client.get('/',headers=[*headers.items(),('Sec-Fetch-Site','same-origin')]).status_code,400)

    def test_cross_site_return_does_not_grant_future_viewers_owner_entry(self):
        config=replace(self.config,member_roles={'viewer@example.test':'viewer'})
        app=create_app(self.review,config,key_resolver=lambda token:KEY.public_key())
        with TestClient(app,base_url=config.origin,headers={'Cf-Access-Jwt-Assertion':self.make_token(email='viewer@example.test')}) as client:
            self.assertEqual(client.get('/',headers={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}).status_code,403)

    def test_session_metadata_reports_access_and_absolute_ceiling_without_token(self):
        expiry=int(self.now)+90;self.client.headers['Cf-Access-Jwt-Assertion']=self.make_token(exp=expiry)
        first=self.post('/auth/login').json()
        self.assertEqual(first['expires_at'],expiry);self.assertEqual(first['identity_expires_at'],expiry)
        self.assertAlmostEqual(first['absolute_expires_at'],self.now+28800)
        self.assertNotIn(self.client.headers['Cf-Access-Jwt-Assertion'],json.dumps(first))
        renewed=self.post('/auth/renew',csrf=first['csrf']);self.assertEqual(renewed.status_code,200)
        self.assertEqual(renewed.json()['expires_at'],first['expires_at'])
        self.assertEqual(renewed.json()['absolute_expires_at'],first['absolute_expires_at'])

    def test_logout_then_new_access_identity_can_start_a_new_session(self):
        csrf=self.login();self.assertEqual(self.post('/auth/logout',csrf=csrf).status_code,200)
        self.assertEqual(self.post('/auth/login').status_code,401)
        self.client.headers['Cf-Access-Jwt-Assertion']=self.make_token(jti='new-synthetic-access-session')
        self.assertEqual(self.post('/auth/login').status_code,200)
        self.assertEqual(self.client.get('/api/overview').status_code,200)

    def test_concurrent_renewal_consumes_predecessor_exactly_once(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        csrf=self.login();cookie=self.client.cookies.get(COOKIE);barrier=threading.Barrier(2)
        def attempt():
            with TestClient(self.app,base_url=self.config.origin,headers={'Cf-Access-Jwt-Assertion':self.token}) as client:
                barrier.wait(timeout=5)
                return client.post('/auth/renew',json={},headers={'Origin':self.config.origin,
                    'Cookie':COOKIE+'='+cookie,'X-Optibrain-CSRF':csrf}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sorted(statuses),[200,403])
        self.assertEqual(self.client.get('/api/overview',headers={'Cookie':COOKIE+'='+cookie}).status_code,403)

    def test_secure_cookie_rotation_expiry_and_absolute_lifetime(self):
        r=self.post('/auth/login');cookie=r.headers['set-cookie'];csrf=r.json()['csrf'];original=self.client.cookies.get(COOKIE)
        for part in ['Secure','HttpOnly','SameSite=strict','Path=/']:self.assertIn(part,cookie)
        self.assertNotIn('Domain=',cookie)
        self.now+=600;r=self.post('/auth/renew',csrf=csrf);self.assertEqual(r.status_code,200);self.assertNotEqual(original,self.client.cookies.get(COOKIE));self.assertNotEqual(csrf,r.json()['csrf'])
        self.now+=1201;self.assertEqual(self.client.get('/auth/session').status_code,403)
        with self.assertRaises(PermissionError):self.app.state.sessions.issue(type('P',(),{'subject':'s','email':EMAIL,'expires_at':self.now+50000})(),{'created':self.now-28801})

    def test_expired_primary_jwt_cannot_renew_or_read(self):
        csrf=self.login();self.client.headers['Cf-Access-Jwt-Assertion']=self.make_token(exp=int(self.now)-120)
        self.assertEqual(self.post('/auth/renew',csrf=csrf).status_code,401);self.assertEqual(self.client.get('/api/overview').status_code,401)

    def test_logout_revokes_cookie_and_current_bearer_with_no_offline_storage(self):
        csrf=self.login();r=self.post('/auth/logout',csrf=csrf);self.assertEqual(r.status_code,200);self.assertIsNone(self.client.cookies.get(COOKIE))
        self.assertIn('"storage"',r.headers['clear-site-data']);self.assertEqual(self.client.get('/api/overview').status_code,401);self.assertEqual(self.post('/auth/login').status_code,401)

    def test_logout_preserves_access_handoff_and_limits_cookie_expiration(self):
        config=Config('https://app.opticable.ca','https://opticable.cloudflareaccess.com',AUDIENCE,(EMAIL,),mode='production')
        app=create_app(self.review,config,key_resolver=lambda token:KEY.public_key())
        token=self.make_token(iss=config.team_domain)
        with TestClient(app,base_url=config.origin,headers={'Cf-Access-Jwt-Assertion':token}) as client:
            h={'Origin':config.origin};login=client.post('/auth/login',json={},headers=h)
            old=client.cookies.get(COOKIE);h['X-Optibrain-CSRF']=login.json()['csrf']
            response=client.post('/auth/logout',json={},headers=h)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['clear-site-data'],'"cache", "storage"')
            self.assertEqual(response.json(),{'signed_out':True,'logout_url':config.origin+'/cdn-cgi/access/logout'})
            cookies=response.headers.get_list('set-cookie');self.assertEqual(len(cookies),1)
            self.assertTrue(cookies[0].startswith(COOKIE+'='));self.assertIn('Max-Age=0',cookies[0])
            self.assertIn('no-store',response.headers['cache-control'])
            self.assertEqual(client.get('/api/overview',headers={'Cookie':COOKIE+'='+old}).status_code,401)
            client.headers['Cf-Access-Jwt-Assertion']=self.make_token(iss=config.team_domain,jti='new-after-logout')
            self.assertEqual(client.get('/api/overview',headers={'Cookie':COOKIE+'='+old}).status_code,403)
            self.assertEqual(client.post('/auth/login',json={},headers={'Origin':config.origin}).status_code,200)
            self.assertEqual(client.get('/api/overview').status_code,200)

    def test_logout_rejects_csrf_and_unauthorized_identity_without_revocation(self):
        csrf=self.login()
        for headers in [{},{'Origin':self.config.origin},{'Origin':self.config.origin,'X-Optibrain-CSRF':'wrong'},
                        {'Origin':'https://evil.test','X-Optibrain-CSRF':csrf}]:
            self.assertEqual(self.client.post('/auth/logout',json={},headers=headers).status_code,403)
            self.assertEqual(self.client.get('/api/overview').status_code,200)
        for token in [self.make_token(email='other@example.test'),self.token[:-10]+'invalid']:
            self.assertIn(self.client.post('/auth/logout',json={},headers={'Origin':self.config.origin,
                'X-Optibrain-CSRF':csrf,'Cf-Access-Jwt-Assertion':token}).status_code,(401,403))
        self.assertEqual(self.post('/auth/logout',csrf=csrf).status_code,200)

    def test_csrf_and_request_bounds(self):
        csrf=self.login()
        for headers in [{'Origin':'https://evil.test'},{'X-Optibrain-CSRF':'wrong'}]:self.assertEqual(self.post('/auth/renew',csrf=csrf,**headers).status_code,403)
        self.assertEqual(self.post('/auth/renew').status_code,403)
        self.assertEqual(self.client.post('/auth/renew',data='bad',headers={'Origin':self.config.origin,'Content-Type':'text/plain'}).status_code,415)
        self.assertEqual(self.post('/api/review/decisions',{'reason':'x'*9000},csrf).status_code,413)
        self.assertEqual(self.client.post('/auth/login',json={},headers=[('Origin',self.config.origin),('Host','localhost:8877'),('Host','evil.test')]).status_code,400)

    def test_registered_items_and_packages_paginate_without_loss_or_duplicates(self):
        self.login();q=self.client.get('/api/overview').json();self.assertEqual((q['registered_items'],q['package_count'],len(q['decisions'])),(91,16,5))
        first=self.client.get('/api/packages').json();second=self.client.get('/api/packages?page=2').json()
        self.assertEqual(len(first['items']),10);self.assertEqual(len(second['items']),6);self.assertEqual(len({p['id'] for p in first['items']+second['items']}),16)
        ids=[]
        for page in range(1,9):ids.extend(i['id'] for i in self.client.get('/api/artifacts?page='+str(page)).json()['items'])
        self.assertEqual(len(ids),91);self.assertEqual(len(set(ids)),91)
        self.assertEqual(self.client.get('/api/artifacts?limit=999').status_code,422)

    def test_staging_review_validates_exact_hash_without_writing_real_journal(self):
        csrf=self.login();item=self.client.get('/api/artifacts').json()['items'][0];before=self.db.read_bytes()
        body={'id':item['id'],'version':item['sha256'],'choice':'APPROVE','reason':'','request_id':'a'*32}
        r=self.post('/api/review/decisions',body,csrf);self.assertEqual(r.status_code,200,r.text);self.assertFalse(r.json()['recorded']);self.assertFalse(r.json()['execution_authorized']);self.assertEqual(before,self.db.read_bytes())
        for extra in [{'version':'0'*64},{'package_id':'fake'},{'choice':'SEND_CUSTOMER'},{'actor':'human:someone'}]:
            r=self.post('/api/review/decisions',{**body,**extra},csrf);self.assertEqual(r.status_code,409,r.text)

    def test_real_editorial_path_reuses_immutable_journal_and_never_external_authority(self):
        # Distinct synthetic audience/email/key; never a production owner JWT.
        config=Config('https://app.opticable.ca','https://opticable.cloudflareaccess.com',AUDIENCE,(EMAIL,),mode='production',editorial_writes=True)
        app=create_app(self.review,config,key_resolver=lambda token:KEY.public_key())
        token=self.make_token(iss=config.team_domain)
        with TestClient(app,base_url=config.origin,headers={'Cf-Access-Jwt-Assertion':token}) as c:
            h={'Origin':config.origin};r=c.post('/auth/login',json={},headers=h);h['X-Optibrain-CSRF']=r.json()['csrf']
            item=c.get('/api/artifacts').json()['items'][0];body={'id':item['id'],'version':item['sha256'],'choice':'REQUEST_REVISION','reason':'Specific fixture correction','request_id':'b'*32}
            first=c.post('/api/review/decisions',json=body,headers=h);self.assertEqual(first.status_code,200,first.text);self.assertEqual(first.json()['actor'],'human:synthetic-unit-owner');self.assertFalse(first.json()['execution_authorized'])
            again=c.post('/api/review/decisions',json=body,headers=h);self.assertEqual(first.json(),again.json())
            with sqlite3.connect(self.db) as db:self.assertEqual(db.execute("select count(*) from action_evidence where kind='business_review_decision'").fetchone()[0],1)

    def test_download_is_exact_attachment_and_content_cannot_execute(self):
        self.login();item=self.client.get('/api/artifacts').json()['items'][0];r=self.client.get('/api/artifacts/'+item['id']+'/download')
        self.assertEqual(sha256(r.content).hexdigest(),item['sha256']);self.assertIn('attachment',r.headers['content-disposition']);self.assertIn('no-store',r.headers['cache-control'])

    def test_all_navigation_data_endpoints_work_and_do_not_create_files(self):
        self.login();before=set(self.root.rglob('*'));db_before=self.db.read_bytes()
        for p in ['/api/overview','/api/sales','/api/marketing','/api/packages','/api/packages?kind=content','/api/artifacts','/api/system','/api/settings']:
            self.assertEqual(self.client.get(p).status_code,200,p)
        self.assertEqual(before,set(self.root.rglob('*')));self.assertEqual(db_before,self.db.read_bytes())

    def test_no_debug_admin_source_files_or_websocket_transport(self):
        self.login()
        for p in ['/docs','/openapi.json','/api/admin','/api/send','/.env','/assets/../command_center.py','/assets/%2e%2e%2fcommand_center.py']:
            self.assertIn(self.client.get(p).status_code,(404,405),p)
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect('/ws'):pass
        self.assertEqual(caught.exception.code,4403)

    def test_no_offline_cache_or_script_injection_sinks(self):
        js=(HERE/'command_center_assets/app.js').read_text()
        for forbidden in ['localStorage','sessionStorage','indexedDB','caches.open','serviceWorker.register','.innerHTML','eval(']:self.assertNotIn(forbidden,js)
        self.assertIn("script-src 'self'",self.client.get('/').headers['content-security-policy'])

    def test_existing_external_proposals_are_hash_verified_and_inspection_only(self):
        payload={'to':['customer@example.test'],'subject':'Existing synthetic proposal','body':'Prepared earlier','from':EMAIL}
        with ActionEvidence(self.db).connect() as db:ActionEvidence.append(db,'existing-proposal','business_send_review_proposal',{'payload':payload,'payload_sha256':digest(payload),'maximum_executions':1,'execution_authorized':False},datetime.now(timezone.utc))
        self.client.headers.pop('Cf-Access-Jwt-Assertion');self.assertEqual(self.client.get('/api/proposals').status_code,401)
        self.client.headers['Cf-Access-Jwt-Assertion']=self.token;csrf=self.login();before=self.db.read_bytes()
        listing=self.client.get('/api/proposals').json();self.assertEqual(listing['total'],1);self.assertNotIn('body',listing['items'][0])
        value=self.client.get('/api/proposals/existing-proposal').json();self.assertEqual(value['proposal']['payload'],payload);self.assertFalse(value['execution_available']);self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(self.post('/api/proposals/existing-proposal',{'execute':True},csrf).status_code,405)

    def test_future_role_model_has_no_current_grants_and_viewer_cannot_review(self):
        self.login();self.assertFalse(self.client.get('/api/settings').json()['team_access'])
        config=replace(self.config,member_roles={'viewer@example.test':'viewer'})
        app=create_app(self.review,config,key_resolver=lambda token:KEY.public_key())
        with TestClient(app,base_url=config.origin,headers={'Cf-Access-Jwt-Assertion':self.make_token(email='viewer@example.test')}) as client:
            h={'Origin':config.origin};r=client.post('/auth/login',json={},headers=h);self.assertEqual(r.json()['role'],'viewer');h['X-Optibrain-CSRF']=r.json()['csrf']
            self.assertEqual(client.get('/api/overview').status_code,200)
            self.assertEqual(client.post('/api/review/decisions',json={},headers={**h,'X-Role':'owner'}).status_code,403)


if __name__=='__main__':unittest.main()
