#!/usr/bin/python3
import hashlib,json,os,re,shutil,socket,sys,tarfile,uuid
from pathlib import Path
os.umask(0o077)
assert socket.gethostname()=='vps-214ba8cd'
sys.path.insert(0,'/home/optibrain/worktrees/optibrain-rebuild-migration/ops/rebuild')
from common import atomic_json,database_snapshot,file_hash,require,now
from recovery import manifest_from_archive,relative
archive=Path(sys.argv[1]);directory=Path(sys.argv[2]);require(str(directory).startswith('/dev/shm/'),'verification_scratch_must_be_ram')
manifest=manifest_from_archive(archive);generation=manifest['timestamp'];require(re.fullmatch(r'\d{8}T\d{6}Z',generation) is not None,'bad_generation');require(manifest['backup_format_version']=='1','bad_format')
expected={v['path']:v for v in manifest['files']};require(len(expected)==len(manifest['files']),'duplicate_manifest_path');dbs={v['backup_path'] for v in manifest['sqlite_databases']};db_bytes=sum(expected[n]['size'] for n in dbs)
reference=archive.parent/('generation-'+generation);use_reference=reference.is_dir() and not reference.is_symlink()
require(use_reference or db_bytes<=384*1024**2,'snapshot_scratch_exceeds_bound')
for name in expected:relative(name)
mem=int(next(v.split()[1] for v in Path('/proc/meminfo').read_text().splitlines() if v.startswith('MemAvailable:')))*1024;require(mem-(0 if use_reference else db_bytes)>=1536*1024**2,'ram_headroom_insufficient')
directory.mkdir(mode=0o700,parents=True,exist_ok=True);require(shutil.disk_usage(directory).free>=(0 if use_reference else db_bytes)+16*1024**2,'tmpfs_headroom_insufficient');scratch=directory/(generation+'-'+uuid.uuid4().hex);scratch.mkdir(mode=0o700)
seen=set();verified_files=set();prefix='generation-'+generation+'/'
with tarfile.open(archive,'r|gz') as tar:
 for member in tar:
  relative(member.name);require(member.name not in seen,'duplicate_tar_member');seen.add(member.name);require(member.isdir() or member.isfile(),'links_and_special_files_refused')
  if member.isdir():continue
  require(member.name.startswith(prefix),'wrong_generation_prefix');name=member.name[len(prefix):]
  if name=='manifest.json':continue
  require(name in expected,'unmanifested_archive_file');row=expected[name];require(member.size==row['size'],'file_size_mismatch');h=hashlib.sha256();out=None
  if name in dbs and not use_reference:
   dest=scratch/name;dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True);out=dest.open('xb')
  try:
   stream=tar.extractfile(member)
   for block in iter(lambda:stream.read(1024**2),b''):
    h.update(block)
    if out:out.write(block)
  finally:
   if out:out.close()
  require(h.hexdigest()==row['sha256'],'file_checksum_mismatch');verified_files.add(name)
require(verified_files==set(expected),'missing_archive_files')
if use_reference:
 for name in dbs:
  f=reference/name;require(f.is_file() and not f.is_symlink() and file_hash(f)==expected[name]['sha256'],'staging_database_reference_mismatch')
snapshots={n:database_snapshot((reference if use_reference else scratch)/n) for n in sorted(dbs)}
r={'at':now(),'status':'PASS','generation':generation,'archive_sha256':file_hash(archive),'files_verified':len(expected),'database_snapshots_verified':len(snapshots),'audit_chains_verified':sum(s['audit_chains_verified'] for s in snapshots.values()),'scratch_bytes':0 if use_reference else db_bytes,'verified_database_reference':str(reference) if use_reference else None,'verification':'all streamed file hashes plus all database integrity, foreign keys and audit chains','scratch_retained':str(scratch),'root_disk_archive_writes':False}
atomic_json(scratch/'stream-verification.json',r);print(json.dumps(r),flush=True)
