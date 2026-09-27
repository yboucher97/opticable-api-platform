#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${repo}/ops/backup/${1:-optibrain-phase2a-r2-bootstrap.sh}"
tmp_dir="$(mktemp -d)"
check() {
  local payload="$1" expected="$2" result
  printf '%s\n' "${payload}" >"${tmp_dir}/response.json"
  result="$(json_bucket_names "${tmp_dir}/response.json")"
  [[ ${result} == "${expected}" ]]
}
check '{"success":true,"result":{"buckets":[{"name":"optibrain-recovery-prod"}]}}' 'optibrain-recovery-prod'
check '{"success":true,"result":{"buckets":[]}}' ''
for payload in '{bad' '{"success":false}' '{"success":true,"result":[]}' '{"success":true,"result":{"buckets":[{}]}}'; do
  printf '%s\n' "${payload}" >"${tmp_dir}/response.json"
  if json_bucket_names "${tmp_dir}/response.json" >/dev/null 2>&1; then
    printf 'Invalid listing accepted\n' >&2; exit 1
  fi
done
# A network/listing failure must propagate through the same capture used by main.
if declare -F list_buckets >/dev/null; then
http() { printf '503'; }
ACCOUNT_ID=fixture
if bucket_names="$(list_buckets 2>/dev/null)"; then
  printf 'Failed listing accepted\n' >&2; exit 1
fi
fi
printf 'Phase 2A bucket listing regression tests passed\n'
