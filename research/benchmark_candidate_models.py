#!/usr/bin/env python3
"""Leakage-aware development benchmarks for gold candidate classification.

All models share the same expanding folds, 48-hour purge, calibration windows
and break-even selection rule. Results are development diagnostics only: the
historical period has already influenced feature and strategy design.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from agent.ml_feature_engineer_gold import GoldFeatureEngineer


PURGE = pd.Timedelta(hours=48)
FEATURES = GoldFeatureEngineer.FEATURE_COLS
MODEL_FEATURES = {
    "calibration_prevalence": [],
    "direction_only_logistic": ["direction_encoded"],
    "smc_score_only_logistic": ["smc_score_encoded"],
    "all_features_logistic": FEATURES,
    "all_features_xgboost": FEATURES,
}


def _safe_probability(values):
    return np.clip(np.asarray(values, dtype=float), 1e-6, 1 - 1e-6)


def _calibrate(raw_cal, y_cal, raw_test):
    calibrator = LogisticRegression(C=1.0, solver="lbfgs", random_state=42)
    raw_cal = _safe_probability(raw_cal)
    raw_test = _safe_probability(raw_test)
    calibrator.fit(np.log(raw_cal / (1 - raw_cal)).reshape(-1, 1), y_cal)
    return calibrator.predict_proba(
        np.log(raw_test / (1 - raw_test)).reshape(-1, 1)
    )[:, 1]


def _predict(model_name, train, calibration, test):
    y_train = train.label_profitable.astype(int)
    y_cal = calibration.label_profitable.astype(int)
    if model_name == "calibration_prevalence":
        # This is available at test time, unlike test-fold prevalence.
        return np.repeat(float(y_cal.mean()), len(test))
    columns = MODEL_FEATURES[model_name]
    if model_name.endswith("logistic"):
        model = make_pipeline(
            StandardScaler(),
            LogisticRegression(C=1.0, max_iter=2000, solver="lbfgs", random_state=42),
        )
    elif model_name == "all_features_xgboost":
        model = XGBClassifier(
            max_depth=3, n_estimators=250, learning_rate=.03,
            subsample=.8, colsample_bytree=.8, min_child_weight=10,
            reg_lambda=2, random_state=42, n_jobs=4,
            objective="binary:logistic", eval_metric="logloss",
        )
    else:  # pragma: no cover - guarded by MODEL_FEATURES
        raise ValueError(f"unknown benchmark model {model_name}")
    model.fit(train[columns], y_train)
    raw_cal = model.predict_proba(calibration[columns])[:, 1]
    raw_test = model.predict_proba(test[columns])[:, 1]
    return _calibrate(raw_cal, y_cal, raw_test)


def _metrics(frame):
    y = frame.label_profitable.astype(int).to_numpy()
    probability = frame.probability.to_numpy(float)
    selected = frame[frame.selected]
    result = {
        "rows": len(frame),
        "prevalence": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, probability)),
        "brier": float(brier_score_loss(y, probability)),
        "log_loss": float(log_loss(y, _safe_probability(probability))),
        "mean_probability": float(probability.mean()),
        "calibration_gap": float(probability.mean() - y.mean()),
        "selected_rows": len(selected),
        "selection_rate": float(len(selected) / len(frame)),
        "selected_mean_probability": (float(selected.probability.mean()) if len(selected) else None),
        "selected_win_rate": (float(selected.label_profitable.mean()) if len(selected) else None),
        "selected_calibration_gap": (
            float(selected.probability.mean() - selected.label_profitable.mean())
            if len(selected) else None
        ),
        "selected_mean_net_return_pct": (
            float(selected.net_return_pct.mean()) if len(selected) else None
        ),
    }
    return result


def weekly_block_intervals(frame, samples=2000, seed=42):
    """Resample complete calendar weeks to preserve short-range dependence."""
    work = frame.copy()
    iso = work.timestamp.dt.isocalendar()
    work["week"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    blocks = [group.index.to_numpy() for _, group in work.groupby("week", sort=True)]
    if not blocks:
        return {"samples": samples, "weeks": 0}
    rng = np.random.default_rng(seed)
    auc_values, selected_means = [], []
    for _ in range(samples):
        chosen = rng.integers(0, len(blocks), len(blocks))
        indices = np.concatenate([blocks[index] for index in chosen])
        draw = work.loc[indices]
        if draw.label_profitable.nunique() > 1:
            auc_values.append(roc_auc_score(draw.label_profitable, draw.probability))
        selected = draw[draw.selected]
        if len(selected):
            selected_means.append(float(selected.net_return_pct.mean()))

    def interval(values):
        clean = np.asarray(values, dtype=float)
        return {
            "median": float(np.median(clean)),
            "lower_95": float(np.quantile(clean, .025)),
            "upper_95": float(np.quantile(clean, .975)),
        }

    return {
        "samples": samples, "weeks": len(blocks), "seed": seed,
        "roc_auc": interval(auc_values),
        "selected_mean_net_return_pct": interval(selected_means),
    }


def benchmark(path, bootstrap_samples=2000, seed=42):
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame = frame.dropna(subset=["label_profitable", "net_return_pct", *FEATURES])
    frame = frame[frame.rr_ratio >= 2].sort_values("timestamp").reset_index(drop=True)
    predictions = {name: [] for name in MODEL_FEATURES}
    fold_reports = {name: [] for name in MODEL_FEATURES}
    years = sorted(year for year in frame.timestamp.dt.year.unique() if year >= 2022)
    for year in years:
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        prior = frame[frame.timestamp < start - PURGE]
        test = frame[(frame.timestamp >= start) & (frame.timestamp < end)].copy()
        if len(prior) < 500 or len(test) < 100:
            continue
        calibration_start = prior.timestamp.iloc[int(len(prior) * .8)]
        train = prior[prior.timestamp < calibration_start - PURGE]
        calibration = prior[prior.timestamp >= calibration_start]
        for model_name in MODEL_FEATURES:
            scored = test[[
                "timestamp", "direction", "rr_ratio", "net_return_pct", "label_profitable"
            ]].copy()
            scored["probability"] = _predict(model_name, train, calibration, test)
            scored["selected"] = scored.probability >= (1 / (scored.rr_ratio + 1) + .03)
            fold_metric = _metrics(scored)
            fold_metric.update({
                "year": int(year), "train_rows": len(train),
                "calibration_rows": len(calibration),
            })
            fold_reports[model_name].append(fold_metric)
            predictions[model_name].append(scored)

    reports = {}
    for model_name, parts in predictions.items():
        combined = pd.concat(parts, ignore_index=True)
        directions = {
            direction: _metrics(group)
            for direction, group in combined.groupby("direction")
        }
        reports[model_name] = {
            "features": MODEL_FEATURES[model_name],
            "folds": fold_reports[model_name],
            "overall": _metrics(combined),
            "by_direction": directions,
            "weekly_block_intervals": weekly_block_intervals(
                combined, samples=bootstrap_samples, seed=seed
            ),
        }
    xgb = reports["all_features_xgboost"]
    prevalence = reports["calibration_prevalence"]
    diagnostic_gates = {
        "xgboost_auc_lower_95_above_chance": (
            xgb["weekly_block_intervals"]["roc_auc"]["lower_95"] > .5
        ),
        "xgboost_brier_better_than_available_prevalence": (
            xgb["overall"]["brier"] < prevalence["overall"]["brier"]
        ),
        "xgboost_selected_return_lower_95_above_zero": (
            xgb["weekly_block_intervals"]["selected_mean_net_return_pct"]["lower_95"] > 0
        ),
        "xgboost_auc_beats_all_simple_models": all(
            xgb["overall"]["roc_auc"] > reports[name]["overall"]["roc_auc"]
            for name in MODEL_FEATURES if name != "all_features_xgboost"
        ),
    }
    return {
        "status": "DEVELOPMENT_BENCHMARK_ONLY",
        "scope": "CONTAMINATED_HISTORY_NOT_MODEL_AUTHORIZATION",
        "purge_hours": 48,
        "selection_rule": "probability >= 1/(rr_ratio+1)+0.03",
        "models": reports,
        "diagnostic_gates": diagnostic_gates,
        "limitations": [
            "2020-2026 influenced strategy and feature development.",
            "Weekly blocks preserve short dependence but are not a final untouched test.",
            "No benchmark result authorizes model deployment or live trading.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    report = benchmark(args.dataset, args.bootstrap_samples, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "status": report["status"],
        "diagnostic_gates": report["diagnostic_gates"],
        "overall": {name: values["overall"] for name, values in report["models"].items()},
    }, indent=2))


if __name__ == "__main__":
    main()
