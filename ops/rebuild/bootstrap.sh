#!/usr/bin/env bash
set -Eeuo pipefail
# Run from the exact reviewed recovery-toolchain checkout. No remote root pipe.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec /usr/bin/python3 -B "${SCRIPT_DIR}/cli.py" "$@"
