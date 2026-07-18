#!/usr/bin/env python3
"""Send unified paper-research metrics to the configured Telegram chat."""

import sys

from agent.notifier import Notifier
from config import settings
from dashboard import calculate_metrics


def get_metrics(csv_path, is_system_a=False):
    """Compatibility wrapper for validation scripts; System A is retired."""
    return calculate_metrics(csv_path)


if __name__ == "__main__":
    try:
        metrics = get_metrics(settings.PAPER_TRADES_CSV)
        Notifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID).send_metrics(metrics)
        print("[METRICS] Unified paper metrics sent to Telegram")
    except Exception as exc:
        print(f"[METRICS] Error: {exc}")
        sys.exit(1)
