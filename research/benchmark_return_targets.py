#!/usr/bin/env python3
"""Chronological benchmarks for alternative executable-side return targets.

This experiment asks whether candidate-time features rank after-cost returns at
1h/4h/12h/48h better than simple baselines.  It does not tune a strategy or
authorize a model.  Every fold uses only earlier labels, purges by each target's
actual executable exit, fixes its selection threshold on a later calibration
slice, and reports BUY/SELL separately.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from agent.ml_feature_engineer_gold import GoldFeatureEngineer
from research.analyze_research_evidence import label_uniqueness


FEATURES = GoldFeatureEngineer.FEATURE_COLS
HORIZONS = (1, 4, 12, 48)
SELECTION_QUANTILE = 0.80
MODEL_FEATURES = {
    "calibration_mean": [],
    "direction_ridge": ["direction_encoded"],
    "smc_score_ridge": ["smc_score_encoded"],
    "all_features_ridge": FEATURES,
    "all_features_xgboost": FEATURES,
}


def _finite_spearman(actual, predicted) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if (len(actual) < 3 or np.ptp(actual) < 1e-12 or
            np.ptp(predicted) < 1e-12):
        return 0.0
    value = spearmanr(actual, predicted).statistic
    return float(value) if np.isfinite(value) else 0.0


def _model(name: str):
    if name.endswith("ridge"):
        return Pipeline([
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=10.0)),
        ])
    if name == "all_features_xgboost":
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
    raise ValueError(f"unknown return benchmark {name}")


def _fit_predict(name, train, calibration, test, target, weights):
    if name == "calibration_mean":
        value = float(calibration[target].mean())
        return np.repeat(value, len(test)), value
    columns = MODEL_FEATURES[name]
    model = _model(name)
    if name.endswith("ridge"):
        model.fit(train[columns], train[target], ridge__sample_weight=weights)
    else:
        model.fit(train[columns], train[target], sample_weight=weights)
    calibration_score = model.predict(calibration[columns])
    test_score = model.predict(test[columns])
    threshold = float(np.quantile(calibration_score, SELECTION_QUANTILE))
    return np.asarray(test_score, dtype=float), threshold


def _metrics(frame: pd.DataFrame, target: str) -> dict:
    actual = frame[target].to_numpy(float)
    predicted = frame["prediction"].to_numpy(float)
    selected = frame[frame.selected]
    directions = {}
    for direction in ("BUY", "SELL"):
        side = frame[frame.direction.eq(direction)]
        chosen = side[side.selected]
        directions[direction] = {
            "rows": len(side),
            "rank_ic_spearman": _finite_spearman(side[target], side.prediction),
            "selected_rows": len(chosen),
            "selected_mean_net_return_pct": (
                float(chosen[target].mean()) if len(chosen) else None
            ),
        }
    return {
        "rows": len(frame),
        "mean_target_net_return_pct": float(np.mean(actual)),
        "mean_prediction_pct": float(np.mean(predicted)),
        "mae_pct": float(mean_absolute_error(actual, predicted)),
        "rmse_pct": float(mean_squared_error(actual, predicted) ** 0.5),
        "r2": float(r2_score(actual, predicted)),
        "rank_ic_spearman": _finite_spearman(actual, predicted),
        "selected_rows": len(selected),
        "selection_rate": float(len(selected) / len(frame)),
        "selected_mean_net_return_pct": (
            float(selected[target].mean()) if len(selected) else None
        ),
        "selected_excess_over_all_candidates_pct": (
            float(selected[target].mean() - frame[target].mean()) if len(selected) else None
        ),
        "by_direction": directions,
    }


def _weekly_block_intervals(frame: pd.DataFrame, target: str, samples=500, seed=42) -> dict:
    work = frame.copy()
    iso = work.target_exit_time.dt.isocalendar()
    work["week"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    groups = []
    for _, group in work.groupby("week", sort=True):
        chosen = group.selected.to_numpy(bool)
        actual = group[target].to_numpy(float)
        groups.append({
            "actual": actual,
            "prediction": group.prediction.to_numpy(float),
            "all_sum": float(actual.sum()),
            "all_count": len(actual),
            "selected_sum": float(actual[chosen].sum()),
            "selected_count": int(chosen.sum()),
        })
    all_sums = np.asarray([group["all_sum"] for group in groups])
    all_counts = np.asarray([group["all_count"] for group in groups])
    selected_sums = np.asarray([group["selected_sum"] for group in groups])
    selected_counts = np.asarray([group["selected_count"] for group in groups])
    rng = np.random.default_rng(seed)
    rank_ic, selected_mean, selected_excess = [], [], []
    for _ in range(samples):
        indices = rng.integers(0, len(groups), len(groups))
        draw_actual = np.concatenate([groups[index]["actual"] for index in indices])
        draw_prediction = np.concatenate(
            [groups[index]["prediction"] for index in indices]
        )
        rank_ic.append(_finite_spearman(draw_actual, draw_prediction))
        chosen_count = int(selected_counts[indices].sum())
        if chosen_count:
            chosen_mean = float(selected_sums[indices].sum() / chosen_count)
            all_mean = float(all_sums[indices].sum() / all_counts[indices].sum())
            selected_mean.append(chosen_mean)
            selected_excess.append(chosen_mean - all_mean)

    def interval(values):
        values = np.asarray(values, dtype=float)
        return {
            "median": float(np.median(values)),
            "lower_95": float(np.quantile(values, 0.025)),
            "upper_95": float(np.quantile(values, 0.975)),
        }

    return {
        "method": "calendar-week block bootstrap",
        "weeks": len(groups),
        "samples": samples,
        "seed": seed,
        "rank_ic_spearman": interval(rank_ic),
        "selected_mean_net_return_pct": interval(selected_mean),
        "selected_excess_over_all_candidates_pct": interval(selected_excess),
    }


def _prepare(path: Path, horizon: int) -> tuple[pd.DataFrame, str]:
    target = f"target_{horizon}h_net_return_pct"
    duration = f"target_{horizon}h_actual_exit_hours"
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    required = [target, duration, "rr_ratio", "direction", *FEATURES]
    frame = frame.dropna(subset=required).copy()
    frame = frame[frame.rr_ratio >= 2].copy()
    frame["target_exit_time"] = (
        frame.timestamp + pd.to_timedelta(frame[duration], unit="h")
    )
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame, target


def benchmark(path: Path, bootstrap_samples=500, seed=42) -> dict:
    horizons = {}
    for horizon in HORIZONS:
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
            uniqueness_frame = train[["timestamp", "target_exit_time"]].rename(
                columns={"target_exit_time": "exit_time"}
            )
            weights, _ = label_uniqueness(uniqueness_frame)
            weights = weights.to_numpy(float)
            weights = weights / np.mean(weights)
            for model_name in MODEL_FEATURES:
                score, threshold = _fit_predict(
                    model_name, train, calibration, test, target, weights,
                )
                scored = test[["timestamp", "target_exit_time", "direction", target]].copy()
                scored["prediction"] = score
                scored["selected"] = score >= threshold
                predictions[model_name].append(scored)
                fold_metric = _metrics(scored, target)
                fold_metric.update({
                    "test_year": int(year),
                    "train_rows": len(train),
                    "calibration_rows": len(calibration),
                    "selection_threshold_pct": threshold,
                })
                fold_reports[model_name].append(fold_metric)

        models = {}
        for offset, model_name in enumerate(MODEL_FEATURES):
            oos = pd.concat(predictions[model_name], ignore_index=True)
            metrics = _metrics(oos, target)
            intervals = _weekly_block_intervals(
                oos, target, bootstrap_samples, seed + horizon * 10 + offset,
            )
            positive_folds = sum(
                report["selected_mean_net_return_pct"] is not None and
                report["selected_mean_net_return_pct"] > 0
                for report in fold_reports[model_name]
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
            }
            models[model_name] = {
                "overall_oos": metrics,
                "weekly_block_intervals": intervals,
                "folds": fold_reports[model_name],
                "exploratory_gates": gates,
                "all_exploratory_gates_pass": all(gates.values()),
            }
        horizons[f"{horizon}h"] = {
            "target": target,
            "eligible_rows": len(frame),
            "models": models,
        }
    any_pass = any(
        model["all_exploratory_gates_pass"]
        for horizon in horizons.values() for model in horizon["models"].values()
    )
    return {
        "status": "EXPLORATORY_SIGNAL_FOUND" if any_pass else "NO_EXPLORATORY_SIGNAL",
        "scope": "CONTAMINATED_DEVELOPMENT_HISTORY_NO_MODEL_AUTHORIZATION",
        "target_version": "multi_horizon_executable_return_v1",
        "horizons_hours": list(HORIZONS),
        "selection_rule": (
            "prediction >= 80th percentile of model scores in the prior calibration slice"
        ),
        "purge_method": "actual target exit must precede calibration/test boundary",
        "fit_weighting": "average inverse target-interval concurrency, normalized to mean one",
        "multiple_testing_warning": (
            "Four targets and four fixed models are exploratory; any pass requires a separately "
            "registered reproduction and cannot authorize deployment."
        ),
        "horizons": horizons,
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
