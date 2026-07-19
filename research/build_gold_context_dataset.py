#!/usr/bin/env python3
"""Join registered gold-context v2 features to frozen candidates point in time."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.download_gold_context import (
    CONTRACT_PATH,
    EXPECTED_CONTRACT_SHA256,
    load_contract,
)


HORIZONS = (1, 4, 24)
CONTEXT_NAMES = ("dollar_idx", "silver", "volatility_idx", "treasury_bond")
CONTEXT_FEATURES = [
    feature
    for name in CONTEXT_NAMES
    for feature in (
        f"ctx_{name}_return_1h_pct",
        f"ctx_{name}_return_4h_pct",
        f"ctx_{name}_return_24h_pct",
        f"ctx_{name}_realized_volatility_24h_pct",
        f"ctx_{name}_staleness_minutes",
        f"ctx_{name}_missing",
    )
] + [
    "ctx_xau_xag_ratio_return_4h_pct",
    "ctx_xau_xag_ratio_return_24h_pct",
]


def load_context_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", "analysis_close"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{path} missing {sorted(required - set(frame.columns))}")
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame = frame.sort_values("timestamp")
    if frame.empty or not frame.timestamp.is_unique:
        raise ValueError(f"{path} is empty or has duplicate timestamps")
    frame["available_at"] = frame.timestamp + pd.Timedelta(hours=1)
    close = pd.to_numeric(frame.analysis_close, errors="coerce")
    if close.isna().any() or (close <= 0).any():
        raise ValueError(f"{path} has invalid analysis close")
    squared_log_return = np.log(close).diff().pow(2)
    frame["realized_volatility_24h_pct"] = (
        squared_log_return.set_axis(frame.available_at)
        .rolling("24h", min_periods=2).sum().pow(0.5).to_numpy() * 100
    )
    return frame[["available_at", "analysis_close", "realized_volatility_24h_pct"]]


def _asof(query_times: pd.Series, context: pd.DataFrame) -> pd.DataFrame:
    left = pd.DataFrame({"query_time": pd.to_datetime(query_times, utc=True)})
    left["row_order"] = np.arange(len(left))
    left = left.sort_values("query_time")
    right = context.sort_values("available_at")
    matched = pd.merge_asof(
        left, right, left_on="query_time", right_on="available_at",
        direction="backward", allow_exact_matches=True,
    )
    if ((matched.available_at.notna()) &
            (matched.available_at > matched.query_time)).any():
        raise RuntimeError("future context value joined to candidate")
    return matched.sort_values("row_order").reset_index(drop=True)


def instrument_features(query_times: pd.Series, context: pd.DataFrame,
                        name: str, max_staleness_minutes: int) -> pd.DataFrame:
    current = _asof(query_times, context)
    staleness = (
        current.query_time - current.available_at
    ).dt.total_seconds() / 60
    current_valid = current.analysis_close.notna() & staleness.le(max_staleness_minutes)
    result = pd.DataFrame(index=np.arange(len(current)))
    for horizon in HORIZONS:
        reference_query = pd.to_datetime(query_times, utc=True) - pd.Timedelta(hours=horizon)
        prior = _asof(reference_query, context)
        prior_staleness = (
            prior.query_time - prior.available_at
        ).dt.total_seconds() / 60
        valid = (
            current_valid & prior.analysis_close.notna() &
            prior_staleness.le(max_staleness_minutes)
        )
        values = (current.analysis_close / prior.analysis_close - 1.0) * 100
        result[f"ctx_{name}_return_{horizon}h_pct"] = values.where(valid).to_numpy()
    result[f"ctx_{name}_realized_volatility_24h_pct"] = (
        current.realized_volatility_24h_pct.where(current_valid).to_numpy()
    )
    result[f"ctx_{name}_staleness_minutes"] = staleness.to_numpy()
    result[f"ctx_{name}_missing"] = (~current_valid).astype(int).to_numpy()
    return result


def _load_xau(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if not {"timestamp", "close"}.issubset(frame.columns):
        raise ValueError("XAU source requires timestamp and midpoint close")
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame = frame.sort_values("timestamp")
    if frame.empty or not frame.timestamp.is_unique:
        raise ValueError("XAU source is empty or duplicated")
    frame["available_at"] = frame.timestamp + pd.Timedelta(minutes=15)
    frame["analysis_close"] = pd.to_numeric(frame.close, errors="coerce")
    return frame[["available_at", "analysis_close"]]


def ratio_features(query_times: pd.Series, xau: pd.DataFrame, silver: pd.DataFrame,
                   max_staleness_minutes: int) -> pd.DataFrame:
    result = pd.DataFrame(index=np.arange(len(query_times)))
    for horizon in (4, 24):
        now_xau = _asof(query_times, xau)
        now_silver = _asof(query_times, silver)
        reference = pd.to_datetime(query_times, utc=True) - pd.Timedelta(hours=horizon)
        old_xau = _asof(reference, xau)
        old_silver = _asof(reference, silver)
        frames = ((now_xau, pd.to_datetime(query_times, utc=True)),
                  (now_silver, pd.to_datetime(query_times, utc=True)),
                  (old_xau, reference), (old_silver, reference))
        valid = pd.Series(True, index=np.arange(len(query_times)))
        for matched, expected_time in frames:
            staleness = (
                pd.Series(expected_time).reset_index(drop=True) - matched.available_at
            ).dt.total_seconds() / 60
            valid &= matched.analysis_close.notna() & staleness.le(max_staleness_minutes)
        current_ratio = now_xau.analysis_close / now_silver.analysis_close
        old_ratio = old_xau.analysis_close / old_silver.analysis_close
        result[f"ctx_xau_xag_ratio_return_{horizon}h_pct"] = (
            (current_ratio / old_ratio - 1.0) * 100
        ).where(valid).to_numpy()
    return result


def build(candidates_path: Path, xau_path: Path, context_dir: Path,
          output: Path, contract_path: Path = CONTRACT_PATH) -> dict:
    contract, contract_sha = load_contract(contract_path)
    manifest_path = context_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("contract_sha256") != contract_sha or
            manifest.get("contract_version") != contract["contract_version"]):
        raise RuntimeError("context input manifest does not match frozen contract")
    for name in CONTEXT_NAMES:
        source = context_dir / f"{name}_1h.csv"
        expected = manifest["instruments"][name]["file_sha256"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"{name} context input hash mismatch")

    candidates = pd.read_csv(candidates_path)
    candidates["timestamp"] = pd.to_datetime(candidates.timestamp, utc=True)
    if not candidates.timestamp.is_monotonic_increasing:
        raise ValueError("candidate timestamps must be chronological")
    query_times = candidates.timestamp
    max_staleness = int(contract["join_contract"]["maximum_staleness_minutes"])
    contexts = {
        name: load_context_frame(context_dir / f"{name}_1h.csv")
        for name in CONTEXT_NAMES
    }
    additions = []
    for name in CONTEXT_NAMES:
        additions.append(instrument_features(query_times, contexts[name], name, max_staleness))
    additions.append(ratio_features(
        query_times, _load_xau(xau_path), contexts["silver"], max_staleness,
    ))
    features = pd.concat(additions, axis=1)
    if list(features.columns) != CONTEXT_FEATURES:
        raise RuntimeError("generated context feature schema differs from registration")
    result = pd.concat([candidates.reset_index(drop=True), features], axis=1)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    result.to_csv(temporary, index=False)
    temporary.replace(output)
    report = {
        "schema_version": 1,
        "contract_version": contract["contract_version"],
        "contract_sha256": contract_sha,
        "candidate_source": str(candidates_path),
        "candidate_source_sha256": hashlib.sha256(candidates_path.read_bytes()).hexdigest(),
        "xau_source": str(xau_path),
        "xau_source_sha256": hashlib.sha256(xau_path.read_bytes()).hexdigest(),
        "context_manifest": str(manifest_path),
        "context_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "rows": len(result),
        "context_features": CONTEXT_FEATURES,
        "missing_fraction": {
            column: float(result[column].isna().mean())
            for column in CONTEXT_FEATURES if not column.endswith("_missing")
        },
        "explicit_missing_rate": {
            name: float(result[f"ctx_{name}_missing"].mean()) for name in CONTEXT_NAMES
        },
        "dataset_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "research_warning": "2020-2026 is development-contaminated; context joining creates no untouched test.",
    }
    output.with_suffix(output.suffix + ".manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument("xau_source", type=Path)
    parser.add_argument("context_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args()
    report = build(
        args.candidates, args.xau_source, args.context_dir, args.output, args.contract,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
