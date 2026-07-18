import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from agent.claude_analyst import AITradingDecider
from agent.gold_correlations import GoldCorrelationValidator
from agent.ml_signal_generator import MLSignalGenerator


class FakeClaude:
    def __init__(self, should_trade=True, confidence=70):
        self.should_trade = should_trade
        self.confidence = confidence

    def analyze_signal(self, *args, **kwargs):
        return {"available": True, "should_trade": self.should_trade,
                "confidence": self.confidence, "reasoning": "test",
                "risks": [], "model": "test"}


class ResearchPipelineTests(unittest.TestCase):
    def test_missing_model_never_creates_random_model(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch("config.settings.ML_MODEL_PATH", Path(directory) / "missing.pkl"), \
             patch("config.settings.ML_MODEL_METADATA_PATH", Path(directory) / "missing.json"):
            generator = MLSignalGenerator()
            self.assertFalse(generator.available)
            self.assertFalse((Path(directory) / "missing.pkl").exists())

    def test_stale_macro_snapshot_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "macro.json"
            snapshot.write_text(json.dumps({
                "timestamp": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "dxy_return_pct": -0.2, "real_yield_change_bps": -2,
                "vix_return_pct": 1.0,
            }))
            with patch("config.settings.MACRO_SNAPSHOT_PATH", snapshot), \
                 patch("config.settings.SNAPSHOT_MAX_AGE_SECONDS", 900):
                result = GoldCorrelationValidator().validate_signal("BUY")
            self.assertFalse(result["available"])
            self.assertIn("stale", result["reasoning"])

    def test_fresh_macro_snapshot_scores_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "macro.json"
            snapshot.write_text(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "dxy_return_pct": -0.2, "real_yield_change_bps": -2,
                "vix_return_pct": 1.0,
            }))
            with patch("config.settings.MACRO_SNAPSHOT_PATH", snapshot):
                result = GoldCorrelationValidator().validate_signal("BUY")
            self.assertTrue(result["available"])
            self.assertEqual(result["score"], 100)
            self.assertTrue(result["is_confirmed"])

    def test_claude_rejection_is_a_veto(self):
        decider = AITradingDecider()
        decider.claude = FakeClaude(should_trade=False, confidence=90)
        result = decider.decide(
            signal_info={}, market_data={},
            ml_result={"available": True, "confidence": 90, "reason": "test"},
            macro_result={"available": True, "is_blocked": False, "score": 75},
            smc_score=90, liquidity_tier="peak", open_positions=[],
        )
        self.assertFalse(result["should_trade"])
        self.assertIn("AI_REJECTED", result["vetoes"])

    def test_missing_validated_ml_is_a_veto(self):
        decider = AITradingDecider()
        decider.claude = FakeClaude()
        result = decider.decide(
            signal_info={}, market_data={},
            ml_result={"available": False, "confidence": None, "reason": "missing"},
            macro_result={"available": False, "is_blocked": False, "score": None},
            smc_score=90, liquidity_tier="peak", open_positions=[],
        )
        self.assertFalse(result["should_trade"])
        self.assertIn("VALIDATED_ML_UNAVAILABLE", result["vetoes"])


if __name__ == "__main__":
    unittest.main()
