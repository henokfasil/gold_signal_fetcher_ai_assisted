"""Validation and point-in-time features for prospective context observation."""

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd

from config import settings
from research.build_gold_context_dataset import (
    CONTEXT_FEATURES,
    CONTEXT_NAMES,
    instrument_features,
    ratio_features,
)


EXPECTED_CONTRACT_SHA256 = "97e7d3b4bf2ad00809c00c9e2b6cb6dfd6961b40c70e26da7772b42ef8048b70"
EXPECTED_FEATURE_SCHEMA_SHA256 = "4100208e9e086f5399dedf3f23a7165ed1444bd8994228b5492adc1525c320c6"


def parse_utc(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_snapshot_sha256(payload: dict) -> str:
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    canonical = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def load_forward_context_contract(path: Path = settings.FORWARD_CONTEXT_CONFIG) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    contract = json.loads(raw)
    schema = json.dumps(CONTEXT_FEATURES, separators=(",", ":"), ensure_ascii=True).encode()
    if digest != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("forward context contract hash mismatch; register a new version")
    if hashlib.sha256(schema).hexdigest() != EXPECTED_FEATURE_SCHEMA_SHA256:
        raise RuntimeError("runtime context feature schema changed")
    feature_contract = contract.get("feature_contract", {})
    isolation = contract.get("isolation", {})
    if (contract.get("schema_version") != 1 or
            contract.get("experiment_version") != "forward-context-buy-20260719-v1" or
            contract.get("paper_only") is not True or
            feature_contract.get("schema_sha256") != EXPECTED_FEATURE_SCHEMA_SHA256 or
            int(feature_contract.get("feature_count", -1)) != len(CONTEXT_FEATURES) or
            isolation.get("may_score_or_approve_paper_trade") is not False or
            isolation.get("may_change_ml_or_claude_decision") is not False or
            isolation.get("may_send_telegram") is not False or
            isolation.get("may_place_broker_order") is not False or
            isolation.get("may_train_or_select_model") is not False):
        raise RuntimeError("forward context contract violates frozen isolation or schema")
    return contract, digest


def _valid_ohlc(bar: dict, prefix: str) -> bool:
    try:
        values = [float(bar[f"{prefix}{field}"]) for field in ("open", "high", "low", "close")]
    except (KeyError, TypeError, ValueError):
        return False
    o, high, low, close = values
    return (all(math.isfinite(value) and value > 0 for value in values) and
            high >= max(o, close, low) and low <= min(o, close, high))


def load_validated_context_snapshot(
    path: Path = settings.GOLD_CONTEXT_SNAPSHOT_PATH,
    contract_path: Path = settings.FORWARD_CONTEXT_CONFIG,
    observed_at: datetime | None = None,
) -> tuple[dict, dict]:
    """Read and validate the file only; this function never fetches data."""
    contract, contract_sha = load_forward_context_contract(contract_path)
    payload = json.loads(Path(path).read_text())
    if (payload.get("schema_version") != 1 or
            payload.get("experiment_version") != contract["experiment_version"] or
            payload.get("contract_sha256") != contract_sha or
            payload.get("provider") != contract["source_contract"]["provider"] or
            payload.get("paper_research_only") is not True or
            payload.get("content_sha256") != canonical_snapshot_sha256(payload)):
        raise ValueError("context snapshot identity or content hash mismatch")

    captured_at = parse_utc(payload["captured_at"])
    observed_at = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    snapshot_age = (observed_at - captured_at).total_seconds()
    if snapshot_age < -60 or snapshot_age > settings.CONTEXT_SNAPSHOT_MAX_AGE_SECONDS:
        raise ValueError(f"context snapshot stale or future-dated ({snapshot_age:.0f}s)")

    expected_instruments = contract["source_contract"]["instruments"]
    if set(payload.get("instruments", {})) != set(expected_instruments):
        raise ValueError("context snapshot instrument set mismatch")
    for name, spec in expected_instruments.items():
        item = payload["instruments"][name]
        bars = item.get("bars", [])
        sides = spec["required_sides"]
        if (item.get("symbol") != spec["symbol"] or
                item.get("required_sides") != sides or
                item.get("analysis_price") != spec["analysis_price"] or
                item.get("resolution") != "1H" or len(bars) != 200):
            raise ValueError(f"{name}: source or bar-count contract mismatch")
        times = [int(bar["time"]) for bar in bars]
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        if (times != sorted(times) or len(times) != len(set(times)) or
                not gaps or abs(float(median(gaps)) - 3600) > 180):
            raise ValueError(f"{name}: timestamp or cadence validation failed")
        if any(timestamp + 3600 > captured_at.timestamp() for timestamp in times):
            raise ValueError(f"{name}: forming one-hour candle present")
        for bar in bars:
            if not _valid_ohlc(bar, "analysis_"):
                raise ValueError(f"{name}: invalid analysis OHLC")
            for side in sides:
                if not _valid_ohlc(bar, f"{side}_"):
                    raise ValueError(f"{name}: invalid {side} OHLC")
            if sides == ["bid", "ask"] and (
                float(bar["ask_open"]) < float(bar["bid_open"]) or
                float(bar["ask_close"]) < float(bar["bid_close"])
            ):
                raise ValueError(f"{name}: negative observed spread")
    return payload, contract


def _context_frame(item: dict) -> pd.DataFrame:
    frame = pd.DataFrame(item["bars"])
    frame["available_at"] = pd.to_datetime(frame["time"], unit="s", utc=True) + pd.Timedelta(hours=1)
    frame["analysis_close"] = pd.to_numeric(frame["analysis_close"], errors="coerce")
    squared_log_return = np.log(frame["analysis_close"]).diff().pow(2)
    frame["realized_volatility_24h_pct"] = (
        squared_log_return.set_axis(frame["available_at"])
        .rolling("24h", min_periods=2).sum().pow(0.5).to_numpy() * 100
    )
    return frame[["available_at", "analysis_close", "realized_volatility_24h_pct"]]


def _xau_frame(payload: dict) -> pd.DataFrame:
    bars = payload["timeframes"]["15M"]["bars"]
    frame = pd.DataFrame(bars)
    frame["available_at"] = pd.to_datetime(frame["time"], unit="s", utc=True) + pd.Timedelta(minutes=15)
    frame["analysis_close"] = pd.to_numeric(frame["close"], errors="coerce")
    if (frame.empty or frame["analysis_close"].isna().any() or
            (frame["analysis_close"] <= 0).any() or
            not frame["available_at"].is_monotonic_increasing or
            frame["available_at"].duplicated().any()):
        raise ValueError("XAU snapshot is invalid for context ratio")
    return frame[["available_at", "analysis_close"]]


def _point_in_time_level(frame: pd.DataFrame, candidate_time: pd.Timestamp) -> tuple[float | None, str | None]:
    eligible = frame[frame["available_at"] <= candidate_time]
    if eligible.empty:
        return None, None
    row = eligible.iloc[-1]
    return float(row["analysis_close"]), row["available_at"].isoformat()


def _plain_value(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.integer, int)):
        return int(value)
    return float(value)


