#!/usr/bin/env python3
"""Download the hash-locked gold-context v2 candle inputs.

The raw files are local research inputs and are not committed.  Interrupted
downloads resume from per-instrument/per-side checkpoints.  The volatility
proxy is deliberately bid-only because source preflight exposed no ask series;
the remaining instruments require exact one-to-one bid/ask joins.
"""

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


CONTRACT_PATH = Path("config/gold_context_v2.json")
EXPECTED_CONTRACT_SHA256 = "a8d2f252ce2b4f06a0828a8b0639088e5fae216b8559134a79e89175e5462e50"
FIELDS = ("open", "high", "low", "close", "volume")


def load_contract(path: Path = CONTRACT_PATH) -> tuple[dict, str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("gold-context contract hash mismatch; register a new version")
    contract = json.loads(raw)
    if (contract.get("contract_version") != "gold-context-20260719-v2" or
            contract.get("provider", {}).get("raw_candle_interval") != "1H"):
        raise RuntimeError("unsupported gold-context contract")
    return contract, digest


def _fetch(symbol: str, start: datetime, end: datetime, side: str) -> pd.DataFrame:
    import dukascopy_python as dukascopy

    offer_side = dukascopy.OFFER_SIDE_BID if side == "bid" else dukascopy.OFFER_SIDE_ASK
    frame = dukascopy.fetch(
        symbol, dukascopy.INTERVAL_HOUR_1, offer_side,
        start, end, max_retries=5,
    )
    if frame is None or frame.empty:
        empty = pd.DataFrame(columns=list(FIELDS))
        empty.index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
        return empty
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame.index.name = "timestamp"
    return frame[list(FIELDS)].sort_index()


def combine_sides(frames: dict[str, pd.DataFrame], required_sides: list[str]) -> pd.DataFrame:
    if required_sides == ["bid"]:
        result = frames["bid"].add_prefix("bid_")
        for field in FIELDS:
            result[f"analysis_{field}"] = result[f"bid_{field}"]
        return result
    if required_sides != ["bid", "ask"]:
        raise ValueError(f"unsupported required sides: {required_sides}")
    result = frames["bid"].add_prefix("bid_").join(
        frames["ask"].add_prefix("ask_"), how="inner", validate="one_to_one",
    )
    if result.empty:
        raise RuntimeError("bid/ask context join is empty")
    for field in ("open", "high", "low", "close"):
        result[f"analysis_{field}"] = (
            result[f"bid_{field}"] + result[f"ask_{field}"]
        ) / 2.0
    result["analysis_volume"] = result[["bid_volume", "ask_volume"]].mean(axis=1)
    result["spread_open"] = result["ask_open"] - result["bid_open"]
    result["spread_close"] = result["ask_close"] - result["bid_close"]
    return result


def _download_side(symbol: str, side: str, start: datetime, end: datetime,
                   checkpoints: Path, chunk_days: int) -> pd.DataFrame:
    paths = []
    cursor = start
    while cursor < end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days))
        path = checkpoints / f"{side}-{cursor:%Y%m%d}-{chunk_end:%Y%m%d}.csv"
        if not path.exists() or path.stat().st_size == 0:
            print(
                f"fetching {symbol} {side} {cursor.date()} through {chunk_end.date()}",
                flush=True,
            )
            frame = _fetch(symbol, cursor, chunk_end, side)
            temporary = path.with_suffix(".tmp")
            frame.to_csv(temporary)
            temporary.replace(path)
        else:
            print(f"reusing checkpoint {path}", flush=True)
        paths.append(path)
        cursor = chunk_end
    frames = [pd.read_csv(path, parse_dates=["timestamp"]) for path in paths]
    result = pd.concat(frames, ignore_index=True)
    result["timestamp"] = pd.to_datetime(result.timestamp, utc=True)
    result = result[
        (result.timestamp >= start) &
        (result.timestamp + pd.Timedelta(hours=1) <= end)
    ]
    result = result.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    if result.empty or not result.timestamp.is_unique or not result.timestamp.is_monotonic_increasing:
        raise RuntimeError(f"{symbol} {side} result is empty, duplicated or unordered")
    return result.set_index("timestamp")[list(FIELDS)]


def download(start: datetime, end: datetime, output_dir: Path,
             chunk_days: int = 90, contract_path: Path = CONTRACT_PATH) -> dict:
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("ordered timezone-aware start/end required")
    contract, contract_sha = load_contract(contract_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports = {}
    for name, spec in contract["instruments"].items():
        symbol = spec["provider_symbol"]
        required_sides = spec["required_sides"]
        checkpoint_dir = output_dir / f".{name}_chunks"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        frames = {
            side: _download_side(
                symbol, side, start, end, checkpoint_dir, chunk_days,
            )
            for side in required_sides
        }
        combined = combine_sides(frames, required_sides).sort_index()
        combined.index.name = "timestamp"
        if combined.index.has_duplicates or not combined.index.is_monotonic_increasing:
            raise RuntimeError(f"{name}: combined timestamps invalid")
        output = output_dir / f"{name}_1h.csv"
        temporary = output.with_suffix(".csv.tmp")
        combined.to_csv(temporary)
        temporary.replace(output)
        gaps = combined.index.to_series().diff().dropna().dt.total_seconds() / 60
        reports[name] = {
            "provider_symbol": symbol,
            "required_sides": required_sides,
            "price_input": spec["price_input"],
            "rows": len(combined),
            "first_candle_open_utc": combined.index[0].isoformat(),
            "last_candle_open_utc": combined.index[-1].isoformat(),
            "last_available_at_utc": (combined.index[-1] + pd.Timedelta(hours=1)).isoformat(),
            "median_gap_minutes": float(gaps.median()) if len(gaps) else None,
            "max_gap_minutes_including_market_closures": float(gaps.max()) if len(gaps) else None,
            "file": str(output),
            "file_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }
    manifest = {
        "schema_version": 1,
        "contract_version": contract["contract_version"],
        "contract_sha256": contract_sha,
        "provider": contract["provider"]["name"],
        "timestamp_semantics": contract["provider"]["timestamp_semantics"],
        "availability_semantics": contract["provider"]["availability_semantics"],
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "instruments": reports,
        "commercial_rights_status": contract["commercial_rights_status"],
        "research_warning": "Inputs are development data and do not establish an edge.",
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _utc_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--start", type=_utc_date, default=_utc_date("2020-01-01"))
    parser.add_argument("--end", type=_utc_date, default=_utc_date("2026-07-18"))
    parser.add_argument("--chunk-days", type=int, default=90)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args()
    report = download(args.start, args.end, args.output_dir, args.chunk_days, args.contract)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
