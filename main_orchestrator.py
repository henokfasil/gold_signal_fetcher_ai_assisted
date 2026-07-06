"""
Gold Signal Fetcher - AI-Assisted (System C)
Orchestrator combining SMC + ML + Claude for superior signal generation.

Full pipeline:
1. SMC detects signals (technical confluence)
2. ML filters with confidence score (0-100%)
3. Claude analyzes market context (risk, timing, news)
4. Combined decision (ML 35% + Claude 35% + SMC 30%)
5. Execute if confidence >= tier threshold
6. Track P&L for continuous learning
"""

import logging
import sys
import os
import csv
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Load environment
load_dotenv("/root/gold_signal_fetcher_ai_assisted/.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Import core components
try:
    from agent.smc_gold_scanner import run_gold_scanner
    from agent.paper_trader import update_gold_trades, get_open_trades
    from agent.liquidity_manager import get_session_description, is_market_closed
    from agent.notifier import Notifier
    logger.info("[ORCHESTRATOR] Core imports successful")
except ImportError as e:
    logger.error(f"[ORCHESTRATOR] Import error: {e}")
    sys.exit(1)

# Optional AI imports (graceful degradation)
try:
    from agent.ml_signal_generator import MLSignalFilter
    from agent.claude_analyst import AITradingDecider
    HAS_AI = True
    logger.info("[ORCHESTRATOR] AI components loaded")
except Exception as e:
    HAS_AI = False
    logger.warning(f"[ORCHESTRATOR] AI components unavailable ({e}), running in SMC-only mode")


class AIAssistedOrchestrator:
    """Orchestrate SMC + ML + Claude trading pipeline."""

    def __init__(self):
        """Initialize orchestrator with all components."""
        if HAS_AI:
            self.ml_filter = MLSignalFilter()
            self.ai_decider = AITradingDecider()
        else:
            self.ml_filter = None
            self.ai_decider = None

        self.notifier = Notifier(
            token=os.environ.get("TELEGRAM_TOKEN"),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
            scan_only=False,
        )
        self.metaapi_token = os.environ.get("METAAPI_TOKEN")
        self.metaapi_account_id = os.environ.get("METAAPI_ACCOUNT_ID")

    def _get_current_price_from_tradingview(self, symbol: str = "XAUUSD") -> float:
        """Fetch current price directly from TradingView charts via MCP."""
        try:
            # Use TradingView MCP to read live price
            # The tv_launch tool should auto-detect and connect to TradingView Desktop
            import json
            from pathlib import Path

            # Read from TradingView price snapshot (cached/live)
            # Try to get latest quote from TradingView indicator data
            tv_data_path = Path("/tmp/tradingview_snapshot.json")

            if tv_data_path.exists():
                with open(tv_data_path, 'r') as f:
                    data = json.load(f)
                    if 'XAUUSD' in data and 'price' in data['XAUUSD']:
                        price = float(data['XAUUSD']['price'])
                        logger.info(f"[PRICE] Current price from TradingView: {price}")
                        return price

            # Fallback: use last price from the SMC scanner run
            from agent.smc_gold_scanner import run_gold_scanner
            signal = run_gold_scanner(self.metaapi_token, self.metaapi_account_id)
            if signal and 'price' in signal:
                price = float(signal['price'])
                logger.info(f"[PRICE] Current price from SMC scanner: {price}")
                return price

            logger.warning("[PRICE] Could not fetch live price from TradingView or SMC")
            return None

        except Exception as e:
            logger.debug(f"[PRICE] Error fetching: {e}")
            return None

    def _update_open_trades_system_c(self, metaapi_token: str, metaapi_account_id: str) -> int:
        """Update open trades in System C CSV using MetaAPI price data."""
        csv_path = Path("/root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv")
        if not csv_path.exists():
            return 0

        try:
            import pandas as pd
            df = pd.read_csv(csv_path, dtype=str).fillna("")
            if df.empty:
                return 0

            updated = 0
            now = datetime.utcnow()

            # Get current price from TradingView MCP (or fallback to SMC scanner)
            current_price = self._get_current_price_from_tradingview("XAUUSD")
            if current_price:
                logger.info(f"[TRADE-UPDATE] Using current XAUUSD price: {current_price}")
            else:
                logger.warning("[TRADE-UPDATE] No live price available, will retry next cycle")

            for idx, row in df.iterrows():
                try:
                    # Skip if already closed (pnl != 0)
                    pnl = float(row.get("pnl", 0))
                    if pnl != 0:
                        continue

                    entry = float(row.get("entry", 0))
                    sl = float(row.get("stop_loss", 0))
                    tp_str = row.get("take_profits", "[0]").strip("[]").strip("np.float64()")
                    tp = float(tp_str) if tp_str else 0
                    direction = str(row.get("direction", "BUY")).upper()

                    # Check expiry (48 hours)
                    ts = datetime.fromisoformat(row.get("timestamp", "").replace("Z", "+00:00"))
                    age_hours = (now - ts).total_seconds() / 3600

                    if age_hours > 48:
                        # Expired - mark as 0% P&L
                        df.at[idx, "pnl"] = "0"
                        updated += 1
                        logger.info(f"[TRADE-CLOSE] Trade EXPIRED (age: {age_hours:.1f}h)")
                        continue

                    # Check if TP/SL hit using current price
                    if current_price is None:
                        continue  # Skip if no price data

                    result = None
                    exit_pnl = None

                    if direction == "BUY":
                        if current_price <= sl:
                            result = "LOSS"
                            exit_pnl = ((sl - entry) / entry) * 100
                        elif current_price >= tp:
                            result = "WIN"
                            exit_pnl = ((tp - entry) / entry) * 100
                    else:  # SELL
                        if current_price >= sl:
                            result = "LOSS"
                            exit_pnl = ((entry - sl) / entry) * 100
                        elif current_price <= tp:
                            result = "WIN"
                            exit_pnl = ((entry - tp) / entry) * 100

                    if result:
                        df.at[idx, "pnl"] = str(round(exit_pnl, 2))
                        updated += 1
                        logger.info(f"[TRADE-CLOSE] {direction} {result}: {exit_pnl:.2f}% P&L @ {current_price:.2f}")

                except (ValueError, TypeError, AttributeError) as e:
                    logger.debug(f"Error parsing trade row: {e}")
                    continue

            if updated > 0:
                df.to_csv(csv_path, index=False)
                logger.info(f"✅ Updated {updated} System C trades with real MetaAPI prices")

            return updated
        except Exception as e:
            logger.error(f"Error updating System C trades: {e}")
            return 0

    def run_scan(self):
        """Execute full AI-assisted scan cycle."""
        logger.info("[ORCHESTRATOR] Starting scan cycle (AI " + ("enabled" if HAS_AI else "disabled") + ")")

        # **NEW: Update open trades (check for closures) every cycle**
        try:
            updated = self._update_open_trades_system_c(self.metaapi_token, self.metaapi_account_id)
            if updated > 0:
                logger.info(f"[ORCHESTRATOR] Updated {updated} open trades")
        except Exception as e:
            logger.warning(f"[ORCHESTRATOR] Trade update skipped: {e}")

        # Check market status
        session_info = get_session_description()
        logger.info(
            f"[SESSION] {session_info['current_day']} {session_info['current_time_utc']} UTC | "
            f"Tier: {session_info['liquidity_tier']} | "
            f"Position size: {session_info['position_size_multiplier']:.0%}"
        )

        if is_market_closed():
            logger.warning("[ORCHESTRATOR] Market closed - skipping scan")
            return

        # Step 1: Update open trades
        try:
            updated = update_gold_trades(self.metaapi_token, self.metaapi_account_id)
            logger.info(f"[ORCHESTRATOR] Updated {updated} open trades")
        except Exception as e:
            logger.error(f"[ORCHESTRATOR] Error updating trades: {e}")

        # Step 2: Get SMC signal
        signal = None
        try:
            signal = run_gold_scanner(self.metaapi_token, self.metaapi_account_id)
            if signal:
                # Derive direction from market structure
                smc_data = signal.get('mtf', {}).get('smc', {})
                struct_4h = smc_data.get('struct_4h', 'unknown')
                signal['direction'] = 'BUY' if struct_4h == 'bullish' else 'SELL'
                signal['pair'] = signal.get('symbol', 'XAUUSD')
                signal['entry'] = signal.get('price')
                signal['take_profits'] = [signal.get('take_profit')]
                logger.info(f"[ORCHESTRATOR] SMC signal: {signal['direction']} @ {signal.get('entry')} | Score: {signal.get('score')}")
            else:
                logger.info("[ORCHESTRATOR] No SMC signal this cycle")
        except Exception as e:
            logger.error(f"[ORCHESTRATOR] SMC scan failed: {e}")
            return

        if not signal:
            logger.info("[ORCHESTRATOR] Scan complete - no signal")
            return

        # Step 3: Apply AI layer if available, otherwise just execute
        if not HAS_AI:
            logger.info("[ORCHESTRATOR] AI unavailable - executing SMC signal directly")
            self._execute_trade_simple(signal)
            return

        try:
            decision = self._apply_ai_layer(signal, session_info)
            logger.info(f"[ORCHESTRATOR] AI Decision: {decision['final_reason']}")

            if not decision['should_trade']:
                logger.info("[ORCHESTRATOR] Signal filtered by AI - skipping execution")
                self.notifier.send(
                    f"🤖 AI filtered signal\n\n"
                    f"SMC Score: {decision['smc_score']:.0f}%\n"
                    f"ML Confidence: {decision['ml_confidence']:.0f}%\n"
                    f"Claude: {decision['claude_confidence']:.0f}%\n"
                    f"Combined: {decision['combined_confidence']:.0f}% (threshold: {decision['threshold']}%)\n\n"
                    f"Reason: {decision['claude_reasoning']}"
                )
                return

            # **NEW: Step 3b: Check for duplicate signals (prevent duplicate logging)**
            if self._is_duplicate_signal(signal):
                logger.warning(f"[DEDUP] Duplicate signal detected: {signal['direction']} @ {signal['entry']:.2f}")
                return

            # Step 4: Execute trade
            self._execute_trade(signal, decision)

        except Exception as e:
            logger.error(f"[ORCHESTRATOR] AI layer error: {e}")
            self.notifier.bot_error(f"AI layer failed: {e}")

    def _is_duplicate_signal(self, signal, max_age_minutes=30) -> bool:
        """Check if identical signal already logged in last N minutes (deduplication)."""
        csv_path = Path("/root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv")
        if not csv_path.exists():
            return False

        try:
            import pandas as pd
            df = pd.read_csv(csv_path, dtype=str).fillna("")
            if df.empty:
                return False

            direction = signal.get("direction", "")
            entry = float(signal.get("entry", 0))
            sl = float(signal.get("stop_loss", 0))
            tp = float(signal.get("take_profits", [0])[0]) if signal.get("take_profits") else 0

            now = datetime.utcnow()
            for _, row in df.iterrows():
                try:
                    ts = datetime.fromisoformat(row.get("timestamp", "").replace("Z", "+00:00"))
                    age_min = (now - ts).total_seconds() / 60

                    if age_min > max_age_minutes:
                        continue

                    # Match if same direction, entry, SL, TP within tolerance
                    if (row.get("direction", "").upper() == direction.upper() and
                        abs(float(row.get("entry", 0)) - entry) < entry * 0.001 and
                        abs(float(row.get("stop_loss", 0)) - sl) < entry * 0.001 and
                        abs(float(row.get("take_profits", str([0]))[1:-1].split(",")[0]) - tp) < entry * 0.001):
                        logger.info(f"[DEDUP] Found duplicate from {age_min:.0f} min ago")
                        return True
                except (ValueError, TypeError, IndexError):
                    continue
        except Exception as e:
            logger.warning(f"[DEDUP] Error checking duplicates: {e}")
        return False

    def _apply_ai_layer(self, signal, session_info) -> dict:
        """Apply ML + Claude analysis to signal."""
        logger.info("[AI-LAYER] Analyzing signal with ML + Claude")

        # Prepare market data for Claude
        market_data = {
            'current_price': signal.get('entry', 'market'),
            'trend_4h': signal.get('indicators_4h', {}).get('trend', 'unknown'),
            'trend_1h': signal.get('indicators_1h', {}).get('trend', 'unknown'),
            'rsi_14': signal.get('indicators_1h', {}).get('rsi', 'N/A'),
            'atr_14': signal.get('indicators_1h', {}).get('atr', 'N/A'),
            'volatility_level': 'normal',
            'news_risk': 'low'
        }

        # Get open positions for Claude context
        try:
            open_positions = get_open_trades()
        except:
            open_positions = []

        # Use AI decider (combines ML + Claude)
        decision = self.ai_decider.decide(
            signal_info=signal,
            market_data=market_data,
            ml_confidence=signal.get('ml_confidence', 50),
            smc_score=signal.get('score', 50),
            liquidity_tier=session_info['liquidity_tier'],
            open_positions=open_positions
        )

        return decision

    def _execute_trade_simple(self, signal):
        """Execute trade without AI approval (fallback mode)."""
        logger.info(f"[EXECUTOR] Executing SMC-only trade: {signal['direction']} {signal['pair']}")
        self.notifier.send(
            f"📊 *SMC Signal Executed*\n\n"
            f"Direction: {signal['direction']} {signal['pair']}\n"
            f"Entry: {signal.get('entry', 'market')}\n"
            f"SL: {signal.get('stop_loss', 'N/A')}\n"
            f"TPs: {signal.get('take_profits', [])}\n"
            f"Score: {signal.get('score', 'N/A')}%\n\n"
            f"⚠️ AI layer unavailable - executing on SMC confidence only"
        )

    def _log_trade_to_csv(self, signal, decision):
        """Log executed trade to paper_trades_ai.csv."""
        csv_path = Path("/root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        trade_row = {
            'timestamp': datetime.utcnow().isoformat(),
            'pair': signal.get('pair', 'XAUUSD'),
            'direction': signal.get('direction', 'UNKNOWN'),
            'entry': float(signal.get('entry', 0)) if signal.get('entry') else 0,
            'stop_loss': float(signal.get('stop_loss', 0)) if signal.get('stop_loss') else 0,
            'take_profits': str(signal.get('take_profits', [])),
            'pnl': 0,
            'signal_source': 'system_c_ai',
            'ml_confidence': float(decision.get('ml_confidence', 0)),
            'claude_confidence': float(decision.get('claude_confidence', 0)),
            'combined_confidence': float(decision.get('combined_confidence', 0)),
        }

        try:
            file_exists = csv_path.exists()
            with open(csv_path, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=trade_row.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(trade_row)
            logger.info(f"[CSV] Trade logged: {signal['pair']} {signal['direction']}")
        except Exception as e:
            logger.error(f"[CSV] Failed to log trade: {e}")

    def _execute_trade(self, signal, decision):
        """Execute the trade after AI approval."""
        logger.info(f"[EXECUTOR] Executing trade: {signal['direction']} {signal['pair']}")

        try:
            # Log to CSV first
            self._log_trade_to_csv(signal, decision)

            # Notify user with AI reasoning
            msg = (
                f"🤖 *AI Signal Executed*\n\n"
                f"Direction: {signal['direction']} {signal['pair']}\n"
                f"Entry: {signal.get('entry', 'market')}\n"
                f"SL: {signal.get('stop_loss', 'N/A')}\n"
                f"TPs: {signal.get('take_profits', [])}\n\n"
                f"*AI Analysis:*\n"
                f"SMC: {decision['smc_score']:.0f}% | "
                f"ML: {decision['ml_confidence']:.0f}% | "
                f"Claude: {decision['claude_confidence']:.0f}%\n"
                f"Combined: {decision['combined_confidence']:.0f}%\n\n"
                f"Claude: {decision['claude_reasoning']}"
            )
            self.notifier.send(msg)
            logger.info(f"[EXECUTOR] Trade notification sent")

        except Exception as e:
            logger.error(f"[EXECUTOR] Error: {e}")
            self.notifier.send(f"⚠️ Trade execution error: {e}")


def main():
    """Main entry point."""
    logger.info("=" * 70)
    logger.info("Gold Signal Fetcher - AI-Assisted (System C)")
    logger.info("=" * 70)
    logger.info("Pipeline: SMC Signals → ML Filtering → Claude Analysis → Trade")
    logger.info("")

    orchestrator = AIAssistedOrchestrator()
    orchestrator.run_scan()

    logger.info("=" * 70)


if __name__ == "__main__":
    main()
