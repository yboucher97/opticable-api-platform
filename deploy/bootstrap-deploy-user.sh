#!/usr/bin/env bash
set -euo pipefail

DEPLOY_USER="${OPTICABLE_DEPLOY_USER:-opticable-deploy}"
DEPLOY_PUBLIC_KEY="${OPTICABLE_DEPLOY_PUBLIC_KEY:-${1:-}}"
COMMAND_WRAPPER="/usr/local/sbin/opticable-api-deploy-command"
ROOT_WRAPPER="/usr/local/sbin/opticable-api-deploy-root"
SUDOERS_FILE="/etc/sudoers.d/opticable-api-deploy"

fail() {
  echo "[opticable-deploy-bootstrap] ERROR: $*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "Run as root."
[[ -n "${DEPLOY_PUBLIC_KEY}" ]] || fail "Provide the dedicated deploy PUBLIC key as the first argument or OPTICABLE_DEPLOY_PUBLIC_KEY."
[[ "${DEPLOY_PUBLIC_KEY}" =~ ^(ssh-ed25519|ecdsa-sha2-nistp256|sk-ssh-ed25519@openssh.com)[[:space:]] ]] \
  || fail "Deploy public key must be an SSH public key."

if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "${DEPLOY_USER}"
fi

cat >"${COMMAND_WRAPPER}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

original="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "${original}" =~ ^deploy[[:space:]]+([0-9a-f]{40})$ ]]; then
  echo "Only 'deploy <40-hex-main-commit-sha>' is permitted." >&2
  exit 64
fi

sha="${BASH_REMATCH[1]}"
exec sudo -n /usr/local/sbin/opticable-api-deploy-root "${sha}"
EOF

cat >"${ROOT_WRAPPER}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

sha="${1:-}"
if [[ ! "${sha}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid deployment SHA." >&2
  exit 64
fi

tmp="$(mktemp /var/tmp/opticable-api-deploy.XXXXXX.sh)"
trap 'rm -f "${tmp}"' EXIT
url="https://raw.githubusercontent.com/yboucher97/opticable-api-platform/${sha}/deploy/update-production.sh"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "${url}" -o "${tmp}"
chmod 700 "${tmp}"
exec bash "${tmp}" "${sha}"
EOF

chown root:root "${COMMAND_WRAPPER}" "${ROOT_WRAPPER}"
chmod 755 "${COMMAND_WRAPPER}" "${ROOT_WRAPPER}"

cat >"${SUDOERS_FILE}" <<EOF
${DEPLOY_USER} ALL=(root) NOPASSWD: ${ROOT_WRAPPER} *
EOF
chmod 440 "${SUDOERS_FILE}"
visudo -cf "${SUDOERS_FILE}" >/dev/null

home_dir="$(getent passwd "${DEPLOY_USER}" | cut -d: -f6)"
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${home_dir}/.ssh"

key_material="$(printf '%s\n' "${DEPLOY_PUBLIC_KEY}" | awk '{print $1" "$2}')"
authorized_line="command=\"${COMMAND_WRAPPER}\",no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc,no-X11-forwarding ${key_material}"

printf '%s\n' "${authorized_line}" >"${home_dir}/.ssh/authorized_keys"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${home_dir}/.ssh/authorized_keys"
chmod 600 "${home_dir}/.ssh/authorized_keys"

echo "Restricted deployment user configured: ${DEPLOY_USER}"
echo "This key cannot open a shell; it can only request: deploy <40-hex-main-commit-sha>"
echo
echo "For the GitHub OPTICABLE_API_DEPLOY_KNOWN_HOSTS secret, copy a trusted host-key line."
echo "On this server, one can be generated from the local SSH host public key, for example:"
echo "  printf 'api01.opticable.ca %s\\n' \"\$(cut -d' ' -f1-2 /etc/ssh/ssh_host_ed25519_key.pub)\""
