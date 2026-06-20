import asyncio
import csv
import logging
import subprocess
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

CSV_PATH = Path("data/paper_trades.csv")
CSV_COLUMNS = [
    "signal_id", "timestamp", "symbol", "direction", "score", "signal_quality",
    "entry_price", "entry_low", "entry_high", "stop_loss", "take_profit",
    "rr_ratio", "trend_filter_result", "plain_english_summary", "main_risk",
    "any_contradictions", "status", "exit_price", "exit_time", "result",
    "profit_pct", "exit_reason", "blocked_reason",
]


def _load_csv() -> pd.DataFrame:
    if not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0:
        df = pd.DataFrame(columns=CSV_COLUMNS)
        df.to_csv(CSV_PATH, index=False)
        return df
    try:
        df = pd.read_csv(CSV_PATH, dtype=str)
        for col in CSV_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[CSV_COLUMNS]
    except Exception as e:
        logger.error(f"Failed to load CSV: {e}")
        return pd.DataFrame(columns=CSV_COLUMNS)


def _save_csv(df: pd.DataFrame):
    try:
        df[CSV_COLUMNS].to_csv(CSV_PATH, index=False)
    except Exception as e:
        logger.error(f"Failed to save CSV: {e}")


def log_signal(signal: dict, analysis: dict, trend_filter_result: str, blocked_reason: str = "") -> str:
    df = _load_csv()
    signal_id = str(uuid.uuid4())[:8].upper()
    status = "BLOCKED" if blocked_reason else "OPEN"

    row = {
        "signal_id": signal_id,
        "timestamp": datetime.utcnow().isoformat(),
        "symbol": signal.get("symbol", ""),
        "direction": signal.get("direction", ""),
        "score": signal.get("score", ""),
        "signal_quality": analysis.get("signal_quality", "UNKNOWN"),
        "entry_price": signal.get("price", ""),
        "entry_low": signal.get("entry_low", ""),
        "entry_high": signal.get("entry_high", ""),
        "stop_loss": signal.get("stop_loss", ""),
        "take_profit": signal.get("take_profit", ""),
        "rr_ratio": signal.get("rr_ratio", ""),
        "trend_filter_result": trend_filter_result,
        "plain_english_summary": analysis.get("plain_english_summary", ""),
        "main_risk": analysis.get("main_risk", ""),
        "any_contradictions": analysis.get("any_contradictions", ""),
        "status": status,
        "exit_price": "",
        "exit_time": "",
        "result": "",
        "profit_pct": "",
        "exit_reason": "",
        "blocked_reason": blocked_reason,
    }

    new_row = pd.DataFrame([row], columns=CSV_COLUMNS)
    df = pd.concat([df, new_row], ignore_index=True)
    _save_csv(df)
    logger.info(f"Signal {signal_id} logged: {signal.get('symbol')} | status={status}")
    return signal_id


def calculate_profit_factor(trades_df: pd.DataFrame) -> float:
    completed = trades_df[trades_df["result"].isin(["WIN", "LOSS"])].copy()
    completed["profit_pct"] = pd.to_numeric(completed["profit_pct"], errors="coerce")
    wins = completed[completed["result"] == "WIN"]["profit_pct"]
    losses = completed[completed["result"] == "LOSS"]["profit_pct"]
    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())
    if gross_loss == 0:
        return float("inf")
    return round(gross_profit / gross_loss, 2)


def _calculate_profit_pct(status: str, entry_price: float, stop_loss: float,
                           take_profit: float, exit_price: float) -> float:
    if status == "WIN":
        return round(((take_profit - entry_price) / entry_price) * 100, 4)
    elif status == "LOSS":
        return round(((stop_loss - entry_price) / entry_price) * 100, 4)
    else:
        return round(((exit_price - entry_price) / entry_price) * 100, 4)


