#!/usr/bin/env bash
set -Eeuo pipefail

readonly BACKUP_FORMAT_VERSION="1"
readonly SCRIPT_VERSION="1.0.4"
readonly REPO_DEFAULT="/opt/opticable-api-platform"
readonly DEST_DEFAULT="/var/backups/optibrain"
readonly CONFIG_DEFAULT="/etc/optibrain/backup.conf"
readonly WORKFLOW_ENV_DEFAULT="/etc/opticable-workflow-api.env"

REPO_DIR="${OPTIBRAIN_REPO_DIR:-${REPO_DEFAULT}}"
DEST_DIR="${OPTIBRAIN_BACKUP_DIR:-${DEST_DEFAULT}}"
CONFIG_FILE="${OPTIBRAIN_BACKUP_CONFIG:-${CONFIG_DEFAULT}}"
WORKFLOW_ENV_FILE="${OPTIBRAIN_WORKFLOW_ENV_FILE:-${WORKFLOW_ENV_DEFAULT}}"
WORKFLOW_STATE_DIR="${OPTIBRAIN_WORKFLOW_STATE_DIR:-/var/lib/opticable-workflow-api}"
PASSWORD_PDF_STATE_DIR="${OPTIBRAIN_PASSWORD_PDF_STATE_DIR:-/var/lib/opticable-password-pdf}"
OMADA_STATE_DIR="${OPTIBRAIN_OMADA_STATE_DIR:-/var/lib/opticable-omada-site}"
PLATFORM_SHARED_DIR="${OPTIBRAIN_PLATFORM_SHARED_DIR:-/var/lib/opticable-api-platform/shared}"
RETENTION_GENERATIONS="${OPTIBRAIN_BACKUP_RETENTION:-7}"
VERIFY_ARCHIVE=""
PRESERVE_EXISTING=false

log() {
  local line="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
  printf '%s\n' "$line" >&2
  command -v logger >/dev/null 2>&1 && logger -t optibrain-backup -- "$*" 2>/dev/null || true
}
fail() { log "ERROR: $*"; exit 1; }

# ProtectHome=true makes root's ~/.gitconfig unavailable to the service. Keep
# Git's trust exception command-scoped and limited to this checkout; never use
# a wildcard safe.directory value.
git_repo() {
  if [[ "${EUID}" -eq 0 && "${REPO_DIR}" == "${REPO_DEFAULT}" ]]; then
    /usr/sbin/runuser -u optibrain -- /usr/bin/git -c core.fsmonitor=false -c core.hooksPath=/dev/null -C "${REPO_DIR}" "$@"
  else
    /usr/bin/git -c core.fsmonitor=false -c core.hooksPath=/dev/null -c "safe.directory=${REPO_DIR}" -C "${REPO_DIR}" "$@"
  fi
}

usage() {
  cat <<'EOF'
Usage:
  optibrain-backup.sh [--config FILE] [--output-dir DIR] [--preserve-existing]
  optibrain-backup.sh --verify ARCHIVE
EOF
}

while (($#)); do
  case "$1" in
    --config) CONFIG_FILE="${2:?missing config path}"; shift 2 ;;
    --output-dir) DEST_DIR="${2:?missing output path}"; shift 2 ;;
    --verify) VERIFY_ARCHIVE="${2:?missing archive path}"; shift 2 ;;
    --preserve-existing) PRESERVE_EXISTING=true; shift ;;
    --retention) RETENTION_GENERATIONS="${2:?missing retention count}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; fail "unknown argument: $1" ;;
  esac
done

readonly PRESERVE_EXISTING

