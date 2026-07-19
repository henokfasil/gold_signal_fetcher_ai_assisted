#!/usr/bin/env python3
"""Evaluate gold-context v2 against matched no-context controls."""

import argparse
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
from research.build_gold_context_dataset import CONTEXT_FEATURES


TECHNICAL_FEATURES = GoldFeatureEngineer.FEATURE_COLS
TARGET_HORIZONS = (4, 12, 48)
MODEL_FEATURES = {
    "calibration_mean": [],
    "direction_ridge": ["direction_encoded"],
    "smc_score_ridge": ["smc_score_encoded"],
    "context_only_ridge": CONTEXT_FEATURES,
    "technical_only_ridge_control": TECHNICAL_FEATURES,
    "technical_plus_context_ridge": TECHNICAL_FEATURES + CONTEXT_FEATURES,
    "technical_only_xgboost_control": TECHNICAL_FEATURES,
    "technical_plus_context_xgboost": TECHNICAL_FEATURES + CONTEXT_FEATURES,
}
PAIRED_CONTROLS = {
    "context_only_ridge": "calibration_mean",
    "technical_plus_context_ridge": "technical_only_ridge_control",
    "technical_plus_context_xgboost": "technical_only_xgboost_control",
}


def _model(name: str):
    if name.endswith("ridge") or name.endswith("ridge_control"):
        return Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=10.0)),
        ])
    if "xgboost" in name:
        return XGBRegressor(
            max_depth=3,
            n_estimators=250,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=10,
            reg_lambda=2,
            random_state=42,
            n_jobs=4,
            objective="reg:squarederror",
            eval_metric="rmse",
        )
    raise ValueError(f"unknown context model {name}")


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
    test_score = model.predict(test[columns])
    threshold = float(np.quantile(calibration_score, SELECTION_QUANTILE))
    return np.asarray(test_score, dtype=float), threshold


