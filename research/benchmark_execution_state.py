#!/usr/bin/env python3
"""Evaluate registered execution-state v1 features against matched controls."""

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

from agent.ml_feature_engineer_gold import GoldFeatureEngineer
from research.analyze_research_evidence import label_uniqueness
from research.benchmark_return_targets import (
    SELECTION_QUANTILE,
    _metrics,
    _weekly_block_intervals,
)
from research.build_execution_state_dataset import (
    CONTRACT_PATH,
    EXECUTION_FEATURES,
    EXPECTED_CONTRACT_SHA256,
    load_contract,
)


TECHNICAL_FEATURES = GoldFeatureEngineer.FEATURE_COLS
TARGET_HORIZONS = (1, 4, 12, 48)
BASE_SLIPPAGE_POINTS_PER_SIDE = 0.10
STRESS_SLIPPAGE_POINTS_PER_SIDE = (0.10, 0.25, 0.50)
REGISTERED_BOOTSTRAP_SAMPLES = 500
REGISTERED_SEED = 42
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
MODEL_FEATURES = {
    "calibration_mean": [],
    "direction_ridge": ["direction_encoded"],
    "smc_score_ridge": ["smc_score_encoded"],
    "execution_only_ridge": EXECUTION_FEATURES,
    "technical_only_ridge_control": TECHNICAL_FEATURES,
    "technical_plus_execution_ridge": TECHNICAL_FEATURES + EXECUTION_FEATURES,
    "technical_only_xgboost_control": TECHNICAL_FEATURES,
    "technical_plus_execution_xgboost": TECHNICAL_FEATURES + EXECUTION_FEATURES,
}
PAIRED_CONTROLS = {
    "execution_only_ridge": "calibration_mean",
    "technical_plus_execution_ridge": "technical_only_ridge_control",
    "technical_plus_execution_xgboost": "technical_only_xgboost_control",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _model(name: str):
    if name.endswith("ridge") or name.endswith("ridge_control"):
        return Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=10.0)),
        ])
    if "xgboost" in name:
        return XGBRegressor(
            **XGBOOST_PARAMETERS,
            objective="reg:squarederror",
            eval_metric="rmse",
        )
    raise ValueError(f"unknown execution-state model {name}")


def _fit_predict(name, train, calibration, test, target, weights):
    if name == "calibration_mean":
        value = float(calibration[target].mean())
        return np.repeat(value, len(test)), value
    columns = MODEL_FEATURES[name]
    model = _model(name)
    if "ridge" in name:
        model.fit(train[columns], train[target], ridge__sample_weight=weights)
    else:
        model.fit(train[columns], train[target], sample_weight=weights)
    calibration_score = model.predict(calibration[columns])
    threshold = float(np.quantile(calibration_score, SELECTION_QUANTILE))
    return np.asarray(model.predict(test[columns]), dtype=float), threshold


