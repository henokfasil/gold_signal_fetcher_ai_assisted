"""Structured LLM review for paper-trading candidates.

The LLM is a conservative context reviewer, not a source of market facts and
not a substitute for a calibrated statistical model.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)


class ClaudeAnalyst:
    PROMPT_VERSION = "claude-review-v1"

    def __init__(self, model: str = None):
        self.model = model or os.getenv("ANTHROPIC_REASONING_MODEL", "claude-sonnet-4-5")
        self.client = None
        self.unavailable_reason = "ANTHROPIC_API_KEY is missing"
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                from anthropic import Anthropic
                self.client = Anthropic()
                self.unavailable_reason = ""
            except Exception as exc:
                self.unavailable_reason = f"Claude client unavailable: {exc}"

    def analyze_signal(self, signal_info: dict, market_data: dict, ml_result: dict,
                       macro_result: dict, open_positions: list = None) -> dict:
        if self.client is None:
            return self._unavailable(self.unavailable_reason)

        payload = {
            "signal": {
                "direction": signal_info.get("direction"),
                "entry": signal_info.get("entry"),
                "stop_loss": signal_info.get("stop_loss"),
                "take_profits": signal_info.get("take_profits"),
                "smc_score": signal_info.get("score"),
                "rr_ratio": signal_info.get("rr_ratio"),
            },
            "market_data": market_data,
            "ml": ml_result,
            "macro": macro_result,
            "open_position_count": len(open_positions or []),
        }
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=400,
                system=(
                    "You review XAUUSD PAPER-TRADING candidates. Use only supplied facts; "
                    "never invent news or market conditions. Reject invalid SL/TP geometry, "
                    "poor reward/risk, stale data, and explicit macro conflicts. Missing data "
                    "must reduce confidence. Return only JSON with keys should_trade (boolean), "
                    "confidence (0-100), reasoning (string), and risks (array of strings)."
                ),
                messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").removeprefix("json").strip()
            parsed = json.loads(raw)
            should_trade = parsed["should_trade"]
            confidence = float(parsed["confidence"])
            if not isinstance(should_trade, bool) or not 0 <= confidence <= 100:
                raise ValueError("response fields outside schema")
            return {
                "available": True,
                "should_trade": should_trade,
                "confidence": confidence,
                "reasoning": str(parsed.get("reasoning", ""))[:1000],
                "risks": [str(item)[:250] for item in parsed.get("risks", [])[:8]],
                "model": self.model,
                "prompt_version": self.PROMPT_VERSION,
            }
        except Exception as exc:
            logger.error("Claude analysis failed: %s", exc)
            return self._unavailable(f"Claude analysis failed: {exc}")

    @staticmethod
    def _unavailable(reason: str) -> dict:
        # Fail closed. The SMC candidate can still be recorded for research,
        # but it must not be represented as an AI-approved paper trade.
        return {"available": False, "should_trade": False, "confidence": None,
                "reasoning": reason, "risks": ["AI_REVIEW_UNAVAILABLE"], "model": None,
                "prompt_version": ClaudeAnalyst.PROMPT_VERSION}


class AITradingDecider:
    """Combine only available, genuine evidence and preserve vetoes."""

    def __init__(self):
        self.claude = ClaudeAnalyst()

    def decide(self, signal_info: dict, market_data: dict, ml_result: dict,
               macro_result: dict, smc_score: float, liquidity_tier: str,
               open_positions: list = None) -> dict:
        claude = self.claude.analyze_signal(
            signal_info, market_data, ml_result, macro_result, open_positions
        )
        thresholds = {"peak": 55, "high": 58, "secondary": 65, "closed": 101}
        threshold = thresholds.get(liquidity_tier, 65)

        components = [("smc", float(smc_score), 0.30)]
        if ml_result.get("available"):
            components.append(("ml", float(ml_result["confidence"]), 0.35))
        if claude.get("available"):
            components.append(("claude", float(claude["confidence"]), 0.35))
        total_weight = sum(weight for _, _, weight in components)
        combined = sum(value * weight for _, value, weight in components) / total_weight

        vetoes = []
        if macro_result.get("is_blocked"):
            vetoes.append("MACRO_CONFLICT")
        if not claude.get("available"):
            vetoes.append("AI_REVIEW_UNAVAILABLE")
        elif not claude.get("should_trade"):
            vetoes.append("AI_REJECTED")
        if not ml_result.get("available"):
            vetoes.append("VALIDATED_ML_UNAVAILABLE")
        if liquidity_tier == "closed":
            vetoes.append("MARKET_CLOSED")

        should_trade = combined >= threshold and not vetoes
        return {
            "should_trade": should_trade,
            "combined_confidence": combined,
            "threshold": threshold,
            "smc_score": float(smc_score),
            "ml_confidence": ml_result.get("confidence"),
            "ml_available": bool(ml_result.get("available")),
            "ml_reason": ml_result.get("reason"),
            "claude_confidence": claude.get("confidence"),
            "claude_available": bool(claude.get("available")),
            "claude_reasoning": claude.get("reasoning"),
            "claude_model": claude.get("model"),
            "claude_prompt_version": claude.get("prompt_version"),
            "macro_available": bool(macro_result.get("available")),
            "macro_score": macro_result.get("score"),
            "vetoes": vetoes,
            "liquidity_tier": liquidity_tier,
            "final_reason": "approved" if should_trade else ", ".join(vetoes) or "below threshold",
        }
