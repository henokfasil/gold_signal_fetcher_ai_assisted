"""
XAUUSD Smart Money Concepts (SMC) scanner — v2 relaxed criteria.

Entry logic (top-down, 4H is the primary bias gate):
  1. 4H structure must be bullish (mandatory gate — replaces 1W gate)
  2. Must be inside ICT Killzone (London 06-10 UTC / NY AM 11-16 UTC)
  3. 1D + 1W alignment adds score bonus
  4. 4H BOS or CHoCH confirms institutional bias
  5. Liquidity sweep on 1H (stop hunt before reversal) adds confidence
  6. Price at fresh OB or FVG = entry zone
  7. 15M BOS/CHoCH = precise entry trigger
  8. ADX > 20 + RSI aligned = momentum confirmation

SL  = below OB low (15M OB preferred for tighter R:R)
TP  = nearest 4H swing high above price (next liquidity pool)

Target: 8-15 signals/week (vs 0 with v1 strict gates)

Public API mirrors gold_scanner.py:
    run_gold_scanner(metaapi_token, metaapi_account_id) -> Optional[dict]
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import pandas as pd

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange

from config import settings

logger = logging.getLogger(__name__)

SYMBOL = "XAUUSDxx"
_GOLD_SYMBOL_VARIANTS = ["XAUUSDxx", "XAUUSDm", "XAUUSD", "GOLD", "XAUUSDc", "XAUUSD.", "XAU/USD"]
_TF_MAP = {"1W": "1w", "1D": "1d", "4H": "4h", "1H": "1h", "15M": "15m"}

_NFP_BLOCK_START_H = 13
_NFP_BLOCK_START_M = 25
_NFP_BLOCK_END_H = 14
_NFP_BLOCK_END_M = 5

# FOMC dates (UTC day, statement at ~19:00 UTC; block 17:30-21:30 to cover EDT/EST)
_FOMC_DATES = frozenset([
    (2025, 1, 29), (2025, 3, 19), (2025, 5, 7),  (2025, 6, 18),
    (2025, 7, 30), (2025, 9, 17), (2025, 10, 29), (2025, 12, 10),
    (2026, 1, 28), (2026, 3, 18), (2026, 5, 6),  (2026, 6, 17),
    (2026, 7, 29), (2026, 9, 16), (2026, 10, 28), (2026, 12, 9),
])
_FOMC_BLOCK_START_H = 17
_FOMC_BLOCK_END_H = 22  # covers statement + press conference

# US CPI release dates (08:30 ET = 13:30 UTC; block 13:00-15:00)
_CPI_DATES = frozenset([
    (2025, 1, 15), (2025, 2, 12), (2025, 3, 12), (2025, 4, 10),
    (2025, 5, 13), (2025, 6, 11), (2025, 7, 15), (2025, 8, 12),
    (2025, 9, 10), (2025, 10, 15), (2025, 11, 12), (2025, 12, 10),
    (2026, 1, 14), (2026, 2, 11), (2026, 3, 11), (2026, 4, 8),
    (2026, 5, 13), (2026, 6, 10), (2026, 7, 15), (2026, 8, 12),
    (2026, 9, 9),  (2026, 10, 14), (2026, 11, 11), (2026, 12, 9),
])
_CPI_BLOCK_START_H = 13
_CPI_BLOCK_END_H = 15

# SMC constants — pull from settings if present, fall back to defaults
_OB_TOLERANCE_PCT = getattr(settings, "SMC_OB_TOLERANCE_PCT", 0.005)  # relaxed 0.3→0.5%
_MIN_FVG_SIZE_PCT = getattr(settings, "SMC_MIN_FVG_SIZE_PCT", 0.001)
_MAX_OB_LOOKBACK = getattr(settings, "SMC_MAX_OB_LOOKBACK", 20)
_MAX_FVG_AGE = getattr(settings, "SMC_MAX_FVG_AGE_CANDLES", 50)

# Swing detection neighbour count per timeframe
_SWING_N = {"1W": 5, "1D": 5, "4H": 3, "1H": 3, "15M": 2}

# ICT Killzones (UTC, wide enough to cover both EST and EDT)
# London Open:  06:00-10:00 UTC
# NY AM:        11:00-16:00 UTC  (includes Silver Bullet 15:00-16:00 UTC)
_KILLZONES = [
    (6, 10),   # London Open
    (11, 16),  # NY AM
]


# ---------------------------------------------------------------------------
# News guard (identical to gold_scanner)
# ---------------------------------------------------------------------------

def _is_first_friday_of_month(dt: datetime) -> bool:
    return dt.weekday() == 4 and dt.day <= 7


def check_news_guard() -> Tuple[bool, str]:
    now_utc = datetime.now(timezone.utc)
    weekday = now_utc.weekday()
    today = (now_utc.year, now_utc.month, now_utc.day)

    # Weekend / market closed
    if weekday == 5:
        return True, "NEWS_GUARD: GOLD market closed (weekend)"
    if weekday == 4 and now_utc.hour >= 21:
        return True, "NEWS_GUARD: GOLD market closed (Friday after 21:00 UTC)"
    if weekday == 6 and now_utc.hour < 22:
        return True, "NEWS_GUARD: GOLD market not yet open (Sunday before 22:00 UTC)"

    # NFP — first Friday of month, 13:25-14:05 UTC
    if _is_first_friday_of_month(now_utc):
        block_start = now_utc.replace(hour=_NFP_BLOCK_START_H, minute=_NFP_BLOCK_START_M, second=0, microsecond=0)
        block_end = now_utc.replace(hour=_NFP_BLOCK_END_H, minute=_NFP_BLOCK_END_M, second=0, microsecond=0)
        if block_start <= now_utc <= block_end:
            return True, "NEWS_GUARD: NFP release window (first Friday 13:25-14:05 UTC)"

    # FOMC — statement at ~19:00 UTC, press conference until ~21:00 UTC
    if today in _FOMC_DATES and _FOMC_BLOCK_START_H <= now_utc.hour < _FOMC_BLOCK_END_H:
        return True, f"NEWS_GUARD: FOMC statement window ({_FOMC_BLOCK_START_H}:00-{_FOMC_BLOCK_END_H}:00 UTC)"

    # CPI — release at 13:30 UTC, high volatility until ~15:00 UTC
    if today in _CPI_DATES and _CPI_BLOCK_START_H <= now_utc.hour < _CPI_BLOCK_END_H:
        return True, f"NEWS_GUARD: CPI release window ({_CPI_BLOCK_START_H}:00-{_CPI_BLOCK_END_H}:00 UTC)"

    return False, "NEWS_GUARD: clear"


def check_killzone() -> Tuple[bool, str]:
    """
    Return (in_killzone: bool, session_name: str).
    Only London Open and NY AM sessions have enough liquidity for reliable GOLD setups.
    """
    hour = datetime.now(timezone.utc).hour
    for start, end in _KILLZONES:
        if start <= hour < end:
            name = "London Open" if start == 6 else "NY AM"
            return True, f"KILLZONE: {name} ({start}:00-{end}:00 UTC)"
    return False, f"KILLZONE: Outside active sessions (current UTC hour={hour})"


# ---------------------------------------------------------------------------
# Candle fetching (identical to gold_scanner)
# ---------------------------------------------------------------------------

def _candles_to_df(candles: list, min_candles: int = 52) -> Optional[pd.DataFrame]:
    if not candles or len(candles) < min_candles:
        logger.warning(f"Insufficient candles: {len(candles) if candles else 0} (need {min_candles})")
        return None

    records = []
    for c in candles:
        try:
            records.append({
                "timestamp": c["time"] if isinstance(c["time"], datetime) else pd.to_datetime(c["time"]),
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c.get("tickVolume", 0)),
            })
        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Skipping malformed candle: {e}")

    if len(records) < min_candles:
        logger.warning(f"Too few valid candles after parsing: {len(records)} (need {min_candles})")
        return None

    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
    return df.iloc[:-1]  # Drop incomplete last candle


async def _resolve_symbol(account) -> Optional[str]:
    for variant in _GOLD_SYMBOL_VARIANTS:
        try:
            candles = await account.get_historical_candles(variant, "1d", datetime.utcnow(), 5)
            if candles and len(candles) > 0:
                logger.info(f"SMC scanner: resolved symbol as '{variant}'")
                return variant
        except Exception as e:
            logger.debug(f"Symbol variant '{variant}' not available: {e}")
    logger.error(f"SMC scanner: none of {_GOLD_SYMBOL_VARIANTS} returned data.")
    return None


async def _fetch_candles_safe(
    account, symbol: str, timeframe: str, count: int = 200, min_candles: int = 52
) -> Optional[pd.DataFrame]:
    for attempt in range(3):
        try:
            candles = await account.get_historical_candles(symbol, timeframe, datetime.utcnow(), count)
            df = _candles_to_df(candles, min_candles=min_candles)
            if df is not None:
                return df
            logger.warning(f"{symbol} {timeframe}: insufficient candles on attempt {attempt + 1}")
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"{symbol} {timeframe} attempt {attempt + 1} failed: {e}. Retrying in {wait}s.")
            await asyncio.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# Compatibility indicators (RSI, EMA, ATR, MACD — for notifier display only)
# ---------------------------------------------------------------------------

def _calc_rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    s = RSIIndicator(close=close, window=period).rsi()
    return round(float(s.iloc[-1]), 2) if not s.dropna().empty else None


def _calc_ema(close: pd.Series, window: int) -> Optional[float]:
    s = EMAIndicator(close=close, window=window).ema_indicator()
    return round(float(s.iloc[-1]), 4) if not s.dropna().empty else None


def _calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Optional[float]:
    s = AverageTrueRange(high=high, low=low, close=close, window=period).average_true_range()
    return round(float(s.iloc[-1]), 4) if not s.dropna().empty else None


def _calc_macd(close: pd.Series) -> dict:
    ind = MACD(close=close, window_slow=settings.MACD_SLOW, window_fast=settings.MACD_FAST, window_sign=settings.MACD_SIGNAL)
    macd_line = ind.macd()
    signal_line = ind.macd_signal()
    histogram = ind.macd_diff()

    crossover = False
    if len(macd_line.dropna()) >= 2:
        crossover = float(macd_line.iloc[-2]) < float(signal_line.iloc[-2]) and float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])

    hist_last3 = list(histogram.dropna().iloc[-3:].astype(float))
    return {
        "macd": round(float(macd_line.iloc[-1]), 6) if not macd_line.dropna().empty else 0.0,
        "signal": round(float(signal_line.iloc[-1]), 6) if not signal_line.dropna().empty else 0.0,
        "histogram": round(float(histogram.iloc[-1]), 6) if not histogram.dropna().empty else 0.0,
        "crossover": crossover,
        "hist_last3": hist_last3,
        "hist_improving": len(hist_last3) == 3 and hist_last3[0] < hist_last3[1] < hist_last3[2],
    }


def _calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Optional[float]:
    try:
        s = ADXIndicator(high=high, low=low, close=close, window=period).adx()
        return round(float(s.iloc[-1]), 2) if not s.dropna().empty else None
    except Exception:
        return None


def _calc_volume_spike(volume: pd.Series, window: int = 20) -> float:
    mean = float(volume.rolling(window).mean().iloc[-1]) or 1.0
    return round(float(volume.iloc[-1]) / max(mean, 1e-10), 2)


# ---------------------------------------------------------------------------
# Layer 2: Swing Detection
# ---------------------------------------------------------------------------

def detect_swing_highs(df: pd.DataFrame, n: int = 3) -> List[int]:
    """
    N-candle pivot high: high[i] strictly greater than N candles on each side.
    Returns list of bar indices.
    """
    highs = df["high"].values
    result = []
    for i in range(n, len(highs) - n):
        if all(highs[i] > highs[i - j] for j in range(1, n + 1)) and \
           all(highs[i] > highs[i + j] for j in range(1, n + 1)):
            result.append(i)
    return result


def detect_swing_lows(df: pd.DataFrame, n: int = 3) -> List[int]:
    """
    N-candle pivot low: low[i] strictly less than N candles on each side.
    """
    lows = df["low"].values
    result = []
    for i in range(n, len(lows) - n):
        if all(lows[i] < lows[i - j] for j in range(1, n + 1)) and \
           all(lows[i] < lows[i + j] for j in range(1, n + 1)):
            result.append(i)
    return result


# ---------------------------------------------------------------------------
# Layer 3: Market Structure Classification
# ---------------------------------------------------------------------------

def classify_market_structure(df: pd.DataFrame, swing_highs: List[int], swing_lows: List[int]) -> str:
    """
    HH + HL → 'bullish'
    LH + LL → 'bearish'
    Mixed   → 'ranging'
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "ranging"

    highs = df["high"].values
    lows = df["low"].values

    h1, h2 = highs[swing_highs[-2]], highs[swing_highs[-1]]
    l1, l2 = lows[swing_lows[-2]], lows[swing_lows[-1]]

    hh = h2 > h1
    hl = l2 > l1
    lh = h2 < h1
    ll = l2 < l1

    if hh and hl:
        return "bullish"
    if lh and ll:
        return "bearish"
    return "ranging"


