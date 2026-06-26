"""
Enhanced Fast Dashboard with Charts & Full Trade Details
"""

import os
import re
import pandas as pd
from datetime import datetime
from flask import Flask
from pathlib import Path

app = Flask(__name__)

SYSTEM_A_CSV = Path("/root/Gold_Signal_Fetcher/data/paper_trades.csv")
SYSTEM_C_CSV = Path("/root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv")


def get_metrics(csv_path):
    """Fast metrics calculation."""
    try:
        if not csv_path.exists():
            return {'signals': 0, 'wins': 0, 'losses': 0, 'pnl': 0}

        df = pd.read_csv(csv_path)
        if df.empty:
            return {'signals': 0, 'wins': 0, 'losses': 0, 'pnl': 0}

        pnl_col = 'pnl' if 'pnl' in df.columns else 'profit_pct'
        df[pnl_col] = pd.to_numeric(df[pnl_col], errors='coerce').fillna(0)

        signals = len(df)
        wins = len(df[df[pnl_col] > 0])
        losses = len(df[df[pnl_col] < 0])
        pnl = df[pnl_col].sum()

        return {'signals': signals, 'wins': wins, 'losses': losses, 'pnl': pnl}
    except:
        return {'signals': 0, 'wins': 0, 'losses': 0, 'pnl': 0}


def get_equity_curve_data(csv_path):
    """Get cumulative P&L for equity curve."""
    try:
        if not csv_path.exists():
            return []

        df = pd.read_csv(csv_path)
        if df.empty:
            return []

        pnl_col = 'pnl' if 'pnl' in df.columns else 'profit_pct'
        df[pnl_col] = pd.to_numeric(df[pnl_col], errors='coerce').fillna(0)

        # Calculate cumulative equity
        cumsum = df[pnl_col].cumsum()
        starting_capital = 10000
        equity = starting_capital + cumsum

        # Return as JSON-compatible format
        return [float(e) for e in equity.tail(50).tolist()]
    except:
        return []


def get_recent_trades_html(csv_path):
    """Get trade rows with full details."""
    try:
        if not csv_path.exists():
            return '<tr><td colspan="10">No trades</td></tr>'

        df = pd.read_csv(csv_path)
        if df.empty:
            return '<tr><td colspan="10">No trades</td></tr>'

        pnl_col = 'pnl' if 'pnl' in df.columns else 'profit_pct'
        df[pnl_col] = pd.to_numeric(df[pnl_col], errors='coerce').fillna(0)

        html = ''
        for _, row in df.tail(10).iterrows():
            pair = row.get('pair', row.get('symbol', 'XAUUSD'))
            direction = row.get('direction', '?')
            entry = str(row.get('entry', row.get('entry_price', '?')))
            sl = str(row.get('stop_loss', row.get('sl', '?')))
            tp = str(row.get('take_profits', row.get('take_profit', '?')))
            pnl = float(row[pnl_col])
            color = '#10b981' if pnl > 0 else '#ef4444' if pnl < 0 else '#666'
            outcome = 'WIN' if pnl > 0 else 'LOSS' if pnl < 0 else 'OPEN'
            timestamp = row.get('timestamp', '')[:10]

            # Clean up TP (remove numpy string representation)
            if 'np.float64' in tp or 'np.float32' in tp or '[' in tp:
                # Extract number from strings like "np.float64(4220.84)" or "[np.float64(4220.84)]"
                # Look for pattern: (number) inside parentheses
                match = re.search(r'\((\d+\.?\d*)\)', tp)
                if match:
                    tp = match.group(1)
                else:
                    # Fallback: just get any number with decimal
                    match = re.search(r'(\d{4,}\.\d+)', tp)
                    tp = match.group(1) if match else 'N/A'

            # Clean up entry and SL too
            entry = entry.replace('?', 'N/A')
            sl = sl.replace('?', 'N/A')
            tp = tp.replace('?', 'N/A')

            html += f'<tr><td>{pair}</td><td>{direction}</td><td>{entry}</td><td>{sl}</td><td>{tp}</td><td style="color:{color}">{outcome}</td><td style="color:{color}">{pnl:.2f}</td><td>{timestamp}</td></tr>'

        return html
    except Exception as e:
        return f'<tr><td colspan="10">Error: {str(e)[:50]}</td></tr>'


