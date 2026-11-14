"""Read-only allocated-block accounting; no cleanup or permission operations.

One global inode set,canonical mount paths,directory blocks,and deleted-open
files distinguish actual unique allocation from overlapping directory views.
"""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import stat
import time

LIVE=Path('/var/lib/optibrain-data/generations/20261111T201316Z')
DEV=Path('/home/ubuntu/optibrain-development')


def unescape(value):
    import re
    return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),value)


def mount_aliases(raw):
    rows=[line.split(' - ',1)[0].split() for line in raw.splitlines()]
    root=next(r for r in rows if unescape(r[4])=='/')
    return {unescape(r[4]):unescape(r[3]) for r in rows if r[2]==root[2] and r[4]!='/' and r[3]!='/'}


def category(path):
    s=str(path)
    if s.startswith('/recovery/'):return 'held_recovery'
    if s.startswith('/var/backups/optibrain/'):return 'local_backups_and_staging'
    if s.startswith(str(LIVE)+'/'):
        if '/optibrain/phase2a/' in s:return 'encrypted_spool'
        if '/business-autopilot/website-preview/' in s:return 'generated_previews'
        if '/business-autopilot/artifacts/' in s:return 'registered_artifacts'
        return 'live_generation_state_source_audit'
    if s.startswith('/var/lib/optibrain-data/generations/'):return 'held_previous_generation'
    if s.startswith(str(DEV)+'/'):
        if any(x in Path(s).parts for x in ('__pycache__','.pytest_cache','node_modules')):return 'development_test_dependency_cache'
        if 'business-browser-cache' in s:return 'browser_tool_cache'
        return 'development_source_and_evidence'
    if s.startswith('/home/ubuntu/.codex/'):return 'codex_tools_and_history'
    if s.startswith('/var/log/'):return 'logs'
    if s.startswith('/var/cache/'):return 'system_cache'
    if s.startswith(('/tmp/','/var/tmp/')):return 'temporary'
    return 'other_system'


def identity(path):
    p=Path(path);s=p.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or p.is_symlink():raise ValueError('Single-link regular file required')
    h=sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
        end=os.fstat(f.fileno())
    if (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)!=(end.st_dev,end.st_ino,end.st_size,end.st_mtime_ns,end.st_ctime_ns):raise ValueError('Changed file identity')
    return {'path':str(p),'dev':s.st_dev,'ino':s.st_ino,'uid':s.st_uid,'bytes':s.st_size,
        'allocated_bytes':s.st_blocks*512,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'sha256':h.hexdigest()}


def cache_candidate(path,active_roots=(),now=None,expected_uid=1000):
    """Only disposable compiled Python cache with exact retained source proof.

    Outside the deployed retention allowlist; classification is never permission.
    """
    now=time.time() if now is None else now;p=Path(path)
    if not p.is_relative_to(DEV) or p.parent.name!='__pycache__' or p.suffix!='.pyc':return None
    if any(p.is_relative_to(Path(r)) for r in active_roots):return None
    # Never classify Git objects,dependency repositories or incident/test results.
    if any(x in p.parts for x in ('.git','node_modules','evidence','recovery')):return None
    try:
        s=p.lstat()
        if s.st_uid!=expected_uid or s.st_nlink!=1 or s.st_mode&0o022 or not stat.S_ISREG(s.st_mode):return None
        source=Path(importlib.util.source_from_cache(str(p)))
        if source.is_symlink() or not source.is_file() or source.stat().st_uid!=expected_uid:return None
        with p.open('rb') as stream:header=stream.read(16)
        if len(header)!=16 or header[:4]!=importlib.util.MAGIC_NUMBER:return None
        flags=int.from_bytes(header[4:8],'little');source_stat=source.stat()
        if flags==0:
            if int.from_bytes(header[8:12],'little')!=int(source_stat.st_mtime)&0xffffffff or int.from_bytes(header[12:16],'little')!=source_stat.st_size&0xffffffff:return None
        elif flags in (1,3):
            if header[8:16]!=importlib.util.source_hash(source.read_bytes()):return None
        else:return None
        f=identity(p);proof=identity(source)
        return {**f,'category':'reproducible_python_bytecode','retained_source':proof,
            'age_days':(now-s.st_mtime)/86400,'eligible':now-s.st_mtime>=7*86400,
            'reason':'Source retained;7-day minimum;no active workspace;revalidate handles and evidence holds before any separate approval',
            'covered_by_current_policy':False,'cache_header_matches_retained_source':True,'action':'PROPOSE_ONLY'}
    except (OSError,ValueError):return None


