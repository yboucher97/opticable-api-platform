#!/usr/bin/env bash
set -Eeuo pipefail

# Root-run, read-only Phase 2A discovery. Values are extracted as opaque data,
# never evaluated as shell, and never printed.

readonly ENV_FILE="/etc/opticable-workflow-api.env"
readonly BOOTSTRAP_TOKEN_FILE="/etc/optibrain/cloudflare-test-token"
readonly BACKUP_DIR="/var/backups/optibrain"
readonly BACKUP_SCRIPT="/opt/opticable-api-platform/ops/backup/optibrain-backup.sh"
readonly TARGET_BUCKET="optibrain-recovery-prod"
readonly CLOUDFLARE_API="https://api.cloudflare.com/client/v4"

tmp_dir=""
cf_token_file=""
cf_account_id=""

cleanup() {
  if [[ -n "${tmp_dir}" && -d "${tmp_dir}" ]]; then
    rm -rf -- "${tmp_dir}"
  fi
}
trap cleanup EXIT

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || die "must run as root"
}

read_env_value() {
  local wanted="$1"
  python3 - "${ENV_FILE}" "${wanted}" <<'PY'
import re, shlex, sys
path, wanted = sys.argv[1:]
pattern = re.compile(r'^[ \t]*(?:export[ \t]+)?' + re.escape(wanted) + r'[ \t]*=(.*)$')
for raw in open(path, encoding='utf-8', errors='replace'):
    match = pattern.match(raw.rstrip('\n'))
    if not match:
        continue
    try:
        values = shlex.split(match.group(1), comments=True, posix=True)
    except ValueError:
        raise SystemExit
    if len(values) == 1:
        print(values[0])
    break
PY
}

safe_http_code() {
  local output_file="$1"
  shift
  curl --silent --show-error --max-time 20 -o "${output_file}" -w '%{http_code}' "$@" 2>/dev/null || printf '000'
}

