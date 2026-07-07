"""
Configuration settings for Gold Signal Fetcher AI-Assisted System C
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / '.env')

# Timezone
TIMEZONE = os.getenv('LOCAL_TIMEZONE', 'Europe/Rome')

# Trading Configuration
PAPER_TRADING = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
PAPER_ACCOUNT_SIZE = float(os.getenv('PAPER_ACCOUNT_SIZE', '10000'))
SCAN_INTERVAL_MINUTES = int(os.getenv('SCAN_INTERVAL_MINUTES', '5'))
TRADE_EXPIRY_HOURS = int(os.getenv('TRADE_EXPIRY_HOURS', '48'))

# API Keys and Credentials
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
METAAPI_TOKEN = os.getenv('METAAPI_TOKEN')
METAAPI_ACCOUNT_ID = os.getenv('METAAPI_ACCOUNT_ID')

# ML Model Configuration
ML_CONFIDENCE_THRESHOLD = float(os.getenv('ML_CONFIDENCE_THRESHOLD', '0.35'))
ML_MODEL_PATH = Path(__file__).parent.parent / 'models' / 'xgboost_gold_model_v2.pkl'

# Risk Management
RISK_PER_TRADE_PCT = float(os.getenv('RISK_PER_TRADE_PCT', '1.0'))
MAX_OPEN_TRADES = int(os.getenv('MAX_OPEN_TRADES', '10'))
MIN_RR_RATIO = float(os.getenv('MIN_RR_RATIO', '2.0'))
DAILY_LOSS_CAP_PCT = float(os.getenv('DAILY_LOSS_CAP_PCT', '3.0'))
WEEKLY_LOSS_CAP_PCT = float(os.getenv('WEEKLY_LOSS_CAP_PCT', '6.0'))

# Strategy Configuration
SYMBOL = os.getenv('SYMBOL', 'XAUUSD')
GOLD_MODE = os.getenv('GOLD_MODE', 'true').lower() == 'true'

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = Path('/var/log/gold_scanner_ai.log')

# CSV Paths
PAPER_TRADES_CSV = Path(__file__).parent.parent / 'data' / 'paper_trades_ai.csv'
SYSTEM_A_CSV = Path('/root/Gold_Signal_Fetcher/data/paper_trades.csv')

# Validation
def validate_settings():
    """Validate that all required settings are configured."""
    required_keys = [
        'ANTHROPIC_API_KEY',
        'TELEGRAM_BOT_TOKEN',
        'TELEGRAM_CHAT_ID',
        'METAAPI_TOKEN',
        'METAAPI_ACCOUNT_ID',
    ]
    missing = [k for k in required_keys if not globals().get(k)]
    if missing:
        import logging
        logging.warning(f"Missing settings: {', '.join(missing)}")
    return len(missing) == 0
