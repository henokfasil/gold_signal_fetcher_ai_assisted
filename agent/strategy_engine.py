"""Isolated multi-strategy paper engine.

Forward-tests statistically-validated strategies (see research/strategy_search.py:
mean-reversion LONG, tight 1:1, survived out-of-sample + FDR) faithfully and in
their own tagged ledger. Deliberately SEPARATE from the SMC orchestrator and the
frozen research pilot: it never touches paper_trades_ai.csv, evidence integrity
or the forward variant journal. Every trade carries a `strategy` key and a
human-readable `strategy_label` so results are always attributable.

Faithful to the backtest: entry on the last completed 1H close, SL = 1.5*ATR,
TP = 1.5*ATR (1:1), one open position per strategy at a time, 48h expiry, and
adverse-first same-bar resolution on 15M bid/ask bars with 0.10pt slippage.
Paper only; there is no broker-order code.
"""
import csv
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone

import numpy as np

from config import settings
from agent.liquidity_manager import is_market_closed

LEDGER = os.getenv("STRATEGY_LEDGER_PATH",
                   str(settings.PROJECT_ROOT / "data" / "paper_trades_strategies.csv"))
RISK_USD = float(os.getenv("STRATEGY_RISK_USD", "50"))   # fixed risk/trade (1R)
ATR_SL = 1.5
RR = 1.0
SLIP = 0.10
EXPIRY_H = 48
COLUMNS = ["candidate_id", "timestamp", "strategy", "strategy_label", "pair",
           "direction", "entry", "stop_loss", "take_profit", "rr_ratio",
           "signal_note", "status", "exit_price", "exit_time", "exit_reason",
           "pnl_r", "pnl_usd", "paper_trading"]


# ---------- indicators (numpy, 1H mid close/high/low) ----------
def _ema(x, n):
    a = 2 / (n + 1); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out

def _rma(x, n):
    a = 1 / n; out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out

def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = _rma(np.clip(d, 0, None), n); dn = _rma(np.clip(-d, 0, None), n)
    rs = np.divide(up, dn, out=np.full_like(up, np.inf), where=dn != 0)
    return 100 - 100 / (1 + rs)

def _atr(h, l, c, n=14):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    return _rma(tr, n)


def _indicators(bars):
    c = np.array([b["close"] for b in bars], float)
    h = np.array([b["high"] for b in bars], float)
    l = np.array([b["low"] for b in bars], float)
    sma = np.convolve(c, np.ones(20) / 20, mode="valid")
    std = np.array([c[i - 19:i + 1].std() for i in range(19, len(c))])
    bb_lo = np.concatenate([np.full(19, np.nan), sma - 2 * std])
    ema20 = _ema(c, 20)
    return dict(close=c, ema20=ema20, rsi=_rsi(c, 14), atr=_atr(h, l, c, 14),
                bb_lo=bb_lo)


# ---------- validated strategy registry (extend here) ----------
def _sig_bollinger_fade_long(ind):
    if np.isnan(ind["bb_lo"][-1]):
        return None
    if ind["close"][-1] < ind["bb_lo"][-1]:
        return f"close {ind['close'][-1]:.2f} < lower BB {ind['bb_lo'][-1]:.2f}"
    return None

def _sig_rsi_meanrev_long(ind):
    if ind["rsi"][-1] < 30 and ind["close"][-1] < ind["ema20"][-1] - ind["atr"][-1]:
        return f"RSI {ind['rsi'][-1]:.1f}<30 & stretched {ind['atr'][-1]:.2f} below EMA20"
    return None

STRATEGIES = [
    {"key": "bollinger_fade_long_v1",
     "label": "Bollinger Fade (Long, 1:1)", "direction": "BUY",
     "signal": _sig_bollinger_fade_long},
    {"key": "rsi_meanrev_long_v1",
     "label": "RSI Mean-Reversion (Long, 1:1)", "direction": "BUY",
     "signal": _sig_rsi_meanrev_long},
]