def _paired_weekly_interval(model_frame: pd.DataFrame, control_frame: pd.DataFrame,
                            target: str, samples=500, seed=42) -> dict:
    columns = ["row_id", "target_exit_time", target, "selected"]
    paired = model_frame[columns].merge(
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
        groups.append({
            "model_sum": float(actual[model_selected].sum()),
            "model_count": int(model_selected.sum()),
            "control_sum": float(actual[control_selected].sum()),
            "control_count": int(control_selected.sum()),
        })
    arrays = {
        key: np.asarray([group[key] for group in groups])
        for key in ("model_sum", "model_count", "control_sum", "control_count")
    }
    rng = np.random.default_rng(seed)
    differences = []
    for _ in range(samples):
        draw = rng.integers(0, len(groups), len(groups))
        model_count = arrays["model_count"][draw].sum()
        control_count = arrays["control_count"][draw].sum()
        if not model_count or not control_count:
            continue
        differences.append(
            arrays["model_sum"][draw].sum() / model_count -
            arrays["control_sum"][draw].sum() / control_count
        )
    values = np.asarray(differences, dtype=float)
    return {
        "method": "paired calendar-week block bootstrap",
        "samples": len(values),
        "weeks": len(groups),
        "seed": seed,
        "median_pct": float(np.median(values)),
        "lower_95_pct": float(np.quantile(values, 0.025)),
        "upper_95_pct": float(np.quantile(values, 0.975)),
    }


def _prepare(path: Path, horizon: int) -> tuple[pd.DataFrame, str]:
    target = f"target_{horizon}h_net_return_pct"
    duration = f"target_{horizon}h_actual_exit_hours"
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    required_nonmissing = [
        target, duration, "rr_ratio", "direction", *TECHNICAL_FEATURES,
    ]
    frame = frame.dropna(subset=required_nonmissing).copy()
    frame = frame[frame.rr_ratio >= 2].copy()
    frame["target_exit_time"] = (
        frame.timestamp + pd.to_timedelta(frame[duration], unit="h")
    )
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    frame["row_id"] = np.arange(len(frame))
    return frame, target


def benchmark(path: Path, bootstrap_samples=500, seed=42) -> dict:
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
                scored = test[
                    ["row_id", "timestamp", "target_exit_time", "direction", target]
                ].copy()
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

        oos_frames = {
            name: pd.concat(parts, ignore_index=True)
            for name, parts in predictions.items()
        }
        models = {}
        for offset, name in enumerate(MODEL_FEATURES):
            oos = oos_frames[name]
            intervals = _weekly_block_intervals(
                oos, target, bootstrap_samples, seed + horizon * 20 + offset,
            )
            direction_intervals = {
                direction: _weekly_block_intervals(
                    oos[oos.direction.eq(direction)].copy(), target,
                    bootstrap_samples,
                    seed + horizon * 1000 + offset * 10 + direction_offset,
                )
                for direction_offset, direction in enumerate(("BUY", "SELL"), start=1)
            }
            positive_folds = sum(
                fold["selected_mean_net_return_pct"] is not None and
                fold["selected_mean_net_return_pct"] > 0
                for fold in fold_reports[name]
            )
            paired = None
            if name in PAIRED_CONTROLS:
                paired = _paired_weekly_interval(
                    oos, oos_frames[PAIRED_CONTROLS[name]], target,
                    bootstrap_samples, seed + horizon * 100 + offset,
                )
            gates = {
                "rank_ic_lower_95_above_zero": (
                    intervals["rank_ic_spearman"]["lower_95"] > 0
                ),
                "selected_return_lower_95_above_zero": (
                    intervals["selected_mean_net_return_pct"]["lower_95"] > 0
                ),
                "selected_excess_lower_95_above_zero": (
                    intervals["selected_excess_over_all_candidates_pct"]["lower_95"] > 0
                ),
                "positive_selected_return_in_at_least_three_folds": positive_folds >= 3,
                "paired_improvement_lower_95_above_zero": (
                    paired is not None and paired["lower_95_pct"] > 0
                ),
            }
            eligible = name in PAIRED_CONTROLS
            models[name] = {
                "features": MODEL_FEATURES[name],
                "matched_control": PAIRED_CONTROLS.get(name),
                "overall_oos": _metrics(oos, target),
                "weekly_block_intervals": intervals,
                "direction_weekly_block_intervals": direction_intervals,
                "paired_improvement": paired,
                "folds": fold_reports[name],
                "context_gate_eligible": eligible,
                "development_gates": gates,
                "all_development_gates_pass": eligible and all(gates.values()),
            }
        horizon_reports[f"{horizon}h"] = {
            "target": target,
            "role": "PRIMARY" if horizon == 4 else "SECONDARY_DIAGNOSTIC",
            "eligible_rows": len(frame),
            "models": models,
        }

    primary_passes = [
        name for name, report in horizon_reports["4h"]["models"].items()
        if report["all_development_gates_pass"]
    ]
    return {
        "status": "CONTEXT_DEVELOPMENT_GATES_PASS" if primary_passes else "REJECT_CONTEXT_MODELS",
        "scope": "CONTAMINATED_DEVELOPMENT_HISTORY_NO_MODEL_AUTHORIZATION",
        "contract_version": "gold-context-20260719-v2",
        "primary_target": "target_4h_net_return_pct",
        "primary_passing_models": primary_passes,
        "selection_rule": (
            "prediction >= 80th percentile of scores in prior calibration slice"
        ),
        "purge_method": "actual target exit precedes calibration/test boundary",
        "fit_weighting": "average inverse target-interval concurrency normalized to mean one",
        "missing_policy": "fold-local median imputation; all-empty training columns become zero; explicit missing flags retained",
        "multiple_testing_warning": "12h and 48h results are secondary diagnostics and cannot promote a context model.",
        "horizons": horizon_reports,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    report = benchmark(args.dataset, args.bootstrap_samples, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
