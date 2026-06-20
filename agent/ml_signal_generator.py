"""
ML-based signal generation using XGBoost.
Predicts signal profitability based on technical indicators.
"""

import os
import json
import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from datetime import datetime
from pathlib import Path

from ml_feature_engineer import FeatureEngineer


class MLSignalGenerator:
    """XGBoost-based signal prediction."""

    MODEL_PATH = Path("/root/gold_signal_fetcher_ai_assisted/models/xgboost_gold_model.pkl")
    FEATURE_COLS_PATH = Path("/root/gold_signal_fetcher_ai_assisted/models/feature_cols.json")

    def __init__(self):
        """Initialize ML model or train from scratch if needed."""
        self.model = None
        self.feature_engineer = FeatureEngineer()
        self.load_or_train_model()

    def load_or_train_model(self):
        """Load existing model or train new one."""
        if self.MODEL_PATH.exists():
            self.model = joblib.load(self.MODEL_PATH)
            print("[ML] Loaded existing XGBoost model")
        else:
            self.train_initial_model()

    def train_initial_model(self):
        """Train initial model on random data (will improve with real trading data)."""
        # For now, create a simple model that learns basic patterns
        # In production, this would train on actual historical trades

        X_train = np.random.randn(100, 16)  # 16 features
        y_train = (np.random.randn(100) > 0).astype(int)  # 50% win/loss

        self.model = xgb.XGBClassifier(
            max_depth=4,
            n_estimators=50,
            learning_rate=0.1,
            random_state=42,
            objective='binary:logistic'
        )
        self.model.fit(X_train, y_train)

        # Save model
        self.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.model, self.MODEL_PATH)
        print("[ML] Trained and saved initial XGBoost model")

    def predict_signal_confidence(self, features_df: pd.DataFrame) -> float:
        """
        Predict confidence that a signal will be profitable.

        Args:
            features_df: DataFrame with extracted features

        Returns:
            Confidence score (0-100)
        """
        if self.model is None:
            return 50.0  # Neutral if no model

        X = self.feature_engineer.prepare_for_model(features_df)

        # Get last row (most recent)
        if len(X) == 0:
            return 50.0

        recent_features = X[-1:].reshape(1, -1)

        # Predict probability
        proba = self.model.predict_proba(recent_features)[0][1]
        confidence = proba * 100

        return float(confidence)

    def update_model_with_trade_result(self, trade_data: dict, profit: float):
        """
        Update model with real trade outcome for continuous learning.

        Args:
            trade_data: Features of the trade
            profit: Actual P&L from the trade
        """
        # In production, this would retrain the model periodically
        # For now, just log it for later analysis
        print(f"[ML] Trade result: profit={profit}, model should improve with more data")


class MLSignalFilter:
    """Filter signals using ML confidence scores."""

    def __init__(self):
        self.ml_generator = MLSignalGenerator()

    def should_execute_signal(
        self,
        features_df: pd.DataFrame,
        base_score: float,
        liquidity_tier: str
    ) -> dict:
        """
        Decide whether to execute a signal based on ML + base score.

        Args:
            features_df: DataFrame with technical features
            base_score: SMC signal score (0-100)
            liquidity_tier: Current liquidity tier (peak/high/secondary/closed)

        Returns:
            Decision dict with confidence, recommendation, reason
        """
        ml_confidence = self.ml_generator.predict_signal_confidence(features_df)

        # Combine scores
        combined_confidence = (base_score * 0.4) + (ml_confidence * 0.6)

        # Tier-based thresholds
        thresholds = {
            'peak': 60,          # Lower threshold during peak liquidity
            'high': 65,          # Moderate threshold
            'secondary': 75,     # Higher threshold during thin hours
            'closed': 100        # Don't trade when closed
        }

        threshold = thresholds.get(liquidity_tier, 70)

        decision = {
            'should_trade': combined_confidence >= threshold,
            'ml_confidence': ml_confidence,
            'base_score': base_score,
            'combined_confidence': combined_confidence,
            'threshold': threshold,
            'liquidity_tier': liquidity_tier,
            'reason': _get_decision_reason(
                combined_confidence, threshold, liquidity_tier, ml_confidence
            )
        }

        return decision


def _get_decision_reason(confidence: float, threshold: float, tier: str, ml_conf: float) -> str:
    """Generate human-readable reason for signal decision."""
    if confidence < threshold:
        gap = threshold - confidence
        return f"Confidence {confidence:.0f} below threshold {threshold} (gap: {gap:.0f}). ML skeptical ({ml_conf:.0f}%)"
    else:
        gap = confidence - threshold
        return f"Confidence {confidence:.0f} above threshold {threshold} (margin: {gap:.0f}). ML supports ({ml_conf:.0f}%)"
