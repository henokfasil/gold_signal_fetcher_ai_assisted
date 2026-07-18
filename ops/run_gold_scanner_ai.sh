#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${GOLD_SYSTEM_C_DIR:-/root/gold_signal_fetcher_ai_assisted}"
PYTHON_BIN="${PROJECT_DIR}/venv/bin/python"
LOCK_FILE="${PROJECT_DIR}/data/scanner.lock"
LOG_FILE="${LOG_FILE:-${PROJECT_DIR}/logs/gold_scanner_ai.log}"

mkdir -p "${PROJECT_DIR}/data" "${PROJECT_DIR}/logs"
cd "${PROJECT_DIR}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "System C environment missing: ${PYTHON_BIN}" >&2
  exit 1
fi

set -a
source "${PROJECT_DIR}/.env"
set +a
export PAPER_TRADING=true
export LOG_FILE

# flock releases automatically on exit and cannot leave a stale PID lock.
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "System C scan already running; skipped" >> "${LOG_FILE}"
  exit 0
fi

exec "${PYTHON_BIN}" "${PROJECT_DIR}/main_orchestrator.py" >> "${LOG_FILE}" 2>&1
