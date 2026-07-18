"""
Enhanced Dashboard: System A (SMC) vs System C (ML + Claude)
Includes equity curves, trade tables, capital performance.
"""

import logging
import os
import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from html import escape
from flask import Flask, render_template_string
from pathlib import Path
from config import settings
from agent.liquidity_manager import is_market_closed

app = Flask(__name__)
logger = logging.getLogger(__name__)

SYSTEM_A_CSV = settings.SYSTEM_A_CSV
SYSTEM_C_CSV = settings.PAPER_TRADES_CSV
STARTING_CAPITAL = settings.PAPER_ACCOUNT_SIZE


def _tail_text(path, max_bytes=65536):
    """Read only the tail of a log file; dashboard requests stay constant-cost."""
    path = Path(path)
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - max_bytes))
        return handle.read().decode("utf-8", errors="replace")


def get_feed_health(snapshot_path=None, log_path=None):
    """Return feed/scanner health using existing files only—no network calls."""
    snapshot_path = Path(snapshot_path or settings.TRADINGVIEW_SNAPSHOT_PATH)
    log_path = Path(log_path or settings.LOG_FILE)
    health = {
        "status": "UNAVAILABLE", "status_class": "bad", "provider": "—",
        "symbol": "—", "captured_at": "—", "age": "—", "timeframes": {},
        "last_scan": "No completed scan found", "market": "CLOSED" if is_market_closed() else "OPEN",
        "paper_mode": "ENFORCED" if settings.PAPER_TRADING else "MISCONFIGURED",
    }
    try:
        payload = json.loads(snapshot_path.read_text())
        captured = datetime.fromisoformat(payload["captured_at"].replace("Z", "+00:00"))
        captured = captured.replace(tzinfo=timezone.utc) if captured.tzinfo is None else captured.astimezone(timezone.utc)
        age_seconds = max(0, int((datetime.now(timezone.utc) - captured).total_seconds()))
        frames = payload.get("timeframes", {})
        health.update({
            "provider": payload.get("provider", "—"), "symbol": payload.get("symbol", "—"),
            "captured_at": captured.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "age": f"{age_seconds // 60}m {age_seconds % 60}s",
            "timeframes": {name: int(data.get("bar_count", len(data.get("bars", []))))
                           for name, data in frames.items()},
        })
        complete = all(health["timeframes"].get(name, 0) >= 200
                       for name in ("1W", "1D", "4H", "1H", "15M"))
        # Allow for the 15-minute schedule plus chart-settling time. The scanner
        # itself retains the stricter SNAPSHOT_MAX_AGE_SECONDS gate.
        fresh = age_seconds <= settings.DASHBOARD_FEED_MAX_AGE_SECONDS
        exact = health["symbol"] == "OANDA:XAUUSD"
        health["status"] = "HEALTHY" if fresh and complete and exact else "DEGRADED"
        health["status_class"] = "good" if health["status"] == "HEALTHY" else "warn"
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        pass

    for line in reversed(_tail_text(log_path).splitlines()):
        marker = "[ORCHESTRATOR] Result:"
        if marker in line:
            health["last_scan"] = line.split(marker, 1)[1].strip()
            break
    return health


def build_feed_health_html(health):
    tf = " ".join(
        f'<span class="tf-chip">{escape(name)}: {count}</span>'
        for name, count in health["timeframes"].items()
    ) or '<span class="muted">No timeframe data</span>'
    fields = [
        ("Provider", health["provider"]), ("Exact symbol", health["symbol"]),
        ("Snapshot age", health["age"]), ("Captured", health["captured_at"]),
        ("Last scan result", health["last_scan"]), ("Market", health["market"]),
        ("Paper mode", health["paper_mode"]), ("Schedule", "Every 15 minutes"),
    ]
    cards = "".join(
        f'<div class="health-item"><div class="metric-label">{escape(label)}</div>'
        f'<div class="health-value">{escape(str(value))}</div></div>'
        for label, value in fields
    )
    return (
        '<section class="health-panel"><div class="health-heading">'
        '<h2>TradingView Data Feed Health</h2>'
        f'<span class="status-pill {health["status_class"]}">{escape(health["status"])}</span>'
        f'</div><div class="health-grid">{cards}</div>'
        f'<div class="timeframes"><div class="metric-label">Validated bars</div>{tf}</div>'
        '<p class="health-note">File-based monitoring only: this panel makes no TradingView or MCP calls.</p>'
        '</section>'
    )


