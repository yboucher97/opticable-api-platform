"""Fixed Git operations on one approved clone and deterministic proposal paths."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from .acquisition_store import digest
from .website_preview_model import identifier, sha, proposal_branch, branch_name, relative_file, repository_name, TEST_CLASSES

PROTECTED_CHECKOUTS = (
    Path('/opt/opticable-api-platform'),
    Path('/home/optibrain/worktrees/opticable-website-preview'),
)

def file_hash(path):
    p=Path(path)
    if p.is_symlink() or p.stat().st_size>2097152:raise ValueError('Bounded regular file required')
    return hashlib.sha256(p.read_bytes()).hexdigest()


def no_symlinks(path):
    p=Path(path)
    if not p.is_absolute() or any(part=='..' for part in p.parts):raise ValueError('Absolute configured path without traversal required')
    for parent in (p,*p.parents):
        if parent.is_symlink():raise ValueError('Symlink path forbidden')
    return p


class LocalGitAdapter:
    def __init__(self, repository, clone_path, proposal_root, *, expected_remote, production_paths=(), max_worktrees=3):
        self.repository=repository_name(repository);self.clone=no_symlinks(clone_path)
        self.root=no_symlinks(proposal_root);self.expected_remote=expected_remote
        self.production_paths=PROTECTED_CHECKOUTS+tuple(no_symlinks(p).resolve() for p in production_paths)
        if not self.clone.is_dir() or type(max_worktrees) is not int or not 1<=max_worktrees<=3:raise ValueError('Missing repository / worktree bound')
        if any(self.clone.resolve()==p or p in self.clone.resolve().parents or self.root.resolve()==p or p in self.root.resolve().parents for p in self.production_paths) or self.root.resolve()==self.clone.resolve() or self.clone.resolve() in self.root.resolve().parents:
            raise ValueError('Production/clone path reuse forbidden')
        self.max_worktrees=max_worktrees;self.common=Path(self._git(self.clone,'rev-parse','--path-format=absolute','--git-common-dir').strip()).resolve()
        self._verify()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.root.stat().st_mode&0o077:raise ValueError('Private proposal root required')
        self.records=self.root/'.records';self.records.mkdir(mode=0o700,exist_ok=True)

    def _git(self, cwd, *args, codes=(0,)):
        # No command text, shell, hooks, signing, external diff or credential environment.
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','GIT_CONFIG_NOSYSTEM':'1',
             'GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0','GIT_AUTHOR_NAME':'OptiBrain Local Preview',
             'GIT_AUTHOR_EMAIL':'preview@localhost','GIT_COMMITTER_NAME':'OptiBrain Local Preview','GIT_COMMITTER_EMAIL':'preview@localhost'}
        with tempfile.TemporaryFile() as out:
            r=subprocess.run(['git','-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false','-c','core.fsmonitor=false',
                '-c','diff.external=','-C',str(cwd),*args],env=env,stdout=out,stderr=subprocess.STDOUT,timeout=30,shell=False)
            if out.tell()>1048576:raise ValueError('Git output exceeds bound')
            out.seek(0);value=out.read().decode('utf-8','replace')
        if r.returncode not in codes:raise ValueError('Bounded Git operation failed: '+value[:300])
        return value if codes==(0,) else (r.returncode,value)

    def _verify(self):
        no_symlinks(self.clone);no_symlinks(self.root)
        if Path(self._git(self.clone,'rev-parse','--show-toplevel').strip()).resolve()!=self.clone.resolve():raise ValueError('Wrong repository root')
        if self._git(self.clone,'remote','get-url','origin').strip()!=self.expected_remote:raise ValueError('Repository remote mismatch')
        current=Path(self._git(self.clone,'rev-parse','--path-format=absolute','--git-common-dir').strip()).resolve()
        if hasattr(self,'common') and current!=self.common:raise ValueError('Repository identity changed')
        code,filters=self._git(self.clone,'config','--get-regexp',r'filter\..*\.(clean|smudge|process)',codes=(0,1))
        if code==0 and filters.strip():raise ValueError('External Git filters forbidden')
        return current

    @contextmanager
    def _locked(self):
        self._verify()
        fd=os.open(self.common/'optibrain-preview.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX);self._verify();yield
        finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)

    def read_repo_state(self, default_branch='main'):
        if default_branch not in {'main','master'}:raise ValueError('Configured default branch required')
        self._verify();head=sha(self._git(self.clone,'rev-parse','HEAD').strip())
        base=sha(self._git(self.clone,'rev-parse','refs/heads/'+default_branch).strip())
        return {'repository':self.repository,'head_sha':head,'default_sha':base,'dirty':bool(self._git(self.clone,'status','--porcelain')),
            'worktrees':self._git(self.clone,'worktree','list','--porcelain'),'common_dir':str(self.common)}

    def fetch_state_from_adapter(self,provider,default_branch='main'):
        """Observe incremental fetch authority through the port; never clone daily."""
        before=self.read_repo_state(default_branch);read=provider.get_branch(self.repository,default_branch);read.validate()
        data=read.data
        if read.state=='COMPLETE' and (not isinstance(data,dict) or data.get('repository')!=self.repository or data.get('branch')!=default_branch):raise ValueError('Fetch identity mismatch')
        return {'read':read.metadata(),'last_sha':before['default_sha'],'observed_sha':sha(data['sha']) if read.state=='COMPLETE' else None,
            'change_detected':data['sha']!=before['default_sha'] if read.state=='COMPLETE' else None,'clone_required':False}

    def normalize_branch_name(self,proposal_id,slug):return branch_name(proposal_id,slug)

    def _record_path(self,pid):return self.records/(digest([self.repository,identifier(pid)])+'.json')

    def _target(self,pid):
        p=self.root/digest(self.repository)[:16]/identifier(pid);no_symlinks(p)
        if self.root.resolve() not in p.resolve().parents:raise ValueError('Worktree outside root')
        return p

    def _read_record(self,pid):
        p=self._record_path(pid);no_symlinks(p)
        if not p.exists():return None
        if p.stat().st_size>8192:raise ValueError('Worktree record exceeds bound')
        v=json.loads(p.read_text())
        if v['proposal_id']!=pid or v['repository']!=self.repository or v['path']!=str(self._target(pid)) or v['common_dir']!=str(self.common):raise ValueError('Worktree identity mismatch')
        proposal_branch(v['branch'],pid);sha(v['base_sha'])
        return v

    def _save_record(self,v):
        path=self._record_path(v['proposal_id']);no_symlinks(path)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as out:json.dump(v,out,sort_keys=True)

    def create_proposal_branch(self,package,branch,now):
        self._package(package);proposal_branch(branch,package['proposal_id'])
        with self._locked():
            if self.read_repo_state()['dirty']:raise ValueError('Dirty clone')
            base=sha(package['base_sha'])
            if self.read_repo_state()['default_sha']!=base:raise ValueError('Stale base')
            record=self._read_record(package['proposal_id'])
            code,_=self._git(self.clone,'show-ref','--verify','--quiet','refs/heads/'+branch,codes=(0,1))
            if code==0:
                if not record or record['branch']!=branch or record['base_sha']!=base:raise ValueError('Duplicate branch collision')
                return record
            if record:raise ValueError('Tracked branch missing')
            self._git(self.clone,'branch','--',branch,base)
            record={'proposal_id':package['proposal_id'],'repository':self.repository,'proposal_revision':package['proposal_revision'],
                'branch':branch,'base_sha':base,'path':str(self._target(package['proposal_id'])),'common_dir':str(self.common),
                'created_at':now.isoformat(),'state':'BRANCH_CREATED','semantic_hash':package['semantic_hash']}
            self._save_record(record);return record

    def _package(self,p):
        if p.get('repository')!=self.repository:raise ValueError('Wrong repository package')
        identifier(p['proposal_id']);sha(p['base_sha'])
        if type(p.get('proposal_revision')) is not int or p['proposal_revision']<1:raise ValueError('Invalid proposal revision')
        if not p.get('allowed_files') or len(p['allowed_files'])>30 or len(p.get('changes',[]))>30:raise ValueError('Bounded package required')
        for f in p['allowed_files']:relative_file(f)
        expected=digest([p['proposal_id'],p['repository'],p['base_sha'],p['allowed_files'],p['changes'],sorted(p['required_tests'])])
        if p.get('semantic_hash')!=expected:raise ValueError('Preparation hash mismatch')
        for c in p['changes']:
            if set(c)!={'path','before','after'} or c['path'] not in p['allowed_files'] or not isinstance(c['before'],str) or not c['before'] or not isinstance(c['after'],str):raise ValueError('Invalid structured change')
        if len(json.dumps(p).encode())>131072:raise ValueError('Package exceeds bound')

    def create_proposal_worktree(self,package,branch,now):
        self._package(package);proposal_branch(branch,package['proposal_id'])
        with self._locked():
            record=self._read_record(package['proposal_id'])
            if not record or record['branch']!=branch or record['base_sha']!=package['base_sha']:raise ValueError('Known branch/base required')
            target=self._target(package['proposal_id'])
            if target.exists():
                if record['state']!='WORKTREE_CREATED':raise ValueError('Worktree collision')
                self.read_worktree_state(package['proposal_id']);return record
            active=sum(r.is_file() and json.loads(r.read_text()).get('state')=='WORKTREE_CREATED' for r in self.records.glob('*.json'))
            if active>=self.max_worktrees:raise ValueError('Active worktree cap')
            target.parent.mkdir(mode=0o700,parents=True,exist_ok=True);no_symlinks(target.parent)
            self._git(self.clone,'worktree','add','--',str(target),branch)
            record['state']='WORKTREE_CREATED';self._save_record(record);return record

    def read_worktree_state(self,pid):
        self._verify();record=self._read_record(identifier(pid))
        if not record or record['state']!='WORKTREE_CREATED':raise ValueError('Known worktree required')
        path=self._target(pid)
        if not path.is_dir() or path.resolve() in self.production_paths:raise ValueError('Missing/production worktree')
        common=Path(self._git(path,'rev-parse','--path-format=absolute','--git-common-dir').strip()).resolve()
        if common!=self.common or self._git(path,'symbolic-ref','--short','HEAD').strip()!=record['branch']:raise ValueError('Cross-repo / proposal worktree collision')
        return {**record,'head_sha':sha(self._git(path,'rev-parse','HEAD').strip()),'dirty':bool(self._git(path,'status','--porcelain'))}

    def commit_prepared_change(self,package,*,protected_scripts=()):
        self._package(package);pid=package['proposal_id']
        with self._locked():
            record=self.read_worktree_state(pid);path=Path(record['path'])
            if record['base_sha']!=package['base_sha'] or record['proposal_revision']>package['proposal_revision']:raise ValueError('Revision/base mismatch')
            if record['dirty']:raise ValueError('Dirty proposal worktree')
            # Exact duplicate replay does no build/commit work.
            if record.get('prepared_semantic_hash')==package['semantic_hash'] and record.get('prepared_head')==record['head_sha']:return record['head_sha']
            code,_=self._git(path,'merge-base','--is-ancestor',package['base_sha'],record['head_sha'],codes=(0,1))
            if code!=0:raise ValueError('Base no longer an ancestor')
            pending={}
            for c in package['changes']:
                relative_file(c['path']);target=path/c['path'];no_symlinks(target)
                if c['path'] in protected_scripts or path.resolve() not in target.resolve().parents or not target.is_file() or target.stat().st_size>2097152:raise ValueError('Unsafe source file')
                current=pending.get(c['path'],target.read_text())
                if current.count(c['before'])!=1:raise ValueError('Exact change precondition mismatch')
                pending[c['path']]=current.replace(c['before'],c['after'],1)
            for f,content in pending.items():
                if len(content.encode())>2097152:raise ValueError('Changed file exceeds bound')
            for f,content in pending.items():(path/f).write_text(content)
            self._git(path,'add','--',*sorted(pending))
            staged=set(self._git(path,'diff','--cached','--name-only','--no-ext-diff').splitlines())
            if staged!=set(pending):raise ValueError('Unexpected staged scope')
            self._git(path,'commit','-m','Prepare '+pid+' revision '+str(package['proposal_revision']))
            head=sha(self._git(path,'rev-parse','HEAD').strip())
            record.update(proposal_revision=package['proposal_revision'],prepared_semantic_hash=package['semantic_hash'],prepared_head=head)
            self._save_record({k:v for k,v in record.items() if k not in {'dirty','head_sha'}});return head

    def detect_conflict(self,pid,current_sha):
        sha(current_sha);record=self.read_worktree_state(pid)
        with self._locked():
            code,_=self._git(self.clone,'merge-tree','--write-tree',current_sha,record['head_sha'],codes=(0,1))
        return code==1

    def compare_base(self,pid,current_sha):
        sha(current_sha);r=self.read_worktree_state(pid)
        if current_sha==r['base_sha']:return 'CURRENT'
        code,_=self._git(self.clone,'merge-base','--is-ancestor',r['head_sha'],current_sha,codes=(0,1))
        if code==0 and r['head_sha']!=r['base_sha']:return 'SUPERSEDED'
        return 'CONFLICTED' if self.detect_conflict(pid,current_sha) else 'NEEDS_REBASE'

    def mark_stale(self,pid,current_sha):return self.compare_base(pid,current_sha)

    def archive_eligibility(self,pid,owner_status):
        r=self.read_worktree_state(pid)
        return {'eligible':not r['dirty'] and owner_status in {'REJECTED','SUPERSEDED'},'state':owner_status,
                'path':r['path'],'deleted':False,'reason':'Controlled archival only; no deletion implemented'}


@dataclass(frozen=True)
class ApprovedScript:
    command_class: str
    script: str
    script_sha256: str
    timeout_seconds: int = 60

    def validate(self):
        relative_file(self.script)
        if self.command_class not in TEST_CLASSES or not __import__('re').fullmatch('[a-f0-9]{64}',self.script_sha256) or type(self.timeout_seconds) is not int or not 1<=self.timeout_seconds<=300:
            raise ValueError('Repository-approved script definition required')
        return self


class ApprovedBuildRunner:
    """Only pinned Python scripts from operator-reviewed policy, never payload argv."""
    def __init__(self,git,definitions):
        if not isinstance(definitions,tuple) or not definitions or len(definitions)>13 or any(not isinstance(d,ApprovedScript) for d in definitions):raise ValueError('Trusted script catalog required')
        self.git=git;self.definitions={d.validate().command_class:d for d in definitions}
        if len(self.definitions)!=len(definitions):raise ValueError('Duplicate command class')
    @property
    def protected_scripts(self):return tuple(d.script for d in self.definitions.values())
    def run(self,pid,command_class):
        d=self.definitions.get(command_class)
        if not d:raise ValueError('Unapproved command class')
        with self.git._locked():
            r=self.git.read_worktree_state(pid);path=Path(r['path']);script=path/d.script;no_symlinks(script)
            if r['dirty'] or file_hash(script)!=d.script_sha256:raise ValueError('Build script not approved / dirty worktree')
            artifacts=self.git.root/'artifacts'/pid/r['head_sha'];no_symlinks(artifacts);artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
            log=artifacts/(command_class.lower()+'.log');no_symlinks(log)
            fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
            started=time.monotonic();warnings=[]
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','OPTICABLE_SITE_ENV':'preview','OPTICABLE_ASSET_VER':r['head_sha'],
                'OPTICABLE_TRACKING':'disabled','OPTICABLE_NOINDEX':'1','OPTICABLE_CANONICAL_ORIGIN':'https://opticable.ca',
                'PYTHONDONTWRITEBYTECODE':'1','OPTIBRAIN_ARTIFACT_ROOT':str(artifacts)}
            with os.fdopen(fd,'wb') as out:
                try:
                    # Policy script must itself be preview-only. No shell or data-supplied args.
                    proc=subprocess.run([sys.executable,'-I',str(script)],cwd=path,env=env,stdout=out,stderr=subprocess.STDOUT,
                        timeout=d.timeout_seconds,shell=False);code=proc.returncode
                except subprocess.TimeoutExpired:code=124;warnings.append('TIMEOUT')
            if log.stat().st_size>1048576:warnings.append('LOG_EXCEEDS_REVIEW_BOUND')
            after=self.git.read_worktree_state(pid)
            if after['head_sha']!=r['head_sha'] or after['dirty']:code=125;warnings.append('SOURCE_CHANGED_DURING_CHECK')
            return {'command_class':command_class,'state':'PASS' if code==0 else 'FAIL','duration_seconds':round(time.monotonic()-started,3),
                'exit_code':code,'artifact_location':str(log),'warnings':warnings,'head_sha':r['head_sha']}
