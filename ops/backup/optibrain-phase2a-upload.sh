#!/usr/bin/env bash
set -Eeuo pipefail
# Total runtime bound also applies to an operator's manual invocation.
exec timeout --signal=TERM 45m /usr/bin/python3 "$(dirname "${BASH_SOURCE[0]}")/optibrain-phase2a-upload.py" "$@"