# ---------------------------------------------------------------------------
# Layer 4: Break of Structure (BOS)
# ---------------------------------------------------------------------------

def detect_bos_up(df: pd.DataFrame, swing_highs: List[int]) -> Optional[dict]:
    """
    Most recent bullish BOS: a candle CLOSE (not wick) breaks above a prior swing high.
    Returns the latest such event, or None.
    """
    if len(swing_highs) < 2:
        return None

    closes = df["close"].values
    highs = df["high"].values
    best = None

    for sh_idx in swing_highs:
        swing_level = highs[sh_idx]
        for j in range(sh_idx + 1, len(closes)):
            if closes[j] > swing_level:
                if best is None or j > best["bos_index"]:
                    best = {
                        "bos_index": j,
                        "broken_level": round(swing_level, 4),
                        "swing_high_index": sh_idx,
                    }
                break

    return best


# ---------------------------------------------------------------------------
# Layer 4b: Change of Character (CHoCH) — fires earlier than BOS
# ---------------------------------------------------------------------------

def detect_choch_up(df: pd.DataFrame, swing_highs: List[int], swing_lows: List[int]) -> Optional[dict]:
    """
    Bullish CHoCH: after a swing low forms, price closes above the most recent
    prior swing high. Weaker than BOS but fires earlier — good for catching
    the turn before the full trend shift is confirmed.
    """
    if not swing_highs or not swing_lows:
        return None

    closes = df["close"].values
    highs = df["high"].values
    last_sl = swing_lows[-1]

    # Swing highs that existed BEFORE the most recent swing low
    prior_highs = [sh for sh in swing_highs if sh < last_sl]
    if not prior_highs:
        return None

    choch_level = highs[prior_highs[-1]]

    for j in range(last_sl + 1, len(closes)):
        if closes[j] > choch_level:
            return {
                "choch_index": j,
                "broken_level": round(choch_level, 4),
                "swing_low_index": last_sl,
            }
    return None


