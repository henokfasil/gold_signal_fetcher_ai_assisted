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
# Opt-in rules-only PAPER track: with no validated ML artifact, approve on the
# SMC score (0-100) at/above this threshold instead of blocking every candidate.
# Paper-only (PAPER_TRADING=true above; no broker-order code exists). Unset this
# to restore the default ML-mandatory research behavior.
export SMC_PAPER_THRESHOLD="${SMC_PAPER_THRESHOLD:-70}"
export LOG_FILE

# flock releases automatically on exit and cannot leave a stale PID lock.
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "System C scan already running; skipped" >> "${LOG_FILE}"
  exit 0
fi

if [[ "${PRICE_DATA_PROVIDER:-dukascopy}" == "tradingview" ]]; then
  COLLECTOR="/usr/local/lib/gold-signal-fetcher/collect_tradingview_snapshot.py"
  SNAPSHOT="${TRADINGVIEW_SNAPSHOT_PATH:-/tmp/tradingview_snapshot.json}"
  if [[ ! -x "${COLLECTOR}" ]]; then
    echo "TradingView collector missing: ${COLLECTOR}" >> "${LOG_FILE}"
    exit 1
  fi
  if ! runuser -u tvfetcher -- env \
      TRADINGVIEW_SNAPSHOT_PATH="${SNAPSHOT}" \
      TRADINGVIEW_MCP_ROOT="${TRADINGVIEW_MCP_ROOT:-/opt/tradingview-mcp}" \
      /usr/bin/python3 "${COLLECTOR}" >> "${LOG_FILE}" 2>&1; then
    echo "TradingView collection failed; paper scan aborted" >> "${LOG_FILE}"
    exit 1
  fi
elif [[ "${PRICE_DATA_PROVIDER:-dukascopy}" == "dukascopy" ]]; then
  COLLECTOR="/usr/local/lib/gold-signal-fetcher/collect_dukascopy_snapshot.py"
  SNAPSHOT="${DUKASCOPY_SNAPSHOT_PATH:-/tmp/dukascopy_snapshot.json}"
  if [[ ! -x "${COLLECTOR}" ]]; then
    echo "Dukascopy collector missing: ${COLLECTOR}" >> "${LOG_FILE}"
    exit 1
  fi
  if ! DUKASCOPY_SNAPSHOT_PATH="${SNAPSHOT}" \
      "${PYTHON_BIN}" "${COLLECTOR}" >> "${LOG_FILE}" 2>&1; then
    echo "Dukascopy collection failed; paper scan aborted" >> "${LOG_FILE}"
    exit 1
  fi

  # Prospective context is deliberately non-blocking and observational.  A
  # failure is journalled as missing context by the orchestrator and cannot
  # change candidate approval, Claude, Telegram or paper positions.
  CONTEXT_COLLECTOR="/usr/local/lib/gold-signal-fetcher/collect_gold_context_snapshot.py"
  CONTEXT_SNAPSHOT="${GOLD_CONTEXT_SNAPSHOT_PATH:-/tmp/gold_context_snapshot.json}"
  if [[ ! -x "${CONTEXT_COLLECTOR}" ]]; then
    echo "Gold-context collector missing; candidate context will be recorded missing" >> "${LOG_FILE}"
  elif ! GOLD_CONTEXT_SNAPSHOT_PATH="${CONTEXT_SNAPSHOT}" \
      FORWARD_CONTEXT_CONFIG="${FORWARD_CONTEXT_CONFIG:-${PROJECT_DIR}/config/forward_context_observation_v1.json}" \
      "${PYTHON_BIN}" "${CONTEXT_COLLECTOR}" >> "${LOG_FILE}" 2>&1; then
    echo "Gold-context collection failed; candidate context will be recorded missing" >> "${LOG_FILE}"
  fi

  # Derive the runtime macro snapshot from the context proxies so the Claude
  # reviewer has point-in-time DXY / real-yield-proxy / VIX context. Non-blocking:
  # if it is not written, macro is simply reported unavailable, never fabricated.
  if ! "${PYTHON_BIN}" -m ops.collect_macro_snapshot >> "${LOG_FILE}" 2>&1; then
    echo "Macro snapshot derivation failed; macro will be recorded unavailable" >> "${LOG_FILE}"
  fi

  # The former Yahoo-price "sentiment" observer is deliberately not run here.
  # It did not implement its registered news/sentiment source contract and had
  # no valid historical comparison. A replacement requires a new hash-locked,
  # point-in-time contract before prospective collection begins.
fi

if ! "${PYTHON_BIN}" "${PROJECT_DIR}/main_orchestrator.py" >> "${LOG_FILE}" 2>&1; then
  echo "Paper orchestrator failed" >> "${LOG_FILE}"
  exit 1
fi

# Reconcile the append-only research evidence after each scan.  A degraded
# audit is visible on the dashboard and in logs but cannot retroactively alter
# the completed candidate decision.
if ! EVIDENCE_INTEGRITY_STATUS_PATH="${EVIDENCE_INTEGRITY_STATUS_PATH:-${PROJECT_DIR}/data/evidence_integrity_status.json}" \
    "${PYTHON_BIN}" -m ops.check_evidence_integrity >> "${LOG_FILE}" 2>&1; then
  echo "Evidence-integrity monitor reports DEGRADED; paper decisions remain unchanged" >> "${LOG_FILE}"
fi
