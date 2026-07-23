#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${GOLD_SYSTEM_C_DIR:-/root/gold_signal_fetcher_ai_assisted}"
PYTHON_BIN="${PROJECT_DIR}/venv/bin/python"
LOCK_FILE="${PROJECT_DIR}/data/event_concordance_daily.lock"
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

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "Event concordance daily job already running; skipped" >> "${LOG_FILE}"
  exit 0
fi

"${PYTHON_BIN}" -m ops.collect_event_concordance_reference \
  >> "${LOG_FILE}" 2>&1

"${PYTHON_BIN}" -m ops.check_event_feature_concordance >> "${LOG_FILE}" 2>&1