if [[ -f "${CONFIG_FILE}" ]]; then
  # Administrator-owned configuration only; no secret values belong here.
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
  REPO_DIR="${OPTIBRAIN_REPO_DIR:-${REPO_DIR}}"
  DEST_DIR="${OPTIBRAIN_BACKUP_DIR:-${DEST_DIR}}"
  WORKFLOW_ENV_FILE="${OPTIBRAIN_WORKFLOW_ENV_FILE:-${WORKFLOW_ENV_FILE}}"
  WORKFLOW_STATE_DIR="${OPTIBRAIN_WORKFLOW_STATE_DIR:-${WORKFLOW_STATE_DIR}}"
  PASSWORD_PDF_STATE_DIR="${OPTIBRAIN_PASSWORD_PDF_STATE_DIR:-${PASSWORD_PDF_STATE_DIR}}"
  OMADA_STATE_DIR="${OPTIBRAIN_OMADA_STATE_DIR:-${OMADA_STATE_DIR}}"
  PLATFORM_SHARED_DIR="${OPTIBRAIN_PLATFORM_SHARED_DIR:-${PLATFORM_SHARED_DIR}}"
  RETENTION_GENERATIONS="${OPTIBRAIN_BACKUP_RETENTION:-${RETENTION_GENERATIONS}}"
fi
umask 077

