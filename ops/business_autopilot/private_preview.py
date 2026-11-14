"""Expiring authenticated loopback fixture for review; never a public deployment.

Reuse the existing native preview sanitizer, then remove active customer flows.
The build stays outside the production website repository. No credentials in URLs.
"""
import ast
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
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
            ('data-camera-brief' in m.group(1) or 'application/ld+json' in m.group(1)) else '', text, flags=re.S|re.I)
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


def serve(root, credentials):
    root = Path(root).resolve(); saved = json.loads(Path(credentials).read_text())
    expected = base64.b64encode((saved['username']+':'+saved['password']).encode()).decode()
    expiry = datetime.fromisoformat(saved['expires_at']).timestamp()
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(root),**kwargs)
        def log_message(self,*args):pass
        def end_headers(self):
            self.send_header('X-Robots-Tag','noindex, nofollow, noarchive, nosnippet')
            self.send_header('Cache-Control','no-store, private')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; connect-src 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:")
            super().end_headers()
        def authorized(self):
            if time.time() >= expiry:
                self.send_error(410,'Review fixture expired');return False
            supplied=self.headers.get('Authorization','')
            if not hmac.compare_digest(supplied,'Basic '+expected):
                self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="Opticable private draft"');self.end_headers();return False
            return True
        def do_GET(self):
            if not self.authorized():return
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
        def do_POST(self):self.send_error(405,'Read-only review fixture')
        do_PUT=do_DELETE=do_PATCH=do_POST
        def list_directory(self,path):self.send_error(404);return None
    server=HTTPServer(('127.0.0.1',8876),Handler);server.timeout=1
    while time.time()<expiry:server.handle_request()
    server.server_close()


if __name__=='__main__':
    if sys.argv[1]=='protect':print(protect(sys.argv[2],sys.argv[3]))
    elif sys.argv[1]=='credentials':
        p=Path(sys.argv[2]);value={'username':'opticable-review','password':secrets.token_urlsafe(32),
            'expires_at':(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()}
        with p.open('x') as f:json.dump(value,f,indent=2)
        p.chmod(0o600);print('Private owner credential file created; 24-hour expiry')
    elif sys.argv[1]=='serve':serve(sys.argv[2],sys.argv[3])
    else:raise SystemExit('Fixed fixture commands only')
