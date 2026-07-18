"""Train a research XGBoost model from historical point-in-time observations.

This command intentionally has no synthetic-data fallback.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from agent.ml_feature_engineer_gold import GoldFeatureEngineer
from config import settings


def train(dataset_path: Path, label_column: str = "label_profitable") -> dict:
    import joblib
    import xgboost as xgb
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    frame = pd.read_csv(dataset_path)
    required = ["timestamp", label_column, *GoldFeatureEngineer.FEATURE_COLS]
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError(f"dataset is missing columns: {', '.join(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame[label_column] = pd.to_numeric(frame[label_column], errors="coerce")
    frame = frame.dropna(subset=[label_column, *GoldFeatureEngineer.FEATURE_COLS])
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    if len(frame) < 500:
        raise ValueError("at least 500 historical observations are required")

    split = int(len(frame) * 0.8)
    train_frame, test_frame = frame.iloc[:split], frame.iloc[split:]
    if train_frame["timestamp"].max() >= test_frame["timestamp"].min():
        raise ValueError("chronological split overlap detected")
    X_train = train_frame[GoldFeatureEngineer.FEATURE_COLS].astype(float)
    y_train = train_frame[label_column].astype(int)
    X_test = test_frame[GoldFeatureEngineer.FEATURE_COLS].astype(float)
    y_test = test_frame[label_column].astype(int)
    if set(y_train.unique()) != {0, 1} or set(y_test.unique()) != {0, 1}:
        raise ValueError("both chronological partitions must contain labels 0 and 1")

    model = xgb.XGBClassifier(
        max_depth=3, n_estimators=200, learning_rate=0.03, subsample=0.8,
        colsample_bytree=0.8, random_state=42, objective="binary:logistic",
        eval_metric="logloss", n_jobs=1,
    )
    model.fit(X_train, y_train)
    probabilities = model.predict_proba(X_test)[:, 1]
    metrics = {
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "brier_score": float(brier_score_loss(y_test, probabilities)),
        "log_loss": float(log_loss(y_test, probabilities)),
    }
    metadata = {
        "model_version": datetime.now(timezone.utc).strftime("gold-xgb-%Y%m%dT%H%M%SZ"),
        "training_data_kind": "historical_point_in_time",
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "feature_names": GoldFeatureEngineer.FEATURE_COLS,
        "label_column": label_column,
        "train_rows": len(train_frame), "test_rows": len(test_frame),
        "train_end": train_frame["timestamp"].max().isoformat(),
        "test_start": test_frame["timestamp"].min().isoformat(),
        "test_end": test_frame["timestamp"].max().isoformat(),
        "metrics": metrics,
        "test_metrics_by_direction": {},
        "warning": "Research model. Chronological holdout is not a final untouched test or CPCV.",
    }
    if "direction" in test_frame.columns:
        for direction, subset in test_frame.groupby("direction"):
            labels = subset[label_column].astype(int)
            if len(subset) >= 20 and labels.nunique() == 2:
                probs = model.predict_proba(subset[GoldFeatureEngineer.FEATURE_COLS].astype(float))[:, 1]
                metadata["test_metrics_by_direction"][str(direction)] = {
                    "rows": len(subset), "roc_auc": float(roc_auc_score(labels, probs)),
                    "brier_score": float(brier_score_loss(labels, probs)),
                    "log_loss": float(log_loss(labels, probs)),
                }
    settings.ML_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, settings.ML_MODEL_PATH)
    settings.ML_MODEL_METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path, help="point-in-time feature/label CSV")
    parser.add_argument("--label-column", default="label_profitable")
    args = parser.parse_args()
    print(json.dumps(train(args.dataset, args.label_column), indent=2))


if __name__ == "__main__":
    main()
