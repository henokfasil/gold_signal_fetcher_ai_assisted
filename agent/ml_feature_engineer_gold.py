"""
ML Feature Engineering for XAUUSD - Gold-Specific Features.
Extends base features with macro and session-based indicators.
"""

import pandas as pd
import numpy as np


class GoldFeatureEngineer:
    """Extract gold-optimized ML features from OHLCV data."""

    FEATURE_COLS = [
        # Technical - Momentum
        'rsi_14',
        'macd',
        'macd_signal',
        'macd_diff',
        'adx_14',

        # Technical - Volatility
        'atr_14',
        'bb_width',
        'bb_position',
        'close_above_bb_upper',
        'close_above_bb_lower',

        # Technical - Trend
        'close_above_ma20',
        'close_above_ma50',
        'price_momentum',
        'volatility',

        # Volume
        'volume_spike',

        # Session-Based
        'session_hour_encoded',
        'day_of_week_encoded',
        'direction_encoded',

        # Candidate-known SMC and risk context
        'rr_ratio',
        'smc_score_encoded',
        'atr_pct',
        'structure_1w_encoded',
        'structure_1d_encoded',
        'structure_4h_encoded',
        'structure_1h_encoded',
        'bos_4h_present',
        'choch_4h_present',
        'bos_15m_present',
        'choch_15m_present',
        'liquidity_sweep_1h_present',
        'price_at_ob',
        'fvg_1h_present',
        'premium_discount_position',
    ]

    @staticmethod
    def extract_features(df: pd.DataFrame, macro_data: dict = None, direction: str = None,
                         candidate_context: dict = None) -> pd.DataFrame:
        """
        Extract gold-specific features from OHLCV data.

        Args:
            df: DataFrame with [open, high, low, close, volume]
            macro_data: Dict with USD, rates, VIX data (optional)

        Returns:
            DataFrame with all features
        """
        features = df.copy()

        # === TECHNICAL FEATURES ===

        # RSI (14)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        features['rsi_14'] = 100 - (100 / (1 + rs))

        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        features['macd'] = exp1 - exp2
        features['macd_signal'] = features['macd'].ewm(span=9, adjust=False).mean()
        features['macd_diff'] = features['macd'] - features['macd_signal']

        # ATR (14)
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        features['atr_14'] = tr.rolling(14).mean()

        # Bollinger Bands (20)
        sma = df['close'].rolling(20).mean()
        std = df['close'].rolling(20).std()
        features['bb_upper'] = sma + (std * 2)
        features['bb_lower'] = sma - (std * 2)
        features['bb_width'] = features['bb_upper'] - features['bb_lower']
        features['bb_position'] = (
            (df['close'] - features['bb_lower']) / (features['bb_width'] + 1e-6)
        ).clip(0, 1)
        features['close_above_bb_upper'] = (df['close'] > features['bb_upper']).astype(int)
        features['close_above_bb_lower'] = (df['close'] > features['bb_lower']).astype(int)

        # ADX (14)
        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        tr_sum = tr.rolling(14).sum()
        plus_di = 100 * (plus_dm.rolling(14).sum() / tr_sum)
        minus_di = 100 * (minus_dm.rolling(14).sum() / tr_sum)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-6)
        features['adx_14'] = dx.rolling(14).mean()

        # Price Action
        features['close_above_ma20'] = (df['close'] > df['close'].rolling(20).mean()).astype(int)
        features['close_above_ma50'] = (df['close'] > df['close'].rolling(50).mean()).astype(int)
        features['price_momentum'] = df['close'].pct_change(5)
        features['volatility'] = df['close'].pct_change().rolling(20).std()

        # Volume
        features['volume_ma'] = df['volume'].rolling(20).mean()
        features['volume_spike'] = (df['volume'] / features['volume_ma']) - 1

        # === SESSION-BASED FEATURES ===

        # Derive session values from each candle timestamp. Using wall-clock time
        # here would make historical training rows contain the inference time.
        if isinstance(df.index, pd.DatetimeIndex):
            timestamps = pd.Series(df.index, index=df.index)
        elif 'timestamp' in df.columns:
            timestamps = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
        else:
            timestamps = pd.Series(pd.NaT, index=df.index)
        features['session_hour_encoded'] = timestamps.dt.hour.fillna(0) / 24.0
        features['day_of_week_encoded'] = timestamps.dt.dayofweek.fillna(0) / 7.0
        # Candidate direction is part of the prediction question: +1 BUY,
        # -1 SELL, 0 only for non-candidate historical feature exploration.
        features['direction_encoded'] = {"BUY": 1.0, "SELL": -1.0}.get(
            str(direction or "").upper(), 0.0
        )

        context = candidate_context or {}
        smc = context.get("smc", {})
        structure_value = {"bullish": 1.0, "bearish": -1.0, "ranging": 0.0}
        features["rr_ratio"] = float(context.get("rr_ratio") or 0)
        features["smc_score_encoded"] = float(context.get("score") or 0) / 100.0
        close = float(df["close"].iloc[-1]) or 1.0
        features["atr_pct"] = float(context.get("atr") or 0) / close
        for timeframe in ("1w", "1d", "4h", "1h"):
            features[f"structure_{timeframe}_encoded"] = structure_value.get(
                smc.get(f"struct_{timeframe}"), 0.0)
        for name in ("bos_4h", "choch_4h", "bos_15m", "choch_15m",
                     "liquidity_sweep_1h", "fvg_1h"):
            features[f"{name}_present"] = float(bool(smc.get(name)))
        features["price_at_ob"] = float(bool(smc.get("price_at_ob")))
        features["premium_discount_position"] = float(
            (smc.get("pd_zone") or {}).get("pct_in_range", 0.5))

        return features

    @staticmethod
    def prepare_for_model(features: pd.DataFrame) -> np.ndarray:
        """
        Prepare features for ML model prediction.

        Args:
            features: DataFrame with extracted features

        Returns:
            Array of feature values (NaN rows excluded)
        """
        X = features[GoldFeatureEngineer.FEATURE_COLS].copy()
        # Forward fill uses only information available at or before each row.
        # Backward filling would leak future indicator values into early rows.
        X = X.ffill().fillna(0)

        return X.values

    @staticmethod
    def get_feature_importance(model) -> dict:
        """
        Get feature importance from trained model.

        Args:
            model: Trained XGBoost model

        Returns:
            Dict of feature names -> importance scores
        """
        if model is None:
            return {}

        importance = model.get_booster().get_score(importance_type='weight')
        return {
            GoldFeatureEngineer.FEATURE_COLS[int(k.split('_')[1])]: v
            for k, v in importance.items()
            if k.startswith('f_')
        }