# ---------------------------------------------------------------------------
# Layer 4c: Liquidity Sweep Detection
# ---------------------------------------------------------------------------

def detect_liquidity_sweep_up(df: pd.DataFrame, swing_lows: List[int]) -> Optional[dict]:
    """
    Bullish liquidity sweep: price wicks below a prior swing low (sweeping
    retail stop orders) then closes back ABOVE it — classic institutional
    stop hunt before a bullish move.
    Searches the last 20 candles for the most recent sweep.
    """
    if len(swing_lows) < 2:
        return None

    lows = df["low"].values
    closes = df["close"].values
    n = len(lows)
    lookback_start = max(0, n - 20)

    for sl_idx in reversed(swing_lows[:-1]):
        sweep_level = lows[sl_idx]
        for j in range(max(sl_idx + 1, lookback_start), n):
            if lows[j] < sweep_level and closes[j] > sweep_level:
                return {
                    "sweep_index": j,
                    "swept_level": round(sweep_level, 4),
                    "wick_low": round(lows[j], 4),
                    "close_after": round(closes[j], 4),
                    "age_candles": n - j,
                }
    return None


# ---------------------------------------------------------------------------
# Layer 5: Order Block Detection
# ---------------------------------------------------------------------------

def find_last_order_block(df: pd.DataFrame, bos: Optional[dict]) -> Optional[dict]:
    """
    Bullish OB: the last bearish candle (close < open) in the _MAX_OB_LOOKBACK
    window before the BOS. This is where institutions loaded long positions.

    Mitigation check: if any candle CLOSED below ob_low after the BOS, the OB
    has been invalidated — institutions are no longer defending that level.
    """
    if bos is None:
        return None

    bos_idx = bos["bos_index"]
    lookback_start = max(0, bos_idx - _MAX_OB_LOOKBACK)

    opens = df["open"].values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(closes)

    ob_idx = None
    for i in range(lookback_start, bos_idx):
        if closes[i] < opens[i]:  # Bearish candle
            ob_idx = i

    if ob_idx is None:
        return None

    ob_high = highs[ob_idx]
    ob_low = lows[ob_idx]

    # A close below ob_low after BOS = OB fully mitigated, no longer valid
    mitigated = any(closes[j] < ob_low for j in range(bos_idx, n))

    return {
        "ob_index": ob_idx,
        "ob_high": round(ob_high, 4),
        "ob_low": round(ob_low, 4),
        "ob_open": round(opens[ob_idx], 4),
        "ob_close": round(closes[ob_idx], 4),
        "mitigated": mitigated,
    }


