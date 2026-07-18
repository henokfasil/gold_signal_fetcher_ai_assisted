"""Unified SMC + ML + Claude paper-research dashboard."""

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from flask import Flask, render_template_string

from agent.liquidity_manager import is_market_closed
from config import settings

app = Flask(__name__)
logger = logging.getLogger(__name__)
STARTING_CAPITAL = settings.PAPER_ACCOUNT_SIZE


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


def _validate_bars(bars):
    if not isinstance(bars, list) or not bars:
        return {"count": 0, "ordered": False, "unique": False, "ohlc": False, "latest": "—"}
    times, valid_ohlc = [], True
    for bar in bars:
        try:
            times.append(int(bar["time"]))
            o, h, low, c = (float(bar[key]) for key in ("open", "high", "low", "close"))
            valid_ohlc &= all(math.isfinite(v) and v > 0 for v in (o, h, low, c))
            valid_ohlc &= h >= max(o, c, low) and low <= min(o, c, h)
        except (KeyError, TypeError, ValueError):
            valid_ohlc = False
    latest = datetime.fromtimestamp(times[-1], timezone.utc).strftime("%m-%d %H:%M") if times else "—"
    return {"count": len(bars), "ordered": times == sorted(times),
            "unique": len(times) == len(set(times)), "ohlc": bool(valid_ohlc), "latest": latest}


