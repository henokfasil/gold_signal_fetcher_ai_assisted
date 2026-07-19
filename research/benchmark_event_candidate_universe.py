#!/usr/bin/env python3
"""Evaluate the registered event-first candidate universe without tuning it."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from research.analyze_research_evidence import label_uniqueness
from research.benchmark_execution_state import (
    _paired_weekly_interval,
    _selected_weekly_interval,
)
from research.benchmark_return_targets import (
    SELECTION_QUANTILE,
    _metrics,
    _weekly_block_intervals,
)
from research.build_event_candidate_universe import (
    CONTRACT_PATH,
    EVENT_FEATURES,
    EVENT_TYPES,
    EXPECTED_CONTRACT_SHA256,
    load_contract,
)


BASE_SLIPPAGE_POINTS_PER_SIDE = 0.10
STRESS_SLIPPAGE_POINTS_PER_SIDE = 0.25
REGISTERED_BOOTSTRAP_SAMPLES = 500
REGISTERED_SEED = 42
DIRECTION_EVENT_FEATURES = EVENT_FEATURES[:6]
MODEL_FEATURES = {
    "calibration_mean": [],
    "direction_event_type_ridge": DIRECTION_EVENT_FEATURES,
    "geometry_ridge": EVENT_FEATURES,
    "geometry_xgboost": EVENT_FEATURES,
}
PAIRED_CONTROLS = {
    "geometry_ridge": "direction_event_type_ridge",
    "geometry_xgboost": "direction_event_type_ridge",
}
XGBOOST_PARAMETERS = {
    "max_depth": 3,
    "n_estimators": 250,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 10,
    "reg_lambda": 2,
    "random_state": 42,
    "n_jobs": 4,
}
TARGETS = (
    ("4h", "target_4h_net_return_pct", "target_4h_actual_exit_hours", "PRIMARY"),
    ("1h", "target_1h_net_return_pct", "target_1h_actual_exit_hours", "SECONDARY_DIAGNOSTIC"),
    ("12h", "target_12h_net_return_pct", "target_12h_actual_exit_hours", "SECONDARY_DIAGNOSTIC"),
    ("48h", "target_48h_net_return_pct", "target_48h_actual_exit_hours", "SECONDARY_DIAGNOSTIC"),
    ("barrier", "net_return_pct", "label_duration_hours", "SECONDARY_DIAGNOSTIC"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _model(name: str):
    if name.endswith("ridge"):
        return Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=10.0)),
        ])
    if name == "geometry_xgboost":
        return XGBRegressor(
            **XGBOOST_PARAMETERS,
            objective="reg:squarederror",
            eval_metric="rmse",
        )
    raise ValueError(f"unknown event-universe model {name}")


def _fit_predict(name, train, calibration, test, target, weights):
    if name == "calibration_mean":
        score = float(calibration[target].mean())
        return np.repeat(score, len(test)), score
    columns = MODEL_FEATURES[name]
    model = _model(name)
    if name.endswith("ridge"):
        model.fit(train[columns], train[target], ridge__sample_weight=weights)
    else:
        model.fit(train[columns], train[target], sample_weight=weights)
    calibration_score = model.predict(calibration[columns])
    threshold = float(np.quantile(calibration_score, SELECTION_QUANTILE))
    return np.asarray(model.predict(test[columns]), dtype=float), threshold


def _stressed_target(frame: pd.DataFrame, target: str,
                     slippage: float = STRESS_SLIPPAGE_POINTS_PER_SIDE) -> pd.Series:
    incremental_points = 2 * (slippage - BASE_SLIPPAGE_POINTS_PER_SIDE)
    return frame[target] - incremental_points / frame["executable_entry"] * 100


def _validate_registered_evaluation(contract: dict, bootstrap_samples: int,
                                    seed: int) -> None:
    evaluation = contract.get("evaluation_contract", {})
    model_sets = evaluation.get("model_feature_sets", {})
    expected_secondary = [item[1] for item in TARGETS if item[3] != "PRIMARY"]
    checks = {
        "primary target": evaluation.get("primary_target") == TARGETS[0][1],
        "secondary targets": evaluation.get("secondary_diagnostic_targets") == expected_secondary,
        "folds": evaluation.get("candidate_year_folds") == [2022, 2023, 2024, 2025, 2026],
        "model ladder": list(evaluation.get("models", {})) == list(MODEL_FEATURES),
        "direction/event features": model_sets.get("direction_event_type_ridge") == DIRECTION_EVENT_FEATURES,
        "geometry ridge features": model_sets.get("geometry_ridge") == "ALL_REGISTERED_GEOMETRY_FEATURES",
        "geometry xgboost features": model_sets.get("geometry_xgboost") == "ALL_REGISTERED_GEOMETRY_FEATURES",
        "paired controls": evaluation.get("paired_controls") == PAIRED_CONTROLS,
        "ridge alpha": float(evaluation.get("ridge_alpha", -1)) == 10.0,
        "xgboost parameters": evaluation.get("xgboost_parameters") == XGBOOST_PARAMETERS,
        "selection threshold": evaluation.get("selection_threshold") == "prediction at or above the prior calibration slice 80th percentile",
        "base cost": float(evaluation.get("base_slippage_points_per_side", -1)) == BASE_SLIPPAGE_POINTS_PER_SIDE,
        "stress cost": float(evaluation.get("stress_slippage_points_per_side", -1)) == STRESS_SLIPPAGE_POINTS_PER_SIDE,
        "only primary can pass": evaluation.get("only_primary_target_can_pass_development_gates") is True,
        "secondary cannot select": evaluation.get("secondary_results_cannot_select_a_horizon_model_threshold_or_event_type") is True,
        "bootstrap samples": bootstrap_samples == REGISTERED_BOOTSTRAP_SAMPLES == evaluation.get("bootstrap_samples"),
        "bootstrap seed": seed == REGISTERED_SEED == evaluation.get("bootstrap_seed"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            "event-universe implementation differs from registered evaluation: "
            + ", ".join(failed)
        )


def _validate_lineage(path: Path, contract: dict, contract_sha: str) -> tuple[dict, dict, Path, Path]:
    label_manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    label_manifest = json.loads(label_manifest_path.read_text())
    feature_path = Path(label_manifest["candidate_source"])
    feature_manifest_path = feature_path.with_suffix(feature_path.suffix + ".manifest.json")
    feature_manifest = json.loads(feature_manifest_path.read_text())
    expected_source = contract["source_contract"]
    valid = (
        label_manifest.get("dataset_sha256") == _sha256(path)
        and label_manifest.get("candidate_source_sha256") == _sha256(feature_path)
        and label_manifest.get("price_source_sha256") == expected_source["source_sha256"]
        and float(label_manifest.get("slippage_points_per_side", -1)) == BASE_SLIPPAGE_POINTS_PER_SIDE
        and label_manifest.get("alternative_horizons_hours") == [1, 4, 12, 48]
        and feature_manifest.get("contract_sha256") == contract_sha
        and feature_manifest.get("source_sha256") == expected_source["source_sha256"]
        and feature_manifest.get("source_manifest_sha256") == expected_source["source_manifest_sha256"]
        and feature_manifest.get("dataset_sha256") == _sha256(feature_path)
        and feature_manifest.get("feature_schema_sha256") == contract["geometry_feature_contract"]["schema_sha256"]
        and feature_manifest.get("contains_outcomes") is False
    )
    if not valid:
        raise RuntimeError("event-universe dataset lineage or manifest mismatch")
    return label_manifest, feature_manifest, label_manifest_path, feature_manifest_path


def _data_quality(frame: pd.DataFrame, contract: dict, feature_manifest: dict) -> dict:
    directions = {"BUY", "SELL"}
    event_types = set(EVENT_TYPES)
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    source_times = pd.to_datetime(frame["event_source_time"], utc=True)
    invalid = int((~frame.direction.isin(directions) | ~frame.event_type.isin(event_types)).sum())
    matured = frame[~frame.label_status.isin(["AMBIGUOUS_SAME_BAR", "UNMATURED"])].copy()
    gates = contract["dataset_quality_gates"]
    direction_counts = matured.direction.value_counts().reindex(sorted(directions), fill_value=0)
    event_counts = matured.event_type.value_counts().reindex(EVENT_TYPES, fill_value=0)
    duplicate_ids = int(frame.event_id.duplicated().sum())
    future_events = int((source_times > timestamps).sum())
    nonfinite = int(np.isinf(frame[EVENT_FEATURES].to_numpy(float)).sum())
    checks = {
        "minimum_total_matured_unambiguous_events": len(matured) >= gates["minimum_total_matured_unambiguous_events"],
        "minimum_each_direction": bool((direction_counts >= gates["minimum_matured_unambiguous_events_per_direction"]).all()),
        "minimum_each_event_type": bool((event_counts >= gates["minimum_matured_unambiguous_events_per_event_type"]).all()),
        "no_duplicate_event_ids": duplicate_ids == gates["duplicate_event_ids_allowed"],
        "no_future_source_event_times": future_events == gates["future_source_event_times_allowed"],
        "valid_direction_and_event_type": invalid == gates["invalid_direction_or_event_type_rows_allowed"],
        "no_infinite_registered_features": nonfinite == 0,
        "manifest_row_count_matches": int(feature_manifest["rows"]) == len(frame),
    }
    return {
        "rows": len(frame),
        "matured_unambiguous_rows": len(matured),
        "matured_unambiguous_direction_counts": {key: int(value) for key, value in direction_counts.items()},
        "matured_unambiguous_event_type_counts": {key: int(value) for key, value in event_counts.items()},
        "duplicate_event_ids": duplicate_ids,
        "future_source_event_times": future_events,
        "invalid_direction_or_event_type_rows": invalid,
        "nonfinite_registered_feature_values": nonfinite,
        "gates": checks,
        "all_gates_pass": all(checks.values()),
    }


def _prepare(frame: pd.DataFrame, target: str, duration: str) -> pd.DataFrame:
    required = [target, duration, "direction", "event_type", "executable_entry"]
    work = frame.dropna(subset=required).copy()
    work["target_exit_time"] = work.timestamp + pd.to_timedelta(work[duration], unit="h")
    work = work.sort_values(["timestamp", "event_id"]).reset_index(drop=True)
    work["row_id"] = np.arange(len(work))
    return work


def benchmark(path: Path, bootstrap_samples=500, seed=42,
              contract_path: Path = CONTRACT_PATH) -> dict:
    contract, contract_sha = load_contract(contract_path)
    if contract_sha != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("event-universe benchmark contract hash mismatch")
    _validate_registered_evaluation(contract, bootstrap_samples, seed)
    label_manifest, feature_manifest, label_manifest_path, feature_manifest_path = (
        _validate_lineage(path, contract, contract_sha)
    )
    raw = pd.read_csv(path)
    raw["timestamp"] = pd.to_datetime(raw.timestamp, utc=True)
    quality = _data_quality(raw, contract, feature_manifest)
    common = {
        "contract_version": contract["contract_version"],
        "contract_sha256": contract_sha,
        "dataset_sha256": _sha256(path),
        "dataset_manifest_sha256": _sha256(label_manifest_path),
        "feature_dataset_sha256": feature_manifest["dataset_sha256"],
        "feature_manifest_sha256": _sha256(feature_manifest_path),
        "benchmark_script_sha256": _sha256(Path(__file__)),
        "bootstrap_samples": bootstrap_samples,
        "seed": seed,
        "data_quality": quality,
        "model_artifact_created": False,
        "runtime_changed": False,
        "paper_approval_authorized": False,
    }
    if not quality["all_gates_pass"]:
        return {
            "status": "REJECT_EVENT_UNIVERSE_DATA_QUALITY",
            "scope": "CONTAMINATED_DEVELOPMENT_HISTORY_NO_MODEL_OR_RUNTIME_AUTHORIZATION",
            **common,
            "primary_target": contract["evaluation_contract"]["primary_target"],
            "primary_passing_models": [],
            "targets": {},
        }

    target_reports = {}
    folds = contract["evaluation_contract"]["candidate_year_folds"]
    for target_offset, (key, target, duration, role) in enumerate(TARGETS):
        frame = _prepare(raw, target, duration)
        predictions = {name: [] for name in MODEL_FEATURES}
        fold_reports = {name: [] for name in MODEL_FEATURES}
        for year in folds:
            start = pd.Timestamp(f"{year}-01-01", tz="UTC")
            end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
            prior = frame[(frame.timestamp < start) & (frame.target_exit_time < start)]
            test = frame[(frame.timestamp >= start) & (frame.timestamp < end)].copy()
            if len(prior) < 500 or len(test) < 100:
                continue
            calibration_start = prior.timestamp.iloc[int(len(prior) * 0.8)]
            train = prior[(prior.timestamp < calibration_start) &
                          (prior.target_exit_time < calibration_start)].copy()
            calibration = prior[prior.timestamp >= calibration_start].copy()
            intervals = train[["timestamp", "target_exit_time"]].rename(
                columns={"target_exit_time": "exit_time"}
            )
            weights, _ = label_uniqueness(intervals)
            weights = weights.to_numpy(float)
            weights /= weights.mean()
            for name in MODEL_FEATURES:
                score, threshold = _fit_predict(
                    name, train, calibration, test, target, weights,
                )
                scored = test[[
                    "row_id", "timestamp", "target_exit_time", "direction",
                    "event_type", "executable_entry", target,
                ]].copy()
                scored["prediction"] = score
                scored["selected"] = score >= threshold
                predictions[name].append(scored)
                metrics = _metrics(scored, target)
                metrics.update({
                    "test_year": int(year),
                    "train_rows": len(train),
                    "calibration_rows": len(calibration),
                    "selection_threshold_pct": threshold,
                })
                fold_reports[name].append(metrics)

        if any(not parts for parts in predictions.values()):
            raise RuntimeError(f"no valid chronological folds for {target}")
        oos_frames = {
            name: pd.concat(parts, ignore_index=True) for name, parts in predictions.items()
        }
        models = {}
        for model_offset, name in enumerate(MODEL_FEATURES):
            oos = oos_frames[name]
            base_seed = seed + target_offset * 10000 + model_offset * 100
            intervals = _weekly_block_intervals(oos, target, bootstrap_samples, base_seed)
            direction_intervals = {
                direction: _weekly_block_intervals(
                    oos[oos.direction.eq(direction)].copy(), target,
                    bootstrap_samples, base_seed + direction_offset,
                )
                for direction_offset, direction in enumerate(("BUY", "SELL"), start=1)
            }
            stressed = oos.copy()
            stressed_target = "stressed_target_0.25"
            stressed[stressed_target] = _stressed_target(stressed, target)
            stressed_interval = _selected_weekly_interval(
                stressed, stressed_target, bootstrap_samples, base_seed + 10,
            )
            stressed_directions = {
                direction: _selected_weekly_interval(
                    stressed[stressed.direction.eq(direction)].copy(), stressed_target,
                    bootstrap_samples, base_seed + 20 + direction_offset,
                )
                for direction_offset, direction in enumerate(("BUY", "SELL"), start=1)
            }
            paired = None
            if name in PAIRED_CONTROLS:
                paired = _paired_weekly_interval(
                    oos, oos_frames[PAIRED_CONTROLS[name]], target,
                    bootstrap_samples, base_seed + 30,
                )
            positive_folds = sum(
                item["selected_mean_net_return_pct"] is not None
                and item["selected_mean_net_return_pct"] > 0
                for item in fold_reports[name]
            )
            direction_eligibility = {}
            if role == "PRIMARY":
                for direction in ("BUY", "SELL"):
                    side_base = direction_intervals[direction]
                    side_stress = stressed_directions[direction]
                    gates = {
                        "rank_ic_lower_95_above_zero": side_base["rank_ic_spearman"]["lower_95"] > 0,
                        "stressed_selected_return_lower_95_above_zero": side_stress["lower_95"] > 0,
                        "selected_rows_at_least_200": side_stress["selected_rows"] >= 200,
                        "selected_weeks_at_least_50": side_stress["selected_weeks"] >= 50,
                    }
                    direction_eligibility[direction] = {
                        "gates": gates, "eligible": all(gates.values()),
                    }
            eligible_directions = [
                direction for direction, item in direction_eligibility.items()
                if item["eligible"]
            ]
            primary_gates = {
                "rank_ic_lower_95_above_zero": intervals["rank_ic_spearman"]["lower_95"] > 0,
                "selected_return_lower_95_above_zero": intervals["selected_mean_net_return_pct"]["lower_95"] > 0,
                "selected_excess_lower_95_above_zero": intervals["selected_excess_over_all_candidates_pct"]["lower_95"] > 0,
                "positive_selected_return_in_at_least_three_folds": positive_folds >= 3,
                "paired_improvement_lower_95_above_zero": paired is not None and paired["lower_95_pct"] > 0,
                "stressed_0_25_selected_return_lower_95_above_zero": stressed_interval["lower_95"] > 0,
                "at_least_one_separately_eligible_direction": bool(eligible_directions),
            }
            gate_eligible = role == "PRIMARY" and name in PAIRED_CONTROLS
            models[name] = {
                "features": MODEL_FEATURES[name],
                "matched_control": PAIRED_CONTROLS.get(name),
                "overall_oos": _metrics(oos, target),
                "weekly_block_intervals": intervals,
                "direction_weekly_block_intervals": direction_intervals,
                "cost_stress_0_25_points_per_side": {
                    "overall_selected_interval": stressed_interval,
                    "direction_selected_intervals": stressed_directions,
                },
                "paired_improvement": paired,
                "folds": fold_reports[name],
                "direction_eligibility": direction_eligibility,
                "eligible_directions": eligible_directions,
                "primary_gate_eligible": gate_eligible,
                "primary_development_gates": primary_gates,
                "all_primary_development_gates_pass": gate_eligible and all(primary_gates.values()),
            }
        target_reports[key] = {
            "target": target,
            "role": role,
            "eligible_rows": len(frame),
            "models": models,
        }

    passing = [
        name for name, result in target_reports["4h"]["models"].items()
        if result["all_primary_development_gates_pass"]
    ]
    return {
        "status": (
            "EVENT_CANDIDATE_UNIVERSE_DEVELOPMENT_GATES_PASS" if passing
            else "REJECT_EVENT_CANDIDATE_UNIVERSE_MODELS"
        ),
        "scope": "CONTAMINATED_DEVELOPMENT_HISTORY_NO_MODEL_OR_RUNTIME_AUTHORIZATION",
        **common,
        "primary_target": contract["evaluation_contract"]["primary_target"],
        "primary_passing_models": passing,
        "selection_rule": contract["evaluation_contract"]["selection_threshold"],
        "purge_method": contract["evaluation_contract"]["purge"],
        "fit_weighting": contract["evaluation_contract"]["fit_weighting"],
        "multiple_testing_warning": (
            "Only the frozen 4h target and geometry models can pass. Secondary targets "
            "cannot select a horizon, model, threshold, event type, or runtime rule."
        ),
        "targets": target_reports,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=REGISTERED_BOOTSTRAP_SAMPLES)
    parser.add_argument("--seed", type=int, default=REGISTERED_SEED)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args()
    report = benchmark(args.dataset, args.bootstrap_samples, args.seed, args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps({
        "status": report["status"],
        "contract_version": report["contract_version"],
        "primary_target": report["primary_target"],
        "primary_passing_models": report["primary_passing_models"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
