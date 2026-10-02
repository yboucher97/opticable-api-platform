#!/usr/bin/env bash
# DEPRECATED Phase 14: retained historical implementation; direct execution refused.
printf '%s\n' 'DEPRECATED: use the reviewed /usr/local/sbin/opticable-api-deploy-root or current recovery runbook.' >&2
exit 64
set -euo pipefail

echo "This app is now installed through the monorepo root installer."
echo "Use:"
echo "  sudo bash <(curl -fsSL https://raw.githubusercontent.com/yboucher97/opticable-api-platform/main/install.sh)"
exit 1
