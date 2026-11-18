"""Loopback-only browser fixture: synthetic identity/data, no production credentials.

Run explicitly with the existing Playwright installation. No server or test HTTP
controls are added to the application factory or the production entrypoint.
"""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,os,secrets,socket,subprocess,sys,tempfile,threading,time

ROOT=Path(__file__).resolve().parents[3]
HERE=ROOT/'ops/business_autopilot'
sys.path[:0]=[str(HERE),str(ROOT/'apps/workflow-api')]
import jwt,uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from command_center import Config,create_app
from review import Review,digest
from workflow.automation.acquisition_store import AcquisitionStore
from workflow.automation.action_evidence import ActionEvidence


def main():
    if len(sys.argv)!=2:raise ValueError('Explicit evidence output directory required')
    evidence=Path(sys.argv[1]);evidence.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='optibrain-auth-fixture-') as folder:
        base=Path(folder);assets=base/'artifacts';assets.mkdir();db=base/'synthetic.db'
        store=AcquisitionStore(db);when=datetime.now(timezone.utc)
        with ActionEvidence(db).connect() as conn:ActionEvidence.setup(conn)
        for i in range(91):
            text=f'Synthetic EST-1145 fixture draft {i}\nNo customer content or authoritative record.\n'
            h=sha256(text.encode()).hexdigest();(assets/(h+'.txt')).write_text(text)
            store.record('CONTENT_ASSET',{'path':h+'.txt','logical_path':f'business-work/response-draft/test-{i%16}/en/draft/{i}.txt',
                'sha256':h,'source_evidence':[{'observed_at':when.isoformat()}],'scope':'live','status':'DRAFT_ONLY'},
                source='platform:business_autopilot',native_id=h,url='https://example.test/',now=when)
        for i in range(5):
            payload={'from':'owner@example.test','to':['recipient@example.invalid'],'subject':f'Synthetic proposal {i}',
                     'body':'Synthetic fixture content for inspection only. '*8}
            with ActionEvidence(db).connect() as conn:
                ActionEvidence.append(conn,'synthetic-proposal-'+str(i),'business_send_review_proposal',
                    {'payload':payload,'payload_sha256':digest(payload),'language':'en','maximum_executions':1,'execution_authorized':False},when)
        # Explicit synthetic measurements keep the pre-existing responsive
        # baseline fixture comparable to the original real-data browser suite.
        # No measurement is invented for the live registry or owner report.
        (base/'latest-cycle.json').write_text(json.dumps({'at':when.isoformat(),'analysis':{
            'ga4':{'sessions':12,'previous_sessions':11,'session_change_percent':9,'key_events':0},
            'gsc':{'clicks':2,'previous_clicks':1,'impressions':20,'previous_impressions':10},
            'freshness':'SYNTHETIC_FIXTURE'},'storage':{'optional_paused':True}}))
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(when-timedelta(minutes=1))
              .not_valid_after(when+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False)
              .sign(key,hashes.SHA256()))
        certificate=base/'tls.pem';private=base/'tls.key'
        certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));private.chmod(0o600)
        sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(16)
        origin='https://localhost:'+str(sock.getsockname()[1]);issuer='https://auth-fixture.cloudflareaccess.com';aud='auth-session-fixture-only'
        logout_only=os.environ.get('COMMAND_LOGOUT_ONLY')=='1'
        web_origin='https://app.opticable.ca' if logout_only else origin
        if logout_only:issuer='https://opticable.cloudflareaccess.com'
        state={'offset':0,'events':[]};state_lock=threading.RLock()
        def now():return time.time()+state['offset']
        def identity(ttl=3600):
            claims={'iss':issuer,'aud':[aud],'sub':'synthetic-browser-owner','email':'owner@example.test','type':'app',
                    'iat':int(time.time())-1,'nbf':int(time.time())-1,'exp':int(now())+ttl,'jti':secrets.token_hex(8)}
            return {'jwt':jwt.encode(claims,key,algorithm='RS256',headers={'kid':'fixture'}),
                    'identity_expires_at':claims['exp'],'now':now(),'url':web_origin}
        app=create_app(Review(db,assets),Config(web_origin,issuer,aud,('owner@example.test',),mode='production' if logout_only else 'staging'),
                       key_resolver=lambda token:key.public_key(),clock=now,readiness=base/'missing')
        @app.middleware('http')
        async def observe(request,call_next):
            response=await call_next(request)
            with state_lock:
                state['events'].append({'path':request.url.path,'method':request.method,'status':response.status_code,
                    'site':request.headers.get('sec-fetch-site'),'mode':request.headers.get('sec-fetch-mode'),
                    'destination':request.headers.get('sec-fetch-dest')})
            return response
        class Control(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                size=int(self.headers.get('Content-Length','0'));assert 0<size<=1024
                data=json.loads(self.rfile.read(size))
                with state_lock:
                    if self.path=='/advance':state['offset']+=int(data['seconds']);result={'now':now()}
                    elif self.path=='/identity':result=identity(int(data.get('ttl',3600)))
                    else:self.send_error(404);return
                body=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):
                with state_lock:body=json.dumps({'events':state['events']}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        control=ThreadingHTTPServer(('127.0.0.1',0),Control)
        thread=threading.Thread(target=control.serve_forever,daemon=True);thread.start()
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=sock.getsockname()[1],ssl_certfile=str(certificate),ssl_keyfile=str(private),
                          access_log=False,log_level='error',proxy_headers=False,server_header=False))
        worker=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);worker.start()
        until=time.monotonic()+10
        while not server.started:
            if time.monotonic()>until:raise RuntimeError('Fixture startup failed')
            time.sleep(.02)
        auth=base/'auth.json';auth.write_text(json.dumps(identity()));auth.chmod(0o600)
        env={**os.environ,'COMMAND_PREVIEW_AUTH':str(auth),'COMMAND_SCREENSHOTS':str(evidence),
             'COMMAND_FIXTURE_URL':origin,'COMMAND_FIXTURE_CONTROL':'http://127.0.0.1:'+str(control.server_port)}
        try:
            scripts=[('command_center_checks.cjs','existing-browser'),('command_center_auth_checks.cjs','auth-browser')]
            if os.environ.get('COMMAND_AUTH_ONLY')=='1':scripts=scripts[1:]
            if logout_only:scripts=[('command_center_logout_checks.cjs','logout-browser')]
            for script,name in scripts:
                result=subprocess.run(['node',str(HERE/script)],env=env,capture_output=True,text=True,timeout=180)
                (evidence/(name+'.log')).write_text(result.stdout+result.stderr)
                if result.returncode:raise RuntimeError(name+' failed; see sanitized local log')
                print(name+': PASS')
        finally:
            (evidence/'origin-request-metadata.json').write_text(json.dumps({'fixture_only':True,'events':state['events']},indent=2))
            server.should_exit=True;worker.join(5);control.shutdown();control.server_close();sock.close()


if __name__=='__main__':main()
