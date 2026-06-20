"""
Comparison Dashboard: System A (SMC) vs System C (ML + Claude)
Real-time side-by-side metrics during 4-week parallel testing.
"""

import os
import json
import pandas as pd
from datetime import datetime, timedelta
from flask import Flask, render_template_string
from pathlib import Path

app = Flask(__name__)

SYSTEM_A_LOG = Path("/var/log/gold_scanner.log")
SYSTEM_C_LOG = Path("/var/log/gold_scanner_ai.log")
SYSTEM_A_CSV = Path("/root/Gold_Signal_Fetcher/data/paper_trades.csv")
SYSTEM_C_CSV = Path("/root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv")


def calculate_metrics(csv_path):
    """Calculate trading metrics from paper trades CSV."""
    try:
        if not csv_path.exists():
            return {
                'status': 'Not started',
                'signals': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'total_pnl': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'sharpe': 0,
                'max_dd': 0
            }

        df = pd.read_csv(csv_path)

        if df.empty:
            return {'status': 'No trades yet', 'signals': 0}

        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] < 0]

        win_count = len(wins)
        loss_count = len(losses)
        total = len(df)

        win_rate = (win_count / total * 100) if total > 0 else 0
        total_pnl = df['pnl'].sum()
        avg_win = wins['pnl'].mean() if len(wins) > 0 else 0
        avg_loss = losses['pnl'].mean() if len(losses) > 0 else 0

        # Profit factor
        total_wins = wins['pnl'].sum() if len(wins) > 0 else 0
        total_losses = abs(losses['pnl'].sum()) if len(losses) > 0 else 1
        profit_factor = total_wins / total_losses if total_losses > 0 else 0

        # Sharpe ratio (simplified)
        returns = df['pnl'].pct_change().dropna()
        sharpe = (returns.mean() / returns.std() * 252) if len(returns) > 0 else 0

        # Max drawdown
        cumsum = df['pnl'].cumsum()
        running_max = cumsum.expanding().max()
        dd = (cumsum - running_max) / running_max
        max_dd = dd.min() * 100 if len(dd) > 0 else 0

        return {
            'status': 'Running',
            'signals': total,
            'wins': win_count,
            'losses': loss_count,
            'win_rate': f"{win_rate:.1f}%",
            'profit_factor': f"{profit_factor:.2f}",
            'total_pnl': f"${total_pnl:.2f}",
            'avg_win': f"${avg_win:.2f}",
            'avg_loss': f"${avg_loss:.2f}",
            'sharpe': f"{sharpe:.2f}",
            'max_dd': f"{max_dd:.1f}%"
        }
    except Exception as e:
        return {'status': f'Error: {str(e)}', 'signals': 0}


def get_winner_class(c_val, a_val):
    """Compare values and return CSS class if C wins."""
    try:
        c_num = float(str(c_val).rstrip('%').replace('$', ''))
        a_num = float(str(a_val).rstrip('%').replace('$', ''))
        return 'winner' if c_num > a_num else ''
    except:
        return ''


