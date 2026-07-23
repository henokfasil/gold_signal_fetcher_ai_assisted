"""Prospective, outcome-blind journal for the frozen event-first universe.

This module observes the already validated Dukascopy snapshot.  It has no
connection to candidate scoring, Claude, Telegram, paper positions or broker
execution.
"""

import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import settings
from research.build_event_candidate_universe import (
    EVENT_FEATURES,
    _atr,
    current_events,
    event_geometry,
    load_contract as load_parent_event_contract,
    stable_event_id,
)


EXPECTED_CONTRACT_SHA256 = (
    "bdc69d70bf4aa7e0b340d4d9825ffded7567fd2bf7743881f7fb548490fed7fd"
)
EXPECTED_PARENT_CONTRACT_SHA256 = (
    "2b57fac00d70b60452a19e14b2daa8d264316016d89fc2425bebf3e05ad40c12"
)
EXPECTED_GEOMETRY_SCHEMA_SHA256 = (
    "346753a3c3effc9f53d42ddde0f9fba296d736ecf38c883515f96995c5d0c252"
)

EVENT_BASE_COLUMNS = [
    "observation_version",
    "observation_contract_sha256",
    "parent_event_contract_version",
    "parent_event_contract_sha256",
    "geometry_schema_sha256",
    "snapshot_sha256",
    "snapshot_captured_at",
    "timestamp",
    "event_id",
    "event_source_time",
    "event_type",
    "source_timeframe",
    "pair",
    "direction",
    "entry",
    "stop_loss",
    "take_profit",
    "rr_ratio",
    "atr_1h",
    "paper_research_only",
]
EVENT_COLUMNS = [*EVENT_BASE_COLUMNS, *EVENT_FEATURES]
SCAN_COLUMNS = [
    "observation_version",
    "observation_contract_sha256",
    "snapshot_sha256",
    "snapshot_captured_at",
    "decision_time",
    "observed_at",
    "provider",
    "symbol",
    "detected_event_count",
    "new_event_count",
    "event_ids",
    "status",
    "paper_research_only",
    "decision_effect",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_utc(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_snapshot_sha256(payload: dict) -> str:
    """Hash the snapshot exactly as the atomic collector does."""
    content = {key: value for key, value in payload.items() if key != "content_sha256"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def load_forward_event_contract(
    path: Path = settings.FORWARD_EVENT_CONFIG,
) -> tuple[dict, str, dict]:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    contract = json.loads(raw)
    parent_spec = contract.get("parent_event_contract", {})
    source = contract.get("source_contract", {})
    event_rows = contract.get("event_row_contract", {})
    scan_rows = contract.get("scan_row_contract", {})
    isolation = contract.get("isolation", {})
    if digest != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("forward-event contract hash mismatch; register a new version")
    if (
        contract.get("schema_version") != 1
        or contract.get("observation_version")
        != "forward-event-observation-20260723-v1"
        or contract.get("paper_research_only") is not True
        or parent_spec.get("contract_sha256") != EXPECTED_PARENT_CONTRACT_SHA256
        or parent_spec.get("geometry_schema_sha256")
        != EXPECTED_GEOMETRY_SCHEMA_SHA256
        or int(parent_spec.get("geometry_feature_count", -1)) != len(EVENT_FEATURES)
        or source.get("provider") != "dukascopy-public"
        or source.get("symbol") != "DUKASCOPY:XAUUSD"
        or source.get("forming_bars_permitted") is not False
        or event_rows.get("base_columns") != EVENT_BASE_COLUMNS
        or event_rows.get("outcome_columns_permitted") is not False
        or scan_rows.get("columns") != SCAN_COLUMNS
        or isolation.get("may_read_or_create_outcomes") is not False
        or isolation.get("may_score_or_approve_paper_candidate") is not False
        or isolation.get("may_change_smc_ml_macro_or_claude_decision") is not False
        or isolation.get("may_send_telegram") is not False
        or isolation.get("may_place_broker_order") is not False
        or isolation.get("may_train_select_or_promote_model") is not False
    ):
        raise RuntimeError("forward-event contract violates its frozen schema or isolation")
    parent_path = settings.PROJECT_ROOT / parent_spec["path"]
    parent, parent_digest = load_parent_event_contract(parent_path)
    if (
        parent_digest != EXPECTED_PARENT_CONTRACT_SHA256
        or parent.get("contract_version") != parent_spec.get("contract_version")
    ):
        raise RuntimeError("parent event contract drift")
    return contract, digest, parent


def snapshot_frames(payload: dict, contract: dict) -> dict[str, pd.DataFrame]:
    """Convert open-timestamp snapshot bars to completed-close indexed frames."""
    source = contract["source_contract"]
    expected = source["expected_cadence_seconds"]
    frames = {}
    for name in source["required_timeframes"]:
        cadence = int(expected[name])
        bars = payload["timeframes"][name]["bars"]
        maximum = int(source["maximum_visible_bars_per_timeframe"])
        if len(bars) != maximum:
            raise ValueError(
                f"{name} snapshot contains {len(bars)} bars; expected {maximum}"
            )
        records = []
        for bar in bars:
            record = {
                "timestamp": pd.to_datetime(
                    int(bar["time"]) + cadence, unit="s", utc=True,
                ),
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": float(bar.get("volume", 0.0)),
                "bid_open": float(bar["bid_open"]),
                "bid_high": float(bar["bid_high"]),
                "bid_low": float(bar["bid_low"]),
                "bid_close": float(bar["bid_close"]),
                "ask_open": float(bar["ask_open"]),
                "ask_high": float(bar["ask_high"]),
                "ask_low": float(bar["ask_low"]),
                "ask_close": float(bar["ask_close"]),
            }
            if not all(
                math.isfinite(value)
                for key, value in record.items()
                if key != "timestamp"
            ):
                raise ValueError(f"{name} contains a non-finite price value")
            records.append(record)
        frame = pd.DataFrame(records).set_index("timestamp").sort_index()
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError(f"{name} completed-close timestamps are invalid")
        frames[name] = frame
    return frames


def _existing_unique_values(path: Path, column: str, columns: list[str]) -> set[str]:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise RuntimeError(f"{path.name} schema drift")
        values = [str(row.get(column, "")).strip() for row in reader]
    if any(not value for value in values):
        raise RuntimeError(f"{path.name} contains an empty {column}")
    if len(values) != len(set(values)):
        raise RuntimeError(f"{path.name} contains duplicate {column} values")
    return set(values)


def _csv_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value


def _append_rows(path: Path, columns: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    if exists:
        with path.open(newline="") as handle:
            if next(csv.reader(handle), []) != columns:
                raise RuntimeError(f"{path.name} schema drift")
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column, "")) for column in columns})
        handle.flush()
        os.fsync(handle.fileno())