def is_price_at_order_block(price: float, ob: Optional[dict]) -> bool:
    """Price is within the OB zone. Rejects mitigated (spent) OBs."""
    if ob is None or ob.get("mitigated", False):
        return False
    tol = ob["ob_high"] * _OB_TOLERANCE_PCT
    return (ob["ob_low"] - tol) <= price <= (ob["ob_high"] + tol)


# ---------------------------------------------------------------------------
# Layer 5b: Fair Value Gap (FVG)
# ---------------------------------------------------------------------------

def detect_fvg(df: pd.DataFrame) -> Optional[dict]:
    """
    Bullish FVG: gap between candle[i-2].high and candle[i].low when candle[i-1]
    is a strong bullish candle (body >= 60% of range). Must not be mitigated.
    Searches backward, returns the most recent unmitigated FVG.
    """
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    closes = df["close"].values
    n = len(highs)

    for i in range(n - 1, max(2, n - _MAX_FVG_AGE), -1):
        body = closes[i - 1] - opens[i - 1]
        candle_range = highs[i - 1] - lows[i - 1]
        if body <= 0 or candle_range == 0:
            continue
        if body / candle_range < 0.6:
            continue

        fvg_low = highs[i - 2]
        fvg_high = lows[i]
        if fvg_high <= fvg_low:
            continue

        fvg_size_pct = (fvg_high - fvg_low) / fvg_low
        if fvg_size_pct < _MIN_FVG_SIZE_PCT:
            continue

        # Check not mitigated — no low has entered the gap since
        mitigated = any(lows[j] < fvg_low for j in range(i, n))
        if mitigated:
            continue

        return {
            "fvg_index": i - 1,
            "fvg_low": round(fvg_low, 4),
            "fvg_high": round(fvg_high, 4),
            "fvg_size_pct": round(fvg_size_pct * 100, 3),
            "age_candles": n - i,
        }

    return None


# ---------------------------------------------------------------------------
# Layer 5c: Premium / Discount zone
# ---------------------------------------------------------------------------

def classify_premium_discount(
    df: pd.DataFrame, swing_highs: List[int], swing_lows: List[int]
) -> dict:
    """
    Divide the most recent swing range into institutional zones.

    Discount zone  (0–40% of range)  — institutions buy here, we buy here
    Equilibrium    (40–60% of range) — neutral, lower confidence
    Premium zone   (60–100% of range) — institutions sell here, avoid buying

    Uses the last confirmed swing high and swing low on this timeframe.
    """
    if not swing_highs or not swing_lows:
        return {"zone": "unknown", "pct_in_range": 0.5, "range_high": None, "range_low": None}

    highs = df["high"].values
    lows = df["low"].values
    price = float(df["close"].iloc[-1])

    range_high = highs[swing_highs[-1]]
    range_low = lows[swing_lows[-1]]
    total_range = range_high - range_low

    if total_range <= 0:
        return {
            "zone": "unknown",
            "pct_in_range": 0.5,
            "range_high": round(range_high, 4),
            "range_low": round(range_low, 4),
            "equilibrium": round((range_high + range_low) / 2, 4),
        }

    pct = (price - range_low) / total_range  # 0 = at swing low, 1 = at swing high

    if pct <= 0.40:
        zone = "discount"
    elif pct >= 0.60:
        zone = "premium"
    else:
        zone = "equilibrium"

    return {
        "zone": zone,
        "pct_in_range": round(pct, 3),
        "range_high": round(range_high, 4),
        "range_low": round(range_low, 4),
        "equilibrium": round((range_high + range_low) / 2, 4),
    }


# ---------------------------------------------------------------------------
# Layer 6: TP target — nearest swing high above price
# ---------------------------------------------------------------------------

