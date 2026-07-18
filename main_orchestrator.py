"""Research-grade paper-trading orchestrator for System C.

Every candidate is auditable. Missing ML, macro, or LLM evidence is explicit;
no random model or fabricated neutral score can approve a paper trade.
"""

import csv
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd

from config import settings
from agent.claude_analyst import AITradingDecider
from agent.gold_correlations import GoldCorrelationValidator
from agent.liquidity_manager import get_session_description, is_market_closed
from agent.ml_signal_generator import MLSignalFilter
from agent.ml_feature_engineer_gold import GoldFeatureEngineer
from agent.notifier import Notifier
from agent.smc_gold_scanner import run_gold_scanner

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

LEDGER_COLUMNS = [
    "candidate_id", "timestamp", "pair", "direction", "entry", "stop_loss",
    "take_profit", "rr_ratio", "smc_score", "ml_available", "ml_confidence",
    "ml_model_version", "claude_available", "claude_confidence",
    "macro_available", "macro_score", "combined_confidence", "threshold",
    "decision", "decision_reason", "status", "exit_price", "exit_time",
    "exit_reason", "pnl_pct", "pnl_usd", "notional_usd", "paper_trading",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


class PaperLedger:
    def __init__(self, path=settings.PAPER_TRADES_CSV):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> pd.DataFrame:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return pd.DataFrame(columns=LEDGER_COLUMNS)
        frame = pd.read_csv(self.path, dtype=str).fillna("")
        for column in LEDGER_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""
        return frame[LEDGER_COLUMNS]

    def save(self, frame: pd.DataFrame) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        frame[LEDGER_COLUMNS].to_csv(temp, index=False)
        temp.replace(self.path)

    def append(self, row: dict) -> None:
        file_exists = self.path.exists() and self.path.stat().st_size > 0
        with self.path.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=LEDGER_COLUMNS, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerow({column: row.get(column, "") for column in LEDGER_COLUMNS})

    def open_positions(self) -> list:
        frame = self.load()
        return frame[frame["status"] == "OPEN"].to_dict("records")

    def is_duplicate(self, signal: dict, minutes: int = 240) -> bool:
        frame = self.load()
        if frame.empty:
            return False
        cutoff = utc_now() - timedelta(minutes=minutes)
        entry = float(signal["entry"])
        for _, row in frame.tail(500).iterrows():
            try:
                if parse_utc(row["timestamp"]) < cutoff or row["direction"] != signal["direction"]:
                    continue
                if abs(float(row["entry"]) - entry) <= entry * 0.001:
                    return True
            except (ValueError, TypeError):
                continue
        return False

    def realized_pnl(self, since: datetime) -> float:
        frame = self.load()
        total = 0.0
        for _, row in frame.iterrows():
            try:
                if row["status"] in {"WIN", "LOSS", "EXPIRED"} and parse_utc(row["exit_time"]) >= since:
                    total += float(row["pnl_pct"] or 0)
            except (ValueError, TypeError):
                continue
        return total

    def realized_pnl_usd(self, since: datetime) -> float:
        """Realized paper dollars, used for account-level loss caps."""
        frame = self.load()
        total = 0.0
        for _, row in frame.iterrows():
            try:
                if row["status"] in {"WIN", "LOSS", "EXPIRED"} and parse_utc(row["exit_time"]) >= since:
                    total += float(row["pnl_usd"] or 0)
            except (ValueError, TypeError):
                continue
        return total


class ForwardFeatureJournal:
    """Append-only point-in-time features, joined to outcomes by candidate ID."""

    COLUMNS = ["candidate_id", "timestamp", "pair", "direction", "entry",
               "stop_loss", "take_profit", "rr_ratio", "smc_score",
               *GoldFeatureEngineer.FEATURE_COLS]

    def __init__(self, path=settings.FORWARD_FEATURES_CSV):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, candidate_id: str, timestamp: str, signal: dict) -> None:
        vector = signal.get("ml_feature_vector")
        names = signal.get("ml_feature_names")
        if names != GoldFeatureEngineer.FEATURE_COLS or vector is None or len(vector) != len(names):
            logger.warning("Forward features unavailable for candidate %s", candidate_id)
            return
        row = {
            "candidate_id": candidate_id, "timestamp": timestamp,
            "pair": signal["pair"], "direction": signal["direction"],
            "entry": signal["entry"], "stop_loss": signal["stop_loss"],
            "take_profit": signal["take_profit"], "rr_ratio": signal.get("rr_ratio"),
            "smc_score": signal.get("score"), **dict(zip(names, vector)),
        }
        exists = self.path.exists() and self.path.stat().st_size > 0
        with self.path.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.COLUMNS, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            writer.writerow(row)


