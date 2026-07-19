#!/usr/bin/env python3
"""Build the hash-locked execution-state v1 candidate dataset point in time."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


CONTRACT_PATH = Path("config/execution_state_v1.json")
EXPECTED_CONTRACT_SHA256 = "e2931d0f80525ca9f9b16d3f9ab2ca5c710b99f41a70dfd08ac8921adecf2232"
EXECUTION_FEATURES = [
    "exec_spread_close_points",
    "exec_spread_close_bps",
    "exec_spread_to_atr_1h",
    "exec_spread_median_96bars_points",
    "exec_spread_ratio_to_median_96bars",
    "exec_spread_percentile_480bars",
    "exec_spread_change_4bars_points",
    "exec_mid_return_4bars_pct",
    "exec_mid_return_16bars_pct",
    "exec_mid_return_96bars_pct",
    "exec_realized_volatility_4bars_pct",
    "exec_realized_volatility_16bars_pct",
    "exec_realized_volatility_96bars_pct",
    "exec_volatility_16bars_percentile_1920bars",
    "exec_true_range_bps",
    "exec_gap_from_previous_close_bps",
    "exec_session_range_bps",
    "exec_distance_to_session_high_bps",
    "exec_distance_to_session_low_bps",
    "exec_bars_since_market_reopen",
    "exec_minute_of_day_sin",
    "exec_minute_of_day_cos",
    "exec_window_asia",
    "exec_window_london_pre_overlap",
    "exec_window_london_new_york_overlap",
    "exec_window_new_york_late",
    "exec_window_rollover",
    "exec_tick_volume_side_imbalance",
    "exec_tick_volume_ratio_to_median_96bars",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _schema_sha256(columns: list[str]) -> str:
    raw = json.dumps(columns, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def load_contract(path: Path = CONTRACT_PATH) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    contract = json.loads(raw)
    feature_contract = contract.get("feature_contract", {})
    if digest != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("execution-state contract hash mismatch; register a new version")
    if (contract.get("schema_version") != 1 or
            contract.get("contract_version") != "execution-state-20260719-v1" or
            contract.get("paper_research_only") is not True or
            feature_contract.get("registered_features") != EXECUTION_FEATURES or
            feature_contract.get("schema_sha256") != _schema_sha256(EXECUTION_FEATURES) or
            int(feature_contract.get("feature_count", -1)) != len(EXECUTION_FEATURES)):
        raise RuntimeError("execution-state contract feature schema mismatch")
    return contract, digest


def load_raw_bars(path: Path) -> pd.DataFrame:
    required = {
        "timestamp", "bid_open", "bid_high", "bid_low", "bid_close", "bid_volume",
        "ask_open", "ask_high", "ask_low", "ask_close", "ask_volume",
        "open", "high", "low", "close", "volume", "spread_open", "spread_close",
    }
    frame = pd.read_csv(path)
    if not required.issubset(frame.columns):
        raise ValueError(f"raw execution source missing {sorted(required - set(frame.columns))}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    if frame.empty or frame["timestamp"].duplicated().any():
        raise ValueError("raw execution source is empty or has duplicate timestamps")
    numeric_columns = sorted(required - {"timestamp"})
    numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("raw execution source contains non-finite values")
    for prefix in ("bid_", "ask_", ""):
        o, high, low, close = (frame[f"{prefix}{field}"]
                               for field in ("open", "high", "low", "close"))
        if ((o <= 0) | (high <= 0) | (low <= 0) | (close <= 0) |
                (high < pd.concat([o, close, low], axis=1).max(axis=1)) |
                (low > pd.concat([o, close, high], axis=1).min(axis=1))).any():
            raise ValueError(f"raw execution source has invalid {prefix or 'midpoint_'}OHLC")
    if ((frame["ask_open"] < frame["bid_open"]) |
            (frame["ask_close"] < frame["bid_close"])).any():
        raise ValueError("raw execution source contains negative observed spread")
    frame["available_at"] = frame["timestamp"] + pd.Timedelta(minutes=15)
    return frame


def compute_execution_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Compute backward-only features for every completed raw candle."""
    frame = raw.copy().sort_values("available_at").reset_index(drop=True)
    close = pd.to_numeric(frame["close"], errors="coerce")
    open_price = pd.to_numeric(frame["open"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    spread = pd.to_numeric(frame["spread_close"], errors="coerce")
    log_return = np.log(close).diff()
    result = pd.DataFrame({"timestamp": frame["available_at"]})

    spread_median = spread.rolling(96, min_periods=96).median()
    result["exec_spread_close_points"] = spread
    result["exec_spread_close_bps"] = spread / close * 10_000
    # Filled after the exact candidate join because the registered 1H ATR is
    # already a causal candidate-time field in the canonical feature schema.
    result["exec_spread_to_atr_1h"] = np.nan
    result["exec_spread_median_96bars_points"] = spread_median
    result["exec_spread_ratio_to_median_96bars"] = spread / spread_median
    result["exec_spread_percentile_480bars"] = (
        spread.rolling(480, min_periods=480).rank(pct=True)
    )
    result["exec_spread_change_4bars_points"] = spread - spread.shift(4)

    for bars in (4, 16, 96):
        result[f"exec_mid_return_{bars}bars_pct"] = close.pct_change(
            bars, fill_method=None,
        ) * 100
        result[f"exec_realized_volatility_{bars}bars_pct"] = (
            log_return.pow(2).rolling(bars, min_periods=bars).sum().pow(0.5) * 100
        )
    result["exec_volatility_16bars_percentile_1920bars"] = (
        result["exec_realized_volatility_16bars_pct"]
        .rolling(1920, min_periods=1920).rank(pct=True)
    )

    previous_close = close.shift(1)
    true_range = pd.concat([
        high - low, (high - previous_close).abs(), (low - previous_close).abs(),
    ], axis=1).max(axis=1)
    result["exec_true_range_bps"] = true_range / close * 10_000
    result["exec_gap_from_previous_close_bps"] = (
        (open_price - previous_close) / previous_close * 10_000
    )

    minutes = frame["available_at"].dt.hour * 60 + frame["available_at"].dt.minute
    windows = np.select(
        [minutes.lt(420), minutes.lt(720), minutes.lt(960), minutes.lt(1260)],
        [0, 1, 2, 3], default=4,
    ).astype(int)
    session_key = frame["available_at"].dt.strftime("%Y-%m-%d") + "-" + pd.Series(
        windows, index=frame.index,
    ).astype(str)
    session_high = high.groupby(session_key).cummax()
    session_low = low.groupby(session_key).cummin()
    result["exec_session_range_bps"] = (session_high - session_low) / close * 10_000
    result["exec_distance_to_session_high_bps"] = (session_high - close) / close * 10_000
    result["exec_distance_to_session_low_bps"] = (close - session_low) / close * 10_000

    gaps = frame["available_at"].diff().dt.total_seconds()
    reopen_group = gaps.gt(1800).fillna(True).cumsum()
    result["exec_bars_since_market_reopen"] = frame.groupby(reopen_group).cumcount()
    angle = 2 * np.pi * minutes / 1440.0
    result["exec_minute_of_day_sin"] = np.sin(angle)
    result["exec_minute_of_day_cos"] = np.cos(angle)
    for code, name in enumerate((
        "asia", "london_pre_overlap", "london_new_york_overlap",
        "new_york_late", "rollover",
    )):
        result[f"exec_window_{name}"] = (windows == code).astype(int)

    bid_volume = pd.to_numeric(frame["bid_volume"], errors="coerce")
    ask_volume = pd.to_numeric(frame["ask_volume"], errors="coerce")
    total_volume = bid_volume + ask_volume
    volume_median = total_volume.rolling(96, min_periods=96).median()
    result["exec_tick_volume_side_imbalance"] = (
        (bid_volume - ask_volume) / total_volume.replace(0, np.nan)
    )
    result["exec_tick_volume_ratio_to_median_96bars"] = total_volume / volume_median
    return result[["timestamp", *EXECUTION_FEATURES]]


def join_candidate_features(candidates: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    work = candidates.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    if not work["timestamp"].is_monotonic_increasing:
        work = work.sort_values("timestamp").reset_index(drop=True)
    joined = work.merge(features, on="timestamp", how="left", validate="many_to_one")
    joined["exec_spread_to_atr_1h"] = (
        joined["exec_spread_close_points"] /
        pd.to_numeric(joined["atr_14"], errors="coerce").replace(0, np.nan)
    )
    return joined


def build(candidates_path: Path, raw_path: Path, output: Path,
          contract_path: Path = CONTRACT_PATH) -> dict:
    contract, contract_sha = load_contract(contract_path)
    source = contract["source_contract"]
    if _sha256(raw_path) != source["raw_file_sha256"]:
        raise RuntimeError("execution raw source hash mismatch")
    if _sha256(candidates_path) != source["candidate_file_sha256"]:
        raise RuntimeError("candidate source hash mismatch")
    raw = load_raw_bars(raw_path)
    features = compute_execution_features(raw)
    candidates = pd.read_csv(candidates_path)
    result = join_candidate_features(candidates, features)
    if len(result) != len(candidates):
        raise RuntimeError("execution-state join changed candidate row count")
    if list(result.columns[-len(EXECUTION_FEATURES):]) != EXECUTION_FEATURES:
        raise RuntimeError("execution-state output schema differs from registration")
    feature_values = result[EXECUTION_FEATURES].apply(pd.to_numeric, errors="coerce")
    missing = feature_values.isna().mean()
    if missing.any():
        raise RuntimeError(f"registered candidate features contain missing values: {missing[missing > 0].to_dict()}")
    if not np.isfinite(feature_values.to_numpy(dtype=float)).all():
        raise RuntimeError("registered candidate features contain non-finite values")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    result.to_csv(temporary, index=False)
    temporary.replace(output)
    report = {
        "schema_version": 1,
        "contract_version": contract["contract_version"],
        "contract_sha256": contract_sha,
        "candidate_source": str(candidates_path),
        "candidate_source_sha256": _sha256(candidates_path),
        "raw_source": str(raw_path),
        "raw_source_sha256": _sha256(raw_path),
        "raw_rows": len(raw),
        "candidate_rows": len(result),
        "first_candidate": result["timestamp"].iloc[0].isoformat(),
        "last_candidate": result["timestamp"].iloc[-1].isoformat(),
        "feature_count": len(EXECUTION_FEATURES),
        "feature_schema_sha256": _schema_sha256(EXECUTION_FEATURES),
        "feature_missing_fraction": {name: float(missing[name]) for name in EXECUTION_FEATURES},
        "exact_timestamp_join": True,
        "future_or_nearest_join_used": False,
        "dataset_sha256": _sha256(output),
        "builder_script_sha256": _sha256(Path(__file__)),
        "commercial_rights_status": contract["commercial_rights_status"],
        "research_warning": "2020-2026 is development-contaminated; this dataset does not establish an edge.",
    }
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    manifest_temporary.write_text(json.dumps(report, indent=2) + "\n")
    manifest_temporary.replace(manifest_path)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument("raw_source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args()
    report = build(args.candidates, args.raw_source, args.output, args.contract)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