def find_nearest_swing_high_above(df: pd.DataFrame, swing_highs: List[int], price: float) -> Optional[float]:
    """Find the nearest swing high above current price (next liquidity pool = TP)."""
    highs = df["high"].values
    candidates = [highs[i] for i in swing_highs if highs[i] > price * 1.001]
    return round(min(candidates), 4) if candidates else None


# ---------------------------------------------------------------------------
# Layer 6: Scoring
# ---------------------------------------------------------------------------

def _score_smc_signal(
    struct_1w: str,
    struct_1d: str,
    struct_4h: str,
    bos_4h: Optional[dict],
    choch_4h: Optional[dict],
    price_at_ob: bool,
    fvg_1h: Optional[dict],
    pd_zone: dict,
    bos_15m: Optional[dict],
    choch_15m: Optional[dict],
    liquidity_sweep_1h: Optional[dict],
    adx_15m: Optional[float],
    rsi_15m: Optional[float],
    in_killzone: bool,
    struct_1w_bullish: bool,
) -> Tuple[int, bool, str]:
    """
    Score 0-100. Target: 8-15 signals/week.

    Mandatory gates (hard skip if failed):
      - 4H structure must be bullish (replaces 1W gate)
      - Must be inside ICT Killzone

    Scoring:
      +20  4H bullish (gate passed)
      +15  1D bullish
      +10  1W bullish (bonus, not gate)
      +15  4H BOS or CHoCH confirmed
      +20  Price at fresh OB or in FVG zone
      +10  Liquidity sweep on 1H (stop hunt detected)
      +10  15M BOS or CHoCH (precise entry trigger)
      +5   ADX(14) > 20 on 15M (trending, not choppy)
      +5   RSI(14) > 50 on 15M (momentum aligned)
    Total possible: 110 — capped at 100.
    Min score to fire: GOLD_MIN_SCORE (45 default)
    """
    # 4H gate: direction determines trade side
    # bearish 4H → SHORT signals; bullish 4H → LONG signals; ranging → use HTF bias
    if struct_4h == "ranging" and struct_1w not in ("bullish", "bearish") and struct_1d not in ("bullish", "bearish"):
        return 0, True, "SKIP: 4H ranging with no directional HTF context"

    # NOTE: Killzone is now a SOFT BONUS, not a hard gate (2026-06-16)
    # This allows 24/5 trading with position sizing adjustments per liquidity tier.
    # See agent/sessions.py and agent/liquidity_manager.py for session-aware adjustments.

    # Scoring: full credit for bullish 4H, partial for ranging
    score = 20 if struct_4h == "bullish" else 10

    # SOFT BONUS: Killzone now adds +5 points (was hard gate before)
    killzone_bonus = 5 if in_killzone else 0
    killzone_note = " (+5 Killzone bonus)" if in_killzone else " (outside peak hours)"

    if struct_1d == "bullish":
        score += 15

    if struct_1w_bullish:
        score += 10  # Weekly context bonus — still matters, just not a hard gate

    if bos_4h is not None or choch_4h is not None:
        score += 15

    if price_at_ob:
        score += 20
    elif fvg_1h is not None:
        score += 10  # FVG alone (without OB retest) is partial credit

    if liquidity_sweep_1h is not None:
        score += 10  # Stop hunt = institutional entry confirmed

    if bos_15m is not None or choch_15m is not None:
        score += 10

    if adx_15m is not None and adx_15m > 20:
        score += 5

    if rsi_15m is not None and rsi_15m > 50:
        score += 5

    # Apply Killzone soft bonus (changed from hard gate to soft bonus)
    score += killzone_bonus

    return min(score, 100), False, ""


# ---------------------------------------------------------------------------
# Layer 6: Signal builder
# ---------------------------------------------------------------------------

