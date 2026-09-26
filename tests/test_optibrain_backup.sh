#!/usr/bin/env bash
set -Eeuo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ops/backup/optibrain-backup.sh"
unit="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ops/backup/optibrain-backup.service"
timer="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ops/backup/optibrain-backup.timer"
tmp="$(mktemp -d)"
trap 'rm -rf -- "${tmp}"' EXIT
mkdir -p "${tmp}/repo/.git" "${tmp}/repo/apps/workflow-api/workflow" "${tmp}/data/automation" "${tmp}/backup" "${tmp}/shared"
printf 'fixture\n' >"${tmp}/repo/README"
printf 'API_VERSION = "fixture-1.0"\n' >"${tmp}/repo/apps/workflow-api/workflow/api.py"
printf 'fixture credential recovery payload\n' >"${tmp}/shared/recovery-fixture"
chmod 2770 "${tmp}/shared"
git -C "${tmp}/repo" init -q
git -C "${tmp}/repo" config user.email test@example.invalid
git -C "${tmp}/repo" config user.name test
git -C "${tmp}/repo" add README
git -C "${tmp}/repo" add apps/workflow-api/workflow/api.py
git -C "${tmp}/repo" commit -qm fixture

if [[ "${EUID}" -eq 0 ]]; then
  chown -R 65534:65534 "${tmp}/repo"
else
  printf 'root/non-root ownership case skipped (test process is not root)\n' >&2
fi

python3 - "${tmp}/data/automation/automation.db" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("create table test (id integer primary key, value text)")
con.execute("insert into test(value) values ('fixture')")
con.commit()
con.close()
PY
cat >"${tmp}/workflow.env" <<EOF
OPTICABLE_AUTOMATION_DB_PATH=${tmp}/data/automation/automation.db
EOF

OPTIBRAIN_REPO_DIR="${tmp}/repo" \
OPTIBRAIN_BACKUP_DIR="${tmp}/backup" \
OPTIBRAIN_WORKFLOW_ENV_FILE="${tmp}/workflow.env" \
GIT_CONFIG_GLOBAL="${tmp}/missing-global-gitconfig" \
GIT_CONFIG_SYSTEM=/dev/null \
OPTIBRAIN_SKIP_LIVE_STATE=false \
OPTIBRAIN_SKIP_LIVE_CONFIG=true \
OPTIBRAIN_PLATFORM_SHARED_DIR="${tmp}/shared" \
OPTIBRAIN_WORKFLOW_STATE_DIR="${tmp}/missing-workflow-state" \
OPTIBRAIN_PASSWORD_PDF_STATE_DIR="${tmp}/missing-password-state" \
OPTIBRAIN_OMADA_STATE_DIR="${tmp}/missing-omada-state" \
  bash "${script}"
archive="$(find "${tmp}/backup" -name 'optibrain-backup-*.tar.gz' -print -quit)"
[[ -n "${archive}" ]]
[[ "$(stat -c '%a' "${tmp}/backup")" == 700 ]]
[[ "$(stat -c '%a' "${archive}")" == 600 ]]
[[ ! -e "${tmp}/backup.log" ]]
sha256sum -c "${archive}.sha256"
bash "${script}" --verify "${archive}"
extract_dir="${tmp}/extract"
mkdir -p "${extract_dir}"
tar -xzf "${archive}" -C "${extract_dir}"
manifest="$(find "${extract_dir}" -name manifest.json -print -quit)"
python3 - "${manifest}" <<'PY'
import json, pathlib, sys
data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
matches = [entry for entry in data["source_metadata"] if entry["source_path"].endswith("/shared")]
assert matches and matches[0]["mode"] == "2770", matches
assert any(entry["backup_path"].endswith("/shared/recovery-fixture") for entry in data["source_metadata"])
PY
staged_shared="$(find "${extract_dir}" -path '*/state/var/lib/opticable-api-platform/shared' -type d -print -quit)"
[[ -n "${staged_shared}" ]]
[[ "$(stat -c '%a' "${staged_shared}")" != 2770 ]]

if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze verify "${unit}" "${timer}"
else
  printf 'systemd-analyze unavailable; unit validation skipped\n' >&2
fi
! grep -Fq '/var/log/optibrain-backup.log' "${unit}"
grep -Fq 'StandardOutput=journal' "${unit}"
grep -Fq 'StandardError=journal' "${unit}"
grep -Fq 'RestrictSUIDSGID=true' "${unit}"
grep -Fq -- '--no-same-permissions' "${script}"
grep -Fq 'safe.directory=' "${script}"
! grep -Fq 'safe.directory=*' "${script}"
! grep -Fq 'OPTIBRAIN_BACKUP_LOG' "${script}"
printf 'backup fixture test passed\n'
