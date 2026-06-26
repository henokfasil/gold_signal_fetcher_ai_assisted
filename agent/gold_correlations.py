"""
Cross-asset correlation validation for XAUUSD signals.
Checks USD strength, real rates, and equity indices to confirm/block gold signals.
"""

import logging
import requests
from typing import Dict, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class GoldCorrelationValidator:
    """Validate gold signals using correlated asset pairs."""

    def __init__(self):
        """Initialize with API endpoints for correlation data."""
        self.usd_base_url = "https://api.polygon.io/v1"
        self.fred_api_url = "https://api.stlouisfed.org/fred"
        self.last_correlation_check = None

    def get_usd_strength(self) -> Tuple[float, str]:
        """
        Get USD Index strength and momentum.
        Returns: (usd_momentum: -1.0 to 1.0, trend: "strong_up" | "weak" | "strong_down")
        """
        try:
            # Simplified: Check if USD is strengthening or weakening
            # In production, would fetch real-time DXY data
            # For now, use static threshold logic
            usd_momentum = 0.3  # Placeholder - would be dynamic

            if usd_momentum > 0.5:
                trend = "strong_up"
            elif usd_momentum > 0.1:
                trend = "weak"
            else:
                trend = "strong_down"

            return usd_momentum, trend
        except Exception as e:
            logger.warning(f"Could not fetch USD strength: {e}")
            return 0, "neutral"

    def get_real_rates(self) -> Tuple[float, str]:
        """
        Get real interest rates (10Y yield - inflation expectations).
        Returns: (rate_momentum: -1.0 to 1.0, direction: "rising" | "stable" | "falling")
        """
        try:
            # Check if real rates are rising or falling
            # Real rates = 10Y yield - inflation expectations
            # Rising real rates = bearish for gold
            # Falling real rates = bullish for gold
            rate_momentum = -0.2  # Placeholder - would be dynamic

            if rate_momentum > 0.1:
                direction = "rising"
            elif rate_momentum > -0.1:
                direction = "stable"
            else:
                direction = "falling"

            return rate_momentum, direction
        except Exception as e:
            logger.warning(f"Could not fetch real rates: {e}")
            return 0, "stable"

    def get_equity_risk_sentiment(self) -> Tuple[float, str]:
        """
        Get equity market risk sentiment (VIX level + SPY trend).
        Returns: (risk_sentiment: 0-100, mode: "risk_on" | "neutral" | "risk_off")
        """
        try:
            # Check if equities are rallying (risk-on) or selling (risk-off)
            # Risk-on = bearish for gold (flows to equities)
            # Risk-off = bullish for gold (safe-haven bid)
            vix_level = 15  # Placeholder - would be dynamic

            if vix_level < 12:
                mode = "risk_on"
            elif vix_level < 18:
                mode = "neutral"
            else:
                mode = "risk_off"

            risk_sentiment = max(0, min(100, vix_level * 5))
            return risk_sentiment, mode
        except Exception as e:
            logger.warning(f"Could not fetch equity sentiment: {e}")
            return 50, "neutral"

    def validate_signal(self, signal_direction: str) -> Dict:
        """
        Validate a gold signal using correlation pairs.

        Args:
            signal_direction: "BUY" or "SELL"

        Returns:
            {
                'is_confirmed': bool,
                'is_blocked': bool,
                'smt_score': 0-100,
                'factors': {
                    'usd': {...},
                    'real_rates': {...},
                    'equity_sentiment': {...}
                },
                'reasoning': str
            }
        """
        usd_momentum, usd_trend = self.get_usd_strength()
        rate_momentum, rate_direction = self.get_real_rates()
        risk_sentiment, risk_mode = self.get_equity_risk_sentiment()

        # Score the signal based on correlations
        smt_score = 50  # Start neutral
        factors = {
            'usd': {
                'momentum': usd_momentum,
                'trend': usd_trend,
                'supports_signal': False
            },
            'real_rates': {
                'momentum': rate_momentum,
                'direction': rate_direction,
                'supports_signal': False
            },
            'equity_sentiment': {
                'risk_level': risk_sentiment,
                'mode': risk_mode,
                'supports_signal': False
            }
        }

        # Gold inverse correlation with USD
        if signal_direction == "BUY":
            # Gold BUY signals confirmed by:
            # - USD weakening (usd_trend != "strong_up")
            # - Real rates falling (rate_direction == "falling")
            # - Risk-off sentiment (risk_mode == "risk_off")

            if usd_trend != "strong_up":
                smt_score += 15
                factors['usd']['supports_signal'] = True

            if rate_direction == "falling":
                smt_score += 15
                factors['real_rates']['supports_signal'] = True

            if risk_mode == "risk_off":
                smt_score += 15
                factors['equity_sentiment']['supports_signal'] = True

        else:  # SELL
            # Gold SELL signals confirmed by:
            # - USD strengthening (usd_trend == "strong_up")
            # - Real rates rising (rate_direction == "rising")
            # - Risk-on sentiment (risk_mode == "risk_on")

            if usd_trend == "strong_up":
                smt_score += 15
                factors['usd']['supports_signal'] = True

            if rate_direction == "rising":
                smt_score += 15
                factors['real_rates']['supports_signal'] = True

            if risk_mode == "risk_on":
                smt_score += 15
                factors['equity_sentiment']['supports_signal'] = True

        # Check for hard blocks (extreme conflicts)
        is_blocked = False
        blocking_reason = ""

        if signal_direction == "BUY" and usd_trend == "strong_up" and rate_direction == "rising":
            is_blocked = True
            blocking_reason = "Strong USD + rising rates block gold buy"

        if signal_direction == "SELL" and usd_trend == "strong_down" and rate_direction == "falling":
            is_blocked = True
            blocking_reason = "Falling rates + weak USD block gold sell"

        is_confirmed = smt_score >= 60 and not is_blocked
        reasoning = self._build_reasoning(signal_direction, factors, smt_score, is_blocked, blocking_reason)

        self.last_correlation_check = datetime.now()

        return {
            'is_confirmed': is_confirmed,
            'is_blocked': is_blocked,
            'smt_score': smt_score,
            'factors': factors,
            'reasoning': reasoning
        }

    def _build_reasoning(self, direction: str, factors: Dict, score: int, blocked: bool, block_reason: str) -> str:
        """Build human-readable reasoning for the correlation check."""
        parts = []

        if blocked:
            return f"HARD BLOCK: {block_reason}"

        parts.append(f"SMT Score: {score}/100")

        if factors['usd']['supports_signal']:
            parts.append(f"✓ USD {factors['usd']['trend']}")
        else:
            parts.append(f"✗ USD {factors['usd']['trend']}")

        if factors['real_rates']['supports_signal']:
            parts.append(f"✓ Rates {factors['real_rates']['direction']}")
        else:
            parts.append(f"✗ Rates {factors['real_rates']['direction']}")

        if factors['equity_sentiment']['supports_signal']:
            parts.append(f"✓ Equities {factors['equity_sentiment']['mode']}")
        else:
            parts.append(f"✗ Equities {factors['equity_sentiment']['mode']}")

        return " | ".join(parts)
