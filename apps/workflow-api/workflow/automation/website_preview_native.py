"""Pinned camera build policy. Source snapshots, never arbitrary proposal argv.

Both native CI browser scripts run against a local production-mode artifact
with every provider request intercepted. The hosted artifact uses preview mode.
The source commit contains only the historical French camera text revision.
"""
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import ast
import tarfile
import time
from urllib.parse import urlsplit

from .website_preview_cloudflare_live import artifact_files
from .website_preview_execution import BINDING_FIELDS, REQUIRED_TESTS
from .website_preview_github_live import PROPOSAL_ID, REPOSITORY
from .website_preview_git import no_symlinks
from .website_preview_model import sha

BASE = 'fc67ddc8c76b7527a620a93ca216b038f210b895'
CAMERA_FR = 'fr/services/systemes-cameras-securite/index.html'
CAMERA_EN = 'en/services/security-camera-systems/index.html'
BUILD_ROOT = Path('/var/lib/optibrain/first-hosted-camera-preview/builds')
TOOLS = Path('/opt/optibrain-preview-tools/node_modules')
BROWSER = Path('/root/.cache/ms-playwright')
WEBSITE_PYTHON = Path('/opt/optibrain-preview-tools/venv/bin/python')
GA_ID = 'G-ZEQXVSZWRL'  # Verified public production configuration; not a secret.

def trusted_tool_file(path):
    path=Path(path).resolve(strict=True)
    for parent in path.parents:
        info=parent.lstat()
        if info.st_uid!=0 or info.st_mode&0o022 or not stat.S_ISDIR(info.st_mode):raise PermissionError('Untrusted build tool parent')
    info=path.lstat()
    if info.st_uid!=0 or info.st_mode&0o022 or not stat.S_ISREG(info.st_mode):raise PermissionError('Untrusted build tool')
    return path

def verify_tools():
    for name,version in [('playwright','1.55.1'),('@axe-core/playwright','4.10.2')]:
        package=trusted_tool_file(TOOLS/name/'package.json')
        if json.loads(package.read_text()).get('version')!=version:raise ValueError('Build tool version differs')
    trusted_tool_file(WEBSITE_PYTHON)
    for package in (WEBSITE_PYTHON.parent.parent/'lib').glob('python*/site-packages/PIL/__init__.py'):
        trusted_tool_file(package)
        if "11.3.0" not in (package.parent/'_version.py').read_text():raise ValueError('Pillow version differs')


def content_proposal(git):
    """Extract the exact historical function, with its matching base precondition."""
    old = git._git(git.clone,'show','a0650b92007f197d68c252363362e2066f9db063^:sitegen.py')
    new = git._git(git.clone,'show','a0650b92007f197d68c252363362e2066f9db063:sitegen.py')
    def section(text):
        start=text.index('def service_conversion_section(')
        end=text.index('\ndef ',start+1)
        return text[start:end]
    return {'path':'sitegen.py','before':section(old),'after':section(new)}


class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[];self.canonical=[];self.alternates=[];self.schemas=[]
        self.h1=0;self.images=[];self.forms=[];self.robots=[];self.schema=False;self.schema_text=''
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='h1':self.h1+=1
        if tag=='link' and a.get('rel')=='canonical':self.canonical.append(a.get('href'))
        if tag=='link' and a.get('rel')=='alternate':self.alternates.append(a)
        if tag=='meta' and a.get('name')=='robots':self.robots.append(a.get('content',''))
        if tag=='img':self.images.append(a)
        if tag=='form' or tag=='iframe' and 'data-preview-form' in a:self.forms.append(a)
        if tag in {'a','link','script','img','source'}:
            if a.get('href') or a.get('src'):self.links.append(a.get('href') or a.get('src'))
        if tag=='script' and a.get('type')=='application/ld+json':self.schema=True;self.schema_text=''
    def handle_data(self,data):
        if self.schema:self.schema_text+=data
    def handle_endtag(self,tag):
        if tag=='script' and self.schema:
            self.schemas.append(json.loads(self.schema_text));self.schema=False


def preview_markup(text):
    # Keep original Forms reference as evidence, prevent external iframe loading.
    def iframe(match):
        tag=match.group(0)
        tag=re.sub(r'\bsrc="([^"]*)"',r'data-preview-original-src="\1"',tag)
        return tag[:-1]+' data-preview-form="present">'
    text=re.sub(r'<iframe\b[^>]*>',iframe,text)
    if '<body' in text:
        guard='<script>document.addEventListener("submit",function(e){e.preventDefault();e.stopImmediatePropagation();},true);</script>'
        text=text.replace('</body>',guard+'</body>')
    return text.replace('href="/fr/contact/?origin_service=security-camera-systems"',
        'data-preview-cta="quote" data-preview-forms-reference="contact" href="/fr/contact/?origin_service=security-camera-systems"')


