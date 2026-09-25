#!/usr/bin/env bash
set -euo pipefail

REPO="yboucher97/opticable-api-platform"
ENV_FILE="/etc/opticable-workflow-api.env"
DEPLOY_KEY="/etc/optibrain/github-actions-deploy-ed25519"
CONTROL_KEY_FILE="/etc/optibrain/control-plane.key"
APP_ROOT="/opt/opticable-api-platform"
PYTHON="${APP_ROOT}/apps/workflow-api/.venv/bin/python"
DEPLOY_HOST="${OPTICABLE_DEPLOY_HOST:-148.113.249.7}"
PUBLIC_BASE_URL="${OPTICABLE_PUBLIC_BASE_URL:-https://optibrain.opticable.ca}"

fail() {
  echo "[opticable-ci-bootstrap] ERROR: $*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "Run with sudo/root."
[[ -r "${ENV_FILE}" ]] || fail "Missing ${ENV_FILE}."
[[ -x "${PYTHON}" ]] || fail "Missing workflow Python venv: ${PYTHON}."
[[ -x "${APP_ROOT}/deploy/bootstrap-deploy-user.sh" ]] || fail "Missing deploy/bootstrap-deploy-user.sh."

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

for name in GITHUB_APP_ID GITHUB_APP_INSTALLATION_ID GITHUB_APP_PRIVATE_KEY_PATH CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID SITE_WORKFLOW_API_KEY; do
  [[ -n "${!name:-}" ]] || fail "Missing required environment variable: ${name}"
done
[[ -r "${GITHUB_APP_PRIVATE_KEY_PATH}" ]] || fail "GitHub App private key is not readable: ${GITHUB_APP_PRIVATE_KEY_PATH}"

install -d -m 750 -o root -g opticable-workflow-api /etc/optibrain

# Verify that the GitHub App can manage repository Actions secrets before changing SSH state.
"${PYTHON}" - <<'PY'
import json, os, time
from pathlib import Path
import httpx, jwt

app_id = os.environ["GITHUB_APP_ID"]
installation_id = os.environ["GITHUB_APP_INSTALLATION_ID"]
private_key = Path(os.environ["GITHUB_APP_PRIVATE_KEY_PATH"]).read_text()
now = int(time.time())
token = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id}, private_key, algorithm="RS256")
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
}
with httpx.Client(timeout=30) as client:
    resp = client.post(f"https://api.github.com/app/installations/{installation_id}/access_tokens", headers=headers)
    resp.raise_for_status()
    installation_token = resp.json()["token"]
    headers["Authorization"] = f"Bearer {installation_token}"
    check = client.get(
        "https://api.github.com/repos/yboucher97/opticable-api-platform/actions/secrets/public-key",
        headers=headers,
    )
    if check.status_code != 200:
        raise SystemExit(
            "GitHub App cannot manage Actions secrets yet. "
            "Set Repository permissions -> Secrets to Read and write, approve the permission change, then rerun this script. "
            f"GitHub returned HTTP {check.status_code}."
        )
print("GitHub App Actions-secret permission: OK")
PY

if [[ ! -s "${CONTROL_KEY_FILE}" ]]; then
  umask 077
  openssl rand -hex 32 > "${CONTROL_KEY_FILE}"
fi
chmod 600 "${CONTROL_KEY_FILE}"

if [[ ! -s "${DEPLOY_KEY}" || ! -s "${DEPLOY_KEY}.pub" ]]; then
  rm -f "${DEPLOY_KEY}" "${DEPLOY_KEY}.pub"
  ssh-keygen -q -t ed25519 -N "" -C "opticable-github-actions-deploy" -f "${DEPLOY_KEY}"
fi
chmod 600 "${DEPLOY_KEY}"
chmod 644 "${DEPLOY_KEY}.pub"

"${APP_ROOT}/deploy/bootstrap-deploy-user.sh" "$(cat "${DEPLOY_KEY}.pub")"

