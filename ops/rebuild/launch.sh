#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
# Download this file from a reviewed commit and verify its published hash first.
# Usage: launch.sh EXACT_TOOLCHAIN_SHA EXACT_SOURCE_ARCHIVE_SHA256 restore ...
TOOLCHAIN_SHA="${1:?exact reviewed toolchain SHA required}"
[[ "${TOOLCHAIN_SHA}" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid toolchain SHA' >&2; exit 1; }
TOOLCHAIN_ARCHIVE_SHA256="${2:?verified toolchain source archive hash required}"
[[ "${TOOLCHAIN_ARCHIVE_SHA256}" =~ ^[0-9a-f]{64}$ ]] || { echo 'Invalid toolchain archive hash' >&2; exit 1; }
shift 2
[[ "${EUID}" -eq 0 ]] || { echo 'Root required on replacement' >&2; exit 1; }
if [[ ! -f /var/lib/optibrain-rebuild/state.json ]]; then
  [[ ! -e /etc/optibrain && ! -e /var/lib/optibrain/releases/current.json && ! -e /var/lib/opticable-workflow-api/output/automation/automation.db ]] \
    || { echo 'Existing production host refused; no packages changed' >&2; exit 1; }
fi
. /etc/os-release
[[ "${ID}" == ubuntu && "${VERSION_ID}" == 24.04 && "$(uname -m)" == x86_64 ]] \
  || { echo 'Ubuntu 24.04 amd64 required' >&2; exit 1; }
# Fetch reviewed tooling as data with Ubuntu's Python stdlib. Git is installed
# later by the canonical audited package operation; no unaudited apt pre-step.
TOOLCHAIN_DIR="/opt/optibrain-rebuild-toolchain/${TOOLCHAIN_SHA}"
/usr/bin/python3 -B - "${TOOLCHAIN_SHA}" "${TOOLCHAIN_ARCHIVE_SHA256}" "${TOOLCHAIN_DIR}" <<'PY'
import hashlib,json,os,pathlib,sys,tarfile,tempfile,urllib.request
sha,expected,target=sys.argv[1:];target=pathlib.Path(target)
receipt=target/'rebuild-toolchain-identity.json'
try:
    for parent in (target,*target.parents):
        assert not parent.is_symlink()
        if parent.exists():
            info=parent.stat();assert info.st_uid==0 and not info.st_mode&0o022
    if receipt.exists():
        assert receipt.stat().st_uid==0 and not receipt.stat().st_mode&0o022
        assert all(not p.is_symlink() for p in target.rglob('*'))

    if receipt.exists():
        saved=json.loads(receipt.read_text())
        assert saved['sha']==sha and saved['archive_sha256']==expected
        for name,digest in saved['files'].items():
            path=target/name
            assert not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest()==digest
    else:
        assert not target.exists(), 'Incomplete toolchain staging retained; inspect before retry'
        target.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent,prefix='download-') as directory:
            archive=pathlib.Path(directory)/'source.tar.gz';h=hashlib.sha256();count=0
            url='https://codeload.github.com/yboucher97/opticable-api-platform/tar.gz/'+sha
            with urllib.request.urlopen(url,timeout=60) as source,archive.open('xb') as output:
                for block in iter(lambda:source.read(1024*1024),b''):
                    count+=len(block);assert count<=32*1024*1024
                    h.update(block);output.write(block)
            assert h.hexdigest()==expected, 'Toolchain archive hash mismatch'
            with tarfile.open(archive) as tar:
                members=tar.getmembers();names=set();expanded=0
                for member in members:
                    parts=pathlib.PurePosixPath(member.name).parts
                    assert member.name not in names and not member.name.startswith('/') and '..' not in parts
                    assert parts[0]=='opticable-api-platform-'+sha and (member.isfile() or member.isdir())
                    names.add(member.name);expanded+=member.size;assert expanded<=128*1024*1024
                target.mkdir(mode=0o755)
                hashes={}
                for member in members:
                    relative=pathlib.PurePosixPath(member.name).relative_to('opticable-api-platform-'+sha)
                    path=target/relative
                    if member.isdir():path.mkdir(mode=0o755,parents=True,exist_ok=True)
                    else:
                        path.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
                        with tar.extractfile(member) as source,path.open('xb') as output:output.write(source.read())
                        path.chmod(0o755 if member.mode&0o111 else 0o644)
                        hashes[str(relative)]=hashlib.sha256(path.read_bytes()).hexdigest()
                receipt.write_text(json.dumps({'sha':sha,'archive_sha256':expected,'files':hashes},sort_keys=True)+'\n')
                receipt.chmod(0o600)
except Exception as exc:
    raise SystemExit('Reviewed toolchain acquisition failed: '+type(exc).__name__)
PY
chown -R root:root "${TOOLCHAIN_DIR}"
chmod -R a+rX "${TOOLCHAIN_DIR}"
exec /usr/bin/python3 -B "${TOOLCHAIN_DIR}/ops/rebuild/cli.py" "$@"