def _build_smc_signal(
    symbol: str,
    score: int,
    price: float,
    ob_4h: Optional[dict],
    ob_15m: Optional[dict],
    atr_1h: float,
    tp_level: Optional[float],
    news_reason: str,
    mtf_compat: dict,
    smc_data: dict,
) -> dict:
    """
    Build the full signal dict.

    SL priority:
      1. Below 15M OB low (tightest — best R:R when 15M entry is confirmed)
      2. Below 4H OB low (structural — used when no 15M OB)
      3. ATR-based fallback

    TP = nearest 4H swing high above price (next liquidity pool).
    """
    # --- SL: use tightest available structure level ---
    if ob_15m is not None and not ob_15m.get("mitigated"):
        stop_loss = round(ob_15m["ob_low"] * (1 - 0.0005), 4)
        sl_source = "15M_OB"
    elif ob_4h is not None and not ob_4h.get("mitigated"):
        stop_loss = round(ob_4h["ob_low"] * (1 - 0.0005), 4)
        sl_source = "4H_OB"
    else:
        stop_loss = round(price - atr_1h * settings.GOLD_ATR_SL_MULTIPLIER, 4)
        sl_source = "ATR"

    # --- TP ---
    if tp_level is not None:
        take_profit = tp_level
    else:
        take_profit = round(price + atr_1h * settings.GOLD_ATR_TP_MULTIPLIER, 4)

    sl_dist = price - stop_loss
    tp_dist = take_profit - price
    rr_ratio = round(tp_dist / sl_dist, 2) if sl_dist > 0 else 0.0
    sl_pct = round((sl_dist / price) * 100, 4) if price > 0 else 0.0
    tp_pct = round((tp_dist / price) * 100, 4) if price > 0 else 0.0

    entry_low = round(price * 0.9995, 4)
    entry_high = round(price * 1.0005, 4)

    # Compat fields for notifier.send_signal()
    ema20_1h = mtf_compat["1H"].get("ema20") or price
    ema50_1h = mtf_compat["1H"].get("ema50") or price
    ema20_4h = mtf_compat["4H"].get("ema20") or price
    ema50_4h = mtf_compat["4H"].get("ema50") or price

    macd_1h = mtf_compat["1H"].get("macd", {})

    return {
        "symbol": symbol,
        "score": score,
        "price": price,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rr_ratio": rr_ratio,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "atr": atr_1h,
        "sl_source": sl_source,
        "news_guard_status": news_reason,
        # Compat display fields
        "rsi_1h": mtf_compat["1H"].get("rsi"),
        "rsi_4h": mtf_compat["4H"].get("rsi"),
        "macd_1h": macd_1h.get("macd", 0.0),
        "signal_1h": macd_1h.get("signal", 0.0),
        "crossover_1h": macd_1h.get("crossover", False),
        "vol_spike": mtf_compat["1H"].get("vol_spike", 1.0),
        "ema_status_1h": "EMA20>EMA50" if ema20_1h > ema50_1h else "EMA20<EMA50",
        "ema_status_4h": "EMA20>EMA50" if ema20_4h > ema50_4h else "EMA20<EMA50",
        "ema20_4h": ema20_4h,
        "ema50_4h": ema50_4h,
        # risk_manager compat
        "indicators_4h": {
            "ema20": ema20_4h,
            "ema50": ema50_4h,
            "close": mtf_compat["4H"].get("price", price),
            "macd_histogram_last_3": mtf_compat["4H"].get("macd", {}).get("hist_last3", [0.0, 0.0, 0.0]),
            "smc_struct_4h": smc_data.get("struct_4h"),
        },
        # Full data for analyst
        "mtf": {
            "price": price,
            "1W": mtf_compat["1W"],
            "1D": mtf_compat["1D"],
            "4H": mtf_compat["4H"],
            "1H": mtf_compat["1H"],
            "smc": smc_data,
        },
    }


# ---------------------------------------------------------------------------
# Multi-timeframe data + SMC orchestration
# ---------------------------------------------------------------------------

