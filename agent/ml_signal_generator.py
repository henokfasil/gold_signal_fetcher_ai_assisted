"""Validated XGBoost inference for gold paper-trading candidates.

Unlike the original implementation, this module never creates a model from
random data.  A model is usable only when it has metadata proving that it was
trained from historical, point-in-time observations.
"""

import json
import logging

import numpy as np

from config import settings
from .ml_feature_engineer_gold import GoldFeatureEngineer

logger = logging.getLogger(__name__)


class MLSignalGenerator:
    """Load and score a versioned gold model, or report it unavailable."""

    def __init__(self):
        self.model = None
        self.metadata = {}
        self.unavailable_reason = "model not loaded"
        self._load_validated_model()

    @property
    def available(self) -> bool:
        return self.model is not None

    def _load_validated_model(self) -> None:
        model_path = settings.ML_MODEL_PATH
        metadata_path = settings.ML_MODEL_METADATA_PATH
        if not model_path.exists() or not metadata_path.exists():
            self.unavailable_reason = "validated model or metadata is missing"
            return

        try:
            metadata = json.loads(metadata_path.read_text())
            if metadata.get("training_data_kind") != "historical_point_in_time":
                self.unavailable_reason = "model metadata does not certify historical point-in-time data"
                return
            if metadata.get("feature_names") != GoldFeatureEngineer.FEATURE_COLS:
                self.unavailable_reason = "model feature schema does not match runtime schema"
                return
            import joblib
            self.model = joblib.load(model_path)
            self.metadata = metadata
            self.unavailable_reason = ""
            logger.info("[ML] Loaded validated model %s", metadata.get("model_version", "unknown"))
        except Exception as exc:
            self.model = None
            self.unavailable_reason = f"model load failed: {exc}"
            logger.warning("[ML] %s", self.unavailable_reason)

    def predict_feature_vector(self, feature_vector) -> dict:
        """Return a scored result with explicit availability and provenance."""
        if not self.available:
            return {
                "available": False,
                "confidence": None,
                "reason": self.unavailable_reason,
                "model_version": None,
            }
        try:
            vector = np.asarray(feature_vector, dtype=float).reshape(1, -1)
            if vector.shape[1] != len(GoldFeatureEngineer.FEATURE_COLS):
                raise ValueError(f"expected {len(GoldFeatureEngineer.FEATURE_COLS)} features")
            confidence = float(self.model.predict_proba(vector)[0][1] * 100)
            return {
                "available": True,
                "confidence": confidence,
                "reason": "validated model inference",
                "model_version": self.metadata.get("model_version"),
            }
        except Exception as exc:
            return {
                "available": False,
                "confidence": None,
                "reason": f"inference failed: {exc}",
                "model_version": self.metadata.get("model_version"),
            }


class MLSignalFilter:
    """Compatibility wrapper used by the orchestrator."""

    def __init__(self):
        self.ml_generator = MLSignalGenerator()

    def score_signal(self, signal: dict) -> dict:
        vector = signal.get("ml_feature_vector")
        if vector is None:
            return {
                "available": False,
                "confidence": None,
                "reason": "signal does not contain a point-in-time feature vector",
                "model_version": None,
            }
        return self.ml_generator.predict_feature_vector(vector)
