"""Fixed loopback HTTPS entrypoint. No provider administration or auto-rollout."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import ssl
import stat
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'apps/workflow-api'));sys.path.insert(0,str(Path(__file__).resolve().parent))


def protected(path):
    p=Path(path);st=p.lstat()
    if p.is_symlink() or not p.is_file() or st.st_uid!=0 or st.st_mode&0o022:
        raise PermissionError('Root-owned immutable application configuration required')
    return p


def verify_source(root,expected,*,require_root=True):
    root=Path(root);manifest=root/'manifest.json'
    if root.is_symlink() or (require_root and root.stat().st_uid!=0) or root.stat().st_mode&0o022:
        raise PermissionError('Immutable runtime root required')
    st=manifest.lstat()
    if manifest.is_symlink() or not stat.S_ISREG(st.st_mode) or st.st_mode&0o022 or (require_root and st.st_uid!=0):
        raise PermissionError('Immutable regular manifest required')
    if sha256(manifest.read_bytes()).hexdigest()!=expected:raise ValueError('Exact approved runtime manifest required')
    files=json.loads(manifest.read_text())
    entries=list(root.rglob('*'))
    if any(p.is_symlink() or p.stat().st_mode&0o022 or (require_root and p.stat().st_uid!=0) for p in entries):
        raise PermissionError('Immutable source members and directories required')
    actual={str(p.relative_to(root)) for p in entries if p.is_file() and p!=manifest}
    if set(files)!=actual:raise ValueError('Unexpected runtime member')
    for name,digest in files.items():
        p=root/name;st=p.lstat()
        if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) or not stat.S_ISREG(st.st_mode) or st.st_mode&0o022 or (require_root and st.st_uid!=0):
            raise PermissionError('Immutable regular source member required')
        if sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('Runtime member changed')
    return len(files)


def main():
    if os.geteuid()==0:raise PermissionError('Command center must run unprivileged')
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    raw=protected(args.config).read_bytes();value=json.loads(raw)
    if set(value)!={'application','database','artifacts','tls_certificate','tls_key','staging_public_key'}:
        raise ValueError('Exact reviewed entrypoint fields required')
    approval=None
    if value['application'].get('mode')=='production':
        if ROOT!=Path('/usr/local/share/optibrain-command-center-v1'):raise PermissionError('Exact approved runtime path required')
        approval=json.loads(protected('/etc/optibrain/command-center-rollout.json').read_text())
        # A one-time rollout authorization produces a pinned installation receipt.
        # Running that same installed code does not require daily reapproval.
        if (approval.get('state')!='INSTALLED_APPROVED' or approval.get('approved') is not True or
            approval.get('config_sha256')!=sha256(raw).hexdigest() or
            datetime.fromisoformat(approval['installed_at'])>datetime.now(timezone.utc) or
            datetime.fromisoformat(approval['installed_at'])>=datetime.fromisoformat(approval['authorization_expires_at'])):
            raise PermissionError('Exact approved installation receipt required')
        verify_source(ROOT,approval['manifest_sha256'])
    from command_center import Config,create_app
    from review import Review
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    config=Config(**value['application']);resolver=None
    if config.mode=='staging':
        if (config.team_domain!='https://optibrain-preview.cloudflareaccess.com' or
            config.audience!='optibrain-command-center-staging-only' or
            config.owner_emails!=['preview-owner@example.invalid']):
            raise PermissionError('Distinct synthetic staging identity required')
        key=load_pem_public_key(protected(value['staging_public_key']).read_bytes());resolver=lambda token:key
    else:
        if value['staging_public_key'] is not None:raise PermissionError('No test key may enter production')
        if Path('/proc/self/attr/current').read_text().strip()!='optibrain-command-center-v1 (enforce)':
            raise PermissionError('Exact enforced journal-only AppArmor profile required')
        if Path(value['database']).resolve()!=Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db').resolve():
            raise PermissionError('Existing canonical journal required')
    app=create_app(Review(value['database'],value['artifacts']),config,key_resolver=resolver)
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8877,proxy_headers=False,forwarded_allow_ips='',
        ssl_certfile=str(protected(value['tls_certificate'])),ssl_keyfile=str(protected(value['tls_key'])),
        ssl_version=ssl.PROTOCOL_TLS_SERVER,ssl_ciphers='ECDHE+AESGCM:ECDHE+CHACHA20',
        server_header=False,access_log=False,log_level='warning',limit_concurrency=16,timeout_keep_alive=5)


if __name__=='__main__':main()
