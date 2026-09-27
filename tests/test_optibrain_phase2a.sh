#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
/usr/bin/python3 "${repo}/tests/test_optibrain_phase2a.py"
bash -n "${repo}/ops/backup/optibrain-phase2a-upload.sh"
systemd-analyze verify "${repo}/ops/backup/optibrain-phase2a-upload.service" "${repo}/ops/backup/optibrain-phase2a-upload.timer"