class ForwardOutcomeJournal:
    """Shadow-label every candidate; this never approves or executes a trade."""

    COLUMNS = ["candidate_id", "candidate_time", "direction", "entry", "stop_loss",
               "take_profit", "status", "exit_time", "exit_price", "label_profitable",
               "net_return_pct", "label_note"]

    def __init__(self, path=settings.FORWARD_OUTCOMES_CSV):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> pd.DataFrame:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return pd.DataFrame(columns=self.COLUMNS)
        frame = pd.read_csv(self.path, dtype=str).fillna("")
        for column in self.COLUMNS:
            if column not in frame:
                frame[column] = ""
        return frame[self.COLUMNS]

    def append(self, candidate_id: str, timestamp: str, signal: dict) -> None:
        exists = self.path.exists() and self.path.stat().st_size > 0
        with self.path.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.COLUMNS)
            if not exists:
                writer.writeheader()
            writer.writerow({"candidate_id": candidate_id, "candidate_time": timestamp,
                             "direction": signal["direction"], "entry": signal["entry"],
                             "stop_loss": signal["stop_loss"], "take_profit": signal["take_profit"],
                             "status": "TRACKING", "label_note": "SHADOW_RESEARCH_ONLY"})

    def update(self, bar: dict, bar_time: datetime) -> int:
        frame = self.load()
        tracking = frame[frame["status"] == "TRACKING"]
        if tracking.empty:
            return 0
        high, low, close = map(float, (bar["high"], bar["low"], bar["close"]))
        cost = settings.RESEARCH_SPREAD_POINTS + 2 * settings.RESEARCH_SLIPPAGE_POINTS
        updated = 0
        for index, row in tracking.iterrows():
            candidate_time = parse_utc(row["candidate_time"])
            if bar_time <= candidate_time:
                continue
            direction = row["direction"]
            entry, stop, target = map(float, (row["entry"], row["stop_loss"], row["take_profit"]))
            hit_tp = high >= target if direction == "BUY" else low <= target
            hit_sl = low <= stop if direction == "BUY" else high >= stop
            status = exit_price = note = None
            if hit_tp and hit_sl:
                status, note = "AMBIGUOUS", "TP_AND_SL_IN_SAME_15M_BAR"
            elif hit_tp:
                status, exit_price, note = "TP", target, "BARRIER_OBSERVED_15M"
            elif hit_sl:
                status, exit_price, note = "SL", stop, "BARRIER_OBSERVED_15M"
            elif bar_time - candidate_time >= timedelta(hours=settings.TRADE_EXPIRY_HOURS):
                status, exit_price, note = "EXPIRY", close, "TIME_EXPIRY_15M_CLOSE"
            if status is None:
                continue
            frame.at[index, "status"] = status
            frame.at[index, "exit_time"] = bar_time.isoformat()
            frame.at[index, "label_note"] = note
            if exit_price is not None:
                gross = exit_price - entry if direction == "BUY" else entry - exit_price
                net = gross - cost
                frame.at[index, "exit_price"] = f"{exit_price:.5f}"
                frame.at[index, "net_return_pct"] = f"{net / entry * 100:.8f}"
                frame.at[index, "label_profitable"] = "1" if net > 0 else "0"
            updated += 1
        if updated:
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            frame.to_csv(temp, index=False)
            temp.replace(self.path)
        return updated


