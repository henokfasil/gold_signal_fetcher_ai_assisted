#!/usr/bin/env python3
"""Relabel frozen SMC candidates with fixed-clock executable-side targets.

This does not regenerate or select candidates. It corrects the legacy
"N candles" expiry into a UTC clock horizon and adds registered 1h/4h/12h/48h
after-cost return and excursion targets from Dukascopy bid/ask candles.
"""

import argparse
import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from research.build_historical_dataset import load_ohlcv


LOG = logging.getLogger(__name__)
HORIZONS_HOURS = (1, 4, 12, 48)


def _utc_timestamp(value) -> pd.Timestamp:
    result = pd.Timestamp(value)
    return result.tz_localize("UTC") if result.tz is None else result.tz_convert("UTC")


def _net_move(direction, entry, exit_price, cost):
    gross = exit_price - entry if direction == "BUY" else entry - exit_price
    return gross - cost


def relabel(candidates: pd.DataFrame, source: pd.DataFrame,
            expiry_hours: int = 48, slippage_points: float = .10) -> pd.DataFrame:
    required_candidates = {
        "timestamp", "direction", "stop_loss", "take_profit",
    }
    required_source = {
        f"{side}_{field}" for side in ("bid", "ask")
        for field in ("open", "high", "low", "close")
    }
    if not required_candidates.issubset(candidates.columns):
        raise ValueError(f"candidate columns missing: {sorted(required_candidates - set(candidates))}")
    if not required_source.issubset(source.columns):
        raise ValueError(f"source columns missing: {sorted(required_source - set(source))}")
    if not source.index.is_monotonic_increasing or source.index.has_duplicates:
        raise ValueError("source timestamps must be ordered and unique")

    work = candidates.copy()
    candidate_times = pd.to_datetime(work["timestamp"], utc=True)
    # Pandas 3 may store DatetimeIndex values at microsecond resolution while
    # Timestamp.value remains nanoseconds. Normalize explicitly before binary
    # search and duration arithmetic.
    source_times = source.index.as_unit("ns").asi8
    arrays = {column: source[column].to_numpy(float) for column in required_source}
    cost = 2.0 * float(slippage_points)
    records = []

    for number, (row, decision_time) in enumerate(
            zip(work.itertuples(index=False), candidate_times), start=1):
        direction = str(row.direction).upper()
        if direction not in {"BUY", "SELL"}:
            raise ValueError(f"invalid direction {direction!r}")
        decision_ns = decision_time.value
        decision_pos = int(np.searchsorted(source_times, decision_ns, side="left"))
        if decision_pos >= len(source_times) or source_times[decision_pos] != decision_ns:
            raise ValueError(f"no exact decision candle for {decision_time.isoformat()}")

        entry_side = "ask" if direction == "BUY" else "bid"
        exit_side = "bid" if direction == "BUY" else "ask"
        executable_entry = float(arrays[f"{entry_side}_close"][decision_pos])
        stop, target = float(row.stop_loss), float(row.take_profit)
        start_pos = decision_pos + 1
        cutoff = decision_time + pd.Timedelta(hours=expiry_hours)
        cutoff_ns = cutoff.value
        barrier_end = int(np.searchsorted(source_times, cutoff_ns, side="right"))
        expiry_pos = int(np.searchsorted(source_times, cutoff_ns, side="left"))

        label_status = None
        exit_pos = None
        exit_price = np.nan
        monitor_slice = slice(start_pos, barrier_end)
        high = arrays[f"{exit_side}_high"][monitor_slice]
        low = arrays[f"{exit_side}_low"][monitor_slice]
        hit_tp = high >= target if direction == "BUY" else low <= target
        hit_sl = low <= stop if direction == "BUY" else high >= stop
        hits = np.flatnonzero(hit_tp | hit_sl)
        if len(hits):
            relative = int(hits[0])
            exit_pos = start_pos + relative
            if hit_tp[relative] and hit_sl[relative]:
                label_status = "AMBIGUOUS_SAME_BAR"
            elif hit_tp[relative]:
                label_status, exit_price = "TP", target
            else:
                label_status, exit_price = "SL", stop
        elif expiry_pos < len(source_times):
            label_status = "EXPIRY"
            exit_pos = expiry_pos
            exit_price = float(arrays[f"{exit_side}_close"][expiry_pos])
        else:
            label_status = "UNMATURED"

        result = {
            "executable_entry": executable_entry,
            "label_status": label_status,
            "exit_time": (
                pd.Timestamp(source_times[exit_pos], tz="UTC").isoformat()
                if exit_pos is not None else ""
            ),
            "net_return_pct": np.nan,
            "label_profitable": np.nan,
            "execution_label_source": "BID_ASK_FIXED_CLOCK",
            "label_duration_hours": (
                (source_times[exit_pos] - decision_ns) / 3_600_000_000_000
                if exit_pos is not None else np.nan
            ),
        }
        if label_status not in {"AMBIGUOUS_SAME_BAR", "UNMATURED"}:
            net_points = _net_move(direction, executable_entry, exit_price, cost)
            result["net_return_pct"] = net_points / executable_entry * 100
            result["label_profitable"] = int(net_points > 0)

        for horizon in HORIZONS_HOURS:
            horizon_time = decision_time + pd.Timedelta(hours=horizon)
            horizon_ns = horizon_time.value
            path_end = int(np.searchsorted(source_times, horizon_ns, side="right"))
            horizon_exit_pos = int(np.searchsorted(source_times, horizon_ns, side="left"))
            prefix = f"target_{horizon}h"
            if horizon_exit_pos >= len(source_times):
                result[f"{prefix}_net_return_pct"] = np.nan
                result[f"{prefix}_mfe_net_pct"] = np.nan
                result[f"{prefix}_mae_net_pct"] = np.nan
                result[f"{prefix}_actual_exit_hours"] = np.nan
                continue
            horizon_exit = float(arrays[f"{exit_side}_close"][horizon_exit_pos])
            result[f"{prefix}_net_return_pct"] = (
                _net_move(direction, executable_entry, horizon_exit, cost)
                / executable_entry * 100
            )
            result[f"{prefix}_actual_exit_hours"] = (
                (source_times[horizon_exit_pos] - decision_ns) / 3_600_000_000_000
            )
            path = slice(start_pos, path_end)
            path_high = arrays[f"{exit_side}_high"][path]
            path_low = arrays[f"{exit_side}_low"][path]
            if not len(path_high):
                result[f"{prefix}_mfe_net_pct"] = np.nan
                result[f"{prefix}_mae_net_pct"] = np.nan
            elif direction == "BUY":
                result[f"{prefix}_mfe_net_pct"] = (
                    float(path_high.max()) - executable_entry - cost
                ) / executable_entry * 100
                result[f"{prefix}_mae_net_pct"] = (
                    float(path_low.min()) - executable_entry - cost
                ) / executable_entry * 100
            else:
                result[f"{prefix}_mfe_net_pct"] = (
                    executable_entry - float(path_low.min()) - cost
                ) / executable_entry * 100
                result[f"{prefix}_mae_net_pct"] = (
                    executable_entry - float(path_high.max()) - cost
                ) / executable_entry * 100

        records.append(result)
        if number % 5000 == 0:
            LOG.info("relabeled %s/%s candidates", number, len(work))

    targets = pd.DataFrame(records, index=work.index)
    for column in targets:
        work[column] = targets[column]
    return work