def _run_smc_analysis(
    df_1w: pd.DataFrame,
    df_1d: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_15m: pd.DataFrame,
    symbol: str,
    news_reason: str,
) -> Optional[dict]:
    """Run full SMC pipeline and return signal dict or None."""

    price = round(float(df_1h["close"].iloc[-1]), 4)

    # --- Compat indicators for display / risk_manager ---
    try:
        mtf_compat = {
            "1W": {
                "price": round(float(df_1w["close"].iloc[-1]), 4),
                "rsi": _calc_rsi(df_1w["close"]),
                "ema20": _calc_ema(df_1w["close"], settings.EMA_FAST),
                "ema50": _calc_ema(df_1w["close"], settings.EMA_SLOW),
                "macd": _calc_macd(df_1w["close"]),
            },
            "1D": {
                "price": round(float(df_1d["close"].iloc[-1]), 4),
                "rsi": _calc_rsi(df_1d["close"]),
                "ema20": _calc_ema(df_1d["close"], settings.EMA_FAST),
                "ema50": _calc_ema(df_1d["close"], settings.EMA_SLOW),
                "macd": _calc_macd(df_1d["close"]),
            },
            "4H": {
                "price": round(float(df_4h["close"].iloc[-1]), 4),
                "rsi": _calc_rsi(df_4h["close"]),
                "ema20": _calc_ema(df_4h["close"], settings.EMA_FAST),
                "ema50": _calc_ema(df_4h["close"], settings.EMA_SLOW),
                "macd": _calc_macd(df_4h["close"]),
            },
            "1H": {
                "price": price,
                "rsi": _calc_rsi(df_1h["close"]),
                "ema20": _calc_ema(df_1h["close"], settings.EMA_FAST),
                "ema50": _calc_ema(df_1h["close"], settings.EMA_SLOW),
                "macd": _calc_macd(df_1h["close"]),
                "vol_spike": _calc_volume_spike(df_1h["volume"]),
            },
        }

        # Derive trend_up for 1W (used by analyst)
        ema50_1w = mtf_compat["1W"]["ema50"] or price
        mtf_compat["1W"]["trend_up"] = price > ema50_1w
        ema20_4h = mtf_compat["4H"]["ema20"] or price
        ema50_4h = mtf_compat["4H"]["ema50"] or price
        mtf_compat["4H"]["ema_bullish"] = ema20_4h > ema50_4h
        mtf_compat["4H"]["price_above_ema50"] = price > ema50_4h

    except Exception as e:
        logger.error(f"SMC compat indicator error: {e}")
        return None

    atr_1h = _calc_atr(df_1h["high"], df_1h["low"], df_1h["close"])
    if atr_1h is None:
        logger.error("SMC: ATR calculation failed — cannot assess volatility")
        return None

    # --- Layer 2: Swing detection ---
    sh_1w = detect_swing_highs(df_1w, _SWING_N["1W"])
    sl_1w = detect_swing_lows(df_1w, _SWING_N["1W"])
    sh_1d = detect_swing_highs(df_1d, _SWING_N["1D"])
    sl_1d = detect_swing_lows(df_1d, _SWING_N["1D"])
    sh_4h = detect_swing_highs(df_4h, _SWING_N["4H"])
    sl_4h = detect_swing_lows(df_4h, _SWING_N["4H"])
    sh_1h = detect_swing_highs(df_1h, _SWING_N["1H"])
    sl_1h = detect_swing_lows(df_1h, _SWING_N["1H"])

    # --- Layer 3: Market structure ---
    struct_1w = classify_market_structure(df_1w, sh_1w, sl_1w)
    struct_1d = classify_market_structure(df_1d, sh_1d, sl_1d)
    struct_4h = classify_market_structure(df_4h, sh_4h, sl_4h)
    struct_1h = classify_market_structure(df_1h, sh_1h, sl_1h)

    logger.info(f"SMC structure: 1W={struct_1w} | 1D={struct_1d} | 4H={struct_4h} | 1H={struct_1h}")

    # --- ICT Killzone check (early log, gate enforced in scoring) ---
    in_killzone, kz_reason = check_killzone()
    logger.info(f"SMC scanner: {kz_reason}")

    # --- Layer 4: BOS ---
    bos_4h = detect_bos_up(df_4h, sh_4h)
    bos_1h = detect_bos_up(df_1h, sh_1h)

    # --- Layer 4b: 15M swing + BOS (entry timing) ---
    sh_15m = detect_swing_highs(df_15m, _SWING_N["15M"])
    sl_15m = detect_swing_lows(df_15m, _SWING_N["15M"])
    struct_15m = classify_market_structure(df_15m, sh_15m, sl_15m)
    bos_15m = detect_bos_up(df_15m, sh_15m)

    # --- Layer 4b: CHoCH detection (fires earlier than BOS) ---
    choch_4h = detect_choch_up(df_4h, sh_4h, sl_4h)
    choch_15m = detect_choch_up(df_15m, sh_15m, sl_15m)

    # --- Layer 4c: Liquidity sweep (stop hunt before reversal) ---
    liquidity_sweep_1h = detect_liquidity_sweep_up(df_1h, sl_1h)

    # --- Layer 5: Order Block ---
    ob_4h = find_last_order_block(df_4h, bos_4h)
    ob_1h = find_last_order_block(df_1h, bos_1h)
    ob_15m = find_last_order_block(df_15m, bos_15m)

    # Use 1H or 15M OB for price-at-OB check (finest entry level)
    price_at_ob = (
        is_price_at_order_block(price, ob_15m)
        or is_price_at_order_block(price, ob_1h)
        or is_price_at_order_block(price, ob_4h)
    )

    # --- Layer 5b: FVG ---
    fvg_1h = detect_fvg(df_1h)

    # --- Layer 5c: Premium / Discount zone (use 4H range) ---
    pd_zone_4h = classify_premium_discount(df_4h, sh_4h, sl_4h)
    logger.info(
        f"SMC zone: {pd_zone_4h['zone'].upper()} "
        f"({pd_zone_4h['pct_in_range'] * 100:.1f}% of 4H range | "
        f"low={pd_zone_4h['range_low']} eq={pd_zone_4h.get('equilibrium')} high={pd_zone_4h['range_high']})"
    )

    # --- Momentum indicators for 15M ---
    adx_15m = _calc_adx(df_15m["high"], df_15m["low"], df_15m["close"])
    rsi_15m = _calc_rsi(df_15m["close"])

    # OB mitigation status for logging
    ob4_status = "fresh" if ob_4h and not ob_4h.get("mitigated") else ("mitigated" if ob_4h else "none")
    ob1_status = "fresh" if ob_1h and not ob_1h.get("mitigated") else ("mitigated" if ob_1h else "none")
    logger.info(
        f"SMC OB: 4H={ob4_status} | 1H={ob1_status} | price_at_ob={price_at_ob} | "
        f"CHoCH_4H={'YES' if choch_4h else 'NO'} | sweep_1H={'YES' if liquidity_sweep_1h else 'NO'} | "
        f"ADX_15M={adx_15m} | RSI_15M={rsi_15m}"
    )

    # --- Layer 6: Scoring ---
    score, skip, skip_reason = _score_smc_signal(
        struct_1w=struct_1w,
        struct_1d=struct_1d,
        struct_4h=struct_4h,
        bos_4h=bos_4h,
        choch_4h=choch_4h,
        price_at_ob=price_at_ob,
        fvg_1h=fvg_1h,
        pd_zone=pd_zone_4h,
        bos_15m=bos_15m,
        choch_15m=choch_15m,
        liquidity_sweep_1h=liquidity_sweep_1h,
        adx_15m=adx_15m,
        rsi_15m=rsi_15m,
        in_killzone=in_killzone,
        struct_1w_bullish=(struct_1w == "bullish"),
    )

    if skip:
        logger.info(f"SMC scanner: {skip_reason}")
        return None

    ob15_status = "fresh" if ob_15m and not ob_15m.get("mitigated") else ("mitigated" if ob_15m else "none")
    logger.info(
        f"SMC scanner: score={score}/100 | OB_4H={ob4_status} | OB_15M={ob15_status} | "
        f"BOS_4H={'YES' if bos_4h else 'NO'} | CHoCH_4H={'YES' if choch_4h else 'NO'} | "
        f"BOS_15M={'YES' if bos_15m else 'NO'} | CHoCH_15M={'YES' if choch_15m else 'NO'} | "
        f"FVG_1H={'YES' if fvg_1h else 'NO'} | sweep_1H={'YES' if liquidity_sweep_1h else 'NO'} | "
        f"price_at_ob={price_at_ob} | zone={pd_zone_4h['zone']}"
    )

    if score < settings.GOLD_MIN_SCORE:
        logger.info(f"SMC scanner: score {score} below GOLD_MIN_SCORE {settings.GOLD_MIN_SCORE} — no signal")
        return None

    # --- TP: nearest 4H swing high above price ---
    tp_level = find_nearest_swing_high_above(df_4h, sh_4h, price)
    if tp_level is None:
        logger.info("SMC scanner: no 4H swing high above price — falling back to ATR TP")

    # Package SMC context for analyst
    smc_data = {
        "struct_1w": struct_1w,
        "struct_1d": struct_1d,
        "struct_4h": struct_4h,
        "struct_1h": struct_1h,
        "struct_15m": struct_15m,
        "bos_4h": bos_4h,
        "choch_4h": choch_4h,
        "bos_1h": bos_1h,
        "bos_15m": bos_15m,
        "choch_15m": choch_15m,
        "liquidity_sweep_1h": liquidity_sweep_1h,
        "ob_4h": ob_4h,
        "ob_1h": ob_1h,
        "ob_15m": ob_15m,
        "price_at_ob": price_at_ob,
        "fvg_1h": fvg_1h,
        "pd_zone": pd_zone_4h,
        "adx_15m": adx_15m,
        "rsi_15m": rsi_15m,
        "in_killzone": in_killzone,
        "killzone_reason": kz_reason,
        "tp_swing_high": tp_level,
        "swing_highs_4h_count": len(sh_4h),
        "swing_lows_4h_count": len(sl_4h),
    }

    # SL: 4H OB is the structural level; 15M OB handled inside _build_smc_signal
    sl_ob = ob_4h if ob_4h is not None else ob_1h

    signal = _build_smc_signal(
        symbol=symbol,
        score=score,
        price=price,
        ob_4h=sl_ob,
        ob_15m=ob_15m,
        atr_1h=atr_1h,
        tp_level=tp_level,
        news_reason=news_reason,
        mtf_compat=mtf_compat,
        smc_data=smc_data,
    )

    logger.info(
        f"SMC scanner: SIGNAL | price={price} | score={score} | "
        f"SL={signal['stop_loss']} | TP={signal['take_profit']} | RR={signal['rr_ratio']}"
    )
    return signal