@app.route('/')
def dashboard():
    """Enhanced dashboard with charts."""
    m_a = get_metrics(SYSTEM_A_CSV)
    m_c = get_metrics(SYSTEM_C_CSV)

    wr_a = f"{(m_a['wins']/m_a['signals']*100):.1f}%" if m_a['signals'] > 0 else "0%"
    wr_c = f"{(m_c['wins']/m_c['signals']*100):.1f}%" if m_c['signals'] > 0 else "0%"

    trades_a = get_recent_trades_html(SYSTEM_A_CSV)
    trades_c = get_recent_trades_html(SYSTEM_C_CSV)

    equity_a = get_equity_curve_data(SYSTEM_A_CSV)
    equity_c = get_equity_curve_data(SYSTEM_C_CSV)

    equity_a_json = str(equity_a).replace("'", '"')
    equity_c_json = str(equity_c).replace("'", '"')

    return f'''<!DOCTYPE html>
<html>
<head>
    <title>Gold Signal Fetcher</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
    <style>
        * {{margin:0; padding:0; box-sizing:border-box;}}
        body {{font-family:Arial,sans-serif; background:#0f172a; color:#e2e8f0; padding:20px;}}
        .container {{max-width:1400px; margin:0 auto;}}
        h1 {{text-align:center; margin-bottom:30px; color:#10b981; font-size:28px;}}

        .metrics-grid {{display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:30px;}}
        .box {{background:#1e293b; border:2px solid #334155; border-radius:8px; padding:20px;}}
        .box.c {{border-color:#10b981;}}

        .title {{color:#10b981; font-size:14px; font-weight:bold; margin-bottom:15px; text-transform:uppercase;}}
        .metric {{display:grid; grid-template-columns:1fr 1fr; gap:15px; margin-bottom:10px;}}
        .metric-item {{background:rgba(0,0,0,0.3); padding:10px; border-radius:4px;}}
        .metric-label {{color:#94a3b8; font-size:11px; text-transform:uppercase;}}
        .metric-value {{font-size:16px; font-weight:bold;}}

        .charts-grid {{display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:30px;}}
        .chart-box {{background:#1e293b; border:2px solid #334155; border-radius:8px; padding:20px;}}
        .chart-box.c {{border-color:#10b981;}}
        .chart-title {{color:#10b981; font-size:12px; font-weight:bold; margin-bottom:15px; text-transform:uppercase;}}
        canvas {{max-height:250px;}}

        .trades-grid {{display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:30px;}}
        .trades-box {{background:#1e293b; border:2px solid #334155; border-radius:8px; padding:20px; overflow-x:auto;}}
        .trades-box.c {{border-color:#10b981;}}

        table {{width:100%; border-collapse:collapse; font-size:11px;}}
        thead {{background:rgba(0,0,0,0.3);}}
        th {{padding:8px; text-align:left; color:#94a3b8; text-transform:uppercase; font-weight:bold; border-bottom:1px solid #334155;}}
        td {{padding:8px; border-bottom:1px solid #1e293b;}}
        tr:hover {{background:rgba(16,185,129,0.1);}}

        .win {{color:#10b981;}}
        .loss {{color:#ef4444;}}
        .open {{color:#f59e0b;}}

        .footer {{text-align:center; color:#64748b; font-size:12px; margin-top:20px;}}
    </style>
</head>
<body>
    <div class="container">
        <h1>🏆 Gold Signal Fetcher - Live Dashboard</h1>

        <!-- Metrics -->
        <div class="metrics-grid">
            <div class="box">
                <div class="title">📊 System A: SMC-Only</div>
                <div class="metric">
                    <div class="metric-item"><div class="metric-label">Signals</div><div class="metric-value">{m_a['signals']}</div></div>
                    <div class="metric-item"><div class="metric-label">Win Rate</div><div class="metric-value">{wr_a}</div></div>
                    <div class="metric-item"><div class="metric-label">Wins/Losses</div><div class="metric-value">{m_a['wins']}/{m_a['losses']}</div></div>
                    <div class="metric-item"><div class="metric-label">Total P&L</div><div class="metric-value">${m_a['pnl']:.2f}</div></div>
                </div>
            </div>

            <div class="box c">
                <div class="title">🤖 System C: ML + Claude</div>
                <div class="metric">
                    <div class="metric-item"><div class="metric-label">Signals</div><div class="metric-value">{m_c['signals']}</div></div>
                    <div class="metric-item"><div class="metric-label">Win Rate</div><div class="metric-value">{wr_c}</div></div>
                    <div class="metric-item"><div class="metric-label">Wins/Losses</div><div class="metric-value">{m_c['wins']}/{m_c['losses']}</div></div>
                    <div class="metric-item"><div class="metric-label">Total P&L</div><div class="metric-value">${m_c['pnl']:.2f}</div></div>
                </div>
            </div>
        </div>

        <!-- Equity Curves -->
        <div class="charts-grid">
            <div class="chart-box">
                <div class="chart-title">📈 System A: Equity Curve</div>
                <canvas id="chartA"></canvas>
            </div>
            <div class="chart-box c">
                <div class="chart-title">📈 System C: Equity Curve</div>
                <canvas id="chartC"></canvas>
            </div>
        </div>

        <!-- Trade Tables -->
        <div class="trades-grid">
            <div class="trades-box">
                <div class="title">📋 Recent Trades - System A</div>
                <table>
                    <thead><tr><th>Pair</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Status</th><th>P&L</th><th>Date</th></tr></thead>
                    <tbody>{trades_a}</tbody>
                </table>
            </div>

            <div class="trades-box c">
                <div class="title">📋 Recent Trades - System C</div>
                <table>
                    <thead><tr><th>Pair</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Status</th><th>P&L</th><th>Date</th></tr></thead>
                    <tbody>{trades_c}</tbody>
                </table>
            </div>
        </div>

        <div class="footer">
            ✅ Live • Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC • Auto-refresh: 60s
        </div>
    </div>

    <script>
        // Chart.js initialization
        const ctxA = document.getElementById('chartA').getContext('2d');
        const ctxC = document.getElementById('chartC').getContext('2d');

        const equityA = {equity_a_json};
        const equityC = {equity_c_json};

        const labels = Array.from({{length: equityA.length}}, (_, i) => `Trade ${{i+1}}`);

        new Chart(ctxA, {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{
                    label: 'Capital ($)',
                    data: equityA,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    tension: 0.1,
                    fill: true
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{
                    legend: {{display: false}},
                    tooltip: {{backgroundColor: '#1e293b', titleColor: '#e2e8f0', bodyColor: '#e2e8f0'}}
                }},
                scales: {{
                    y: {{
                        beginAtZero: false,
                        grid: {{color: '#334155'}},
                        ticks: {{color: '#94a3b8'}}
                    }},
                    x: {{
                        grid: {{display: false}},
                        ticks: {{color: '#94a3b8', maxTicksLimit: 5}}
                    }}
                }}
            }}
        }});

        new Chart(ctxC, {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{
                    label: 'Capital ($)',
                    data: equityC,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 2,
                    tension: 0.1,
                    fill: true
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{
                    legend: {{display: false}},
                    tooltip: {{backgroundColor: '#1e293b', titleColor: '#e2e8f0', bodyColor: '#e2e8f0'}}
                }},
                scales: {{
                    y: {{
                        beginAtZero: false,
                        grid: {{color: '#334155'}},
                        ticks: {{color: '#94a3b8'}}
                    }},
                    x: {{
                        grid: {{display: false}},
                        ticks: {{color: '#94a3b8', maxTicksLimit: 5}}
                    }}
                }}
            }}
        }});

        // Auto-refresh
        setTimeout(() => location.reload(), 60000);
    </script>
</body>
</html>'''


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8502, debug=False)