def _paired_weekly_interval(model_frame: pd.DataFrame, control_frame: pd.DataFrame,
                            target: str, samples=500, seed=42) -> dict:
    paired = model_frame[["row_id", "target_exit_time", target, "selected"]].merge(
        control_frame[["row_id", "selected"]], on="row_id", validate="one_to_one",
        suffixes=("_model", "_control"),
    )
    iso = paired.target_exit_time.dt.isocalendar()
    paired["week"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    groups = []
    for _, group in paired.groupby("week", sort=True):
        actual = group[target].to_numpy(float)
        model_selected = group.selected_model.to_numpy(bool)
        control_selected = group.selected_control.to_numpy(bool)
        groups.append((
            float(actual[model_selected].sum()), int(model_selected.sum()),
            float(actual[control_selected].sum()), int(control_selected.sum()),
        ))
    values = np.asarray(groups, dtype=float)
    rng = np.random.default_rng(seed)
    differences = []
    for _ in range(samples):
        draw = values[rng.integers(0, len(values), len(values))]
        model_count, control_count = draw[:, 1].sum(), draw[:, 3].sum()
        if model_count and control_count:
            differences.append(
                draw[:, 0].sum() / model_count - draw[:, 2].sum() / control_count
            )
    differences = np.asarray(differences, dtype=float)
    return {
        "method": "paired calendar-week block bootstrap",
        "samples": len(differences), "weeks": len(groups), "seed": seed,
        "median_pct": float(np.median(differences)),
        "lower_95_pct": float(np.quantile(differences, 0.025)),
        "upper_95_pct": float(np.quantile(differences, 0.975)),
    }


def _selected_weekly_interval(frame: pd.DataFrame, target: str,
                              samples=500, seed=42) -> dict:
    work = frame.copy()
    iso = work.target_exit_time.dt.isocalendar()
    work["week"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    groups = []
    for _, group in work.groupby("week", sort=True):
        chosen = group[group.selected]
        groups.append((float(chosen[target].sum()), len(chosen)))
    values = np.asarray(groups, dtype=float)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(samples):
        draw = values[rng.integers(0, len(values), len(values))]
        count = draw[:, 1].sum()
        if count:
            means.append(draw[:, 0].sum() / count)
    means = np.asarray(means, dtype=float)
    selected = work[work.selected]
    selected_weeks = selected["week"].nunique()
    return {
        "method": "calendar-week block bootstrap of selected mean",
        "samples": len(means), "weeks": len(groups), "selected_weeks": int(selected_weeks),
        "selected_rows": len(selected), "seed": seed,
        "median": float(np.median(means)),
        "lower_95": float(np.quantile(means, 0.025)),
        "upper_95": float(np.quantile(means, 0.975)),
    }


def _prepare(path: Path, horizon: int) -> tuple[pd.DataFrame, str]:
    target = f"target_{horizon}h_net_return_pct"
    duration = f"target_{horizon}h_actual_exit_hours"
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    required = [
        target, duration, "rr_ratio", "direction", "executable_entry",
        *TECHNICAL_FEATURES, *EXECUTION_FEATURES,
    ]
    frame = frame.dropna(subset=required).copy()
    frame = frame[frame.rr_ratio >= 2].copy()
    frame["target_exit_time"] = frame.timestamp + pd.to_timedelta(
        frame[duration], unit="h",
    )
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    frame["row_id"] = np.arange(len(frame))
    return frame, target


def _stressed_target(frame: pd.DataFrame, target: str, slippage: float) -> pd.Series:
    incremental_points = 2 * (slippage - BASE_SLIPPAGE_POINTS_PER_SIDE)
    return frame[target] - incremental_points / frame["executable_entry"] * 100


def _validate_registered_evaluation(contract: dict, bootstrap_samples: int,
                                    seed: int) -> None:
    evaluation = contract.get("evaluation_contract", {})
    expected_secondary = [f"target_{h}h_net_return_pct" for h in TARGET_HORIZONS[1:]]
    checks = {
        "primary target": evaluation.get("primary_target") == "target_1h_net_return_pct",
        "secondary targets": evaluation.get("secondary_diagnostic_targets") == expected_secondary,
        "minimum risk reward": float(evaluation.get("candidate_minimum_risk_reward", -1)) == 2.0,
        "model ladder": list(evaluation.get("models", {})) == list(MODEL_FEATURES),
        "paired controls": evaluation.get("paired_controls") == PAIRED_CONTROLS,
        "xgboost parameters": evaluation.get("xgboost_parameters") == XGBOOST_PARAMETERS,
        "cost stress": evaluation.get("cost_stress_slippage_points_per_side") == list(
            STRESS_SLIPPAGE_POINTS_PER_SIDE
        ),
        "only primary can pass": evaluation.get(
            "only_primary_target_can_pass_development_gates"
        ) is True,
        "secondary cannot select": evaluation.get(
            "secondary_results_cannot_select_a_horizon_model_or_threshold"
        ) is True,
        "registered bootstrap samples": bootstrap_samples == REGISTERED_BOOTSTRAP_SAMPLES,
        "registered seed": seed == REGISTERED_SEED,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            "execution-state implementation differs from registered evaluation: "
            + ", ".join(failed)
        )


def benchmark(path: Path, bootstrap_samples=500, seed=42,
              contract_path: Path = CONTRACT_PATH) -> dict:
    contract, contract_sha = load_contract(contract_path)
    if contract_sha != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("execution-state benchmark contract hash mismatch")
    _validate_registered_evaluation(contract, bootstrap_samples, seed)
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("contract_sha256") != contract_sha or
            manifest.get("dataset_sha256") != _sha256(path) or
            manifest.get("feature_schema_sha256") != contract["feature_contract"]["schema_sha256"]):
        raise RuntimeError("execution-state dataset manifest mismatch")

    horizon_reports = {}
    for horizon in TARGET_HORIZONS:
        frame, target = _prepare(path, horizon)
        predictions = {name: [] for name in MODEL_FEATURES}
        fold_reports = {name: [] for name in MODEL_FEATURES}
        years = sorted(year for year in frame.timestamp.dt.year.unique() if year >= 2022)
        for year in years:
            start = pd.Timestamp(f"{year}-01-01", tz="UTC")
            end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
            prior = frame[(frame.timestamp < start) & (frame.target_exit_time < start)]
            test = frame[(frame.timestamp >= start) & (frame.timestamp < end)].copy()
            if len(prior) < 500 or len(test) < 100:
                continue
            calibration_start = prior.timestamp.iloc[int(len(prior) * 0.8)]
            train = prior[
                (prior.timestamp < calibration_start) &
                (prior.target_exit_time < calibration_start)
            ].copy()
            calibration = prior[prior.timestamp >= calibration_start].copy()
            intervals = train[["timestamp", "target_exit_time"]].rename(
                columns={"target_exit_time": "exit_time"}
            )
            weights, _ = label_uniqueness(intervals)
            weights = weights.to_numpy(float)
            weights = weights / np.mean(weights)
            for name in MODEL_FEATURES:
                score, threshold = _fit_predict(
                    name, train, calibration, test, target, weights,
                )
                scored = test[[
                    "row_id", "timestamp", "target_exit_time", "direction",
                    "executable_entry", target,
                ]].copy()
                scored["prediction"] = score
                scored["selected"] = score >= threshold
                predictions[name].append(scored)
                metrics = _metrics(scored, target)
                metrics.update({
                    "test_year": int(year), "train_rows": len(train),
                    "calibration_rows": len(calibration),
                    "selection_threshold_pct": threshold,
                })
                fold_reports[name].append(metrics)

        oos_frames = {
            name: pd.concat(parts, ignore_index=True) for name, parts in predictions.items()
        }
        models = {}
        for offset, name in enumerate(MODEL_FEATURES):
            oos = oos_frames[name]
            base_intervals = _weekly_block_intervals(
                oos, target, bootstrap_samples, seed + horizon * 100 + offset,
            )
            direction_intervals = {
                direction: _weekly_block_intervals(
                    oos[oos.direction.eq(direction)].copy(), target, bootstrap_samples,
                    seed + horizon * 1000 + offset * 10 + direction_offset,
                )
                for direction_offset, direction in enumerate(("BUY", "SELL"), start=1)
            }
            stress = {}
            for stress_offset, slippage in enumerate(STRESS_SLIPPAGE_POINTS_PER_SIDE):
                stress_name = f"slippage_{slippage:.2f}_points_per_side"
                stressed = oos.copy()
                stressed_target = f"stressed_target_{slippage:.2f}"
                stressed[stressed_target] = _stressed_target(stressed, target, slippage)
                stress_report = {
                    "slippage_points_per_side": slippage,
                    "overall_selected_interval": _selected_weekly_interval(
                        stressed, stressed_target, bootstrap_samples,
                        seed + horizon * 10000 + offset * 100 + stress_offset,
                    ),
                }
                if horizon == 1 and abs(slippage - 0.25) < 1e-12:
                    stress_report["direction_selected_intervals"] = {
                        direction: _selected_weekly_interval(
                            stressed[stressed.direction.eq(direction)].copy(),
                            stressed_target, bootstrap_samples,
                            seed + horizon * 100000 + offset * 100 + direction_offset,
                        )
                        for direction_offset, direction in enumerate(("BUY", "SELL"), start=1)
                    }
                stress[stress_name] = stress_report

            paired = None
            if name in PAIRED_CONTROLS:
                paired = _paired_weekly_interval(
                    oos, oos_frames[PAIRED_CONTROLS[name]], target,
                    bootstrap_samples, seed + horizon * 1000000 + offset,
                )
            positive_folds = sum(
                item["selected_mean_net_return_pct"] is not None and
                item["selected_mean_net_return_pct"] > 0
                for item in fold_reports[name]
            )
            direction_eligibility = {}
            if horizon == 1:
                direction_stress = stress[
                    "slippage_0.25_points_per_side"
                ]["direction_selected_intervals"]
                for direction in ("BUY", "SELL"):
                    side_base = direction_intervals[direction]
                    side_stress = direction_stress[direction]
                    direction_gates = {
                        "rank_ic_lower_95_above_zero": (
                            side_base["rank_ic_spearman"]["lower_95"] > 0
                        ),
                        "stressed_selected_return_lower_95_above_zero": (
                            side_stress["lower_95"] > 0
                        ),
                        "selected_rows_at_least_200": side_stress["selected_rows"] >= 200,
                        "selected_weeks_at_least_50": side_stress["selected_weeks"] >= 50,
                    }
                    direction_eligibility[direction] = {
                        "gates": direction_gates,
                        "eligible": all(direction_gates.values()),
                    }
            eligible_directions = [
                direction for direction, item in direction_eligibility.items()
                if item["eligible"]
            ]
            primary_gates = {
                "rank_ic_lower_95_above_zero": (
                    base_intervals["rank_ic_spearman"]["lower_95"] > 0
                ),
                "selected_return_lower_95_above_zero": (
                    base_intervals["selected_mean_net_return_pct"]["lower_95"] > 0
                ),
                "selected_excess_lower_95_above_zero": (
                    base_intervals["selected_excess_over_all_candidates_pct"]["lower_95"] > 0
                ),
                "positive_selected_return_in_at_least_three_folds": positive_folds >= 3,
                "paired_improvement_lower_95_above_zero": (
                    paired is not None and paired["lower_95_pct"] > 0
                ),
                "stressed_0_25_selected_return_lower_95_above_zero": (
                    stress["slippage_0.25_points_per_side"]
                    ["overall_selected_interval"]["lower_95"] > 0
                ),
                "at_least_one_separately_eligible_direction": bool(eligible_directions),
            }
            gate_eligible = horizon == 1 and name in PAIRED_CONTROLS
            models[name] = {
                "features": MODEL_FEATURES[name],
                "matched_control": PAIRED_CONTROLS.get(name),
                "overall_oos": _metrics(oos, target),
                "weekly_block_intervals": base_intervals,
                "direction_weekly_block_intervals": direction_intervals,
                "cost_stress": stress,
                "paired_improvement": paired,
                "folds": fold_reports[name],
                "direction_eligibility": direction_eligibility,
                "eligible_directions": eligible_directions,
                "primary_gate_eligible": gate_eligible,
                "primary_development_gates": primary_gates,
                "all_primary_development_gates_pass": (
                    gate_eligible and all(primary_gates.values())
                ),
            }
        horizon_reports[f"{horizon}h"] = {
            "target": target,
            "role": "PRIMARY" if horizon == 1 else "SECONDARY_DIAGNOSTIC",
            "eligible_rows": len(frame),
            "models": models,
        }

    passing = [
        name for name, result in horizon_reports["1h"]["models"].items()
        if result["all_primary_development_gates_pass"]
    ]
    return {
        "status": (
            "EXECUTION_STATE_DEVELOPMENT_GATES_PASS" if passing
            else "REJECT_EXECUTION_STATE_MODELS"
        ),
        "scope": "CONTAMINATED_DEVELOPMENT_HISTORY_NO_MODEL_OR_RUNTIME_AUTHORIZATION",
        "contract_version": contract["contract_version"],
        "contract_sha256": contract_sha,
        "dataset_sha256": _sha256(path),
        "dataset_manifest_sha256": _sha256(manifest_path),
        "benchmark_script_sha256": _sha256(Path(__file__)),
        "bootstrap_samples": bootstrap_samples,
        "seed": seed,
        "primary_target": contract["evaluation_contract"]["primary_target"],
        "primary_passing_models": passing,
        "selection_rule": contract["evaluation_contract"]["selection_threshold"],
        "purge_method": contract["evaluation_contract"]["purge"],
        "fit_weighting": contract["evaluation_contract"]["fit_weighting"],
        "cost_stress_method": contract["evaluation_contract"]["cost_stress_method"],
        "model_artifact_created": False,
        "runtime_changed": False,
        "multiple_testing_warning": (
            "Only 1h can pass; 4h/12h/48h are diagnostics and cannot select a model or target."
        ),
        "horizons": horizon_reports,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args()
    report = benchmark(
        args.dataset, args.bootstrap_samples, args.seed, args.contract,
    )
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
