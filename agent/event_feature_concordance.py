"""Outcome-blind runtime/historical concordance for frozen event features.

The runtime side is reconstructed from content-addressed native-timeframe
snapshots.  The comparison side is reconstructed from a delayed, separately
fetched set of all five native timeframes and causally sliced to the exact
runtime window.  This module has no connection to outcomes, candidate scoring,
Claude, notifications, paper positions or broker execution.
"""

import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from agent.forward_event_journal import (
    EVENT_COLUMNS,
    SCAN_COLUMNS,
    canonical_snapshot_sha256,
    load_forward_event_contract,
    snapshot_frames,
)
from config import settings
from research.build_event_candidate_universe import (
    EVENT_FEATURES,
    _atr,
    current_events,
    event_geometry,
    stable_event_id,
)


EXPECTED_CONTRACT_SHA256 = (
    "eb93d931d3e93650633c7010b59618670f8c9815a49033cb1e3698ccc7daab95"
)
EXPECTED_FORWARD_CONTRACT_SHA256 = (
    "bdc69d70bf4aa7e0b340d4d9825ffded7567fd2bf7743881f7fb548490fed7fd"
)
EXPECTED_PARENT_CONTRACT_SHA256 = (
    "2b57fac00d70b60452a19e14b2daa8d264316016d89fc2425bebf3e05ad40c12"
)
EXPECTED_GEOMETRY_SCHEMA_SHA256 = (
    "346753a3c3effc9f53d42ddde0f9fba296d736ecf38c883515f96995c5d0c252"
)
IDENTITY_FIELDS = [
    "event_id",
    "event_source_time",
    "event_type",
    "source_timeframe",
    "pair",
    "direction",
]
NUMERIC_BASE_FIELDS = [
    "entry",
    "stop_loss",
    "take_profit",
    "rr_ratio",
    "atr_1h",
]
NUMERIC_CONTRACT_FIELDS = [
    *NUMERIC_BASE_FIELDS,
    "ALL_55_REGISTERED_GEOMETRY_FEATURES",
]
NUMERIC_FIELDS = [
    *NUMERIC_BASE_FIELDS,
    *EVENT_FEATURES,
]
HEX_DIGITS = set("0123456789abcdef")
EXPECTED_TIMEFRAMES = ["1W", "1D", "4H", "1H", "15M"]
EXPECTED_CADENCES = {
    "1W": 604800,
    "1D": 86400,
    "4H": 14400,
    "1H": 3600,
    "15M": 900,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_utc(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else settings.PROJECT_ROOT / path


def load_event_feature_concordance_contract(
    path: Path = settings.EVENT_FEATURE_CONCORDANCE_CONFIG,
) -> tuple[dict, str, dict, dict]:
    """Load the hash-locked concordance contract and both frozen parents."""
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    contract = json.loads(raw)
    runtime = contract.get("runtime_observation_contract", {})
    parent = contract.get("parent_event_contract", {})
    preflight = contract.get("preflight_finding", {})
    replay = contract.get("independent_replay_source", {})
    comparison = contract.get("comparison_contract", {})
    gates = contract.get("authorization_gates", {})
    isolation = contract.get("isolation", {})
    if digest != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError(
            "event-feature-concordance contract hash mismatch; register a new version"
        )
    if (
        contract.get("schema_version") != 1
        or contract.get("monitor_version")
        != "event-feature-concordance-20260723-v1"
        or contract.get("paper_research_only") is not True
        or runtime.get("contract_sha256") != EXPECTED_FORWARD_CONTRACT_SHA256
        or runtime.get("snapshot_archive_append_only") is not True
        or parent.get("contract_sha256") != EXPECTED_PARENT_CONTRACT_SHA256
        or parent.get("geometry_schema_sha256")
        != EXPECTED_GEOMETRY_SCHEMA_SHA256
        or int(parent.get("geometry_feature_count", -1)) != len(EVENT_FEATURES)
        or preflight.get("decision")
        != "REJECT_15M_RESAMPLED_FEATURES_FOR_NATIVE_RUNTIME_PROMOTION"
        or int(preflight.get("numeric_feature_mismatches", -1)) != 107
        or int(preflight.get("missingness_mismatches", -1)) != 10
        or replay.get("provider") != "dukascopy-public"
        or replay.get("symbol") != "DUKASCOPY:XAUUSD"
        or replay.get("snapshot_schema_version") != 2
        or replay.get("required_timeframes") != EXPECTED_TIMEFRAMES
        or replay.get("expected_cadence_seconds") != EXPECTED_CADENCES
        or int(replay.get("runtime_window_bars_per_timeframe", -1)) != 200
        or int(replay.get("reference_bars_per_timeframe", -1)) != 400
        or replay.get("collector_path") != "ops/collect_dukascopy_snapshot.py"
        or int(replay.get("minimum_delay_after_cutoff_minutes", -1)) != 20
        or replay.get("one_reference_per_cutoff") is not True
        or replay.get("reference_snapshot_append_only") is not True
        or replay.get("reference_manifest_append_only") is not True
        or comparison.get("identity_fields_exact") != IDENTITY_FIELDS
        or comparison.get("numeric_fields") != NUMERIC_CONTRACT_FIELDS
        or comparison.get("missing_values_match_exactly") is not True
        or comparison.get("performance_or_outcome_columns_permitted") is not False
        or float(comparison.get("absolute_tolerance", -1)) != 1e-9
        or float(comparison.get("relative_tolerance", -1)) != 1e-9
        or int(comparison.get("future_source_event_times_allowed", -1)) != 0
        or int(comparison.get("duplicate_scan_times_allowed", -1)) != 0
        or int(comparison.get("duplicate_event_ids_allowed", -1)) != 0
        or int(gates.get("minimum_compared_decision_times", -1)) != 120
        or int(gates.get("minimum_compared_events", -1)) != 30
        or gates.get("required_directions") != ["BUY", "SELL"]
        or gates.get("required_event_types")
        != ["SWEEP_1H", "CHOCH_1H", "FVG_1H", "BOS_4H", "CHOCH_4H"]
        or int(gates.get("maximum_authorization_artifact_age_hours", -1)) != 30
        or int(gates.get("maximum_latest_runtime_to_replay_lag_hours", -1)) != 36
        or int(gates.get("runtime_archive_or_self_replay_failures_allowed", -1))
        != 0
        or int(gates.get("historical_membership_mismatches_allowed", -1)) != 0
        or int(gates.get("identity_mismatches_allowed", -1)) != 0
        or int(gates.get("numeric_or_missingness_mismatches_allowed", -1)) != 0
        or gates.get("source_or_contract_hash_drift_allowed") is not False
        or isolation.get("may_read_or_create_outcomes") is not False
        or isolation.get("may_read_performance_columns") is not False
        or isolation.get("may_evaluate_profitability") is not False
        or isolation.get("may_score_or_approve_candidate") is not False
        or isolation.get("may_change_smc_ml_macro_or_claude_decision") is not False
        or isolation.get("may_send_telegram") is not False
        or isolation.get("may_place_broker_order") is not False
        or isolation.get("may_train_select_or_promote_model") is not False
        or isolation.get("failure_may_block_existing_candidate_pipeline") is not False
        or contract.get("status_artifact", {}).get("contains_performance") is not False
    ):
        raise RuntimeError(
            "event-feature-concordance contract violates its frozen schema or isolation"
        )
    preflight_path = _project_path(preflight["report_path"])
    if _sha256(preflight_path) != preflight["report_sha256"]:
        raise RuntimeError("event-feature-concordance preflight report hash drift")
    forward_path = _project_path(runtime["path"])
    forward, forward_digest, parent_contract = load_forward_event_contract(
        forward_path
    )
    if (
        forward_digest != EXPECTED_FORWARD_CONTRACT_SHA256
        or forward.get("observation_version") != runtime.get("observation_version")
        or parent_contract.get("contract_version") != parent.get("contract_version")
    ):
        raise RuntimeError("event-feature-concordance parent contract drift")
    return contract, digest, forward, parent_contract


class RuntimeEventSnapshotArchive:
    """Persist exactly one content-addressed snapshot for each new 1H scan."""

    def __init__(
        self,
        archive_dir: Path | None = None,
        contract_path: Path = settings.EVENT_FEATURE_CONCORDANCE_CONFIG,
    ):
        self.contract, self.contract_sha256, self.forward, _ = (
            load_event_feature_concordance_contract(contract_path)
        )
        configured = self.contract["runtime_observation_contract"][
            "snapshot_archive_directory"
        ]
        self.archive_dir = Path(archive_dir or _project_path(configured))
        self.collection_start = _parse_utc(
            self.contract["collection_starts_at_utc"]
        )

    def archive(self, payload: dict, decision_time) -> dict:
        decision = _parse_utc(decision_time)
        if decision < self.collection_start:
            return {"status": "BEFORE_REGISTERED_START", "path": ""}
        snapshot_sha = str(payload.get("content_sha256", "")).lower()
        if (
            len(snapshot_sha) != 64
            or any(character not in HEX_DIGITS for character in snapshot_sha)
            or snapshot_sha != canonical_snapshot_sha256(payload)
        ):
            raise ValueError("runtime archive received an invalid snapshot content hash")
        frames = snapshot_frames(payload, self.forward)
        actual_decision = frames["1H"].index[-1].to_pydatetime()
        if actual_decision.astimezone(timezone.utc) != decision:
            raise ValueError("runtime archive decision time does not match the snapshot")

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        target = self.archive_dir / f"{snapshot_sha}.json"
        if target.exists():
            existing = json.loads(target.read_text())
            if canonical_snapshot_sha256(existing) != snapshot_sha or existing != payload:
                raise RuntimeError("content-addressed runtime snapshot collision")
            return {"status": "ALREADY_ARCHIVED", "path": str(target)}

        temporary = self.archive_dir / f".{snapshot_sha}.{os.getpid()}.tmp"
        with temporary.open("x") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists():
            existing = json.loads(target.read_text())
            temporary.unlink()
            if canonical_snapshot_sha256(existing) != snapshot_sha or existing != payload:
                raise RuntimeError("content-addressed runtime snapshot collision")
            return {"status": "ALREADY_ARCHIVED", "path": str(target)}
        temporary.replace(target)
        return {"status": "ARCHIVED", "path": str(target)}


def _read_exact_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=columns)
    with path.open(newline="") as handle:
        header = next(csv.reader(handle), [])
    if header != columns:
        raise RuntimeError(f"{path.name} schema drift")
    return pd.read_csv(path, dtype=str).fillna("")[columns]


def _parse_scan_event_ids(value) -> list[str]:
    parsed = json.loads(str(value))
    if (
        not isinstance(parsed, list)
        or any(not isinstance(item, str) or not item for item in parsed)
        or len(parsed) != len(set(parsed))
    ):
        raise ValueError("event scan contains invalid event_ids")
    return sorted(parsed)


def _visible_frames(
    frames: dict[str, pd.DataFrame],
    decision_time: pd.Timestamp,
    forward_contract: dict,
) -> dict[str, pd.DataFrame]:
    source = forward_contract["source_contract"]
    maximum = int(source["maximum_visible_bars_per_timeframe"])
    visible = {}
    for name in source["required_timeframes"]:
        frame = frames[name].loc[:decision_time].tail(maximum).copy()
        if len(frame) != maximum:
            raise ValueError(
                f"{name} has {len(frame)} completed bars at {decision_time}; "
                f"need the exact {maximum}-bar runtime window"
            )
        visible[name] = frame
    if decision_time not in visible["15M"].index:
        raise ValueError("decision time has no exact completed 15M bar")
    return visible


def _event_rows_at_decision(
    frames: dict[str, pd.DataFrame],
    decision_time,
    forward_contract: dict,
    parent_contract: dict,
    decision_source: pd.DataFrame | None = None,
) -> dict[str, dict]:
    decision = pd.Timestamp(decision_time)
    decision = (
        decision.tz_localize("UTC")
        if decision.tz is None
        else decision.tz_convert("UTC")
    )
    visible = _visible_frames(frames, decision, forward_contract)
    source = decision_source if decision_source is not None else visible["15M"]
    if decision not in source.index:
        raise ValueError("decision time has no exact executable 15M source bar")
    decision_bar = source.loc[decision]
    if isinstance(decision_bar, pd.DataFrame):
        decision_bar = decision_bar.iloc[-1]
    atr_1h = _atr(visible["1H"])
    if not math.isfinite(atr_1h) or atr_1h <= 0:
        raise ValueError("event replay has no valid 1H ATR")
    version = parent_contract["contract_version"]
    symbol = forward_contract["source_contract"]["symbol"]
    rows = {}
    for event in current_events(visible, decision):
        event_time = pd.Timestamp(
            visible[event["timeframe"]].index[event["event_index"]]
        )
        event_id = stable_event_id(
            version,
            symbol,
            event["direction"],
            event["event_type"],
            event_time,
        )
        if event_id in rows:
            raise RuntimeError("event replay produced duplicate stable IDs")
        entry = float(decision_bar["close"])
        if event["direction"] == "BUY":
            stop_loss, take_profit = entry - atr_1h, entry + 2 * atr_1h
        else:
            stop_loss, take_profit = entry + atr_1h, entry - 2 * atr_1h
        rows[event_id] = {
            "timestamp": decision.isoformat(),
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
            **event_geometry(visible, event, decision, decision_bar),
        }
    return rows


def _event_map(frame: pd.DataFrame) -> dict[str, dict]:
    if frame.empty:
        return {}
    return {
        str(row["event_id"]): row
        for row in frame.to_dict("records")
    }


def _is_missing(value) -> bool:
    if value is None or str(value).strip() == "":
        return True
    try:
        return not math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _normalized_identity(field: str, value) -> str:
    if field == "event_source_time":
        return _parse_utc(value).isoformat()
    return str(value).strip()


def _compare_event_maps(
    expected: dict[str, dict],
    actual: dict[str, dict],
    absolute_tolerance: float,
    relative_tolerance: float,
    samples: list[dict],
    stage: str,
) -> dict:
    expected_ids, actual_ids = set(expected), set(actual)
    membership_mismatch = int(expected_ids != actual_ids)
    identity_mismatches = 0
    value_mismatches = 0
    missingness_mismatches = 0
    max_absolute_error = 0.0
    max_relative_error = 0.0
    if membership_mismatch and len(samples) < 12:
        samples.append({
            "stage": stage,
            "field": "event_ids",
            "missing_from_actual": sorted(expected_ids - actual_ids),
            "unexpected_actual": sorted(actual_ids - expected_ids),
        })
    for event_id in sorted(expected_ids & actual_ids):
        left, right = expected[event_id], actual[event_id]
        for field in IDENTITY_FIELDS:
            try:
                matches = (
                    _normalized_identity(field, left.get(field))
                    == _normalized_identity(field, right.get(field))
                )
            except (TypeError, ValueError):
                matches = False
            if not matches:
                identity_mismatches += 1
                if len(samples) < 12:
                    samples.append({
                        "stage": stage,
                        "event_id": event_id,
                        "field": field,
                        "expected": str(left.get(field)),
                        "actual": str(right.get(field)),
                    })
        for field in NUMERIC_FIELDS:
            left_missing, right_missing = (
                _is_missing(left.get(field)),
                _is_missing(right.get(field)),
            )
            if left_missing or right_missing:
                if left_missing != right_missing:
                    missingness_mismatches += 1
                    if len(samples) < 12:
                        samples.append({
                            "stage": stage,
                            "event_id": event_id,
                            "field": field,
                            "expected": str(left.get(field)),
                            "actual": str(right.get(field)),
                            "kind": "missingness",
                        })
                continue
            try:
                left_value, right_value = float(left[field]), float(right[field])
            except (TypeError, ValueError, KeyError):
                value_mismatches += 1
                continue
            absolute_error = abs(left_value - right_value)
            relative_error = absolute_error / max(
                abs(left_value), abs(right_value), 1e-15
            )
            max_absolute_error = max(max_absolute_error, absolute_error)
            max_relative_error = max(max_relative_error, relative_error)
            if not math.isclose(
                left_value,
                right_value,
                rel_tol=relative_tolerance,
                abs_tol=absolute_tolerance,
            ):
                value_mismatches += 1
                if len(samples) < 12:
                    samples.append({
                        "stage": stage,
                        "event_id": event_id,
                        "field": field,
                        "expected": left_value,
                        "actual": right_value,
                        "absolute_error": absolute_error,
                        "relative_error": relative_error,
                    })
    return {
        "membership_mismatches": membership_mismatch,
        "identity_mismatches": identity_mismatches,
        "value_mismatches": value_mismatches,
        "missingness_mismatches": missingness_mismatches,
        "max_absolute_error": max_absolute_error,
        "max_relative_error": max_relative_error,
    }


def _merge_metrics(total: dict, current: dict) -> None:
    for name in (
        "membership_mismatches",
        "identity_mismatches",
        "value_mismatches",
        "missingness_mismatches",
    ):
        total[name] += current[name]
    total["max_absolute_error"] = max(
        total["max_absolute_error"], current["max_absolute_error"]
    )
    total["max_relative_error"] = max(
        total["max_relative_error"], current["max_relative_error"]
    )


def _empty_comparison() -> dict:
    return {
        "membership_mismatches": 0,
        "identity_mismatches": 0,
        "value_mismatches": 0,
        "missingness_mismatches": 0,
        "max_absolute_error": 0.0,
        "max_relative_error": 0.0,
    }


def _write_append_only_json(path: Path, payload: dict) -> str:
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text()) != payload:
            raise RuntimeError(f"append-only artifact collision: {path.name}")
        return "ALREADY_EXISTS"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    with temporary.open("x") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    if path.exists():
        existing = json.loads(path.read_text())
        temporary.unlink()
        if existing != payload:
            raise RuntimeError(f"append-only artifact collision: {path.name}")
        return "ALREADY_EXISTS"
    temporary.replace(path)
    return "CREATED"


