#!/usr/bin/env bash
set -Eeuo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ops/backup/optibrain-phase2a-r2-bootstrap.sh"
tmp="$(mktemp -d)"
trap 'rm -rf -- "${tmp}"' EXIT
mkdir -p "${tmp}/bin" "${tmp}/backup" "${tmp}/etc"

archive="${tmp}/backup/optibrain-backup-20260927T010000Z.tar.gz"
printf 'fixture backup\n' >"${archive}"
sha256sum "${archive}" >"${archive}.sha256"
printf 'age1testrecipient\n' >"${tmp}/etc/recipient"
printf 'test-token-not-used-by-health-fixture\n' >"${tmp}/token"
printf '# account intentionally omitted: healthy health must pass before later validation\n' >"${tmp}/env"
cat >"${tmp}/verify-backup" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat >"${tmp}/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
case "${2:-}" in
  is-enabled) printf 'enabled\n' ;;
  is-active) printf 'active\n' ;;
  *) exit 1 ;;
esac
EOF
cat >"${tmp}/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
output=''
while (($#)); do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    -w) shift 2 ;;
    *) shift ;;
  esac
done
case "${HEALTH_CASE}" in
  healthy) printf '{"status":"ok","version":"1.7.0"}\n' >"${output}"; printf '200\n' ;;
  curl_failure) exit 7 ;;
  http_non_200) printf '{"status":"ok","version":"1.7.0"}\n' >"${output}"; printf '503\n' ;;
  missing_file) rm -f -- "${output}"; printf '200\n' ;;
  malformed_json) printf '{not-json\n' >"${output}"; printf '200\n' ;;
  status_not_ok) printf '{"status":"degraded","version":"1.7.0"}\n' >"${output}"; printf '200\n' ;;
  *) exit 99 ;;
esac
EOF
chmod 700 "${tmp}/bin/systemctl" "${tmp}/bin/curl" "${tmp}/verify-backup"

run_case() {
  local name="$1" expected="$2" output status case_dir
  case_dir="${tmp}/${name}"
  mkdir -p "${case_dir}"
  set +e
  output="$({
    PATH="${tmp}/bin:${PATH}" \
      HEALTH_CASE="${name}" \
      bash -c 'source "$1"; tmp_dir="$2"; check_production_health "$2/health.json"' \
        -- "${script}" "${case_dir}"
  } 2>&1)"
  status=$?
  set -e
  [[ ${status} -ne 0 ]] || { printf 'case %s unexpectedly passed\n%s\n' "${name}" "${output}" >&2; return 1; }
  [[ ${output} == *"${expected}"* ]] || { printf 'case %s missing expected output: %s\n%s\n' "${name}" "${expected}" "${output}" >&2; return 1; }
}

healthy_dir="${tmp}/healthy"
mkdir -p "${healthy_dir}"
healthy_output="$(PATH="${tmp}/bin:${PATH}" HEALTH_CASE=healthy \
  bash -c 'source "$1"; tmp_dir="$2"; check_production_health "$2/health.json"' \
  -- "${script}" "${healthy_dir}")"
[[ ${healthy_output} == 'Production workflow API: PASS (HTTP 200, status=ok, version=1.7.0)' ]]

run_case curl_failure 'curl exit 7'
run_case http_non_200 'production health check failed'
run_case missing_file 'response file missing'
run_case malformed_json 'production health check failed'
run_case status_not_ok 'production health check failed'

printf 'Phase 2A R2 health regression tests passed\n'
