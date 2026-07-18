#!/usr/bin/env python3
"""Replay the live SMC candidate generator over historical 15-minute OHLCV.

Input timestamps are candle OPEN times by default. A row is made visible only
at its close, preventing the current candle's high/low/close from leaking into
the decision. Output contains candidates only, with cost-adjusted labels based
on subsequent 15-minute bars.
"""

import argparse
import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from agent.ml_feature_engineer_gold import GoldFeatureEngineer
from agent.smc_gold_scanner import _run_smc_analysis

LOG = logging.getLogger(__name__)
TF_RULES = {"1W": "W-FRI", "1D": "1D", "4H": "4h", "1H": "1h", "15M": "15min"}
MINIMUMS = {"1W": 52, "1D": 52, "4H": 52, "1H": 52, "15M": 52}


def load_ohlcv(path: Path, timestamp_is: str = "open") -> pd.DataFrame:
    frame = pd.read_csv(path)
    aliases = {str(c).strip().lower().replace(" ", "_"): c for c in frame.columns}
    time_col = next((aliases[k] for k in ("timestamp", "time", "datetime", "date") if k in aliases), None)
    if time_col is None:
        raise ValueError("input needs timestamp/time/datetime/date column")
    rename = {aliases[name]: name for name in ("open", "high", "low", "close", "volume") if name in aliases}
    frame = frame.rename(columns=rename)
    required = ["open", "high", "low", "close"]
    missing = [c for c in required if c not in frame]
    if missing:
        raise ValueError(f"input missing OHLC columns: {', '.join(missing)}")
    if "volume" not in frame:
        frame["volume"] = 0.0
    frame["timestamp"] = pd.to_datetime(frame[time_col], utc=True, errors="raise")
    optional = [f"{side}_{field}" for side in ("bid", "ask")
                for field in ("open", "high", "low", "close") if f"{side}_{field}" in frame]
    frame = frame[["timestamp", "open", "high", "low", "close", "volume", *optional]].copy()
    for column in ("open", "high", "low", "close", "volume", *optional):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    valid = ((frame[["open", "high", "low", "close"]] > 0).all(axis=1)
             & (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
             & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)))
    if not valid.all():
        raise ValueError(f"{int((~valid).sum())} malformed OHLC rows")
    if timestamp_is == "open":
        frame["timestamp"] += pd.Timedelta(minutes=15)
    frame = frame.set_index("timestamp")
    return frame


