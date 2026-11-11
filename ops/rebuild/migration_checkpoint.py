#!/usr/bin/env python3
"""Small encrypted, create-only off-host control checkpoint; reuses backup uploader.

No full business backup and no OLD disk staging. Captures the existing audit DB
using SQLite backup, verifies all canonical chains, and independently hashes a
full R2 GET. Only changes to canonical audit/profile create a new generation.
"""
import configparser
from datetime import datetime,timezone
import fcntl,hashlib,importlib.util,json,os,shlex,shutil,sqlite3,subprocess,sys,tarfile,tempfile
from pathlib import Path
from common import atomic_json,digest,file_hash,require

ROOT=Path('/recovery/migration-preparation/autonomous-20261101')
CONTROL=Path('/var/lib/optibrain-rebuild')

def copy_stage_evidence(evidence,destination):
    # Preserve identical stage basenames from separate approved windows.
    for source in [*evidence.glob('*.json'),*evidence.glob('source-control-*.tar.gz'),*evidence.glob('windows/*/*.json'),*evidence.glob('windows/*/source-control-*.tar.gz')]:
        if source.is_file() and not source.is_symlink() and source.stat().st_size<1024**2:
            out=destination/source.relative_to(evidence)
            out.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            shutil.copyfile(source,out)


def seal():
    require(os.geteuid()==0 and os.uname().nodename=='vps-f8e9b20e','replacement_root_only')
    with (CONTROL/'migration-checkpoint.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        profile=json.loads(Path('/etc/optibrain/migration/profile.json').read_text())
        with sqlite3.connect((CONTROL/'actions.db').as_uri()+'?mode=ro',uri=True) as source:
            source.execute('PRAGMA query_only=ON');source.execute('BEGIN')
            marker=source.execute('SELECT max(event_id) FROM action_evidence').fetchone()[0]
        identity=digest({'execution_id':profile['execution_id'],'profile_sha256':digest(profile),'canonical_event_id':marker})
        receipt_path=CONTROL/'migration-offhost.json'
        if receipt_path.exists():
            previous=json.loads(receipt_path.read_text())
            if previous.get('checkpoint_identity')==identity and previous.get('status')=='PASS':return previous
        directory=ROOT/'checkpoints';directory.mkdir(mode=0o700,exist_ok=True)
        require(shutil.disk_usage('/').free>2*1024**3,'control_checkpoint_capacity_low')
        with tempfile.TemporaryDirectory(prefix='control-seal-',dir='/run/optibrain-migration-watchdog') as tmp:
            p=Path(tmp);snapshot=p/'actions.db'
            with sqlite3.connect((CONTROL/'actions.db').as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(snapshot) as dest:source.backup(dest)
            from common import database_snapshot
            verified=database_snapshot(snapshot);require(verified['audit_chains_verified']>0,'control_audit_chains_missing')
            # Take the marker from the actual consistent snapshot, not the preliminary read.
            with sqlite3.connect(snapshot) as db:marker=db.execute('SELECT max(event_id) FROM action_evidence').fetchone()[0]
            identity=digest({'execution_id':profile['execution_id'],'profile_sha256':digest(profile),'canonical_event_id':marker})
            atomic_json(p/'snapshot-integrity.json',verified)
            for f in ['profile.json','owner-approvals.json','window-verification.json']:
                if Path('/etc/optibrain/migration/'+f).exists():shutil.copyfile('/etc/optibrain/migration/'+f,p/f)
            for f in ['window-verification.json','migration-health.json','migration-status.txt','state.json','backup-verified.json']:
                if (CONTROL/f).exists():shutil.copyfile(CONTROL/f,p/f)
            status=Path('/recovery/migration-preparation/autonomous-20261101/owner-status.txt')
            if status.exists():shutil.copyfile(status,p/'owner-status.txt')
            code=Path(__file__).resolve().parents[2]
            for f in [*list((code/'ops/rebuild').glob('*.py')),*list((code/'systemd').glob('*'))]:
                if f.is_file() and not f.is_symlink():
                    dest=p/'control-code'/f.relative_to(code);dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True);shutil.copyfile(f,dest)
            evidence=ROOT/'executor'
            if evidence.exists():
                dest=p/'stage-evidence';dest.mkdir(mode=0o700)
                copy_stage_evidence(evidence,dest)
            authorizations=ROOT/'executor/owner-authorizations'
            if authorizations.exists():
                out=p/'actual-owner-authorization';out.mkdir(mode=0o700)
                for f in authorizations.iterdir():
                    if f.is_file() and f.stat().st_size<=65536:shutil.copyfile(f,out/f.name)
            # Large immutable deployment runtimes are sealed once in the completion packet,
            # not copied into every heartbeat/stage checkpoint. Exact hashes stay in profile.
            archive=p/'control.tar.gz'
            with tarfile.open(archive,'w:gz') as t:
                for f in sorted(p.iterdir()):
                    if f!=archive:t.add(f,arcname=f.name,recursive=True)
            plaintext_hash=file_hash(archive)
            cipher=directory/(identity+'.tar.gz.age')
            creation=cipher.with_suffix(cipher.suffix+'.creation.json')
            if cipher.exists():
                require(creation.exists(),'interrupted_cipher_requires_reconciliation')
                prior=json.loads(creation.read_text());require(file_hash(cipher)==prior['ciphertext_sha256'],'interrupted_cipher_hash_mismatch')
                plaintext_hash=prior['plaintext_sha256']
            else:
                recipient=Path('/etc/optibrain/age-recipient').read_text().strip()
                subprocess.run(['age','-r',recipient,'-o',str(cipher),str(archive)],check=True,capture_output=True)
                atomic_json(creation,{'plaintext_sha256':plaintext_hash,'ciphertext_sha256':file_hash(cipher),'checkpoint_identity':identity})
            spec=importlib.util.spec_from_file_location('existing_uploader','/usr/local/lib/optibrain-backup/optibrain-phase2a-upload.py');u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
            import boto3
            from botocore.config import Config
            values={}
            for line in Path('/etc/optibrain/phase2a.conf').read_text().splitlines():
                if line.strip() and not line.lstrip().startswith('#'):
                    k,v=line.split('=',1);values[k.strip()]=shlex.split(v)[0]
            credentials=configparser.ConfigParser();credentials.read('/etc/optibrain/r2-uploader.env')
            c=boto3.client('s3',endpoint_url='https://'+values['OPTIBRAIN_PHASE2A_ACCOUNT_ID']+'.r2.cloudflarestorage.com',aws_access_key_id=credentials['default']['aws_access_key_id'],aws_secret_access_key=credentials['default']['aws_secret_access_key'],region_name='auto',config=Config(signature_version='s3v4',connect_timeout=10,read_timeout=45,retries={'mode':'standard','total_max_attempts':3}))
            c.meta.events.register('before-call.s3.PutObject',u.create_only_header)
            key='backups/'+datetime.now(timezone.utc).strftime('%Y/%m/%d')+'/migration-control-'+profile['execution_id']+'-'+identity+'.tar.gz.age'
            u.transfer(c,cipher,key,ROOT)
            head=c.head_object(Bucket=u.BUCKET,Key=key);read=c.get_object(Bucket=u.BUCKET,Key=key,IfMatch=head['ETag']);h=hashlib.sha256();size=0
            try:
                for b in read['Body'].iter_chunks(chunk_size=1024**2):h.update(b);size+=len(b)
            finally:read['Body'].close()
            require(h.hexdigest()==file_hash(cipher) and size==cipher.stat().st_size==head['ContentLength'],'control_offhost_full_readback_failed')
            receipt={'status':'PASS','at':datetime.now(timezone.utc).isoformat(),'checkpoint_identity':identity,
                'execution_id':profile['execution_id'],'canonical_event_id':marker,'audit_chains_verified':verified['audit_chains_verified'],
                'object_key':key,'plaintext_sha256':plaintext_hash,'ciphertext_sha256':h.hexdigest(),'ciphertext_bytes':size,
                'full_R2_readback':'PASS','current_business_source_backup':False,'existing_evidence_deleted':False}
            # Receipt contains no new canonical event: avoids an endless snapshot feedback loop.
            atomic_json(receipt_path,receipt);atomic_json(directory/(identity+'.receipt.json'),receipt)
            return receipt

if __name__=='__main__':
    try:print(json.dumps(seal()))
    except Exception as e:print(json.dumps({'status':'BLOCKED','error':type(e).__name__}));raise SystemExit(1)
