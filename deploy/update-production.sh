#!/usr/bin/env bash
set -euo pipefail

APP_NAME="opticable-api-platform"
TARGET_SHA="${1:-}"
INSTALL_DIR="${OPTICABLE_API_INSTALL_DIR:-/opt/opticable-api-platform}"
WORKFLOW_APP_DIR="${INSTALL_DIR}/apps/workflow-api"
WORKFLOW_SERVICE_NAME="${OPTICABLE_WORKFLOW_SERVICE_NAME:-opticable-workflow-api}"
WORKFLOW_PORT="${OPTICABLE_WORKFLOW_PORT:-8100}"
LOCAL_HEALTH_URL="${OPTICABLE_WORKFLOW_HEALTH_URL:-http://127.0.0.1:${WORKFLOW_PORT}/health}"
LOCK_FILE="${OPTICABLE_DEPLOY_LOCK_FILE:-/var/lock/opticable-api-platform-deploy.lock}"
STAGE_ROOT="${OPTICABLE_DEPLOY_STAGE_ROOT:-/var/tmp/opticable-api-platform-deploy}"
HEALTH_ATTEMPTS="${OPTICABLE_DEPLOY_HEALTH_ATTEMPTS:-20}"
HEALTH_DELAY_SECONDS="${OPTICABLE_DEPLOY_HEALTH_DELAY_SECONDS:-2}"

log() {
  printf '[%s-deploy] %s\n' "${APP_NAME}" "$*"
}

fail() {
  printf '[%s-deploy] ERROR: %s\n' "${APP_NAME}" "$*" >&2
  exit 1
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "Deployment must run as root (or through passwordless sudo)."
  fi
}

health_check() {
  local attempts="${1:-${HEALTH_ATTEMPTS}}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if systemctl is-active --quiet "${WORKFLOW_SERVICE_NAME}" \
      && curl -fsS --max-time 5 "${LOCAL_HEALTH_URL}" >/dev/null; then
      return 0
    fi
    sleep "${HEALTH_DELAY_SECONDS}"
  done
  return 1
}

install_requirements() {
  local app_dir="$1"
  local venv="$2"
  python3 -m venv "${venv}"
  "${venv}/bin/python" -m pip install --disable-pip-version-check --no-cache-dir --upgrade pip >/dev/null
  "${venv}/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -r "${app_dir}/requirements.txt" >/dev/null
}

validate_release() {
  local release_dir="$1"
  local app_dir="${release_dir}/apps/workflow-api"
  local venv="${release_dir}/.validate-venv"

  log "Validating target release before touching production"
  install_requirements "${app_dir}" "${venv}"
  (
    cd "${app_dir}"
    "${venv}/bin/python" -m compileall -q workflow tests
    "${venv}/bin/python" -m unittest discover -s tests -v
  )
}

ensure_live_venv() {
  if [[ ! -x "${WORKFLOW_APP_DIR}/.venv/bin/python" ]]; then
    log "Creating production workflow virtual environment"
    python3 -m venv "${WORKFLOW_APP_DIR}/.venv"
  fi
  "${WORKFLOW_APP_DIR}/.venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir --upgrade pip >/dev/null
  "${WORKFLOW_APP_DIR}/.venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -r "${WORKFLOW_APP_DIR}/requirements.txt" >/dev/null
}

rollback() {
  local previous_sha="$1"
  log "Rolling back production code to ${previous_sha}"
  git -C "${INSTALL_DIR}" reset --hard "${previous_sha}"
  ensure_live_venv
  systemctl restart "${WORKFLOW_SERVICE_NAME}"
  if health_check; then
    log "Rollback health check succeeded"
    return 0
  fi
  log "Rollback health check FAILED"
  return 1
}

main() {
  require_root
  [[ -n "${TARGET_SHA}" ]] || fail "Target commit SHA is required."
  [[ -d "${INSTALL_DIR}/.git" ]] || fail "Expected Git checkout at ${INSTALL_DIR}."
  [[ -f "${WORKFLOW_APP_DIR}/requirements.txt" ]] || fail "Workflow API not found at ${WORKFLOW_APP_DIR}."
  git config --global --add safe.directory "${INSTALL_DIR}"

  mkdir -p "$(dirname "${LOCK_FILE}")" "${STAGE_ROOT}"
  exec 9>"${LOCK_FILE}"
  flock -n 9 || fail "Another deployment is already running."

  if [[ -n "$(git -C "${INSTALL_DIR}" status --porcelain --untracked-files=no)" ]]; then
    fail "Production checkout has modified tracked files. Refusing to overwrite local changes."
  fi

  local previous_sha
  previous_sha="$(git -C "${INSTALL_DIR}" rev-parse HEAD)"
  log "Current production commit: ${previous_sha}"
  log "Requested target commit:   ${TARGET_SHA}"

  git -C "${INSTALL_DIR}" fetch --prune origin main
  git -C "${INSTALL_DIR}" cat-file -e "${TARGET_SHA}^{commit}" 2>/dev/null \
    || fail "Target SHA ${TARGET_SHA} is not available after fetch."
  git -C "${INSTALL_DIR}" merge-base --is-ancestor "${TARGET_SHA}" origin/main \
    || fail "Target SHA ${TARGET_SHA} is not an ancestor of origin/main."

  if [[ "${previous_sha}" == "${TARGET_SHA}" ]]; then
    log "Target is already deployed; verifying health only"
    health_check || fail "Service is not healthy even though target commit is already deployed."
    exit 0
  fi

  local stage_dir="${STAGE_ROOT}/${TARGET_SHA}"
  rm -rf "${stage_dir}"
  git -C "${INSTALL_DIR}" worktree prune
  git -C "${INSTALL_DIR}" worktree add --detach "${stage_dir}" "${TARGET_SHA}" >/dev/null

  cleanup() {
    rm -rf "${stage_dir}/.validate-venv" 2>/dev/null || true
    git -C "${INSTALL_DIR}" worktree remove --force "${stage_dir}" >/dev/null 2>&1 || true
    rm -rf "${stage_dir}" 2>/dev/null || true
  }
  trap cleanup EXIT

  validate_release "${stage_dir}"

  log "Validation passed; switching production checkout"
  git -C "${INSTALL_DIR}" reset --hard "${TARGET_SHA}"

  if ! ensure_live_venv; then
    log "Dependency installation failed after switch"
    rollback "${previous_sha}" || true
    fail "Deployment failed while installing production dependencies."
  fi

  log "Restarting ${WORKFLOW_SERVICE_NAME}"
  if ! systemctl restart "${WORKFLOW_SERVICE_NAME}"; then
    rollback "${previous_sha}" || true
    fail "Service restart failed."
  fi

  if ! health_check; then
    log "New release failed health checks"
    rollback "${previous_sha}" || fail "New release failed and rollback also failed. Manual intervention required."
    fail "New release failed health checks and was rolled back."
  fi

  log "Deployment successful: ${TARGET_SHA}"
}

main "$@"
