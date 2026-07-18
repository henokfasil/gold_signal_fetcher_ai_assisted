#!/usr/bin/env python3
"""Compare an OANDA TradingView 15M snapshot with Dukascopy bid/ask history.

This measures price concordance only. It refuses to claim candidate concordance
when the TradingView snapshot lacks genuine higher-timeframe bars.
"""

import argparse
import json
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd


def _frame_metrics(joined, suffix_a="_oanda", suffix_b="_dukascopy"):
    metrics = {}
    for column in ("open", "high", "low", "close"):
        left = joined[f"{column}{suffix_a}"].astype(float)
        right = joined[f"{column}{suffix_b}"].astype(float)
        difference = left - right
        metrics[column] = {
            "mean_absolute_difference_points": float(difference.abs().mean()),
            "median_bias_points": float(difference.median()),
            "max_absolute_difference_points": float(difference.abs().max()),
            "correlation": float(left.corr(right)),
        }
    oanda_direction = np.sign(
        joined[f"close{suffix_a}"] - joined[f"open{suffix_a}"]
    )
    dukascopy_direction = np.sign(
        joined[f"close{suffix_b}"] - joined[f"open{suffix_b}"]
    )
    metrics["bar_direction_agreement"] = float((oanda_direction == dukascopy_direction).mean())
    return metrics


def _aggregate(frame, rule):
    return (frame.set_index("timestamp").resample(rule, label="left", closed="left")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna().reset_index())


def compare(dukascopy_path, snapshot_path):
    payload = json.loads(Path(snapshot_path).read_text())
    if payload.get("symbol") != "OANDA:XAUUSD":
        raise ValueError("snapshot is not exact OANDA:XAUUSD")
    oanda = pd.DataFrame(payload["timeframes"]["15M"]["bars"])
    oanda["timestamp"] = pd.to_datetime(oanda["time"], unit="s", utc=True)
    intervals = np.diff(oanda.time.astype(int))
    if not len(intervals) or abs(float(median(intervals)) - 900) > 45:
        raise ValueError("snapshot 15M cadence is invalid")
    oanda = oanda[["timestamp", "open", "high", "low", "close"]].copy()

    dukascopy = pd.read_csv(dukascopy_path)
    dukascopy["timestamp"] = pd.to_datetime(dukascopy.timestamp, utc=True)
    start, end = oanda.timestamp.min(), oanda.timestamp.max()
    dukascopy = dukascopy[
        dukascopy.timestamp.between(start, end)
    ][["timestamp", "open", "high", "low", "close"]].copy()
    joined = oanda.merge(
        dukascopy, on="timestamp", how="inner", suffixes=("_oanda", "_dukascopy"),
        validate="one_to_one",
    )
    if joined.empty:
        raise ValueError("feeds have no overlapping timestamps")

    aggregates = {}
    for name, rule in (("1H_FROM_15M", "1h"), ("4H_FROM_15M", "4h")):
        left = _aggregate(oanda, rule)
        right = _aggregate(dukascopy, rule)
        combined = left.merge(
            right, on="timestamp", suffixes=("_oanda", "_dukascopy"), validate="one_to_one"
        )
        aggregates[name] = {
            "matched_bars": len(combined),
            "metrics": _frame_metrics(combined),
        }

    frame_fingerprints = {
        name: json.dumps(data.get("bars", []), sort_keys=True, separators=(",", ":"))
        for name, data in payload.get("timeframes", {}).items()
    }
    true_multitimeframe = (
        len(frame_fingerprints) == 5 and len(set(frame_fingerprints.values())) == 5
    )
    return {
        "status": "PRELIMINARY_PRICE_CONCORDANCE_ONLY",
        "oanda_source": "TradingView MCP OANDA:XAUUSD 15M snapshot",
        "dukascopy_source": str(dukascopy_path),
        "snapshot_captured_at": payload.get("captured_at"),
        "overlap": {
            "oanda_bars": len(oanda), "dukascopy_bars": len(dukascopy),
            "matched_bars": len(joined),
            "match_rate_oanda": float(len(joined) / len(oanda)),
            "start": joined.timestamp.min().isoformat(),
            "end": joined.timestamp.max().isoformat(),
        },
        "15M": _frame_metrics(joined),
        "aggregated_from_matched_15M": aggregates,
        "true_multitimeframe_snapshot": true_multitimeframe,
        "candidate_membership_concordance": (
            "NOT_EVALUABLE_MCP_RETURNED_DUPLICATED_15M_PAYLOADS"
            if not true_multitimeframe else "REQUIRES_POINT_IN_TIME_REPLAY"
        ),
        "limitations": [
            "Only 200 OANDA 15M bars are available in this snapshot.",
            "Aggregated 1H/4H comparisons cover the same short 15M overlap, not 200 native bars.",
            "Price correlation does not establish SMC candidate-membership agreement.",
            "TradingView MCP currently returns duplicated 15M bars after timeframe changes.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dukascopy", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.dukascopy, args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
