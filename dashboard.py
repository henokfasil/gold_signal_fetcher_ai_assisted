"""Unified SMC + ML + Claude paper-research dashboard."""

import json
import logging
import math
import os
from statistics import median
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from flask import Flask, render_template_string

from agent.gold_context_snapshot import (
    CONTEXT_NAMES,
    load_forward_context_contract,
    load_validated_context_snapshot,
)
from agent.evidence_integrity import build_evidence_integrity_report
from agent.event_feature_concordance import (
    event_feature_shadow_registration_eligible,
    load_event_feature_concordance_contract,
)
from agent.forward_event_journal import (
    EVENT_COLUMNS,
    SCAN_COLUMNS,
    load_forward_event_contract,
)
from agent.liquidity_manager import is_market_closed
from config import settings

app = Flask(__name__)
logger = logging.getLogger(__name__)
STARTING_CAPITAL = settings.PAPER_ACCOUNT_SIZE
EXPECTED_CADENCE_SECONDS = {"1W": 604800, "1D": 86400, "4H": 14400,
                            "1H": 3600, "15M": 900}


def load_trades(csv_path):
    path = Path(csv_path)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path).fillna("")
    except (OSError, pd.errors.ParserError):
        return pd.DataFrame()


def calculate_metrics(csv_path):
    """Calculate unified paper-candidate and approved-trade metrics."""
    frame = load_trades(csv_path)
    empty = {
        "status": "Collecting", "starting_capital": f"${STARTING_CAPITAL:,.2f}",
        "current_capital": f"${STARTING_CAPITAL:,.2f}", "total_profit": "$0.00",
        "return_pct": "0.00%", "signals": 0, "candidates": 0, "approved": 0,
        "rejected": 0, "open": 0, "wins": 0, "losses": 0, "expired": 0,
        "win_rate": "0.0%", "profit_factor": "0.00", "max_drawdown": "0.00%",
        "buys": 0, "sells": 0, "total_pnl": "$0.00",
    }
    if frame.empty:
        return empty

    status = frame.get("status", pd.Series("", index=frame.index)).astype(str).str.upper()
    decision = frame.get("decision", pd.Series("", index=frame.index)).astype(str).str.upper()
    direction = frame.get("direction", pd.Series("", index=frame.index)).astype(str).str.upper()
    pnl = pd.to_numeric(frame.get("pnl_usd", pd.Series(0, index=frame.index)), errors="coerce").fillna(0)
    approved_mask = decision.eq("APPROVE") | status.isin(["OPEN", "WIN", "LOSS", "EXPIRED"])
    closed_mask = status.isin(["WIN", "LOSS", "EXPIRED"])
    resolved_mask = status.isin(["WIN", "LOSS"])
    wins, losses = int(status.eq("WIN").sum()), int(status.eq("LOSS").sum())
    gross_win = float(pnl[(pnl > 0) & closed_mask].sum())
    gross_loss = abs(float(pnl[(pnl < 0) & closed_mask].sum()))
    total_pnl = float(pnl[closed_mask].sum())
    equity = STARTING_CAPITAL + pnl[closed_mask].cumsum()
    if equity.empty:
        max_dd = 0.0
    else:
        peaks = equity.cummax()
        max_dd = float(((equity - peaks) / peaks * 100).min())

    result = dict(empty)
    result.update({
        "status": "Paper research active", "current_capital": f"${STARTING_CAPITAL + total_pnl:,.2f}",
        "total_profit": f"${total_pnl:,.2f}", "total_pnl": f"${total_pnl:,.2f}",
        "return_pct": f"{total_pnl / STARTING_CAPITAL * 100:.2f}%",
        "signals": int(approved_mask.sum()), "candidates": len(frame),
        "approved": int(approved_mask.sum()), "rejected": int((decision.eq("REJECT") | status.eq("REJECTED")).sum()),
        "open": int(status.eq("OPEN").sum()), "wins": wins, "losses": losses,
        "expired": int(status.eq("EXPIRED").sum()),
        "win_rate": f"{(wins / int(resolved_mask.sum()) * 100) if resolved_mask.any() else 0:.1f}%",
        "profit_factor": "∞" if gross_loss == 0 and gross_win > 0 else f"{gross_win / gross_loss if gross_loss else 0:.2f}",
        "max_drawdown": f"{max_dd:.2f}%", "buys": int(direction.eq("BUY").sum()),
        "sells": int(direction.eq("SELL").sum()),
    })
    return result