class ForwardVariantJournal:
    """Append-only membership in the hash-locked prospective shadow test."""

    EXPECTED_CONTRACT_SHA256 = "f2a9e6dd7880b10195fc3f2e0367ed9561e5354fa96af25c732887805287fff0"
    COLUMNS = [
        "candidate_id", "timestamp", "experiment_version", "contract_sha256",
        "strategy_config_version", "feature_schema_sha256", "ml_model_version",
        "claude_model", "claude_prompt_version",
        "direction", "baseline_v1", "buy_liquidity_v1", "min_rr_eligible",
        "liquidity_sweep_1h_present", "rr_ratio", "paper_trading", "assignment_note",
    ]

    def __init__(self, path=settings.FORWARD_VARIANT_ASSIGNMENTS_CSV,
                 contract_path=settings.RESEARCH_VARIANT_CONFIG):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw_contract = contract_path.read_bytes()
            digest = hashlib.sha256(raw_contract).hexdigest()
            contract = json.loads(raw_contract)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"shadow experiment contract unavailable: {exc}") from exc
        if digest != self.EXPECTED_CONTRACT_SHA256:
            raise RuntimeError("shadow experiment contract hash mismatch; create a new version")
        required_variants = {"baseline_v1", "buy_liquidity_v1"}
        feature_schema = json.dumps(
            GoldFeatureEngineer.FEATURE_COLS, separators=(",", ":"), ensure_ascii=True
        ).encode()
        feature_schema_sha256 = hashlib.sha256(feature_schema).hexdigest()
        common = contract.get("common_evaluation", {})
        runtime_contract_matches = (
            settings.PRICE_DATA_PROVIDER == "tradingview" and
            int(common.get("outcome_expiry_hours", -1)) == settings.TRADE_EXPIRY_HOURS and
            float(common.get("spread_points", -1)) == settings.RESEARCH_SPREAD_POINTS and
            float(common.get("slippage_points_per_side", -1)) == settings.RESEARCH_SLIPPAGE_POINTS and
            float(common.get("minimum_risk_reward_ratio", -1)) == float(
                settings.strategy_value("risk_gates", "min_risk_reward_ratio", settings.MIN_RR_RATIO)
            )
        )
        if (contract.get("schema_version") != 1 or not contract.get("paper_only") or
                set(contract.get("variants", {})) != required_variants or
                contract.get("lineage", {}).get("feature_schema_sha256") != feature_schema_sha256 or
                not runtime_contract_matches or
                contract.get("isolation", {}).get("may_approve_paper_trade") is not False or
                contract.get("isolation", {}).get("may_send_telegram") is not False):
            raise RuntimeError("shadow experiment contract violates frozen research rules or runtime settings")
        self.contract = contract
        self.contract_sha256 = digest

    def append(self, candidate_id: str, timestamp: str, signal: dict,
               decision: dict = None) -> None:
        decision = decision or {}
        direction = str(signal.get("direction", "")).upper()
        variants = self.contract["variants"]
        sweep_present = bool(signal.get("mtf", {}).get("smc", {}).get("liquidity_sweep_1h"))
        try:
            rr_ratio = float(signal.get("rr_ratio") or 0)
        except (TypeError, ValueError):
            rr_ratio = 0.0
        min_rr = float(self.contract["common_evaluation"]["minimum_risk_reward_ratio"])
        baseline_member = direction in variants["baseline_v1"]["directions"]
        buy_liquidity_member = (
            direction in variants["buy_liquidity_v1"]["directions"] and sweep_present
        )
        row = {
            "candidate_id": candidate_id,
            "timestamp": timestamp,
            "experiment_version": self.contract["experiment_version"],
            "contract_sha256": self.contract_sha256,
            "strategy_config_version": self.contract["lineage"]["strategy_config_version"],
            "feature_schema_sha256": self.contract["lineage"]["feature_schema_sha256"],
            "ml_model_version": decision.get("ml_model_version") or "UNAVAILABLE",
            "claude_model": decision.get("claude_model") or "UNAVAILABLE",
            "claude_prompt_version": (decision.get("claude_prompt_version") or
                                      self.contract["lineage"]["claude_prompt_version"]),
            "direction": direction,
            "baseline_v1": int(baseline_member),
            "buy_liquidity_v1": int(buy_liquidity_member),
            "min_rr_eligible": int(rr_ratio >= min_rr),
            "liquidity_sweep_1h_present": int(sweep_present),
            "rr_ratio": rr_ratio,
            "paper_trading": True,
            "assignment_note": "SHADOW_RESEARCH_ONLY_NO_APPROVAL_OR_TELEGRAM_EFFECT",
        }
        exists = self.path.exists() and self.path.stat().st_size > 0
        with self.path.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.COLUMNS)
            if not exists:
                writer.writeheader()
            writer.writerow(row)