class NativeWebsiteRunner:
    protected_scripts=()  # sitegen.py is the explicitly allowed historical copy change.
    def __init__(self,git,store,*,source_root):
        self.git=git;self.store=store;self.source_root=no_symlinks(source_root)
        self.receipts={}

    def _command(self,argv,cwd,env,log,timeout=300):
        started=time.monotonic()
        with log.open('wb') as out:
            result=subprocess.run(argv,cwd=cwd,env=env,stdout=out,stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,timeout=timeout,shell=False)
        os.chmod(log,0o600)
        if log.stat().st_size>2*1024*1024:raise ValueError('Validation log exceeds bound')
        if result.returncode:raise ValueError('Native validation failed: '+log.name)
        return round(time.monotonic()-started,3)

    def _snapshot(self,commit,destination):
        sha(commit);no_symlinks(destination)
        if destination.exists():raise ValueError('Existing unverified build snapshot')
        destination.mkdir(mode=0o700)
        with io.BytesIO() as raw:
            result=subprocess.run(['git','-c','safe.directory='+str(self.git.clone),'-c','core.hooksPath=/dev/null',
                '-C',str(self.git.clone),'archive','--format=tar',commit],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},timeout=60)
            if result.returncode or len(result.stdout)>512*1024*1024:raise ValueError('Source archive invalid/oversize')
            raw.write(result.stdout);raw.seek(0)
            with tarfile.open(fileobj=raw) as archive:
                members=archive.getmembers()
                if len(members)>10000:raise ValueError('Source file bound exceeded')
                for m in members:
                    path=PurePosixPath(m.name)
                    if path.is_absolute() or '..' in path.parts or not(m.isfile() or m.isdir()):raise ValueError('Unsafe source archive')
                    target=destination/m.name
                    if m.isdir():target.mkdir(parents=True,exist_ok=True,mode=0o700)
                    else:
                        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                        with archive.extractfile(m) as stream:target.write_bytes(stream.read())

    def _build(self,source,mode,log,asset_version):
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1',
            'OPTICABLE_SITE_URL':'https://opticable.ca','OPTICABLE_SITE_ENV':mode,
            'OPTICABLE_ENABLE_TRACKING':'1' if mode=='production' else '0',
            'OPTICABLE_FORCE_NOINDEX':'0' if mode=='production' else '1',
            'OPTICABLE_GA_MEASUREMENT_ID':GA_ID,'OPTICABLE_ASSET_VER':asset_version,
            'OPTICABLE_DEPLOY_DIR':'dist' if mode=='production' else 'preview-dist'}
        return self._command([str(WEBSITE_PYTHON),'-B',str(source/'sitegen.py')],source,env,log)

    def _all(self,pid):
        verify_tools()
        local=self.git.read_worktree_state(pid);value=self.store.preview(pid,__import__('datetime').datetime.now(__import__('datetime').timezone.utc))
        if pid!=PROPOSAL_ID or local['repository']!=REPOSITORY or local['base_sha']!=BASE or local['dirty']:
            raise ValueError('Pinned repository/current base/clean worktree required')
        if not value or value['head_sha']!=local['head_sha']:raise ValueError('Canonical prepared SHA required')
        if value['package']['changes']!=[content_proposal(self.git)]:raise ValueError('Only historical content revision allowed')
        head=local['head_sha'];root=BUILD_ROOT/pid/head;no_symlinks(root);root.mkdir(parents=True,mode=0o700,exist_ok=True)
        receipt_path=root/'validation.json'
        if receipt_path.exists():
            saved=json.loads(receipt_path.read_text())
            policy=hashlib.sha256(Path(__file__).read_bytes()+(self.source_root/'ops/first_hosted_camera_preview/browser_checks.cjs').read_bytes()).hexdigest()
            if saved.get('policy_sha256')!=policy or saved['head_sha']!=head or artifact_files(root/'source/preview-dist')[1]!=saved['artifact_sha256']:
                raise ValueError('Existing artifact changed')
            return saved
        self._snapshot(head,root/'source');self._snapshot(BASE,root/'base')
        for source in (root/'source').glob('*.py'):
            ast.parse(source.read_text(),filename=source.name)
        results={}; duration=self._build(root/'source','production',root/'build-production.log',BASE)
        self._build(root/'base','production',root/'build-base.log',BASE)
        self._build(root/'source','preview',root/'build-preview.log',head)
        prod=root/'source/dist';base=root/'base/dist';preview=root/'source/preview-dist'
        files={p.relative_to(prod).as_posix():p for p in prod.rglob('*') if p.is_file()}
        base_files={p.relative_to(base).as_posix():p for p in base.rglob('*') if p.is_file()}
        if set(files)!=set(base_files):raise ValueError('Unrelated route/asset inventory change')
        changed=[n for n,p in files.items() if p.read_bytes()!=base_files[n].read_bytes()]
        if CAMERA_FR not in changed or any(n not in {CAMERA_FR,'sitemap.xml'} for n in changed):
            raise ValueError('Generated change exceeds French camera scope: '+str(changed[:8]))
        fr=(prod/CAMERA_FR).read_text();en=(prod/CAMERA_EN).read_text();page=Page();page.feed(fr)
        for text in ['Caméras IP pour commerces et entrepôts','Demander une soumission','Combien de caméras faut-il?','Faut-il remplacer toutes les caméras?']:
            if text not in fr:raise ValueError('Historical French camera content missing')
        if 'Caméras IP pour commerces et entrepôts' in en:raise ValueError('French content leaked into English')
        if page.canonical!=['https://opticable.ca/'+CAMERA_FR.removesuffix('index.html')] or len(page.alternates)<2 or not page.schemas:
            raise ValueError('Camera SEO contract missing')
        for v in page.schemas:
            if not isinstance(v,(dict,list)):raise ValueError('Invalid JSON-LD')
        for output in preview.rglob('*.html'):
            text=output.read_text();p=Page();p.feed(text)
            if not p.robots or not any('noindex' in r for r in p.robots):raise ValueError('Preview page indexable')
            for ref in p.links:
                u=urlsplit(ref)
                if u.scheme not in ('','https') or u.netloc and u.netloc!='opticable.ca':continue
                path=u.path or '/'
                if path.startswith('/api/'):continue
                target=preview/path.lstrip('/')
                if path in {'/fr','/fr/'}:target=preview/'index.html'
                elif path.endswith('/'):target=target/'index.html'
                elif not target.suffix:target=target/'index.html'
                if not target.exists():raise ValueError('Broken generated link: '+path)
            output.write_text(preview_markup(text))
        for p in preview.rglob('*'):
            if p.is_file() and p.suffix in {'.html','.js','.json','.css','.txt','.xml'}:
                data=p.read_text()
                if re.search(r'-----BEGIN .*PRIVATE KEY-----|(?:ghp_|ghs_|github_pat_)[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{30,}',data):
                    raise ValueError('Secret pattern in artifact')
        binding={k:value[k] for k in BINDING_FIELDS}
        manifest={**binding,'artifact_content_sha256':artifact_files(preview)[1],
            'source_build':'sitegen.py','tracking_enabled':False,'form_submissions_enabled':False}
        (preview/'preview-evidence.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PLAYWRIGHT_MODULE':str(TOOLS/'playwright'),
            'PLAYWRIGHT_BROWSERS_PATH':str(BROWSER),'OPTIBRAIN_PREVIEW_DIR':str(preview),'OPTIBRAIN_PRODUCTION_DIR':str(prod)}
        for name in ['measurement-check.cjs','native-success-check.cjs']:
            try:self._command(['/usr/bin/node',str(root/'source'/name)],root/'source',env,root/(name+'.log'))
            except ValueError:
                # One known isolated callback-fixture navigation race; retain
                # the failed log. No arbitrary failure or provider write retry.
                if name!='native-success-check.cjs' or 'Execution context was destroyed' not in (root/(name+'.log')).read_text():raise
                self._command(['/usr/bin/node',str(root/'source'/name)],root/'source',env,root/(name+'.bounded-rerun.log'))
        self._command(['/usr/bin/node',str(self.source_root/'ops/first_hosted_camera_preview/browser_checks.cjs')],
            root/'source',env,root/'browser-checks.log')
        browser=json.loads((root/'browser-checks.log').read_text().strip().splitlines()[-1])
        if browser.get('passed') is not True or browser.get('provider_requests')!=0 or browser.get('form_submissions')!=0:
            raise ValueError('Isolated browser evidence invalid')
        if self.git.read_worktree_state(pid)['dirty'] or self.git.read_worktree_state(pid)['head_sha']!=head:
            raise ValueError('Source changed while testing')
        for k in sorted(REQUIRED_TESTS|{'LINT'}):
            results[k]={'command_class':k,'state':'PASS','head_sha':head,'exit_code':0,
                'artifact_location':str(root/'validation.json'),'warnings':[],'duration_seconds':duration if k=='BUILD' else 0}
        saved={'head_sha':head,'base_sha':BASE,'tests':results,'generated_diff':changed,'browser':browser,
            'policy_sha256':hashlib.sha256(Path(__file__).read_bytes()+(self.source_root/'ops/first_hosted_camera_preview/browser_checks.cjs').read_bytes()).hexdigest(),
            'artifact_root':str(preview),'artifact_sha256':artifact_files(preview)[1],
            'native_checks':['measurement-check.cjs','native-success-check.cjs'],'provider_requests':0,'form_submissions':0}
        receipt_path.write_text(json.dumps(saved,indent=2)+'\n');os.chmod(receipt_path,0o600)
        return saved

    def run(self,pid,command_class):
        if command_class not in REQUIRED_TESTS|{'LINT'}:raise ValueError('Unapproved test class')
        started=time.monotonic()
        if pid not in self.receipts:
            try:self.receipts[pid]=self._all(pid)
            except (ValueError,OSError,subprocess.TimeoutExpired) as error:
                local=self.git.read_worktree_state(pid)
                return {'command_class':command_class,'state':'FAIL','head_sha':local['head_sha'],'exit_code':1,
                    'warnings':[str(error)[:300]],'duration_seconds':round(time.monotonic()-started,3)}
        return self.receipts[pid]['tests'][command_class]
