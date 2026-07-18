#!/usr/bin/env python3
"""Purged expanding-window validation for the candidate classifier.

This is a development diagnostic, not a final untouched test. Each test year is
scored by a model trained only on earlier observations. The last 20% of each
training window calibrates probabilities. Training labels must actually exit
before the next calibration/test boundary, which is safer than assuming a
fixed row count or nominal horizon around market closures.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from xgboost import XGBClassifier

from agent.ml_feature_engineer_gold import GoldFeatureEngineer


def metrics(y, probability):
    return {"rows": len(y), "prevalence": float(np.mean(y)),
            "roc_auc": float(roc_auc_score(y, probability)),
            "brier": float(brier_score_loss(y, probability)),
            "brier_baseline": float(brier_score_loss(y, np.repeat(np.mean(y), len(y)))),
            "log_loss": float(log_loss(y, probability))}


def validate(path: Path) -> dict:
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["exit_time"] = pd.to_datetime(frame["exit_time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["label_profitable", "net_return_pct", "exit_time",
                                *GoldFeatureEngineer.FEATURE_COLS])
    frame = frame[frame["rr_ratio"] >= 2].sort_values("timestamp").reset_index(drop=True)
    folds, predictions = [], []
    years = sorted(y for y in frame.timestamp.dt.year.unique() if y >= 2022)
    for year in years:
        test_start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        test_end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        prior = frame[(frame.timestamp < test_start) & (frame.exit_time < test_start)]
        test = frame[(frame.timestamp >= test_start) & (frame.timestamp < test_end)]
        if len(prior) < 500 or len(test) < 100:
            continue
        calibration_start = prior.timestamp.iloc[int(len(prior) * .8)]
        train = prior[(prior.timestamp < calibration_start) &
                      (prior.exit_time < calibration_start)]
        calibration = prior[prior.timestamp >= calibration_start]
        X_train, y_train = train[GoldFeatureEngineer.FEATURE_COLS], train.label_profitable.astype(int)
        X_cal, y_cal = calibration[GoldFeatureEngineer.FEATURE_COLS], calibration.label_profitable.astype(int)
        X_test, y_test = test[GoldFeatureEngineer.FEATURE_COLS], test.label_profitable.astype(int)
        model = XGBClassifier(max_depth=3, n_estimators=250, learning_rate=.03,
                              subsample=.8, colsample_bytree=.8, min_child_weight=10,
                              reg_lambda=2, random_state=42, n_jobs=4,
                              objective="binary:logistic", eval_metric="logloss")
        model.fit(X_train, y_train)
        raw_cal = np.clip(model.predict_proba(X_cal)[:, 1], 1e-6, 1 - 1e-6)
        calibrator = LogisticRegression(C=1.0, solver="lbfgs")
        calibrator.fit(np.log(raw_cal / (1 - raw_cal)).reshape(-1, 1), y_cal)
        raw_test = np.clip(model.predict_proba(X_test)[:, 1], 1e-6, 1 - 1e-6)
        probability = calibrator.predict_proba(
            np.log(raw_test / (1 - raw_test)).reshape(-1, 1))[:, 1]
        fold = metrics(y_test, probability)
        fold.update({"year": int(year), "train_rows": len(train),
                     "calibration_rows": len(calibration),
                     "test_start": test.timestamp.min().isoformat(),
                     "test_end": test.timestamp.max().isoformat()})
        folds.append(fold)
        scored = test[["timestamp", "direction", "rr_ratio", "net_return_pct", "label_profitable"]].copy()
        scored["probability"] = probability
        # Candidate-specific break-even probability from known reward/risk,
        # plus a fixed safety margin chosen before observing fold results.
        scored["selected"] = probability >= (1 / (scored.rr_ratio + 1) + .03)
        predictions.append(scored)
    out = pd.concat(predictions, ignore_index=True)
    overall = metrics(out.label_profitable.astype(int), out.probability)
    selected = out[out.selected]
    economic = {"selected_rows": len(selected), "selection_rate": len(selected) / len(out),
                "mean_net_return_pct": float(selected.net_return_pct.mean()),
                "win_rate": float(selected.label_profitable.mean())}
    by_direction = {}
    for direction, group in out.groupby("direction"):
        chosen = group[group.selected]
        by_direction[direction] = {**metrics(group.label_profitable.astype(int), group.probability),
                                   "selected_rows": len(chosen),
                                   "selected_mean_net_return_pct": float(chosen.net_return_pct.mean()) if len(chosen) else None,
                                   "selected_win_rate": float(chosen.label_profitable.mean()) if len(chosen) else None}
    gates = {
        "overall_auc_at_least_0_55": overall["roc_auc"] >= .55,
        "brier_beats_prevalence_baseline": overall["brier"] < overall["brier_baseline"],
        "no_fold_auc_below_0_45": all(fold["roc_auc"] >= .45 for fold in folds),
        "buy_selected_expectancy_positive": by_direction.get("BUY", {}).get("selected_mean_net_return_pct", -1) > 0,
        "sell_selected_expectancy_positive": by_direction.get("SELL", {}).get("selected_mean_net_return_pct", -1) > 0,
    }
    return {"status": "REJECT_MODEL" if not all(gates.values()) else "DEVELOPMENT_GATES_PASS",
            "scope": "DEVELOPMENT_ONLY_NOT_UNTOUCHED", "acceptance_gates": gates,
            "purge_method": "actual label exit must precede calibration/test boundary",
            "features": GoldFeatureEngineer.FEATURE_COLS, "folds": folds,
            "overall_oos": overall, "economic_diagnostic": economic,
            "by_direction": by_direction,
            "limitations": ["2020-2026 influenced feature development; not a final untouched test.",
                            "Candidate returns overlap and do not simulate portfolio capacity.",
                            "Historical and future Dukascopy collection windows can still differ in feed state and regimes.",
                            "Final acceptance requires frozen forward paper evidence."]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