def update_open_trades(exchange) -> int:
    """Check all OPEN crypto trades using ccxt OHLC candles."""
    df = _load_csv()
    open_mask = df["status"] == "OPEN"
    open_trades = df[open_mask].copy()

    if open_trades.empty:
        logger.info("No open trades to update.")
        return 0

    updated = 0
    now_utc = datetime.now(timezone.utc)

    for idx, row in open_trades.iterrows():
        try:
            symbol = row["symbol"]
            entry_price = float(row["entry_price"])
            stop_loss = float(row["stop_loss"])
            take_profit = float(row["take_profit"])
            entry_time = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)

            if (now_utc - entry_time) >= timedelta(hours=settings.TRADE_EXPIRY_HOURS):
                try:
                    ticker = exchange.fetch_ticker(symbol)
                    current_price = float(ticker["last"])
                except Exception:
                    current_price = entry_price
                df.at[idx, "status"] = "EXPIRED"
                df.at[idx, "exit_price"] = str(current_price)
                df.at[idx, "exit_time"] = now_utc.isoformat()
                df.at[idx, "result"] = "EXPIRED"
                df.at[idx, "profit_pct"] = str(_calculate_profit_pct("EXPIRED", entry_price, stop_loss, take_profit, current_price))
                df.at[idx, "exit_reason"] = "TIMEOUT_48H"
                updated += 1
                continue

            since_ms = int(entry_time.timestamp() * 1000)
            try:
                raw = exchange.fetch_ohlcv(symbol, "1h", since=since_ms, limit=200)
            except Exception as e:
                logger.warning(f"Could not fetch candles for {symbol}: {e}")
                continue

            if not raw:
                continue

            hit = None
            exit_price_val = None
            exit_reason = None

            for candle in raw:
                ts_ms, o, h, l, c, v = candle
                candle_time = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                if candle_time <= entry_time:
                    continue
                if l <= stop_loss and h >= take_profit:
                    hit = "LOSS"
                    exit_price_val = stop_loss
                    exit_reason = "BOTH_HIT_CONSERVATIVE"
                    break
                elif l <= stop_loss:
                    hit = "LOSS"
                    exit_price_val = stop_loss
                    exit_reason = "STOP_LOSS_HIT"
                    break
                elif h >= take_profit:
                    hit = "WIN"
                    exit_price_val = take_profit
                    exit_reason = "TAKE_PROFIT_HIT"
                    break

            if hit:
                df.at[idx, "status"] = hit
                df.at[idx, "exit_price"] = str(exit_price_val)
                df.at[idx, "exit_time"] = now_utc.isoformat()
                df.at[idx, "result"] = hit
                df.at[idx, "profit_pct"] = str(_calculate_profit_pct(hit, entry_price, stop_loss, take_profit, exit_price_val))
                df.at[idx, "exit_reason"] = exit_reason
                updated += 1
                logger.info(f"Trade {row['signal_id']} {symbol}: {hit} via {exit_reason}")

        except Exception as e:
            logger.error(f"Error updating trade {row.get('signal_id', '?')}: {e}")
            continue

    _save_csv(df)
    logger.info(f"Updated {updated} trades.")
    return updated


