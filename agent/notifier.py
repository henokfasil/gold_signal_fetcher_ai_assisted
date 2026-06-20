import asyncio
import logging
from datetime import datetime

import pytz

from config import settings

logger = logging.getLogger(__name__)

_PARIS_TZ = pytz.timezone(settings.TIMEZONE)


def _paris_now_str() -> str:
    return datetime.now(_PARIS_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


class Notifier:
    """Telegram notification wrapper. All sends are fire-and-forget with full error isolation."""

    def __init__(self, token: str, chat_id: str, scan_only: bool = False):
        self.token = token
        self.chat_id = chat_id
        self.scan_only = scan_only
        self._prefix = "[SCAN ONLY] " if scan_only else ""

    def _run_async(self, coro):
        """Run async coroutine safely regardless of event loop state."""
        try:
            try:
                asyncio.get_running_loop()
                # There is a running loop — run in a separate thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result(timeout=30)
            except RuntimeError:
                # No running loop — create a fresh one
                return asyncio.run(coro)
        except Exception as e:
            logger.error(f"Async runner error: {e}")

    async def _send_async(self, text: str):
        try:
            from telegram import Bot
            from telegram.constants import ParseMode
            bot = Bot(token=self.token)
            await bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    def send(self, text: str):
        """Send a message. Fails silently - never crash the main process."""
        try:
            full_text = self._prefix + text
            self._run_async(self._send_async(full_text))
        except Exception as e:
            logger.error(f"Notifier.send error: {e}")

    def send_signal(self, signal_id: str, signal: dict, analysis: dict, trend_filter_result: str):
        """Send full signal notification."""
        try:
            msg = (
                f"🔍 PAPER SIGNAL #{signal_id}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"Coin: {signal['symbol']}\n"
                f"Score: {signal['score']}/100 | Quality: {analysis.get('signal_quality', 'N/A')}\n"
                f"Trend Filter: {trend_filter_result}\n\n"
                f"💰 Entry: {signal['entry_low']} - {signal['entry_high']}\n"
                f"🎯 Take Profit: {signal['take_profit']} (+{signal['tp_pct']}%)\n"
                f"🛑 Stop Loss: {signal['stop_loss']} (-{signal['sl_pct']}%)\n"
                f"⚖️ R/R Ratio: {signal['rr_ratio']}\n\n"
                f"📝 {analysis.get('plain_english_summary', 'N/A')}\n"
                f"⚠️ Risk: {analysis.get('main_risk', 'N/A')}\n"
                f"🔍 Contradictions: {analysis.get('any_contradictions', 'N/A')}\n"
                f"📊 Confidence: {analysis.get('confidence_note', 'N/A')}\n\n"
                f"Indicators:\n"
                f"RSI 1h={signal['rsi_1h']} | RSI 4h={signal.get('rsi_4h', 'N/A')}\n"
                f"MACD={signal['crossover_1h']} | Vol={signal['vol_spike']}x\n"
                f"EMA 1h={signal['ema_status_1h']} | EMA 4h={signal['ema_status_4h']}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ PAPER TRADE ONLY - No real money"
            )
            self.send(msg)
        except Exception as e:
            logger.error(f"send_signal error: {e}")

    def send_block_notification(self, symbol: str, score: int, blocked_reason: str):
        """Send brief block notification."""
        try:
            msg = (
                f"🚫 Signal blocked: {symbol}\n"
                f"Score: {score}/100\n"
                f"Reason: {blocked_reason}\n"
                f"Time: {_paris_now_str()}"
            )
            self.send(msg)
        except Exception as e:
            logger.error(f"send_block_notification error: {e}")

    def send_alert(self, error_type: str, error_message: str, recovery_action: str):
        """Send error alert."""
        try:
            msg = (
                f"🚨 AGENT ERROR\n"
                f"Type: {error_type}\n"
                f"Message: {error_message[:500]}\n"
                f"Time: {_paris_now_str()}\n"
                f"Next action: {recovery_action}"
            )
            self.send(msg)
        except Exception as e:
            logger.error(f"send_alert error: {e}")

    def send_scan_summary(self, scanned: int, shortlisted: int, signals_logged: int, signals_blocked: int, open_trades: int):
        """Send heartbeat. If no signals, only send once per day (first run after midnight Paris time)."""
        try:
            if signals_logged == 0 and signals_blocked == 0:
                now = datetime.now(_PARIS_TZ)
                # Only send the quiet heartbeat on the first run of the day (00:00-00:59)
                if now.hour != 0:
                    return
                status = "😴 No signals today so far"
            else:
                status = "✅ Signals found!" if signals_logged > 0 else "🚫 Signals blocked by risk manager"

            msg = (
                f"📡 Scan Complete — {_paris_now_str()}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{status}\n"
                f"🔍 Scanned: {scanned} coins\n"
                f"🎯 Shortlisted: {shortlisted} | Logged: {signals_logged} | Blocked: {signals_blocked}\n"
                f"📂 Open paper trades: {open_trades}/{settings.MAX_OPEN_PAPER_TRADES}"
            )
            self.send(msg)
        except Exception as e:
            logger.error(f"send_scan_summary error: {e}")

    def send_daily_report(self, stats: dict, scanned: int, passed: int,
                          blocked: int, days_running: int):
        """Send formatted daily report."""
        try:
            today = datetime.now(_PARIS_TZ).strftime("%Y-%m-%d")
            pnl_str = f"{stats['total_paper_pnl_pct']:+.2f}%" if stats['total_paper_pnl_pct'] != 0 else "0.00%"
            best_pct = f"+{stats['best_trade_pct']:.2f}%" if stats['best_trade_pct'] >= 0 else f"{stats['best_trade_pct']:.2f}%"
            worst_pct = f"{stats['worst_trade_pct']:.2f}%"

            pf = stats['profit_factor']
            pf_str = "∞" if pf == float("inf") else str(pf)

            msg = (
                f"📊 DAILY PAPER TRADING REPORT\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 {today} | 🕐 08:00 Europe/Paris\n"
                f"⏱ System running: {days_running} days\n\n"
                f"YESTERDAY:\n"
                f"🔍 Scanned: {scanned} coins\n"
                f"✅ Signals passed: {passed}\n"
                f"🚫 Blocked: {blocked}\n\n"
                f"OPEN TRADES: {stats['total_open']}/{settings.MAX_OPEN_PAPER_TRADES}\n\n"
                f"ALL TIME RESULTS:\n"
                f"📈 Wins: {stats['total_wins']} | 📉 Losses: {stats['total_losses']} | ⏰ Expired: {stats['total_expired']}\n"
                f"🎯 Win Rate: {stats['win_rate']}%\n"
                f"📊 Profit Factor: {pf_str}\n"
                f"💰 Cumulative Paper P&L: {pnl_str}\n"
                f"🏆 Best: {stats['best_trade_symbol']} {best_pct}\n"
                f"💀 Worst: {stats['worst_trade_symbol']} {worst_pct}\n\n"
                f"SIGNAL QUALITY:\n"
                f"💪 Strong: {stats['strong_count']} | 👍 Moderate: {stats['moderate_count']} | 👎 Weak: {stats['weak_count']}\n\n"
                f"TREND FILTER:\n"
                f"✅ Passed: {stats['trend_passed']} | 🚫 Blocked: {stats['trend_blocked']}\n\n"
                f"⚠️ PAPER TRADING ONLY - NO REAL MONEY\n"
                f"📋 Min 100 signals before considering real money\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            self.send(msg)
        except Exception as e:
            logger.error(f"send_daily_report error: {e}")

    def send_metrics(self, system_a_metrics: dict, system_c_metrics: dict):
        """Send System A vs System C comparison metrics."""
        try:
            msg = (
                f"📊 <b>System A vs System C Comparison</b>\n"
                f"⚙️ <b>System A (SMC-Only):</b>\n"
                f"Status: {system_a_metrics['status']}\n"
                f"Signals: {system_a_metrics['signals']}\n"
            )
            if system_a_metrics['signals'] > 0:
                msg += (
                    f"Win Rate: {system_a_metrics['win_rate']}\n"
                    f"Wins/Losses: {system_a_metrics['wins']}/{system_a_metrics['losses']}\n"
                    f"Total P&L: ${system_a_metrics['total_pnl']}\n"
                )

            msg += (
                f"\n🧠 <b>System C (ML + Claude):</b>\n"
                f"Status: {system_c_metrics['status']}\n"
                f"Signals: {system_c_metrics['signals']}\n"
            )
            if system_c_metrics['signals'] > 0:
                msg += (
                    f"Win Rate: {system_c_metrics['win_rate']}\n"
                    f"Wins/Losses: {system_c_metrics['wins']}/{system_c_metrics['losses']}\n"
                    f"Total P&L: ${system_c_metrics['total_pnl']}\n"
                )

            msg += f"\n📈 Dashboard: http://72.60.133.179:8502"
            self.send(msg)
        except Exception as e:
            logger.error(f"send_metrics error: {e}")