class ForwardEventJournal:
    """Append one frozen event row per stable ID and one scan row per 1H close."""

    def __init__(
        self,
        event_path: Path = settings.FORWARD_EVENT_OBSERVATIONS_CSV,
        scan_path: Path = settings.FORWARD_EVENT_SCANS_CSV,
        contract_path: Path = settings.FORWARD_EVENT_CONFIG,
    ):
        self.event_path = Path(event_path)
        self.scan_path = Path(scan_path)
        self.contract, self.contract_sha256, self.parent = (
            load_forward_event_contract(contract_path)
        )
        self.collection_start = _parse_utc(
            self.contract["collection_starts_at_utc"]
        )

    def observe(self, payload: dict, observed_at: datetime | None = None) -> dict:
        source = self.contract["source_contract"]
        if (
            payload.get("schema_version") != source["snapshot_schema_version"]
            or payload.get("provider") != source["provider"]
            or payload.get("symbol") != source["symbol"]
            or payload.get("paper_research_only") is not True
        ):
            raise ValueError("event observation received the wrong snapshot identity")
        snapshot_sha = str(payload.get("content_sha256", ""))
        if not snapshot_sha or snapshot_sha != canonical_snapshot_sha256(payload):
            raise ValueError("event observation snapshot content hash mismatch")

        frames = snapshot_frames(payload, self.contract)
        decision_time = frames["1H"].index[-1]
        decision_dt = decision_time.to_pydatetime().astimezone(timezone.utc)
        if decision_dt < self.collection_start:
            return {
                "status": "BEFORE_REGISTERED_START",
                "decision_time": decision_dt.isoformat(),
                "detected_event_count": 0,
                "new_event_count": 0,
            }

        completed_decisions = _existing_unique_values(
            self.scan_path, "decision_time", SCAN_COLUMNS,
        )
        decision_iso = decision_dt.isoformat()
        if decision_iso in completed_decisions:
            return {
                "status": "ALREADY_OBSERVED",
                "decision_time": decision_iso,
                "detected_event_count": 0,
                "new_event_count": 0,
            }

        minimum = int(source["minimum_visible_bars_per_timeframe"])
        maximum = int(source["maximum_visible_bars_per_timeframe"])
        visible = {}
        for name, frame in frames.items():
            sliced = frame.loc[:decision_time].tail(maximum).copy()
            if len(sliced) < minimum:
                raise ValueError(
                    f"{name} has {len(sliced)} visible completed bars; need {minimum}"
                )
            visible[name] = sliced
        if decision_time not in visible["15M"].index:
            raise ValueError("1H decision time has no exact completed 15M decision bar")
        decision_bar = visible["15M"].loc[decision_time]
        if isinstance(decision_bar, pd.DataFrame):
            decision_bar = decision_bar.iloc[-1]
        atr_1h = _atr(visible["1H"])
        if not math.isfinite(atr_1h) or atr_1h <= 0:
            raise ValueError("event observation has no valid 1H ATR")

        parent_version = self.parent["contract_version"]
        symbol = source["symbol"]
        existing_ids = _existing_unique_values(
            self.event_path, "event_id", EVENT_COLUMNS,
        )
        detected = []
        new_rows = []
        for event in current_events(visible, decision_time):
            event_time = pd.Timestamp(
                visible[event["timeframe"]].index[event["event_index"]]
            )
            if event_time > decision_time:
                raise RuntimeError("prospective event source time is after decision time")
            event_id = stable_event_id(
                parent_version,
                symbol,
                event["direction"],
                event["event_type"],
                event_time,
            )
            detected.append(event_id)
            if event_id in existing_ids:
                continue
            entry = float(decision_bar["close"])
            if event["direction"] == "BUY":
                stop_loss, take_profit = entry - atr_1h, entry + 2 * atr_1h
            else:
                stop_loss, take_profit = entry + atr_1h, entry - 2 * atr_1h
            geometry = event_geometry(
                visible, event, decision_time, decision_bar,
            )
            new_rows.append({
                "observation_version": self.contract["observation_version"],
                "observation_contract_sha256": self.contract_sha256,
                "parent_event_contract_version": parent_version,
                "parent_event_contract_sha256": EXPECTED_PARENT_CONTRACT_SHA256,
                "geometry_schema_sha256": EXPECTED_GEOMETRY_SCHEMA_SHA256,
                "snapshot_sha256": snapshot_sha,
                "snapshot_captured_at": payload["captured_at"],
                "timestamp": decision_iso,
                "event_id": event_id,
                "event_source_time": event_time.isoformat(),
                "event_type": event["event_type"],
                "source_timeframe": event["timeframe"],
                "pair": symbol,
                "direction": event["direction"],
                "entry": entry,
                "stop_loss": float(stop_loss),
                "take_profit": float(take_profit),
                "rr_ratio": 2.0,
                "atr_1h": float(atr_1h),
                "paper_research_only": True,
                **geometry,
            })
            existing_ids.add(event_id)

        if len(detected) != len(set(detected)):
            raise RuntimeError("event detector returned duplicate stable IDs")
        _append_rows(self.event_path, EVENT_COLUMNS, new_rows)
        observed = observed_at or datetime.now(timezone.utc)
        if observed.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        scan_row = {
            "observation_version": self.contract["observation_version"],
            "observation_contract_sha256": self.contract_sha256,
            "snapshot_sha256": snapshot_sha,
            "snapshot_captured_at": payload["captured_at"],
            "decision_time": decision_iso,
            "observed_at": observed.astimezone(timezone.utc).isoformat(),
            "provider": source["provider"],
            "symbol": symbol,
            "detected_event_count": len(detected),
            "new_event_count": len(new_rows),
            "event_ids": json.dumps(sorted(detected), separators=(",", ":")),
            "status": "PASS",
            "paper_research_only": True,
            "decision_effect": "NONE_OBSERVATION_ONLY",
        }
        _append_rows(self.scan_path, SCAN_COLUMNS, [scan_row])
        return {
            "status": "PASS",
            "decision_time": decision_iso,
            "detected_event_count": len(detected),
            "new_event_count": len(new_rows),
        }
