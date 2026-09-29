#!/usr/bin/env bash
# Installed as a root-owned wrapper only through separately reviewed bootstrap.
set -Eeuo pipefail
[[ ${EUID} -eq 0 && $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || exit 64
target_sha=$1
guard_path=/var/lib/optibrain/phase6/active-release.json
if [[ -e $guard_path || -L $guard_path ]]; then
  # A staged release cannot be replaced by a delayed baseline/main workflow.
  env -i PATH=/usr/bin:/bin /usr/bin/python3 - "$guard_path" "$target_sha" <<'PY'
import json, os, re, stat, sys
path, target = sys.argv[1:]
descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
with os.fdopen(descriptor) as handle:
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
        raise SystemExit("Unsafe release guard")
    value = json.load(handle)
if value.get("baseline") != "52f11d4fc14d8582c03837e0317f849efe8aa3d7" or not re.fullmatch(r"[a-f0-9]{40}", value.get("candidate", "")) or value["candidate"] != target:
    raise SystemExit("Requested deployment differs from staged release")
if value.get("status") not in {"staging", "staged", "promoted", "complete", "blocked"}:
    raise SystemExit("Unknown release guard state")
PY
fi
umask 077
trusted_stage=$(mktemp -d /var/tmp/opticable-api-trusted-main.XXXXXX)
trap 'rm -rf -- "$trusted_stage"' EXIT
# Ignore caller-controlled Git/system/user configuration and the writable live repo.
trusted_git() {
  env -i PATH=/usr/bin:/bin LANG=C.UTF-8 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null /usr/bin/git "$@"
}
trusted_git init --bare --quiet "$trusted_stage/repository.git"
trusted_git -C "$trusted_stage/repository.git" -c protocol.file.allow=never \
  fetch --quiet --depth=1 https://github.com/yboucher97/opticable-api-platform.git refs/heads/main
reviewed_main=$(trusted_git -C "$trusted_stage/repository.git" rev-parse --verify 'FETCH_HEAD^{commit}')
[[ $target_sha == "$reviewed_main" ]] || { echo 'Deployment target is not current remote main.' >&2; exit 65; }
# Materialize code from the verified Git tree only AFTER the identity check.
trusted_git -C "$trusted_stage/repository.git" show "$target_sha:deploy/update-production.sh" > "$trusted_stage/deploy.sh"
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /bin/bash "$trusted_stage/deploy.sh" "$target_sha"