json_success() {
  local response_file="$1"
  python3 - "${response_file}" <<'PY'
import json, sys
try:
    data = json.loads(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    print("invalid")
    raise SystemExit
print("true" if data.get("success") is True else "false")
PY
}

json_token_status() {
  local response_file="$1"
  python3 - "${response_file}" <<'PY'
import json, sys
try:
    result = json.load(open(sys.argv[1], encoding='utf-8')).get("result", {})
except Exception:
    print("unparseable")
    raise SystemExit
print(result.get("status", "unknown") if isinstance(result, dict) else "unknown")
PY
}

json_token_id() {
  local response_file="$1"
  python3 - "${response_file}" <<'PY'
import json, re, sys
try:
    result = json.load(open(sys.argv[1], encoding='utf-8')).get("result", {})
except Exception:
    raise SystemExit
value = result.get("id", "") if isinstance(result, dict) else ""
if re.fullmatch(r"[0-9a-fA-F]{32}", str(value)):
    print(value)
PY
}

json_error_codes() {
  local response_file="$1"
  python3 - "${response_file}" <<'PY'
import json, sys
try:
    data = json.loads(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    print("unparseable-response")
    raise SystemExit
codes = []
for item in data.get("errors", []):
    if isinstance(item, dict) and item.get("code") is not None:
        codes.append(str(item["code"]))
print(",".join(codes) if codes else "none")
PY
}

json_account_ids() {
  local response_file="$1"
  python3 - "${response_file}" <<'PY'
import json, re, sys
try:
    data = json.loads(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    raise SystemExit
for item in data.get("result", []) if isinstance(data.get("result"), list) else []:
    if isinstance(item, dict) and re.fullmatch(r"[0-9a-fA-F]{32}", str(item.get("id", ""))):
        print(item["id"])
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
write_curl_config() {
  local config_file="$1"
  : >"${config_file}"
  chmod 600 "${config_file}"
  printf 'header = "Authorization: Bearer %s"\nheader = "Accept: application/json"\n' \
    "$(<"${cf_token_file}")" >"${config_file}"
}

verify_cloudflare_account_token() {
  local response_file="$1" config_file="$2" code success status
  code="$(safe_http_code "${response_file}" \
    --config "${config_file}" \
    "${CLOUDFLARE_API}/accounts/${cf_account_id}/tokens/verify")"
  success="$(json_success "${response_file}")"
  status="$(json_token_status "${response_file}")"
  if [[ "${code}" == "200" && "${success}" == "true" && "${status}" == "active" ]]; then
    printf 'Bootstrap Cloudflare account-token verification: PASS (HTTP 200, status=active)\n'
    return 0
  fi
  printf 'Bootstrap Cloudflare account-token verification: FAIL (HTTP %s, status=%s, error codes: %s)\n' \
    "${code}" "${status}" "$(json_error_codes "${response_file}")"
  return 1
}

discover_account() {
  local response_file="$1" config_file="$2" code identity
  if [[ "${cf_account_id}" =~ ^[0-9a-fA-F]{32}$ ]]; then
    code="$(safe_http_code "${response_file}" --config "${config_file}" \
      "${CLOUDFLARE_API}/accounts/${cf_account_id}")"
    identity="$(python3 - "${response_file}" <<'PY'
import json, re, sys
try:
    result = json.load(open(sys.argv[1], encoding='utf-8')).get("result", {})
except Exception:
    print("unparseable")
    raise SystemExit
if isinstance(result, dict):
    name = result.get("name")
    if isinstance(name, str):
        print(re.sub(r"[^A-Za-z0-9 ._-]", "?", name)[:120])
PY
    )"
    if [[ "${code}" == "200" && "$(json_success "${response_file}")" == "true" ]]; then
      printf 'Cloudflare account identity: PASS (configured account, name=%s)\n' "${identity:-unreported}"
      return 0
    fi
    printf 'Cloudflare account identity: FAIL (HTTP %s, error codes: %s)\n' \
      "${code}" "$(json_error_codes "${response_file}")"
    return 1
  fi
  printf 'Cloudflare account identity: FAIL (configured account ID is missing or invalid)\n'
  return 1
}

discover_r2() {
  local response_file="$1" config_file="$2" code success names
  code="$(safe_http_code "${response_file}" \
    --config "${config_file}" \
    "${CLOUDFLARE_API}/accounts/${cf_account_id}/r2/buckets")"
  success="$(json_success "${response_file}")"
  if [[ "${code}" == "200" && "${success}" == "true" ]]; then
    names="$(json_bucket_names "${response_file}")" || die "invalid R2 listing; target existence remains unknown"
    printf 'R2 bucket-list permission: PASS (HTTP 200)\n'
    if [[ -n "${names}" ]]; then
      printf 'R2 buckets:\n%s\n' "${names}"
    else
      printf 'R2 buckets: none\n'
    fi
    if printf '%s\n' "${names}" | grep -Fxq "${TARGET_BUCKET}"; then
      printf 'Target bucket %s exists: yes\n' "${TARGET_BUCKET}"
    else
      printf 'Target bucket %s exists: no\n' "${TARGET_BUCKET}"
    fi
    return 0
  fi
  printf 'R2 bucket-list permission: FAIL (HTTP %s, error codes: %s)\n' \
    "${code}" "$(json_error_codes "${response_file}")"
  printf 'R2 bucket-provisioning capability: NOT AVAILABLE FOR DISCOVERY\n'
  return 1
}

determine_bucket_create_capability() {
  local verify_file="$1" details_file="$2" config_file="$3" token_id code capability
  token_id="$(json_token_id "${verify_file}")"
  if [[ ! "${token_id}" =~ ^[0-9a-fA-F]{32}$ ]]; then
    printf 'R2 bucket-create capability: UNDETERMINED (token identifier unavailable; no write probe made)\n'
    return 0
  fi
  code="$(safe_http_code "${details_file}" --config "${config_file}" \
    "${CLOUDFLARE_API}/accounts/${cf_account_id}/tokens/${token_id}")"
  capability="$(python3 - "${details_file}" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    print("unparseable")
    raise SystemExit
found = False
for policy in data.get("result", {}).get("policies", []) if isinstance(data.get("result"), dict) else []:
    if policy.get("effect") != "allow":
        continue
    for group in policy.get("permission_groups", []):
        if group.get("name") == "Workers R2 Storage Write":
            found = True
print("sufficient" if found else "insufficient")
PY
  )"
  if [[ "${code}" == "200" && "$(json_success "${details_file}")" == "true" ]]; then
    if [[ "${capability}" == "sufficient" ]]; then
      printf 'R2 bucket-create capability: SUFFICIENT (explicit Workers R2 Storage Write policy; no create attempted)\n'
    else
      printf 'R2 bucket-create capability: INSUFFICIENT (no explicit Workers R2 Storage Write policy; no create attempted)\n'
    fi
  else
    printf 'R2 bucket-create capability: UNDETERMINED (token policy details unavailable; R2 list access does not prove create access; no write probe made)\n'
  fi
}

verify_latest_backup() {
  local latest sidecar checksum_output verify_output size
  latest="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'optibrain-backup-*.tar.gz' -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
  [[ -n "${latest}" ]] || die "no local OptiBrain backup archive found"
  sidecar="${latest}.sha256"
  [[ -f "${sidecar}" ]] || die "latest backup checksum sidecar is missing"
  size="$(stat -c '%s' "${latest}")"
  checksum_output="${tmp_dir}/checksum.txt"
  verify_output="${tmp_dir}/verify.txt"
  if sha256sum -c "${sidecar}" >"${checksum_output}" 2>&1; then
    printf 'Latest local backup checksum: PASS\n'
  else
    printf 'Latest local backup checksum: FAIL\n'
    return 1
  fi
  if "${BACKUP_SCRIPT}" --verify "${latest}" >"${verify_output}" 2>&1; then
    printf 'Latest local backup restore verification: PASS\n'
  else
    printf 'Latest local backup restore verification: FAIL\n'
    return 1
  fi
  printf 'Latest local backup: %s bytes\n' "${size}"
}

verify_runtime_health() {
  local enabled active response_file http_code
  enabled="$(systemctl is-enabled optibrain-backup.timer 2>/dev/null || true)"
  active="$(systemctl is-active optibrain-backup.timer 2>/dev/null || true)"
  printf 'optibrain-backup.timer: enabled=%s active=%s\n' "${enabled}" "${active}"

  response_file="${tmp_dir}/health.json"
  http_code="$(curl --silent --show-error --max-time 20 -o "${response_file}" -w '%{http_code}' \
    'http://127.0.0.1:8100/health' 2>/dev/null || printf '000')"
  python3 - "${http_code}" "${response_file}" <<'PY'
import json, sys
code, path = sys.argv[1:]
try:
    data = json.loads(open(path, encoding="utf-8").read())
except Exception:
    data = {}
status = data.get("status") if isinstance(data, dict) else None
version = data.get("version") if isinstance(data, dict) else None
if code == "200" and status == "ok":
    print(f"Production workflow API: PASS (HTTP 200, status={status}, version={version})")
else:
    print(f"Production workflow API: FAIL (HTTP {code})")
    raise SystemExit(1)
PY
}

main() {
require_root
[[ -r "${ENV_FILE}" ]] || die "Cloudflare environment file is not readable"
[[ -r "${BOOTSTRAP_TOKEN_FILE}" ]] || die "${BOOTSTRAP_TOKEN_FILE} is not readable"
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
command -v systemctl >/dev/null 2>&1 || die "systemctl is required"

tmp_dir="$(mktemp -d)"
chmod 700 "${tmp_dir}"
cf_account_id="$(read_env_value CLOUDFLARE_ACCOUNT_ID)"
[[ -n "${cf_account_id}" ]] || die "CLOUDFLARE_ACCOUNT_ID is missing from protected configuration"
[[ "${cf_account_id}" =~ ^[0-9a-fA-F]{32}$ ]] || die "CLOUDFLARE_ACCOUNT_ID is invalid"
cf_token_file="${BOOTSTRAP_TOKEN_FILE}"
[[ -s "${cf_token_file}" ]] || die "bootstrap account token is empty"

auth_response="${tmp_dir}/token-verify.json"
account_response="${tmp_dir}/accounts.json"
config_file="${tmp_dir}/curl.conf"
write_curl_config "${config_file}"
r2_response="${tmp_dir}/r2-buckets.json"
token_details_response="${tmp_dir}/token-details.json"

verify_cloudflare_account_token "${auth_response}" "${config_file}" || exit 1
discover_account "${account_response}" "${config_file}" || exit 1
discover_r2 "${r2_response}" "${config_file}" || exit 1
determine_bucket_create_capability "${auth_response}" "${token_details_response}" "${config_file}"
verify_latest_backup
verify_runtime_health

printf 'Read-only discovery complete; no Cloudflare or production mutations performed.\n'

}
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
