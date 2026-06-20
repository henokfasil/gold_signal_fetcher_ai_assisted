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
import asyncio
from dotenv import load_dotenv
from datetime import datetime

# Load environment
load_dotenv("/root/gold_signal_fetcher_ai_assisted/.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Import all components
try:
    from agent.smc_gold_scanner import run_gold_scanner
    from agent.ml_signal_generator import MLSignalFilter
    from agent.claude_analyst import AITradingDecider
    from agent.paper_trader import update_gold_trades, get_open_trades, place_paper_trade
    from agent.liquidity_manager import get_session_description, is_market_closed
    from agent.notifier import Notifier
    logger.info("[ORCHESTRATOR] All imports successful")
except ImportError as e:
    logger.error(f"[ORCHESTRATOR] Import error: {e}")
    sys.exit(1)


class AIAssistedOrchestrator:
    """Orchestrate SMC + ML + Claude trading pipeline."""

    def __init__(self):
        """Initialize orchestrator with all components."""
        self.ml_filter = MLSignalFilter()
        self.ai_decider = AITradingDecider()
        self.notifier = Notifier(
            token=os.environ.get("TELEGRAM_TOKEN"),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
            scan_only=False,
        )
        self.metaapi_token = os.environ.get("METAAPI_TOKEN")
        self.metaapi_account_id = os.environ.get("METAAPI_ACCOUNT_ID")

    async def run_scan(self):
        """Execute full AI-assisted scan cycle."""
        logger.info("[ORCHESTRATOR] Starting AI-assisted scan cycle")

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
                logger.info(f"[ORCHESTRATOR] SMC signal: {signal['direction']} @ {signal.get('entry')} | Score: {signal.get('score')}")
            else:
                logger.info("[ORCHESTRATOR] No SMC signal this cycle")
        except Exception as e:
            logger.error(f"[ORCHESTRATOR] SMC scan failed: {e}")
            return

        if not signal:
            logger.info("[ORCHESTRATOR] Scan complete - no signal")
            return

        # Step 3: Apply ML filter + Claude analysis
        try:
            decision = await self._apply_ai_layer(signal, session_info)
            logger.info(f"[ORCHESTRATOR] AI Decision: {decision['final_reason']}")

            if not decision['should_trade']:
                logger.info("[ORCHESTRATOR] Signal filtered by AI - skipping execution")
                self.notifier.trade_instruction(
                    f"🤖 AI filtered signal\n\n"
                    f"SMC Score: {decision['smc_score']:.0f}%\n"
                    f"ML Confidence: {decision['ml_confidence']:.0f}%\n"
                    f"Claude: {decision['claude_confidence']:.0f}%\n"
                    f"Combined: {decision['combined_confidence']:.0f}% (threshold: {decision['threshold']}%)\n\n"
                    f"Reason: {decision['claude_reasoning']}"
                )
                return

            # Step 4: Execute trade
            await self._execute_trade(signal, decision)

        except Exception as e:
            logger.error(f"[ORCHESTRATOR] AI layer error: {e}")
            self.notifier.bot_error(f"AI layer failed: {e}")

    async def _apply_ai_layer(self, signal, session_info) -> dict:
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

    async def _execute_trade(self, signal, decision):
        """Execute the trade after AI approval."""
        logger.info(f"[EXECUTOR] Executing trade: {signal['direction']} {signal['pair']}")

        try:
            # Place the trade
            results = await place_paper_trade(signal, self.metaapi_token, self.metaapi_account_id)

            if results:
                logger.info(f"[EXECUTOR] Trade executed: {len(results)} position(s) opened")

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
                self.notifier.trade_instruction(msg)
            else:
                logger.error("[EXECUTOR] Trade failed")
                self.notifier.bot_error("Trade execution failed")

        except Exception as e:
            logger.error(f"[EXECUTOR] Error: {e}")
            self.notifier.bot_error(f"Trade execution error: {e}")


async def main():
    """Main entry point."""
    logger.info("=" * 70)
    logger.info("Gold Signal Fetcher - AI-Assisted (System C)")
    logger.info("=" * 70)
    logger.info("Pipeline: SMC Signals → ML Filtering → Claude Analysis → Trade")
    logger.info("")

    orchestrator = AIAssistedOrchestrator()
    await orchestrator.run_scan()

    logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
