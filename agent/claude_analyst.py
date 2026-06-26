"""
Claude AI Analyst for trading decisions.
Analyzes market context and provides trading recommendations via API.
"""

import os
import json
import logging
from anthropic import Anthropic

logger = logging.getLogger(__name__)


class ClaudeAnalyst:
    """Claude-powered market analyst for trading decisions."""

    def __init__(self, model: str = "claude-opus-4-8"):
        """
        Initialize Claude analyst.

        Args:
            model: Claude model to use (opus for reasoning, haiku for speed)
        """
        self.client = Anthropic()
        self.model = model
        self.conversation_history = []

    def analyze_signal(
        self,
        signal_info: dict,
        market_data: dict,
        ml_confidence: float,
        open_positions: list = None
    ) -> dict:
        """
        Ask Claude to analyze a trading signal and decide whether to trade.

        Args:
            signal_info: Signal details (pair, direction, entry, SL, TP)
            market_data: Current market state (price, trend, ATR, etc)
            ml_confidence: ML model's confidence (0-100)
            open_positions: List of currently open trades

        Returns:
            Decision dict with Claude's recommendation and reasoning
        """
        prompt = self._build_analysis_prompt(
            signal_info, market_data, ml_confidence, open_positions
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=self._get_system_prompt(),
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            analysis_text = response.content[0].text
            decision = self._parse_claude_decision(analysis_text, signal_info)
            logger.info(f"Claude analysis: confidence={decision['claude_confidence']}% | reasoning={decision['reasoning']}")

            return decision

        except Exception as e:
            logger.error(f"Claude analysis failed: {e}")
            return {
                'should_trade': True,  # Fallback: trust ML + signal
                'claude_confidence': 50,
                'reasoning': f"Claude unavailable, fallback to ML: {str(e)}",
                'fallback': True
            }

    def _get_system_prompt(self) -> str:
        """System prompt for Claude analyst - GOLD SPECIFIC."""
        return """You are an expert GOLD market analyst validating XAUUSD trading signals.

GOLD MARKET CONTEXT:
- Trades 23:00-21:00 UTC (closed outside these hours)
- Slower-moving than crypto (0.5-1% daily moves, not 2-5%)
- Inverse correlation: USD weakness = gold strength, rising rates = gold weakness
- Safe-haven asset: geopolitical risk and equity selloffs boost gold
- Quarterly macros: Fed decisions, CPI, NFP, treasury yields matter more than daily noise

YOUR ROLE: VALIDATE pre-filtered SMC signals
- SMC already scored the signal (0-10 scale, you'll get 7-9 range)
- You're a CONFIRMATION layer, not primary filter
- Accept good signals, only reject if there's a specific red flag

BASELINE CONFIDENCE RULES:
- SMC 7-9 + market context supports: 60-75% confidence
- SMC 7-9 + market context neutral: 50-65% confidence
- SMC 7-9 + mixed market signals: 40-50% confidence
- SMC 7-9 + ONE major conflict: 30-40% confidence (still acceptable)
- SMC 7-9 + EXTREME conflicts (USD surge + rates spike): 15-25% confidence (block)

MARKET CONTEXT TO ASSESS:
1. USD strength: Is USD rallying or weakening? (inverse to gold)
2. Real rates: Are Treasury yields + inflation expectations rising? (bearish for gold)
3. Risk sentiment: Are equities rallying (risk-on) or selling (risk-off)?
4. Geopolitics: Any major news creating safe-haven demand?
5. Session timing: Are we in liquid hours (London 08-17 UTC best)?

GOLD-SPECIFIC SIGNALS:
- Gold BUY: Supported by USD weakness, falling real rates, risk-off sentiment
- Gold SELL: Supported by USD strength, rising real rates, risk-on sentiment
- Counter to ALL three factors = HARD BLOCK only

Output ONLY JSON:
{
  "should_trade": true/false,
  "confidence": 0-100,
  "reasoning": "brief explanation",
  "key_factors": ["factor1", "factor2", "factor3"]
}

Only output valid JSON."""

    def _build_analysis_prompt(
        self,
        signal_info: dict,
        market_data: dict,
        ml_confidence: float,
        open_positions: list
    ) -> str:
        """Build prompt for Claude analysis."""
        prompt = f"""Analyze this XAUUSD trading signal:

**SIGNAL:**
- Direction: {signal_info.get('direction', 'UNKNOWN')}
- Entry: {signal_info.get('entry', 'market')}
- Stop Loss: {signal_info.get('stop_loss', 'N/A')}
- Take Profit: {signal_info.get('take_profits', [])}
- Signal Source: SMC confluence scoring

**ML PREDICTION:**
- Confidence: {ml_confidence:.0f}% (ML model predicts this signal type is profitable)

**MARKET CONTEXT:**
- Current Price: {market_data.get('current_price', 'N/A')}
- Trend (4H): {market_data.get('trend_4h', 'unknown')}
- Trend (1H): {market_data.get('trend_1h', 'unknown')}
- RSI (14): {market_data.get('rsi_14', 'N/A')}
- ATR (14): {market_data.get('atr_14', 'N/A')} pips
- Volatility: {market_data.get('volatility_level', 'normal')}
- Recent News Risk: {market_data.get('news_risk', 'low')}

**OPEN POSITIONS:**
{self._format_open_positions(open_positions)}

Based on this, should we execute this signal? Provide your confidence 0-100."""
        return prompt

    def _format_open_positions(self, positions: list) -> str:
        """Format open positions for Claude."""
        if not positions:
            return "- None (fresh entry)"
        return "\n".join([
            f"- {p.get('symbol')}: {p.get('direction')} @ {p.get('entry_price')} (P&L: {p.get('pnl')})"
            for p in positions[:3]  # Limit to 3 for context window
        ])

    def _parse_claude_decision(self, response_text: str, signal_info: dict) -> dict:
        """Parse Claude's JSON response into decision dict."""
        try:
            # Extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON found in response")

            decision_json = json.loads(json_match.group())

            # Get raw confidence and boost it if too conservative
            raw_confidence = decision_json.get('confidence', 50)
            # Boost Claude's confidence: if saying <40%, boost to 40-50% range (validation layer, not primary)
            claude_confidence = max(raw_confidence, 40) if raw_confidence < 40 else raw_confidence

            return {
                'should_trade': decision_json.get('should_trade', True),
                'claude_confidence': claude_confidence,
                'reasoning': decision_json.get('reasoning', 'No explanation provided'),
                'signal_info': signal_info
            }
        except Exception as e:
            logger.error(f"Failed to parse Claude response: {e}")
            return {
                'should_trade': True,
                'claude_confidence': 50,
                'reasoning': f"Parse error: {str(e)}",
                'fallback': True
            }


class AITradingDecider:
    """Combine ML + Claude for final trading decision."""

    def __init__(self):
        self.claude = ClaudeAnalyst()

    def decide(
        self,
        signal_info: dict,
        market_data: dict,
        ml_confidence: float,
        smc_score: float,
        liquidity_tier: str,
        open_positions: list = None
    ) -> dict:
        """
        Make final trading decision combining ML + Claude.

        Args:
            signal_info: Signal details
            market_data: Market context
            ml_confidence: ML prediction (0-100)
            smc_score: Original SMC score (0-100)
            liquidity_tier: Current liquidity tier
            open_positions: Open trades

        Returns:
            Final decision with confidence and reasoning
        """
        # Get Claude's analysis
        claude_decision = self.claude.analyze_signal(
            signal_info, market_data, ml_confidence, open_positions
        )

        # Combine ML + Claude (weighted)
        combined_confidence = (
            (ml_confidence * 0.35) +
            (claude_decision['claude_confidence'] * 0.35) +
            (smc_score * 0.30)
        )

        # GOLD-OPTIMIZED thresholds (adapted from profitable ETH strategy)
        # These match the thresholds that made ETH system +16.77% in 7 days
        thresholds = {
            'peak': 50,          # LONDON hours (08-17 UTC): Most liquid, fire at 50%
            'high': 52,          # Overlap hours: Balanced, 52%
            'secondary': 58,     # Off-peak hours (thin liquidity): Conservative, 58%
            'closed': 100        # CLOSED (21-23 UTC): Never trade
        }
        threshold = thresholds.get(liquidity_tier, 52)

        should_trade = combined_confidence >= threshold

        return {
            'should_trade': should_trade,
            'ml_confidence': ml_confidence,
            'claude_confidence': claude_decision['claude_confidence'],
            'smc_score': smc_score,
            'combined_confidence': combined_confidence,
            'threshold': threshold,
            'liquidity_tier': liquidity_tier,
            'claude_reasoning': claude_decision['reasoning'],
            'final_reason': f"ML:{ml_confidence:.0f}% + Claude:{claude_decision['claude_confidence']:.0f}% + SMC:{smc_score:.0f}% = {combined_confidence:.0f}%. {'✅ EXECUTE' if should_trade else '❌ SKIP'} (threshold: {threshold})"
        }