# ---------------------------------------------------------------------------
# Async orchestrator
# ---------------------------------------------------------------------------

async def _run_gold_scanner_async(metaapi_token: str, metaapi_account_id: str) -> Optional[dict]:
    try:
        from metaapi_cloud_sdk import MetaApi
    except ImportError:
        logger.error("metaapi_cloud_sdk is not installed. Run: pip install metaapi-cloud-sdk")
        return None

    news_blocked, news_reason = check_news_guard()
    if news_blocked:
        logger.info(f"SMC scanner: {news_reason} — skipping scan")
        return None

    api = None
    try:
        api = MetaApi(token=metaapi_token)
        account = await api.metatrader_account_api.get_account(metaapi_account_id)

        logger.info("SMC scanner: waiting for MT5 account to be deployed...")
        await account.wait_deployed()
        logger.info("SMC scanner: account deployed, fetching candles...")

        symbol = await _resolve_symbol(account)
        if symbol is None:
            return None

        logger.info(f"SMC scanner: fetching {symbol} candles for 1W, 1D, 4H, 1H, 15M...")
        df_1w  = await _fetch_candles_safe(account, symbol, _TF_MAP["1W"],  200)
        df_1d  = await _fetch_candles_safe(account, symbol, _TF_MAP["1D"],  200)
        df_4h  = await _fetch_candles_safe(account, symbol, _TF_MAP["4H"],  200)
        df_1h  = await _fetch_candles_safe(account, symbol, _TF_MAP["1H"],  200)
        df_15m = await _fetch_candles_safe(account, symbol, _TF_MAP["15M"], 200, min_candles=20)

        for tf_name, df in [("1W", df_1w), ("1D", df_1d), ("4H", df_4h), ("1H", df_1h)]:
            if df is None:
                logger.error(f"SMC scanner: failed to fetch {tf_name} candles for {symbol}")
                return None

        if df_15m is None:
            logger.warning("SMC scanner: 15M candles unavailable — proceeding without 15M layer")
            df_15m = df_1h.iloc[-40:].reset_index(drop=True)  # Fallback: use last 40 1H bars

        logger.info("SMC scanner: all candles fetched. Running SMC analysis...")
        return _run_smc_analysis(df_1w, df_1d, df_4h, df_1h, df_15m, symbol, news_reason)

    except Exception as e:
        logger.error(f"SMC scanner: unexpected error: {e}")
        return None
    finally:
        if api is not None:
            try:
                await api.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Public entry point (identical signature to gold_scanner.py)
# ---------------------------------------------------------------------------

def run_gold_scanner(metaapi_token: str, metaapi_account_id: str) -> Optional[dict]:
    """
    Synchronous entry point for the XAUUSD SMC scanner.
    Drop-in replacement for gold_scanner.run_gold_scanner().
    Returns a signal dict if a qualifying setup is found, or None.
    """
    try:
        return asyncio.run(_run_gold_scanner_async(metaapi_token, metaapi_account_id))
    except Exception as e:
        logger.error(f"SMC scanner: asyncio.run failed: {e}")
        return None
