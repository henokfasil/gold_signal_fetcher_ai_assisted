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
from agent.ml_feature_engineer_gold import GoldFeatureEngineer
from agent.notifier import Notifier
from agent.smc_gold_scanner import (
    _build_smc_signal, _candles_to_df, _run_from_price_snapshot,
    _run_from_tradingview_snapshot,
    detect_bos_down,
)
from dashboard import (
    get_context_health, get_event_concordance_health,
    get_evidence_integrity, get_feed_health,
    get_shadow_variants,
)
from main_orchestrator import (
    AIAssistedOrchestrator, ForwardContextJournal, ForwardFeatureJournal,
    ForwardOutcomeJournal, ForwardVariantJournal,
)
from agent.gold_context_snapshot import (
    CONTEXT_FEATURES, canonical_snapshot_sha256, load_forward_context_contract,
    load_validated_context_snapshot,
)
from agent.evidence_integrity import (
    build_evidence_integrity_report, drift_report, load_integrity_contract,
)
from agent.event_feature_concordance import (
    DelayedNativeReferenceArchive,
    RuntimeEventSnapshotArchive,
    build_event_feature_concordance_report,
    event_feature_shadow_registration_eligible,
    event_feature_use_authorized,
    load_event_feature_concordance_contract,
)
from agent.forward_event_journal import (
    ForwardEventJournal,
    canonical_snapshot_sha256 as canonical_event_snapshot_sha256,
    load_forward_event_contract,
    snapshot_frames as event_snapshot_frames,
)
from ops.collect_gold_context_snapshot import collect as collect_gold_context
from research.build_historical_dataset import label_candidate, load_ohlcv
from research.export_forward_dataset import export
from research.simulate_portfolio import simulate
from research.analyze_research_evidence import label_uniqueness, weekly_block_bootstrap
from research.relabel_candidate_targets import relabel
from research.benchmark_return_targets import _prepare as prepare_return_target
from research.download_gold_context import combine_sides, load_contract
from research.build_gold_context_dataset import instrument_features
from research.build_execution_state_dataset import (
    EXECUTION_FEATURES, compute_execution_features,
    join_candidate_features, load_contract as load_execution_state_contract,
)
from research.benchmark_execution_state import (
    _stressed_target, _validate_registered_evaluation,
)
from research.benchmark_candidate_generation import (
    _stress_returns as stress_candidate_generation_returns,
    _validate_registered_evaluation as validate_candidate_generation_evaluation,
    load_contract as load_candidate_generation_contract,
    variant_masks as candidate_generation_variant_masks,
)
from research.build_event_candidate_universe import (
    EVENT_FEATURES, current_events as current_event_candidates,
    event_geometry as build_event_geometry,
    load_contract as load_event_universe_contract,
    stable_event_id,
)
from research.benchmark_event_candidate_universe import (
    _stressed_target as stress_event_universe_target,
    _validate_registered_evaluation as validate_event_universe_evaluation,
)


class FakeClaude:
    def __init__(self, should_trade=True, confidence=70):
        self.should_trade = should_trade
        self.confidence = confidence

    def analyze_signal(self, *args, **kwargs):
        return {"available": True, "should_trade": self.should_trade,
                "confidence": self.confidence, "reasoning": "test",
                "risks": [], "model": "test"}