host_key="$(cut -d' ' -f1-2 /etc/ssh/ssh_host_ed25519_key.pub)"
[[ -n "${host_key}" ]] || fail "Could not read local SSH Ed25519 host key."
known_hosts_line="${DEPLOY_HOST} ${host_key}"

# PyNaCl is used only for GitHub's required sealed-box encryption of repository secrets.
"${PYTHON}" -m pip install --quiet "PyNaCl>=1.5,<2"

export OPTICABLE_BOOTSTRAP_DEPLOY_KEY="${DEPLOY_KEY}"
export OPTICABLE_BOOTSTRAP_CONTROL_KEY_FILE="${CONTROL_KEY_FILE}"
export OPTICABLE_BOOTSTRAP_KNOWN_HOSTS="${known_hosts_line}"
export OPTICABLE_BOOTSTRAP_DEPLOY_HOST="${DEPLOY_HOST}"
export OPTICABLE_BOOTSTRAP_PUBLIC_BASE_URL="${PUBLIC_BASE_URL}"

"${PYTHON}" - <<'PY'
import base64
import os
import time
from pathlib import Path

import httpx
import jwt
from nacl import public

repo = "yboucher97/opticable-api-platform"
app_id = os.environ["GITHUB_APP_ID"]
installation_id = os.environ["GITHUB_APP_INSTALLATION_ID"]
private_key = Path(os.environ["GITHUB_APP_PRIVATE_KEY_PATH"]).read_text()
now = int(time.time())
app_jwt = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id}, private_key, algorithm="RS256")

headers = {
    "Authorization": f"Bearer {app_jwt}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
}
with httpx.Client(timeout=30) as client:
    token_resp = client.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers=headers,
    )
    token_resp.raise_for_status()
    installation_token = token_resp.json()["token"]
    headers["Authorization"] = f"Bearer {installation_token}"

    key_resp = client.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers=headers,
    )
    key_resp.raise_for_status()
    key_data = key_resp.json()
    public_key = public.PublicKey(base64.b64decode(key_data["key"]))
    sealed_box = public.SealedBox(public_key)

    secrets = {
        "CLOUDFLARE_API_TOKEN": os.environ["CLOUDFLARE_API_TOKEN"],
        "CLOUDFLARE_ACCOUNT_ID": os.environ["CLOUDFLARE_ACCOUNT_ID"],
        "OPTICABLE_CONTROL_PLANE_API_KEY": Path(os.environ["OPTICABLE_BOOTSTRAP_CONTROL_KEY_FILE"]).read_text().strip(),
        "OPTICABLE_CORE_API_KEY": os.environ["SITE_WORKFLOW_API_KEY"],
        "OPTICABLE_API_DEPLOY_HOST": os.environ["OPTICABLE_BOOTSTRAP_DEPLOY_HOST"],
        "OPTICABLE_API_DEPLOY_SSH_KEY": Path(os.environ["OPTICABLE_BOOTSTRAP_DEPLOY_KEY"]).read_text(),
        "OPTICABLE_API_DEPLOY_KNOWN_HOSTS": os.environ["OPTICABLE_BOOTSTRAP_KNOWN_HOSTS"],
        "OPTICABLE_API_DEPLOY_PORT": "22",
        "OPTICABLE_API_PUBLIC_BASE_URL": os.environ["OPTICABLE_BOOTSTRAP_PUBLIC_BASE_URL"],
    }

    for name, value in secrets.items():
        encrypted = base64.b64encode(sealed_box.encrypt(value.encode())).decode()
        response = client.put(
            f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": key_data["key_id"]},
        )
        if response.status_code not in (201, 204):
            raise SystemExit(f"Failed to set GitHub secret {name}: HTTP {response.status_code}")

print(f"Published {len(secrets)} GitHub Actions secrets without exposing their values.")
PY

echo "[opticable-ci-bootstrap] SUCCESS"
echo "GitHub Actions can now deploy both the API platform and durable Cloudflare control plane."
echo "No secret values were printed."
