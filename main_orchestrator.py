"""Research-grade paper-trading orchestrator for System C.

Every candidate is auditable. Missing ML, macro, or LLM evidence is explicit;
no random model or fabricated neutral score can approve a paper trade.
"""

import csv
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

    def is_duplicate(self, signal: dict, minutes: int = 30) -> bool:
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


class AIAssistedOrchestrator:
    def __init__(self):
        if not settings.PAPER_TRADING:
            raise RuntimeError("System C is research-only: PAPER_TRADING must remain true")
        self.ledger = PaperLedger()
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
            record = data.get(settings.SYMBOL, data)
            timestamp_value = record.get("timestamp") or data.get("timestamp")
            if not timestamp_value:
                return None, "price snapshot has no timestamp"
            age = (utc_now() - parse_utc(timestamp_value)).total_seconds()
            if age < 0 or age > settings.SNAPSHOT_MAX_AGE_SECONDS:
                return None, f"price snapshot stale ({age:.0f}s)"
            return float(record["price"]), "fresh price snapshot"
        except (KeyError, ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
            return None, f"invalid price snapshot: {exc}"

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
        structure = signal.get("mtf", {}).get("smc", {}).get("struct_4h")
        # The current scanner implements bullish BOS/CHoCH and constructs SL
        # below / TP above. It must never be relabelled as a short.
        if structure != "bullish":
            raise ValueError(f"bullish scanner returned non-bullish structure: {structure}")
        normalized = dict(signal)
        normalized.update({
            "direction": "BUY", "pair": signal.get("symbol", settings.SYMBOL),
            "entry": float(signal["price"]), "stop_loss": float(signal["stop_loss"]),
            "take_profit": float(signal["take_profit"]),
            "take_profits": [float(signal["take_profit"])],
        })
        if not normalized["stop_loss"] < normalized["entry"] < normalized["take_profit"]:
            raise ValueError("invalid BUY geometry: expected SL < entry < TP")
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
        if self.ledger.realized_pnl(today) <= -abs(settings.DAILY_LOSS_CAP_PCT):
            vetoes.append("DAILY_LOSS_CAP")
        if self.ledger.realized_pnl(week) <= -abs(settings.WEEKLY_LOSS_CAP_PCT):
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

    def _record_candidate(self, signal: dict, decision: dict, status: str) -> None:
        base_notional = float(settings.strategy_value("position_sizing", "base_size_usd", 5000))
        self.ledger.append({
            "candidate_id": uuid.uuid4().hex[:12].upper(), "timestamp": utc_now().isoformat(),
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

    def run_scan(self):
        logger.info("[ORCHESTRATOR] Research paper-trading scan started")
        self.update_open_trades()
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
        self._record_candidate(signal, decision, status)
        logger.info("[DECISION] %s: %s", status, decision["final_reason"])
        return {"status": status, "decision": decision}


def main():
    result = AIAssistedOrchestrator().run_scan()
    logger.info("[ORCHESTRATOR] Result: %s", result.get("status"))


if __name__ == "__main__":
    main()
