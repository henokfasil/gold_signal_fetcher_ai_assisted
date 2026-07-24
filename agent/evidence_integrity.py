"""File-only reconciliation and input-drift monitoring for paper evidence.

The monitor intentionally never reads outcome return, P&L, win-rate or profit
factor values.  It is operational observability and has no path into candidate
scoring, Claude, Telegram, paper positions or model selection.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from agent.ml_feature_engineer_gold import GoldFeatureEngineer
from config import settings
from research.build_gold_context_dataset import CONTEXT_FEATURES, CONTEXT_NAMES


EXPECTED_CONTRACT_SHA256 = "a11aaa5b16e13c0f2474b769be457d9a567ab1e3bb2f4bf28065304fe57bd834"
EXPECTED_PARENT_CONTRACT_SHA256 = (
    "7aa62452c2cfd8e0c454163d35b82eb0e45612daa04ad2b88cd27d2c93550934"
)
EXPECTED_CONTEXT_ERRATA_SHA256 = (
    "790fd4b40feabc9b8d1b468412d27d3d92993417821bd22ab383b3dda2cf1bab"
)
TECHNICAL_SCHEMA_SHA256 = "8e567c3aa764cc894bf1892e6ceae8011aa4933b69a23f4e80bfaa996063e965"
CONTEXT_SCHEMA_SHA256 = "4100208e9e086f5399dedf3f23a7165ed1444bd8994228b5492adc1525c320c6"
CONTEXT_LEDGER_SCHEMA_SHA256 = (
    "e3467e53050a69f33a5ecee12947ceaeb71a5c4845af9ef1f44abba2c141a47a"
)

CANONICAL_COLUMNS = ["candidate_id", "timestamp", "direction", "paper_trading"]
FEATURE_COLUMNS = [
    "candidate_id", "timestamp", "direction", *GoldFeatureEngineer.FEATURE_COLS,
]
OUTCOME_COLUMNS = ["candidate_id", "candidate_time", "direction", "status"]
VARIANT_COLUMNS = [
    "candidate_id", "timestamp", "experiment_version", "contract_sha256",
    "direction", "baseline_v1", "paper_trading",
]
CONTEXT_RAW_COLUMNS = [
    column
    for name in (*CONTEXT_NAMES, "xau")
    for column in (f"ctx_{name}_analysis_close", f"ctx_{name}_available_at")
]
CONTEXT_COLUMNS = [
    "candidate_id", "timestamp", "experiment_version", "contract_sha256",
    "feature_schema_sha256", "provider", "context_snapshot_sha256",
    "context_snapshot_captured_at", "context_available", "context_reason",
    "direction",
    "baseline_context_capture_v1", "buy_context_hypothesis_v1", "paper_trading",
    "assignment_note", *CONTEXT_FEATURES, *CONTEXT_RAW_COLUMNS,
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _schema_sha256(columns: list[str]) -> str:
    raw = json.dumps(columns, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _parse_utc(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_integrity_contract(path: Path = settings.EVIDENCE_INTEGRITY_CONFIG) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    contract = json.loads(raw)
    isolation = contract.get("isolation", {})
    reconciliation = contract.get("reconciliation", {})
    drift = contract.get("drift_monitor", {})
    if digest != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("evidence-integrity contract hash mismatch; register a new version")
    if (_schema_sha256(GoldFeatureEngineer.FEATURE_COLS) != TECHNICAL_SCHEMA_SHA256 or
            _schema_sha256(CONTEXT_FEATURES) != CONTEXT_SCHEMA_SHA256):
        raise RuntimeError("runtime feature schema changed")
    supersedes = contract.get("supersedes", {})
    errata = contract.get("registered_errata", {})
    if (contract.get("schema_version") != 2 or
            contract.get("monitor_version") != "evidence-integrity-20260724-v2" or
            contract.get("paper_research_only") is not True or
            supersedes.get("contract_sha256") != EXPECTED_PARENT_CONTRACT_SHA256 or
            errata.get("contract_sha256") != EXPECTED_CONTEXT_ERRATA_SHA256 or
            errata.get("exact_row_hash_match_required") is not True or
            errata.get("exclude_only_from_context_drift_windows") is not True or
            errata.get("registered_errata_alone_is_warning_not_healthy") is not True or
            reconciliation.get("technical_feature_schema_sha256") != TECHNICAL_SCHEMA_SHA256 or
            reconciliation.get("context_feature_schema_sha256") != CONTEXT_SCHEMA_SHA256 or
            int(drift.get("minimum_total_rows", -1)) != 200 or
            int(drift.get("quantile_bins_fitted_on_reference_only", -1)) != 10 or
            isolation.get("may_read_outcome_performance_columns") is not False or
            isolation.get("may_evaluate_interim_profitability") is not False or
            isolation.get("may_score_or_approve_candidate") is not False or
            isolation.get("may_change_ml_or_claude_decision") is not False or
            isolation.get("may_send_telegram") is not False or
            isolation.get("may_place_broker_order") is not False or
            isolation.get("may_train_select_or_promote_model") is not False):
        raise RuntimeError("evidence-integrity contract violates frozen schema or isolation")
    return contract, digest


def _project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else settings.PROJECT_ROOT / path


def load_context_errata(contract: dict) -> tuple[dict, str]:
    """Load exact, outcome-blind context exceptions without mutating the ledger."""
    spec = contract["registered_errata"]
    path = _project_path(spec["path"])
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    errata = json.loads(raw)
    isolation = errata.get("isolation", {})
    disposition = errata.get("disposition", {})
    rows = errata.get("affected_rows", [])
    if (
        digest != EXPECTED_CONTEXT_ERRATA_SHA256
        or digest != spec["contract_sha256"]
        or errata.get("schema_version") != 1
        or errata.get("erratum_version")
        != "context-observation-errata-20260724-v1"
        or errata.get("paper_research_only") is not True
        or errata.get("discovery", {}).get("outcomes_read") is not False
        or errata.get("discovery", {}).get("performance_columns_read") != []
        or errata.get("source_ledger", {}).get("header_sha256")
        != CONTEXT_LEDGER_SCHEMA_SHA256
        or errata.get("source_ledger", {}).get("mutation_permitted") is not False
        or len(rows) != 2
        or len({row.get("candidate_id") for row in rows}) != len(rows)
        or any(
            set(row.get("invalid_fields", [])) - set(CONTEXT_FEATURES)
            for row in rows
        )
        or disposition.get("original_rows_retained") is not True
        or disposition.get("replacement_values_imputed") is not False
        or disposition.get("treat_as_valid_context") is not False
        or disposition.get("exclude_from_context_drift_windows") is not True
        or disposition.get("decision_effect") != "NONE_OBSERVATION_ONLY"
        or isolation.get("may_read_outcomes") is not False
        or isolation.get("may_read_performance_columns") is not False
        or isolation.get("may_change_candidate_or_ai_decision") is not False
        or isolation.get("may_send_telegram") is not False
        or isolation.get("may_place_broker_order") is not False
        or isolation.get("may_train_select_or_promote_model") is not False
    ):
        raise RuntimeError("context errata violates its frozen provenance or isolation")
    return errata, digest


def _read_selected(path: Path, desired: list[str], forbidden: set[str]) -> dict:
    """Read only explicitly selected fields; performance values stay unread."""
    path = Path(path)
    result = {
        "frame": pd.DataFrame(columns=desired), "exists": False,
        "header": [], "missing_columns": list(desired), "error": "",
    }
    if set(desired) & forbidden:
        raise RuntimeError("monitor requested a forbidden performance column")
    if not path.exists() or path.stat().st_size == 0:
        return result
    try:
        header = list(pd.read_csv(path, nrows=0).columns)
        selected = [column for column in desired if column in header]
        frame = pd.read_csv(path, usecols=selected, dtype=str).fillna("") if selected else pd.DataFrame()
        for column in desired:
            if column not in frame:
                frame[column] = ""
        result.update({
            "frame": frame[desired], "exists": True, "header": header,
            "missing_columns": [column for column in desired if column not in header],
        })
    except (OSError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        result.update({"exists": True, "error": f"{type(exc).__name__}: {exc}"})
    return result


def _prepare_identity(frame: pd.DataFrame, timestamp_column: str) -> pd.DataFrame:
    result = frame.copy()
    result["candidate_id"] = result["candidate_id"].astype(str).str.strip()
    result["_timestamp"] = pd.to_datetime(result[timestamp_column], utc=True, errors="coerce")
    if "direction" in result:
        result["direction"] = result["direction"].astype(str).str.upper().str.strip()
    return result


def _true_mask(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def _scope(frame: pd.DataFrame, start: datetime, cutoff: datetime) -> pd.DataFrame:
    return frame[frame["_timestamp"].between(start, cutoff, inclusive="both")].copy()


def _identity_mismatches(expected: pd.DataFrame, actual: pd.DataFrame,
                         tolerance_seconds: float) -> int:
    if expected.empty or actual.empty:
        return 0
    left = expected.drop_duplicates("candidate_id", keep="first")[
        ["candidate_id", "_timestamp", "direction"]
    ]
    right = actual.drop_duplicates("candidate_id", keep="first")[
        ["candidate_id", "_timestamp", "direction"]
    ]
    joined = left.merge(right, on="candidate_id", suffixes=("_expected", "_actual"))
    if joined.empty:
        return 0
    seconds = (joined["_timestamp_actual"] - joined["_timestamp_expected"]).dt.total_seconds().abs()
    mismatch = (
        joined["_timestamp_expected"].isna() | joined["_timestamp_actual"].isna() |
        seconds.gt(tolerance_seconds) |
        joined["direction_expected"].ne(joined["direction_actual"])
    )
    return int(mismatch.sum())


def _reconcile_ledger(name: str, loaded: dict, expected: pd.DataFrame,
                      timestamp_column: str, start: datetime, cutoff: datetime,
                      tolerance_seconds: float) -> tuple[dict, pd.DataFrame]:
    frame = _prepare_identity(loaded["frame"], timestamp_column)
    expected_ids = set(expected["candidate_id"])
    in_time = frame["_timestamp"].between(start, cutoff, inclusive="both")
    actual = frame[in_time | frame["candidate_id"].isin(expected_ids)].copy()
    actual_ids = set(actual["candidate_id"])
    missing = expected_ids - actual_ids
    orphan = set(actual.loc[in_time, "candidate_id"]) - expected_ids
    duplicates = int(actual["candidate_id"].duplicated().sum())
    mismatches = _identity_mismatches(expected, actual, tolerance_seconds)
    schema_error = bool(loaded["missing_columns"] or loaded["error"])
    unhealthy = bool(missing or orphan or duplicates or mismatches or schema_error)
    if expected.empty and not loaded["exists"]:
        status = "READY"
        schema = "NOT CREATED"
    else:
        status = "FAIL" if unhealthy else "PASS"
        schema = "FAIL" if schema_error else "PASS"
    report = {
        "name": name, "status": status, "expected": len(expected), "rows": len(actual),
        "missing": len(missing), "orphan": len(orphan), "duplicates": duplicates,
        "identity_mismatches": mismatches,
        "schema": schema,
    }
    return report, actual


def _numeric_invalid_rows(frame: pd.DataFrame, columns: list[str]) -> int:
    if frame.empty:
        return 0
    numeric = frame[columns].apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
    return int((~valid).sum())


def _canonical_context_row_sha256(row: pd.Series) -> str:
    payload = {
        column: str(row.get(column, ""))
        for column in CONTEXT_COLUMNS
    }
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _registered_context_errata(
    context_rows: pd.DataFrame,
    context_expected: pd.DataFrame,
    context_invalid: pd.Series,
    errata: dict,
) -> tuple[pd.Series, list[dict], list[str]]:
    """Match only frozen row hashes and exact non-finite field sets."""
    recognized = pd.Series(False, index=context_rows.index)
    applied = []
    issues = []
    expected_ids = set(context_expected["candidate_id"].astype(str))
    numeric = context_rows[CONTEXT_FEATURES].apply(pd.to_numeric, errors="coerce")
    for entry in errata["affected_rows"]:
        candidate_id = str(entry["candidate_id"])
        if candidate_id not in expected_ids:
            continue
        matches = context_rows[
            context_rows["candidate_id"].astype(str).eq(candidate_id)
        ]
        if len(matches) != 1:
            issues.append(
                f"registered context erratum row count changed: {candidate_id}"
            )
            continue
        index = matches.index[0]
        row = matches.iloc[0]
        actual_invalid_fields = {
            column
            for column in CONTEXT_FEATURES
            if not np.isfinite(float(numeric.loc[index, column]))
        }
        if (
            not bool(context_invalid.loc[index])
            or str(row["timestamp"]) != entry["timestamp"]
            or str(row["direction"]).upper() != entry["direction"]
            or _canonical_context_row_sha256(row)
            != entry["canonical_row_sha256"]
            or actual_invalid_fields != set(entry["invalid_fields"])
        ):
            issues.append(
                f"registered context erratum row content changed: {candidate_id}"
            )
            continue
        recognized.loc[index] = True
        applied.append({
            "candidate_id": candidate_id,
            "timestamp": entry["timestamp"],
            "direction": entry["direction"],
            "invalid_fields": list(entry["invalid_fields"]),
            "canonical_row_sha256": entry["canonical_row_sha256"],
            "disposition": "QUARANTINED_NOT_VALID_CONTEXT",
        })
    return recognized, applied, issues


def _psi(reference: pd.Series, current: pd.Series, bins: int,
         pseudocount: float, minimum_valid: int) -> dict:
    ref = pd.to_numeric(reference, errors="coerce").replace([np.inf, -np.inf], np.nan)
    cur = pd.to_numeric(current, errors="coerce").replace([np.inf, -np.inf], np.nan)
    ref_missing = float(ref.isna().mean())
    cur_missing = float(cur.isna().mean())
    ref_valid, cur_valid = ref.dropna().to_numpy(), cur.dropna().to_numpy()
    if len(ref_valid) < minimum_valid or len(cur_valid) < minimum_valid:
        return {
            "psi": None, "reference_missing": ref_missing,
            "current_missing": cur_missing, "missingness_change": cur_missing - ref_missing,
        }
    quantiles = np.unique(np.quantile(ref_valid, np.linspace(0, 1, bins + 1)))
    if len(quantiles) == 1:
        center = float(ref_valid[0])
        epsilon = max(abs(center) * 1e-9, 1e-12)
        edges = np.array([-np.inf, center - epsilon, center + epsilon, np.inf])
    else:
        # Midpoints keep repeated/discrete reference quantiles useful (for
        # example a binary feature still gets two bins) while all boundaries
        # remain fitted exclusively on the frozen reference window.
        internal = (quantiles[:-1] + quantiles[1:]) / 2.0
        edges = np.concatenate(([-np.inf], internal, [np.inf]))
    ref_counts = np.histogram(ref_valid, bins=edges)[0].astype(float)
    cur_counts = np.histogram(cur_valid, bins=edges)[0].astype(float)
    ref_prop = (ref_counts + pseudocount) / (ref_counts.sum() + pseudocount * len(ref_counts))
    cur_prop = (cur_counts + pseudocount) / (cur_counts.sum() + pseudocount * len(cur_counts))
    value = float(np.sum((cur_prop - ref_prop) * np.log(cur_prop / ref_prop)))
    return {
        "psi": value, "reference_missing": ref_missing,
        "current_missing": cur_missing, "missingness_change": cur_missing - ref_missing,
    }


def drift_report(frame: pd.DataFrame, feature_columns: list[str], contract: dict) -> dict:
    """Compare immutable first-100 and latest-100 distributions, never outcomes."""
    spec = contract["drift_monitor"]
    minimum_rows = int(spec["minimum_total_rows"])
    window = minimum_rows // 2
    result = {
        "status": "AWAITING 200 ROWS", "rows": len(frame),
        "reference_rows": min(len(frame), window), "current_rows": 0,
        "max_psi": None, "warning_features": 0, "alert_features": 0,
        "top_features": [],
    }
    if len(frame) < minimum_rows:
        return result
    ordered = frame.sort_values("_timestamp")
    reference, current = ordered.iloc[:window], ordered.iloc[-window:]
    details = []
    for column in feature_columns:
        metrics = _psi(
            reference[column], current[column],
            int(spec["quantile_bins_fitted_on_reference_only"]),
            float(spec["bin_pseudocount"]),
            int(spec["minimum_non_missing_per_feature_per_window"]),
        )
        psi_value = metrics["psi"]
        missing_change = metrics["missingness_change"]
        severity = "STABLE"
        if ((psi_value is not None and psi_value >= float(spec["alert_psi"])) or
                missing_change >= float(spec["missingness_alert_absolute_increase"])):
            severity = "ALERT"
        elif ((psi_value is not None and psi_value >= float(spec["warning_psi"])) or
              missing_change >= float(spec["missingness_warning_absolute_increase"])):
            severity = "WARNING"
        details.append({"feature": column, "severity": severity, **metrics})
    rank = {"ALERT": 2, "WARNING": 1, "STABLE": 0}
    details.sort(key=lambda item: (
        rank[item["severity"]], item["psi"] if item["psi"] is not None else -1,
        item["missingness_change"],
    ), reverse=True)
    alert_count = sum(item["severity"] == "ALERT" for item in details)
    warning_count = sum(item["severity"] == "WARNING" for item in details)
    finite_psi = [item["psi"] for item in details if item["psi"] is not None]
    result.update({
        "status": "ALERT" if alert_count else "WARNING" if warning_count else "STABLE",
        "reference_rows": window, "current_rows": window,
        "max_psi": max(finite_psi) if finite_psi else None,
        "warning_features": warning_count, "alert_features": alert_count,
        "top_features": details[:5],
    })
    return result


def build_evidence_integrity_report(
    ledger_path: Path = settings.PAPER_TRADES_CSV,
    features_path: Path = settings.FORWARD_FEATURES_CSV,
    outcomes_path: Path = settings.FORWARD_OUTCOMES_CSV,
    variants_path: Path = settings.FORWARD_VARIANT_ASSIGNMENTS_CSV,
    context_path: Path = settings.FORWARD_CONTEXT_CSV,
    config_path: Path = settings.EVIDENCE_INTEGRITY_CONFIG,
    variant_contract_path: Path = settings.RESEARCH_VARIANT_CONFIG,
    context_contract_path: Path = settings.FORWARD_CONTEXT_CONFIG,
    observed_at: datetime | None = None,
) -> dict:
    contract, contract_sha = load_integrity_contract(config_path)
    errata, errata_sha = load_context_errata(contract)
    now = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reconciliation = contract["reconciliation"]
    pilot_spec = reconciliation["pilot_scope"]
    context_spec = reconciliation["context_scope"]
    forbidden = set(reconciliation["performance_columns_forbidden"])
    issues = []
    warnings = []

    try:
        variant_hash = _sha256(variant_contract_path)
        context_hash = _sha256(context_contract_path)
    except OSError as exc:
        variant_hash = context_hash = "UNAVAILABLE"
        issues.append(f"research contract unavailable: {exc}")
    if variant_hash != pilot_spec["variant_contract_sha256"]:
        issues.append("variant contract hash drift")
    if context_hash != context_spec["context_contract_sha256"]:
        issues.append("context contract hash drift")

    pilot_start = _parse_utc(pilot_spec["start_at_utc"])
    pilot_cutoff = _parse_utc(pilot_spec["assignment_cutoff_at_utc"])
    context_start = _parse_utc(context_spec["start_at_utc"])
    context_cutoff = _parse_utc(context_spec["assignment_cutoff_at_utc"])
    tolerance = float(reconciliation["candidate_timestamp_match_tolerance_seconds"])

    canonical_loaded = _read_selected(ledger_path, CANONICAL_COLUMNS, forbidden)
    canonical = _prepare_identity(canonical_loaded["frame"], "timestamp")
    if canonical_loaded["exists"] and (canonical_loaded["missing_columns"] or canonical_loaded["error"]):
        issues.append("canonical candidate ledger schema/read failure")
    if canonical["candidate_id"].duplicated().any():
        issues.append("canonical candidate IDs are duplicated")
    if canonical["candidate_id"].eq("").any() or canonical["_timestamp"].isna().any():
        issues.append("canonical candidate identity or timestamp is invalid")
    if (~canonical["direction"].isin(["BUY", "SELL"])).any():
        issues.append("canonical candidate direction is invalid")
    if len(canonical) and not _true_mask(canonical["paper_trading"]).all():
        issues.append("canonical ledger contains a non-paper candidate")

    pilot_expected = _scope(canonical, pilot_start, pilot_cutoff)
    context_expected = _scope(canonical, context_start, context_cutoff)
    loaded = {
        "features": _read_selected(features_path, FEATURE_COLUMNS, forbidden),
        "outcomes": _read_selected(outcomes_path, OUTCOME_COLUMNS, forbidden),
        "variants": _read_selected(variants_path, VARIANT_COLUMNS, forbidden),
        "context": _read_selected(context_path, CONTEXT_COLUMNS, forbidden),
    }
    reports = []
    feature_report, feature_rows = _reconcile_ledger(
        "Technical features", loaded["features"], pilot_expected, "timestamp",
        pilot_start, pilot_cutoff, tolerance,
    )
    outcome_report, outcome_rows = _reconcile_ledger(
        "Shadow outcomes", loaded["outcomes"], pilot_expected, "candidate_time",
        pilot_start, pilot_cutoff, tolerance,
    )
    variant_report, variant_rows = _reconcile_ledger(
        "Variant assignments", loaded["variants"], pilot_expected, "timestamp",
        pilot_start, pilot_cutoff, tolerance,
    )
    context_report, context_rows = _reconcile_ledger(
        "Context observations", loaded["context"], context_expected, "timestamp",
        context_start, context_cutoff, tolerance,
    )
    reports.extend([feature_report, outcome_report, variant_report, context_report])

    technical_header_features = [
        column for column in loaded["features"]["header"]
        if column in GoldFeatureEngineer.FEATURE_COLS
    ]
    if loaded["features"]["exists"] and technical_header_features != GoldFeatureEngineer.FEATURE_COLS:
        feature_report["schema"] = "FAIL"
        issues.append("technical feature schema drift")
    invalid_technical = _numeric_invalid_rows(feature_rows, GoldFeatureEngineer.FEATURE_COLS)
    feature_report["invalid_rows"] = invalid_technical
    if invalid_technical:
        issues.append(f"technical feature rows invalid: {invalid_technical}")

    allowed_states = set(reconciliation["allowed_outcome_states"])
    invalid_outcomes = int((~outcome_rows["status"].astype(str).str.upper().isin(allowed_states)).sum())
    outcome_report["invalid_rows"] = invalid_outcomes
    if invalid_outcomes:
        issues.append(f"outcome state rows invalid: {invalid_outcomes}")

    variant_invalid = pd.Series(False, index=variant_rows.index)
    if len(variant_rows):
        variant_invalid = (
            variant_rows["experiment_version"].ne("forward-pilot-20260719-v3") |
            variant_rows["contract_sha256"].ne(pilot_spec["variant_contract_sha256"]) |
            ~_true_mask(variant_rows["baseline_v1"]) |
            ~_true_mask(variant_rows["paper_trading"])
        )
    variant_report["invalid_rows"] = int(variant_invalid.sum())
    if variant_invalid.any():
        issues.append(f"variant contract or membership rows invalid: {int(variant_invalid.sum())}")

    context_header_features = [
        column for column in loaded["context"]["header"] if column in CONTEXT_FEATURES
    ]
    if loaded["context"]["exists"] and context_header_features != CONTEXT_FEATURES:
        context_report["schema"] = "FAIL"
        issues.append("context feature schema drift")
    context_invalid = pd.Series(False, index=context_rows.index)
    context_missing = pd.Series(False, index=context_rows.index)
    if len(context_rows):
        capture_available = _true_mask(context_rows["context_available"])
        instrument_missing = pd.DataFrame({
            name: pd.to_numeric(context_rows[f"ctx_{name}_missing"], errors="coerce").ne(0)
            for name in CONTEXT_NAMES
        }).any(axis=1)
        context_missing = ~capture_available | instrument_missing
        complete = capture_available & ~instrument_missing
        numeric = context_rows[CONTEXT_FEATURES].apply(pd.to_numeric, errors="coerce")
        numeric_valid = pd.Series(
            np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1), index=context_rows.index,
        )
        context_invalid = (
            context_rows["experiment_version"].ne("forward-context-buy-20260719-v1") |
            context_rows["contract_sha256"].ne(context_spec["context_contract_sha256"]) |
            context_rows["feature_schema_sha256"].ne(CONTEXT_SCHEMA_SHA256) |
            ~_true_mask(context_rows["baseline_context_capture_v1"]) |
            ~_true_mask(context_rows["paper_trading"]) |
            _true_mask(context_rows["buy_context_hypothesis_v1"]).ne(
                context_rows["direction"].eq("BUY")
            ) |
            (complete & ~numeric_valid)
        )
    recognized_errata, applied_errata, errata_issues = (
        _registered_context_errata(
            context_rows,
            context_expected,
            context_invalid,
            errata,
        )
    )
    issues.extend(errata_issues)
    unregistered_context_invalid = context_invalid & ~recognized_errata
    context_report["missing_capture_rows"] = int(context_missing.sum())
    context_report["invalid_rows"] = int(unregistered_context_invalid.sum())
    context_report["registered_errata_rows"] = int(recognized_errata.sum())
    if context_missing.any():
        issues.append(f"context capture or instrument rows missing: {int(context_missing.sum())}")
    if unregistered_context_invalid.any():
        issues.append(
            "unregistered context contract or feature rows invalid: "
            f"{int(unregistered_context_invalid.sum())}"
        )
    if applied_errata:
        warnings.append(
            f"registered context errata quarantined: {len(applied_errata)}"
        )

    for ledger in reports:
        if (ledger["status"] == "FAIL" or ledger["schema"] == "FAIL" or
                ledger.get("invalid_rows", 0)):
            issues.append(
                f"{ledger['name']} reconciliation failed "
                f"(missing={ledger['missing']}, orphan={ledger['orphan']}, "
                f"duplicates={ledger['duplicates']}, identity={ledger['identity_mismatches']})"
            )

    feature_drift_rows = feature_rows[
        feature_rows["candidate_id"].isin(set(pilot_expected["candidate_id"]))
    ].drop_duplicates("candidate_id", keep="first")
    context_drift_rows = context_rows[
        context_rows["candidate_id"].isin(set(context_expected["candidate_id"]))
        & ~recognized_errata
    ].drop_duplicates("candidate_id", keep="first")
    technical_drift = drift_report(
        feature_drift_rows, GoldFeatureEngineer.FEATURE_COLS, contract,
    )
    context_drift = drift_report(context_drift_rows, CONTEXT_FEATURES, contract)
    drift_alert = any(item["status"] == "ALERT" for item in (technical_drift, context_drift))
    drift_warning = any(item["status"] == "WARNING" for item in (technical_drift, context_drift))
    if drift_alert:
        issues.append("prospective input PSI reached the registered alert threshold")

    if issues:
        status, status_class = "DEGRADED", "bad"
    elif warnings:
        status, status_class = "WARNING · REGISTERED ERRATA", "warn"
    elif drift_warning:
        status, status_class = "WARNING", "warn"
    elif len(pilot_expected) == 0 and len(context_expected) == 0:
        status, status_class = "READY · AWAITING CANDIDATES", "good"
    elif technical_drift["status"].startswith("AWAITING") or context_drift["status"].startswith("AWAITING"):
        status, status_class = "HEALTHY · DRIFT BASELINE COLLECTING", "good"
    else:
        status, status_class = "HEALTHY", "good"

    return {
        "schema_version": contract["schema_version"],
        "monitor_version": contract["monitor_version"],
        "contract_sha256": contract_sha,
        "generated_at": now.isoformat(),
        "status": status,
        "status_class": status_class,
        "paper_research_only": True,
        "performance_columns_read": [],
        "canonical_candidates_total": len(canonical),
        "pilot_candidates": len(pilot_expected),
        "context_scope_candidates": len(context_expected),
        "context_errata": {
            "erratum_version": errata["erratum_version"],
            "contract_sha256": errata_sha,
            "registered_rows": len(errata["affected_rows"]),
            "applied_rows": len(applied_errata),
            "rows": applied_errata,
            "ledger_mutated": False,
            "excluded_from_context_drift_rows": len(applied_errata),
            "future_context_evaluation":
            errata["disposition"]["future_context_evaluation"],
        },
        "ledgers": reports,
        "technical_drift": technical_drift,
        "context_drift": context_drift,
        "issues": list(dict.fromkeys(issues)),
        "warnings": list(dict.fromkeys(warnings)),
        "effect": "None — operational monitoring only",
    }