async def _update_gold_trades_async(metaapi_token: str, metaapi_account_id: str) -> list:
    """
    Check all OPEN XAUUSD trades using MetaApi 1H candles.
    Returns list of dicts describing closed trades (for monitor notifications).
    """
    try:
        from metaapi_cloud_sdk import MetaApi
    except ImportError:
        logger.error("metaapi_cloud_sdk not installed.")
        return []

    df = _load_csv()
    # Match any XAUUSDxx / XAUUSDm / XAUUSD variant
    open_mask = (df["status"] == "OPEN") & (df["symbol"].str.contains("XAUUSD", na=False))
    open_trades = df[open_mask].copy()

    if open_trades.empty:
        logger.info("No open XAUUSD trades to update.")
        return []

    api = None
    closed_trades = []
    updated = 0
    now_utc = datetime.now(timezone.utc)

    try:
        api = MetaApi(token=metaapi_token)
        account = await api.metatrader_account_api.get_account(metaapi_account_id)
        await account.wait_deployed()

        symbol = df[open_mask]["symbol"].iloc[0]  # Use actual stored symbol

        for idx, row in open_trades.iterrows():
            try:
                entry_price = float(row["entry_price"])
                stop_loss = float(row["stop_loss"])
                take_profit = float(row["take_profit"])
                entry_time = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)

                # Check expiry
                if (now_utc - entry_time) >= timedelta(hours=settings.TRADE_EXPIRY_HOURS):
                    try:
                        candles = await account.get_historical_candles(symbol, "1h", datetime.utcnow(), 1)
                        current_price = float(candles[-1]["close"]) if candles else entry_price
                    except Exception:
                        current_price = entry_price
                    df.at[idx, "status"] = "EXPIRED"
                    df.at[idx, "exit_price"] = str(current_price)
                    df.at[idx, "exit_time"] = now_utc.isoformat()
                    df.at[idx, "result"] = "EXPIRED"
                    df.at[idx, "profit_pct"] = str(_calculate_profit_pct("EXPIRED", entry_price, stop_loss, take_profit, current_price))
                    df.at[idx, "exit_reason"] = "TIMEOUT_48H"
                    updated += 1
                    closed_trades.append({"signal_id": row["signal_id"], "symbol": symbol, "result": "EXPIRED", "exit_reason": "TIMEOUT_48H", "profit_pct": df.at[idx, "profit_pct"]})
                    logger.info(f"Trade {row['signal_id']} {symbol}: EXPIRED")
                    continue

                candles = await account.get_historical_candles(symbol, "1h", datetime.utcnow(), 200)
                if not candles:
                    continue

                hit = None
                exit_price_val = None
                exit_reason = None

                for candle in sorted(candles, key=lambda c: c["time"]):
                    candle_time = candle["time"]
                    if isinstance(candle_time, str):
                        candle_time = datetime.fromisoformat(candle_time.replace("Z", "+00:00"))
                    if candle_time.tzinfo is None:
                        candle_time = candle_time.replace(tzinfo=timezone.utc)
                    if candle_time <= entry_time:
                        continue
                    h = float(candle["high"])
                    l = float(candle["low"])
                    if l <= stop_loss and h >= take_profit:
                        hit = "LOSS"
                        exit_price_val = stop_loss
                        exit_reason = "BOTH_HIT_CONSERVATIVE"
                        break
                    elif l <= stop_loss:
                        hit = "LOSS"
                        exit_price_val = stop_loss
                        exit_reason = "STOP_LOSS_HIT"
                        break
                    elif h >= take_profit:
                        hit = "WIN"
                        exit_price_val = take_profit
                        exit_reason = "TAKE_PROFIT_HIT"
                        break

                if hit:
                    profit = _calculate_profit_pct(hit, entry_price, stop_loss, take_profit, exit_price_val)
                    df.at[idx, "status"] = hit
                    df.at[idx, "exit_price"] = str(exit_price_val)
                    df.at[idx, "exit_time"] = now_utc.isoformat()
                    df.at[idx, "result"] = hit
                    df.at[idx, "profit_pct"] = str(profit)
                    df.at[idx, "exit_reason"] = exit_reason
                    updated += 1
                    closed_trades.append({"signal_id": row["signal_id"], "symbol": symbol, "result": hit, "exit_reason": exit_reason, "profit_pct": str(profit), "entry_price": entry_price, "exit_price": exit_price_val})
                    logger.info(f"Trade {row['signal_id']} {symbol}: {hit} via {exit_reason}")

            except Exception as e:
                logger.error(f"Error updating XAUUSD trade {row.get('signal_id', '?')}: {e}")
                continue

    except Exception as e:
        logger.error(f"MetaApi connection error in update_gold_trades: {e}")
    finally:
        if api is not None:
            try:
                await api.close()
            except Exception:
                pass

    _save_csv(df)
    logger.info(f"Gold trades updated: {updated}")
    return closed_trades


def update_gold_trades(metaapi_token: str, metaapi_account_id: str) -> int:
    """Synchronous entry point for updating open XAUUSD trade outcomes via MetaApi."""
    try:
        closed = asyncio.run(_update_gold_trades_async(metaapi_token, metaapi_account_id))
        return len(closed)
    except Exception as e:
        logger.error(f"update_gold_trades failed: {e}")
        return 0


def update_gold_trades_with_results(metaapi_token: str, metaapi_account_id: str) -> list:
    """Like update_gold_trades but returns list of closed trade dicts for notifications."""
    try:
        return asyncio.run(_update_gold_trades_async(metaapi_token, metaapi_account_id))
    except Exception as e:
        logger.error(f"update_gold_trades failed: {e}")
        return []


def get_open_trades() -> list:
    df = _load_csv()
    return df[df["status"] == "OPEN"].to_dict("records")


def get_daily_signal_count() -> int:
    df = _load_csv()
    today = datetime.utcnow().date().isoformat()
    return len(df[(df["timestamp"].str.startswith(today)) & (df["status"] != "BLOCKED")])


def get_recent_closed_trades(n: int = 5) -> list:
    """Return last n closed trades (WIN/LOSS/EXPIRED) formatted for Claude memory context."""
    df = _load_csv()
    completed = df[df["result"].isin(["WIN", "LOSS", "EXPIRED"])].copy()
    if completed.empty:
        return []
    completed = completed.sort_values("exit_time", ascending=False).head(n)
    trades = []
    for _, row in completed.iterrows():
        try:
            entry = float(row.get("entry_price") or 0)
            sl = float(row.get("stop_loss") or 0)
            direction = "SHORT" if sl > entry else "LONG"
            trades.append({
                "signal_id": row.get("signal_id", "?"),
                "date": str(row.get("timestamp", ""))[:10],
                "direction": direction,
                "entry": entry,
                "stop_loss": sl,
                "take_profit": float(row.get("take_profit") or 0),
                "rr_ratio": row.get("rr_ratio", "?"),
                "score": row.get("score", "?"),
                "signal_quality": row.get("signal_quality", "?"),
                "result": row.get("result", "?"),
                "profit_pct": row.get("profit_pct", "?"),
                "exit_reason": row.get("exit_reason", "?"),
                "summary": str(row.get("plain_english_summary", ""))[:200],
            })
        except Exception:
            continue
    return trades
    df = _load_csv()
    completed = df[df["result"].isin(["WIN", "LOSS"])].copy()
    completed = completed.sort_values("exit_time", ascending=True)
    return completed.tail(n).to_dict("records")


