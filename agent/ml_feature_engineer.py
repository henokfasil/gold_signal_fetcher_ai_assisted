"""
ML Feature Engineering for XAUUSD signals.
Extracts technical indicators and market context features for model prediction.
"""

import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, MACD, Stoch
from ta.volatility import AverageTrueRange, BollingerBands
from ta.trend import ADXIndicator


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

        # Momentum
        features['rsi_14'] = RSIIndicator(close=df['close'], window=14).rsi()
        features['rsi_oversold'] = (features['rsi_14'] < 35).astype(int)
        features['rsi_overbought'] = (features['rsi_14'] > 65).astype(int)

        # MACD
        macd = MACD(close=df['close'], window_fast=12, window_slow=26, window_sign=9)
        features['macd'] = macd.macd()
        features['macd_signal'] = macd.macd_signal()
        features['macd_diff'] = macd.macd_diff()

        # ATR (volatility)
        features['atr_14'] = AverageTrueRange(
            high=df['high'],
            low=df['low'],
            close=df['close'],
            window=14
        ).average_true_range()

        # Bollinger Bands
        bb = BollingerBands(close=df['close'], window=20, window_dev=2)
        features['bb_upper'] = bb.bollinger_hband()
        features['bb_lower'] = bb.bollinger_lband()
        features['bb_width'] = features['bb_upper'] - features['bb_lower']
        features['bb_position'] = (
            (df['close'] - features['bb_lower']) / features['bb_width']
        ).clip(0, 1)

        # ADX (trend strength)
        features['adx_14'] = ADXIndicator(
            high=df['high'],
            low=df['low'],
            close=df['close'],
            window=14
        ).adx()

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
        X = X.fillna(method='bfill').fillna(0)  # Fill NaN with forward fill, then 0

        return X.values
