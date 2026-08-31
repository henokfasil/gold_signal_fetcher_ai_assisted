"""Structured LLM review for paper-trading candidates.

The LLM is a conservative context reviewer, not a source of market facts and
not a substitute for a calibrated statistical model.
"""

import json
import hashlib
import logging
import os

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ClaudeReviewOutput(BaseModel):
    """Strict response schema enforced by Anthropic before parsing."""

    model_config = ConfigDict(extra="forbid")

    should_trade: bool
    confidence: float = Field(ge=0, le=100)
    reasoning: str
    risks: list[str]


class ClaudeAnalyst:
    PROMPT_VERSION = "claude-review-v2-json-schema"

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
        request_json = json.dumps(
            payload, default=str, sort_keys=True, separators=(",", ":"),
        )
        request_sha256 = hashlib.sha256(request_json.encode()).hexdigest()
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=800,
                temperature=0,
                system=(
                    "You review XAUUSD PAPER-TRADING candidates. Use only supplied facts; "
                    "never invent news or market conditions. Reject invalid SL/TP geometry, "
                    "poor reward/risk, stale data, and explicit macro conflicts. Missing data "
                    "must reduce confidence. Your result is an auditable veto/explanation, not "
                    "a statistically calibrated forecast and never overrides hard risk gates. "
                    "Complete the registered structured response with "
                    "should_trade, confidence, reasoning and risks."
                ),
                messages=[{"role": "user", "content": request_json}],
                output_format=ClaudeReviewOutput,
            )
            if getattr(response, "stop_reason", None) == "max_tokens":
                raise ValueError("Claude response was truncated at max_tokens")
            parsed_blocks = [
                block for block in response.content
                if getattr(block, "parsed_output", None) is not None
            ]
            if len(parsed_blocks) != 1:
                raise ValueError(
                    "Claude response did not contain exactly one structured output"
                )
            parsed = parsed_blocks[0].parsed_output
            if not isinstance(parsed, ClaudeReviewOutput):
                parsed = ClaudeReviewOutput.model_validate(parsed)
            raw = str(getattr(parsed_blocks[0], "text", "")).strip()
            if not raw:
                raw = json.dumps(
                    parsed.model_dump(),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            risks = [str(item)[:250] for item in parsed.risks[:8]]
            return {
                "available": True,
                "should_trade": parsed.should_trade,
                "confidence": float(parsed.confidence),
                "reasoning": parsed.reasoning[:1000],
                "risks": risks,
                "model": self.model,
                "prompt_version": self.PROMPT_VERSION,
                "request_sha256": request_sha256,
                "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "request_payload_json": request_json,
                "response_payload_json": raw,
            }
        except Exception as exc:
            logger.error("Claude analysis failed: %s", exc)
            result = self._unavailable(f"Claude analysis failed: {exc}")
            result["request_sha256"] = request_sha256
            result["request_payload_json"] = request_json
            return result

    @staticmethod
    def _unavailable(reason: str) -> dict:
        # Fail closed. The SMC candidate can still be recorded for research,
        # but it must not be represented as an AI-approved paper trade.
        return {"available": False, "should_trade": False, "confidence": None,
                "reasoning": reason, "risks": ["AI_REVIEW_UNAVAILABLE"], "model": None,
                "prompt_version": ClaudeAnalyst.PROMPT_VERSION,
                "request_sha256": None, "response_sha256": None,
                "request_payload_json": None, "response_payload_json": None}


class AITradingDecider:
    """Combine only available, genuine evidence and preserve vetoes."""

    def __init__(self):
        self.claude = ClaudeAnalyst()

    def decide(self, signal_info: dict, market_data: dict, ml_result: dict,
               macro_result: dict, smc_score: float, liquidity_tier: str,
               open_positions: list = None,
               hard_vetoes: list[str] | None = None) -> dict:
        # The LLM is deliberately excluded from the numeric approval score.
        # Its confidence is not statistically calibrated; Claude may veto and
        # explain only. A future validated ML artifact must carry its own frozen
        # selection threshold in metadata.
        ml_threshold = ml_result.get("selection_threshold_pct")
        ml_ready = ml_result.get("available") and ml_threshold is not None
        # Opt-in rules-only PAPER track. When SMC_PAPER_THRESHOLD is set AND no
        # validated ML artifact exists, gate on the SMC score (0-100) instead of
        # blocking every candidate with an impossible 101.0 bar. When the env var
        # is UNSET, the original ML-mandatory scientific behavior is preserved
        # exactly (impossible bar + hard veto), so the frozen research invariants
        # and their guardrail tests are unchanged. Strictly paper-only either way:
        # PAPER_TRADING=true and no broker-order code exists anywhere in the repo.
        paper_threshold = os.getenv("SMC_PAPER_THRESHOLD")
        paper_track = (paper_threshold is not None) and not ml_ready

        if ml_ready:
            decision_score = float(ml_result["confidence"])
            threshold = float(ml_threshold)
        elif paper_track:
            decision_score = float(smc_score)
            threshold = float(paper_threshold)
        else:
            decision_score = float(smc_score)
            threshold = 101.0

        vetoes = list(dict.fromkeys(hard_vetoes or []))
        flags = []
        if macro_result.get("is_blocked"):
            vetoes.append("MACRO_CONFLICT")
        if not ml_ready:
            if paper_track:
                # Non-blocking provenance flag. The dashboard/ledger still record
                # ML unavailability via this flag and the ml_available field.
                flags.append("VALIDATED_ML_UNAVAILABLE")
            else:
                vetoes.append("VALIDATED_ML_UNAVAILABLE")
        if liquidity_tier == "closed":
            vetoes.append("MARKET_CLOSED")
        vetoes = list(dict.fromkeys(vetoes))

        approval_preconditions_met = decision_score >= threshold and not vetoes
        if approval_preconditions_met:
            claude = self.claude.analyze_signal(
                signal_info, market_data, ml_result, macro_result, open_positions
            )
            claude_review_attempted = True
            if not claude.get("available"):
                if paper_track:
                    # Soft (opt-in): Claude/transport being unavailable no longer
                    # blocks a paper trade. A genuine Claude veto (AI_REJECTED)
                    # below still blocks on real evidence conflict.
                    flags.append("AI_REVIEW_UNAVAILABLE")
                else:
                    vetoes.append("AI_REVIEW_UNAVAILABLE")
            elif not claude.get("should_trade"):
                if paper_track:
                    # Advisory only in the paper track: Claude's veto is logged as a
                    # flag (its reasoning is journalled) but does not block the paper
                    # trade. It becomes a shadow signal to evaluate later against a
                    # no-LLM baseline. Deterministic gates (min R:R, macro
                    # strong-conflict, market-closed) still block.
                    flags.append("AI_REJECTED")
                else:
                    vetoes.append("AI_REJECTED")
        else:
            failed_preconditions = vetoes or ["BELOW_REGISTERED_ML_THRESHOLD"]
            claude = ClaudeAnalyst._unavailable(
                "Claude review not attempted because approval preconditions failed: "
                + ", ".join(failed_preconditions)
            )
            claude["risks"] = [
                "AI_REVIEW_SKIPPED_PRECONDITION", *failed_preconditions,
            ]
            claude_review_attempted = False

        should_trade = decision_score >= threshold and not vetoes
        return {
            "should_trade": should_trade,
            # Retain the legacy field name for ledger compatibility. It is now
            # the validated ML decision score, or SMC score when ML is absent.
            "combined_confidence": decision_score,
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
            "claude_request_sha256": claude.get("request_sha256"),
            "claude_response_sha256": claude.get("response_sha256"),
            "claude_should_trade": claude.get("should_trade"),
            "claude_risks": claude.get("risks", []),
            "claude_request_payload_json": claude.get("request_payload_json"),
            "claude_response_payload_json": claude.get("response_payload_json"),
            "claude_review_attempted": claude_review_attempted,
            "macro_available": bool(macro_result.get("available")),
            "macro_score": macro_result.get("score"),
            "vetoes": vetoes,
            "flags": flags,
            "liquidity_tier": liquidity_tier,
            "final_reason": (
                ("approved" + (f" [{', '.join(flags)}]" if flags else ""))
                if should_trade
                else ", ".join(vetoes)
                or ("below SMC paper threshold" if paper_track
                    else "below registered ML threshold")
            ),
        }