class AIAssistedOrchestrator:
    def __init__(self):
        if not settings.PAPER_TRADING:
            raise RuntimeError("System C is research-only: PAPER_TRADING must remain true")
        self.ledger = PaperLedger()
        self.forward_features = ForwardFeatureJournal()
        self.forward_outcomes = ForwardOutcomeJournal()
        self.forward_variants = ForwardVariantJournal()
        self.ml_filter = MLSignalFilter()
        self.correlation = GoldCorrelationValidator()
        self.ai_decider = AITradingDecider()
        self.notifier = Notifier(
            token=settings.TELEGRAM_BOT_TOKEN or __import__("os").environ.get("TELEGRAM_TOKEN"),
            chat_id=settings.TELEGRAM_CHAT_ID,
            scan_only=False,
        )

    def _fresh_price(self):
        path = settings.TRADINGVIEW_SNAPSHOT_PATH
        if not path.exists():
            return None, "price snapshot missing"
        try:
            data = json.loads(path.read_text())
            timestamp_value = data.get("captured_at") or data.get("timestamp")
            if not timestamp_value:
                return None, "price snapshot has no timestamp"
            age = (utc_now() - parse_utc(timestamp_value)).total_seconds()
            if age < 0 or age > settings.SNAPSHOT_MAX_AGE_SECONDS:
                return None, f"price snapshot stale ({age:.0f}s)"
            bars = data["timeframes"]["15M"]["bars"]
            return float(bars[-1]["close"]), "fresh TradingView 15M close"
        except (KeyError, ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
            return None, f"invalid price snapshot: {exc}"

    def update_forward_outcomes(self) -> int:
        """Replay all completed snapshot bars newer than tracked candidates."""
        try:
            payload = json.loads(settings.TRADINGVIEW_SNAPSHOT_PATH.read_text())
            captured_at = parse_utc(payload["captured_at"])
            updated = 0
            for bar in payload["timeframes"]["15M"]["bars"]:
                raw_time = bar["time"]
                open_time = (datetime.fromtimestamp(float(raw_time), tz=timezone.utc)
                             if isinstance(raw_time, (int, float)) or str(raw_time).isdigit()
                             else parse_utc(str(raw_time)))
                close_time = open_time + timedelta(minutes=15)
                # TradingView includes the currently forming bar. Never label
                # from it because its high/low are not final yet.
                if close_time <= captured_at:
                    updated += self.forward_outcomes.update(bar, close_time)
            return updated
        except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Forward shadow outcomes not updated: %s", exc)
            return 0

    def update_open_trades(self) -> int:
        """Apply observation-time exits while recording their limited precision."""
        frame = self.ledger.load()
        open_rows = frame[frame["status"] == "OPEN"]
        if open_rows.empty:
            return 0
        current_price, price_reason = self._fresh_price()
        now = utc_now()
        updated = 0
        for index, row in open_rows.iterrows():
            try:
                entry, stop, target = map(float, (row["entry"], row["stop_loss"], row["take_profit"]))
                direction = row["direction"]
                age = now - parse_utc(row["timestamp"])
                result = exit_price = exit_reason = None
                if current_price is not None:
                    if direction == "BUY" and current_price <= stop:
                        result, exit_price, exit_reason = "LOSS", stop, "SL_OBSERVED_AT_SCAN"
                    elif direction == "BUY" and current_price >= target:
                        result, exit_price, exit_reason = "WIN", target, "TP_OBSERVED_AT_SCAN"
                    elif direction == "SELL" and current_price >= stop:
                        result, exit_price, exit_reason = "LOSS", stop, "SL_OBSERVED_AT_SCAN"
                    elif direction == "SELL" and current_price <= target:
                        result, exit_price, exit_reason = "WIN", target, "TP_OBSERVED_AT_SCAN"
                if result is None and age >= timedelta(hours=settings.TRADE_EXPIRY_HOURS):
                    result, exit_price = "EXPIRED", current_price or entry
                    exit_reason = f"TIME_EXPIRY_{settings.TRADE_EXPIRY_HOURS}H;{price_reason}"
                if result is None:
                    continue
                signed_move = ((exit_price - entry) / entry) * 100
                pnl_pct = signed_move if direction == "BUY" else -signed_move
                notional = float(row["notional_usd"] or 0)
                frame.at[index, "status"] = result
                frame.at[index, "exit_price"] = f"{exit_price:.5f}"
                frame.at[index, "exit_time"] = now.isoformat()
                frame.at[index, "exit_reason"] = exit_reason
                frame.at[index, "pnl_pct"] = f"{pnl_pct:.6f}"
                frame.at[index, "pnl_usd"] = f"{notional * pnl_pct / 100:.2f}"
                updated += 1
            except (ValueError, TypeError) as exc:
                logger.warning("Invalid open ledger row %s: %s", index, exc)
        if updated:
            self.ledger.save(frame)
        return updated

    @staticmethod
    def _normalize_signal(signal: dict) -> dict:
        direction = str(signal.get("direction", "")).upper()
        structure = signal.get("mtf", {}).get("smc", {}).get("struct_4h")
        expected = {"BUY": "bullish", "SELL": "bearish"}.get(direction)
        if expected is None or structure != expected:
            raise ValueError(f"direction/structure mismatch: {direction}/{structure}")
        normalized = dict(signal)
        normalized.update({
            "direction": direction, "pair": signal.get("symbol", settings.SYMBOL),
            "entry": float(signal["price"]), "stop_loss": float(signal["stop_loss"]),
            "take_profit": float(signal["take_profit"]),
            "take_profits": [float(signal["take_profit"])],
        })
        valid = (normalized["stop_loss"] < normalized["entry"] < normalized["take_profit"]
                 if direction == "BUY" else
                 normalized["take_profit"] < normalized["entry"] < normalized["stop_loss"])
        if not valid:
            raise ValueError(f"invalid {direction} signal geometry")
        return normalized

    def _risk_vetoes(self, signal: dict) -> list:
        vetoes = []
        open_count = len(self.ledger.open_positions())
        max_open = int(settings.strategy_value("risk_gates", "max_open_trades", settings.MAX_OPEN_TRADES))
        min_rr = float(settings.strategy_value("risk_gates", "min_risk_reward_ratio", settings.MIN_RR_RATIO))
        if open_count >= max_open:
            vetoes.append("MAX_OPEN_TRADES")
        if float(signal.get("rr_ratio") or 0) < min_rr:
            vetoes.append("MIN_RR_NOT_MET")
        today = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
        week = today - timedelta(days=today.weekday())
        daily_account_pct = self.ledger.realized_pnl_usd(today) / settings.PAPER_ACCOUNT_SIZE * 100
        weekly_account_pct = self.ledger.realized_pnl_usd(week) / settings.PAPER_ACCOUNT_SIZE * 100
        if daily_account_pct <= -abs(settings.DAILY_LOSS_CAP_PCT):
            vetoes.append("DAILY_LOSS_CAP")
        if weekly_account_pct <= -abs(settings.WEEKLY_LOSS_CAP_PCT):
            vetoes.append("WEEKLY_LOSS_CAP")
        return vetoes

    def _market_context(self, signal: dict, macro: dict) -> dict:
        mtf = signal.get("mtf", {})
        return {
            "as_of": utc_now().isoformat(),
            "price": signal["entry"],
            "trend_4h": mtf.get("smc", {}).get("struct_4h"),
            "trend_1h": mtf.get("smc", {}).get("struct_1h"),
            "rsi_1h": mtf.get("1H", {}).get("rsi"),
            "atr_1h": signal.get("atr"),
            "news_guard": signal.get("news_guard_status"),
            "macro_snapshot": macro.get("snapshot") if macro.get("available") else None,
        }

    def _record_candidate(self, signal: dict, decision: dict, status: str) -> str:
        base_notional = float(settings.strategy_value("position_sizing", "base_size_usd", 5000))
        candidate_id = uuid.uuid4().hex[:12].upper()
        timestamp = utc_now().isoformat()
        self.ledger.append({
            "candidate_id": candidate_id, "timestamp": timestamp,
            "pair": signal["pair"], "direction": signal["direction"], "entry": signal["entry"],
            "stop_loss": signal["stop_loss"], "take_profit": signal["take_profit"],
            "rr_ratio": signal.get("rr_ratio"), "smc_score": decision["smc_score"],
            "ml_available": decision["ml_available"], "ml_confidence": decision["ml_confidence"],
            "ml_model_version": decision.get("ml_model_version"),
            "claude_available": decision["claude_available"],
            "claude_confidence": decision["claude_confidence"],
            "macro_available": decision["macro_available"], "macro_score": decision["macro_score"],
            "combined_confidence": f"{decision['combined_confidence']:.4f}",
            "threshold": decision["threshold"], "decision": "APPROVE" if status == "OPEN" else "REJECT",
            "decision_reason": decision["final_reason"], "status": status,
            "notional_usd": base_notional, "paper_trading": True,
        })
        self.forward_features.append(candidate_id, timestamp, signal)
        self.forward_outcomes.append(candidate_id, timestamp, signal)
        self.forward_variants.append(candidate_id, timestamp, signal, decision)
        return candidate_id

    def run_scan(self):
        logger.info("[ORCHESTRATOR] Research paper-trading scan started")
        self.update_open_trades()
        self.update_forward_outcomes()
        session = get_session_description()
        if is_market_closed():
            logger.info("[ORCHESTRATOR] Market closed")
            return {"status": "MARKET_CLOSED"}

        signal = run_gold_scanner(settings.METAAPI_TOKEN, settings.METAAPI_ACCOUNT_ID)
        if not signal:
            return {"status": "NO_CANDIDATE"}
        signal = self._normalize_signal(signal)
        if self.ledger.is_duplicate(signal):
            return {"status": "DUPLICATE"}

        ml_result = self.ml_filter.score_signal(signal)
        macro_result = self.correlation.validate_signal(signal["direction"])
        decision = self.ai_decider.decide(
            signal_info=signal, market_data=self._market_context(signal, macro_result),
            ml_result=ml_result, macro_result=macro_result,
            smc_score=float(signal.get("score", 0)), liquidity_tier=session["liquidity_tier"],
            open_positions=self.ledger.open_positions(),
        )
        decision["ml_model_version"] = ml_result.get("model_version")
        risk_vetoes = self._risk_vetoes(signal)
        if risk_vetoes:
            decision["vetoes"].extend(risk_vetoes)
            decision["should_trade"] = False
            decision["final_reason"] = ", ".join(decision["vetoes"])

        status = "OPEN" if decision["should_trade"] else "REJECTED"
        candidate_id = self._record_candidate(signal, decision, status)
        logger.info("[DECISION] %s: %s", status, decision["final_reason"])
        if status == "OPEN":
            self.notifier.send_paper_signal(candidate_id, signal, decision)
        return {"status": status, "decision": decision}


def main():
    result = AIAssistedOrchestrator().run_scan()
    logger.info("[ORCHESTRATOR] Result: %s", result.get("status"))


if __name__ == "__main__":
    main()
