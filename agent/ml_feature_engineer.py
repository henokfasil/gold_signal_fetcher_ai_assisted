"""
ML Feature Engineering for XAUUSD signals.
Extracts technical indicators and market context features for model prediction.
"""

import pandas as pd
import numpy as np


class FeatureEngineer:
    """Extract ML features from OHLCV data."""

    @staticmethod
    def extract_features(df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract technical features from OHLCV data.

        Args:
            df: DataFrame with columns [open, high, low, close, volume]

        Returns:
            DataFrame with extracted features
        """
        features = df.copy()

        # Momentum - RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        features['rsi_14'] = 100 - (100 / (1 + rs))
        features['rsi_oversold'] = (features['rsi_14'] < 35).astype(int)
        features['rsi_overbought'] = (features['rsi_14'] > 65).astype(int)

        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        features['macd'] = exp1 - exp2
        features['macd_signal'] = features['macd'].ewm(span=9, adjust=False).mean()
        features['macd_diff'] = features['macd'] - features['macd_signal']

        # ATR (volatility)
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        features['atr_14'] = tr.rolling(14).mean()

        # Bollinger Bands
        sma = df['close'].rolling(20).mean()
        std = df['close'].rolling(20).std()
        features['bb_upper'] = sma + (std * 2)
        features['bb_lower'] = sma - (std * 2)
        features['bb_width'] = features['bb_upper'] - features['bb_lower']
        features['bb_position'] = (
            (df['close'] - features['bb_lower']) / (features['bb_width'] + 1e-6)
        ).clip(0, 1)

        # ADX (simplified trend strength using DX)
        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        tr_sum = tr.rolling(14).sum()
        plus_di = 100 * (plus_dm.rolling(14).sum() / tr_sum)
        minus_di = 100 * (minus_dm.rolling(14).sum() / tr_sum)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-6)
        features['adx_14'] = dx.rolling(14).mean()

        # Price action
        features['close_above_ma20'] = (df['close'] > df['close'].rolling(20).mean()).astype(int)
        features['close_above_ma50'] = (df['close'] > df['close'].rolling(50).mean()).astype(int)
        features['price_momentum'] = df['close'].pct_change(5)
        features['volatility'] = df['close'].pct_change().rolling(20).std()

        # Volume
        features['volume_ma'] = df['volume'].rolling(20).mean()
        features['volume_spike'] = (df['volume'] / features['volume_ma']) - 1

        return features

    @staticmethod
    def prepare_for_model(features: pd.DataFrame) -> np.ndarray:
        """
        Prepare features for ML model prediction.

        Args:
            features: DataFrame with extracted features

        Returns:
            Array of feature values, NaN-filled rows excluded
        """
        feature_cols = [
            'rsi_14', 'rsi_oversold', 'rsi_overbought',
            'macd', 'macd_signal', 'macd_diff',
            'atr_14', 'bb_upper', 'bb_lower', 'bb_width', 'bb_position',
            'adx_14',
            'close_above_ma20', 'close_above_ma50',
            'price_momentum', 'volatility',
            'volume_spike'
        ]

        X = features[feature_cols].copy()
        X = X.bfill().fillna(0)  # Fill NaN with backward fill, then 0

        return X.values