def load_trades(csv_path):
    """Load trades from CSV."""
    if not csv_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(csv_path)
        return df
    except:
        return pd.DataFrame()


def calculate_metrics(csv_path):
    """Calculate metrics from trades (handles both System A and C schemas)."""
    df = load_trades(csv_path)

    if df.empty:
        return {
            'status': 'Not started',
            'starting_capital': '$10,000',
            'current_capital': '$10,000',
            'total_profit': '$0.00',
            'return_pct': '0.0%',
            'signals': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': '0.0%',
            'profit_factor': '0.00',
            'total_pnl': '$0.00'
        }

    # Detect schema
    is_system_c = 'candidate_id' in df.columns and 'pair' in df.columns

    # BLOCKED signals were never trades — exclude from counts and tables
    if 'status' in df.columns:
        df = df[df['status'].astype(str).str.upper() != 'BLOCKED']
    if 'trend_filter_result' in df.columns:
        df = df[~df['trend_filter_result'].astype(str).str.startswith('BLOCKED')]

    total_trades = len(df)

    if is_system_c:
        # System C: count outcomes explicitly and use USD P&L for capital.
        df['pnl_usd'] = pd.to_numeric(df['pnl_usd'], errors='coerce').fillna(0)
        closed = df[df['status'].isin(['WIN', 'LOSS', 'EXPIRED'])]
        wins = len(closed[closed['status'] == 'WIN'])
        losses = len(closed[closed['status'] == 'LOSS'])
        total_pnl = closed['pnl_usd'].sum()
        wins_sum = closed[closed['pnl_usd'] > 0]['pnl_usd'].sum() if wins > 0 else 0
        losses_sum = abs(closed[closed['pnl_usd'] < 0]['pnl_usd'].sum()) if losses > 0 else 1
    else:
        # System A: use 'profit_pct' and check 'result' column
        df['profit_pct'] = pd.to_numeric(df['profit_pct'], errors='coerce').fillna(0)
        df['result'] = df['result'].fillna('')
        closed = df[df['result'].isin(['WIN', 'LOSS', 'EXPIRED'])]
        wins = len(closed[closed['result'] == 'WIN'])
        losses = len(closed[closed['result'] == 'LOSS'])
        total_pnl = closed['profit_pct'].sum() if not closed.empty else 0
        wins_sum = closed[closed['result'] == 'WIN']['profit_pct'].sum() if wins > 0 else 0
        losses_sum = abs(closed[closed['result'] == 'LOSS']['profit_pct'].sum()) if losses > 0 else 1

    win_rate = ((wins + losses) > 0 and (wins / (wins + losses) * 100)) or 0
    current_capital = STARTING_CAPITAL + total_pnl
    return_pct = (total_pnl / STARTING_CAPITAL * 100) if STARTING_CAPITAL > 0 else 0
    profit_factor = wins_sum / losses_sum if losses_sum > 0 else 0

    return {
        'status': 'Running',
        'starting_capital': f'${STARTING_CAPITAL:,.2f}',
        'current_capital': f'${current_capital:,.2f}',
        'total_profit': f'${total_pnl:,.2f}',
        'return_pct': f'{return_pct:.2f}%',
        'signals': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': f'{win_rate:.1f}%',
        'profit_factor': f'{profit_factor:.2f}',
        'total_pnl': f'${total_pnl:,.2f}'
    }


