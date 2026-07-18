#!/usr/bin/env python3
"""Chronological paper-portfolio replay with runtime-aligned risk gates."""

import argparse
import heapq
import json
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd


def _max_drawdown(equity_values):
    values = np.asarray(equity_values, dtype=float)
    peaks = np.maximum.accumulate(values)
    return float(np.max((peaks - values) / peaks) * 100) if len(values) else 0.0


def simulate(frame: pd.DataFrame, starting_capital=10_000.0, notional=5_000.0,
             cooldown_hours=4, max_open=15, min_rr=2.0,
             daily_loss_cap_pct=3.0, weekly_loss_cap_pct=6.0):
    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data["exit_time"] = pd.to_datetime(data["exit_time"], utc=True, errors="coerce")
    data = data.sort_values("timestamp").reset_index(drop=True)
    equity = starting_capital
    equity_curve = [(data.timestamp.min(), equity)] if len(data) else []
    open_heap, recent = [], {"BUY": deque(), "SELL": deque()}
    daily_pnl, weekly_pnl = defaultdict(float), defaultdict(float)
    records, trade_id, max_concurrent = [], 0, 0

    def settle(until):
        nonlocal equity
        while open_heap and open_heap[0][0] <= until:
            exit_at, _, record_index, pnl_usd = heapq.heappop(open_heap)
            equity += pnl_usd
            day = exit_at.date().isoformat()
            week = f"{exit_at.isocalendar().year}-W{exit_at.isocalendar().week:02d}"
            daily_pnl[day] += pnl_usd
            weekly_pnl[week] += pnl_usd
            records[record_index]["equity_after_exit"] = equity
            equity_curve.append((exit_at, equity))

    for _, row in data.iterrows():
        now, direction, entry = row.timestamp, row.direction, float(row.entry)
        settle(now)
        queue = recent[direction]
        while queue and now - queue[0][0] > pd.Timedelta(hours=cooldown_hours):
            queue.popleft()
        duplicate = any(abs(previous_entry - entry) <= entry * .001 for _, previous_entry in queue)
        if duplicate:
            records.append({"timestamp": now, "direction": direction, "entry": entry,
                            "decision": "REJECT", "reason": "SETUP_COOLDOWN"})
            continue
        queue.append((now, entry))
        reason = None
        if pd.isna(row.label_profitable) or pd.isna(row.exit_time):
            reason = "UNMATURED_OR_AMBIGUOUS"
        elif float(row.rr_ratio) < min_rr:
            reason = "MIN_RR_NOT_MET"
        elif len(open_heap) >= max_open:
            reason = "MAX_OPEN_TRADES"
        day = now.date().isoformat()
        week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
        if reason is None and daily_pnl[day] / starting_capital * 100 <= -abs(daily_loss_cap_pct):
            reason = "DAILY_LOSS_CAP"
        if reason is None and weekly_pnl[week] / starting_capital * 100 <= -abs(weekly_loss_cap_pct):
            reason = "WEEKLY_LOSS_CAP"
        if reason:
            records.append({"timestamp": now, "direction": direction, "entry": entry,
                            "decision": "REJECT", "reason": reason})
            continue
        pnl_usd = notional * float(row.net_return_pct) / 100.0
        record = {"timestamp": now, "exit_time": row.exit_time, "direction": direction,
                  "entry": entry, "rr_ratio": float(row.rr_ratio),
                  "label_status": row.label_status, "net_return_pct": float(row.net_return_pct),
                  "pnl_usd": pnl_usd, "decision": "OPEN", "reason": "GATES_PASSED",
                  "equity_at_entry": equity, "equity_after_exit": np.nan}
        records.append(record)
        heapq.heappush(open_heap, (row.exit_time, trade_id, len(records) - 1, pnl_usd))
        trade_id += 1
        max_concurrent = max(max_concurrent, len(open_heap))
    settle(pd.Timestamp.max.tz_localize("UTC"))
    output = pd.DataFrame(records)
    opened = output[output.decision == "OPEN"].copy()
    wins = opened[opened.pnl_usd > 0].pnl_usd.sum()
    losses = abs(opened[opened.pnl_usd < 0].pnl_usd.sum())
    by_direction = {}
    for direction, group in opened.groupby("direction"):
        by_direction[direction] = {"trades": len(group),
                                   "win_rate": float((group.pnl_usd > 0).mean()),
                                   "pnl_usd": float(group.pnl_usd.sum()),
                                   "mean_net_return_pct": float(group.net_return_pct.mean())}
    report = {"starting_capital": starting_capital, "ending_capital": equity,
              "net_pnl_usd": equity - starting_capital,
              "return_pct": (equity / starting_capital - 1) * 100,
              "opened": len(opened), "rejected": int((output.decision == "REJECT").sum()),
              "max_concurrent": max_concurrent, "max_drawdown_pct": _max_drawdown([v for _, v in equity_curve]),
              "profit_factor": float(wins / losses) if losses else None,
              "by_direction": by_direction,
              "rejection_reasons": output[output.decision == "REJECT"].reason.value_counts().to_dict(),
              "limitations": ["Development history, not untouched evidence.",
                              "Fixed paper notional; no broker execution or financing costs.",
                              "Portfolio outcomes use Dukascopy historical bid/ask labels."]}
    return output, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    events, report = simulate(pd.read_csv(args.dataset))
    args.events.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(args.events, index=False)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
