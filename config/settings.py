"""
Configuration settings for Gold Signal Fetcher AI-Assisted System C
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / '.env')

STRATEGY_CONFIG_PATH = Path(
    os.getenv('GOLD_STRATEGY_CONFIG', PROJECT_ROOT / 'config' / 'gold_strategy_params.json')
)
try:
    STRATEGY_CONFIG = json.loads(STRATEGY_CONFIG_PATH.read_text())
except (OSError, json.JSONDecodeError):
    STRATEGY_CONFIG = {}

# Timezone
TIMEZONE = os.getenv('LOCAL_TIMEZONE', 'Europe/Rome')

# Trading Configuration
PAPER_TRADING = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
PAPER_ACCOUNT_SIZE = float(os.getenv('PAPER_ACCOUNT_SIZE', '10000'))
SCAN_INTERVAL_MINUTES = int(os.getenv('SCAN_INTERVAL_MINUTES', '5'))
TRADE_EXPIRY_HOURS = int(os.getenv('TRADE_EXPIRY_HOURS', '48'))

# API Keys and Credentials
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
METAAPI_TOKEN = os.getenv('METAAPI_TOKEN')
METAAPI_ACCOUNT_ID = os.getenv('METAAPI_ACCOUNT_ID')
PRICE_DATA_PROVIDER = os.getenv('PRICE_DATA_PROVIDER', 'tradingview').lower()

# ML Model Configuration
ML_CONFIDENCE_THRESHOLD = float(os.getenv('ML_CONFIDENCE_THRESHOLD', '0.35'))
ML_MODEL_PATH = Path(os.getenv('ML_MODEL_PATH', PROJECT_ROOT / 'models' / 'xgboost_gold_model_v2.pkl'))
ML_MODEL_METADATA_PATH = Path(
    os.getenv('ML_MODEL_METADATA_PATH', PROJECT_ROOT / 'models' / 'xgboost_gold_model_v2.metadata.json')
)

# Risk Management
RISK_PER_TRADE_PCT = float(os.getenv('RISK_PER_TRADE_PCT', '1.0'))
MAX_OPEN_TRADES = int(os.getenv('MAX_OPEN_TRADES', '10'))
MIN_RR_RATIO = float(os.getenv('MIN_RR_RATIO', '2.0'))
DAILY_LOSS_CAP_PCT = float(os.getenv('DAILY_LOSS_CAP_PCT', '3.0'))
WEEKLY_LOSS_CAP_PCT = float(os.getenv('WEEKLY_LOSS_CAP_PCT', '6.0'))

# Strategy Configuration
SYMBOL = os.getenv('SYMBOL', 'XAUUSD')
GOLD_MODE = os.getenv('GOLD_MODE', 'true').lower() == 'true'
EMA_FAST = int(os.getenv('EMA_FAST', '20'))
EMA_SLOW = int(os.getenv('EMA_SLOW', '50'))
MACD_FAST = int(os.getenv('MACD_FAST', '12'))
MACD_SLOW = int(os.getenv('MACD_SLOW', '26'))
MACD_SIGNAL = int(os.getenv('MACD_SIGNAL', '9'))
GOLD_MIN_SCORE = int(os.getenv('GOLD_MIN_SCORE', '45'))
GOLD_ATR_SL_MULTIPLIER = float(os.getenv('GOLD_ATR_SL_MULTIPLIER', '1.5'))
GOLD_ATR_TP_MULTIPLIER = float(os.getenv('GOLD_ATR_TP_MULTIPLIER', '3.0'))

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = Path(os.getenv('LOG_FILE', PROJECT_ROOT / 'logs' / 'gold_scanner_ai.log'))

# CSV Paths
PAPER_TRADES_CSV = Path(os.getenv('PAPER_TRADES_CSV', PROJECT_ROOT / 'data' / 'paper_trades_ai.csv'))
FORWARD_FEATURES_CSV = Path(
    os.getenv('FORWARD_FEATURES_CSV', PROJECT_ROOT / 'data' / 'forward_candidate_features.csv')
)
SYSTEM_A_CSV = Path(os.getenv('SYSTEM_A_CSV', '/root/Gold_Signal_Fetcher/data/paper_trades.csv'))
TRADINGVIEW_SNAPSHOT_PATH = Path(
    os.getenv('TRADINGVIEW_SNAPSHOT_PATH', '/tmp/tradingview_snapshot.json')
)
MACRO_SNAPSHOT_PATH = Path(os.getenv('MACRO_SNAPSHOT_PATH', '/tmp/gold_macro_snapshot.json'))
SNAPSHOT_MAX_AGE_SECONDS = int(os.getenv('SNAPSHOT_MAX_AGE_SECONDS', '900'))
DASHBOARD_FEED_MAX_AGE_SECONDS = int(os.getenv('DASHBOARD_FEED_MAX_AGE_SECONDS', '1200'))


def strategy_value(section: str, key: str, default):
    """Read a strategy setting while keeping environment-safe defaults."""
    return STRATEGY_CONFIG.get(section, {}).get(key, default)

# Validation
def validate_settings():
    """Validate that all required settings are configured."""
    required_keys = [
        'ANTHROPIC_API_KEY',
        'TELEGRAM_BOT_TOKEN',
        'TELEGRAM_CHAT_ID',
    ]
    if PRICE_DATA_PROVIDER == 'metaapi':
        required_keys.extend(['METAAPI_TOKEN', 'METAAPI_ACCOUNT_ID'])
    missing = [k for k in required_keys if not globals().get(k)]
    if missing:
        import logging
        logging.warning(f"Missing settings: {', '.join(missing)}")
    return len(missing) == 0