class ResearchPipelineTests(unittest.TestCase):
    @staticmethod
    def _forward_context_fixture(captured_at):
        contract, contract_sha = load_forward_context_contract()
        last_open = captured_at.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        times = [int((last_open - timedelta(hours=199 - i)).timestamp()) for i in range(200)]
        instruments = {}
        for offset, (name, spec) in enumerate(
                contract["source_contract"]["instruments"].items()):
            bars = []
            for index, timestamp in enumerate(times):
                bid = 20.0 + offset * 10 + index * 0.01
                analysis = bid if spec["required_sides"] == ["bid"] else bid + 0.05
                bar = {
                    "time": timestamp,
                    "analysis_open": analysis, "analysis_high": analysis + 0.2,
                    "analysis_low": analysis - 0.2, "analysis_close": analysis + 0.05,
                    "analysis_volume": 10.0,
                    "bid_open": bid, "bid_high": bid + 0.2,
                    "bid_low": bid - 0.2, "bid_close": bid + 0.05,
                    "bid_volume": 10.0,
                }
                if spec["required_sides"] == ["bid", "ask"]:
                    bar.update({
                        "ask_open": bid + 0.1, "ask_high": bid + 0.3,
                        "ask_low": bid - 0.1, "ask_close": bid + 0.15,
                        "ask_volume": 12.0, "spread_open": 0.1, "spread_close": 0.1,
                    })
                bars.append(bar)
            instruments[name] = {
                "symbol": spec["symbol"], "required_sides": spec["required_sides"],
                "analysis_price": spec["analysis_price"], "resolution": "1H",
                "bar_count": 200, "median_cadence_seconds": 3600.0,
                "latest_available_at": datetime.fromtimestamp(
                    times[-1] + 3600, timezone.utc,
                ).isoformat(),
                "bars": bars,
            }
        payload = {
            "schema_version": 1, "experiment_version": contract["experiment_version"],
            "contract_sha256": contract_sha, "provider": "dukascopy-public",
            "captured_at": captured_at.isoformat(),
            "timestamp_semantics": "candle_open_utc; available_at=open+1h; forming candles excluded",
            "paper_research_only": True, "collection_elapsed_seconds": 1.0,
            "instruments": instruments,
        }
        payload["content_sha256"] = canonical_snapshot_sha256(payload)
        xau_last_open = captured_at.replace(second=0, microsecond=0) - timedelta(minutes=15)
        xau_last_open -= timedelta(minutes=xau_last_open.minute % 15)
        xau = {
            "timeframes": {"15M": {"bars": [
                {"time": int((xau_last_open - timedelta(minutes=15 * (199 - i))).timestamp()),
                 "close": 2000 + i * 0.1}
                for i in range(200)
            ]}}
        }
        return payload, xau

    @staticmethod
    def _integrity_fixture(root, rows=1, shifted=False):
        started = datetime(2026, 7, 19, 13, 30, tzinfo=timezone.utc)
        canonical, features, outcomes, variants, contexts = [], [], [], [], []
        for index in range(rows):
            timestamp = (started + timedelta(minutes=15 * index)).isoformat()
            candidate_id = f"{index + 1:012X}"
            direction = "BUY" if index % 2 == 0 else "SELL"
            canonical.append({
                "candidate_id": candidate_id, "timestamp": timestamp,
                "direction": direction, "paper_trading": True,
            })
            feature_value = 100.0 if shifted and index >= rows // 2 else float(index % 5)
            feature_row = {
                "candidate_id": candidate_id, "timestamp": timestamp, "direction": direction,
            }
            feature_row.update({name: feature_value for name in GoldFeatureEngineer.FEATURE_COLS})
            features.append(feature_row)
            outcomes.append({
                "candidate_id": candidate_id, "candidate_time": timestamp,
                "direction": direction, "status": "TRACKING",
                "net_return_pct": "FORBIDDEN_VALUE_MUST_NOT_BE_READ",
            })
            variants.append({
                "candidate_id": candidate_id, "timestamp": timestamp,
                "experiment_version": "forward-pilot-20260719-v3",
                "contract_sha256": ForwardVariantJournal.EXPECTED_CONTRACT_SHA256,
                "direction": direction, "baseline_v1": 1, "paper_trading": True,
            })
            context_row = {
                "candidate_id": candidate_id, "timestamp": timestamp,
                "experiment_version": "forward-context-buy-20260719-v1",
                "contract_sha256": (
                    "97e7d3b4bf2ad00809c00c9e2b6cb6dfd6961b40c70e26da7772b42ef8048b70"
                ),
                "feature_schema_sha256": (
                    "4100208e9e086f5399dedf3f23a7165ed1444bd8994228b5492adc1525c320c6"
                ),
                "direction": direction, "context_available": 1,
                "baseline_context_capture_v1": 1,
                "buy_context_hypothesis_v1": int(direction == "BUY"),
                "paper_trading": True,
            }
            context_row.update({name: feature_value for name in CONTEXT_FEATURES})
            for name in ("dollar_idx", "silver", "volatility_idx", "treasury_bond"):
                context_row[f"ctx_{name}_missing"] = 0
            contexts.append(context_row)
        paths = {
            "ledger_path": root / "ledger.csv", "features_path": root / "features.csv",
            "outcomes_path": root / "outcomes.csv", "variants_path": root / "variants.csv",
            "context_path": root / "context.csv",
        }
        for key, values in (
            ("ledger_path", canonical), ("features_path", features),
            ("outcomes_path", outcomes), ("variants_path", variants),
            ("context_path", contexts),
        ):
            pd.DataFrame(values).to_csv(paths[key], index=False)
        return paths

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

    def test_execution_state_contract_and_feature_schema_are_hash_locked(self):
        contract, digest = load_execution_state_contract()
        self.assertEqual(
            digest,
            "e2931d0f80525ca9f9b16d3f9ab2ca5c710b99f41a70dfd08ac8921adecf2232",
        )
        self.assertEqual(contract["feature_contract"]["registered_features"],
                         EXECUTION_FEATURES)
        self.assertEqual(contract["evaluation_contract"]["primary_target"],
                         "target_1h_net_return_pct")
        self.assertTrue(contract["paper_research_only"])

    @staticmethod
    def _execution_bars(rows=2105):
        timestamp = pd.date_range("2025-01-01", periods=rows, freq="15min", tz="UTC")
        trend = pd.Series(range(rows), dtype=float) * 0.01
        midpoint = 2000.0 + trend + pd.Series(range(rows), dtype=float).mod(17) * 0.002
        spread = 0.18 + pd.Series(range(rows), dtype=float).mod(11) * 0.001
        bid = midpoint - spread / 2
        ask = midpoint + spread / 2
        return pd.DataFrame({
            "timestamp": timestamp,
            "available_at": timestamp + pd.Timedelta(minutes=15),
            "open": midpoint - 0.02,
            "high": midpoint + 0.20,
            "low": midpoint - 0.20,
            "close": midpoint,
            "spread_close": spread,
            "bid_volume": 10.0 + pd.Series(range(rows), dtype=float).mod(13),
            "ask_volume": 11.0 + pd.Series(range(rows), dtype=float).mod(7),
        })

    def test_execution_state_features_do_not_read_future_bars(self):
        raw = self._execution_bars()
        cutoff = 2000
        original = compute_execution_features(raw).iloc[cutoff]
        changed = raw.copy()
        future = changed.index > cutoff
        changed.loc[future, ["open", "high", "low", "close"]] += 1000
        changed.loc[future, "spread_close"] += 20
        changed.loc[future, ["bid_volume", "ask_volume"]] *= 50
        recomputed = compute_execution_features(changed).iloc[cutoff]
        pd.testing.assert_series_equal(original, recomputed)
        computed_features = [
            name for name in EXECUTION_FEATURES if name != "exec_spread_to_atr_1h"
        ]
        self.assertTrue(original[computed_features].notna().all())
        self.assertEqual(
            int(original[[name for name in EXECUTION_FEATURES
                          if name.startswith("exec_window_")]].sum()),
            1,
        )

    def test_execution_state_join_is_exact_and_preserves_registered_order(self):
        raw = self._execution_bars()
        features = compute_execution_features(raw)
        timestamp = features.iloc[2000]["timestamp"]
        candidates = pd.DataFrame({"timestamp": [timestamp], "atr_14": [2.0]})
        joined = join_candidate_features(candidates, features)
        self.assertEqual(list(joined.columns[-len(EXECUTION_FEATURES):]),
                         EXECUTION_FEATURES)
        self.assertAlmostEqual(
            joined.iloc[0]["exec_spread_to_atr_1h"],
            joined.iloc[0]["exec_spread_close_points"] / 2.0,
        )
        missing_time = pd.DataFrame({
            "timestamp": [timestamp + pd.Timedelta(seconds=1)], "atr_14": [2.0],
        })
        missed = join_candidate_features(missing_time, features)
        self.assertTrue(missed["exec_spread_close_points"].isna().all())

    def test_execution_state_slippage_stress_is_two_sided_and_incremental(self):
        frame = pd.DataFrame({
            "target_1h_net_return_pct": [1.0], "executable_entry": [2000.0],
        })
        self.assertAlmostEqual(
            _stressed_target(frame, "target_1h_net_return_pct", 0.10).iloc[0],
            1.0,
        )
        self.assertAlmostEqual(
            _stressed_target(frame, "target_1h_net_return_pct", 0.25).iloc[0],
            1.0 - 0.30 / 2000.0 * 100,
        )

    def test_execution_state_benchmark_refuses_unregistered_sampling(self):
        contract, _ = load_execution_state_contract()
        _validate_registered_evaluation(contract, 500, 42)
        with self.assertRaisesRegex(RuntimeError, "registered bootstrap samples"):
            _validate_registered_evaluation(contract, 499, 42)
        with self.assertRaisesRegex(RuntimeError, "registered seed"):
            _validate_registered_evaluation(contract, 500, 43)

    def test_candidate_generation_contract_is_hash_locked(self):
        contract, digest = load_candidate_generation_contract()
        self.assertEqual(
            digest,
            "484246c8c1c4cc464a7da9059fac9da1235ebf4d5ad90442fbb2c68642130da9",
        )
        self.assertEqual(
            contract["evaluation_contract"]["primary_variant"],
            "sweep_value_retest_primary",
        )
        self.assertTrue(contract["paper_research_only"])
        self.assertFalse(contract["decision_rule"]["paper_approval_authorized"])

    def test_candidate_generation_primary_membership_is_directional_and_causal(self):
        frame = pd.DataFrame([
            {
                "direction": "BUY", "rr_ratio": 2.0, "smc_score": 90,
                "structure_1d_encoded": 1, "structure_1h_encoded": 1,
                "choch_4h_present": 0, "choch_15m_present": 1,
                "liquidity_sweep_1h_present": 1, "price_at_ob": 1,
                "fvg_1h_present": 0, "premium_discount_position": 0.4,
            },
            {
                "direction": "SELL", "rr_ratio": 2.0, "smc_score": 80,
                "structure_1d_encoded": -1, "structure_1h_encoded": -1,
                "choch_4h_present": 1, "choch_15m_present": 0,
                "liquidity_sweep_1h_present": 1, "price_at_ob": 0,
                "fvg_1h_present": 1, "premium_discount_position": 0.6,
            },
            {
                "direction": "BUY", "rr_ratio": 2.0, "smc_score": 90,
                "structure_1d_encoded": 1, "structure_1h_encoded": -1,
                "choch_4h_present": 0, "choch_15m_present": 0,
                "liquidity_sweep_1h_present": 1, "price_at_ob": 1,
                "fvg_1h_present": 1, "premium_discount_position": 0.7,
            },
        ])
        masks = candidate_generation_variant_masks(frame)
        self.assertEqual(masks["sweep_value_retest_primary"].tolist(),
                         [True, True, False])
        self.assertEqual(masks["multi_timeframe_alignment_only"].tolist(),
                         [True, True, False])
        self.assertEqual(masks["smc_score_85_control"].tolist(),
                         [True, False, True])

    def test_candidate_generation_cost_stress_is_two_sided_and_incremental(self):
        contract, _ = load_candidate_generation_contract()
        frame = pd.DataFrame({
            "net_return_pct": [1.0], "executable_entry": [2000.0],
        })
        stressed = stress_candidate_generation_returns(frame, contract)
        self.assertAlmostEqual(
            stressed.iloc[0]["net_return_pct"],
            1.0 - 0.30 / 2000.0 * 100,
        )

    def test_candidate_generation_refuses_unregistered_sampling(self):
        contract, _ = load_candidate_generation_contract()
        validate_candidate_generation_evaluation(contract, 2000, 42)
        with self.assertRaisesRegex(RuntimeError, "bootstrap samples"):
            validate_candidate_generation_evaluation(contract, 1999, 42)
        with self.assertRaisesRegex(RuntimeError, "bootstrap seed"):
            validate_candidate_generation_evaluation(contract, 2000, 43)

    def test_event_universe_contract_and_geometry_schema_are_hash_locked(self):
        contract, digest = load_event_universe_contract()
        self.assertEqual(
            digest,
            "2b57fac00d70b60452a19e14b2daa8d264316016d89fc2425bebf3e05ad40c12",
        )
        self.assertEqual(
            contract["geometry_feature_contract"]["registered_features"],
            EVENT_FEATURES,
        )
        self.assertEqual(len(EVENT_FEATURES), 55)
        self.assertFalse(contract["decision_rule"]["paper_approval_authorized"])

    def test_event_universe_stable_id_deduplicates_repeated_scans(self):
        args = (
            "event-candidate-universe-20260719-v1", "DUKASCOPY:XAUUSD",
            "BUY", "SWEEP_1H", "2026-01-02T10:00:00Z",
        )
        self.assertEqual(stable_event_id(*args), stable_event_id(*args))
        changed = list(args)
        changed[-1] = "2026-01-02T11:00:00Z"
        self.assertNotEqual(stable_event_id(*args), stable_event_id(*changed))

    def test_event_universe_benchmark_refuses_unregistered_sampling(self):
        contract, _ = load_event_universe_contract()
        validate_event_universe_evaluation(contract, 500, 42)
        with self.assertRaisesRegex(RuntimeError, "bootstrap samples"):
            validate_event_universe_evaluation(contract, 499, 42)
        with self.assertRaisesRegex(RuntimeError, "bootstrap seed"):
            validate_event_universe_evaluation(contract, 500, 43)

    def test_event_universe_cost_stress_is_two_sided_and_incremental(self):
        frame = pd.DataFrame({
            "target_4h_net_return_pct": [1.0], "executable_entry": [2000.0],
        })
        stressed = stress_event_universe_target(
            frame, "target_4h_net_return_pct", 0.25,
        )
        self.assertAlmostEqual(stressed.iloc[0], 1.0 - 0.30 / 2000.0 * 100)

    @staticmethod
    def _event_universe_frames():
        as_of = pd.Timestamp("2026-07-23T21:00:00Z")

        def make_frame(freq, end, periods=200):
            index = pd.date_range(end=end, periods=periods, freq=freq, tz="UTC")
            close = 100 + pd.RangeIndex(periods).to_numpy(dtype=float) * 0.01
            frame = pd.DataFrame({
                "open": close - 0.02, "high": close + 0.10,
                "low": close - 0.10, "close": close, "volume": 10.0,
            }, index=index)
            return frame

        frames = {
            "1W": make_frame("7D", as_of - pd.Timedelta(days=2)),
            "1D": make_frame("1D", as_of),
            "4H": make_frame("4h", as_of - pd.Timedelta(hours=1)),
            "1H": make_frame("1h", as_of),
            "15M": make_frame("15min", as_of),
        }
        one_hour = frames["1H"]
        one_hour.iloc[-3, one_hour.columns.get_loc("open")] = 100.0
        one_hour.iloc[-3, one_hour.columns.get_loc("close")] = 100.0
        one_hour.iloc[-3, one_hour.columns.get_loc("high")] = 100.2
        one_hour.iloc[-3, one_hour.columns.get_loc("low")] = 99.8
        one_hour.iloc[-2, one_hour.columns.get_loc("open")] = 100.3
        one_hour.iloc[-2, one_hour.columns.get_loc("close")] = 102.0
        one_hour.iloc[-2, one_hour.columns.get_loc("high")] = 102.1
        one_hour.iloc[-2, one_hour.columns.get_loc("low")] = 100.2
        one_hour.iloc[-1, one_hour.columns.get_loc("open")] = 101.5
        one_hour.iloc[-1, one_hour.columns.get_loc("close")] = 102.5
        one_hour.iloc[-1, one_hour.columns.get_loc("high")] = 103.0
        one_hour.iloc[-1, one_hour.columns.get_loc("low")] = 101.0
        return frames, as_of

    def test_event_universe_emits_only_newly_confirmed_fvg_with_causal_geometry(self):
        frames, as_of = self._event_universe_frames()
        events = current_event_candidates(frames, as_of)
        bullish_fvg = [
            event for event in events
            if event["event_type"] == "FVG_1H" and event["direction"] == "BUY"
        ]
        self.assertEqual(len(bullish_fvg), 1)
        decision = pd.Series({
            "open": 102.0, "high": 102.6, "low": 101.9, "close": 102.5,
            "bid_close": 102.45, "ask_close": 102.55,
        })
        geometry = build_event_geometry(frames, bullish_fvg[0], as_of, decision)
        self.assertEqual(list(geometry), EVENT_FEATURES)
        self.assertEqual(geometry["event_type_fvg_1h"], 1.0)
        self.assertEqual(geometry["event_direction_encoded"], 1.0)
        self.assertEqual(geometry["fvg_present"], 1.0)
        self.assertGreater(geometry["fvg_width_atr_1h"], 0)

    @classmethod
    def _prospective_event_snapshot(cls):
        frames, as_of = cls._event_universe_frames()
        cadences = {
            "1W": 604800, "1D": 86400, "4H": 14400,
            "1H": 3600, "15M": 900,
        }
        payload_frames = {}
        for name, frame in frames.items():
            bars = []
            for timestamp, row in frame.iterrows():
                bars.append({
                    "time": int(timestamp.timestamp()) - cadences[name],
                    "open": float(row["open"]), "high": float(row["high"]),
                    "low": float(row["low"]), "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "bid_open": float(row["open"]) - 0.05,
                    "bid_high": float(row["high"]) - 0.05,
                    "bid_low": float(row["low"]) - 0.05,
                    "bid_close": float(row["close"]) - 0.05,
                    "ask_open": float(row["open"]) + 0.05,
                    "ask_high": float(row["high"]) + 0.05,
                    "ask_low": float(row["low"]) + 0.05,
                    "ask_close": float(row["close"]) + 0.05,
                })
            payload_frames[name] = {
                "resolution": name, "bar_count": len(bars), "bars": bars,
            }
        payload = {
            "schema_version": 2, "provider": "dukascopy-public",
            "symbol": "DUKASCOPY:XAUUSD",
            "captured_at": (as_of + pd.Timedelta(minutes=5)).isoformat(),
            "timestamp_semantics": "candle_open_utc; forming candles excluded",
            "price_components": ["bid", "ask", "midpoint"],
            "paper_research_only": True, "collection_elapsed_seconds": 1.0,
            "timeframes": payload_frames,
        }
        payload["content_sha256"] = canonical_event_snapshot_sha256(payload)
        return payload, as_of

    @staticmethod
    def _expand_reference_snapshot(payload):
        expanded = json.loads(json.dumps(payload))
        cadences = {
            "1W": 604800, "1D": 86400, "4H": 14400,
            "1H": 3600, "15M": 900,
        }
        for name, timeframe in expanded["timeframes"].items():
            first = timeframe["bars"][0]
            older = []
            for offset in range(200, 0, -1):
                bar = dict(first)
                bar["time"] = int(first["time"]) - offset * cadences[name]
                older.append(bar)
            timeframe["bars"] = [*older, *timeframe["bars"]]
            timeframe["bar_count"] = 400
        expanded["content_sha256"] = canonical_event_snapshot_sha256(expanded)
        return expanded

    def test_forward_event_contract_and_journal_are_isolated_and_idempotent(self):
        contract, digest, parent = load_forward_event_contract()
        self.assertEqual(
            digest,
            "bdc69d70bf4aa7e0b340d4d9825ffded7567fd2bf7743881f7fb548490fed7fd",
        )
        self.assertFalse(contract["isolation"]["may_read_or_create_outcomes"])
        self.assertFalse(contract["isolation"]["may_send_telegram"])
        self.assertEqual(
            parent["contract_version"], "event-candidate-universe-20260719-v1",
        )
        payload, as_of = self._prospective_event_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = ForwardEventJournal(
                root / "events.csv", root / "scans.csv",
            )
            first = journal.observe(
                payload, observed_at=as_of.to_pydatetime() + timedelta(minutes=5),
            )
            second = journal.observe(
                payload, observed_at=as_of.to_pydatetime() + timedelta(minutes=20),
            )
            self.assertEqual(first["status"], "PASS")
            self.assertEqual(second["status"], "ALREADY_OBSERVED")
            events = pd.read_csv(root / "events.csv")
            scans = pd.read_csv(root / "scans.csv")
            self.assertTrue(
                ((events["event_type"] == "FVG_1H") &
                 (events["direction"] == "BUY")).any()
            )
            self.assertFalse(events["event_id"].duplicated().any())
            self.assertEqual(len(scans), 1)
            self.assertEqual(scans.iloc[0]["decision_effect"],
                             "NONE_OBSERVATION_ONLY")

    def test_forward_event_journal_rejects_snapshot_hash_drift(self):
        payload, _ = self._prospective_event_snapshot()
        payload["timeframes"]["15M"]["bars"][-1]["close"] += 1
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = ForwardEventJournal(
                root / "events.csv", root / "scans.csv",
            )
            with self.assertRaisesRegex(ValueError, "content hash"):
                journal.observe(payload)

    def test_event_feature_concordance_archives_and_self_replays_fail_closed(self):
        contract, digest, _, _ = load_event_feature_concordance_contract()
        self.assertEqual(
            digest,
            "eb93d931d3e93650633c7010b59618670f8c9815a49033cb1e3698ccc7daab95",
        )
        self.assertFalse(contract["isolation"]["may_read_or_create_outcomes"])
        self.assertFalse(contract["isolation"]["may_score_or_approve_candidate"])
        payload, as_of = self._prospective_event_snapshot()
        shift = timedelta(hours=4)
        for timeframe in payload["timeframes"].values():
            for bar in timeframe["bars"]:
                bar["time"] += int(shift.total_seconds())
        payload["captured_at"] = (
            datetime.fromisoformat(payload["captured_at"]) + shift
        ).isoformat()
        payload["content_sha256"] = canonical_event_snapshot_sha256(payload)
        shifted_as_of = as_of.to_pydatetime() + shift
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events_path, scans_path = root / "events.csv", root / "scans.csv"
            journal = ForwardEventJournal(events_path, scans_path)
            observed = journal.observe(
                payload, observed_at=shifted_as_of + timedelta(minutes=5),
            )
            archive = RuntimeEventSnapshotArchive(root / "archive")
            archived = archive.archive(payload, observed["decision_time"])
            self.assertEqual(archived["status"], "ARCHIVED")
            with patch(
                "agent.event_feature_concordance._load_delayed_native_references",
                side_effect=FileNotFoundError("test replay not collected"),
            ):
                report = build_event_feature_concordance_report(
                    events_path,
                    scans_path,
                    root / "archive",
                    observed_at=shifted_as_of + timedelta(hours=1),
                )
            self.assertEqual(report["status"], "AWAITING INDEPENDENT REPLAY")
            self.assertEqual(report["archived_self_replay_decisions"], 1)
            self.assertEqual(report["archive_or_self_replay_failures"], 0)
            self.assertEqual(report["performance_columns_read"], [])
            self.assertFalse(report["feature_use_authorized"])
            self.assertFalse(report["shadow_registration_eligible"])
            forward_contract, _, _ = load_forward_event_contract()
            replay_frames = event_snapshot_frames(payload, forward_contract)
            with patch(
                "agent.event_feature_concordance._load_delayed_native_references",
                return_value=(
                    [{
                        "snapshot_content_sha256": payload["content_sha256"],
                        "reference_cutoff": pd.Timestamp(
                            "2026-07-25T00:00:00Z"
                        ).to_pydatetime(),
                        "collected_at": pd.Timestamp(
                            "2026-07-25T00:30:00Z"
                        ).to_pydatetime(),
                        "latest_decision": pd.Timestamp(shifted_as_of),
                        "frames": replay_frames,
                    }],
                    {"test_source": "identical point-in-time fixture"},
                ),
            ):
                compared = build_event_feature_concordance_report(
                    events_path,
                    scans_path,
                    root / "archive",
                    observed_at=shifted_as_of + timedelta(hours=1),
                )
            self.assertEqual(compared["status"], "COLLECTING")
            self.assertEqual(compared["compared_decision_times"], 1)
            self.assertGreaterEqual(compared["compared_events"], 1)
            self.assertEqual(
                compared["historical_replay"]["membership_mismatches"], 0,
            )
            self.assertEqual(compared["historical_replay"]["value_mismatches"], 0)

    def test_event_feature_concordance_rejects_tampered_archive_and_stale_pass(self):
        payload, as_of = self._prospective_event_snapshot()
        shift = timedelta(hours=4)
        for timeframe in payload["timeframes"].values():
            for bar in timeframe["bars"]:
                bar["time"] += int(shift.total_seconds())
        payload["captured_at"] = (
            datetime.fromisoformat(payload["captured_at"]) + shift
        ).isoformat()
        payload["content_sha256"] = canonical_event_snapshot_sha256(payload)
        shifted_as_of = as_of.to_pydatetime() + shift
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events_path, scans_path = root / "events.csv", root / "scans.csv"
            journal = ForwardEventJournal(events_path, scans_path)
            observed = journal.observe(
                payload, observed_at=shifted_as_of + timedelta(minutes=5),
            )
            archive = RuntimeEventSnapshotArchive(root / "archive")
            archived = Path(archive.archive(
                payload, observed["decision_time"],
            )["path"])
            corrupted = json.loads(archived.read_text())
            corrupted["timeframes"]["15M"]["bars"][-1]["close"] += 1
            archived.write_text(json.dumps(corrupted))
            with patch(
                "agent.event_feature_concordance._load_delayed_native_references",
                side_effect=FileNotFoundError("test replay not collected"),
            ):
                report = build_event_feature_concordance_report(
                    events_path,
                    scans_path,
                    root / "archive",
                    observed_at=shifted_as_of + timedelta(hours=1),
                )
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["archive_or_self_replay_failures"], 1)

            _, digest, _, _ = load_event_feature_concordance_contract()
            stale_status = root / "status.json"
            stale_status.write_text(json.dumps({
                "monitor_version": "event-feature-concordance-20260723-v1",
                "contract_sha256": digest,
                "generated_at": (
                    shifted_as_of - timedelta(hours=31)
                ).isoformat(),
                "status": "PASS",
                "technical_concordance_passed": True,
                "shadow_registration_eligible": True,
                "feature_use_authorized": False,
                "performance_columns_read": [],
            }))
            authorized, reason = event_feature_shadow_registration_eligible(
                stale_status,
                observed_at=shifted_as_of,
            )
            self.assertFalse(authorized)
            self.assertIn("stale", reason)
            forged_status = root / "forged-status.json"
            forged_status.write_text(json.dumps({
                "monitor_version": "event-feature-concordance-20260723-v1",
                "contract_sha256": digest,
                "generated_at": shifted_as_of.isoformat(),
                "status": "PASS",
                "status_class": "good",
                "paper_research_only": True,
                "technical_concordance_passed": True,
                "shadow_registration_eligible": True,
                "feature_use_authorized": False,
                "authorization_scope":
                    "REGISTER_SEPARATE_PROSPECTIVE_SHADOW_EXPERIMENT_ONLY",
                "performance_columns_read": [],
                "decision_effect": "NONE_OBSERVATION_ONLY",
            }))
            forged_authorized, forged_reason = (
                event_feature_shadow_registration_eligible(
                    forged_status,
                    observed_at=shifted_as_of,
                )
            )
            self.assertFalse(forged_authorized)
            self.assertIn("frozen gates", forged_reason)
            feature_use, feature_reason = event_feature_use_authorized()
            self.assertFalse(feature_use)
            self.assertIn("not authorized", feature_reason)

    def test_delayed_native_reference_is_append_only_per_cutoff(self):
        payload, as_of = self._prospective_event_snapshot()
        payload = self._expand_reference_snapshot(payload)
        shift = timedelta(hours=3)
        for timeframe in payload["timeframes"].values():
            for bar in timeframe["bars"]:
                bar["time"] += int(shift.total_seconds())
        cutoff = as_of.to_pydatetime() + shift
        payload["captured_at"] = cutoff.isoformat()
        payload["content_sha256"] = canonical_event_snapshot_sha256(payload)
        with tempfile.TemporaryDirectory() as directory:
            archive = DelayedNativeReferenceArchive(Path(directory))
            first = archive.store(
                payload,
                collected_at=cutoff + timedelta(minutes=25),
            )
            self.assertEqual(first["status"], "CAPTURED")
            repeated = json.loads(json.dumps(payload))
            repeated["collection_elapsed_seconds"] = 2.0
            repeated["content_sha256"] = canonical_event_snapshot_sha256(repeated)
            second = archive.store(
                repeated,
                collected_at=cutoff + timedelta(minutes=30),
            )
            self.assertEqual(second["status"], "ALREADY_CAPTURED")
            revised = json.loads(json.dumps(payload))
            revised["timeframes"]["15M"]["bars"][-1]["close"] += 0.01
            revised["content_sha256"] = canonical_event_snapshot_sha256(revised)
            with self.assertRaisesRegex(RuntimeError, "changed"):
                archive.store(
                    revised,
                    collected_at=cutoff + timedelta(minutes=35),
                )

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

    def test_portfolio_simulator_handles_empty_variant_fold(self):
        empty = pd.DataFrame(columns=[
            "timestamp", "exit_time", "direction", "entry", "rr_ratio",
            "label_profitable", "label_status", "net_return_pct",
        ])
        events, report = simulate(empty)
        self.assertTrue(events.empty)
        self.assertEqual(report["opened"], 0)
        self.assertEqual(report["return_pct"], 0.0)

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

    def test_fixed_clock_expiry_ignores_post_cutoff_barrier_range(self):
        decision_time = pd.Timestamp("2026-01-02T20:00:00Z")  # Friday
        future = pd.DataFrame([
            {"bid_high": 101, "bid_low": 99, "bid_close": 100,
             "ask_high": 101.5, "ask_low": 99.5, "ask_close": 100.5},
            # First executable close after the Sunday cutoff. Its high crosses
            # TP, but the range is post-expiry and must not create a TP label.
            {"bid_high": 103, "bid_low": 99, "bid_close": 101,
             "ask_high": 103.5, "ask_low": 99.5, "ask_close": 101.5},
        ], index=pd.DatetimeIndex([
            "2026-01-02T20:15:00Z", "2026-01-04T22:15:00Z",
        ]))
        decision = pd.Series({"ask_close": 100.5, "bid_close": 100.0})
        label = label_candidate(
            {"direction": "BUY", "price": 100, "stop_loss": 98, "take_profit": 102},
            future, 48, .35, .1, decision, candidate_time=decision_time,
        )
        self.assertEqual(label["label_status"], "EXPIRY")
        self.assertEqual(label["exit_time"], "2026-01-04T22:15:00+00:00")

    def test_relabel_targets_use_clock_horizons_and_executable_sides(self):
        index = pd.DatetimeIndex([
            "2026-01-02T20:00:00Z", "2026-01-02T20:15:00Z",
            "2026-01-04T22:15:00Z",
        ])
        source = pd.DataFrame({
            "bid_open": [100, 100, 100], "bid_high": [101, 101, 103],
            "bid_low": [99, 99, 99], "bid_close": [100, 100, 101],
            "ask_open": [100.5, 100.5, 100.5], "ask_high": [101.5, 101.5, 103.5],
            "ask_low": [99.5, 99.5, 99.5], "ask_close": [100.5, 100.5, 101.5],
        }, index=index)
        candidates = pd.DataFrame([{
            "timestamp": "2026-01-02T20:00:00Z", "direction": "BUY",
            "entry": 100.25, "stop_loss": 98, "take_profit": 102,
        }])
        result = relabel(candidates, source).iloc[0]
        self.assertEqual(result["label_status"], "EXPIRY")
        self.assertEqual(result["execution_label_source"], "BID_ASK_FIXED_CLOCK")
        self.assertAlmostEqual(result["executable_entry"], 100.5)
        self.assertAlmostEqual(result["label_duration_hours"], 50.25)
        self.assertAlmostEqual(
            result["net_return_pct"], (101 - 100.5 - .2) / 100.5 * 100,
        )

    def test_return_target_purge_time_uses_actual_executable_exit(self):
        from agent.ml_feature_engineer_gold import GoldFeatureEngineer
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.csv"
            row = {
                "timestamp": "2026-01-02T20:00:00Z", "direction": "BUY",
                "target_48h_net_return_pct": 0.1,
                "target_48h_actual_exit_hours": 50.25,
            }
            row.update({name: 0.0 for name in GoldFeatureEngineer.FEATURE_COLS})
            row["rr_ratio"] = 2.0
            pd.DataFrame([row]).to_csv(path, index=False)
            prepared, target = prepare_return_target(path, 48)
            self.assertEqual(target, "target_48h_net_return_pct")
            self.assertEqual(
                prepared.iloc[0]["target_exit_time"],
                pd.Timestamp("2026-01-04T22:15:00Z"),
            )

    def test_gold_context_contract_is_hash_locked(self):
        contract, digest = load_contract()
        self.assertEqual(contract["contract_version"], "gold-context-20260719-v2")
        self.assertEqual(
            digest,
            "a8d2f252ce2b4f06a0828a8b0639088e5fae216b8559134a79e89175e5462e50",
        )

    def test_gold_context_combines_registered_price_sides_without_fabrication(self):
        index = pd.DatetimeIndex(["2026-01-01T00:00:00Z"])
        bid = pd.DataFrame({
            "open": [99.0], "high": [101.0], "low": [98.0],
            "close": [100.0], "volume": [10.0],
        }, index=index)
        ask = pd.DataFrame({
            "open": [100.0], "high": [102.0], "low": [99.0],
            "close": [101.0], "volume": [12.0],
        }, index=index)
        midpoint = combine_sides({"bid": bid, "ask": ask}, ["bid", "ask"])
        self.assertAlmostEqual(midpoint.iloc[0]["analysis_close"], 100.5)
        bid_only = combine_sides({"bid": bid}, ["bid"])
        self.assertAlmostEqual(bid_only.iloc[0]["analysis_close"], 100.0)
        self.assertFalse(any(column.startswith("ask_") for column in bid_only.columns))

    def test_gold_context_join_uses_only_values_available_before_candidate(self):
        context = pd.DataFrame({
            "available_at": pd.to_datetime([
                "2026-01-01T09:00:00Z", "2026-01-01T10:00:00Z",
                "2026-01-01T11:00:00Z",
            ], utc=True),
            "analysis_close": [100.0, 101.0, 999.0],
            "realized_volatility_24h_pct": [0.1, 0.2, 99.0],
        })
        query = pd.Series(pd.to_datetime(["2026-01-01T10:30:00Z"], utc=True))
        result = instrument_features(query, context, "test", 4320).iloc[0]
        self.assertAlmostEqual(result["ctx_test_return_1h_pct"], 1.0)
        self.assertAlmostEqual(result["ctx_test_realized_volatility_24h_pct"], 0.2)
        self.assertEqual(result["ctx_test_staleness_minutes"], 30.0)
        self.assertEqual(result["ctx_test_missing"], 0)

    def test_forward_context_contract_is_hash_locked_and_isolated(self):
        contract, digest = load_forward_context_contract()
        self.assertEqual(
            digest, "97e7d3b4bf2ad00809c00c9e2b6cb6dfd6961b40c70e26da7772b42ef8048b70",
        )
        self.assertFalse(contract["isolation"]["may_score_or_approve_paper_trade"])
        self.assertFalse(contract["isolation"]["may_send_telegram"])

    def test_context_collector_uses_registered_sides_and_complete_bars(self):
        with tempfile.TemporaryDirectory() as directory:
            captured_at = datetime.now(timezone.utc).replace(minute=30, second=0, microsecond=0)
            last_open = captured_at.replace(minute=0) - timedelta(hours=1)
            index = pd.date_range(end=last_open, periods=240, freq="h", tz="UTC")

            def fake_fetch(symbol, start, end, side):
                base = 100.0 + (0.1 if side == "ask" else 0.0)
                values = pd.Series(range(len(index)), index=index, dtype=float) * 0.01 + base
                return pd.DataFrame({
                    "open": values, "high": values + 0.2, "low": values - 0.2,
                    "close": values + 0.05, "volume": 10.0,
                }, index=index)

            output = Path(directory) / "snapshot.json"
            with patch("ops.collect_gold_context_snapshot._fetch", side_effect=fake_fetch) as fetch:
                payload = collect_gold_context(
                    output, Path("config/forward_context_observation_v1.json"),
                    captured_at, use_cache=False,
                )
            self.assertEqual(fetch.call_count, 7)
            self.assertEqual(payload["instruments"]["volatility_idx"]["required_sides"], ["bid"])
            self.assertNotIn("ask_close", payload["instruments"]["volatility_idx"]["bars"][-1])
            self.assertTrue(all(item["bar_count"] == 200
                                for item in payload["instruments"].values()))
            validated, _ = load_validated_context_snapshot(
                output, observed_at=captured_at,
            )
            self.assertEqual(validated["content_sha256"], payload["content_sha256"])

    def test_forward_context_records_both_directions_without_decision_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured_at = datetime.now(timezone.utc).replace(microsecond=0)
            payload, xau = self._forward_context_fixture(captured_at)
            snapshot = root / "context.json"
            snapshot.write_text(json.dumps(payload))
            journal = ForwardContextJournal(root / "rows.csv", snapshot_path=snapshot)
            journal.append("BUY1", captured_at.isoformat(), {"direction": "BUY"}, xau)
            journal.append("SELL1", captured_at.isoformat(), {"direction": "SELL"}, xau)
            rows = pd.read_csv(root / "rows.csv").set_index("candidate_id")
            self.assertEqual(rows.loc["BUY1", "buy_context_hypothesis_v1"], 1)
            self.assertEqual(rows.loc["SELL1", "buy_context_hypothesis_v1"], 0)
            self.assertEqual(rows.loc["SELL1", "baseline_context_capture_v1"], 1)
            self.assertTrue((rows["context_available"] == 1).all())
            self.assertTrue(all(column in rows.columns for column in CONTEXT_FEATURES))
            self.assertIn("NO_SCORE_APPROVAL_CLAUDE_TELEGRAM_OR_BROKER_EFFECT",
                          rows.loc["BUY1", "assignment_note"])

    def test_forward_context_failure_is_journalled_missing_not_raised(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.csv"
            journal = ForwardContextJournal(path, snapshot_path=Path(directory) / "missing.json")
            timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            journal.append("MISSING1", timestamp, {"direction": "BUY"}, {"timeframes": {}})
            row = pd.read_csv(path).iloc[0]
            self.assertEqual(row["context_available"], 0)
            self.assertEqual(row["ctx_silver_missing"], 1)
            self.assertTrue(str(row["context_reason"]).startswith("MISSING:"))

    def test_dashboard_context_panel_reports_health_and_counts_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured_at = datetime.now(timezone.utc).replace(microsecond=0)
            payload, xau = self._forward_context_fixture(captured_at)
            snapshot = root / "context.json"
            snapshot.write_text(json.dumps(payload))
            journal = ForwardContextJournal(root / "rows.csv", snapshot_path=snapshot)
            journal.append("BUY1", captured_at.isoformat(), {"direction": "BUY"}, xau)
            journal.append("SELL1", captured_at.isoformat(), {"direction": "SELL"}, xau)
            health = get_context_health(snapshot, root / "rows.csv")
            self.assertEqual(health["status"], "HEALTHY · COLLECTING")
            self.assertEqual(health["captured_candidates"], 2)
            self.assertEqual(health["buy_hypothesis_candidates"], 1)
            self.assertEqual(health["sell_observations"], 1)
            self.assertNotIn("return", health)

    def test_evidence_integrity_contract_is_hash_locked_and_performance_is_forbidden(self):
        contract, digest = load_integrity_contract()
        self.assertEqual(
            digest, "7aa62452c2cfd8e0c454163d35b82eb0e45612daa04ad2b88cd27d2c93550934",
        )
        self.assertFalse(contract["isolation"]["may_read_outcome_performance_columns"])
        self.assertFalse(contract["isolation"]["may_evaluate_interim_profitability"])

    def test_evidence_integrity_reconciles_complete_candidate_without_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._integrity_fixture(Path(directory))
            original_read_csv = pd.read_csv

            def guarded_read_csv(path, *args, **kwargs):
                if Path(path) == paths["outcomes_path"] and kwargs.get("nrows") is None:
                    forbidden = {"net_return_pct", "label_profitable", "pnl_pct", "pnl_usd"}
                    self.assertFalse(set(kwargs.get("usecols", [])) & forbidden)
                return original_read_csv(path, *args, **kwargs)

            with patch("agent.evidence_integrity.pd.read_csv", side_effect=guarded_read_csv):
                report = build_evidence_integrity_report(**paths)
            self.assertEqual(report["status"], "HEALTHY · DRIFT BASELINE COLLECTING")
            self.assertEqual(report["performance_columns_read"], [])
            self.assertTrue(all(item["status"] == "PASS" for item in report["ledgers"]))

    def test_evidence_integrity_degrades_on_missing_outcome_and_context(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._integrity_fixture(Path(directory))
            pd.DataFrame(columns=[
                "candidate_id", "candidate_time", "direction", "status",
            ]).to_csv(paths["outcomes_path"], index=False)
            context = pd.read_csv(paths["context_path"])
            context.loc[0, "context_available"] = 0
            context.loc[0, "ctx_silver_missing"] = 1
            context.to_csv(paths["context_path"], index=False)
            report = build_evidence_integrity_report(**paths)
            self.assertEqual(report["status"], "DEGRADED")
            by_name = {item["name"]: item for item in report["ledgers"]}
            self.assertEqual(by_name["Shadow outcomes"]["missing"], 1)
            self.assertEqual(by_name["Context observations"]["missing_capture_rows"], 1)

    def test_evidence_integrity_detects_duplicates_orphans_and_timestamp_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._integrity_fixture(Path(directory))
            features = pd.read_csv(paths["features_path"], dtype=str)
            features.loc[0, "timestamp"] = "2026-07-19T13:31:00+00:00"
            duplicate = features.iloc[[0]].copy()
            orphan = features.iloc[[0]].copy()
            orphan.loc[:, "candidate_id"] = "FFFFFFFFFFFF"
            features = pd.concat([features, duplicate, orphan], ignore_index=True)
            features.to_csv(paths["features_path"], index=False)
            report = build_evidence_integrity_report(**paths)
            technical = next(item for item in report["ledgers"]
                             if item["name"] == "Technical features")
            self.assertEqual(report["status"], "DEGRADED")
            self.assertEqual(technical["duplicates"], 1)
            self.assertEqual(technical["orphan"], 1)
            self.assertEqual(technical["identity_mismatches"], 1)

    def test_registered_psi_detects_large_prospective_feature_shift(self):
        contract, _ = load_integrity_contract()
        frame = pd.DataFrame({
            "_timestamp": pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC"),
            "feature": [0.0] * 100 + [10.0] * 100,
        })
        report = drift_report(frame, ["feature"], contract)
        self.assertEqual(report["status"], "ALERT")
        self.assertGreaterEqual(report["max_psi"], 0.25)

    def test_dashboard_evidence_integrity_reports_counts_not_performance(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._integrity_fixture(Path(directory))
            report = get_evidence_integrity(**paths, status_path=Path(directory) / "missing.json")
            self.assertEqual(report["status"], "HEALTHY · DRIFT BASELINE COLLECTING")
            self.assertEqual(report["performance_access"], "NEVER")
            self.assertEqual(report["pilot_candidates"], 1)

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

    def test_forward_feature_journal_repairs_duplicate_rr_header_with_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forward.csv"
            header = ForwardFeatureJournal.LEGACY_COLUMNS
            values = [str(index) for index in range(len(header))]
            path.write_text(",".join(header) + "\n" + ",".join(values) + "\n")
            ForwardFeatureJournal(path)
            repaired_header = path.read_text().splitlines()[0].split(",")
            self.assertEqual(repaired_header, ForwardFeatureJournal.COLUMNS)
            self.assertEqual(repaired_header.count("rr_ratio"), 1)
            self.assertTrue(path.with_suffix(
                path.suffix + ".pre-duplicate-rr-ratio-schema"
            ).exists())
            self.assertEqual(len(pd.read_csv(path)), 1)

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

    def test_forward_runtime_does_not_count_barrier_after_clock_expiry(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch("config.settings.PRICE_DATA_PROVIDER", "dukascopy"):
            journal = ForwardOutcomeJournal(Path(directory) / "outcomes.csv")
            started = datetime(2026, 1, 2, 20, 0, tzinfo=timezone.utc)
            journal.append("ABC", started.isoformat(), {
                "direction": "BUY", "entry": 100, "stop_loss": 98,
                "take_profit": 102, "decision_bid_close": 100,
                "decision_ask_close": 100.5,
                "execution_quote_source": "DUKASCOPY_BID_ASK",
            })
            bar = {
                "high": 103, "low": 99, "close": 101,
                "bid_high": 103, "bid_low": 99, "bid_close": 101,
                "ask_high": 103.5, "ask_low": 99.5, "ask_close": 101.5,
            }
            updated = journal.update(bar, started + timedelta(hours=50, minutes=15))
            row = journal.load().iloc[0]
            self.assertEqual(updated, 1)
            self.assertEqual(row["status"], "EXPIRY")
            self.assertIn("FIRST_EXECUTABLE_CLOSE_AFTER_EXPIRY", row["label_note"])

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

    def test_forward_variant_stops_assigning_after_fixed_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assignments.csv"
            journal = ForwardVariantJournal(path)
            signal = {"direction": "BUY", "rr_ratio": 2.1, "mtf": {"smc": {}}}
            journal.append("LATE", "2027-01-16T23:04:39Z", signal)
            self.assertFalse(path.exists())

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
                "candidate_id": "ABC", "experiment_version": "forward-pilot-20260719-v3",
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
                             "forward-pilot-20260719-v3")
            self.assertEqual(str(joined.iloc[0]["buy_liquidity_v1"]), "1")

    def test_dashboard_shadow_panel_counts_only_eligible_matured_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([
                {"candidate_id": "BUY1", "timestamp": "2026-07-18T21:20:00Z",
                 "experiment_version": "forward-pilot-20260719-v3", "baseline_v1": 1,
                 "buy_liquidity_v1": 1, "min_rr_eligible": 1},
                {"candidate_id": "SELL1", "timestamp": "2026-07-18T21:35:00Z",
                 "experiment_version": "forward-pilot-20260719-v3", "baseline_v1": 1,
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

    def test_claude_confidence_is_not_a_numeric_approval_vote(self):
        decider = AITradingDecider()
        decider.claude = FakeClaude(should_trade=True, confidence=5)
        low_confidence = decider.decide(
            signal_info={}, market_data={},
            ml_result={
                "available": True, "confidence": 70, "reason": "test",
                "selection_threshold_pct": 65,
            },
            macro_result={"available": True, "is_blocked": False, "score": 75},
            smc_score=90, liquidity_tier="peak", open_positions=[],
        )
        decider.claude = FakeClaude(should_trade=True, confidence=99)
        high_confidence = decider.decide(
            signal_info={}, market_data={},
            ml_result={
                "available": True, "confidence": 70, "reason": "test",
                "selection_threshold_pct": 65,
            },
            macro_result={"available": True, "is_blocked": False, "score": 75},
            smc_score=90, liquidity_tier="peak", open_positions=[],
        )
        self.assertTrue(low_confidence["should_trade"])
        self.assertTrue(high_confidence["should_trade"])
        self.assertEqual(low_confidence["combined_confidence"], 70)
        self.assertEqual(high_confidence["combined_confidence"], 70)

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
