#!/usr/bin/env python3
"""Build the hash-locked, outcome-free event-first XAUUSD candidate universe."""

import argparse
import hashlib
import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from agent.smc_gold_scanner import (
    _SWING_N,
    _calc_atr,
    classify_market_structure,
    classify_premium_discount,
    detect_bearish_fvg,
    detect_bos_down,
    detect_bos_up,
    detect_choch_down,
    detect_choch_up,
    detect_fvg,
    detect_liquidity_sweep_down,
    detect_liquidity_sweep_up,
    detect_swing_highs,
    detect_swing_lows,
    find_last_bearish_order_block,
    find_last_order_block,
)
from research.build_historical_dataset import (
    MINIMUMS,
    TF_RULES,
    load_ohlcv,
    resample_closed_bars,
)


LOG = logging.getLogger(__name__)
CONTRACT_PATH = Path("config/event_candidate_universe_v1.json")
EXPECTED_CONTRACT_SHA256 = (
    "2b57fac00d70b60452a19e14b2daa8d264316016d89fc2425bebf3e05ad40c12"
)
EVENT_TYPES = ("SWEEP_1H", "CHOCH_1H", "FVG_1H", "BOS_4H", "CHOCH_4H")
EVENT_FEATURES = [
    "event_direction_encoded", "event_type_sweep_1h", "event_type_choch_1h",
    "event_type_fvg_1h", "event_type_bos_4h", "event_type_choch_4h",
    "event_break_distance_atr", "event_body_atr", "event_range_atr",
    "sweep_present", "sweep_age_bars_1h", "sweep_depth_atr_1h",
    "sweep_reclaim_atr_1h", "sweep_reclaim_fraction",
    "distance_to_swept_level_atr_1h", "bos_age_bars_4h",
    "choch_age_bars_4h", "bos_age_bars_1h", "choch_age_bars_1h",
    "bos_age_bars_15m", "choch_age_bars_15m", "structure_1w_encoded",
    "structure_1d_encoded", "structure_4h_encoded", "structure_1h_encoded",
    "structure_15m_encoded", "structure_alignment_count",
    "structure_4h_transition", "structure_1h_transition",
    "value_position_4h_raw", "value_position_4h_clipped", "ob_present",
    "ob_timeframe_encoded", "ob_age_bars", "ob_width_atr", "ob_distance_atr",
    "ob_mitigated", "ob_mitigation_touch_count", "fvg_present",
    "fvg_age_bars_1h", "fvg_width_atr_1h", "fvg_distance_atr_1h",
    "atr_1h_pct", "spread_close_bps", "hour_sin", "hour_cos",
    "sweep_missing", "ob_missing", "fvg_missing", "bos_4h_missing",
    "choch_4h_missing", "bos_1h_missing", "choch_1h_missing",
    "bos_15m_missing", "choch_15m_missing",
]
STRUCTURE_ENCODING = {"bearish": -1.0, "ranging": 0.0, "bullish": 1.0}
TIMEFRAME_ENCODING = {"15M": 1.0, "1H": 2.0, "4H": 3.0}


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _schema_sha256(columns: list[str]) -> str:
    raw = json.dumps(columns, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def load_contract(path: Path = CONTRACT_PATH) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    contract = json.loads(raw)
    feature_contract = contract.get("geometry_feature_contract", {})
    source = contract.get("source_contract", {})
    universe = contract.get("event_universe_contract", {})
    if digest != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("event-universe contract hash mismatch; register a new version")
    if (contract.get("schema_version") != 1 or
            contract.get("contract_version") != "event-candidate-universe-20260719-v1" or
            contract.get("paper_research_only") is not True or
            feature_contract.get("registered_features") != EVENT_FEATURES or
            feature_contract.get("feature_count") != len(EVENT_FEATURES) or
            feature_contract.get("schema_sha256") != _schema_sha256(EVENT_FEATURES) or
            tuple(universe.get("event_types", {})) != EVENT_TYPES or
            source.get("forming_bars_permitted") is not False):
        raise RuntimeError("event-universe contract schema mismatch")
    return contract, digest


def stable_event_id(contract_version: str, symbol: str, direction: str,
                    event_type: str, source_event_time) -> str:
    timestamp = pd.Timestamp(source_event_time)
    timestamp = (timestamp.tz_localize("UTC") if timestamp.tz is None
                 else timestamp.tz_convert("UTC"))
    raw = "|".join((contract_version, symbol, direction, event_type,
                    timestamp.isoformat())).encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def _swings(frame: pd.DataFrame, timeframe: str) -> tuple[list[int], list[int]]:
    return (
        detect_swing_highs(frame, _SWING_N[timeframe]),
        detect_swing_lows(frame, _SWING_N[timeframe]),
    )


def _structure(frame: pd.DataFrame, timeframe: str) -> tuple[str, list[int], list[int]]:
    highs, lows = _swings(frame, timeframe)
    return classify_market_structure(frame, highs, lows), highs, lows


def _directional_objects(frame: pd.DataFrame, timeframe: str, direction: str,
                         highs: list[int], lows: list[int]) -> dict:
    if direction == "BUY":
        bos = detect_bos_up(frame, highs)
        choch = detect_choch_up(frame, highs, lows)
        order_block = find_last_order_block(frame, bos)
    else:
        bos = detect_bos_down(frame, lows)
        choch = detect_choch_down(frame, highs, lows)
        order_block = find_last_bearish_order_block(frame, bos)
    return {"bos": bos, "choch": choch, "order_block": order_block}


def current_events(frames: dict[str, pd.DataFrame], as_of) -> list[dict]:
    """Return only events whose defining/confirmation bar is newly complete."""
    as_of = pd.Timestamp(as_of)
    states = {name: _structure(frame, name) for name, frame in frames.items()}
    events = []
    one_hour = frames["1H"]
    _, highs_1h, lows_1h = states["1H"]
    for direction in ("BUY", "SELL"):
        if direction == "BUY":
            sweep = detect_liquidity_sweep_up(one_hour, lows_1h)
            choch = detect_choch_up(one_hour, highs_1h, lows_1h)
            fvg = detect_fvg(one_hour)
        else:
            sweep = detect_liquidity_sweep_down(one_hour, highs_1h)
            choch = detect_choch_down(one_hour, highs_1h, lows_1h)
            fvg = detect_bearish_fvg(one_hour)
        if sweep is not None and int(sweep["sweep_index"]) == len(one_hour) - 1:
            events.append({"event_type": "SWEEP_1H", "direction": direction,
                           "timeframe": "1H", "object": sweep,
                           "event_index": int(sweep["sweep_index"])})
        if choch is not None and int(choch["choch_index"]) == len(one_hour) - 1:
            events.append({"event_type": "CHOCH_1H", "direction": direction,
                           "timeframe": "1H", "object": choch,
                           "event_index": int(choch["choch_index"])})
        if fvg is not None and int(fvg["fvg_index"]) + 1 == len(one_hour) - 1:
            events.append({"event_type": "FVG_1H", "direction": direction,
                           "timeframe": "1H", "object": fvg,
                           "event_index": int(fvg["fvg_index"]) + 1})

    four_hour = frames["4H"]
    if pd.Timestamp(four_hour.index[-1]) == as_of:
        _, highs_4h, lows_4h = states["4H"]
        for direction in ("BUY", "SELL"):
            objects = _directional_objects(
                four_hour, "4H", direction, highs_4h, lows_4h,
            )
            for event_type, object_name, index_name in (
                ("BOS_4H", "bos", "bos_index"),
                ("CHOCH_4H", "choch", "choch_index"),
            ):
                item = objects[object_name]
                if item is not None and int(item[index_name]) == len(four_hour) - 1:
                    events.append({"event_type": event_type, "direction": direction,
                                   "timeframe": "4H", "object": item,
                                   "event_index": int(item[index_name])})
    return events


def _age(frame: pd.DataFrame, item: dict | None, index_name: str) -> float:
    return (float(len(frame) - 1 - int(item[index_name]))
            if item is not None else np.nan)


def _distance_to_zone(price: float, low: float, high: float) -> float:
    if low <= price <= high:
        return 0.0
    return low - price if price < low else price - high


def _atr(frame: pd.DataFrame) -> float:
    value = _calc_atr(frame["high"], frame["low"], frame["close"])
    return float(value) if value is not None and value > 0 else np.nan


def _transition(frame: pd.DataFrame, timeframe: str, current: str) -> float:
    if len(frame) <= max(2 * _SWING_N[timeframe] + 2, 10):
        return 0.0
    previous, _, _ = _structure(frame.iloc[:-1].copy(), timeframe)
    return STRUCTURE_ENCODING[current] - STRUCTURE_ENCODING[previous]


def _order_block_geometry(frames: dict[str, pd.DataFrame], states: dict,
                          direction: str, price: float) -> dict:
    candidates = []
    for timeframe in ("15M", "1H", "4H"):
        frame = frames[timeframe]
        _, highs, lows = states[timeframe]
        objects = _directional_objects(frame, timeframe, direction, highs, lows)
        block, bos = objects["order_block"], objects["bos"]
        atr = _atr(frame)
        if block is None or not np.isfinite(atr) or atr <= 0:
            continue
        distance = _distance_to_zone(price, float(block["ob_low"]),
                                     float(block["ob_high"])) / atr
        start = (int(bos["bos_index"]) + 1) if bos is not None else len(frame)
        later = frame.iloc[start:]
        touches = int((
            (later["low"] <= float(block["ob_high"])) &
            (later["high"] >= float(block["ob_low"]))
        ).sum())
        candidates.append({
            "distance": float(distance), "timeframe": timeframe,
            "block": block, "atr": atr, "touches": touches,
        })
    if not candidates:
        return {
            "ob_present": 0.0, "ob_timeframe_encoded": np.nan,
            "ob_age_bars": np.nan, "ob_width_atr": np.nan,
            "ob_distance_atr": np.nan, "ob_mitigated": np.nan,
            "ob_mitigation_touch_count": np.nan, "ob_missing": 1.0,
        }
    chosen = min(candidates, key=lambda item: (
        item["distance"], TIMEFRAME_ENCODING[item["timeframe"]],
    ))
    block, timeframe = chosen["block"], chosen["timeframe"]
    return {
        "ob_present": 1.0,
        "ob_timeframe_encoded": TIMEFRAME_ENCODING[timeframe],
        "ob_age_bars": float(len(frames[timeframe]) - 1 - int(block["ob_index"])),
        "ob_width_atr": (
            float(block["ob_high"] - block["ob_low"]) / chosen["atr"]
        ),
        "ob_distance_atr": chosen["distance"],
        "ob_mitigated": float(bool(block.get("mitigated", False))),
        "ob_mitigation_touch_count": float(chosen["touches"]),
        "ob_missing": 0.0,
    }


def event_geometry(frames: dict[str, pd.DataFrame], event: dict,
                   as_of, decision_bar: pd.Series) -> dict:
    states = {name: _structure(frame, name) for name, frame in frames.items()}
    structures = {name: item[0] for name, item in states.items()}
    direction = event["direction"]
    expected = "bullish" if direction == "BUY" else "bearish"
    sign = 1.0 if direction == "BUY" else -1.0
    price = float(decision_bar["close"])
    atr_1h = _atr(frames["1H"])
    event_frame = frames[event["timeframe"]]
    event_atr = _atr(event_frame)
    event_bar = event_frame.iloc[event["event_index"]]
    item = event["object"]
    if event["event_type"].startswith("SWEEP"):
        level = float(item["swept_level"])
    elif event["event_type"].startswith("FVG"):
        level = (float(item["fvg_low"]) + float(item["fvg_high"])) / 2
    else:
        level = float(item["broken_level"])

    directional = {}
    for timeframe in ("4H", "1H", "15M"):
        _, highs, lows = states[timeframe]
        directional[timeframe] = _directional_objects(
            frames[timeframe], timeframe, direction, highs, lows,
        )
    _, highs_1h, lows_1h = states["1H"]
    sweep = (detect_liquidity_sweep_up(frames["1H"], lows_1h)
             if direction == "BUY" else
             detect_liquidity_sweep_down(frames["1H"], highs_1h))
    if sweep is None:
        sweep_values = {
            "sweep_present": 0.0, "sweep_age_bars_1h": np.nan,
            "sweep_depth_atr_1h": np.nan, "sweep_reclaim_atr_1h": np.nan,
            "sweep_reclaim_fraction": np.nan,
            "distance_to_swept_level_atr_1h": np.nan, "sweep_missing": 1.0,
        }
    else:
        sweep_level = float(sweep["swept_level"])
        wick = float(sweep["wick_low"] if direction == "BUY" else sweep["wick_high"])
        close_after = float(sweep["close_after"])
        depth = (sweep_level - wick if direction == "BUY" else wick - sweep_level)
        reclaim = (close_after - sweep_level if direction == "BUY"
                   else sweep_level - close_after)
        sweep_values = {
            "sweep_present": 1.0,
            "sweep_age_bars_1h": _age(frames["1H"], sweep, "sweep_index"),
            "sweep_depth_atr_1h": depth / atr_1h,
            "sweep_reclaim_atr_1h": reclaim / atr_1h,
            "sweep_reclaim_fraction": reclaim / max(depth + reclaim, 1e-12),
            "distance_to_swept_level_atr_1h": sign * (price - sweep_level) / atr_1h,
            "sweep_missing": 0.0,
        }

    fvg = (detect_fvg(frames["1H"]) if direction == "BUY"
           else detect_bearish_fvg(frames["1H"]))
    if fvg is None:
        fvg_values = {
            "fvg_present": 0.0, "fvg_age_bars_1h": np.nan,
            "fvg_width_atr_1h": np.nan, "fvg_distance_atr_1h": np.nan,
            "fvg_missing": 1.0,
        }
    else:
        fvg_values = {
            "fvg_present": 1.0,
            "fvg_age_bars_1h": float(fvg["age_candles"]),
            "fvg_width_atr_1h": (
                float(fvg["fvg_high"] - fvg["fvg_low"]) / atr_1h
            ),
            "fvg_distance_atr_1h": _distance_to_zone(
                price, float(fvg["fvg_low"]), float(fvg["fvg_high"]),
            ) / atr_1h,
            "fvg_missing": 0.0,
        }

    value = classify_premium_discount(
        frames["4H"], states["4H"][1], states["4H"][2],
    )
    raw_value = float(value.get("pct_in_range", 0.5))
    as_of = pd.Timestamp(as_of)
    radians = 2 * math.pi * (as_of.hour * 60 + as_of.minute) / 1440
    event_flags = {name: 0.0 for name in (
        "event_type_sweep_1h", "event_type_choch_1h", "event_type_fvg_1h",
        "event_type_bos_4h", "event_type_choch_4h",
    )}
    event_flags[f"event_type_{event['event_type'].lower()}"] = 1.0
    ask_close = float(decision_bar["ask_close"])
    bid_close = float(decision_bar["bid_close"])
    result = {
        "event_direction_encoded": sign,
        **event_flags,
        "event_break_distance_atr": sign * (float(event_bar["close"]) - level) / event_atr,
        "event_body_atr": abs(float(event_bar["close"] - event_bar["open"])) / event_atr,
        "event_range_atr": float(event_bar["high"] - event_bar["low"]) / event_atr,
        **sweep_values,
        "bos_age_bars_4h": _age(frames["4H"], directional["4H"]["bos"], "bos_index"),
        "choch_age_bars_4h": _age(frames["4H"], directional["4H"]["choch"], "choch_index"),
        "bos_age_bars_1h": _age(frames["1H"], directional["1H"]["bos"], "bos_index"),
        "choch_age_bars_1h": _age(frames["1H"], directional["1H"]["choch"], "choch_index"),
        "bos_age_bars_15m": _age(frames["15M"], directional["15M"]["bos"], "bos_index"),
        "choch_age_bars_15m": _age(frames["15M"], directional["15M"]["choch"], "choch_index"),
        "structure_1w_encoded": STRUCTURE_ENCODING[structures["1W"]],
        "structure_1d_encoded": STRUCTURE_ENCODING[structures["1D"]],
        "structure_4h_encoded": STRUCTURE_ENCODING[structures["4H"]],
        "structure_1h_encoded": STRUCTURE_ENCODING[structures["1H"]],
        "structure_15m_encoded": STRUCTURE_ENCODING[structures["15M"]],
        "structure_alignment_count": float(sum(
            structure == expected for structure in structures.values()
        )),
        "structure_4h_transition": _transition(
            frames["4H"], "4H", structures["4H"],
        ),
        "structure_1h_transition": _transition(
            frames["1H"], "1H", structures["1H"],
        ),
        "value_position_4h_raw": raw_value,
        "value_position_4h_clipped": float(np.clip(raw_value, 0, 1)),
        **_order_block_geometry(frames, states, direction, price),
        **fvg_values,
        "atr_1h_pct": atr_1h / price * 100,
        "spread_close_bps": (ask_close - bid_close) / price * 10_000,
        "hour_sin": math.sin(radians), "hour_cos": math.cos(radians),
        "bos_4h_missing": float(directional["4H"]["bos"] is None),
        "choch_4h_missing": float(directional["4H"]["choch"] is None),
        "bos_1h_missing": float(directional["1H"]["bos"] is None),
        "choch_1h_missing": float(directional["1H"]["choch"] is None),
        "bos_15m_missing": float(directional["15M"]["bos"] is None),
        "choch_15m_missing": float(directional["15M"]["choch"] is None),
    }
    if set(result) != set(EVENT_FEATURES):
        raise RuntimeError("event geometry implementation differs from contract")
    values = np.asarray([result[name] for name in EVENT_FEATURES], dtype=float)
    if np.isinf(values).any():
        raise ValueError("event geometry produced infinite values")
    return {name: result[name] for name in EVENT_FEATURES}


def build(source: pd.DataFrame, contract: dict) -> pd.DataFrame:
    frames = {name: resample_closed_bars(source, rule) for name, rule in TF_RULES.items()}
    first_time = max(frame.index[MINIMUMS[name] - 1] for name, frame in frames.items()
                     if len(frame) >= MINIMUMS[name])
    scan_times = frames["1H"].index[frames["1H"].index >= first_time]
    rows, seen = [], set()
    symbol, version = contract["source_contract"]["symbol"], contract["contract_version"]
    for position, as_of in enumerate(scan_times, start=1):
        sliced = {}
        for name, frame in frames.items():
            visible = frame.loc[:as_of].tail(
                contract["source_contract"]["maximum_visible_bars_per_timeframe"]
            ).copy()
            if len(visible) < MINIMUMS[name]:
                break
            sliced[name] = visible
        if len(sliced) != 5 or as_of not in source.index:
            continue
        decision_bar = source.loc[as_of]
        if isinstance(decision_bar, pd.DataFrame):
            decision_bar = decision_bar.iloc[-1]
        atr_1h = _atr(sliced["1H"])
        if not np.isfinite(atr_1h) or atr_1h <= 0:
            continue
        for event in current_events(sliced, as_of):
            event_time = pd.Timestamp(sliced[event["timeframe"]].index[event["event_index"]])
            if event_time > as_of:
                raise RuntimeError("source event time is after decision time")
            event_id = stable_event_id(
                version, symbol, event["direction"], event["event_type"], event_time,
            )
            if event_id in seen:
                continue
            seen.add(event_id)
            entry = float(decision_bar["close"])
            if event["direction"] == "BUY":
                stop, target = entry - atr_1h, entry + 2 * atr_1h
            else:
                stop, target = entry + atr_1h, entry - 2 * atr_1h
            geometry = event_geometry(sliced, event, as_of, decision_bar)
            rows.append({
                "timestamp": as_of.isoformat(), "event_id": event_id,
                "event_source_time": event_time.isoformat(),
                "event_type": event["event_type"], "source_timeframe": event["timeframe"],
                "pair": symbol, "direction": event["direction"],
                "entry": entry, "stop_loss": float(stop),
                "take_profit": float(target), "rr_ratio": 2.0,
                "atr_1h": atr_1h, **geometry,
            })
        if position % 2000 == 0:
            LOG.info("processed %s/%s hourly decisions; %s unique events",
                     position, len(scan_times), len(rows))
    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError("event-universe extraction produced no events")
    if result["event_id"].duplicated().any():
        raise RuntimeError("event-universe extraction produced duplicate event IDs")
    if (pd.to_datetime(result["event_source_time"], utc=True) >
            pd.to_datetime(result["timestamp"], utc=True)).any():
        raise RuntimeError("event-universe extraction produced future source event times")
    return result.sort_values(["timestamp", "event_id"]).reset_index(drop=True)


def write_dataset(source_path: Path, output: Path,
                  contract_path: Path = CONTRACT_PATH) -> dict:
    contract, contract_sha = load_contract(contract_path)
    source_contract = contract["source_contract"]
    manifest_path = Path(source_contract["source_manifest_path"])
    if (_sha256(source_path) != source_contract["source_sha256"] or
            _sha256(manifest_path) != source_contract["source_manifest_sha256"]):
        raise RuntimeError("event-universe source lineage hash mismatch")
    source = load_ohlcv(source_path, "open")
    result = build(source, contract)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    result.to_csv(temporary, index=False)
    temporary.replace(output)
    report = {
        "schema_version": 1,
        "contract_version": contract["contract_version"],
        "contract_sha256": contract_sha,
        "source_path": str(source_path), "source_sha256": _sha256(source_path),
        "source_manifest_sha256": _sha256(manifest_path),
        "dataset_sha256": _sha256(output), "rows": len(result),
        "first_event_time": result["timestamp"].iloc[0],
        "last_event_time": result["timestamp"].iloc[-1],
        "event_type_counts": result["event_type"].value_counts().sort_index().to_dict(),
        "direction_counts": result["direction"].value_counts().sort_index().to_dict(),
        "duplicate_event_ids": int(result["event_id"].duplicated().sum()),
        "future_source_event_times": int((
            pd.to_datetime(result["event_source_time"], utc=True) >
            pd.to_datetime(result["timestamp"], utc=True)
        ).sum()),
        "feature_count": len(EVENT_FEATURES),
        "feature_schema_sha256": _schema_sha256(EVENT_FEATURES),
        "contains_outcomes": False,
        "research_warning": (
            "Outcome-free event extraction from contaminated development history; "
            "no result or runtime authorization is implied."
        ),
    }
    output.with_suffix(output.suffix + ".manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("agent.smc_gold_scanner").setLevel(logging.WARNING)
    print(json.dumps(write_dataset(args.source, args.output, args.contract), indent=2))


if __name__ == "__main__":
    main()