# ---------- ledger IO ----------
def _load():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER) as f:
        return list(csv.DictReader(f))

def _save(rows):
    d = os.path.dirname(LEDGER) or "."
    fd, tmp = tempfile.mkstemp(dir=d)
    with os.fdopen(fd, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
    os.replace(tmp, LEDGER)


def _snapshot():
    path = settings.price_snapshot_contract()["path"]
    return json.loads(open(path).read())


def _resolve_open(row, bars15):
    """Replay 15M bid/ask bars after entry; adverse-first. Returns updated row."""
    entry = float(row["entry"]); sl = float(row["stop_loss"]); tp = float(row["take_profit"])
    risk = abs(entry - sl)
    entry_t = datetime.fromisoformat(row["timestamp"]).timestamp()
    exp_t = entry_t + EXPIRY_H * 3600
    for b in bars15:
        if b["time"] <= entry_t:
            continue
        # BUY closes on bid
        if b["bid_low"] <= sl:
            r = (-(entry - sl) - SLIP) / risk
            return _close(row, sl, b["time"], "SL", r)
        if b["bid_high"] >= tp:
            r = ((tp - entry) - SLIP) / risk
            return _close(row, tp, b["time"], "TP", r)
        if b["time"] >= exp_t:
            px = b["bid_close"]; r = ((px - entry) - SLIP) / risk
            return _close(row, px, b["time"], "EXPIRY", r)
    return row  # still open


def _close(row, price, t, reason, r):
    row = dict(row)
    row["status"] = "WIN" if r > 0 else ("LOSS" if r < 0 else "EXPIRED")
    if reason == "EXPIRY":
        row["status"] = "WIN" if r > 0 else "LOSS"
    row["exit_price"] = round(float(price), 4)
    row["exit_time"] = datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
    row["exit_reason"] = reason
    row["pnl_r"] = round(r, 3)
    row["pnl_usd"] = round(r * RISK_USD, 2)
    return row


def run():
    snap = _snapshot()
    tf = snap["timeframes"]
    bars1h = tf["1H"]["bars"]
    bars15 = tf["15M"]["bars"]
    rows = _load()

    # 1) update open positions
    for i, row in enumerate(rows):
        if str(row.get("status", "")).upper() == "OPEN":
            rows[i] = _resolve_open(row, bars15)

    opened = []
    if not is_market_closed():
        ind = _indicators(bars1h)
        last_bar_t = bars1h[-1]["time"]
        for strat in STRATEGIES:
            key = strat["key"]
            has_open = any(r["strategy"] == key and str(r.get("status", "")).upper() == "OPEN"
                           for r in rows)
            if has_open:
                continue
            # require a NEW completed 1H bar since this strategy's last entry
            last_entry_t = max([datetime.fromisoformat(r["timestamp"]).timestamp()
                                for r in rows if r["strategy"] == key] or [0])
            if last_bar_t <= last_entry_t:
                continue
            note = strat["signal"](ind)
            if not note:
                continue
            atr = float(ind["atr"][-1])
            if atr <= 0:
                continue
            entry = float(ind["close"][-1]) + SLIP           # long: fill slightly worse
            sl = round(entry - ATR_SL * atr, 4)
            tp = round(entry + RR * ATR_SL * atr, 4)
            rows.append({
                "candidate_id": uuid.uuid4().hex[:12],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "strategy": key, "strategy_label": strat["label"],
                "pair": "XAUUSD", "direction": strat["direction"],
                "entry": round(entry, 4), "stop_loss": sl, "take_profit": tp,
                "rr_ratio": RR, "signal_note": note, "status": "OPEN",
                "exit_price": "", "exit_time": "", "exit_reason": "",
                "pnl_r": "", "pnl_usd": "", "paper_trading": True,
            })
            opened.append(key)

    _save(rows)
    return {"opened": opened, "total": len(rows),
            "open_now": sum(1 for r in rows if str(r.get("status", "")).upper() == "OPEN")}


if __name__ == "__main__":
    print(run())
