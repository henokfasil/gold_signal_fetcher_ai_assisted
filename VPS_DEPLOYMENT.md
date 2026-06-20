# VPS Deployment Guide: System C (ML + Claude)

Deploy alongside System A for parallel 4-week testing.

## Quick Setup (5 minutes)

### 1. Copy files to VPS
```bash
sshpass -p 'hFr57ig-mN?UY#' scp -r /Users/henok/gold_signal_fetcher_ai_assisted/* \
  root@72.60.133.179:/root/gold_signal_fetcher_ai_assisted/
```

### 2. SSH into VPS
```bash
sshpass -p 'hFr57ig-mN?UY#' ssh -o StrictHostKeyChecking=no root@72.60.133.179
```

### 3. Install dependencies (on VPS)
```bash
cd /root/gold_signal_fetcher_ai_assisted

# Create venv if not exists
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 4. Setup environment (on VPS)
```bash
# Copy .env.example to .env and update
cp .env.example .env
nano .env

# Required variables:
# METAAPI_TOKEN=...
# METAAPI_ACCOUNT_ID=...
# TELEGRAM_TOKEN=...
# TELEGRAM_CHAT_ID=...
# ANTHROPIC_API_KEY=...  (for Claude)
```

### 5. Create data directories
```bash
mkdir -p /root/gold_signal_fetcher_ai_assisted/data
mkdir -p /root/gold_signal_fetcher_ai_assisted/models
touch /root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv
```

### 6. Initialize paper trades CSV
```bash
cat > /root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv << 'EOF'
timestamp,pair,direction,entry,stop_loss,take_profits,pnl,signal_source,ml_confidence,claude_confidence,combined_confidence
EOF
```

---

## Cron Setup (on VPS)

### System A: SMC-only (existing)
```bash
crontab -e
```

Add (if not already there):
```
# System A: SMC signals every 5 minutes (Mon-Fri)
*/5 * * * 1-5 cd /root/Gold_Signal_Fetcher && set -a && . .env && set +a && /root/Gold_Signal_Fetcher/venv/bin/python main.py >> /var/log/gold_scanner.log 2>&1
```

### System C: ML + Claude (new)
```bash
crontab -e
```

Add:
```
# System C: AI-assisted signals every 5 minutes (Mon-Fri)
*/5 * * * 1-5 cd /root/gold_signal_fetcher_ai_assisted && set -a && . .env && set +a && /root/gold_signal_fetcher_ai_assisted/venv/bin/python main_orchestrator.py >> /var/log/gold_scanner_ai.log 2>&1
```

Verify both are installed:
```bash
crontab -l
```

---

## Dashboard Setup (on VPS)

### Start dashboard in background
```bash
cd /root/gold_signal_fetcher_ai_assisted
source venv/bin/activate

# Start Flask dashboard on port 8502
nohup python dashboard.py > /var/log/gold_dashboard.log 2>&1 &
```

### Access dashboard
From your local machine:
```
http://72.60.133.179:8502
```

### Monitor dashboard
```bash
tail -f /var/log/gold_dashboard.log
```

---

## Monitoring Commands

### Monitor both system logs in real-time
```bash
# System A
tail -f /var/log/gold_scanner.log

# System C
tail -f /var/log/gold_scanner_ai.log

# Dashboard
tail -f /var/log/gold_dashboard.log
```

### Check cron execution
```bash
# Verify cron jobs ran
grep "gold_scanner" /var/log/syslog | tail -20

# Check for errors
grep "ERROR" /var/log/gold_scanner_ai.log | tail -10
```

### View paper trade results
```bash
# System A
tail -20 /root/Gold_Signal_Fetcher/data/paper_trades.csv

