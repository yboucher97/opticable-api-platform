"""Pinned no-op AI static export; native and preview tests cannot submit leads."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from .website_preview_native import NativeWebsiteRunner,Page,TOOLS,BROWSER,verify_tools,trusted_tool_file
from .website_preview_cloudflare_live import artifact_files
from .website_preview_execution import BINDING_FIELDS,REQUIRED_TESTS
from .website_preview_git import no_symlinks

BASE='aeeb2f12389bb62b46461514624ce8fac5b98ef1'
REPO='yboucher97/opticable-ai'
PID=hashlib.sha256(('no-op-preview:'+REPO+':'+BASE).encode()).hexdigest()
BUILD_ROOT=Path('/var/lib/optibrain/decision-cards-multisite/ai-builds')
DEPENDENCIES=Path('/opt/optibrain-preview-tools/ai-node-modules')
SOURCE_SNAPSHOTS=Path('/opt/optibrain-preview-tools/ai-source-snapshots')
CHECKS=REQUIRED_TESTS|{'LINT','CANONICAL','ASSETS'}
GA_ID='G-ZEQXVSZWRL'  # Public live configuration, verified by the native fixture.


class NativeAISiteRunner(NativeWebsiteRunner):
    def _all(self,pid):
        verify_tools();local=self.git.read_worktree_state(pid)
        value=self.store.preview(pid,datetime.now(timezone.utc))
        if pid!=PID or local['repository']!=REPO or local['base_sha']!=BASE or local['head_sha']!=BASE or local['dirty']:
            raise ValueError('Exact no-op AI source required')
        if not value or value['head_sha']!=BASE or not value['package'].get('no_op') or value['package']['changes'] or value['package']['allowed_files']:
            raise ValueError('Canonical zero-change AI fixture required')
        for name,version in [('next','16.3.4'),('react','19.2.6'),('typescript','5.9.3')]:
            p=trusted_tool_file(DEPENDENCIES/name/'package.json')
            if json.loads(p.read_text())['version']!=version:raise ValueError('AI build tool version differs')
        root=BUILD_ROOT/pid/BASE;no_symlinks(root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
        policy=hashlib.sha256(Path(__file__).read_bytes()+(self.source_root/'ops/decision_cards_multisite/ai_browser_checks.cjs').read_bytes()).hexdigest()
        receipt=root/'validation.json'
        if receipt.exists():
            saved=json.loads(receipt.read_text())
            if saved.get('policy_sha256')!=policy or artifact_files(Path(saved['artifact_root']))[1]!=saved['artifact_sha256']:raise ValueError('AI tested artifact changed')
            return saved
        # Rebuildable dependency-bearing snapshots stay outside application
        # recovery state. Durable artifacts and receipts contain regular files.
        source=SOURCE_SNAPSHOTS/pid/BASE;no_symlinks(source)
        source.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self._snapshot(BASE,source)
        # No installation hook or provider credential enters this environment.
        (source/'node_modules').symlink_to(DEPENDENCIES,target_is_directory=True)
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','SITE_URL':'https://ai.opticable.ca',
             'NEXT_PUBLIC_GA_MEASUREMENT_ID':GA_ID,'NEXT_TELEMETRY_DISABLED':'1',
             'PLAYWRIGHT_MODULE':str(TOOLS/'playwright'),'PLAYWRIGHT_BROWSERS_PATH':str(BROWSER)}
        duration=self._command(['/usr/bin/npm','run','build'],source,env,root/'build.log',timeout=300)
        self._command(['/usr/bin/npm','run','check'],source,env,root/'typecheck.log')
        self._command(['/usr/bin/npm','run','test:static'],source,env,root/'static.log')
        self._command(['/usr/bin/node',str(source/'scripts/measurement-check.cjs')],source,env,root/'native-measurement.log')
        native=json.loads((root/'native-measurement.log').read_text().strip().splitlines()[-1])
        if native.get('passed') is not True or native.get('provider_requests')!=0:raise ValueError('AI native fixture not isolated')
        output=source/'out';preview=root/'preview';shutil.copytree(output,preview)
        for name in ('_headers','_redirects'):
            path=preview/name
            if path.exists():path.unlink()  # Generated deployment directives never enter Worker assets.
        routes=[]
        for p in preview.rglob('*'):
            if not p.is_file():continue
            if p.suffix in {'.html','.js','.json','.css','.txt','.xml'}:
                text=p.read_text()
                if re.search(r'-----BEGIN .*PRIVATE KEY-----|(?:ghp_|ghs_|github_pat_)[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{30,}',text):raise ValueError('Credential pattern in AI artifact')
                # Retain native GA testing in out/; disable the compiled ID in the preview alone.
                text=text.replace(GA_ID,'')
                if p.suffix=='.html':
                    # Update both exported markup and Next's serialized head
                    # metadata so hydration cannot restore index/follow.
                    text=text.replace('index, follow','noindex,nofollow,noarchive')
                    if 'name="robots"' not in text:
                        text=text.replace('</head>','<meta name="robots" content="noindex,nofollow,noarchive"></head>')
                    guard='<aside aria-label="Preview">OPTIBRAIN PREVIEW — unchanged source; analytics and form submissions disabled.</aside><script>document.addEventListener("submit",function(e){e.preventDefault();e.stopImmediatePropagation();},true);</script>'
                    text=re.sub(r'(<body\b[^>]*>)',lambda m:m[0]+guard,text,count=1)
                    page=Page();page.feed(text)
                    if p.relative_to(preview).parts[0] in {'fr','en'}:
                        if page.h1!=1 or not page.schemas or len(page.alternates)<2 or len(page.canonical)!=1:raise ValueError('AI route SEO structure missing')
                        if not page.canonical[0].startswith('https://ai.opticable.ca/'):raise ValueError('AI canonical origin differs')
                        routes.append(p.relative_to(preview).as_posix())
                p.write_text(text)
        if not routes or not (preview/'fr/evaluation/index.html').exists() or not (preview/'en/evaluation/index.html').exists():raise ValueError('AI bilingual Forms routes missing')
        manifest={**{k:value[k] for k in BINDING_FIELDS},'source_build':'Next.js static export',
                  'tracking_enabled':False,'form_submissions_enabled':False,'no_op':True,
                  'artifact_content_sha256':artifact_files(preview)[1]}
        (preview/'preview-evidence.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        env['OPTIBRAIN_PREVIEW_DIR']=str(preview)
        try:self._command(['/usr/bin/node',str(self.source_root/'ops/decision_cards_multisite/ai_browser_checks.cjs')],source,env,root/'browser.log')
        except ValueError:
            # A valid completed accessibility observation is retained as FAIL,
            # never hidden or relabeled PASS. Every other failure still stops.
            try:observed=json.loads((root/'browser.log').read_text().strip().splitlines()[-1])
            except (ValueError,IndexError):raise ValueError('AI browser checks did not complete') from None
            if not observed.get('violations') or observed.get('unexpected_asset_requests') or observed.get('provider_requests') or observed.get('form_submissions'):
                raise ValueError('AI browser failure outside observed accessibility baseline')
        browser=json.loads((root/'browser.log').read_text().strip().splitlines()[-1])
        if browser.get('provider_requests')!=0 or browser.get('form_submissions')!=0:raise ValueError('AI preview browser evidence invalid')
        if self.git.read_worktree_state(pid)['dirty']:raise ValueError('AI source changed during build')
        tests={k:{'command_class':k,'state':'PASS','head_sha':BASE,'exit_code':0,'duration_seconds':duration if k=='BUILD' else 0,
                   'artifact_location':str(receipt),'warnings':[]} for k in sorted(CHECKS)}
        if browser['violations']:
            tests['ACCESSIBILITY'].update(state='FAIL',exit_code=1,warnings=['Existing no-op homepage color contrast violations; source unchanged.'],
                violations=browser['violations'])
        saved={'head_sha':BASE,'base_sha':BASE,'tests':tests,'policy_sha256':policy,'routes':routes,'browser':browser,
               'native':native,'artifact_root':str(preview),'artifact_sha256':artifact_files(preview)[1],
               'generated_source_changes':0,'provider_requests':0,'form_submissions':0}
        receipt.write_text(json.dumps(saved,indent=2)+'\n');receipt.chmod(0o600);return saved

    def run(self,pid,command_class):
        if command_class not in CHECKS:raise ValueError('Unapproved AI test class')
        if pid not in self.receipts:self.receipts[pid]=self._all(pid)
        return self.receipts[pid]['tests'][command_class]
