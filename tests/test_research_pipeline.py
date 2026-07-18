import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from agent.claude_analyst import AITradingDecider
from agent.gold_correlations import GoldCorrelationValidator
from agent.ml_signal_generator import MLSignalGenerator
from agent.notifier import Notifier
from agent.smc_gold_scanner import (
    _build_smc_signal, _candles_to_df, _run_from_tradingview_snapshot,
    detect_bos_down,
)
from dashboard import get_feed_health
from main_orchestrator import AIAssistedOrchestrator


class FakeClaude:
    def __init__(self, should_trade=True, confidence=70):
        self.should_trade = should_trade
        self.confidence = confidence

    def analyze_signal(self, *args, **kwargs):
        return {"available": True, "should_trade": self.should_trade,
                "confidence": self.confidence, "reasoning": "test",
                "risks": [], "model": "test"}


class ResearchPipelineTests(unittest.TestCase):
    def test_dashboard_reports_healthy_complete_snapshot_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "tv.json"
            log = Path(directory) / "scanner.log"
            bars = [{"time": 1_700_000_000 + i * 900, "open": 2000,
                     "high": 2002, "low": 1998, "close": 2001, "volume": 10}
                    for i in range(200)]
            snapshot.write_text(json.dumps({
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "provider": "tradingview-mcp", "symbol": "OANDA:XAUUSD",
                "timeframes": {name: {"bar_count": 200, "bars": bars}
                               for name in ("1W", "1D", "4H", "1H", "15M")},
            }))
            log.write_text("x [ORCHESTRATOR] Result: NO_CANDIDATE\n")
            with patch("dashboard.is_market_closed", return_value=False):
                health = get_feed_health(snapshot, log)
            self.assertEqual(health["status"], "HEALTHY")
            self.assertEqual(health["last_scan"], "NO_CANDIDATE")
            self.assertEqual(health["market"], "OPEN")

    def test_bearish_bos_and_sell_geometry_are_real_not_relabelled(self):
        frame = pd.DataFrame({
            "open": [10, 9, 8, 8, 7], "high": [11, 10, 9, 9, 8],
            "low": [9, 8, 7, 7.5, 6], "close": [10, 9, 8, 8, 6.5],
        })
        self.assertIsNotNone(detect_bos_down(frame, [1, 3]))
        compat = {name: {"ema20": 100, "ema50": 101, "price": 100, "macd": {}}
                  for name in ("1W", "1D", "4H", "1H")}
        signal = _build_smc_signal(
            symbol="OANDA:XAUUSD", direction="SELL", score=70, price=100,
            ob_4h=None, ob_15m=None, atr_1h=2, tp_level=None, news_reason="clear",
            mtf_compat=compat, smc_data={"struct_4h": "bearish"},
        )
        self.assertLess(signal["take_profit"], signal["price"])
        self.assertGreater(signal["stop_loss"], signal["price"])
        normalized = AIAssistedOrchestrator._normalize_signal(signal)
        self.assertEqual(normalized["direction"], "SELL")

    def test_telegram_paper_signal_is_explicit_and_directional(self):
        notifier = Notifier("token", "chat")
        with patch.object(notifier, "send") as send:
            notifier.send_paper_signal("ABC123", {
                "direction": "SELL", "pair": "OANDA:XAUUSD", "entry": 100,
                "stop_loss": 102, "take_profit": 96, "rr_ratio": 2,
                "score": 70,
            }, {"combined_confidence": 65, "final_reason": "test"})
        message = send.call_args.args[0]
        self.assertIn("SELL", message)
        self.assertIn("PAPER TRADING ONLY", message)

    def test_tradingview_unix_timestamps_are_parsed_as_seconds(self):
        candles = [{"time": 1_700_000_000 + i * 3600, "open": 2000,
                    "high": 2002, "low": 1998, "close": 2001, "volume": 10}
                   for i in range(53)]
        frame = _candles_to_df(candles, min_candles=52)
        self.assertEqual(frame.iloc[0]["timestamp"].year, 2023)

    def test_stale_tradingview_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "tv.json"
            snapshot.write_text(json.dumps({
                "captured_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "symbol": "OANDA:XAUUSD", "timeframes": {},
            }))
            with patch("config.settings.TRADINGVIEW_SNAPSHOT_PATH", snapshot), \
                 patch("config.settings.SNAPSHOT_MAX_AGE_SECONDS", 900), \
                 patch("agent.smc_gold_scanner.check_news_guard", return_value=(False, "clear")):
                self.assertIsNone(_run_from_tradingview_snapshot())

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
