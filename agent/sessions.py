"""
Global trading sessions and liquidity tiers for XAUUSD.
Defines when markets are active and their liquidity levels.
All times in UTC (no DST changes).
"""

from datetime import datetime, timezone
from typing import Tuple, Optional
from enum import Enum


class LiquidityTier(Enum):
    """Position sizing and risk tier based on market liquidity."""
    PEAK = "peak"           # 100% position size
    HIGH = "high"           # 90% position size
    SECONDARY = "secondary" # 60% position size
    CLOSED = "closed"       # 0% - market closed


class TradingSession(Enum):
    """Major global trading sessions."""
    ASIA = "asia"           # Sydney, Tokyo, Hong Kong, Singapore
    LONDON = "london"       # Frankfurt, Zurich, London
    NY = "ny"               # New York, Chicago
    WEEKEND = "weekend"     # Market closed


def get_current_utc_hour() -> int:
    """Get current hour in UTC (0-23)."""
    return datetime.now(timezone.utc).hour


def get_current_utc_time() -> datetime:
    """Get current time in UTC."""
    return datetime.now(timezone.utc)


def get_day_of_week() -> int:
    """Get day of week. 0=Monday, 4=Friday, 5=Saturday, 6=Sunday."""
    return datetime.now(timezone.utc).weekday()


def is_market_open() -> bool:
    """Check if any major market is open (Mon-Fri)."""
    day = get_day_of_week()
    if day >= 5:  # Saturday or Sunday
        return False
    return True


def get_session_at_time(hour: int) -> TradingSession:
    """
    Determine which session is active at given UTC hour.

    Args:
        hour: UTC hour (0-23)

    Returns:
        TradingSession enum
    """
    # Asian session: 20:00 (prev day) - 08:00 UTC (Sydney opens 21:00, Tokyo 21:00, HK 22:30, closes 06:30)
    if 20 <= hour or hour < 8:
        return TradingSession.ASIA
    # London session: 08:00 - 16:30 UTC
    elif 8 <= hour < 17:
        return TradingSession.LONDON
    # NY session: 12:00 - 21:00 UTC
    elif 12 <= hour < 21:
        return TradingSession.NY
    else:
        return TradingSession.ASIA  # Default to Asia for hours 17-20


def get_liquidity_tier(hour: int, minute: int = 0) -> LiquidityTier:
    """
    Determine liquidity tier based on UTC time.

    Tiers:
      PEAK:       London + NY overlap (13:00-16:30 UTC) = 100% position
      HIGH:       London alone (08:00-13:00), NY alone (16:30-21:00), Tokyo+London (08:00-12:00)
      SECONDARY:  Asian hours (20:00-08:00), Early NY (12:00-13:00)
      CLOSED:     Weekend or dead hours

    Args:
        hour: UTC hour (0-23)
        minute: UTC minute (0-59)

    Returns:
        LiquidityTier enum
    """
    day = get_day_of_week()

    # Check if weekend
    if day >= 5:  # Saturday or Sunday
        return LiquidityTier.CLOSED

    # Friday after 21:00 - market closing
    if day == 4 and hour >= 21:
        return LiquidityTier.CLOSED

    # PEAK LIQUIDITY: London + NY overlap (13:00-16:30 UTC)
    if 13 <= hour < 16 or (hour == 16 and minute < 30):
        return LiquidityTier.PEAK

    # HIGH LIQUIDITY: London session (08:00-13:00 UTC)
    if 8 <= hour < 13:
        return LiquidityTier.HIGH

    # HIGH LIQUIDITY: NY session (16:30-20:00 UTC)
    # Note: NY closes at 21:00, but 20:00-21:00 is transitional (Asian opens, thin)
    if (hour == 16 and minute >= 30) or (17 <= hour < 20):
        return LiquidityTier.HIGH

    # SECONDARY LIQUIDITY: Asian hours (20:00 UTC - 08:00 UTC)
    # Includes late NY-to-Asia transition, all of Asia, early London prep
    if 20 <= hour or hour < 8:
        return LiquidityTier.SECONDARY

    # Default fallback
    return LiquidityTier.SECONDARY


def get_position_size_multiplier(tier: LiquidityTier) -> float:
    """
    Get position size multiplier based on liquidity tier.

    Args:
        tier: LiquidityTier enum

    Returns:
        float: multiplier (0.0 to 1.0)
    """
    multipliers = {
        LiquidityTier.PEAK: 1.0,
        LiquidityTier.HIGH: 0.9,
        LiquidityTier.SECONDARY: 0.6,
        LiquidityTier.CLOSED: 0.0,
    }
    return multipliers.get(tier, 0.0)


def get_confidence_gate_requirement(tier: LiquidityTier) -> str:
    """
    Get confidence gate requirement based on liquidity tier.
    Higher tiers can accept weaker signals.

    Args:
        tier: LiquidityTier enum

    Returns:
        str: "STRONG", "MODERATE", or "WEAK"
    """
    gates = {
        LiquidityTier.PEAK: "WEAK",        # Can trade anything during peak liquidity
        LiquidityTier.HIGH: "MODERATE",    # Need moderate+ signals
        LiquidityTier.SECONDARY: "STRONG", # Only strong signals in thin hours
        LiquidityTier.CLOSED: "STRONG",    # Same as secondary (if somehow trading)
    }
    return gates.get(tier, "STRONG")


def get_session_info() -> dict:
    """Get current session info."""
    hour = get_current_utc_hour()
    minute = datetime.now(timezone.utc).minute
    tier = get_liquidity_tier(hour, minute)
    session = get_session_at_time(hour)

    return {
        "utc_hour": hour,
        "utc_minute": minute,
        "session": session.value,
        "tier": tier.value,
        "is_market_open": is_market_open(),
        "position_size_multiplier": get_position_size_multiplier(tier),
        "confidence_gate": get_confidence_gate_requirement(tier),
    }


# Session definitions for documentation
SESSIONS_REFERENCE = {
    "PEAK_LIQUIDITY": {
        "description": "London + NY overlap",
        "hours_utc": "13:00-16:30",
        "position_size": "100%",
        "confidence_gate": "WEAK",
        "key_events": "LBMA close + COMEX active"
    },
    "HIGH_LIQUIDITY": {
        "description": "London morning OR NY afternoon",
        "hours_utc": "08:00-13:00 AND 16:30-21:00",
        "position_size": "90%",
        "confidence_gate": "MODERATE",
        "key_events": "LBMA auctions (10:30, 15:00), COMEX open"
    },
    "SECONDARY_LIQUIDITY": {
        "description": "Asian hours (thin)",
        "hours_utc": "20:00-08:00",
        "position_size": "60%",
        "confidence_gate": "STRONG",
        "key_events": "Tokyo, HK, Singapore open (thin for gold)"
    },
    "CLOSED": {
        "description": "Weekend + Friday close",
        "hours_utc": "Fri 21:00 - Sun 20:00",
        "position_size": "0%",
        "confidence_gate": "N/A",
        "key_events": "Gap risk, no trading"
    }
}