def get_recent_trades(csv_path, limit=10):
    """Get recent trades handling both System A and System C schemas."""
    df = load_trades(csv_path)
    if df.empty:
        return []

    # Detect schema (System A or System C)
    is_system_c = 'candidate_id' in df.columns and 'pair' in df.columns
    is_system_a = 'signal_id' in df.columns and 'symbol' in df.columns

    # BLOCKED signals were never trades — don't render them as OPEN positions
    if 'status' in df.columns:
        df = df[df['status'].astype(str).str.upper() != 'BLOCKED']
    if 'trend_filter_result' in df.columns:
        df = df[~df['trend_filter_result'].astype(str).str.startswith('BLOCKED')]

    trades = []
    recent = df.tail(limit).copy()

    for _, row in recent.iterrows():
        try:
            if is_system_c:
                # System C schema
                pair = row.get('pair', 'XAUUSD')
                direction = str(row.get('direction', 'N/A')).upper()
                entry = row.get('entry', 'N/A')
                status = str(row.get('status', 'REJECTED')).upper()
                pct_value = pd.to_numeric(row.get('pnl_pct', ''), errors='coerce')
                usd_value = pd.to_numeric(row.get('pnl_usd', ''), errors='coerce')
                outcome = status
                pnl_pct = '-' if pd.isna(pct_value) else f'{pct_value:.2f}%'
                pnl_usd = '-' if pd.isna(usd_value) else f'${usd_value:.2f}'
                timestamp = row.get('timestamp', '')

            else:
                # System A schema
                pair = row.get('symbol', 'XAUUSD')

                # Handle NaN direction column (pandas reads empty as 'nan' float)
                import pandas as pd
                direction_val = row.get('direction', '')
                direction_str = str(direction_val).strip().upper()
                if direction_str in ['NAN', ''] or pd.isna(direction_val):
                    # Infer from entry vs take_profit
                    try:
                        entry_val = float(row.get('entry_price', 0))
                        tp_val = float(row.get('take_profit', 0))
                        direction = 'BUY' if tp_val > entry_val else 'SELL'
                    except:
                        direction = 'UNKNOWN'
                else:
                    direction = direction_str

                entry = row.get('entry_price', 'N/A')

                # Handle NaN result column
                result_val = row.get('result', '')
                result_str = str(result_val).strip().upper()
                if result_str in ['NAN', '']:
                    result = 'OPEN'
                else:
                    result = result_str

                # Parse profit_pct safely - check for NaN
                try:
                    pnl_pct_raw = row.get('profit_pct', 0)
                    if pd.isna(pnl_pct_raw):
                        pnl_pct_val = 0
                    else:
                        pnl_pct_val = float(pnl_pct_raw)
                except:
                    pnl_pct_val = 0

                outcome = result if result in ['WIN', 'LOSS', 'EXPIRED'] else 'OPEN'
                pnl_pct = '-' if pnl_pct_val == 0 or result == 'OPEN' else f'{pnl_pct_val:.2f}%'
                pnl_usd = '-' if pnl_pct_val == 0 or result == 'OPEN' else f'${(pnl_pct_val/100*10000):.2f}'
                timestamp = row.get('timestamp', '')

            trades.append({
                'pair': pair,
                'direction': direction,
                'outcome': outcome,
                'entry': entry,
                'pnl_pct': pnl_pct,
                'pnl_usd': pnl_usd,
                'timestamp': timestamp
            })
        except Exception as e:
            logger.warning(f"Error parsing trade: {e}")
            continue

    return trades


def build_trade_rows_html(csv_path):
    """Build HTML table rows for recent trades."""
    trades = get_recent_trades(csv_path, limit=10)

    if not trades:
        return '<tr><td colspan="7" style="text-align:center; padding:20px; color:#94a3b8;">No closed trades</td></tr>'

    rows = ''
    for trade in trades:
        if trade['outcome'] == 'WIN':
            color = '#10b981'  # Green
        elif trade['outcome'] == 'LOSS':
            color = '#ef4444'  # Red
        else:  # OPEN
            color = '#f59e0b'  # Amber
        rows += f'''
        <tr>
            <td>{trade['pair']}</td>
            <td>{trade['direction']}</td>
            <td style="color:{color}; font-weight:bold;">{trade['outcome']}</td>
            <td>{trade['entry']}</td>
            <td>-</td>
            <td style="color:{color}">{trade['pnl_pct']}</td>
            <td style="color:{color}">{trade['pnl_usd']}</td>
            <td>{trade['timestamp'][:10]}</td>
        </tr>
        '''
    return rows