def calculate_running_stats() -> dict:
    df = _load_csv()
    total_signals = len(df[df["status"] != "BLOCKED"])
    total_blocked = len(df[df["status"] == "BLOCKED"])
    completed = df[df["result"].isin(["WIN", "LOSS", "EXPIRED"])].copy()
    completed["profit_pct"] = pd.to_numeric(completed["profit_pct"], errors="coerce")
    wins = completed[completed["result"] == "WIN"]
    losses = completed[completed["result"] == "LOSS"]
    expired = completed[completed["result"] == "EXPIRED"]
    total_wins = len(wins)
    total_losses = len(losses)
    total_expired = len(expired)
    total_open = len(df[df["status"] == "OPEN"])
    win_rate = round((total_wins / (total_wins + total_losses) * 100), 1) if (total_wins + total_losses) > 0 else 0.0
    profit_factor = calculate_profit_factor(completed)
    avg_win_pct = round(wins["profit_pct"].mean(), 2) if total_wins > 0 else 0.0
    avg_loss_pct = round(losses["profit_pct"].mean(), 2) if total_losses > 0 else 0.0
    total_pnl = round(completed["profit_pct"].sum(), 2)

    sorted_completed = completed.sort_values("exit_time").reset_index(drop=True)
    consecutive_wins = 0
    consecutive_losses = 0
    if not sorted_completed.empty:
        for _, r in sorted_completed[::-1].iterrows():
            if r["result"] == "WIN":
                if consecutive_losses == 0:
                    consecutive_wins += 1
                else:
                    break
            elif r["result"] == "LOSS":
                if consecutive_wins == 0:
                    consecutive_losses += 1
                else:
                    break
            else:
                break

    best_trade = wins.loc[wins["profit_pct"].idxmax()] if not wins.empty else None
    worst_trade = losses.loc[losses["profit_pct"].idxmin()] if not losses.empty else None
    sq = df[df["status"] != "BLOCKED"]["signal_quality"].value_counts().to_dict()
    trend_passed = len(df[df["trend_filter_result"].str.startswith("TREND_OK", na=False)])
    trend_blocked = len(df[df["trend_filter_result"].str.startswith("BLOCKED", na=False)])

    return {
        "total_signals": total_signals, "total_wins": total_wins, "total_losses": total_losses,
        "total_expired": total_expired, "total_blocked": total_blocked, "total_open": total_open,
        "win_rate": win_rate, "profit_factor": profit_factor,
        "avg_win_pct": avg_win_pct, "avg_loss_pct": avg_loss_pct,
        "consecutive_wins": consecutive_wins, "consecutive_losses": consecutive_losses,
        "best_trade_symbol": best_trade["symbol"] if best_trade is not None else "N/A",
        "best_trade_pct": round(float(best_trade["profit_pct"]), 2) if best_trade is not None else 0.0,
        "worst_trade_symbol": worst_trade["symbol"] if worst_trade is not None else "N/A",
        "worst_trade_pct": round(float(worst_trade["profit_pct"]), 2) if worst_trade is not None else 0.0,
        "total_paper_pnl_pct": total_pnl,
        "strong_count": sq.get("STRONG", 0), "moderate_count": sq.get("MODERATE", 0), "weak_count": sq.get("WEAK", 0),
        "trend_passed": trend_passed, "trend_blocked": trend_blocked,
    }


def commit_trades_csv():
    try:
        subprocess.run(["git", "config", "user.email", "agent@crypto-signal-agent.com"], check=True)
        subprocess.run(["git", "config", "user.name", "Signal Agent"], check=True)
        subprocess.run(["git", "add", "data/paper_trades.csv"], check=True)
        subprocess.run(["git", "commit", "-m", f"Update paper trades {datetime.utcnow().isoformat()}"], check=True)
        subprocess.run(["git", "push"], check=True)
        logger.info("paper_trades.csv committed to repo")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Git commit failed: {e}. CSV updated locally but not pushed.")