def get_feed_health(snapshot_path=None, log_path=None):
    """Validate the existing atomic snapshot; makes no network or MCP calls."""
    snapshot_path = Path(snapshot_path or settings.TRADINGVIEW_SNAPSHOT_PATH)
    health = {
        "status": "UNAVAILABLE", "status_class": "bad", "provider": "—", "symbol": "—",
        "captured_at": "—", "age": "—", "frames": {}, "integrity": "FAILED",
        "price_consistency": "—", "last_scan": "No completed scan", "market": "CLOSED" if is_market_closed() else "OPEN",
        "paper_mode": "ENFORCED" if settings.PAPER_TRADING else "MISCONFIGURED",
        "telegram": "CONFIGURED" if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID else "NOT CONFIGURED",
    }
    try:
        payload = json.loads(snapshot_path.read_text())
        captured = datetime.fromisoformat(payload["captured_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
        age_seconds = max(0, int((datetime.now(timezone.utc) - captured).total_seconds()))
        frames = {name: _validate_bars(data.get("bars", [])) for name, data in payload.get("timeframes", {}).items()}
        closes = [float(payload["timeframes"][name]["bars"][-1]["close"]) for name in frames if frames[name]["count"]]
        divergence = ((max(closes) - min(closes)) / min(closes) * 100) if closes else float("inf")
        integrity = all(frames.get(name, {}).get("count", 0) >= 200 and
                        frames[name]["ordered"] and frames[name]["unique"] and frames[name]["ohlc"]
                        for name in ("1W", "1D", "4H", "1H", "15M"))
        fresh = age_seconds <= settings.DASHBOARD_FEED_MAX_AGE_SECONDS
        exact = payload.get("symbol") == "OANDA:XAUUSD" and payload.get("provider") == "tradingview-mcp"
        consistent = divergence <= 2.0
        healthy = fresh and exact and integrity and consistent
        health.update({
            "status": "HEALTHY" if healthy else "DEGRADED", "status_class": "good" if healthy else "warn",
            "provider": payload.get("provider", "—"), "symbol": payload.get("symbol", "—"),
            "captured_at": captured.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "age": f"{age_seconds // 60}m {age_seconds % 60}s", "frames": frames,
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
        "baseline_assigned": 0, "baseline_eligible": 0, "baseline_matured": 0,
        "liquidity_assigned": 0, "liquidity_eligible": 0, "liquidity_matured": 0,
        "effect": "None — research only",
    }
    try:
        contract = json.loads(Path(contract_path or settings.RESEARCH_VARIANT_CONFIG).read_text())
        result["experiment"] = contract["experiment_version"]
        result["frozen_at"] = str(contract["frozen_at_utc"]).replace("T", " ").replace("Z", " UTC")
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


TEMPLATE = """
<!doctype html><html><head><title>Gold Signal Research</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<style>
*{box-sizing:border-box}body{margin:0;background:#0b1220;color:#e5edf7;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1380px;margin:auto;padding:24px}.header{display:flex;justify-content:space-between;align-items:end;margin-bottom:22px}.header h1{margin:0;color:#38d38a;font-size:27px}.muted{color:#7f8da3}.panel{background:#151f30;border:1px solid #2a3a51;border-radius:10px;padding:18px;margin-bottom:20px}.feed{border-color:#1597e5}.panel-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}.panel h2{font-size:16px;margin:0;color:#58bfff}.pill{padding:6px 12px;border-radius:999px;font-weight:800;font-size:11px}.good{background:#38c968;color:#061b0d}.warn{background:#f5a623;color:#2d1900}.bad{background:#ef5350;color:#2d0505}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:#0e1726;border-radius:6px;padding:13px;min-height:70px}.label{text-transform:uppercase;color:#718198;font-size:10px;font-weight:700}.value{font-size:17px;font-weight:750;margin-top:7px}.quality{width:100%;border-collapse:collapse;margin-top:14px}.quality th,.quality td{padding:8px;border-bottom:1px solid #26364c;text-align:left}.ok{color:#42d987}.no{color:#ff6b6b}.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:20px}.metric{background:#151f30;border-left:3px solid #38d38a;border-radius:7px;padding:14px}.metric .value{font-size:19px}.capital{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.table-wrap{overflow:auto}table.trades{width:100%;border-collapse:collapse;min-width:1100px}table.trades th,table.trades td{padding:10px;border-bottom:1px solid #26364c;text-align:left;font-size:12px}table.trades th{color:#718198;text-transform:uppercase;font-size:10px}.BUY{color:#42d987;font-weight:800}.SELL{color:#ff7474;font-weight:800}.OPEN{color:#4db8ff}.WIN{color:#42d987}.LOSS{color:#ff6b6b}.REJECTED{color:#9aa8bb}.note{margin-top:12px;font-size:11px;color:#718198}@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}.metrics{grid-template-columns:repeat(2,1fr)}.capital{grid-template-columns:1fr}.header{display:block}.header .muted{margin-top:8px}}
</style></head><body><div class="wrap">
<div class="header"><div><h1>Gold Signal Fetcher</h1><div class="muted">Unified SMC + ML validation gate + Claude review · research paper trading</div></div><div class="muted">Updated {{ now }} UTC</div></div>
<section class="panel feed"><div class="panel-head"><h2>TradingView Data Quality</h2><span class="pill {{ feed.status_class }}">{{ feed.status }}</span></div>
<div class="grid">
{% for label,value in [('Provider',feed.provider),('Exact symbol',feed.symbol),('Snapshot age',feed.age),('Captured',feed.captured_at),('OHLC integrity',feed.integrity),('Cross-TF close variance',feed.price_consistency),('Last scan',feed.last_scan),('Market',feed.market),('Paper mode',feed.paper_mode),('Telegram',feed.telegram),('Schedule','Every 15 minutes'),('Execution','No broker orders')] %}<div class="card"><div class="label">{{ label }}</div><div class="value">{{ value }}</div></div>{% endfor %}
</div><table class="quality"><thead><tr><th>Timeframe</th><th>Bars</th><th>Ordered</th><th>Unique</th><th>OHLC valid</th><th>Latest bar UTC</th></tr></thead><tbody>{% for name,q in feed.frames.items() %}<tr><td>{{ name }}</td><td>{{ q.count }}</td><td class="{{ 'ok' if q.ordered else 'no' }}">{{ 'PASS' if q.ordered else 'FAIL' }}</td><td class="{{ 'ok' if q.unique else 'no' }}">{{ 'PASS' if q.unique else 'FAIL' }}</td><td class="{{ 'ok' if q.ohlc else 'no' }}">{{ 'PASS' if q.ohlc else 'FAIL' }}</td><td>{{ q.latest }}</td></tr>{% endfor %}</tbody></table>
<div class="note">File-only validation: page views do not call TradingView, MCP, Telegram, Claude, or the scanner.</div></section>

<section class="panel"><div class="panel-head"><h2>Prospective Shadow Variants</h2><span class="pill {{ variants.status_class }}">{{ variants.status }}</span></div>
<div class="grid">
{% for label,value in [('Experiment',variants.experiment),('Frozen at',variants.frozen_at),('First assignment',variants.first_assignment),('Decision / Telegram effect',variants.effect),('Baseline assigned',variants.baseline_assigned),('Baseline R/R eligible',variants.baseline_eligible),('Baseline matured',variants.baseline_matured),('BUY + 1H sweep assigned',variants.liquidity_assigned),('BUY + 1H sweep R/R eligible',variants.liquidity_eligible),('BUY + 1H sweep matured',variants.liquidity_matured),('Minimum before review','3–6 months'),('Target sample','200 matured BUY-variant candidates')] %}<div class="card"><div class="label">{{ label }}</div><div class="value">{{ value }}</div></div>{% endfor %}
</div><div class="note">Membership is assigned once at candidate time. This panel reports collection progress only; it does not claim validation, profitability, or model readiness.</div></section>

<div class="capital"><div class="panel"><div class="label">Paper starting capital</div><div class="value">{{ m.starting_capital }}</div></div><div class="panel"><div class="label">Paper marked capital</div><div class="value">{{ m.current_capital }}</div></div><div class="panel"><div class="label">Realized paper P&amp;L</div><div class="value">{{ m.total_profit }} · {{ m.return_pct }}</div></div></div>
<div class="metrics">
{% for label,value in [('Candidates',m.candidates),('Approved',m.approved),('Rejected',m.rejected),('Open',m.open),('Wins / losses',m.wins|string+' / '+m.losses|string),('Expired',m.expired),('Win rate',m.win_rate),('Profit factor',m.profit_factor),('Max drawdown',m.max_drawdown),('BUY candidates',m.buys),('SELL candidates',m.sells),('Status',m.status)] %}<div class="metric"><div class="label">{{ label }}</div><div class="value">{{ value }}</div></div>{% endfor %}
</div>
<section class="panel"><div class="panel-head"><h2>Recent Unified Candidates</h2><span class="muted">Newest first</span></div><div class="table-wrap"><table class="trades"><thead><tr><th>Time UTC</th><th>Side</th><th>Status</th><th>Entry</th><th>Stop</th><th>Target</th><th>R/R</th><th>SMC</th><th>Combined</th><th>P&amp;L $</th><th>Decision reason</th></tr></thead><tbody>{% if rows %}{% for r in rows %}<tr><td>{{ r.time }}</td><td class="{{ r.direction }}">{{ r.direction }}</td><td class="{{ r.status }}">{{ r.status }}</td><td>{{ r.entry }}</td><td>{{ r.stop }}</td><td>{{ r.target }}</td><td>{{ r.rr }}</td><td>{{ r.smc }}</td><td>{{ r.confidence }}</td><td>{{ r.pnl }}</td><td>{{ r.reason }}</td></tr>{% endfor %}{% else %}<tr><td colspan="11" class="muted">No candidates recorded yet. The market is currently closed.</td></tr>{% endif %}</tbody></table></div></section>
<div class="note">Research system only. Engineering health and paper results do not establish profitability or suitability for live capital.</div>
</div></body></html>
"""


@app.route("/")
def dashboard():
    return render_template_string(TEMPLATE, m=calculate_metrics(settings.PAPER_TRADES_CSV),
                                  rows=get_recent_trades(settings.PAPER_TRADES_CSV),
                                  feed=get_feed_health(),
                                  variants=get_shadow_variants(),
                                  now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8502, debug=False)
