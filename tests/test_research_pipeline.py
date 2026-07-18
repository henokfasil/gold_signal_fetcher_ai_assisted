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
    _build_smc_signal, _candles_to_df, _run_from_price_snapshot,
    _run_from_tradingview_snapshot,
    detect_bos_down,
)
from dashboard import get_feed_health, get_shadow_variants
from main_orchestrator import (
    AIAssistedOrchestrator, ForwardFeatureJournal, ForwardOutcomeJournal,
    ForwardVariantJournal,
)
from research.build_historical_dataset import label_candidate, load_ohlcv
from research.export_forward_dataset import export
from research.simulate_portfolio import simulate
from research.analyze_research_evidence import label_uniqueness, weekly_block_bootstrap


class FakeClaude:
    def __init__(self, should_trade=True, confidence=70):
        self.should_trade = should_trade
        self.confidence = confidence

    def analyze_signal(self, *args, **kwargs):
        return {"available": True, "should_trade": self.should_trade,
                "confidence": self.confidence, "reasoning": "test",
                "risks": [], "model": "test"}


class ResearchPipelineTests(unittest.TestCase):
    def test_label_uniqueness_discounts_overlapping_outcomes(self):
        frame = pd.DataFrame({
            "timestamp": ["2026-01-02T10:00:00Z", "2026-01-02T10:15:00Z"],
            "exit_time": ["2026-01-02T10:30:00Z", "2026-01-02T10:30:00Z"],
        })
        weights, report = label_uniqueness(frame)
        self.assertLess(weights.iloc[1], weights.iloc[0])
        self.assertLess(report["sum_uniqueness"], 2)
        self.assertEqual(report["max_label_concurrency"], 2)

    def test_weekly_bootstrap_is_deterministic(self):
        opened = pd.DataFrame({
            "exit_time": ["2026-01-02T10:00:00Z", "2026-01-09T10:00:00Z"],
            "pnl_usd": [10.0, -5.0],
        })
        first = weekly_block_bootstrap(opened, samples=50, seed=7)
        second = weekly_block_bootstrap(opened, samples=50, seed=7)
        self.assertEqual(first, second)

    def test_portfolio_simulator_enforces_setup_cooldown(self):
        rows = pd.DataFrame([
            {"timestamp": "2026-01-02T10:00:00Z", "exit_time": "2026-01-02T11:00:00Z",
             "direction": "BUY", "entry": 100, "rr_ratio": 2, "label_profitable": 1,
             "label_status": "TP", "net_return_pct": 1},
            {"timestamp": "2026-01-02T10:15:00Z", "exit_time": "2026-01-02T11:15:00Z",
             "direction": "BUY", "entry": 100.05, "rr_ratio": 2, "label_profitable": 1,
             "label_status": "TP", "net_return_pct": 1},
        ])
        events, report = simulate(rows, cooldown_hours=4)
        self.assertEqual(report["opened"], 1)
        self.assertEqual(events.iloc[1]["reason"], "SETUP_COOLDOWN")

    def test_historical_open_timestamp_becomes_visible_at_close(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bars.csv"
            pd.DataFrame([{"time": "2026-01-02T10:00:00Z", "open": 100,
                           "high": 102, "low": 99, "close": 101, "volume": 1}]).to_csv(source, index=False)
            frame = load_ohlcv(source, "open")
            self.assertEqual(frame.index[0].minute, 15)

    def test_historical_same_bar_tp_sl_is_excluded(self):
        future = pd.DataFrame([{"open": 100, "high": 103, "low": 97, "close": 101}],
                              index=pd.DatetimeIndex(["2026-01-02T10:15:00Z"]))
        label = label_candidate({"direction": "BUY", "price": 100,
                                 "stop_loss": 98, "take_profit": 102},
                                future, 48, 0.3, 0.1)
        self.assertEqual(label["label_status"], "AMBIGUOUS_SAME_BAR")
        self.assertTrue(pd.isna(label["label_profitable"]))

    def test_historical_buy_label_uses_ask_entry_and_bid_exit(self):
        future = pd.DataFrame([{"open": 100, "high": 103, "low": 100, "close": 102,
                                "bid_high": 102, "bid_low": 100, "bid_close": 101.8,
                                "ask_high": 102.8, "ask_low": 100.8, "ask_close": 102.6}],
                              index=pd.DatetimeIndex(["2026-01-02T10:15:00Z"]))
        decision = pd.Series({"ask_close": 100.8, "bid_close": 100.0})
        label = label_candidate({"direction": "BUY", "price": 100,
                                 "stop_loss": 98, "take_profit": 102},
                                future, 48, .83, .1, decision)
        self.assertEqual(label["label_status"], "TP")
        self.assertEqual(label["execution_label_source"], "BID_ASK")
        self.assertAlmostEqual(label["net_return_pct"], (102 - 100.8 - .2) / 100.8 * 100)

    def test_forward_journal_preserves_exact_candidate_features(self):
        from agent.ml_feature_engineer_gold import GoldFeatureEngineer
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forward.csv"
            journal = ForwardFeatureJournal(path)
            names = GoldFeatureEngineer.FEATURE_COLS
            signal = {"pair": "OANDA:XAUUSD", "direction": "SELL", "entry": 100,
                      "stop_loss": 102, "take_profit": 96, "rr_ratio": 2,
                      "score": 70, "ml_feature_names": names,
                      "ml_feature_vector": list(range(len(names)))}
            journal.append("ABC", "2026-01-02T10:15:00+00:00", signal)
            row = pd.read_csv(path).iloc[0]
            self.assertEqual(row["candidate_id"], "ABC")
            self.assertEqual(row["direction_encoded"], names.index("direction_encoded"))

    def test_rejected_candidate_can_receive_shadow_outcome(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch("config.settings.PRICE_DATA_PROVIDER", "tradingview"):
            journal = ForwardOutcomeJournal(Path(directory) / "outcomes.csv")
            signal = {"direction": "SELL", "entry": 100, "stop_loss": 102,
                      "take_profit": 96}
            started = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)
            journal.append("ABC", started.isoformat(), signal)
            updated = journal.update({"high": 101, "low": 95, "close": 97},
                                     started + timedelta(minutes=15))
            row = journal.load().iloc[0]
            self.assertEqual(updated, 1)
            self.assertEqual(row["status"], "TP")
            self.assertEqual(row["label_profitable"], "1")

    def test_forward_buy_outcome_uses_ask_entry_and_bid_bar(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch("config.settings.PRICE_DATA_PROVIDER", "dukascopy"):
            journal = ForwardOutcomeJournal(Path(directory) / "outcomes.csv")
            signal = {
                "direction": "BUY", "entry": 100, "stop_loss": 98,
                "take_profit": 102, "decision_bid_close": 100.0,
                "decision_ask_close": 100.5,
                "execution_quote_source": "DUKASCOPY_BID_ASK",
            }
            started = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)
            journal.append("ABC", started.isoformat(), signal)
            not_executable = {
                "high": 103, "low": 99, "close": 102,
                "bid_high": 101.9, "bid_low": 99, "bid_close": 101.8,
                "ask_high": 102.5, "ask_low": 99.5, "ask_close": 102.3,
            }
            self.assertEqual(journal.update(not_executable, started + timedelta(minutes=15)), 0)
            executable = dict(not_executable, bid_high=102.0)
            self.assertEqual(journal.update(executable, started + timedelta(minutes=30)), 1)
            row = journal.load().iloc[0]
            self.assertEqual(row["status"], "TP")
            self.assertAlmostEqual(float(row["entry"]), 100.5)
            expected = (102 - 100.5 - 0.2) / 100.5 * 100
            self.assertAlmostEqual(float(row["net_return_pct"]), expected, places=7)
            self.assertIn("BID_ASK", row["label_note"])

    def test_forward_variant_membership_is_point_in_time_and_directional(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assignments.csv"
            journal = ForwardVariantJournal(path)
            buy = {"direction": "BUY", "rr_ratio": 2.1,
                   "mtf": {"smc": {"liquidity_sweep_1h": {"level": 100}}}}
            sell = {"direction": "SELL", "rr_ratio": 1.9,
                    "mtf": {"smc": {"liquidity_sweep_1h": {"level": 105}}}}
            journal.append("BUY1", "2026-07-18T21:20:00+00:00", buy)
            journal.append("SELL1", "2026-07-18T21:35:00+00:00", sell)
            rows = pd.read_csv(path).set_index("candidate_id")
            self.assertEqual(rows.loc["BUY1", "baseline_v1"], 1)
            self.assertEqual(rows.loc["BUY1", "buy_liquidity_v1"], 1)
            self.assertEqual(rows.loc["SELL1", "baseline_v1"], 1)
            self.assertEqual(rows.loc["SELL1", "buy_liquidity_v1"], 0)
            self.assertEqual(rows.loc["SELL1", "min_rr_eligible"], 0)
            self.assertEqual(rows.loc["BUY1", "strategy_config_version"], "3.0-research")
            self.assertEqual(rows.loc["BUY1", "ml_model_version"], "UNAVAILABLE")
            self.assertIn("NO_APPROVAL_OR_TELEGRAM_EFFECT",
                          rows.loc["BUY1", "assignment_note"])

    def test_forward_variant_contract_is_hash_locked(self):
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "changed.json"
            contract.write_text('{"schema_version": 1, "paper_only": true}')
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                ForwardVariantJournal(Path(directory) / "rows.csv", contract)

    def test_forward_variant_refuses_runtime_slippage_drift(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch("config.settings.RESEARCH_SLIPPAGE_POINTS", 0.50):
            with self.assertRaisesRegex(RuntimeError, "runtime settings"):
                ForwardVariantJournal(Path(directory) / "rows.csv")

    def test_forward_export_requires_and_preserves_frozen_assignment(self):
        from agent.ml_feature_engineer_gold import GoldFeatureEngineer
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feature_row = {"candidate_id": "ABC", "timestamp": "2026-07-18T21:20:00Z"}
            feature_row.update({name: 0.0 for name in GoldFeatureEngineer.FEATURE_COLS})
            pd.DataFrame([feature_row]).to_csv(root / "features.csv", index=False)
            pd.DataFrame([{
                "candidate_id": "ABC", "experiment_version": "forward-pilot-20260719-v2",
                "contract_sha256": ForwardVariantJournal.EXPECTED_CONTRACT_SHA256,
                "baseline_v1": 1, "buy_liquidity_v1": 1, "min_rr_eligible": 1,
                "liquidity_sweep_1h_present": 1, "paper_trading": True,
                "strategy_config_version": "3.0-research",
                "feature_schema_sha256": "8e567c3aa764cc894bf1892e6ceae8011aa4933b69a23f4e80bfaa996063e965",
                "ml_model_version": "UNAVAILABLE", "claude_model": "UNAVAILABLE",
                "claude_prompt_version": "claude-review-v1",
                "assignment_note": "SHADOW_RESEARCH_ONLY_NO_APPROVAL_OR_TELEGRAM_EFFECT",
            }]).to_csv(root / "assignments.csv", index=False)
            pd.DataFrame([{
                "candidate_id": "ABC", "status": "TP", "exit_time": "2026-07-19T01:00:00Z",
                "exit_price": 102, "net_return_pct": 0.5, "label_note": "BARRIER_OBSERVED_15M",
                "label_profitable": 1,
            }]).to_csv(root / "outcomes.csv", index=False)
            joined = export(root / "features.csv", root / "outcomes.csv",
                            root / "assignments.csv")
            self.assertEqual(len(joined), 1)
            self.assertEqual(joined.iloc[0]["experiment_version"],
                             "forward-pilot-20260719-v2")
            self.assertEqual(str(joined.iloc[0]["buy_liquidity_v1"]), "1")

    def test_dashboard_shadow_panel_counts_only_eligible_matured_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([
                {"candidate_id": "BUY1", "timestamp": "2026-07-18T21:20:00Z",
                 "experiment_version": "forward-pilot-20260719-v2", "baseline_v1": 1,
                 "buy_liquidity_v1": 1, "min_rr_eligible": 1},
                {"candidate_id": "SELL1", "timestamp": "2026-07-18T21:35:00Z",
                 "experiment_version": "forward-pilot-20260719-v2", "baseline_v1": 1,
                 "buy_liquidity_v1": 0, "min_rr_eligible": 1},
            ]).to_csv(root / "assignments.csv", index=False)
            pd.DataFrame([
                {"candidate_id": "BUY1", "status": "TP"},
                {"candidate_id": "SELL1", "status": "TRACKING"},
            ]).to_csv(root / "outcomes.csv", index=False)
            report = get_shadow_variants(root / "assignments.csv", root / "outcomes.csv")
            self.assertEqual(report["baseline_assigned"], 2)
            self.assertEqual(report["baseline_matured"], 1)
            self.assertEqual(report["liquidity_assigned"], 1)
            self.assertEqual(report["liquidity_matured"], 1)
            self.assertEqual(report["effect"], "None — research only")

    def test_dashboard_reports_healthy_complete_snapshot_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "tv.json"
            log = Path(directory) / "scanner.log"
            cadences = {"1W": 604800, "1D": 86400, "4H": 14400,
                        "1H": 3600, "15M": 900}
            last_time = int(datetime.now(timezone.utc).timestamp() // 900 * 900) - 900
            frames = {}
            for name, cadence in cadences.items():
                bars = [{"time": last_time - (199 - i) * cadence, "open": 2000,
                         "high": 2002, "low": 1998, "close": 2001, "volume": 10}
                        for i in range(200)]
                frames[name] = {"resolution": name, "bar_count": 200, "bars": bars}
            snapshot.write_text(json.dumps({
                "schema_version": 2,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "provider": "tradingview-mcp", "symbol": "OANDA:XAUUSD",
                "timeframes": frames,
            }))
            log.write_text("x [ORCHESTRATOR] Result: NO_CANDIDATE\n")
            with patch("config.settings.PRICE_DATA_PROVIDER", "tradingview"), \
                 patch("dashboard.is_market_closed", return_value=False):
                health = get_feed_health(snapshot, log)
            self.assertEqual(health["status"], "HEALTHY")
            self.assertEqual(health["last_scan"], "NO_CANDIDATE")
            self.assertEqual(health["market"], "OPEN")

    def test_dukascopy_snapshot_requires_and_preserves_bid_ask_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "dukascopy.json"
            cadences = {"1W": 604800, "1D": 86400, "4H": 14400,
                        "1H": 3600, "15M": 900}
            last_time = int(datetime.now(timezone.utc).timestamp() // 900 * 900) - 900
            frames = {}
            for offset, (name, cadence) in enumerate(cadences.items()):
                bars = []
                for i in range(200):
                    close = 2001 + offset * 0.01
                    bars.append({
                        "time": last_time - (199 - i) * cadence,
                        "open": 2000 + offset * 0.01, "high": 2002 + offset * 0.01,
                        "low": 1998 + offset * 0.01, "close": close, "volume": 10,
                        "bid_open": 1999.9, "bid_high": 2001.9,
                        "bid_low": 1997.9, "bid_close": close - 0.1,
                        "ask_open": 2000.1, "ask_high": 2002.1,
                        "ask_low": 1998.1, "ask_close": close + 0.1,
                    })
                frames[name] = {"resolution": name, "bar_count": 200, "bars": bars}
            snapshot.write_text(json.dumps({
                "schema_version": 2,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "provider": "dukascopy-public", "symbol": "DUKASCOPY:XAUUSD",
                "timeframes": frames,
            }))
            with patch("config.settings.PRICE_DATA_PROVIDER", "dukascopy"), \
                 patch("config.settings.DUKASCOPY_SNAPSHOT_PATH", snapshot), \
                 patch("dashboard.is_market_closed", return_value=False):
                health = get_feed_health(snapshot, Path(directory) / "missing.log")
            self.assertEqual(health["status"], "HEALTHY")
            self.assertTrue(all(frame["quotes"] for frame in health["frames"].values()))

            fake_signal = {"direction": "BUY"}
            with patch("config.settings.PRICE_DATA_PROVIDER", "dukascopy"), \
                 patch("config.settings.DUKASCOPY_SNAPSHOT_PATH", snapshot), \
                 patch("agent.smc_gold_scanner.check_news_guard", return_value=(False, "clear")), \
                 patch("agent.smc_gold_scanner._run_smc_analysis", return_value=fake_signal):
                result = _run_from_price_snapshot()
            self.assertEqual(result["execution_quote_source"], "DUKASCOPY_BID_ASK")
            self.assertAlmostEqual(result["decision_ask_close"],
                                   frames["15M"]["bars"][-1]["ask_close"])

    def test_duplicate_15m_payloads_cannot_claim_multitimeframe_health(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "tv.json"
            last_time = int(datetime.now(timezone.utc).timestamp() // 900 * 900)
            bars = [{"time": last_time - (199 - i) * 900, "open": 2000,
                     "high": 2002, "low": 1998, "close": 2001, "volume": 10}
                    for i in range(200)]
            snapshot.write_text(json.dumps({
                "schema_version": 2,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "provider": "tradingview-mcp", "symbol": "OANDA:XAUUSD",
                "timeframes": {name: {"resolution": name, "bars": bars}
                               for name in ("1W", "1D", "4H", "1H", "15M")},
            }))
            with patch("config.settings.PRICE_DATA_PROVIDER", "tradingview"), \
                 patch("dashboard.is_market_closed", return_value=False):
                health = get_feed_health(snapshot, Path(directory) / "missing.log")
            self.assertEqual(health["status"], "DEGRADED")
            self.assertEqual(health["integrity"], "FAIL")
            self.assertFalse(health["frames"]["1W"]["cadence"])
            with patch("config.settings.PRICE_DATA_PROVIDER", "tradingview"), \
                 patch("config.settings.TRADINGVIEW_SNAPSHOT_PATH", snapshot), \
                 patch("agent.smc_gold_scanner.check_news_guard", return_value=(False, "clear")):
                self.assertIsNone(_run_from_tradingview_snapshot())

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
            with patch("config.settings.PRICE_DATA_PROVIDER", "tradingview"), \
                 patch("config.settings.TRADINGVIEW_SNAPSHOT_PATH", snapshot), \
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
