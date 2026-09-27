#!/usr/bin/env bash
set -Eeuo pipefail

# Root-run Phase 2A R2 bootstrap. This script deliberately creates no R2 API
# credential: Cloudflare's account R2 credential secret is dashboard-only and
# is displayed once. Routine upload access must therefore be created manually
# with an explicit bucket restriction.

readonly ENV_FILE="${OPTIBRAIN_WORKFLOW_ENV_FILE:-/etc/opticable-workflow-api.env}"
readonly BOOTSTRAP_TOKEN_FILE="${OPTIBRAIN_R2_BOOTSTRAP_TOKEN_FILE:-/etc/optibrain/cloudflare-test-token}"
readonly RECIPIENT_FILE="${OPTIBRAIN_PHASE2A_RECIPIENT_FILE:-/etc/optibrain/age-recipient}"
readonly BACKUP_DIR="${OPTIBRAIN_PHASE2A_BACKUP_DIR:-/var/backups/optibrain}"
readonly BACKUP_SCRIPT="${OPTIBRAIN_PHASE1_BACKUP_SCRIPT:-/opt/opticable-api-platform/ops/backup/optibrain-backup.sh}"
readonly TARGET_BUCKET="optibrain-recovery-prod"
readonly CLOUDFLARE_API="${OPTIBRAIN_CLOUDFLARE_API:-https://api.cloudflare.com/client/v4}"

tmp_dir=""
cleanup() { [[ -n "${tmp_dir}" && -d "${tmp_dir}" ]] && rm -rf -- "${tmp_dir}"; }
trap cleanup EXIT
die() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

require_root() { [[ ${EUID} -eq 0 ]] || die 'must run as root'; }
read_env_value() {
  python3 - "${ENV_FILE}" "$1" <<'PY'
import re, shlex, sys
path, wanted = sys.argv[1:]
pattern = re.compile(r'^[ \t]*(?:export[ \t]+)?' + re.escape(wanted) + r'[ \t]*=(.*)$')
for raw in open(path, encoding='utf-8', errors='replace'):
    m = pattern.match(raw.rstrip('\n'))
    if not m: continue
    try: values = shlex.split(m.group(1), comments=True, posix=True)
    except ValueError: raise SystemExit(1)
    if len(values) == 1: print(values[0])
    break
PY
}
json_success() { python3 - "$1" <<'PY'
import json, sys
try: print('true' if json.load(open(sys.argv[1])).get('success') is True else 'false')
except Exception: print('false')
PY
}
json_bucket_names() { python3 - "$1" <<'PY'
import json, sys
try:
    data=json.load(open(sys.argv[1]))
    result=data.get('result')
    buckets=result.get('buckets') if isinstance(result, dict) else None
    if data.get('success') is not True or not isinstance(buckets, list):
        raise ValueError('invalid bucket response')
    names=[]
    for item in buckets:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('invalid bucket entry')
        names.append(item['name'])
    for name in names: print(name)
except Exception:
    print('ERROR: invalid R2 bucket listing response', file=sys.stderr)
    raise SystemExit(1)
PY
}
json_errors() { python3 - "$1" <<'PY'
import json, sys
try:
    data=json.load(open(sys.argv[1])); values=[]
    for item in data.get('errors', []):
        if isinstance(item, dict) and item.get('code') is not None: values.append(str(item['code']))
    print(','.join(values) if values else 'none')
except Exception: print('unparseable')
PY
}
http() {
  local out="$1" method="$2" url="$3" body="${4:-}"
  if [[ -n "${body}" ]]; then
    curl --silent --show-error --max-time 20 -X "${method}" -H "Content-Type: application/json" \
      --config "${tmp_dir}/curl.conf" --data "${body}" -o "${out}" -w '%{http_code}' "${url}" 2>/dev/null || printf '000'
  else
    curl --silent --show-error --max-time 20 -X "${method}" --config "${tmp_dir}/curl.conf" \
      -o "${out}" -w '%{http_code}' "${url}" 2>/dev/null || printf '000'
  fi
}
list_buckets() {
  local code
  code="$(http "${tmp_dir}/buckets.json" GET "${CLOUDFLARE_API}/accounts/${ACCOUNT_ID}/r2/buckets")"
  [[ ${code} == 200 && $(json_success "${tmp_dir}/buckets.json") == true ]] || die "R2 bucket listing failed (HTTP ${code}, error codes: $(json_errors "${tmp_dir}/buckets.json"))"
  json_bucket_names "${tmp_dir}/buckets.json"
}

check_production_health() {
  local response_file="$1" download_file="${1}.download" http_code curl_status=0

  # Use a separate download path. curl is allowed to remove its output path on
  # transfer failure; parsing only happens after curl success and an explicit
  # file-existence check.
  rm -f -- "${download_file}"
  if http_code="$(curl --silent --show-error --max-time 20 -o "${download_file}" \
    -w '%{http_code}' http://127.0.0.1:8100/health 2>/dev/null)"; then
    :
  else
    curl_status=$?
  fi
  (( curl_status == 0 )) || die "production health check failed (curl exit ${curl_status})"
  [[ -f "${download_file}" ]] || die 'production health check failed (response file missing)'
  mv -- "${download_file}" "${response_file}" || die 'production health check failed (response file could not be finalized)'

  python3 - "${http_code}" "${response_file}" <<'PY' || die 'production health check failed'
import json
import re
import sys

http_code, response_file = sys.argv[1:]
try:
    with open(response_file, encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, ValueError, TypeError):
    raise SystemExit(1)

if not isinstance(data, dict) or http_code != "200" or data.get("status") != "ok":
    raise SystemExit(1)

version = data.get("version")
if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+:-]{0,31}", version):
    version = "unknown"