def _same_market_snapshot(left: dict, right: dict) -> bool:
    fields = (
        "schema_version",
        "provider",
        "symbol",
        "captured_at",
        "timestamp_semantics",
        "price_components",
        "paper_research_only",
        "timeframes",
    )
    return all(left.get(field) == right.get(field) for field in fields)


def _reference_snapshot_frames(
    payload: dict,
    forward_contract: dict,
    reference_bar_count: int,
) -> dict[str, pd.DataFrame]:
    reference_contract = {
        **forward_contract,
        "source_contract": {
            **forward_contract["source_contract"],
            "maximum_visible_bars_per_timeframe": int(reference_bar_count),
        },
    }
    return snapshot_frames(payload, reference_contract)


class DelayedNativeReferenceArchive:
    """Store one separately fetched native snapshot per completed UTC cutoff."""

    def __init__(
        self,
        archive_dir: Path | None = None,
        contract_path: Path = settings.EVENT_FEATURE_CONCORDANCE_CONFIG,
    ):
        self.contract, self.contract_sha256, self.forward, _ = (
            load_event_feature_concordance_contract(contract_path)
        )
        source = self.contract["independent_replay_source"]
        configured = source["reference_archive_directory"]
        self.archive_dir = Path(archive_dir or _project_path(configured))
        self.snapshot_suffix = source["snapshot_suffix"]
        self.manifest_suffix = source["manifest_suffix"]
        self.minimum_delay = int(source["minimum_delay_after_cutoff_minutes"])
        self.reference_bar_count = int(source["reference_bars_per_timeframe"])

    def store(self, payload: dict, collected_at: datetime | None = None) -> dict:
        collected = collected_at or datetime.now(timezone.utc)
        if collected.tzinfo is None:
            raise ValueError("reference collected_at must be timezone-aware")
        collected = collected.astimezone(timezone.utc)
        snapshot_sha = str(payload.get("content_sha256", "")).lower()
        if (
            len(snapshot_sha) != 64
            or any(character not in HEX_DIGITS for character in snapshot_sha)
            or snapshot_sha != canonical_snapshot_sha256(payload)
        ):
            raise ValueError("delayed reference has an invalid snapshot content hash")
        source = self.contract["independent_replay_source"]
        if (
            payload.get("schema_version") != source["snapshot_schema_version"]
            or payload.get("provider") != source["provider"]
            or payload.get("symbol") != source["symbol"]
            or payload.get("paper_research_only") is not True
        ):
            raise ValueError("delayed reference has the wrong source identity")
        cutoff = _parse_utc(payload["captured_at"])
        if any((cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond)):
            raise ValueError("delayed reference cutoff is not UTC midnight")
        if collected < cutoff + pd.Timedelta(minutes=self.minimum_delay):
            raise ValueError("delayed reference was fetched before its minimum delay")
        frames = _reference_snapshot_frames(
            payload,
            self.forward,
            self.reference_bar_count,
        )
        latest_decision = frames["1H"].index[-1].to_pydatetime().astimezone(
            timezone.utc
        )
        if latest_decision > cutoff:
            raise ValueError("delayed reference contains a bar after its cutoff")

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        for manifest_path in self.archive_dir.glob(f"*{self.manifest_suffix}"):
            manifest = json.loads(manifest_path.read_text())
            if _parse_utc(manifest.get("reference_cutoff")) != cutoff:
                continue
            existing_sha = str(manifest.get("snapshot_content_sha256", ""))
            existing_path = self.archive_dir / (
                f"{existing_sha}{self.snapshot_suffix}"
            )
            existing = json.loads(existing_path.read_text())
            if not _same_market_snapshot(existing, payload):
                raise RuntimeError(
                    "delayed native reference changed for an existing cutoff"
                )
            return {
                "status": "ALREADY_CAPTURED",
                "snapshot_path": str(existing_path),
                "manifest_path": str(manifest_path),
                "snapshot_content_sha256": existing_sha,
                "reference_cutoff": cutoff.isoformat(),
                "latest_decision_time": manifest["latest_decision_time"],
            }

        snapshot_path = self.archive_dir / (
            f"{snapshot_sha}{self.snapshot_suffix}"
        )
        _write_append_only_json(snapshot_path, payload)
        manifest = {
            "schema_version": 1,
            "monitor_version": self.contract["monitor_version"],
            "concordance_contract_sha256": self.contract_sha256,
            "snapshot_content_sha256": snapshot_sha,
            "snapshot_file_sha256": _sha256(snapshot_path),
            "reference_cutoff": cutoff.isoformat(),
            "collected_at": collected.isoformat(),
            "minimum_delay_minutes": self.minimum_delay,
            "reference_bars_per_timeframe": self.reference_bar_count,
            "provider": source["provider"],
            "symbol": source["symbol"],
            "latest_decision_time": latest_decision.isoformat(),
            "paper_research_only": True,
            "performance_columns": [],
            "decision_effect": "NONE_OBSERVATION_ONLY",
        }
        manifest_path = self.archive_dir / (
            f"{snapshot_sha}{self.manifest_suffix}"
        )
        _write_append_only_json(manifest_path, manifest)
        return {
            "status": "CAPTURED",
            "snapshot_path": str(snapshot_path),
            "manifest_path": str(manifest_path),
            "snapshot_content_sha256": snapshot_sha,
            "reference_cutoff": cutoff.isoformat(),
            "latest_decision_time": latest_decision.isoformat(),
        }


