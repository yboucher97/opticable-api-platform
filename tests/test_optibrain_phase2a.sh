#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
/usr/bin/python3 "${repo}/tests/test_optibrain_phase2a.py"
bash -n "${repo}/ops/backup/optibrain-phase2a-upload.sh"
# Static unit validation also works in CI without a production runtime install.
unit_dir=$(mktemp -d)
trap 'rm -rf -- "${unit_dir}"' EXIT
sed 's|^ExecStart=.*|ExecStart=/usr/bin/true|' "${repo}/ops/backup/optibrain-phase2a-upload.service" >"${unit_dir}/optibrain-phase2a-upload.service"
cp "${repo}/ops/backup/optibrain-phase2a-upload.timer" "${unit_dir}/"
systemd-analyze verify "${unit_dir}/optibrain-phase2a-upload.service" "${unit_dir}/optibrain-phase2a-upload.timer"
# Deployment separately verifies the installed units and their real executable.