def extract_candidate_context(payload: dict, xau_payload: dict, candidate_time,
                              contract: dict | None = None) -> dict:
    """Create the exact registered feature vector using backward-only joins."""
    if contract is None:
        contract, _ = load_forward_context_contract()
    timestamp = pd.Timestamp(parse_utc(candidate_time))
    query = pd.Series([timestamp])
    max_staleness = int(contract["feature_contract"]["maximum_staleness_minutes"])
    contexts = {
        name: _context_frame(payload["instruments"][name]) for name in CONTEXT_NAMES
    }
    additions = [
        instrument_features(query, contexts[name], name, max_staleness)
        for name in CONTEXT_NAMES
    ]
    xau = _xau_frame(xau_payload)
    additions.append(ratio_features(query, xau, contexts["silver"], max_staleness))
    result = pd.concat(additions, axis=1)
    if list(result.columns) != CONTEXT_FEATURES:
        raise RuntimeError("prospective context feature schema differs from registration")

    raw_levels = {}
    for name, frame in contexts.items():
        value, available_at = _point_in_time_level(frame, timestamp)
        raw_levels[f"ctx_{name}_analysis_close"] = value
        raw_levels[f"ctx_{name}_available_at"] = available_at
    xau_value, xau_available = _point_in_time_level(xau, timestamp)
    raw_levels["ctx_xau_analysis_close"] = xau_value
    raw_levels["ctx_xau_available_at"] = xau_available
    return {
        "features": {column: _plain_value(result.iloc[0][column]) for column in CONTEXT_FEATURES},
        "raw_levels": raw_levels,
    }