def get_closed_trades(csv_path, limit=15):
    """Get only closed trades (WIN/LOSS/EXPIRED) for the dashboard."""
    frame = load_trades(csv_path)
    if frame.empty:
        return []

    # Filter to closed trades only
    status = frame.get("status", pd.Series("", index=frame.index)).astype(str).str.upper()
    closed = frame[status.isin(["WIN", "LOSS", "EXPIRED"])].copy()
    if closed.empty:
        return []

    records = []
    for _, row in closed.tail(limit).iloc[::-1].iterrows():
        pnl_usd = float(row.get("pnl_usd", 0)) if pd.notna(row.get("pnl_usd")) else 0
        status_val = str(row.get("status", "")).upper()
        outcome_class = "WIN" if status_val == "WIN" else ("LOSS" if status_val == "LOSS" else "OPEN")

        records.append({
            "time": str(row.get("timestamp", ""))[:16].replace("T", " "),
            "direction": str(row.get("direction", "—")).upper(),
            "entry": f"{row.get('entry', '—'):.2f}" if pd.notna(row.get("entry")) else "—",
            "exit": f"{row.get('exit_price', '—'):.2f}" if pd.notna(row.get("exit_price")) else "—",
            "rr": f"{row.get('rr_ratio', '—'):.2f}" if pd.notna(row.get("rr_ratio")) else "—",
            "pnl": f"${pnl_usd:+.2f}",
            "outcome_class": outcome_class,
            "status": status_val,
            "reason": str(row.get("decision_reason", ""))[:60],
        })
    return records


def get_recent_trades(csv_path, limit=20):
    frame = load_trades(csv_path)
    if frame.empty:
        return []
    records = []
    for _, row in frame.tail(limit).iloc[::-1].iterrows():
        records.append({
            "time": str(row.get("timestamp", ""))[:19].replace("T", " "),
            "direction": str(row.get("direction", "—")).upper(),
            "status": str(row.get("status", "—")).upper(),
            "entry": row.get("entry", "—"), "stop": row.get("stop_loss", "—"),
            "target": row.get("take_profit", "—"), "rr": row.get("rr_ratio", "—"),
            "smc": row.get("smc_score", "—"), "confidence": row.get("combined_confidence", "—"),
            "pnl": row.get("pnl_usd", "—") or "—", "reason": str(row.get("decision_reason", ""))[:180],
        })
    return records


def _tail_text(path, max_bytes=65536):
    path = Path(path)
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - max_bytes))
        return handle.read().decode("utf-8", errors="replace")


def _validate_bars(bars, timeframe):
    if not isinstance(bars, list) or not bars:
        return {"count": 0, "ordered": False, "unique": False, "ohlc": False,
                "quotes": False, "cadence": False, "interval": "—", "latest": "—"}
    times, valid_ohlc, valid_quotes = [], True, True
    quote_fields_present = all(
        all(f"{side}_{field}" in bar for side in ("bid", "ask")
            for field in ("open", "high", "low", "close"))
        for bar in bars
    )
    for bar in bars:
        try:
            times.append(int(bar["time"]))
            o, h, low, c = (float(bar[key]) for key in ("open", "high", "low", "close"))
            valid_ohlc &= all(math.isfinite(v) and v > 0 for v in (o, h, low, c))
            valid_ohlc &= h >= max(o, c, low) and low <= min(o, c, h)
            if quote_fields_present:
                for side in ("bid", "ask"):
                    qo, qh, ql, qc = (float(bar[f"{side}_{key}"])
                                      for key in ("open", "high", "low", "close"))
                    valid_quotes &= all(math.isfinite(v) and v > 0 for v in (qo, qh, ql, qc))
                    valid_quotes &= qh >= max(qo, qc, ql) and ql <= min(qo, qc, qh)
                valid_quotes &= float(bar["ask_close"]) >= float(bar["bid_close"])
        except (KeyError, TypeError, ValueError):
            valid_ohlc = False
            valid_quotes = False
    latest = datetime.fromtimestamp(times[-1], timezone.utc).strftime("%m-%d %H:%M") if times else "—"
    intervals = [later - earlier for earlier, later in zip(times, times[1:])]
    actual_interval = float(median(intervals)) if intervals else 0
    expected_interval = EXPECTED_CADENCE_SECONDS.get(timeframe, 0)
    cadence = bool(expected_interval and
                   abs(actual_interval - expected_interval) <= expected_interval * .05)
    return {"count": len(bars), "ordered": times == sorted(times),
            "unique": len(times) == len(set(times)), "ohlc": bool(valid_ohlc),
            "quotes": bool(quote_fields_present and valid_quotes),
            "cadence": cadence, "interval": f"{actual_interval:.0f}s", "latest": latest}


