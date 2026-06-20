"""
Liquidity-aware position sizing and risk adjustments.
Wraps around risk_manager to apply session-based multipliers.
Does NOT modify existing risk_manager logic.
"""

import logging
from agent import sessions
from config import settings

logger = logging.getLogger(__name__)


def get_adjusted_position_size(base_position_size: float) -> float:
    """
    Adjust base position size based on current liquidity tier.

    Args:
        base_position_size: Default position size from settings

    Returns:
        float: Adjusted position size
    """
    current_tier = sessions.get_liquidity_tier(
        sessions.get_current_utc_hour(),
        sessions.get_current_utc_time().minute
    )

    multiplier = sessions.get_position_size_multiplier(current_tier)
    adjusted = base_position_size * multiplier

    logger.info(
        f"Position size adjustment: {base_position_size} × {multiplier} = {adjusted} "
        f"(tier: {current_tier.value})"
    )

    return adjusted


def get_adjusted_stop_loss_width(base_atr: float, tier: sessions.LiquidityTier) -> float:
    """
    Adjust stop loss width based on liquidity tier.
    Thinner stops during peak liquidity, wider during thin hours.

    Args:
        base_atr: Base ATR-derived stop loss width
        tier: Current liquidity tier

    Returns:
        float: Adjusted stop loss width
    """
    adjustments = {
        sessions.LiquidityTier.PEAK: 0.9,        # Tighten stops 10% (best liquidity)
        sessions.LiquidityTier.HIGH: 1.0,        # Keep normal
        sessions.LiquidityTier.SECONDARY: 1.2,   # Widen stops 20% (thin liquidity)
        sessions.LiquidityTier.CLOSED: 1.5,      # Very wide (don't trade)
    }

    adjustment = adjustments.get(tier, 1.0)
    adjusted_sl = base_atr * adjustment

    return adjusted_sl


def should_trade_this_signal(signal_quality: str) -> bool:
    """
    Determine if signal should be traded based on current liquidity tier.
    Uses tier-specific confidence gates.

    Args:
        signal_quality: Signal quality from analyst (STRONG, MODERATE, WEAK)

    Returns:
        bool: True if signal meets tier's confidence requirement
    """
    current_tier = sessions.get_liquidity_tier(
        sessions.get_current_utc_hour(),
        sessions.get_current_utc_time().minute
    )

    required_gate = sessions.get_confidence_gate_requirement(current_tier)

    # Quality ranking: STRONG > MODERATE > WEAK
    quality_rank = {
        "STRONG": 3,
        "MODERATE": 2,
        "WEAK": 1,
    }

    gate_rank = {
        "STRONG": 3,
        "MODERATE": 2,
        "WEAK": 1,
    }

    signal_rank = quality_rank.get(signal_quality, 0)
    required_rank = gate_rank.get(required_gate, 3)

    can_trade = signal_rank >= required_rank

    logger.info(
        f"Liquidity tier {current_tier.value}: signal={signal_quality} "
        f"(rank {signal_rank}), required={required_gate} (rank {required_rank}), "
        f"can_trade={can_trade}"
    )

    return can_trade


def get_session_description() -> dict:
    """Get human-readable description of current trading session."""
    hour = sessions.get_current_utc_hour()
    minute = sessions.get_current_utc_time().minute
    tier = sessions.get_liquidity_tier(hour, minute)
    day = sessions.get_day_of_week()

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    return {
        "current_time_utc": f"{hour:02d}:{minute:02d}",
        "current_day": day_names[day],
        "liquidity_tier": tier.value,
        "position_size_multiplier": sessions.get_position_size_multiplier(tier),
        "confidence_gate": sessions.get_confidence_gate_requirement(tier),
        "is_trading_allowed": tier != sessions.LiquidityTier.CLOSED,
        "session_reference": sessions.SESSIONS_REFERENCE.get(
            tier.value.upper() + "_LIQUIDITY",
            {"description": "Unknown"}
        )
    }


def is_during_peak_hours() -> bool:
    """Quick check: are we in peak liquidity hours (13:00-16:30 UTC)?"""
    tier = sessions.get_liquidity_tier(
        sessions.get_current_utc_hour(),
        sessions.get_current_utc_time().minute
    )
    return tier == sessions.LiquidityTier.PEAK


def is_market_closed() -> bool:
    """Check if market is currently closed."""
    tier = sessions.get_liquidity_tier(
        sessions.get_current_utc_hour(),
        sessions.get_current_utc_time().minute
    )
    return tier == sessions.LiquidityTier.CLOSED
