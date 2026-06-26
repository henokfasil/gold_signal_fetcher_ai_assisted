"""
Fast Dashboard: Minimal but informative
"""

import os
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


def get_recent_trades_html(csv_path):
    """Get trade rows."""
    try:
        if not csv_path.exists():
            return '<tr><td colspan="6">No trades</td></tr>'

        df = pd.read_csv(csv_path)
        if df.empty:
            return '<tr><td colspan="6">No trades</td></tr>'

        pnl_col = 'pnl' if 'pnl' in df.columns else 'profit_pct'
        df[pnl_col] = pd.to_numeric(df[pnl_col], errors='coerce').fillna(0)

        html = ''
        for _, row in df.tail(10).iterrows():
            pair = row.get('pair', row.get('symbol', 'XAUUSD'))
            direction = row.get('direction', '?')
            entry = row.get('entry', '?')
            pnl = float(row[pnl_col])
            color = '#10b981' if pnl > 0 else '#ef4444' if pnl < 0 else '#666'
            outcome = 'WIN' if pnl > 0 else 'LOSS' if pnl < 0 else 'OPEN'

            html += f'<tr><td>{pair}</td><td>{direction}</td><td>{entry}</td><td style="color:{color}">{outcome}</td><td style="color:{color}">{pnl:.2f}</td><td>{row.get("timestamp", "")[:10]}</td></tr>'

        return html
    except:
        return '<tr><td colspan="6">Error loading trades</td></tr>'


@app.route('/')
def dashboard():
    """Ultra-fast dashboard."""
    m_a = get_metrics(SYSTEM_A_CSV)
    m_c = get_metrics(SYSTEM_C_CSV)

    wr_a = f"{(m_a['wins']/m_a['signals']*100):.1f}%" if m_a['signals'] > 0 else "0%"
    wr_c = f"{(m_c['wins']/m_c['signals']*100):.1f}%" if m_c['signals'] > 0 else "0%"

    trades_a = get_recent_trades_html(SYSTEM_A_CSV)
    trades_c = get_recent_trades_html(SYSTEM_C_CSV)

    return f'''<!DOCTYPE html>
<html>
<head>
    <title>Gold Signal Fetcher</title>
    <style>
        * {{margin:0; padding:0; box-sizing:border-box;}}
        body {{font-family:Arial,sans-serif; background:#0f172a; color:#e2e8f0; padding:20px;}}
        .container {{max-width:1200px; margin:0 auto;}}
        h1 {{text-align:center; margin-bottom:30px; color:#10b981;}}
        .grid {{display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:30px;}}
        .box {{background:#1e293b; border:2px solid #334155; border-radius:8px; padding:20px;}}
        .box.c {{border-color:#10b981;}}
        .title {{color:#10b981; font-size:14px; font-weight:bold; margin-bottom:15px; text-transform:uppercase;}}
        .metric {{display:grid; grid-template-columns:1fr 1fr; gap:15px; margin-bottom:10px;}}
        .metric-item {{background:rgba(0,0,0,0.3); padding:10px; border-radius:4px;}}
        .metric-label {{color:#94a3b8; font-size:11px; text-transform:uppercase;}}
        .metric-value {{font-size:16px; font-weight:bold;}}
        table {{width:100%; font-size:12px; margin-top:15px;}}
        thead {{background:rgba(0,0,0,0.3);}}
        th {{padding:8px; text-align:left; color:#94a3b8; text-transform:uppercase; font-weight:bold;}}
        td {{padding:8px; border-bottom:1px solid #1e293b;}}
        .win {{color:#10b981;}}
        .loss {{color:#ef4444;}}
        .footer {{text-align:center; color:#64748b; font-size:12px; margin-top:20px;}}
    </style>
</head>
<body>
    <div class="container">
        <h1>🏆 Gold Signal Fetcher - Live Dashboard</h1>

        <div class="grid">
            <div class="box">
                <div class="title">📊 System A: SMC-Only</div>
                <div class="metric">
                    <div class="metric-item"><div class="metric-label">Signals</div><div class="metric-value">{m_a['signals']}</div></div>
                    <div class="metric-item"><div class="metric-label">Win Rate</div><div class="metric-value">{wr_a}</div></div>
                    <div class="metric-item"><div class="metric-label">Wins/Losses</div><div class="metric-value">{m_a['wins']}/{m_a['losses']}</div></div>
                    <div class="metric-item"><div class="metric-label">Total P&L</div><div class="metric-value">${m_a['pnl']:.2f}</div></div>
                </div>
                <table>
                    <thead><tr><th>Pair</th><th>Dir</th><th>Entry</th><th>Status</th><th>P&L</th><th>Date</th></tr></thead>
                    <tbody>{trades_a}</tbody>
                </table>
            </div>

            <div class="box c">
                <div class="title">🤖 System C: ML + Claude</div>
                <div class="metric">
                    <div class="metric-item"><div class="metric-label">Signals</div><div class="metric-value">{m_c['signals']}</div></div>
                    <div class="metric-item"><div class="metric-label">Win Rate</div><div class="metric-value">{wr_c}</div></div>
                    <div class="metric-item"><div class="metric-label">Wins/Losses</div><div class="metric-value">{m_c['wins']}/{m_c['losses']}</div></div>
                    <div class="metric-item"><div class="metric-label">Total P&L</div><div class="metric-value">${m_c['pnl']:.2f}</div></div>
                </div>
                <table>
                    <thead><tr><th>Pair</th><th>Dir</th><th>Entry</th><th>Status</th><th>P&L</th><th>Date</th></tr></thead>
                    <tbody>{trades_c}</tbody>
                </table>
            </div>
        </div>

        <div class="footer">
            ✅ Live • Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC • Auto-refresh: 60s
        </div>
    </div>
    <script>setTimeout(() => location.reload(), 60000);</script>
</body>
</html>'''


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8502, debug=False)