# System C
tail -20 /root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv
```

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'agent'"
Ensure you're in the correct directory:
```bash
cd /root/gold_signal_fetcher_ai_assisted
source venv/bin/activate
python main_orchestrator.py
```

### "ANTHROPIC_API_KEY not found"
Check .env file exists and has the key:
```bash
cat /root/gold_signal_fetcher_ai_assisted/.env | grep ANTHROPIC_API_KEY
```

### Cron not running
Check crontab syntax:
```bash
crontab -l
```

Check if the venv Python path is correct:
```bash
which python3
# Should be: /root/gold_signal_fetcher_ai_assisted/venv/bin/python3
```

### Dashboard not loading
Check if Flask is running:
```bash
lsof -i :8502
```

Restart it:
```bash
pkill -f "python dashboard.py"
cd /root/gold_signal_fetcher_ai_assisted && source venv/bin/activate && nohup python dashboard.py > /var/log/gold_dashboard.log 2>&1 &
```

---

## Daily Monitoring Checklist

### Every day at market open (08:00 UTC):
1. Check both systems executed signals:
   ```bash
   tail -5 /var/log/gold_scanner.log
   tail -5 /var/log/gold_scanner_ai.log
   ```

2. View dashboard metrics:
   - Win rate for each system
   - P&L comparison
   - Signal counts

3. Check for errors:
   ```bash
   grep "ERROR" /var/log/gold_scanner*.log
   grep "ERROR" /var/log/gold_dashboard.log
   ```

### Weekly (every Sunday evening):
1. Calculate metrics:
   ```bash
   # System A win rate
   awk -F',' '$7 > 0' /root/Gold_Signal_Fetcher/data/paper_trades.csv | wc -l
   
   # System C win rate
   awk -F',' '$7 > 0' /root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv | wc -l
   ```

2. Compare P&L:
   ```bash
   # System A total
   awk -F',' '{sum+=$7} END {print "System A P&L:", sum}' /root/Gold_Signal_Fetcher/data/paper_trades.csv
   
   # System C total
   awk -F',' '{sum+=$7} END {print "System C P&L:", sum}' /root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv
   ```

---

## File Structure on VPS

```
/root/gold_signal_fetcher_ai_assisted/
├── main_orchestrator.py           # Main entry point (called by cron)
├── dashboard.py                   # Flask dashboard (port 8502)
├── agent/
│   ├── smc_gold_scanner.py       # SMC signal generation
│   ├── ml_feature_engineer.py    # 16 technical features
│   ├── ml_signal_generator.py    # XGBoost predictor
│   ├── claude_analyst.py         # Claude API integration
│   ├── paper_trader.py           # Trade execution
│   ├── liquidity_manager.py      # Session/tier logic
│   ├── notifier.py               # Telegram notifications
│   └── sessions.py               # Session management
├── models/
│   ├── xgboost_gold_model.pkl    # ML model (auto-created)
│   └── feature_cols.json         # Feature names
├── data/
│   └── paper_trades_ai.csv       # Results tracking
├── config/
│   └── settings.py               # Configuration
├── .env                          # Environment variables
├── requirements.txt              # Python dependencies
├── venv/                         # Virtual environment
└── VPS_DEPLOYMENT.md             # This file

/var/log/
├── gold_scanner.log              # System A execution log
├── gold_scanner_ai.log           # System C execution log
└── gold_dashboard.log            # Dashboard log

/root/Gold_Signal_Fetcher/
├── data/
│   └── paper_trades.csv          # System A results
└── [System A files...]
```

---

## Success Indicators

### After first 24 hours:
- [ ] Both cron jobs executed (check logs)
- [ ] Both CSV files have entries
- [ ] Dashboard loads without errors
- [ ] No "ModuleNotFoundError" in logs

### After first week:
- [ ] System A has 5+ signals
- [ ] System C has 5+ signals
- [ ] Dashboard shows metrics for both
- [ ] No API errors in logs

### After 4 weeks:
- [ ] Win rates calculable for both systems
- [ ] P&L difference clear (one winning)
- [ ] Ready to decide on production integration

---

## Stopping/Restarting Systems

### Stop cron (pause scanning)
```bash
# Comment out both lines in crontab
crontab -e
```

### Restart cron (resume scanning)
```bash
crontab -e
```

### Restart dashboard only
```bash
pkill -f "python dashboard.py"
cd /root/gold_signal_fetcher_ai_assisted && source venv/bin/activate && \
nohup python dashboard.py > /var/log/gold_dashboard.log 2>&1 &
```

### Full restart (everything)
```bash
# Stop
crontab -e  # Comment out lines
pkill -f "python dashboard.py"

# Wait 30 seconds, then restart
crontab -e  # Uncomment lines
cd /root/gold_signal_fetcher_ai_assisted && source venv/bin/activate && \
nohup python dashboard.py > /var/log/gold_dashboard.log 2>&1 &
```

---

## Cost Tracking

### Costs per week:
- **XGBoost:** $0 (local compute)
- **Claude API:** ~$0.84 (1 analysis/5 min × 48 min/day × 5 days × $0.003)
- **MetaApi:** Depends on plan
- **VPS:** ~$15 (existing)

Total: ~$15.84/week for testing

---

## Next Steps

1. Deploy files to VPS
2. Install dependencies
3. Set up .env with all keys
4. Add both cron jobs
5. Start dashboard
6. Monitor metrics for 4 weeks
7. Compare System A vs System C
8. Decide: integrate winner into production?

---

Last updated: 2026-06-21
Status: Ready for deployment
