#!/usr/bin/env python3
"""Collect the frozen prospective gold-context snapshot atomically.

This is an observational paper-research input.  It cannot score candidates,
approve paper trades, call Claude, send Telegram messages or place orders.
Completed one-hour candles are fetched from the exact source identities and
price sides registered before prospective collection began.
"""

import hashlib
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import pandas as pd


OUTPUT = Path(os.getenv("GOLD_CONTEXT_SNAPSHOT_PATH", "/tmp/gold_context_snapshot.json"))
CONTRACT_PATH = Path(os.getenv(
    "FORWARD_CONTEXT_CONFIG", "config/forward_context_observation_v1.json",
))
EXPECTED_CONTRACT_SHA256 = "97e7d3b4bf2ad00809c00c9e2b6cb6dfd6961b40c70e26da7772b42ef8048b70"
BAR_COUNT = int(os.getenv("GOLD_CONTEXT_BAR_COUNT", "200"))
CACHE_SECONDS = int(os.getenv("GOLD_CONTEXT_CACHE_SECONDS", "3300"))
LOOKBACK_DAYS = int(os.getenv("GOLD_CONTEXT_LOOKBACK_DAYS", "30"))
FIELDS = ("open", "high", "low", "close", "volume")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_sha256(payload: dict) -> str:
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    canonical = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _load_contract(path: Path = CONTRACT_PATH) -> tuple[dict, str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    contract = json.loads(raw)
    if digest != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("forward context contract hash mismatch; register a new version")
    if (contract.get("schema_version") != 1 or
            contract.get("experiment_version") != "forward-context-buy-20260719-v1" or
            contract.get("paper_only") is not True):
        raise RuntimeError("unsupported forward context contract")
    return contract, digest


def _fetch(symbol: str, start: datetime, end: datetime, side: str) -> pd.DataFrame:
    import dukascopy_python as dukascopy

    offer_side = dukascopy.OFFER_SIDE_BID if side == "bid" else dukascopy.OFFER_SIDE_ASK
    frame = dukascopy.fetch(
        symbol, dukascopy.INTERVAL_HOUR_1, offer_side,
        start, end, max_retries=3,
    )
    if frame is None or frame.empty:
        raise RuntimeError(f"Dukascopy returned no {side} 1H data for {symbol}")
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame[list(FIELDS)].sort_index()


def _combine_sides(frames: dict[str, pd.DataFrame], required_sides: list[str]) -> pd.DataFrame:
    if required_sides == ["bid"]:
        result = frames["bid"].add_prefix("bid_")
        for field in FIELDS:
            result[f"analysis_{field}"] = result[f"bid_{field}"]
        return result.sort_index()
    if required_sides != ["bid", "ask"]:
        raise RuntimeError(f"unsupported context price sides: {required_sides}")
    result = frames["bid"].add_prefix("bid_").join(
        frames["ask"].add_prefix("ask_"), how="inner", validate="one_to_one",
    )
    if result.empty:
        raise RuntimeError("Dukascopy context bid/ask join is empty")
    for field in ("open", "high", "low", "close"):
        result[f"analysis_{field}"] = (
            result[f"bid_{field}"] + result[f"ask_{field}"]
        ) / 2.0
    result["analysis_volume"] = result[["bid_volume", "ask_volume"]].mean(axis=1)
    result["spread_open"] = result["ask_open"] - result["bid_open"]
    result["spread_close"] = result["ask_close"] - result["bid_close"]
    return result.sort_index()


def _validate_and_encode(name: str, frame: pd.DataFrame,
                         required_sides: list[str], captured_at: datetime) -> tuple[list[dict], float]:
    complete = frame[frame.index + pd.Timedelta(hours=1) <= captured_at].tail(BAR_COUNT)
    if len(complete) != BAR_COUNT:
        raise RuntimeError(f"{name}: expected {BAR_COUNT} complete bars, got {len(complete)}")
    if not complete.index.is_monotonic_increasing or complete.index.has_duplicates:
        raise RuntimeError(f"{name}: timestamps are unordered or duplicated")
    gaps = complete.index.to_series().diff().dropna().dt.total_seconds()
    actual_cadence = float(median(gaps)) if len(gaps) else 0.0
    if abs(actual_cadence - 3600) > 180:
        raise RuntimeError(f"{name}: median cadence {actual_cadence:.0f}s expected 3600s")

    columns = [f"analysis_{field}" for field in FIELDS]
    columns.extend(f"{side}_{field}" for side in required_sides for field in FIELDS)
    if required_sides == ["bid", "ask"]:
        columns.extend(["spread_open", "spread_close"])
    rows = []
    for timestamp, row in complete.iterrows():
        encoded = {"time": int(timestamp.timestamp())}
        for column in columns:
            value = float(row[column])
            if not math.isfinite(value):
                raise RuntimeError(f"{name}: non-finite {column}")
            encoded[column] = value
        for prefix in ("analysis_", *(f"{side}_" for side in required_sides)):
            o, high, low, close = (encoded[f"{prefix}{field}"]
                                   for field in ("open", "high", "low", "close"))
            if min(o, high, low, close) <= 0 or high < max(o, close, low) or low > min(o, close, high):
                raise RuntimeError(f"{name}: invalid {prefix}OHLC")
        if (required_sides == ["bid", "ask"] and
                (encoded["ask_close"] < encoded["bid_close"] or
                 encoded["ask_open"] < encoded["bid_open"])):
            raise RuntimeError(f"{name}: negative observed spread")
        rows.append(encoded)
    return rows, actual_cadence


def _cached_snapshot(output: Path, captured_at: datetime,
                     contract_sha256: str) -> dict | None:
    try:
        payload = json.loads(output.read_text())
        age = (captured_at - _parse_utc(payload["captured_at"])).total_seconds()
        if (0 <= age <= CACHE_SECONDS and
                payload.get("schema_version") == 1 and
                payload.get("contract_sha256") == contract_sha256 and
                payload.get("content_sha256") == _canonical_sha256(payload)):
            return payload
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return None


def collect(output: Path = OUTPUT, contract_path: Path = CONTRACT_PATH,
            captured_at: datetime | None = None, use_cache: bool = True) -> dict:
    captured_at = captured_at or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        raise ValueError("captured_at must be timezone-aware")
    captured_at = captured_at.astimezone(timezone.utc)
    contract, contract_sha = _load_contract(contract_path)
    if use_cache:
        cached = _cached_snapshot(output, captured_at, contract_sha)
        if cached is not None:
            cached["cache_reused"] = True
            return cached

    started = time.monotonic()
    instrument_payloads = {}
    for name, spec in contract["source_contract"]["instruments"].items():
        symbol = spec["symbol"]
        sides = spec["required_sides"]
        start = captured_at - timedelta(days=LOOKBACK_DAYS)
        frames = {side: _fetch(symbol, start, captured_at, side) for side in sides}
        combined = _combine_sides(frames, sides)
        bars, cadence = _validate_and_encode(name, combined, sides, captured_at)
        instrument_payloads[name] = {
            "symbol": symbol,
            "required_sides": sides,
            "analysis_price": spec["analysis_price"],
            "resolution": "1H",
            "bar_count": len(bars),
            "median_cadence_seconds": cadence,
            "latest_available_at": datetime.fromtimestamp(
                bars[-1]["time"] + 3600, timezone.utc,
            ).isoformat(),
            "bars": bars,
        }

    payload = {
        "schema_version": 1,
        "experiment_version": contract["experiment_version"],
        "contract_sha256": contract_sha,
        "provider": contract["source_contract"]["provider"],
        "captured_at": captured_at.isoformat(),
        "timestamp_semantics": "candle_open_utc; available_at=open+1h; forming candles excluded",
        "paper_research_only": True,
        "collection_elapsed_seconds": round(time.monotonic() - started, 3),
        "instruments": instrument_payloads,
    }
    payload["content_sha256"] = _canonical_sha256(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(output)
    return payload


if __name__ == "__main__":
    result = collect()
    print(json.dumps({
        "output": str(OUTPUT),
        "provider": result["provider"],
        "experiment_version": result["experiment_version"],
        "captured_at": result["captured_at"],
        "cache_reused": result.get("cache_reused", False),
        "collection_elapsed_seconds": result["collection_elapsed_seconds"],
        "bars": {name: item["bar_count"] for name, item in result["instruments"].items()},
        "content_sha256": result["content_sha256"],
    }, indent=2))
