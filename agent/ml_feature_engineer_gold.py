"""
ML Feature Engineering for XAUUSD - Gold-Specific Features.
Extends base features with macro and session-based indicators.
"""

import pandas as pd
import numpy as np
from datetime import datetime


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

        # Gold-Specific Macro
        'usd_strength',
        'real_rates_momentum',
        'risk_sentiment',

        # Session-Based
        'session_hour_encoded',
        'day_of_week_encoded'
    ]

    @staticmethod
    def extract_features(df: pd.DataFrame, macro_data: dict = None) -> pd.DataFrame:
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

        # === GOLD-SPECIFIC MACRO FEATURES ===

        if macro_data is None:
            macro_data = {
                'usd_strength': 0.0,
                'real_rates_momentum': 0.0,
                'risk_sentiment': 50.0
            }

        # USD Strength (-1 to 1, negative = weak USD = gold bullish)
        features['usd_strength'] = macro_data.get('usd_strength', 0.0)

        # Real Rates Momentum (-1 to 1, negative = falling rates = gold bullish)
        features['real_rates_momentum'] = macro_data.get('real_rates_momentum', 0.0)

        # Risk Sentiment (0-100, higher = risk-off = gold bullish)
        features['risk_sentiment'] = macro_data.get('risk_sentiment', 50.0) / 100.0

        # === SESSION-BASED FEATURES ===

        # Encode current hour (0-23) as cyclical features
        current_hour = datetime.utcnow().hour
        features['session_hour_encoded'] = current_hour / 24.0

        # Encode day of week (0-6) as cyclical features
        current_dow = datetime.utcnow().weekday()
        features['day_of_week_encoded'] = current_dow / 7.0

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
        X = X.bfill().fillna(0)  # Fill NaN with backward fill, then 0

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
