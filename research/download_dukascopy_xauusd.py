#!/usr/bin/env python3
"""Download account-free Dukascopy XAUUSD bid/ask candles with provenance.

The downloader writes one checkpoint per UTC date chunk, so interrupted runs
resume without repeating completed network work. The final CSV contains a
midpoint OHLCV view for the SMC replay plus the original bid/ask OHLC fields.
"""

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

TIMEFRAME_MINUTES = 15


def _fetch(start: datetime, end: datetime, side: str) -> pd.DataFrame:
    import dukascopy_python as dukascopy
    from dukascopy_python.instruments import INSTRUMENT_FX_METALS_XAU_USD
    offer_side = dukascopy.OFFER_SIDE_BID if side == "bid" else dukascopy.OFFER_SIDE_ASK
    frame = dukascopy.fetch(
        INSTRUMENT_FX_METALS_XAU_USD, dukascopy.INTERVAL_MIN_15,
        offer_side, start, end, max_retries=5,
    )
    if frame is None or frame.empty:
        raise RuntimeError(f"Dukascopy returned no {side} data for {start} to {end}")
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame[["open", "high", "low", "close", "volume"]]


def _chunk_frame(start: datetime, end: datetime) -> pd.DataFrame:
    bid, ask = _fetch(start, end, "bid"), _fetch(start, end, "ask")
    joined = bid.add_prefix("bid_").join(ask.add_prefix("ask_"), how="inner", validate="one_to_one")
    if joined.empty:
        raise RuntimeError("bid/ask join is empty")
    for field in ("open", "high", "low", "close"):
        joined[field] = (joined[f"bid_{field}"] + joined[f"ask_{field}"]) / 2.0
    joined["volume"] = joined[["bid_volume", "ask_volume"]].mean(axis=1)
    joined["spread_open"] = joined["ask_open"] - joined["bid_open"]
    joined["spread_close"] = joined["ask_close"] - joined["bid_close"]
    joined.index.name = "timestamp"
    return joined


def download(start: datetime, end: datetime, output: Path, chunk_days: int = 14) -> dict:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end must be timezone-aware")
    if start >= end:
        raise ValueError("start must be before end")
    checkpoint_dir = output.parent / f".{output.stem}_chunks"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    cursor = start
    paths = []
    while cursor < end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days))
        path = checkpoint_dir / f"{cursor:%Y%m%d}-{chunk_end:%Y%m%d}.csv"
        if not path.exists() or path.stat().st_size == 0:
            print(f"fetching {cursor.date()} through {chunk_end.date()} (bid + ask)", flush=True)
            frame = _chunk_frame(cursor, chunk_end)
            temp = path.with_suffix(".tmp")
            frame.to_csv(temp)
            temp.replace(path)
        else:
            print(f"reusing checkpoint {path.name}", flush=True)
        paths.append(path)
        cursor = chunk_end
    frames = [pd.read_csv(path, parse_dates=["timestamp"]) for path in paths]
    result = pd.concat(frames, ignore_index=True)
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True)
    result = result[(result["timestamp"] >= start) & (result["timestamp"] < end)]
    result = result.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    if result.empty or not result["timestamp"].is_monotonic_increasing:
        raise RuntimeError("final dataset is empty or unordered")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    result.to_csv(temp, index=False)
    temp.replace(output)
    gaps = result["timestamp"].diff().dropna().dt.total_seconds() / 60
    manifest = {
        "schema_version": 1, "provider": "Dukascopy Bank SA public historical feed",
        "instrument": "XAUUSD", "price_components": ["bid", "ask", "midpoint"],
        "timeframe": "15M", "timestamp_semantics": "candle_open_utc",
        "requested_start": start.isoformat(), "requested_end_exclusive": end.isoformat(),
        "first_bar": result["timestamp"].iloc[0].isoformat(),
        "last_bar": result["timestamp"].iloc[-1].isoformat(), "rows": len(result),
        "duplicate_timestamps": int(result["timestamp"].duplicated().sum()),
        "median_gap_minutes": float(gaps.median()) if len(gaps) else None,
        "max_gap_minutes_including_market_closures": float(gaps.max()) if len(gaps) else None,
        "mean_spread_close_points": float(result["spread_close"].mean()),
        "p95_spread_close_points": float(result["spread_close"].quantile(0.95)),
        "file_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "research_warning": "Dukascopy feed differs from runtime OANDA:TradingView feed; validate cross-feed stability.",
    }
    output.with_suffix(output.suffix + ".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _utc_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=_utc_date, default=_utc_date("2020-01-01"))
    parser.add_argument("--end", type=_utc_date, default=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))
    parser.add_argument("--chunk-days", type=int, default=14)
    args = parser.parse_args()
    print(json.dumps(download(args.start, args.end, args.output, args.chunk_days), indent=2))


if __name__ == "__main__":
    main()