@app.route('/')
def dashboard():
    """Render enhanced comparison dashboard."""
    metrics_a = calculate_metrics(SYSTEM_A_CSV)
    metrics_c = calculate_metrics(SYSTEM_C_CSV)

    trades_a = build_trade_rows_html(SYSTEM_A_CSV)
    trades_c = build_trade_rows_html(SYSTEM_C_CSV)
    feed_health = build_feed_health_html(get_feed_health())

    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Gold Signal Fetcher - Dashboard</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta http-equiv="refresh" content="60">
        <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #0f172a;
                color: #e2e8f0;
                padding: 20px;
            }
            .header {
                text-align: center;
                margin-bottom: 30px;
            }
            .header h1 {
                font-size: 28px;
                margin-bottom: 10px;
                color: #10b981;
            }
            .header p {
                color: #94a3b8;
                font-size: 14px;
            }
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }

            .capital-section {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 30px;
            }
            .health-panel {
                background: #1e293b; border: 2px solid #0ea5e9; border-radius: 8px;
                padding: 20px; margin-bottom: 30px;
            }
            .health-heading { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:16px; }
            .health-heading h2 { color:#38bdf8; font-size:17px; }
            .status-pill { padding:6px 12px; border-radius:999px; font-size:12px; font-weight:700; }
            .status-pill.good { color:#052e16; background:#22c55e; }
            .status-pill.warn { color:#422006; background:#f59e0b; }
            .status-pill.bad { color:#450a0a; background:#ef4444; }
            .health-grid { display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; }
            .health-item { background:rgba(0,0,0,.3); padding:12px; border-radius:4px; }
            .health-value { margin-top:5px; font-size:14px; font-weight:600; overflow-wrap:anywhere; }
            .timeframes { margin-top:15px; }
            .tf-chip { display:inline-block; margin:7px 7px 0 0; padding:6px 9px; background:#0f172a; border:1px solid #334155; border-radius:4px; font-size:12px; }
            .health-note, .muted { color:#64748b; font-size:11px; margin-top:12px; }
            .capital-box {
                background: #1e293b;
                border: 2px solid #334155;
                border-radius: 8px;
                padding: 20px;
            }
            .capital-box.c { border-color: #10b981; }
            .capital-title {
                color: #10b981;
                font-size: 14px;
                margin-bottom: 15px;
                text-transform: uppercase;
                font-weight: 600;
            }
            .capital-row {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 15px;
                padding: 10px;
                background: rgba(0,0,0,0.2);
                border-radius: 4px;
            }
            .capital-label {
                color: #94a3b8;
                font-size: 12px;
                text-transform: uppercase;
            }
            .capital-value {
                font-size: 18px;
                font-weight: 600;
                color: #f1f5f9;
            }
            .positive { color: #10b981; }
            .negative { color: #ef4444; }

            .metrics-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 30px;
            }
            .system {
                background: #1e293b;
                border: 2px solid #334155;
                border-radius: 8px;
                padding: 20px;
            }
            .system.c { border-color: #10b981; }
            .system h2 {
                color: #10b981;
                font-size: 16px;
                margin-bottom: 20px;
            }

            .metrics-grid-2 {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 15px;
            }
            .metric-box {
                background: rgba(0,0,0,0.3);
                padding: 15px;
                border-radius: 4px;
                border-left: 3px solid #10b981;
            }
            .metric-label {
                color: #94a3b8;
                font-size: 11px;
                text-transform: uppercase;
                margin-bottom: 5px;
            }
            .metric-value {
                font-size: 20px;
                font-weight: 600;
            }

            .trades-section {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 30px;
            }
            .trades-box {
                background: #1e293b;
                border: 2px solid #334155;
                border-radius: 8px;
                padding: 20px;
            }
            .trades-box.c { border-color: #10b981; }
            .trades-box h3 {
                color: #10b981;
                font-size: 14px;
                margin-bottom: 15px;
                text-transform: uppercase;
            }

            table {
                width: 100%;
                border-collapse: collapse;
                font-size: 12px;
            }
            thead {
                background: rgba(0,0,0,0.3);
                border-bottom: 1px solid #334155;
            }
            th {
                padding: 10px;
                text-align: left;
                color: #94a3b8;
                text-transform: uppercase;
                font-weight: 600;
            }
            td {
                padding: 10px;
                border-bottom: 1px solid #1e293b;
            }
            tr:hover {
                background: rgba(16,185,129,0.1);
            }

            .last-updated {
                text-align: center;
                color: #64748b;
                font-size: 12px;
                margin-top: 20px;
            }
            @media (max-width: 800px) {
                .health-grid { grid-template-columns:1fr 1fr; }
                .capital-section, .metrics-grid, .trades-section { grid-template-columns:1fr; }
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🏆 Gold Signal Fetcher - System Comparison</h1>
            <p>System A (SMC-Only) vs System C (ML + Claude AI)</p>
        </div>

        <div class="container">
            ''' + feed_health + '''
            <!-- Capital Performance -->
            <div class="capital-section">
                <div class="capital-box">
                    <div class="capital-title">💰 System A: SMC-Only</div>
                    <div class="capital-row">
                        <div><div class="capital-label">Starting Capital</div><div class="capital-value">''' + metrics_a['starting_capital'] + '''</div></div>
                        <div><div class="capital-label">Current Capital</div><div class="capital-value">''' + metrics_a['current_capital'] + '''</div></div>
                    </div>
                    <div class="capital-row">
                        <div><div class="capital-label">Total Profit</div><div class="capital-value ''' + ('positive' if float(metrics_a['total_profit'].replace('$','').replace(',','')) >= 0 else 'negative') + '''"''' + metrics_a['total_profit'] + '''</div></div>
                        <div><div class="capital-label">Return %</div><div class="capital-value ''' + ('positive' if float(metrics_a['return_pct'].replace('%','').replace(',','')) >= 0 else 'negative') + '''"''' + metrics_a['return_pct'] + '''</div></div>
                    </div>
                </div>

                <div class="capital-box c">
                    <div class="capital-title">🤖 System C: ML + Claude</div>
                    <div class="capital-row">
                        <div><div class="capital-label">Starting Capital</div><div class="capital-value">''' + metrics_c['starting_capital'] + '''</div></div>
                        <div><div class="capital-label">Current Capital</div><div class="capital-value">''' + metrics_c['current_capital'] + '''</div></div>
                    </div>
                    <div class="capital-row">
                        <div><div class="capital-label">Total Profit</div><div class="capital-value ''' + ('positive' if float(metrics_c['total_profit'].replace('$','').replace(',','')) >= 0 else 'negative') + '''"''' + metrics_c['total_profit'] + '''</div></div>
                        <div><div class="capital-label">Return %</div><div class="capital-value ''' + ('positive' if float(metrics_c['return_pct'].replace('%','').replace(',','')) >= 0 else 'negative') + '''"''' + metrics_c['return_pct'] + '''</div></div>
                    </div>
                </div>
            </div>

            <!-- Metrics -->
            <div class="metrics-grid">
                <div class="system">
                    <h2>📊 System A: Metrics</h2>
                    <div class="metrics-grid-2">
                        <div class="metric-box">
                            <div class="metric-label">Total Trades</div>
                            <div class="metric-value">''' + str(metrics_a['signals']) + '''</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Win Rate</div>
                            <div class="metric-value">''' + metrics_a['win_rate'] + '''</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Wins / Losses</div>
                            <div class="metric-value">''' + str(metrics_a['wins']) + ''' / ''' + str(metrics_a['losses']) + '''</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Profit Factor</div>
                            <div class="metric-value">''' + metrics_a['profit_factor'] + '''</div>
                        </div>
                    </div>
                </div>

                <div class="system c">
                    <h2>🤖 System C: Metrics</h2>
                    <div class="metrics-grid-2">
                        <div class="metric-box">
                            <div class="metric-label">Total Trades</div>
                            <div class="metric-value">''' + str(metrics_c['signals']) + '''</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Win Rate</div>
                            <div class="metric-value">''' + metrics_c['win_rate'] + '''</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Wins / Losses</div>
                            <div class="metric-value">''' + str(metrics_c['wins']) + ''' / ''' + str(metrics_c['losses']) + '''</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Profit Factor</div>
                            <div class="metric-value">''' + metrics_c['profit_factor'] + '''</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Trades Tables -->
            <div class="trades-section">
                <div class="trades-box">
                    <h3>📋 Recent Closed Trades - System A</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Dir</th>
                                <th>Outcome</th>
                                <th>Entry</th>
                                <th>Close</th>
                                <th>P&L %</th>
                                <th>P&L $</th>
                                <th>Closed At</th>
                            </tr>
                        </thead>
                        <tbody>
                            ''' + trades_a + '''
                        </tbody>
                    </table>
                </div>

                <div class="trades-box c">
                    <h3>📋 Recent Closed Trades - System C</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Dir</th>
                                <th>Outcome</th>
                                <th>Entry</th>
                                <th>Close</th>
                                <th>P&L %</th>
                                <th>P&L $</th>
                                <th>Closed At</th>
                            </tr>
                        </thead>
                        <tbody>
                            ''' + trades_c + '''
                        </tbody>
                    </table>
                </div>
            </div>

            <div class="last-updated">
                📅 Last updated: ''' + datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S') + ''' UTC | Auto-refresh every 60s
            </div>
        </div>

        <script>
            // Auto-refresh every 60 seconds
            setTimeout(() => location.reload(), 60000);
        </script>
    </body>
    </html>
    '''

    return render_template_string(html)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8502, debug=False)