def get_feed_health(snapshot_path=None, log_path=None):
    """Validate the existing atomic snapshot; makes no network or MCP calls."""
    try:
        contract = settings.price_snapshot_contract()
    except ValueError:
        contract = {"path": settings.TRADINGVIEW_SNAPSHOT_PATH, "provider": "", "symbol": ""}
    snapshot_path = Path(snapshot_path or contract["path"])
    health = {
        "status": "UNAVAILABLE", "status_class": "bad", "provider": "—", "symbol": "—",
        "captured_at": "—", "age": "—", "bar_age": "—", "frames": {}, "integrity": "FAILED",
        "price_consistency": "—", "last_scan": "No completed scan", "market": "CLOSED" if is_market_closed() else "OPEN",
        "paper_mode": "ENFORCED" if settings.PAPER_TRADING else "MISCONFIGURED",
        "telegram": "CONFIGURED" if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID else "NOT CONFIGURED",
    }
    try:
        payload = json.loads(snapshot_path.read_text())
        captured = datetime.fromisoformat(payload["captured_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
        age_seconds = max(0, int((datetime.now(timezone.utc) - captured).total_seconds()))
        frames = {name: _validate_bars(data.get("bars", []), name)
                  for name, data in payload.get("timeframes", {}).items()}
        closes = [float(payload["timeframes"][name]["bars"][-1]["close"]) for name in frames if frames[name]["count"]]
        divergence = ((max(closes) - min(closes)) / min(closes) * 100) if closes else float("inf")
        frame_payloads = [json.dumps(payload["timeframes"][name].get("bars", []),
                                    sort_keys=True, separators=(",", ":"))
                          for name in ("1W", "1D", "4H", "1H", "15M")
                          if name in payload.get("timeframes", {})]
        distinct_frames = len(frame_payloads) == 5 and len(set(frame_payloads)) == 5
        quotes_required = contract["provider"] == "dukascopy-public"
        integrity = payload.get("schema_version") == 2 and distinct_frames and all(
                        frames.get(name, {}).get("count", 0) >= 200 and frames[name]["ordered"] and
                        frames[name]["unique"] and frames[name]["ohlc"] and frames[name]["cadence"] and
                        (frames[name]["quotes"] or not quotes_required)
                        for name in ("1W", "1D", "4H", "1H", "15M"))
        fresh = age_seconds <= settings.DASHBOARD_FEED_MAX_AGE_SECONDS
        latest_15m = int(payload["timeframes"]["15M"]["bars"][-1]["time"]) + 900
        bar_age_seconds = max(0, int(datetime.now(timezone.utc).timestamp() - latest_15m))
        market_closed = is_market_closed()
        bar_fresh = market_closed or bar_age_seconds <= settings.PRICE_BAR_MAX_LAG_SECONDS
        exact = (payload.get("symbol") == contract["symbol"] and
                 payload.get("provider") == contract["provider"])
        # Completed higher-timeframe candles naturally have different end
        # times. Dispersion is informational; a broad sanity ceiling catches
        # gross symbol/source corruption without rejecting normal weekly moves.
        consistent = divergence <= 20.0
        healthy = fresh and bar_fresh and exact and integrity and consistent
        health.update({
            "status": "HEALTHY" if healthy else "DEGRADED", "status_class": "good" if healthy else "warn",
            "provider": payload.get("provider", "—"), "symbol": payload.get("symbol", "—"),
            "captured_at": captured.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "age": f"{age_seconds // 60}m {age_seconds % 60}s",
            "bar_age": f"{bar_age_seconds // 60}m {bar_age_seconds % 60}s",
            "frames": frames,
            "integrity": "PASS" if integrity else "FAIL", "price_consistency": f"{divergence:.3f}% spread",
        })
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        pass
    for line in reversed(_tail_text(log_path or settings.LOG_FILE).splitlines()):
        if "[ORCHESTRATOR] Result:" in line:
            health["last_scan"] = line.split("[ORCHESTRATOR] Result:", 1)[1].strip()
            break
    return health


def get_shadow_variants(assignments_path=None, outcomes_path=None, contract_path=None):
    """Summarize prospective variants from local files without evaluating them."""
    result = {
        "status": "FROZEN · COLLECTING", "status_class": "warn",
        "experiment": "—", "frozen_at": "—", "first_assignment": "Awaiting first candidate",
        "assignment_cutoff": "—", "evaluation_at": "—",
        "purpose": "Pilot diagnostics; no edge claim",
        "baseline_assigned": 0, "baseline_eligible": 0, "baseline_matured": 0,
        "liquidity_assigned": 0, "liquidity_eligible": 0, "liquidity_matured": 0,
        "effect": "None — research only",
    }
    try:
        contract = json.loads(Path(contract_path or settings.RESEARCH_VARIANT_CONFIG).read_text())
        result["experiment"] = contract["experiment_version"]
        result["frozen_at"] = str(contract["frozen_at_utc"]).replace("T", " ").replace("Z", " UTC")
        stopping = contract.get("stopping_rule", {})
        result["assignment_cutoff"] = str(stopping.get("assignment_cutoff_at_utc", "—")).replace(
            "T", " ").replace("Z", " UTC")
        result["evaluation_at"] = str(stopping.get("evaluate_once_at_utc", "—")).replace(
            "T", " ").replace("Z", " UTC")
        result["purpose"] = contract.get("pilot_purpose", result["purpose"])
        isolation = contract["isolation"]
        if (not contract.get("paper_only") or isolation.get("may_approve_paper_trade") is not False or
                isolation.get("may_send_telegram") is not False):
            raise ValueError("invalid isolation contract")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        result.update({"status": "CONFIG ERROR", "status_class": "bad"})
        return result

    assignments = load_trades(assignments_path or settings.FORWARD_VARIANT_ASSIGNMENTS_CSV)
    if assignments.empty:
        return result
    required = {"candidate_id", "timestamp", "experiment_version", "baseline_v1",
                "buy_liquidity_v1", "min_rr_eligible"}
    if not required.issubset(assignments.columns):
        result.update({"status": "ASSIGNMENT ERROR", "status_class": "bad"})
        return result
    assignments = assignments[assignments["experiment_version"].eq(result["experiment"])].copy()
    if assignments.empty:
        result.update({"status": "VERSION MISMATCH", "status_class": "bad"})
        return result
    for column in ("baseline_v1", "buy_liquidity_v1", "min_rr_eligible"):
        assignments[column] = pd.to_numeric(assignments[column], errors="coerce").fillna(0).eq(1)
    eligible = assignments["min_rr_eligible"]
    baseline = assignments["baseline_v1"]
    liquidity = assignments["buy_liquidity_v1"]
    result.update({
        "first_assignment": str(assignments["timestamp"].min())[:19].replace("T", " ") + " UTC",
        "baseline_assigned": int(baseline.sum()),
        "baseline_eligible": int((baseline & eligible).sum()),
        "liquidity_assigned": int(liquidity.sum()),
        "liquidity_eligible": int((liquidity & eligible).sum()),
    })

    outcomes = load_trades(outcomes_path or settings.FORWARD_OUTCOMES_CSV)
    if not outcomes.empty and {"candidate_id", "status"}.issubset(outcomes.columns):
        matured_ids = set(outcomes.loc[
            outcomes["status"].astype(str).str.upper().isin(["TP", "SL", "EXPIRY"]),
            "candidate_id",
        ].astype(str))
        matured = assignments["candidate_id"].astype(str).isin(matured_ids)
        result["baseline_matured"] = int((baseline & eligible & matured).sum())
        result["liquidity_matured"] = int((liquidity & eligible & matured).sum())
    return result


def get_context_health(snapshot_path=None, journal_path=None, contract_path=None):
    """Report context source/capture integrity without inspecting outcomes."""
    contract_path = Path(contract_path or settings.FORWARD_CONTEXT_CONFIG)
    result = {
        "status": "UNAVAILABLE", "status_class": "bad", "experiment": "—",
        "provider": "—", "captured_at": "—", "snapshot_age": "—",
        "assignment_cutoff": "—", "evaluation_at": "—", "instruments": {},
        "captured_candidates": 0, "buy_hypothesis_candidates": 0,
        "sell_observations": 0, "missing_captures": 0, "capture_rate": "—",
        "effect": "None — observation only",
    }
    try:
        contract, contract_sha = load_forward_context_contract(contract_path)
        result["experiment"] = contract["experiment_version"]
        result["provider"] = contract["source_contract"]["provider"]
        stopping = contract["stopping_rule"]
        result["assignment_cutoff"] = str(stopping["assignment_cutoff_at_utc"]).replace(
            "T", " ").replace("Z", " UTC")
        result["evaluation_at"] = str(stopping["evaluate_once_at_utc"]).replace(
            "T", " ").replace("Z", " UTC")
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        result.update({"status": "CONFIG ERROR", "status_class": "bad"})
        return result

    snapshot_ok = False
    try:
        payload, _ = load_validated_context_snapshot(
            Path(snapshot_path or settings.GOLD_CONTEXT_SNAPSHOT_PATH), contract_path,
        )
        captured = datetime.fromisoformat(payload["captured_at"].replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
        age_seconds = max(0, int((datetime.now(timezone.utc) - captured).total_seconds()))
        result["captured_at"] = captured.strftime("%Y-%m-%d %H:%M:%S UTC")
        result["snapshot_age"] = f"{age_seconds // 60}m {age_seconds % 60}s"
        now_epoch = datetime.now(timezone.utc).timestamp()
        for name in CONTEXT_NAMES:
            item = payload["instruments"][name]
            latest_available = int(item["bars"][-1]["time"]) + 3600
            staleness_minutes = max(0, int((now_epoch - latest_available) / 60))
            result["instruments"][name] = {
                "symbol": item["symbol"],
                "sides": "+".join(item["required_sides"]),
                "analysis": item["analysis_price"],
                "count": item["bar_count"],
                "cadence": f"{float(item['median_cadence_seconds']):.0f}s",
                "latest": datetime.fromtimestamp(latest_available, timezone.utc).strftime(
                    "%Y-%m-%d %H:%M UTC"
                ),
                "staleness": f"{staleness_minutes}m",
                "missing_rate": "Awaiting candidates",
            }
        snapshot_ok = True
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        for name, spec in contract["source_contract"]["instruments"].items():
            result["instruments"][name] = {
                "symbol": spec["symbol"], "sides": "+".join(spec["required_sides"]),
                "analysis": spec["analysis_price"], "count": 0, "cadence": "—",
                "latest": "—", "staleness": "—", "missing_rate": "—",
            }

    journal = load_trades(journal_path or settings.FORWARD_CONTEXT_CSV)
    journal_ok = True
    if not journal.empty:
        required = {
            "candidate_id", "experiment_version", "contract_sha256", "direction",
            "context_available", "baseline_context_capture_v1",
            "buy_context_hypothesis_v1",
        }
        if not required.issubset(journal.columns):
            journal_ok = False
        else:
            current_version = (
                journal["experiment_version"].eq(result["experiment"]) &
                journal["contract_sha256"].eq(contract_sha)
            )
            journal_ok = bool(current_version.all())
            journal = journal[current_version].copy()
            if journal["candidate_id"].astype(str).duplicated().any():
                journal_ok = False
            available = pd.to_numeric(journal["context_available"], errors="coerce").fillna(0).eq(1)
            direction = journal["direction"].astype(str).str.upper()
            result.update({
                "captured_candidates": len(journal),
                "buy_hypothesis_candidates": int(direction.eq("BUY").sum()),
                "sell_observations": int(direction.eq("SELL").sum()),
                "missing_captures": int((~available).sum()),
                "capture_rate": f"{available.mean() * 100:.1f}%" if len(journal) else "—",
            })
            for name in CONTEXT_NAMES:
                column = f"ctx_{name}_missing"
                if column in journal and len(journal):
                    missing = pd.to_numeric(journal[column], errors="coerce").fillna(1).eq(1)
                    result["instruments"][name]["missing_rate"] = f"{missing.mean() * 100:.1f}%"

    healthy = snapshot_ok and journal_ok and result["missing_captures"] == 0
    result.update({
        "status": "HEALTHY · COLLECTING" if healthy else "DEGRADED",
        "status_class": "good" if healthy else "warn",
    })
    return result


def get_evidence_integrity(
    ledger_path=None, features_path=None, outcomes_path=None,
    variants_path=None, context_path=None, config_path=None,
    variant_contract_path=None, context_contract_path=None, status_path=None,
):
    """Reconcile evidence files without reading any performance values."""
    try:
        report = build_evidence_integrity_report(
            ledger_path=Path(ledger_path or settings.PAPER_TRADES_CSV),
            features_path=Path(features_path or settings.FORWARD_FEATURES_CSV),
            outcomes_path=Path(outcomes_path or settings.FORWARD_OUTCOMES_CSV),
            variants_path=Path(variants_path or settings.FORWARD_VARIANT_ASSIGNMENTS_CSV),
            context_path=Path(context_path or settings.FORWARD_CONTEXT_CSV),
            config_path=Path(config_path or settings.EVIDENCE_INTEGRITY_CONFIG),
            variant_contract_path=Path(variant_contract_path or settings.RESEARCH_VARIANT_CONFIG),
            context_contract_path=Path(context_contract_path or settings.FORWARD_CONTEXT_CONFIG),
        )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return {
            "status": "CONFIG ERROR", "status_class": "bad", "monitor_version": "—",
            "canonical_candidates_total": 0, "pilot_candidates": 0,
            "context_scope_candidates": 0, "ledgers": [],
            "technical_drift": {"status": "UNAVAILABLE", "max_psi_display": "—"},
            "context_drift": {"status": "UNAVAILABLE", "max_psi_display": "—"},
            "issue_summary": str(exc)[:240], "scheduled_check": "Unavailable",
            "performance_access": "NEVER", "effect": "None — operational monitoring only",
        }

    for key in ("technical_drift", "context_drift"):
        value = report[key].get("max_psi")
        report[key]["max_psi_display"] = "—" if value is None else f"{value:.3f}"
    report["issue_summary"] = (
        "; ".join(report["issues"][:4]) if report["issues"] else "None"
    )
    report["performance_access"] = (
        "NEVER" if not report["performance_columns_read"] else "CONTRACT VIOLATION"
    )
    report["scheduled_check"] = "Awaiting first scheduled audit"
    try:
        artifact = json.loads(Path(
            status_path or settings.EVIDENCE_INTEGRITY_STATUS_PATH
        ).read_text())
        if (artifact.get("monitor_version") == report["monitor_version"] and
                artifact.get("contract_sha256") == report["contract_sha256"]):
            generated = datetime.fromisoformat(
                artifact["generated_at"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            age = max(0, int((datetime.now(timezone.utc) - generated).total_seconds()))
            report["scheduled_check"] = f"{age // 60}m {age % 60}s ago · {artifact['status']}"
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        pass
    return report


def get_event_concordance_health(status_path=None, contract_path=None):
    """Read the scheduled concordance artifact without recomputing or networking."""
    result = {
        "status": "AWAITING RUNTIME ARCHIVES",
        "status_class": "warn",
        "runtime_scans": 0,
        "self_replay": 0,
        "compared_decisions": 0,
        "minimum_decisions": 120,
        "compared_events": 0,
        "minimum_events": 30,
        "replay_lag": "—",
        "authorized": "NO",
        "coverage": "No directions or event types covered yet",
        "age": "Awaiting first scheduled audit",
        "issue_summary": "None",
    }
    contract_loaded = False
    try:
        contract, digest, _, _ = load_event_feature_concordance_contract(
            Path(contract_path or settings.EVENT_FEATURE_CONCORDANCE_CONFIG)
        )
        contract_loaded = True
        gates = contract["authorization_gates"]
        result["minimum_decisions"] = int(gates["minimum_compared_decision_times"])
        result["minimum_events"] = int(gates["minimum_compared_events"])
        artifact = json.loads(
            Path(
                status_path or settings.EVENT_FEATURE_CONCORDANCE_STATUS_PATH
            ).read_text()
        )
        if (
            artifact.get("monitor_version") != contract["monitor_version"]
            or artifact.get("contract_sha256") != digest
            or artifact.get("performance_columns_read") != []
        ):
            raise ValueError("event concordance artifact provenance mismatch")
        now = datetime.now(timezone.utc)
        generated = datetime.fromisoformat(
            artifact["generated_at"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        age_seconds = max(
            0, int((now - generated).total_seconds())
        )
        eligible, eligibility_reason = (
            event_feature_shadow_registration_eligible(
                Path(
                    status_path
                    or settings.EVENT_FEATURE_CONCORDANCE_STATUS_PATH
                ),
                Path(
                    contract_path
                    or settings.EVENT_FEATURE_CONCORDANCE_CONFIG
                ),
                observed_at=now,
            )
        )
        if artifact.get("status") == "PASS" and not eligible:
            raise ValueError(
                f"event concordance PASS artifact rejected: {eligibility_reason}"
            )
        directions = artifact.get("covered_directions", [])
        event_types = artifact.get("covered_event_types", [])
        lag = artifact.get("latest_runtime_to_replay_lag_hours")
        result.update({
            "status": str(artifact["status"]),
            "status_class": str(artifact.get("status_class", "warn")),
            "runtime_scans": int(artifact.get("runtime_scans", 0)),
            "self_replay": int(
                artifact.get("archived_self_replay_decisions", 0)
            ),
            "compared_decisions": int(
                artifact.get("compared_decision_times", 0)
            ),
            "compared_events": int(artifact.get("compared_events", 0)),
            "replay_lag": "—" if lag is None else f"{float(lag):.1f}h",
            "authorized": (
                "SHADOW REGISTRATION ELIGIBLE"
                if eligible
                else "NO"
            ),
            "coverage": (
                f"{len(directions)}/2 directions · {len(event_types)}/5 event types"
            ),
            "age": f"{age_seconds // 60}m {age_seconds % 60}s ago",
            "issue_summary": (
                "; ".join(artifact.get("issues", [])[:3]) or "None"
            ),
        })
    except FileNotFoundError as exc:
        if not contract_loaded:
            result.update({
                "status": "CONFIG ERROR",
                "status_class": "bad",
                "issue_summary": str(exc)[:240],
            })
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        result.update({
            "status": "CONFIG ERROR",
            "status_class": "bad",
            "issue_summary": str(exc)[:240],
        })
    return result


TEMPLATE = """
<!doctype html><html><head><title>Gold Signal Fetcher</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<style>
*{box-sizing:border-box}body{margin:0;background:#0a0e27;color:#e5edf7;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1280px;margin:auto;padding:24px}.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px;border-bottom:2px solid #1e40af;padding-bottom:12px}.header h1{margin:0;color:#fbbf24;font-size:28px}.subtitle{color:#9ca3af;font-size:13px}.muted{color:#9ca3af}.alert{background:rgba(239,68,68,0.1);border-left:4px solid #ef4444;padding:14px;border-radius:6px;margin-bottom:20px;display:none}.alert.show{display:block}.alert-text{color:#fca5a5;font-weight:500}.panel{background:#111827;border:1px solid #1e40af;border-radius:8px;padding:20px;margin-bottom:20px}.panel h2{font-size:16px;margin:0 0 16px 0;color:#60a5fa;text-transform:uppercase;letter-spacing:1px}.pill{display:inline-block;padding:6px 14px;border-radius:999px;font-weight:800;font-size:11px;margin-left:12px}.good{background:#10b981;color:#ffffff}.warn{background:#d97706;color:#ffffff}.bad{background:#dc2626;color:#ffffff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:14px;margin-bottom:16px}.card{background:#1f2937;border:1px solid #374151;border-radius:6px;padding:14px;text-align:center}.label{text-transform:uppercase;color:#9ca3af;font-size:11px;font-weight:700;margin-bottom:8px}.value{font-size:18px;font-weight:900;color:#fbbf24}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}.metric{background:#1f2937;border-left:3px solid #10b981;padding:16px;border-radius:6px}.metric .label{font-size:10px}.metric .value{font-size:20px;color:#10b981}.capital-row{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:20px}.capital-card{background:#1f2937;border:1px solid #374151;padding:16px;border-radius:6px}.capital-card .label{text-align:left;margin-bottom:8px}.capital-card .value{text-align:left;font-size:20px}.table-wrap{overflow:auto}.trades-table{width:100%;border-collapse:collapse;min-width:900px}.trades-table th,.trades-table td{padding:10px;border-bottom:1px solid #2d3748;text-align:left;font-size:12px}.trades-table th{background:#1e2d42;color:#9ca3af;text-transform:uppercase;font-size:10px;font-weight:700}.trades-table tr:hover{background:#1f2937}.BUY{color:#10b981;font-weight:800}.SELL{color:#f87171;font-weight:800}.WIN{color:#10b981;font-weight:800}.LOSS{color:#ef4444;font-weight:800}.OPEN{color:#60a5fa}.note{margin-top:12px;font-size:11px;color:#9ca3af}@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}.metrics{grid-template-columns:repeat(2,1fr)}.capital-row{grid-template-columns:1fr}.header{display:block;border-bottom:none;padding-bottom:0}}
</style></head><body><div class="wrap">

<div class="header">
  <div>
    <h1>🥇 Gold Signal Fetcher</h1>
    <div class="subtitle">AI-assisted, evidence-governed XAUUSD paper research</div>
  </div>
  <div class="muted">{{ now }} UTC</div>
</div>

{% if feed.status != "HEALTHY" or integrity.status_class == "bad" or concordance.status_class == "bad" %}
<div class="alert show">
  <div class="alert-text">⚠️ Feed: {{ feed.status }} • Evidence: {{ integrity.status }} • Feature parity: {{ concordance.status }} • {{ integrity.issue_summary }} {{ concordance.issue_summary }}</div>
</div>
{% endif %}

<section class="panel">
  <h2>Operational Integrity <span class="pill {{ integrity.status_class }}">{{ integrity.status }}</span></h2>
  <div class="grid">
    <div class="card"><div class="label">Price Feed</div><div class="value">{{ feed.status }}</div></div>
    <div class="card"><div class="label">Snapshot Age</div><div class="value">{{ feed.age }}</div></div>
    <div class="card"><div class="label">Last Candidate Scan</div><div class="value">{{ feed.last_scan }}</div></div>
    <div class="card"><div class="label">Evidence Candidates</div><div class="value">{{ integrity.pilot_candidates }}</div></div>
    <div class="card"><div class="label">Event Observer</div><div class="value">{{ event.status }}</div></div>
    <div class="card"><div class="label">Prospective Events</div><div class="value">{{ event.events }}</div></div>
    <div class="card"><div class="label">Feature Parity</div><div class="value">{{ concordance.status }}</div></div>
  </div>
  <div class="note">File-only monitoring. Event observations are outcome-blind and isolated from signals. Current evidence issue: {{ integrity.issue_summary }}</div>
</section>

<section class="panel">
  <h2>Event Feature Concordance <span class="pill {{ concordance.status_class }}">{{ concordance.status }}</span></h2>
  <div class="grid">
    <div class="card"><div class="label">Runtime Archives</div><div class="value">{{ concordance.self_replay }}/{{ concordance.runtime_scans }}</div></div>
    <div class="card"><div class="label">Compared Decisions</div><div class="value">{{ concordance.compared_decisions }}/{{ concordance.minimum_decisions }}</div></div>
    <div class="card"><div class="label">Compared Events</div><div class="value">{{ concordance.compared_events }}/{{ concordance.minimum_events }}</div></div>
    <div class="card"><div class="label">Coverage</div><div class="value">{{ concordance.coverage }}</div></div>
    <div class="card"><div class="label">Replay Lag</div><div class="value">{{ concordance.replay_lag }}</div></div>
    <div class="card"><div class="label">Next Authority</div><div class="value">{{ concordance.authorized }}</div></div>
  </div>
  <div class="note">Native runtime snapshots are content-addressed and compared with a delayed, separately fetched five-timeframe reference. This reads no outcomes and can authorize only registration of a later shadow experiment. Audit: {{ concordance.age }}. Issue: {{ concordance.issue_summary }}</div>
</section>

<section class="panel">
  <h2>Structured AI Review <span class="pill {{ ai.status_class }}">{{ ai.status }}</span></h2>
  <div class="grid">
    <div class="card"><div class="label">Journalled Reviews</div><div class="value">{{ ai.total }}</div></div>
    <div class="card"><div class="label">Available</div><div class="value">{{ ai.available }}</div></div>
    <div class="card"><div class="label">Context Passes</div><div class="value">{{ ai.passes }}</div></div>
    <div class="card"><div class="label">Vetoes</div><div class="value">{{ ai.vetoes }}</div></div>
    <div class="card"><div class="label">Avg Self-confidence</div><div class="value">{{ ai.avg_confidence }}</div></div>
    <div class="card"><div class="label">Latest Model</div><div class="value">{{ ai.model }}</div></div>
  </div>
  <div class="note">Exactly one structured Claude review per new candidate. Its confidence is recorded for research but has no numeric vote; Claude can veto and explain only. Request/response payloads, hashes, model and prompt version are journalled.</div>
</section>

<section class="panel">
  <h2>Performance Metrics</h2>
  <div class="capital-row">
    <div class="capital-card"><div class="label">Starting Capital</div><div class="value">{{ m.starting_capital }}</div></div>
    <div class="capital-card"><div class="label">Current Equity</div><div class="value">{{ m.current_capital }}</div></div>
    <div class="capital-card"><div class="label">P&L Return</div><div class="value">{{ m.total_profit }} ({{ m.return_pct }})</div></div>
  </div>
  <div class="metrics">
    <div class="metric"><div class="label">Signals Analyzed</div><div class="value">{{ m.candidates }}</div></div>
    <div class="metric"><div class="label">Wins</div><div class="value" style="color:#10b981">{{ m.wins }}</div></div>
    <div class="metric"><div class="label">Losses</div><div class="value" style="color:#ef4444">{{ m.losses }}</div></div>
    <div class="metric"><div class="label">Win Rate</div><div class="value">{{ m.win_rate }}</div></div>
    <div class="metric"><div class="label">Profit Factor</div><div class="value">{{ m.profit_factor }}</div></div>
    <div class="metric"><div class="label">Max Drawdown</div><div class="value">{{ m.max_drawdown }}</div></div>
  </div>
</section>

<section class="panel">
  <h2>Recent Wins & Losses</h2>
  <div class="table-wrap">
    <table class="trades-table">
      <thead>
        <tr>
          <th>Time UTC</th>
          <th>Side</th>
          <th>Entry</th>
          <th>Exit</th>
          <th>R/R</th>
          <th>P&L</th>
          <th>Status</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {% if closed_trades %}
          {% for r in closed_trades %}
            <tr>
              <td>{{ r.time }}</td>
              <td class="{{ r.direction }}">{{ r.direction }}</td>
              <td>{{ r.entry }}</td>
              <td>{{ r.exit }}</td>
              <td>{{ r.rr }}</td>
              <td class="{{ r.outcome_class }}">{{ r.pnl }}</td>
              <td class="{{ r.status }}">{{ r.status }}</td>
              <td style="font-size:11px;color:#9ca3af">{{ r.reason }}</td>
            </tr>
          {% endfor %}
        {% else %}
          <tr><td colspan="8" class="muted">No closed trades yet.</td></tr>
        {% endif %}
      </tbody>
    </table>
  </div>
  <div class="note">Closed paper-ledger trades only. These outcomes are not supplied to Claude and do not calibrate its confidence.</div>
</section>

<div class="note" style="text-align:center;margin-top:30px">Research paper trading only. Results do not establish profitability or suitability for live capital.</div>

</div></body></html>
"""


def get_ai_review_stats(path=None):
    """Report AI-review provenance only; never infer profitability."""
    frame = load_trades(path or settings.FORWARD_AI_REVIEWS_CSV)
    empty = {
        "status": "AWAITING REVIEWS", "status_class": "warn", "total": 0,
        "available": 0, "passes": 0, "vetoes": 0,
        "avg_confidence": "—", "model": "—",
    }
    if frame.empty:
        return empty
    required = {"available", "should_trade", "confidence", "model"}
    if not required.issubset(frame.columns):
        return {**empty, "status": "SCHEMA ERROR", "status_class": "bad"}
    available = frame["available"].astype(str).str.lower().isin(
        {"1", "true", "yes"}
    )
    should_trade = frame["should_trade"].astype(str).str.lower().isin(
        {"1", "true", "yes"}
    )
    confidence = pd.to_numeric(frame["confidence"], errors="coerce")
    models = frame.loc[frame["model"].astype(str).str.len().gt(0), "model"]
    return {
        "status": "OBSERVING", "status_class": "good", "total": len(frame),
        "available": int(available.sum()),
        "passes": int((available & should_trade).sum()),
        "vetoes": int((available & ~should_trade).sum()),
        "avg_confidence": (
            f"{confidence[available].mean():.0f}%"
            if confidence[available].notna().any() else "—"
        ),
        "model": str(models.iloc[-1]) if len(models) else "—",
    }


def get_event_observation_health(event_path=None, scan_path=None):
    """Validate prospective event files using counts and provenance only."""
    result = {
        "status": "AWAITING FIRST 1H CLOSE", "status_class": "warn",
        "events": 0, "scans": 0, "latest_decision": "—",
    }
    try:
        _, contract_sha, _ = load_forward_event_contract()
        events = load_trades(
            event_path or settings.FORWARD_EVENT_OBSERVATIONS_CSV,
        )
        scans = load_trades(scan_path or settings.FORWARD_EVENT_SCANS_CSV)
        if not events.empty and list(events.columns) != EVENT_COLUMNS:
            raise ValueError("event row schema drift")
        if not scans.empty and list(scans.columns) != SCAN_COLUMNS:
            raise ValueError("event scan schema drift")
        if not events.empty:
            if events["event_id"].astype(str).duplicated().any():
                raise ValueError("duplicate prospective event IDs")
            if not events["observation_contract_sha256"].eq(contract_sha).all():
                raise ValueError("event contract provenance drift")
        if scans.empty:
            return result
        if scans["decision_time"].astype(str).duplicated().any():
            raise ValueError("duplicate event decision times")
        if not scans["observation_contract_sha256"].eq(contract_sha).all():
            raise ValueError("event scan contract provenance drift")
        latest = pd.to_datetime(
            scans["decision_time"], utc=True, errors="raise",
        ).max()
        age_seconds = (
            datetime.now(timezone.utc) - latest.to_pydatetime()
        ).total_seconds()
        stale = not is_market_closed() and age_seconds > 5400
        return {
            "status": "STALE" if stale else "HEALTHY",
            "status_class": "bad" if stale else "good",
            "events": len(events), "scans": len(scans),
            "latest_decision": latest.isoformat(),
        }
    except (OSError, RuntimeError, ValueError, KeyError, TypeError,
            json.JSONDecodeError, pd.errors.ParserError) as exc:
        logger.warning("Event observation health unavailable: %s", exc)
        return {**result, "status": "DEGRADED", "status_class": "bad"}


@app.route("/")
def dashboard():
    return render_template_string(TEMPLATE, m=calculate_metrics(settings.PAPER_TRADES_CSV),
                                  closed_trades=get_closed_trades(settings.PAPER_TRADES_CSV),
                                  feed=get_feed_health(),
                                  integrity=get_evidence_integrity(),
                                  event=get_event_observation_health(),
                                  concordance=get_event_concordance_health(),
                                  ai=get_ai_review_stats(),
                                  now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8502, debug=False)
