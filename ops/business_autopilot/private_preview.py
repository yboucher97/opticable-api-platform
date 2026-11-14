"""Expiring authenticated loopback fixture for review; never a public deployment.

Reuse the existing native preview sanitizer, then remove active customer flows.
The build stays outside the production website repository. No credentials in URLs.
"""
import ast
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib.util
import mimetypes
import os
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qs
from http.server import SimpleHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import secrets
import sys
import time


def native_guard(source):
    tree = ast.parse(Path(source).read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'preview_markup')
    namespace = {'re': re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['preview_markup']


def protect(root, native_source):
    guard = native_guard(native_source)
    count = 0
    for page in Path(root).rglob('*.html'):
        text = guard(page.read_text())
        # Only the reviewed local brief script and inert structured data survive.
        text = re.sub(r'<script\b([^>]*)>.*?</script\s*>', lambda m: m.group(0) if
            ('data-camera-brief' in m.group(1) or 'data-cabling-handover' in m.group(1) or 'application/ld+json' in m.group(1)) else '', text, flags=re.S|re.I)
        text = re.sub(r'<iframe\b.*?</iframe\s*>', '<p>Customer form disabled in private preview.</p>', text, flags=re.S|re.I)
        text = re.sub(r'<form\b.*?</form\s*>', '<p>Customer form disabled in private preview.</p>', text, flags=re.S|re.I)
        text = re.sub(r'(<a\b[^>]*?\s)href\s*=\s*([\"\'])(?:https?:|//|mailto:|tel:)[^\"\']*\2', r'\1href="#private-preview" data-external-disabled="true"', text, flags=re.I)
        # Resource hints must not establish outside connections.
        text = re.sub(r'<link\b[^>]*rel=[\"\'](?:preconnect|dns-prefetch)[\"\'][^>]*>', '', text, flags=re.I)
        if not re.search(r'<meta\b[^>]*name="robots"[^>]*noindex', text, re.I):
            raise ValueError('Native preview noindex missing')
        page.write_text(text); count += 1
    (Path(root)/'robots.txt').write_text('User-agent: *\nDisallow: /\n')
    for sitemap in Path(root).glob('*sitemap*.xml'):
        sitemap.unlink()
    return count


def serve(root, credentials, review=None, *, port=8876, stop_event=None, session_seconds=1200):
    root = Path(root).resolve(); saved = json.loads(Path(credentials).read_text())
    expected = base64.b64encode((saved['username']+':'+saved['password']).encode()).decode()
    expiry = datetime.fromisoformat(saved['expires_at']).timestamp()
    if saved['username'] != 'opticable-review':raise ValueError('Existing owner identity required')
    sessions = {}
    origins = {f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(root),**kwargs)
        def log_message(self,*args):pass
        def end_headers(self):
            self.send_header('X-Robots-Tag','noindex, nofollow, noarchive, nosnippet')
            self.send_header('Cache-Control','no-store, private')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; connect-src 'self'; form-action 'self'; frame-src 'none'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:")
            super().end_headers()
        def authorized(self):
            nonlocal expected,expiry
            # Root/owner credential revocation takes effect on the next request.
            # A refresh cannot extend the original primary credential lifetime.
            try:
                live=json.loads(Path(credentials).read_text())
                if live['username']!='opticable-review':raise ValueError('Owner identity changed')
                current=base64.b64encode((live['username']+':'+live['password']).encode()).decode()
                expiry=min(expiry,datetime.fromisoformat(live['expires_at']).timestamp())
                if current!=expected:sessions.clear();expected=current
            except (OSError,ValueError,KeyError):
                sessions.clear();self.send_error(403);return False
            if time.time() >= expiry:
                self.send_error(410,'Review fixture expired');return False
            supplied=self.headers.get('Authorization','')
            if not hmac.compare_digest(supplied,'Basic '+expected):
                self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="Opticable private draft"');self.end_headers();return False
            return True
        def json_response(self,status,value):
            raw=json.dumps(value,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def owner_session(self,renew=False):
            now=time.time()
            for key in list(sessions):
                if sessions[key]['expires']<=now:del sessions[key]
            cookie=SimpleCookie(self.headers.get('Cookie',''));token=cookie['ob_review'].value if 'ob_review' in cookie else ''
            if not renew and token in sessions:
                value=sessions[token];self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'csrf':value['csrf'],'expires_at':datetime.fromtimestamp(value['expires'],timezone.utc).isoformat()}).encode());return
            if renew:
                prior=sessions.get(token)
                if not prior or prior['expires']<=now or not hmac.compare_digest(self.headers.get('X-Review-CSRF',''),prior['csrf']):raise PermissionError('Expired session or invalid CSRF')
                del sessions[token]
            if len(sessions)>=64:raise PermissionError('Session budget exceeded')
            token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32);until=min(now+min(1200,max(1,session_seconds)),expiry)
            sessions[token]={'csrf':csrf,'expires':until}
            self.send_response(200);self.send_header('Set-Cookie',f'ob_review={token}; Path=/review/; HttpOnly; SameSite=Strict; Max-Age={max(0,int(until-now))}')
            self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'csrf':csrf,'expires_at':datetime.fromtimestamp(until,timezone.utc).isoformat()}).encode())
        def current_session(self):
            cookie=SimpleCookie(self.headers.get('Cookie',''));token=cookie['ob_review'].value if 'ob_review' in cookie else ''
            session=sessions.get(token)
            if not session or session['expires']<=time.time() or not hmac.compare_digest(session['csrf'],self.headers.get('X-Review-CSRF','')):raise PermissionError('Expired session or invalid CSRF')
            return session
        def do_GET(self):
            if not self.authorized():return
            if self.headers.get('Host') not in {f'127.0.0.1:{port}',f'localhost:{port}'}:self.send_error(403);return
            if review and self.path.startswith('/review'):
                path=urlsplit(self.path).path;params=parse_qs(urlsplit(self.path).query)
                try:
                    if path=='/review/session':return self.owner_session()
                    if path=='/review/website-package':
                        return self.json_response(200,json.loads((root/'review/review-package.json').read_text()))
                    if path.startswith('/review/artifact/'):
                        item,raw=review.item(path.rsplit('/',1)[-1]);self.send_response(200)
                        kind=mimetypes.guess_type(item['path'])[0] or 'text/plain'
                        self.send_header('Content-Type',kind+'; charset=utf-8' if kind.startswith('text/') else kind)
                    else:
                        identifier=path.rsplit('/',1)[-1] if path.startswith('/review/item/') else None
                        if path not in ('/review','/review/') and not identifier:self.send_error(404);return
                        raw=review.render(params.get('q',[''])[0][:150],params.get('category',[''])[0],identifier=identifier,urgency=params.get('urgency',[''])[0][:10],filter_status=params.get('status',[''])[0][:20]);self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
                    self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
                except (ValueError,OSError):return self.json_response(409,{'error':'Artifact unavailable or integrity changed'})

            path=self.path.split('?',1)[0]
            resolved=Path(self.translate_path(path))
            if not resolved.resolve().is_relative_to(root) or any(p.startswith('.') for p in resolved.relative_to(root).parts):
                self.send_error(404);return
            if 'sitemap' in path.lower():self.send_error(410,'Excluded from preview');return
            return super().do_GET()
        def do_HEAD(self):
            if not self.authorized():return
            if 'sitemap' in self.path.lower():self.send_error(410);return
            return super().do_HEAD()
        def do_POST(self):
            if not review:self.send_error(405,'Read-only review fixture');return
            if not self.authorized():return
            if self.headers.get('Origin') not in origins or self.headers.get('Host') not in {f'127.0.0.1:{port}',f'localhost:{port}'}:
                return self.json_response(403,{'error':'Same-origin owner request required'})
            try:
                if self.path=='/review/session/refresh':return self.owner_session(renew=True)
                if self.path!='/review/decision':self.send_error(405);return
                self.current_session()
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=8192 or self.headers.get('Content-Type')!='application/json':raise ValueError('Bounded JSON request required')
                body=json.loads(self.rfile.read(size));identity={'actor':'owner:opticable-review','expires_at':datetime.fromtimestamp(expiry,timezone.utc)}
                return self.json_response(200,review.decision(body,identity,datetime.now(timezone.utc)))
            except PermissionError:return self.json_response(403,{'error':'Current owner session and CSRF required'})
            except (ValueError,TypeError,KeyError):return self.json_response(409,{'error':'Invalid,stale or conflicting exact review request'})
        def do_PUT(self):self.send_error(405,'Unsupported method')
        do_DELETE=do_PATCH=do_PUT
        def list_directory(self,path):self.send_error(404);return None
    server=HTTPServer(('127.0.0.1',port),Handler);server.timeout=1
    while time.time()<expiry and not (stop_event and stop_event.is_set()):server.handle_request()
    server.server_close()


if __name__=='__main__':
    if sys.argv[1]=='protect':print(protect(sys.argv[2],sys.argv[3]))
    elif sys.argv[1]=='credentials':
        p=Path(sys.argv[2]);value={'username':'opticable-review','password':secrets.token_urlsafe(32),
            'expires_at':(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()}
        with p.open('x') as f:json.dump(value,f,indent=2)
        p.chmod(0o600);print('Private owner credential file created; 24-hour expiry')
    elif sys.argv[1]=='serve':serve(sys.argv[2],sys.argv[3])
    elif sys.argv[1]=='owner-review':
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from review import Review
        cfg=json.loads(Path('/etc/optibrain/platform-intelligence.json').read_text())
        if Path(sys.argv[4]).resolve()!=Path(cfg['database']).resolve() or not Path(sys.argv[4]).is_file():raise ValueError('Existing configured journal required')
        spec=importlib.util.spec_from_file_location('existing_platform_native','/usr/local/lib/optibrain-platform-intelligence.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.verify_runtime(Path(cfg['runtime']))
        # Existing journal and existing preview; no new database or listener port.
        serve(sys.argv[2],sys.argv[3],Review(sys.argv[4],sys.argv[5]))
    else:raise SystemExit('Fixed fixture commands only')