def _load_delayed_native_references(
    contract: dict,
    forward_contract: dict,
    observed_at: datetime,
) -> tuple[list[dict], dict]:
    source = contract["independent_replay_source"]
    archive_dir = _project_path(source["reference_archive_directory"])
    snapshot_suffix = source["snapshot_suffix"]
    manifest_suffix = source["manifest_suffix"]
    snapshot_paths = {
        path.name[:-len(snapshot_suffix)]: path
        for path in archive_dir.glob(f"*{snapshot_suffix}")
    } if archive_dir.exists() else {}
    manifest_paths = {
        path.name[:-len(manifest_suffix)]: path
        for path in archive_dir.glob(f"*{manifest_suffix}")
    } if archive_dir.exists() else {}
    if not snapshot_paths and not manifest_paths:
        raise FileNotFoundError("no delayed native reference snapshots are available")
    if set(snapshot_paths) != set(manifest_paths):
        raise RuntimeError("delayed native reference snapshot/manifest orphan")

    references = []
    cutoffs = set()
    minimum_delay = int(source["minimum_delay_after_cutoff_minutes"])
    reference_bar_count = int(source["reference_bars_per_timeframe"])
    for snapshot_sha in sorted(snapshot_paths):
        if (
            len(snapshot_sha) != 64
            or any(character not in HEX_DIGITS for character in snapshot_sha)
        ):
            raise RuntimeError("delayed native reference filename is invalid")
        snapshot_path = snapshot_paths[snapshot_sha]
        manifest_path = manifest_paths[snapshot_sha]
        payload = json.loads(snapshot_path.read_text())
        manifest = json.loads(manifest_path.read_text())
        cutoff = _parse_utc(manifest.get("reference_cutoff"))
        collected = _parse_utc(manifest.get("collected_at"))
        if cutoff in cutoffs:
            raise RuntimeError("duplicate delayed native reference cutoff")
        cutoffs.add(cutoff)
        if (
            snapshot_sha != canonical_snapshot_sha256(payload)
            or payload.get("content_sha256") != snapshot_sha
            or _parse_utc(payload.get("captured_at")) != cutoff
            or any((cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond))
            or collected < cutoff + pd.Timedelta(minutes=minimum_delay)
            or collected > observed_at
            or manifest.get("schema_version") != 1
            or manifest.get("monitor_version") != contract["monitor_version"]
            or manifest.get("concordance_contract_sha256")
            != EXPECTED_CONTRACT_SHA256
            or manifest.get("snapshot_content_sha256") != snapshot_sha
            or manifest.get("snapshot_file_sha256") != _sha256(snapshot_path)
            or manifest.get("minimum_delay_minutes") != minimum_delay
            or manifest.get("reference_bars_per_timeframe") != reference_bar_count
            or manifest.get("provider") != source["provider"]
            or manifest.get("symbol") != source["symbol"]
            or manifest.get("paper_research_only") is not True
            or manifest.get("performance_columns") != []
            or manifest.get("decision_effect") != "NONE_OBSERVATION_ONLY"
        ):
            raise RuntimeError("delayed native reference provenance mismatch")
        frames = _reference_snapshot_frames(
            payload,
            forward_contract,
            reference_bar_count,
        )
        latest_decision = pd.Timestamp(frames["1H"].index[-1])
        if (
            latest_decision > cutoff
            or _parse_utc(manifest.get("latest_decision_time"))
            != latest_decision.to_pydatetime().astimezone(timezone.utc)
        ):
            raise RuntimeError("delayed native reference decision coverage mismatch")
        references.append({
            "snapshot_content_sha256": snapshot_sha,
            "reference_cutoff": cutoff,
            "collected_at": collected,
            "latest_decision": latest_decision,
            "frames": frames,
        })
    references.sort(key=lambda item: item["reference_cutoff"])
    return references, {
        "reference_count": len(references),
        "reference_snapshot_sha256s": [
            item["snapshot_content_sha256"] for item in references
        ],
        "first_reference_cutoff": references[0]["reference_cutoff"].isoformat(),
        "latest_reference_cutoff": references[-1]["reference_cutoff"].isoformat(),
        "latest_covered_decision": references[-1]["latest_decision"].isoformat(),
    }