@app.route('/')
def dashboard():
    """Render comparison dashboard."""
    system_a = calculate_metrics(SYSTEM_A_CSV)
    system_c = calculate_metrics(SYSTEM_C_CSV)

    # Build comparison rows
    comparison_rows = f'''
                <div class="row">
                    <div class="row-label">Win Rate</div>
                    <div class="row-value">{system_a['win_rate']}</div>
                    <div class="row-value {get_winner_class(system_c['win_rate'], system_a['win_rate'])}">{system_c['win_rate']}</div>
                </div>
                <div class="row">
                    <div class="row-label">Profit Factor</div>
                    <div class="row-value">{system_a['profit_factor']}</div>
                    <div class="row-value {get_winner_class(system_c['profit_factor'], system_a['profit_factor'])}">{system_c['profit_factor']}</div>
                </div>
                <div class="row">
                    <div class="row-label">Total P&L</div>
                    <div class="row-value">{system_a['total_pnl']}</div>
                    <div class="row-value {get_winner_class(system_c['total_pnl'], system_a['total_pnl'])}">{system_c['total_pnl']}</div>
                </div>
    '''

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Gold Scanner: System A vs C</title>
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
            }
            .header p {
                color: #94a3b8;
                font-size: 14px;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
            }
            .system {
                background: #1e293b;
                border: 2px solid #334155;
                border-radius: 8px;
                padding: 20px;
            }
            .system.c {
                border-color: #10b981;
                background: linear-gradient(135deg, #1e293b 0%, #064e3b 100%);
            }
            .system h2 {
                font-size: 20px;
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 2px solid #334155;
            }
            .system.c h2 {
                border-color: #10b981;
                color: #10b981;
            }
            .metrics {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 15px;
            }
            .metric {
                background: rgba(0, 0, 0, 0.3);
                padding: 12px;
                border-radius: 6px;
                border-left: 3px solid #334155;
            }
            .system.c .metric {
                border-left-color: #10b981;
            }
            .metric-label {
                font-size: 12px;
                color: #94a3b8;
                text-transform: uppercase;
                margin-bottom: 5px;
            }
            .metric-value {
                font-size: 18px;
                font-weight: 600;
                color: #f1f5f9;
            }
            .good {
                color: #10b981;
            }
            .bad {
                color: #ef4444;
            }
            .status {
                padding: 10px;
                border-radius: 4px;
                font-size: 12px;
                margin-bottom: 15px;
            }
            .status.running {
                background: #1e3a1f;
                color: #10b981;
                border: 1px solid #10b981;
            }
            .status.pending {
                background: #3f3825;
                color: #f59e0b;
                border: 1px solid #f59e0b;
            }
            .comparison {
                grid-column: 1 / -1;
                background: #1e293b;
                border: 2px solid #334155;
                border-radius: 8px;
                padding: 20px;
                margin-top: 10px;
            }
            .comparison h3 {
                margin-bottom: 15px;
                color: #10b981;
            }
            .row {
                display: grid;
                grid-template-columns: 150px 1fr 1fr;
                gap: 15px;
                padding: 10px 0;
                border-bottom: 1px solid #334155;
            }
            .row:last-child {
                border-bottom: none;
            }
            .row-label {
                color: #94a3b8;
                font-size: 12px;
                text-transform: uppercase;
            }
            .row-value {
                font-weight: 600;
            }
            .winner {
                background: rgba(16, 185, 129, 0.1);
                border-left: 3px solid #10b981;
                padding-left: 10px;
                color: #10b981;
            }
            .footer {
                grid-column: 1 / -1;
                text-align: center;
                margin-top: 20px;
                color: #64748b;
                font-size: 12px;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🤖 Gold Signal Fetcher - 4-Week Comparison</h1>
            <p>System A (SMC-only) vs System C (ML + Claude AI)</p>
            <p style="font-size: 12px; margin-top: 10px;">Last updated: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC") + """</p>
        </div>

        <div class="container">
            <!-- System A -->
            <div class="system">
                <h2>⚙️ System A: SMC-Only</h2>
                <div class="status """ + ('running' if system_a['signals'] > 0 else 'pending') + """">
                    """ + system_a['status'] + """
                </div>
                <div class="metrics">
                    <div class="metric">
                        <div class="metric-label">Signals</div>
                        <div class="metric-value">""" + str(system_a['signals']) + """</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Win Rate</div>
                        <div class="metric-value">""" + str(system_a['win_rate']) + """</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Wins/Losses</div>
                        <div class="metric-value">""" + str(system_a['wins']) + """/""" + str(system_a['losses']) + """</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Profit Factor</div>
                        <div class="metric-value">""" + str(system_a['profit_factor']) + """</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Total P&L</div>
                        <div class="metric-value">""" + str(system_a['total_pnl']) + """</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Sharpe Ratio</div>
                        <div class="metric-value">""" + str(system_a['sharpe']) + """</div>
                    </div>
                </div>
            </div>

            <!-- System C -->
            <div class="system c">
                <h2>🧠 System C: ML + Claude</h2>
                <div class="status """ + ('running' if system_c['signals'] > 0 else 'pending') + """">
                    """ + system_c['status'] + """
                </div>
                <div class="metrics">
                    <div class="metric">
                        <div class="metric-label">Signals</div>
                        <div class="metric-value">""" + str(system_c['signals']) + """</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Win Rate</div>
                        <div class="metric-value">""" + str(system_c['win_rate']) + """</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Wins/Losses</div>
                        <div class="metric-value">""" + str(system_c['wins']) + """/""" + str(system_c['losses']) + """</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Profit Factor</div>
                        <div class="metric-value">""" + str(system_c['profit_factor']) + """</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Total P&L</div>
                        <div class="metric-value">""" + str(system_c['total_pnl']) + """</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Sharpe Ratio</div>
                        <div class="metric-value">""" + str(system_c['sharpe']) + """</div>
                    </div>
                </div>
            </div>

            <!-- Comparison -->
            <div class="comparison">
                <h3>📊 Head-to-Head Metrics</h3>
                <div class="row">
                    <div class="row-label">Metric</div>
                    <div class="row-label">System A</div>
                    <div class="row-label">System C</div>
                </div>
                """ + comparison_rows + """
            </div>
        </div>

        <div class="footer">
            System A (SMC baseline) vs System C (ML + Claude combo) | Running parallel for 4 weeks | Auto-refresh every 60s
        </div>

        <script>
            setTimeout(() => location.reload(), 60000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8502, debug=False)