require_safe_destination() {
  [[ -d "${REPO_DIR}/.git" ]] || fail "repository is not a Git checkout: ${REPO_DIR}"
  mkdir -p "${DEST_DIR}"; chmod 700 "${DEST_DIR}"
  [[ "${EUID}" -eq 0 ]] && chown root:root "${DEST_DIR}"
  local repo_real dest_real
  repo_real="$(realpath -e "${REPO_DIR}")"; dest_real="$(realpath -e "${DEST_DIR}")"
  [[ "${dest_real}" != "${repo_real}" && "${dest_real}" != "${repo_real}"/* ]] \
    || fail "refusing backup destination inside the Git repository: ${dest_real}"
}

read_env_value() {
  local key="$1"
  [[ -r "${WORKFLOW_ENV_FILE}" ]] || return 0
  awk -F= -v wanted="${key}" '$1 == wanted { sub(/^[^=]*=/, ""); gsub(/^['"'"']|['"'"'"'"'"'"'"'"']$/, ""); print; exit }' "${WORKFLOW_ENV_FILE}"
}

sqlite_backup() {
  local source="$1" destination="$2" result_file="$3"
  [[ -f "${source}" ]] || fail "automation SQLite database not found: ${source}"
  python3 - "${source}" "${destination}" "${result_file}" <<'PY'
import sqlite3, sys
source, destination, result_file = sys.argv[1:]
try:
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
    src.execute("PRAGMA busy_timeout=30000")
    dst = sqlite3.connect(destination, timeout=30)
    src.backup(dst)
    result = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close(); src.close()
    with open(result_file, "w", encoding="utf-8") as handle: handle.write(str(result))
    if result != "ok": raise RuntimeError(f"SQLite integrity_check returned {result!r}")
except Exception as exc:
    with open(result_file, "w", encoding="utf-8") as handle: handle.write(f"ERROR: {exc}")
    raise
PY
}

verify_archive() {
  local archive="$1" verify_dir manifest
  [[ -f "${archive}" ]] || fail "archive not found: ${archive}"
  verify_dir="$(mktemp -d)"
  trap 'rm -rf -- "${verify_dir}"' RETURN
  tar -tzf "${archive}" >/dev/null || fail "archive is not readable: ${archive}"
  if tar -tzf "${archive}" | awk 'BEGIN { bad=0 } ($0 ~ /^\// || $0 ~ /(^|\/)\.\.($|\/)/) { bad=1 } END { exit bad }'; then :; else
    fail "archive contains an unsafe absolute or parent-traversal path: ${archive}"
  fi
  tar -xzf "${archive}" -C "${verify_dir}" --no-same-owner
  manifest="$(find "${verify_dir}" -type f -name manifest.json -print -quit)"
  [[ -n "${manifest}" ]] || fail "manifest.json missing from ${archive}"
  python3 - "${manifest}" "$(dirname "${manifest}")" <<'PY'
import hashlib, json, pathlib, sqlite3, sys
manifest_path = pathlib.Path(sys.argv[1]); root = pathlib.Path(sys.argv[2])
data = json.loads(manifest_path.read_text(encoding="utf-8"))
if data.get("backup_format_version") != "1": raise SystemExit("unsupported backup format")
for entry in data.get("files", []):
    path = root / entry["path"]
    if not path.is_file(): raise SystemExit(f"missing file: {entry['path']}")
    if path.stat().st_size != entry["size"]: raise SystemExit(f"size mismatch: {entry['path']}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise SystemExit(f"checksum mismatch: {entry['path']}")
for entry in data.get("sqlite_databases", []):
    path = root / entry["backup_path"]
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    result = con.execute("PRAGMA integrity_check").fetchone()[0]; con.close()
    if result != "ok": raise SystemExit(f"SQLite integrity failure: {entry['backup_path']}: {result}")
print("verified")
PY
  log "Verified backup archive: ${archive}"
}

if [[ -n "${VERIFY_ARCHIVE}" ]]; then verify_archive "${VERIFY_ARCHIVE}"; exit 0; fi
if [[ "${EUID}" -ne 0 && ( "${REPO_DIR}" == "${REPO_DEFAULT}" || "${DEST_DIR}" == "${DEST_DEFAULT}" ) ]]; then
  fail "backup creation must run as root so protected state and secret files remain recoverable"
fi
require_safe_destination
# Same lock for systemd and manual CLI; no unrelated job is blocked. The
# destination is root-owned0700 in production and the lock is never removed.
exec 9>"${DEST_DIR}/.backup.lock"
flock -n 9 || fail "another local backup is already running"
[[ "${RETENTION_GENERATIONS}" =~ ^[1-9][0-9]*$ ]] || fail "retention must be a positive integer"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
generation="${DEST_DIR}/generation-${timestamp}"
archive="${DEST_DIR}/optibrain-backup-${timestamp}.tar.gz"
[[ ! -e "${archive}" && ! -e "${archive}.sha256" && ! -e "${generation}" ]] || fail "backup generation collision"
staging="$(mktemp -d "${DEST_DIR}/.staging-${timestamp}.XXXXXX")"
trap 'rm -rf -- "${staging}"' EXIT
mkdir -p "${staging}/source" "${staging}/state" "${staging}/system" "${staging}/credentials" "${staging}/database"

git_sha="$(git_repo rev-parse HEAD)"
git_branch="$(git_repo symbolic-ref --short -q HEAD || printf detached)"
git_dirty="$( [[ -z "$(git_repo status --porcelain)" ]] && printf false || printf true )"
app_version="$(grep -E '^[[:space:]]*API_VERSION[[:space:]]*=' "${REPO_DIR}/apps/workflow-api/workflow/api.py" | head -1 | sed -E 's/.*=//; s/[[:space:]\"'"'"']//g')"
app_version="${app_version:-unknown}"

git_repo archive --format=tar.gz --prefix="opticable-api-platform-${git_sha}/" HEAD >"${staging}/source/opticable-api-platform-${git_sha}.tar.gz"
cat >"${staging}/source/release-identity.txt" <<EOF
backup_script_version=${SCRIPT_VERSION}
repository=${REPO_DIR}
production_git_sha=${git_sha}
production_git_branch=${git_branch}
production_git_dirty=${git_dirty}
application_version=${app_version}
hostname=$(hostname -f 2>/dev/null || hostname)
timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

copy_if_present() {
  local source="$1" target="$2"
  [[ -e "${source}" ]] || return 0
  if [[ -L "${source}" && ( "${source}" == /etc/systemd/system/optibrain-* || "${source}" == /etc/systemd/system/opticable-* ) && "$(readlink "${source}")" == /dev/null ]]; then
    # Encode retired AND fresh-recovery unit masks as regular metadata; never
    # extract an absolute symlink. These are denial state, never enablement.
    mkdir -p "${staging}/system"
    python3 - "${staging}/system/systemd-masks.json" "$(basename "${source}")" <<'PY'
import json,pathlib,re,sys
if not re.fullmatch(r'optibrain-agent-(dispatch|status|usage)\.(service|timer)|(?:optibrain-backup|optibrain-phase2a-upload|opticable-phase9-intake-receipts|opticable-phase10-service-events|opticable-phase12-test-runner)\.timer|opticable-phase12-test-runner\.service',sys.argv[2]):
    raise SystemExit('unsupported masked application unit')
p=pathlib.Path(sys.argv[1]);units=json.loads(p.read_text()) if p.exists() else []
p.write_text(json.dumps(sorted(set(units+[sys.argv[2]]))))
PY
    return 0
  fi
  record_source_metadata "${source}" "${target}"
  if [[ -d "${source}" && ! -L "${source}" ]]; then
    mkdir -p "${staging}/${target}"
    # Preserve source metadata in the archive/manifest, but do not apply source
    # permissions while constructing the staging tree. In particular, a setgid
    # source directory must not become a setgid staging directory.
    tar -C "${source}" -cf - . | tar -C "${staging}/${target}" --no-same-owner --no-same-permissions -xf -
  else
    mkdir -p "$(dirname "${staging}/${target}")"
    tar -C "$(dirname "${source}")" -cf - "$(basename "${source}")" \
      | tar -C "$(dirname "${staging}/${target}")" --no-same-owner --no-same-permissions -xf -
  fi
}

record_source_metadata() {
  local source="$1" target="$2" excluded_relative="${3:-}"
  python3 - "${source}" "${target}" "${excluded_relative}" "${staging}/metadata.jsonl" <<'PY'
import grp, json, pathlib, pwd, sys
source, target, excluded_relative, output = sys.argv[1:]
root = pathlib.Path(source)
paths = [root] if not root.is_dir() or root.is_symlink() else sorted([root, *root.rglob("*")])
with open(output, "a", encoding="utf-8") as handle:
    for path in paths:
        relative = "." if path == root else path.relative_to(root).as_posix()
        if excluded_relative and (relative == excluded_relative or relative.startswith(excluded_relative + "/") or relative.endswith((".db-wal", ".db-shm"))):
            continue
        stat = path.lstat()
        mode = stat.st_mode & 0o7777
        if path.is_dir() and not path.is_symlink(): kind = "directory"
        elif path.is_symlink(): kind = "symlink"
        elif path.is_file(): kind = "file"
        else: kind = "other"
        try: owner = pwd.getpwuid(stat.st_uid).pw_name
        except KeyError: owner = str(stat.st_uid)
        try: group = grp.getgrgid(stat.st_gid).gr_name
        except KeyError: group = str(stat.st_gid)
        handle.write(json.dumps({
            "source_path": str(path), "backup_path": f"{target}/{relative}",
            "type": kind, "uid": stat.st_uid, "gid": stat.st_gid,
            "owner": owner, "group": group, "mode": format(mode, "04o"),
            "mtime_ns": stat.st_mtime_ns,
        }, sort_keys=True) + "\n")
PY
}

db_path="$(read_env_value OPTICABLE_AUTOMATION_DB_PATH)"
if [[ -z "${db_path}" ]]; then
  output_root="$(read_env_value SITE_WORKFLOW_OUTPUT_ROOT)"
  output_root="${output_root:-/var/lib/opticable-workflow-api/output/site_workflow}"
  db_path="${output_root}/automation/automation.db"
fi
db_path="$(realpath -m "${db_path}")"

copy_workflow_state_without_database() {
  local source="$1" target="$2" relative_db
  [[ -d "${source}" ]] || return 0
  relative_db="$(realpath --relative-to="${source}" "${db_path}" 2>/dev/null || true)"
  record_source_metadata "${source}" "${target}" "${relative_db}"
  mkdir -p "${staging}/${target}"
  tar_args=(--exclude='./*.db' --exclude='./*.db-wal' --exclude='./*.db-shm')
  if [[ -n "${relative_db}" && "${relative_db}" != ../* ]]; then
    tar_args+=("--exclude=./${relative_db}" "--exclude=./${relative_db}-wal" "--exclude=./${relative_db}-shm")
  fi
  tar -C "${source}" "${tar_args[@]}" -cf - . \
    | tar -C "${staging}/${target}" --no-same-owner --no-same-permissions -xf -
}

if [[ "${OPTIBRAIN_SKIP_LIVE_STATE:-false}" != "true" ]]; then
  copy_workflow_state_without_database "${WORKFLOW_STATE_DIR}" state/var/lib/opticable-workflow-api
  copy_if_present "${PASSWORD_PDF_STATE_DIR}" state/var/lib/opticable-password-pdf
  copy_if_present "${OMADA_STATE_DIR}" state/var/lib/opticable-omada-site
  copy_if_present "${PLATFORM_SHARED_DIR}" state/var/lib/opticable-api-platform/shared
  # Root-owned protection, crosswalk, action, document and recovery state is
  # required for a safe restore. Exclude encrypted backup cache recursion.
  if [[ -d /var/lib/optibrain ]]; then
    record_source_metadata /var/lib/optibrain state/var/lib/optibrain phase2a
    mkdir -p "${staging}/state/var/lib/optibrain"
    tar -C /var/lib/optibrain --exclude='./phase2a' --exclude='./*.db' --exclude='./*.db-wal' --exclude='./*.db-shm' -cf - . \
      | tar -C "${staging}/state/var/lib/optibrain" --no-same-owner --no-same-permissions -xf -
    copy_if_present /var/lib/optibrain/phase2a/state.json state/var/lib/optibrain/phase2a/state.json
  fi
fi

if [[ "${OPTIBRAIN_SKIP_LIVE_STATE:-false}" != "true" && "${OPTIBRAIN_SKIP_LIVE_CONFIG:-false}" != "true" ]]; then
  for path in \
    /etc/opticable-workflow-api.env /etc/opticable-password-pdf.env /etc/opticable-omada-site.env \
    /etc/optibrain /etc/opticable-password-pdf /etc/caddy/Caddyfile /etc/caddy/conf.d /etc/systemd/journald.conf.d \
    /etc/systemd/system/opticable-workflow-api.service \
    /etc/systemd/system/opticable-password-pdf.service \
    /etc/systemd/system/opticable-omada-site.service; do
    [[ -e "${path}" ]] && copy_if_present "${path}" "system${path}"
  done
  for path in /etc/systemd/system/optibrain-*.service /etc/systemd/system/optibrain-*.timer \
    /etc/systemd/system/optibrain-*.service.d /etc/systemd/system/optibrain-*.timer.d \
    /etc/systemd/system/opticable-*.service /etc/systemd/system/opticable-*.timer \
    /etc/systemd/system/opticable-*.service.d /etc/systemd/system/opticable-*.timer.d \
    /usr/local/lib/optibrain /usr/local/lib/optibrain-backup \
    /usr/local/sbin/opticable-api-deploy-root /usr/local/sbin/opticable-api-deploy-command \
    /etc/ssh /home/opticable-deploy/.ssh/authorized_keys; do
    [[ -e "${path}" ]] && copy_if_present "${path}" "system${path}"
  done
fi

# Every additional application .db receives an online SQLite snapshot. Copying
# an open database while omitting its WAL is not a recoverable backup.
if [[ "${OPTIBRAIN_SKIP_LIVE_STATE:-false}" != "true" ]]; then
  while IFS= read -r -d '' extra_db; do
    [[ "${extra_db}" == "${db_path}" ]] && continue
    target="${staging}/state${extra_db}"
    mkdir -p "$(dirname "${target}")"
    sqlite_backup "${extra_db}" "${target}" "${target}.integrity"
  done < <(find "${WORKFLOW_STATE_DIR}" /var/lib/optibrain -path /var/lib/optibrain/phase2a -prune -o -type f -name '*.db' -print0)
fi

sqlite_result="${staging}/database/integrity.txt"
sqlite_backup "${db_path}" "${staging}/database/automation.db" "${sqlite_result}"
chmod 600 "${staging}/database/automation.db" "${sqlite_result}"

{
  printf 'credential_metadata_version=1\n'
  printf 'secret_values_included=true_in_root_only_archive\n'
  for path in /etc/opticable-workflow-api.env /etc/opticable-password-pdf.env /etc/opticable-omada-site.env /etc/optibrain/github-app.pem /etc/optibrain/control-plane.key; do
    if [[ -e "${path}" ]]; then stat -c 'path=%n mode=%a owner=%U group=%G size=%s present=true' "${path}"; else printf 'path=%s present=false\n' "${path}"; fi
  done
} >"${staging}/credentials/metadata.txt"

python3 - "${staging}" "${timestamp}" "${git_sha}" "${app_version}" "${sqlite_result}" <<'PY'
import hashlib, json, pathlib, socket, sys
root = pathlib.Path(sys.argv[1]); timestamp, git_sha, app_version, sqlite_result_path = sys.argv[2:]
files = []
for path in sorted(p for p in root.rglob("*") if p.is_file() and p != root / "manifest.json"):
    files.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
manifest = {
    "backup_format_version": "1", "backup_script_version": "1.0.4", "timestamp": timestamp,
    "hostname": socket.getfqdn(), "production_git_sha": git_sha, "application_version": app_version,
    "included_components": ["source_release", "sqlite_database", "persistent_state", "generated_operational_state", "etc_configuration", "systemd_units", "caddy_configuration", "credential_metadata"],
    "database_integrity": pathlib.Path(sqlite_result_path).read_text(encoding="utf-8"),
    "source_metadata": [json.loads(line) for line in (root / "metadata.jsonl").read_text(encoding="utf-8").splitlines()] if (root / "metadata.jsonl").exists() else [],
    "sqlite_databases": [{"backup_path": "database/automation.db", "integrity": "ok"}] + [
        {"backup_path": p.relative_to(root).as_posix(), "integrity": "ok"}
        for p in sorted((root / "state").rglob("*.db")) if pathlib.Path(str(p) + ".integrity").is_file()
    ], "files": files,
}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

chmod -R go-rwx "${staging}"
find "${staging}" -type d -exec chmod 700 {} +
find "${staging}" -type f -exec chmod 600 {} +
mv "${staging}" "${generation}"
trap - EXIT
tar -czf "${archive}.tmp" -C "${DEST_DIR}" "$(basename "${generation}")"
mv "${archive}.tmp" "${archive}"
sha256sum "${archive}" >"${archive}.sha256"
chmod 600 "${archive}" "${archive}.sha256"
chown root:root "${archive}" "${archive}.sha256" 2>/dev/null || true
rm -rf -- "${generation}"
verify_archive "${archive}"

mapfile -t archives < <(find "${DEST_DIR}" -maxdepth 1 -type f -name 'optibrain-backup-*.tar.gz' -printf '%T@ %p\n' | sort -nr | awk '{print $2}')
if [[ "${PRESERVE_EXISTING}" != true ]] && (( ${#archives[@]} > RETENTION_GENERATIONS )); then
  valid_count=0
  for candidate in "${archives[@]}"; do if verify_archive "${candidate}" >/dev/null 2>&1; then ((valid_count++)) || true; fi; done
  if (( valid_count > 1 )); then
    for candidate in "${archives[@]:RETENTION_GENERATIONS}"; do rm -f -- "${candidate}" "${candidate}.sha256"; log "Removed retained backup beyond policy: ${candidate}"; done
  else log "Retention skipped: refusing to risk deleting the only valid backup"; fi
fi
log "Created and verified backup: ${archive}"
printf '%s\n' "${archive}"