def active_workspaces():
    result=set()
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            cwd=(p/'cwd').resolve(strict=True)
            if cwd.is_relative_to(DEV):result.add(str(DEV/cwd.relative_to(DEV).parts[0]))
            # Script arguments can bind active tests even when cwd is elsewhere.
            for arg in (p/'cmdline').read_bytes().split(b'\0'):
                try:
                    q=Path(os.fsdecode(arg))
                    if q.is_absolute() and q.is_relative_to(DEV) and q.relative_to(DEV).parts:result.add(str(DEV/q.relative_to(DEV).parts[0]))
                except ValueError:pass
        except (FileNotFoundError,ProcessLookupError):pass
    return sorted(result)


def scan(root=Path('/'),aliases=None,active_roots=()):
    root=Path(root);device=root.lstat().st_dev;seen=set();categories=defaultdict(Counter);alias_bytes=0;alias_count=0;cross=[];races=0;symlinks=0;cache=[];workspace=defaultdict(int)
    aliases=mount_aliases(Path('/proc/self/mountinfo').read_text()) if aliases is None else aliases
    stack=[root];first={}
    while stack:
        path=stack.pop()
        if str(path) in aliases:continue
        try:s=path.lstat()
        except FileNotFoundError:races+=1;continue
        if s.st_dev!=device:continue
        key=s.st_dev,s.st_ino
        if key in seen:
            alias_count+=1;alias_bytes+=s.st_blocks*512
            if len(cross)<100 and first[key]!=category(path):cross.append({'path':str(path),'category':category(path),'charged_to':first[key],'allocated_bytes':s.st_blocks*512})
            continue
        seen.add(key);kind=category(path);first[key]=kind;c=categories[kind]
        c['allocated_bytes']+=s.st_blocks*512;c['inodes']+=1
        if stat.S_ISDIR(s.st_mode):
            c['directory_bytes']+=s.st_blocks*512
            try:stack.extend(sorted(path.iterdir(),reverse=True))
            except FileNotFoundError:races+=1
        elif stat.S_ISLNK(s.st_mode):symlinks+=1
        elif stat.S_ISREG(s.st_mode):
            c['files']+=1;c['logical_bytes']+=s.st_size
            if path.is_relative_to(DEV) and path!=DEV:
                workspace[path.relative_to(DEV).parts[0]]+=s.st_blocks*512
                candidate=cache_candidate(path,active_roots)
                if candidate:cache.append(candidate)
    return {'categories':{k:dict(v) for k,v in categories.items()},'unique_allocated_bytes':sum(v['allocated_bytes'] for v in categories.values()),
        'unique_inodes':len(seen),'hardlink_aliases_excluded':alias_count,'hardlink_alias_allocated_bytes_not_added':alias_bytes,
        'cross_category_shared_examples':cross,'bind_aliases_excluded':aliases,'symlinks_not_followed':symlinks,'vanished_entries':races,
        'development_workspace_unique_bytes':dict(sorted(workspace.items(),key=lambda x:-x[1])),
        'reproducible_cache_files':cache,'eligible_cache_candidates':[c for c in cache if c['eligible']]}


def deleted_open(device):
    found={}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            for fd in (p/'fd').iterdir():
                try:
                    if not os.readlink(fd).endswith(' (deleted)'):continue
                    st=fd.stat()
                    if st.st_dev==device and stat.S_ISREG(st.st_mode):found[(st.st_dev,st.st_ino)]=st.st_blocks*512
                except (FileNotFoundError,ProcessLookupError):pass
        except (FileNotFoundError,ProcessLookupError):pass
    return {'unique_open_deleted_inodes':len(found),'allocated_bytes':sum(found.values())}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();start=os.statvfs('/');active=active_workspaces()
    data=scan(active_roots=active);end=os.statvfs('/');unlinked=deleted_open(Path('/').stat().st_dev)
    data.update(at=datetime.now(timezone.utc).isoformat(),host=os.uname().nodename,active_workspaces_excluded=active,
        df_used_before=(start.f_blocks-start.f_bfree)*start.f_frsize,df_used_after=(end.f_blocks-end.f_bfree)*end.f_frsize,
        available_bytes=end.f_bavail*end.f_frsize,open_deleted=unlinked,
        filesystem_metadata_and_live_scan_gap=(end.f_blocks-end.f_bfree)*end.f_frsize-data['unique_allocated_bytes']-unlinked['allocated_bytes'],
        note='Unique categories are additive once;directory aliases are excluded. df gap includes filesystem metadata and concurrent changes. Cache candidates are proposals outside the current deletion policy;no file is deleted.',files_deleted=0)
    fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps({k:data[k] for k in ('unique_allocated_bytes','df_used_after','available_bytes','hardlink_aliases_excluded','filesystem_metadata_and_live_scan_gap')}))
    print(json.dumps({'eligible_cache_files':len(data['eligible_cache_candidates']),'cache_candidates_allocated_bytes':sum(c['allocated_bytes'] for c in data['eligible_cache_candidates'])}))


if __name__=='__main__':main()
