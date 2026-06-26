"""
Enhanced Dashboard: System A (SMC) vs System C (ML + Claude)
Includes equity curves, trade tables, capital performance.
"""

import os
import json
import pandas as pd
from datetime import datetime, timedelta
from flask import Flask, render_template_string
from pathlib import Path

app = Flask(__name__)

SYSTEM_A_CSV = Path("/root/Gold_Signal_Fetcher/data/paper_trades.csv")
SYSTEM_C_CSV = Path("/root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv")
STARTING_CAPITAL = 10000


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
    """Calculate metrics from trades."""
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

    # Determine PNL column
    pnl_col = 'pnl' if 'pnl' in df.columns else 'profit_pct'

    # Convert to numeric
    df[pnl_col] = pd.to_numeric(df[pnl_col], errors='coerce').fillna(0)

    total_trades = len(df)
    wins = len(df[df[pnl_col] > 0])
    losses = len(df[df[pnl_col] < 0])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    total_pnl = df[pnl_col].sum()
    current_capital = STARTING_CAPITAL + total_pnl
    return_pct = (total_pnl / STARTING_CAPITAL * 100)

    # Profit factor
    wins_sum = df[df[pnl_col] > 0][pnl_col].sum() if wins > 0 else 0
    losses_sum = abs(df[df[pnl_col] < 0][pnl_col].sum()) if losses > 0 else 1
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
    """Get recent closed trades."""
    df = load_trades(csv_path)
    if df.empty:
        return []

    # Determine PNL column
    pnl_col = 'pnl' if 'pnl' in df.columns else 'profit_pct'

    # Filter for closed trades (where pnl is not 0 or 'pending')
    df[pnl_col] = pd.to_numeric(df[pnl_col], errors='coerce')
    closed = df[df[pnl_col] != 0].tail(limit)

    trades = []
    for _, row in closed.iterrows():
        pair = row.get('pair', row.get('symbol', 'XAUUSD'))
        direction = row.get('direction', 'N/A')
        pnl = float(row[pnl_col])
        outcome = 'WIN' if pnl > 0 else 'LOSS'
        entry = row.get('entry', 'N/A')

        trades.append({
            'pair': pair,
            'direction': direction,
            'outcome': outcome,
            'entry': entry,
            'pnl_pct': f'{pnl:.2f}%' if pnl_col == 'profit_pct' else f'{(pnl/10000*100):.2f}%',
            'pnl_usd': f'${pnl:.2f}',
            'timestamp': row.get('timestamp', '')
        })

    return trades


def build_trade_rows_html(csv_path):
    """Build HTML table rows for recent trades."""
    trades = get_recent_trades(csv_path, limit=10)

    if not trades:
        return '<tr><td colspan="7" style="text-align:center; padding:20px; color:#94a3b8;">No closed trades</td></tr>'

    rows = ''
    for trade in trades:
        color = '#10b981' if trade['outcome'] == 'WIN' else '#ef4444'
        rows += f'''
        <tr>
            <td>{trade['pair']}</td>
            <td>{trade['direction']}</td>
            <td style="color:{color}">{trade['outcome']}</td>
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

    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Gold Signal Fetcher - Dashboard</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
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
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🏆 Gold Signal Fetcher - System Comparison</h1>
            <p>System A (SMC-Only) vs System C (ML + Claude AI)</p>
        </div>

        <div class="container">
            <!-- Capital Performance -->
            <div class="capital-section">
                <div class="capital-box">
                    <div class="capital-title">💰 System A: SMC-Only</div>
                    <div class="capital-row">
                        <div><div class="capital-label">Starting Capital</div><div class="capital-value">''' + metrics_a['starting_capital'] + '''</div></div>
                        <div><div class="capital-label">Current Capital</div><div class="capital-value">''' + metrics_a['current_capital'] + '''</div></div>
                    </div>
                    <div class="capital-row">
                        <div><div class="capital-label">Total Profit</div><div class="capital-value ''' + ('positive' if float(metrics_a['total_profit'].replace('$','')) >= 0 else 'negative') + '''"''' + metrics_a['total_profit'] + '''</div></div>
                        <div><div class="capital-label">Return %</div><div class="capital-value ''' + ('positive' if float(metrics_a['return_pct'].replace('%','')) >= 0 else 'negative') + '''"''' + metrics_a['return_pct'] + '''</div></div>
                    </div>
                </div>

                <div class="capital-box c">
                    <div class="capital-title">🤖 System C: ML + Claude</div>
                    <div class="capital-row">
                        <div><div class="capital-label">Starting Capital</div><div class="capital-value">''' + metrics_c['starting_capital'] + '''</div></div>
                        <div><div class="capital-label">Current Capital</div><div class="capital-value">''' + metrics_c['current_capital'] + '''</div></div>
                    </div>
                    <div class="capital-row">
                        <div><div class="capital-label">Total Profit</div><div class="capital-value ''' + ('positive' if float(metrics_c['total_profit'].replace('$','')) >= 0 else 'negative') + '''"''' + metrics_c['total_profit'] + '''</div></div>
                        <div><div class="capital-label">Return %</div><div class="capital-value ''' + ('positive' if float(metrics_c['return_pct'].replace('%','')) >= 0 else 'negative') + '''"''' + metrics_c['return_pct'] + '''</div></div>
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