print(f"Production workflow API: PASS (HTTP 200, status=ok, version={version})")
PY
}

main() {
require_root
for command in curl python3 sha256sum systemctl; do command -v "${command}" >/dev/null || die "${command} is required"; done
tmp_dir="$(mktemp -d)"; chmod 700 "${tmp_dir}"
[[ -r "${ENV_FILE}" ]] || die "protected workflow environment is missing"
[[ -r "${BOOTSTRAP_TOKEN_FILE}" && -s "${BOOTSTRAP_TOKEN_FILE}" ]] || die "bootstrap token is missing"
[[ -r "${RECIPIENT_FILE}" ]] || die "public AGE recipient is missing"
recipient="$(tr -d '[:space:]' <"${RECIPIENT_FILE}")"
[[ ${recipient} =~ ^age1[a-z0-9]+$ ]] || die 'AGE recipient is not a public recipient'
[[ $(wc -l <"${RECIPIENT_FILE}") -eq 1 ]] || die 'AGE recipient must contain one line'
! grep -Eq 'AGE-SECRET-KEY-|BEGIN AGE ENCRYPTED' "${RECIPIENT_FILE}" || die 'private AGE material found in recipient file'

latest="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'optibrain-backup-*.tar.gz' -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
[[ -n ${latest} && -f ${latest}.sha256 ]] || die 'latest Phase 1 backup or checksum is missing'
sha256sum -c "${latest}.sha256" >/dev/null || die 'latest Phase 1 checksum failed'
"${BACKUP_SCRIPT}" --verify "${latest}" >/dev/null || die 'latest Phase 1 verification failed'
[[ $(systemctl is-enabled optibrain-backup.timer 2>/dev/null || true) == enabled ]] || die 'Phase 1 backup timer is not enabled'
[[ $(systemctl is-active optibrain-backup.timer 2>/dev/null || true) == active ]] || die 'Phase 1 backup timer is not active'
health="${tmp_dir}/health.json"
check_production_health "${health}"

ACCOUNT_ID="$(read_env_value CLOUDFLARE_ACCOUNT_ID)"
[[ ${ACCOUNT_ID} =~ ^[0-9a-fA-F]{32}$ ]] || die 'Cloudflare account ID is invalid or missing'
: >"${tmp_dir}/curl.conf"; chmod 600 "${tmp_dir}/curl.conf"
printf 'header = "Authorization: Bearer %s"\nheader = "Accept: application/json"\n' \
  "$(<"${BOOTSTRAP_TOKEN_FILE}")" >"${tmp_dir}/curl.conf"
verify_code="$(http "${tmp_dir}/verify.json" GET "${CLOUDFLARE_API}/accounts/${ACCOUNT_ID}/tokens/verify")"
[[ ${verify_code} == 200 && $(json_success "${tmp_dir}/verify.json") == true ]] || die "bootstrap token verification failed (HTTP ${verify_code}, error codes: $(json_errors "${tmp_dir}/verify.json"))"
printf 'Bootstrap token: verified\n'

bucket_names="$(list_buckets)" || die 'R2 bucket discovery failed; refusing creation'
mapfile -t buckets <<<"${bucket_names}"
if printf '%s\n' "${buckets[@]}" | grep -Fxq "${TARGET_BUCKET}"; then
  operation='already present; no create performed'
else
  create_code="$(http "${tmp_dir}/create.json" POST "${CLOUDFLARE_API}/accounts/${ACCOUNT_ID}/r2/buckets" '{"name":"optibrain-recovery-prod"}')"
  [[ ${create_code} == 200 && $(json_success "${tmp_dir}/create.json") == true ]] || die "target bucket creation failed (HTTP ${create_code}, error codes: $(json_errors "${tmp_dir}/create.json"))"
  operation='created exactly once'
fi
bucket_names="$(list_buckets)" || die 'R2 bucket verification failed'
mapfile -t buckets <<<"${bucket_names}"
printf '%s\n' "${buckets[@]}" | grep -Fxq "${TARGET_BUCKET}" || die 'target bucket not present after bootstrap'
printf 'Target bucket: %s\nBucket operation: %s\n' "${TARGET_BUCKET}" "${operation}"
printf 'Bucket privacy: private by default; no public URL or custom-domain request made\n'
printf 'Permanent uploader approach: dashboard-created account R2 API token, Object Read & Write, specific bucket only; no credential created by this script\n'
printf 'Credential creation: dashboard-required (secret is one-time displayed; no secret stored or printed)\n'
printf 'Dashboard steps: R2 Overview -> Manage API Tokens -> Create Account API token -> name optibrain-recovery-uploader -> Object Read & Write -> apply to specific buckets only -> select %s -> create -> save Access Key ID and Secret Access Key once in a root-only 0600 file\n' "${TARGET_BUCKET}"
printf 'AGE recipient: public recipient verified\nPrivate AGE identity on VPS: absent from recipient file; this script neither reads nor creates one\n'
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
