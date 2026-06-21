#!/usr/bin/env python3
"""
Send daily System A vs System C metrics to Telegram at 20:00 Rome time.
Run via cron: 0 18 * * 1-5 (18:00 UTC = 20:00 Rome time in summer)
"""

import os
import sys
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# Load env
load_dotenv("/root/gold_signal_fetcher_ai_assisted/.env")

# Import notifier
sys.path.insert(0, "/root/gold_signal_fetcher_ai_assisted")
from agent.notifier import Notifier

def get_metrics(csv_path, is_system_a=False):
    """Calculate metrics from CSV."""
    try:
        if not Path(csv_path).exists():
            return {'status': 'Not started', 'signals': 0, 'wins': 0, 'losses': 0}

        df = pd.read_csv(csv_path)
        if df.empty:
            return {'status': 'No trades yet', 'signals': 0, 'wins': 0, 'losses': 0}

        # Handle different column names
        pnl_col = 'pnl' if 'pnl' in df.columns else 'profit_pct'

        # Filter out blocked signals (System A only)
        if is_system_a and 'status' in df.columns:
            df = df[df['status'] != 'BLOCKED']

        if df.empty:
            return {'status': 'No executed trades', 'signals': 0, 'wins': 0, 'losses': 0}

        wins = df[df[pnl_col] > 0]
        losses = df[df[pnl_col] < 0]
        total = len(df)

        win_rate = (len(wins) / total * 100) if total > 0 else 0
        total_pnl = df[pnl_col].sum()

        return {
            'status': 'Running',
            'signals': total,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': f"{win_rate:.1f}%",
            'total_pnl': f"{total_pnl:.2f}",
        }
    except Exception as e:
        return {'status': f'Error: {str(e)}', 'signals': 0, 'wins': 0, 'losses': 0}


if __name__ == "__main__":
    try:
        # Get metrics
        a_metrics = get_metrics("/root/Gold_Signal_Fetcher/data/paper_trades.csv", is_system_a=True)
        c_metrics = get_metrics("/root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv")

        # Send via notifier
        notifier = Notifier(
            token=os.environ.get("TELEGRAM_TOKEN"),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
        )

        notifier.send_metrics(a_metrics, c_metrics)
        print("[METRICS] Daily metrics sent to Telegram")

    except Exception as e:
        print(f"[METRICS] Error: {e}")
        sys.exit(1)