def resample_closed_bars(source: pd.DataFrame, rule: str) -> pd.DataFrame:
    result = source.resample(rule, label="right", closed="right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["open", "high", "low", "close"])
    result["timestamp"] = result.index
    return result


def label_candidate(signal: dict, future: pd.DataFrame, expiry_hours: int,
                    spread_points: float, slippage_points: float,
                    decision_bar: pd.Series = None, candidate_time=None) -> dict:
    direction = signal["direction"]
    entry, stop, target = map(float, (signal["price"], signal["stop_loss"], signal["take_profit"]))
    has_quotes = (decision_bar is not None and
                  all(f"{side}_{field}" in future.columns for side in ("bid", "ask")
                      for field in ("high", "low", "close")) and
                  "ask_close" in decision_bar and "bid_close" in decision_bar)
    if has_quotes:
        executable_entry = float(decision_bar["ask_close"] if direction == "BUY"
                                 else decision_bar["bid_close"])
        cost = 2.0 * float(slippage_points)
        side = "bid" if direction == "BUY" else "ask"
    else:
        executable_entry, cost, side = entry, float(spread_points) + 2.0 * float(slippage_points), None
    if candidate_time is None:
        # Compatibility for callers without an explicit decision time. Dataset
        # construction always supplies candidate_time and uses clock time.
        horizon = future.iloc[: max(1, expiry_hours * 4)]
        expiry_bar = horizon.iloc[-1:] if not horizon.empty else horizon
    else:
        decision_time = pd.Timestamp(candidate_time)
        decision_time = (decision_time.tz_localize("UTC") if decision_time.tz is None
                         else decision_time.tz_convert("UTC"))
        cutoff = decision_time + pd.Timedelta(hours=expiry_hours)
        # Barrier monitoring ends at the fixed UTC cutoff. When the market is
        # closed then, liquidation uses the first executable close afterward
        # without using that post-cutoff candle's range to invent a TP or SL.
        horizon = future.loc[future.index <= cutoff]
        expiry_bar = future.loc[future.index >= cutoff].iloc[:1]
    for timestamp, bar in horizon.iterrows():
        high = bar[f"{side}_high"] if side else bar["high"]
        low = bar[f"{side}_low"] if side else bar["low"]
        hit_tp = high >= target if direction == "BUY" else low <= target
        hit_sl = low <= stop if direction == "BUY" else high >= stop
        if hit_tp and hit_sl:
            return {"label_profitable": np.nan, "label_status": "AMBIGUOUS_SAME_BAR",
                    "exit_time": timestamp.isoformat(), "net_return_pct": np.nan}
        if hit_tp or hit_sl:
            gross_points = (target - executable_entry if direction == "BUY" else executable_entry - target) if hit_tp else \
                           (stop - executable_entry if direction == "BUY" else executable_entry - stop)
            net_points = gross_points - cost
            return {"label_profitable": int(net_points > 0),
                    "label_status": "TP" if hit_tp else "SL", "exit_time": timestamp.isoformat(),
            "net_return_pct": net_points / executable_entry * 100,
            "execution_label_source": "BID_ASK" if has_quotes else "MIDPOINT_COST_ASSUMPTION"}
    if expiry_bar.empty:
        return {"label_profitable": np.nan, "label_status": "UNMATURED",
                "exit_time": "", "net_return_pct": np.nan}
    exit_price = float(expiry_bar.iloc[0][f"{side}_close"] if side else expiry_bar.iloc[0]["close"])
    gross_points = exit_price - executable_entry if direction == "BUY" else executable_entry - exit_price
    net_points = gross_points - cost
    return {"label_profitable": int(net_points > 0), "label_status": "EXPIRY",
            "exit_time": expiry_bar.index[0].isoformat(), "net_return_pct": net_points / executable_entry * 100,
            "execution_label_source": "BID_ASK" if has_quotes else "MIDPOINT_COST_ASSUMPTION"}


def build(source: pd.DataFrame, scan_minutes: int = 15, expiry_hours: int = 48,
          spread_points: float = 0.35, slippage_points: float = 0.10) -> pd.DataFrame:
    frames = {name: resample_closed_bars(source, rule) for name, rule in TF_RULES.items()}
    first_time = max(frame.index[MINIMUMS[name] - 1] for name, frame in frames.items()
                     if len(frame) >= MINIMUMS[name])
    rows, last_candidate = [], None
    scan_times = frames["15M"].index[frames["15M"].index >= first_time]
    step = max(1, scan_minutes // 15)
    for position, as_of in enumerate(scan_times[::step]):
        sliced = {}
        for name, frame in frames.items():
            visible = frame.loc[:as_of].tail(200).copy()
            if len(visible) < MINIMUMS[name]:
                break
            sliced[name] = visible.reset_index(drop=True)
        if len(sliced) != 5:
            continue
        signal = _run_smc_analysis(sliced["1W"], sliced["1D"], sliced["4H"], sliced["1H"],
                                   sliced["15M"], "OANDA:XAUUSD", "HISTORICAL_REPLAY", as_of.to_pydatetime())
        if not signal:
            continue
        dedup_key = (signal["direction"], round(float(signal["price"]), 1))
        if last_candidate and dedup_key == last_candidate[0] and as_of - last_candidate[1] <= pd.Timedelta(minutes=30):
            continue
        last_candidate = (dedup_key, as_of)
        vector = signal.get("ml_feature_vector")
        if vector is None:
            continue
        future = source.loc[source.index > as_of]
        decision_bar = source.loc[as_of]
        if isinstance(decision_bar, pd.DataFrame):
            decision_bar = decision_bar.iloc[-1]
        label = label_candidate(
            signal, future, expiry_hours, spread_points, slippage_points,
            decision_bar, candidate_time=as_of,
        )
        row = {"timestamp": as_of.isoformat(), "pair": "OANDA:XAUUSD",
               "direction": signal["direction"], "entry": signal["price"],
               "stop_loss": signal["stop_loss"], "take_profit": signal["take_profit"],
               "rr_ratio": signal["rr_ratio"], "smc_score": signal["score"],
               **dict(zip(GoldFeatureEngineer.FEATURE_COLS, vector)), **label}
        rows.append(row)
        if position and position % 1000 == 0:
            LOG.info("processed %s scan points; %s candidates", position, len(rows))
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="15-minute XAUUSD OHLCV CSV")
    parser.add_argument("output", type=Path, help="versioned candidate dataset CSV")
    parser.add_argument("--timestamp-is", choices=("open", "close"), default="open")
    parser.add_argument("--scan-minutes", type=int, default=15)
    parser.add_argument("--expiry-hours", type=int, default=48)
    parser.add_argument("--spread-points", type=float, default=0.35)
    parser.add_argument("--slippage-points", type=float, default=0.10)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # The live scanner emits several INFO lines per decision. Historical replay
    # can contain 100k+ decision points, so retain warnings and periodic builder
    # progress without producing gigabytes of logs.
    logging.getLogger("agent.smc_gold_scanner").setLevel(logging.WARNING)
    source = load_ohlcv(args.input, args.timestamp_is)
    result = build(source, args.scan_minutes, args.expiry_hours, args.spread_points, args.slippage_points)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    manifest = {"schema_version": 1, "source": str(args.input.resolve()),
                "source_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
                "dataset_sha256": digest, "rows": len(result),
                "timestamp_semantics": args.timestamp_is, "scan_minutes": args.scan_minutes,
                "expiry_hours": args.expiry_hours, "spread_points": args.spread_points,
                "slippage_points_per_side": args.slippage_points,
                "horizon_semantics": "fixed UTC clock hours; first executable close at/after cutoff",
                "ambiguous_rows": int((result.get("label_status") == "AMBIGUOUS_SAME_BAR").sum()) if len(result) else 0,
                "warning": "Research labels from 15-minute OHLC; same-bar TP/SL ordering is excluded."}
    args.output.with_suffix(args.output.suffix + ".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