def write_dataset(candidates_path: Path, source_path: Path, output: Path,
                  timestamp_is: str = "open", expiry_hours: int = 48,
                  slippage_points: float = .10) -> dict:
    candidates = pd.read_csv(candidates_path)
    source = load_ohlcv(source_path, timestamp_is)
    result = relabel(candidates, source, expiry_hours, slippage_points)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    result.to_csv(temporary, index=False)
    temporary.replace(output)
    durations = pd.to_numeric(result["label_duration_hours"], errors="coerce")
    manifest = {
        "schema_version": 1,
        "target_version": "bid_ask_fixed_clock_v1",
        "candidate_source": str(candidates_path),
        "candidate_source_sha256": hashlib.sha256(candidates_path.read_bytes()).hexdigest(),
        "price_source": str(source_path),
        "price_source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "dataset_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "rows": len(result),
        "expiry_hours_utc_clock": expiry_hours,
        "expiry_execution": "first executable 15M close at/after cutoff",
        "barrier_monitoring": "candidate close < bar close <= UTC cutoff",
        "post_cutoff_bar_range_used_for_barrier": False,
        "slippage_points_per_side": slippage_points,
        "spread": "observed bid/ask",
        "alternative_horizons_hours": list(HORIZONS_HOURS),
        "ambiguous_rows": int(result["label_status"].eq("AMBIGUOUS_SAME_BAR").sum()),
        "unmatured_rows": int(result["label_status"].eq("UNMATURED").sum()),
        "labels_over_48_clock_hours": int((durations > expiry_hours).sum()),
        "max_label_duration_hours": float(durations.max()),
        "research_warning": (
            "Candidate/feature design remains contaminated by inspected 2020-2026 history; "
            "new targets do not create an untouched test."
        ),
    }
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--timestamp-is", choices=("open", "close"), default="open")
    parser.add_argument("--expiry-hours", type=int, default=48)
    parser.add_argument("--slippage-points", type=float, default=.10)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = write_dataset(
        args.candidates, args.source, args.output, args.timestamp_is,
        args.expiry_hours, args.slippage_points,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
