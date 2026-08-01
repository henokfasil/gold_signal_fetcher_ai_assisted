#!/usr/bin/env python3
"""Non-network integration smoke test for the System C research contracts."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from agent.ml_feature_engineer_gold import GoldFeatureEngineer
from agent.ml_signal_generator import MLSignalFilter
from main_orchestrator import AIAssistedOrchestrator, PaperLedger


def main():
    rng = np.random.default_rng(42)
    index = pd.date_range("2026-01-01", periods=100, freq="h", tz="UTC")
    close = 2400 + rng.normal(0, 1, len(index)).cumsum()
    candles = pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1,
        "close": close, "volume": rng.integers(100, 1000, len(index)),
    }, index=index)
    features = GoldFeatureEngineer.extract_features(candles)
    vector = GoldFeatureEngineer.prepare_for_model(features)[-1]
    assert len(vector) == len(GoldFeatureEngineer.FEATURE_COLS)
    assert np.isfinite(vector).all()

    ml = MLSignalFilter().score_signal({"ml_feature_vector": vector.tolist()})
    assert ml["available"] is False, "an unvalidated local model must not score"

    bullish = {
        "direction": "BUY", "price": 2400, "stop_loss": 2390,
        "take_profit": 2420, "score": 75,
        "symbol": "XAUUSD", "rr_ratio": 2.0,
        "mtf": {"smc": {"struct_4h": "bullish"}},
    }
    normalized = AIAssistedOrchestrator._normalize_signal(bullish)
    assert normalized["direction"] == "BUY"
    assert normalized["stop_loss"] < normalized["entry"] < normalized["take_profit"]

    with tempfile.TemporaryDirectory() as directory:
        ledger = PaperLedger(Path(directory) / "ledger.csv")
        ledger.append({
            "candidate_id": "TEST", "timestamp": "2026-01-01T00:00:00+00:00",
            "pair": "XAUUSD", "direction": "BUY", "entry": 2400,
            "stop_loss": 2390, "take_profit": 2420, "decision": "REJECT",
            "status": "REJECTED", "paper_trading": True,
        })
        loaded = ledger.load()
        assert loaded.iloc[0]["status"] == "REJECTED"
        assert loaded.iloc[0]["paper_trading"] == "True"

    print("PASS: features, validated-model gate, BUY geometry, and audit ledger")


if __name__ == "__main__":
    main()
