#!/usr/bin/env python3
"""Collect an atomic, execution-aware XAUUSD multi-timeframe snapshot.

The Dukascopy public feed supplies independent bid and ask candles.  This
collector joins them one-to-one, derives midpoint OHLC for SMC analysis, keeps
the executable bid/ask fields for forward outcomes, drops forming candles and
fails closed when cadence, ordering, bar count or OHLC integrity is invalid.
"""

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import pandas as pd


OUTPUT = Path(os.getenv("DUKASCOPY_SNAPSHOT_PATH", "/tmp/dukascopy_snapshot.json"))
BAR_COUNT = int(os.getenv("DUKASCOPY_BAR_COUNT", "200"))

# Lookbacks include weekends and a safety margin above 200 traded candles.
FRAME_SPECS = {
    "1W": ("INTERVAL_WEEK_1", 604800, 1500),
    "1D": ("INTERVAL_DAY_1", 86400, 330),
    "4H": ("INTERVAL_HOUR_4", 14400, 50),
    "1H": ("INTERVAL_HOUR_1", 3600, 14),
    "15M": ("INTERVAL_MIN_15", 900, 5),
}


def _fetch(start: datetime, end: datetime, interval_name: str, side: str) -> pd.DataFrame:
    import dukascopy_python as dukascopy
    from dukascopy_python.instruments import INSTRUMENT_FX_METALS_XAU_USD

    offer_side = dukascopy.OFFER_SIDE_BID if side == "bid" else dukascopy.OFFER_SIDE_ASK
    frame = dukascopy.fetch(
        INSTRUMENT_FX_METALS_XAU_USD,
        getattr(dukascopy, interval_name),
        offer_side,
        start,
        end,
        max_retries=3,
    )
    if frame is None or frame.empty:
        raise RuntimeError(f"Dukascopy returned no {side} {interval_name} data")
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame[["open", "high", "low", "close", "volume"]]


def _join_executable_sides(bid: pd.DataFrame, ask: pd.DataFrame) -> pd.DataFrame:
    joined = bid.add_prefix("bid_").join(
        ask.add_prefix("ask_"), how="inner", validate="one_to_one"
    )
    if joined.empty:
        raise RuntimeError("Dukascopy bid/ask join is empty")
    for field in ("open", "high", "low", "close"):
        joined[field] = (joined[f"bid_{field}"] + joined[f"ask_{field}"]) / 2.0
    joined["volume"] = joined[["bid_volume", "ask_volume"]].mean(axis=1)
    joined["spread_open"] = joined["ask_open"] - joined["bid_open"]
    joined["spread_close"] = joined["ask_close"] - joined["bid_close"]
    return joined.sort_index()


def _bar_payload(frame: pd.DataFrame) -> list[dict]:
    fields = (
        "open", "high", "low", "close", "volume",
        "bid_open", "bid_high", "bid_low", "bid_close", "bid_volume",
        "ask_open", "ask_high", "ask_low", "ask_close", "ask_volume",
        "spread_open", "spread_close",
    )
    rows = []
    for timestamp, row in frame.iterrows():
        item = {"time": int(timestamp.timestamp())}
        item.update({field: float(row[field]) for field in fields})
        rows.append(item)
    return rows


def _validate_frame(name: str, bars: list[dict], expected_cadence: int) -> float:
    if len(bars) != BAR_COUNT:
        raise RuntimeError(f"{name}: expected {BAR_COUNT} complete bars, got {len(bars)}")
    times = [int(bar["time"]) for bar in bars]
    if times != sorted(times) or len(times) != len(set(times)):
        raise RuntimeError(f"{name}: timestamps are unordered or duplicated")
    intervals = [later - earlier for earlier, later in zip(times, times[1:])]
    actual_cadence = float(median(intervals)) if intervals else 0.0
    if abs(actual_cadence - expected_cadence) > expected_cadence * 0.05:
        raise RuntimeError(
            f"{name}: median cadence {actual_cadence:.0f}s expected {expected_cadence}s"
        )
    for bar in bars:
        for prefix in ("", "bid_", "ask_"):
            o, h, low, close = (float(bar[f"{prefix}{field}"])
                                for field in ("open", "high", "low", "close"))
            if min(o, h, low, close) <= 0 or h < max(o, close, low) or low > min(o, close, h):
                raise RuntimeError(f"{name}: invalid {prefix or 'midpoint_'}OHLC")
        if float(bar["ask_close"]) < float(bar["bid_close"]):
            raise RuntimeError(f"{name}: negative close spread")
    return actual_cadence


def collect(output: Path = OUTPUT, captured_at: datetime | None = None) -> dict:
    captured_at = captured_at or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        raise ValueError("captured_at must be timezone-aware")
    started = time.monotonic()
    frames = {}
    fingerprints = set()
    for name, (interval_name, cadence_seconds, lookback_days) in FRAME_SPECS.items():
        start = captured_at - timedelta(days=lookback_days)
        bid = _fetch(start, captured_at, interval_name, "bid")
        ask = _fetch(start, captured_at, interval_name, "ask")
        joined = _join_executable_sides(bid, ask)

        # Candle timestamps denote opens.  Never expose a candle whose nominal
        # close is after collection time, even if the upstream endpoint emits it.
        complete = joined[joined.index + pd.to_timedelta(cadence_seconds, unit="s") <= captured_at]
        bars = _bar_payload(complete.tail(BAR_COUNT))
        actual_cadence = _validate_frame(name, bars, cadence_seconds)
        midpoint_fingerprint = json.dumps(
            [{field: row[field] for field in ("time", "open", "high", "low", "close")}
             for row in bars],
            sort_keys=True,
            separators=(",", ":"),
        )
        if midpoint_fingerprint in fingerprints:
            raise RuntimeError(f"{name}: duplicate cross-timeframe payload")
        fingerprints.add(midpoint_fingerprint)
        frames[name] = {
            "resolution": name,
            "bar_count": len(bars),
            "expected_cadence_seconds": cadence_seconds,
            "median_cadence_seconds": actual_cadence,
            "bars": bars,
        }

    snapshot = {
        "schema_version": 2,
        "provider": "dukascopy-public",
        "symbol": "DUKASCOPY:XAUUSD",
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "timestamp_semantics": "candle_open_utc; forming candles excluded",
        "price_components": ["bid", "ask", "midpoint"],
        "paper_research_only": True,
        "collection_elapsed_seconds": round(time.monotonic() - started, 3),
        "timeframes": frames,
    }
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    snapshot["content_sha256"] = hashlib.sha256(canonical).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, indent=2) + "\n")
    temporary.replace(output)
    return snapshot


if __name__ == "__main__":
    result = collect()
    print(json.dumps({
        "output": str(OUTPUT),
        "provider": result["provider"],
        "symbol": result["symbol"],
        "captured_at": result["captured_at"],
        "collection_elapsed_seconds": result["collection_elapsed_seconds"],
        "bars": {name: frame["bar_count"] for name, frame in result["timeframes"].items()},
        "content_sha256": result["content_sha256"],
    }, indent=2))