def build_event_feature_concordance_report(
    event_path: Path | None = None,
    scan_path: Path | None = None,
    archive_dir: Path | None = None,
    contract_path: Path = settings.EVENT_FEATURE_CONCORDANCE_CONFIG,
    observed_at: datetime | None = None,
) -> dict:
    """Compare only source identity, event membership and registered features."""
    contract, contract_sha, forward, parent = (
        load_event_feature_concordance_contract(contract_path)
    )
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    now = now.astimezone(timezone.utc)
    runtime = contract["runtime_observation_contract"]
    comparison = contract["comparison_contract"]
    gates = contract["authorization_gates"]
    collection_start = _parse_utc(contract["collection_starts_at_utc"])
    event_path = Path(event_path or _project_path(runtime["event_ledger_path"]))
    scan_path = Path(scan_path or _project_path(runtime["scan_ledger_path"]))
    archive_dir = Path(
        archive_dir or _project_path(runtime["snapshot_archive_directory"])
    )
    all_events = _read_exact_csv(event_path, EVENT_COLUMNS)
    all_scans = _read_exact_csv(scan_path, SCAN_COLUMNS)
    all_scans["_decision"] = pd.to_datetime(
        all_scans["decision_time"], utc=True, errors="coerce"
    )
    all_events["_decision"] = pd.to_datetime(
        all_events["timestamp"], utc=True, errors="coerce"
    )
    invalid_runtime_timestamps = int(
        all_scans["_decision"].isna().sum()
        + all_events["_decision"].isna().sum()
    )
    scans = all_scans[all_scans["_decision"] >= collection_start].copy()
    events = all_events[all_events["_decision"] >= collection_start].copy()
    issues = []
    samples: list[dict] = []
    if invalid_runtime_timestamps:
        issues.append(
            f"runtime event or scan timestamps invalid: {invalid_runtime_timestamps}"
        )
    if scans["decision_time"].duplicated().any():
        issues.append("runtime scan decision times are duplicated")
    if all_events["event_id"].duplicated().any():
        issues.append("runtime event IDs are duplicated")
    scan_decisions = set(scans["_decision"].dropna())
    event_decisions = set(events["_decision"].dropna())
    if event_decisions - scan_decisions:
        issues.append("runtime event rows exist without a matching scan decision")
    if len(scans) and (
        not scans["status"].eq("PASS").all()
        or not scans["observation_version"].eq(
            forward["observation_version"]
        ).all()
        or not scans["observation_contract_sha256"].eq(
            EXPECTED_FORWARD_CONTRACT_SHA256
        ).all()
        or not scans["provider"].eq("dukascopy-public").all()
        or not scans["symbol"].eq("DUKASCOPY:XAUUSD").all()
        or not scans["paper_research_only"].astype(str).str.lower().isin(
            {"1", "true", "yes"}
        ).all()
        or not scans["decision_effect"].eq("NONE_OBSERVATION_ONLY").all()
    ):
        issues.append("runtime scan status or contract provenance is invalid")
    if len(events):
        event_source_times = pd.to_datetime(
            events["event_source_time"], utc=True, errors="coerce"
        )
        if (
            not events["observation_version"].eq(
                forward["observation_version"]
            ).all()
            or not events["observation_contract_sha256"].eq(
                EXPECTED_FORWARD_CONTRACT_SHA256
            ).all()
            or not events["parent_event_contract_version"].eq(
                parent["contract_version"]
            ).all()
            or not events["parent_event_contract_sha256"].eq(
                EXPECTED_PARENT_CONTRACT_SHA256
            ).all()
            or not events["geometry_schema_sha256"].eq(
                EXPECTED_GEOMETRY_SCHEMA_SHA256
            ).all()
            or not events["paper_research_only"].astype(str).str.lower().isin(
                {"1", "true", "yes"}
            ).all()
            or not events["direction"].isin(["BUY", "SELL"]).all()
            or not events["pair"].eq("DUKASCOPY:XAUUSD").all()
            or not events["event_type"].isin(
                contract["authorization_gates"]["required_event_types"]
            ).all()
            or event_source_times.isna().any()
            or (event_source_times > events["_decision"]).any()
        ):
            issues.append("runtime event contract provenance or identity is invalid")

    self_metrics = _empty_comparison()
    historical_metrics = _empty_comparison()
    self_replay_decisions = 0
    archive_failures = 0
    runtime_rows_by_decision: dict[pd.Timestamp, dict[str, dict]] = {}
    valid_archived_rows: dict[pd.Timestamp, dict[str, dict]] = {}
    for decision, frame in events.groupby("_decision", sort=False):
        runtime_rows_by_decision[pd.Timestamp(decision)] = _event_map(frame)
    seen_event_ids = set(
        all_events.loc[
            all_events["_decision"] < collection_start, "event_id"
        ].astype(str)
    )
    for _, scan in scans.sort_values("_decision").iterrows():
        decision = pd.Timestamp(scan["_decision"])
        expected_new_rows = runtime_rows_by_decision.get(decision, {})
        try:
            scan_ids = _parse_scan_event_ids(scan["event_ids"])
            expected_new_ids = set(scan_ids) - seen_event_ids
            seen_event_ids.update(expected_new_rows)
            if (
                set(expected_new_rows) != expected_new_ids
                or int(scan["detected_event_count"]) != len(scan_ids)
                or int(scan["new_event_count"]) != len(expected_new_rows)
            ):
                raise ValueError(
                    "scan new-event membership does not match the event ledger"
                )
            snapshot_sha = str(scan["snapshot_sha256"]).lower()
            snapshot_path = archive_dir / f"{snapshot_sha}.json"
            payload = json.loads(snapshot_path.read_text())
            if (
                snapshot_sha != canonical_snapshot_sha256(payload)
                or payload.get("content_sha256") != snapshot_sha
            ):
                raise ValueError("archived snapshot content hash mismatch")
            frames = snapshot_frames(payload, forward)
            if pd.Timestamp(frames["1H"].index[-1]) != decision:
                raise ValueError("archived snapshot decision-time mismatch")
            recomputed = _event_rows_at_decision(
                frames, decision, forward, parent,
            )
            if scan_ids != sorted(recomputed):
                raise ValueError(
                    "scan membership does not match its archived snapshot replay"
                )
            recomputed_new_rows = {
                event_id: recomputed[event_id]
                for event_id in expected_new_rows
                if event_id in recomputed
            }
            metrics = _compare_event_maps(
                expected_new_rows,
                recomputed_new_rows,
                float(comparison["absolute_tolerance"]),
                float(comparison["relative_tolerance"]),
                samples,
                f"runtime-self-replay:{decision.isoformat()}",
            )
            _merge_metrics(self_metrics, metrics)
            self_replay_decisions += 1
            valid_archived_rows[decision] = recomputed
        except (
            OSError,
            RuntimeError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            archive_failures += 1
            if len(samples) < 12:
                samples.append({
                    "stage": "runtime-self-replay",
                    "decision_time": decision.isoformat(),
                    "error": str(exc),
                })
    if archive_failures:
        issues.append(f"runtime archive/self-replay failures: {archive_failures}")
    if any(
        self_metrics[name]
        for name in (
            "membership_mismatches",
            "identity_mismatches",
            "value_mismatches",
            "missingness_mismatches",
        )
    ):
        issues.append("runtime archived snapshots do not reproduce their journals")

    replay_state = "AVAILABLE"
    replay_provenance = {}
    replay_references = None
    try:
        replay_references, replay_provenance = (
            _load_delayed_native_references(contract, forward, now)
        )
    except FileNotFoundError as exc:
        replay_state = "AWAITING_SOURCE"
        replay_provenance = {"message": str(exc)}
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        replay_state = "FAILED"
        replay_provenance = {"message": str(exc)}
        issues.append(f"independent replay source invalid: {exc}")

    compared_decisions = 0
    compared_events = 0
    covered_directions = set()
    covered_event_types = set()
    latest_compared = None
    if replay_references is not None:
        for decision, runtime_rows in sorted(valid_archived_rows.items()):
            reference = next(
                (
                    item for item in replay_references
                    if decision <= item["latest_decision"]
                ),
                None,
            )
            if reference is None:
                continue
            try:
                replay_rows = _event_rows_at_decision(
                    reference["frames"], decision, forward, parent,
                )
                metrics = _compare_event_maps(
                    runtime_rows,
                    replay_rows,
                    float(comparison["absolute_tolerance"]),
                    float(comparison["relative_tolerance"]),
                    samples,
                    f"historical-replay:{decision.isoformat()}",
                )
                _merge_metrics(historical_metrics, metrics)
                compared_decisions += 1
                compared_events += len(runtime_rows)
                latest_compared = decision
                covered_directions.update(
                    row["direction"] for row in runtime_rows.values()
                )
                covered_event_types.update(
                    row["event_type"] for row in runtime_rows.values()
                )
            except (
                OSError,
                RuntimeError,
                ValueError,
                KeyError,
                TypeError,
            ) as exc:
                historical_metrics["membership_mismatches"] += 1
                if len(samples) < 12:
                    samples.append({
                        "stage": "historical-replay",
                        "decision_time": decision.isoformat(),
                        "error": str(exc),
                    })
    if any(
        historical_metrics[name]
        for name in (
            "membership_mismatches",
            "identity_mismatches",
            "value_mismatches",
            "missingness_mismatches",
        )
    ):
        issues.append("independent historical replay differs from runtime observations")

    required_directions = set(gates["required_directions"])
    required_event_types = set(gates["required_event_types"])
    latest_runtime = (
        pd.Timestamp(scans["_decision"].max()) if len(scans) else None
    )
    replay_lag_hours = None
    if latest_runtime is not None and latest_compared is not None:
        replay_lag_hours = max(
            0.0,
            (latest_runtime - latest_compared).total_seconds() / 3600,
        )
    gate_results = {
        "minimum_decisions": (
            compared_decisions >= int(gates["minimum_compared_decision_times"])
        ),
        "minimum_events": compared_events >= int(gates["minimum_compared_events"]),
        "both_directions": required_directions.issubset(covered_directions),
        "all_event_types": required_event_types.issubset(covered_event_types),
        "runtime_self_replay": archive_failures == 0 and not any(
            self_metrics[name]
            for name in (
                "membership_mismatches",
                "identity_mismatches",
                "value_mismatches",
                "missingness_mismatches",
            )
        ),
        "historical_concordance": not any(
            historical_metrics[name]
            for name in (
                "membership_mismatches",
                "identity_mismatches",
                "value_mismatches",
                "missingness_mismatches",
            )
        ),
        "replay_freshness": (
            replay_lag_hours is not None
            and replay_lag_hours
            <= float(gates["maximum_latest_runtime_to_replay_lag_hours"])
        ),
    }
    if issues:
        status, status_class = "FAIL", "bad"
    elif scans.empty:
        status, status_class = "AWAITING RUNTIME ARCHIVES", "warn"
    elif replay_state == "AWAITING_SOURCE":
        status, status_class = "AWAITING INDEPENDENT REPLAY", "warn"
    elif compared_decisions == 0:
        status, status_class = "AWAITING REPLAY COVERAGE", "warn"
    elif not gate_results["replay_freshness"]:
        status, status_class = "STALE REPLAY", "warn"
    elif all(gate_results.values()):
        status, status_class = "PASS", "good"
    else:
        status, status_class = "COLLECTING", "warn"
    shadow_registration_eligible = status == "PASS"
    return {
        "schema_version": 1,
        "monitor_version": contract["monitor_version"],
        "contract_sha256": contract_sha,
        "generated_at": now.isoformat(),
        "collection_starts_at_utc": collection_start.isoformat(),
        "status": status,
        "status_class": status_class,
        "paper_research_only": True,
        "performance_columns_read": [],
        "runtime_scans": len(scans),
        "runtime_events": len(events),
        "archived_self_replay_decisions": self_replay_decisions,
        "archive_or_self_replay_failures": archive_failures,
        "replay_source_status": replay_state,
        "replay_provenance": replay_provenance,
        "compared_decision_times": compared_decisions,
        "compared_events": compared_events,
        "latest_runtime_decision": (
            latest_runtime.isoformat() if latest_runtime is not None else None
        ),
        "latest_compared_decision": (
            latest_compared.isoformat() if latest_compared is not None else None
        ),
        "latest_runtime_to_replay_lag_hours": replay_lag_hours,
        "covered_directions": sorted(covered_directions),
        "covered_event_types": sorted(covered_event_types),
        "runtime_self_replay": self_metrics,
        "historical_replay": historical_metrics,
        "gate_results": gate_results,
        "issues": issues,
        "mismatch_samples": samples,
        "technical_concordance_passed": shadow_registration_eligible,
        "shadow_registration_eligible": shadow_registration_eligible,
        "feature_use_authorized": False,
        "authorization_scope": (
            "REGISTER_SEPARATE_PROSPECTIVE_SHADOW_EXPERIMENT_ONLY"
            if shadow_registration_eligible
            else "NONE"
        ),
        "decision_effect": "NONE_OBSERVATION_ONLY",
    }


def event_feature_shadow_registration_eligible(
    status_path: Path = settings.EVENT_FEATURE_CONCORDANCE_STATUS_PATH,
    contract_path: Path = settings.EVENT_FEATURE_CONCORDANCE_CONFIG,
    observed_at: datetime | None = None,
) -> tuple[bool, str]:
    """Validate eligibility to register, but not activate, a shadow experiment."""
    contract, digest, _, _ = load_event_feature_concordance_contract(contract_path)
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    try:
        report = json.loads(Path(status_path).read_text())
        generated = _parse_utc(report["generated_at"])
        gates = contract["authorization_gates"]
        maximum_age = float(gates["maximum_authorization_artifact_age_hours"])
        age_hours = (now.astimezone(timezone.utc) - generated).total_seconds() / 3600
        if age_hours < 0 or age_hours > maximum_age:
            return False, "concordance artifact is stale"
        metric_names = (
            "membership_mismatches",
            "identity_mismatches",
            "value_mismatches",
            "missingness_mismatches",
        )
        runtime_metrics = report.get("runtime_self_replay")
        historical_metrics = report.get("historical_replay")
        gate_results = report.get("gate_results")
        required_gate_names = {
            "minimum_decisions",
            "minimum_events",
            "both_directions",
            "all_event_types",
            "runtime_self_replay",
            "historical_concordance",
            "replay_freshness",
        }
        directions = report.get("covered_directions")
        event_types = report.get("covered_event_types")
        replay_lag = report.get("latest_runtime_to_replay_lag_hours")
        runtime_scans = int(report.get("runtime_scans", -1))
        self_replays = int(report.get("archived_self_replay_decisions", -1))
        compared_decisions = int(report.get("compared_decision_times", -1))
        compared_events = int(report.get("compared_events", -1))
        if (
            report.get("monitor_version") != contract["monitor_version"]
            or report.get("contract_sha256") != digest
            or report.get("status") != "PASS"
            or report.get("status_class") != "good"
            or report.get("paper_research_only") is not True
            or report.get("technical_concordance_passed") is not True
            or report.get("shadow_registration_eligible") is not True
            or report.get("feature_use_authorized") is not False
            or report.get("authorization_scope")
            != "REGISTER_SEPARATE_PROSPECTIVE_SHADOW_EXPERIMENT_ONLY"
            or report.get("performance_columns_read") != []
            or report.get("decision_effect") != "NONE_OBSERVATION_ONLY"
            or report.get("issues") != []
            or report.get("replay_source_status") != "AVAILABLE"
            or int(report.get("archive_or_self_replay_failures", -1)) != 0
            or runtime_scans != self_replays
            or compared_decisions > self_replays
            or compared_decisions
            < int(gates["minimum_compared_decision_times"])
            or compared_events < int(gates["minimum_compared_events"])
            or not isinstance(directions, list)
            or not set(gates["required_directions"]).issubset(directions)
            or not isinstance(event_types, list)
            or not set(gates["required_event_types"]).issubset(event_types)
            or not isinstance(replay_lag, (int, float))
            or replay_lag < 0
            or replay_lag
            > float(gates["maximum_latest_runtime_to_replay_lag_hours"])
            or not isinstance(runtime_metrics, dict)
            or any(int(runtime_metrics.get(name, -1)) != 0 for name in metric_names)
            or not isinstance(historical_metrics, dict)
            or any(
                int(historical_metrics.get(name, -1)) != 0
                for name in metric_names
            )
            or not isinstance(gate_results, dict)
            or not all(
                gate_results.get(name) is True
                for name in required_gate_names
            )
        ):
            return False, "concordance artifact has not passed its frozen gates"
        return True, "technical concordance passed for shadow registration only"
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        return False, f"concordance artifact unavailable: {exc}"


def event_feature_use_authorized(*_args, **_kwargs) -> tuple[bool, str]:
    """Event features need a later frozen shadow contract even after parity."""
    return (
        False,
        "event feature use is not authorized; concordance can only permit "
        "registration of a separate prospective shadow experiment",
    )
