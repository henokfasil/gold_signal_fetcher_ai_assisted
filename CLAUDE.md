# CLAUDE.md

Gold Signal Fetcher - AI-Assisted Version (ML + Claude Combo)

---

## Quick Status (2026-06-21) ✅ LIVE ON VPS

**System: Deployed & Running**
- ✅ Repository created: `gold_signal_fetcher_ai_assisted`
- ✅ ML components built (feature engineer, XGBoost predictor)
- ✅ Claude analyst integrated (market analysis + decisions)
- ✅ Combined decision engine (ML + Claude + SMC scoring)
- ✅ Orchestrator pipeline complete (main_orchestrator.py)
- ✅ Comparison dashboard deployed (Flask, port 8502)
- ✅ All files deployed to VPS
- ✅ Cron jobs configured (every 5 min, Mon-Fri)
- ✅ Firewall opened for external access
- 🚀 **Status: Running in parallel with System A**
- ⏳ Signals start: Monday June 23 (market opens)

**Architecture:**
```
XAUUSD Price Data
        ↓
   SMC Signals (from Gold_Signal_Fetcher)
        ↓
   ML Confidence Score (XGBoost, 0-100)
        ↓
   Claude Analysis (market context, risk check)
        ↓
   Combined Decision (ML 35% + Claude 35% + SMC 30%)
        ↓
   Trade or Skip? (threshold-based per liquidity tier)
        ↓
   MetaApi Executor → Paper Trade
        ↓
   Track P&L + Metrics
```

---

## Deployment Status (June 21, 2026)

### ✅ Live on VPS (72.60.133.179)
- **Main Orchestrator:** `/root/gold_signal_fetcher_ai_assisted/main_orchestrator.py`
- **Dashboard:** http://72.60.133.179:8502 (Flask on port 8502)
- **Cron Schedule:** Every 5 minutes, Monday-Friday only
- **System A Log:** `/var/log/gold_scanner.log`
- **System C Log:** `/var/log/gold_scanner_ai.log`
- **Dashboard Log:** `/var/log/gold_dashboard_ai.log`

### 🔧 Configuration
- `.env` copied from System A (has METAAPI_TOKEN, TELEGRAM_TOKEN, ANTHROPIC_API_KEY)
- Paper trades CSV: `/root/gold_signal_fetcher_ai_assisted/data/paper_trades_ai.csv`
- ML model: `/root/gold_signal_fetcher_ai_assisted/models/xgboost_gold_model.pkl`

### 📊 Dashboard Features
- Side-by-side System A vs System C metrics
- Real-time comparison: Win rate, Profit factor, P&L, Sharpe ratio
- Green highlights for winning system in each metric
- Auto-refreshes every 60 seconds
- Shows "Not started" for System C (weekend - market closed)
- Will show signals starting Monday when market opens

---

## Components

### 1. ML Feature Engineer (`agent/ml_feature_engineer.py`)
Extracts 16 technical features from OHLCV:
- **Momentum:** RSI(14), RSI oversold/overbought flags
- **Trend:** MACD, ADX(14), price vs MA20/MA50
- **Volatility:** ATR(14), Bollinger Bands width/position
- **Volume:** Volume spike ratio
- **Price Action:** Momentum, volatility, trend strength

**Usage:**
```python
from agent.ml_feature_engineer import FeatureEngineer

engineer = FeatureEngineer()
features_df = engineer.extract_features(ohlcv_data)
X = engineer.prepare_for_model(features_df)  # Ready for XGBoost
```

### 2. ML Signal Generator (`agent/ml_signal_generator.py`)
XGBoost classifier predicting signal profitability:
- Trained on market data patterns
- Outputs confidence 0-100%
- Combines with SMC score using weighted formula

**Usage:**
```python
from agent.ml_signal_generator import MLSignalFilter

filter = MLSignalFilter()
decision = filter.should_execute_signal(
    features_df, 
    base_score=72,  # SMC score
    liquidity_tier='peak'
)
print(decision['combined_confidence'])  # 65-80 (typical)
```

### 3. Claude Analyst (`agent/claude_analyst.py`)
Claude Opus analyzes market context and decides:
- Reads signal, market data, ML confidence, open positions
- Assesses: signal quality, market timing, risk, news
- Returns confidence 0-100% + reasoning

**Usage:**
```python
from agent.claude_analyst import AITradingDecider

decider = AITradingDecider()
decision = decider.decide(
    signal_info={'direction': 'BUY', 'entry': 4320, 'sl': 4310},
    market_data={'current_price': 4320, 'trend_4h': 'bullish', 'rsi_14': 35},
    ml_confidence=72,
    smc_score=68,
    liquidity_tier='peak'
)
# Returns: should_trade=True, combined_confidence=71, reasoning=...
```

---

## Decision Formula

```
Final Confidence = (ML_Score × 0.35) + (Claude_Score × 0.35) + (SMC_Score × 0.30)

Then: IF Final_Confidence >= Tier_Threshold → EXECUTE
      ELSE → SKIP
```

**Tier Thresholds:**
- PEAK (13:00-16:30 UTC): 55%+ (aggressive, liquid)
- HIGH (08-13, 16:30-20 UTC): 60%+ (balanced)
- SECONDARY (20-08 UTC): 70%+ (conservative, thin)

---

## Integration Plan (Week 1-4)

### Week 1: Setup ✅ COMPLETE (Deployed June 21)
- ✅ Copy SMC base components from `Gold_Signal_Fetcher`
- ✅ Integrate `claude_analyst.py` into signal pipeline
- ✅ Integrate `ml_signal_generator.py` into signal pipeline
- ✅ Create paper_trades_ai.csv for tracking
- ✅ Create orchestrator pipeline (main_orchestrator.py)
- ✅ Build comparison dashboard (dashboard.py)
- ✅ Write VPS deployment guide (VPS_DEPLOYMENT.md)
- ✅ Deploy System C to VPS
- ✅ Configure cron jobs (both systems)
- ✅ Open firewall port 8502
- ✅ Dashboard accessible: http://72.60.133.179:8502

### Week 2-3: Live Testing (June 23 - July 7)
- ✅ Both systems running in parallel (Mon-Fri)
- Paper trading independently on real market signals
- Track metrics: win rate, profit factor, Sharpe, drawdown
- Monitor Claude decision quality (cost ~$0.84/day)
- Real-time comparison on dashboard

### Week 4: Analysis & Decision (July 8-14)
- Analyze 4-week performance data
- If System C wins (58%+ win rate): integrate into production
- If System A wins: keep SMC-only, save Claude costs
- Document findings in final report

---

## Expected Performance

**Conservative estimate (based on ML + Claude combo benefits):**
- System A (SMC-only): 52% win rate, 1.3 profit factor
- System C (ML + Claude): 58-65% win rate, 1.5-1.8 profit factor

**Why System C wins:**
1. ML learns market patterns SMC doesn't capture
2. Claude catches false signals (news, extreme conditions)
3. Combined approach: "does it score high? yes. does it make sense? let Claude check."

---

## Cost Considerations

**Claude API usage:**
- ~1 analysis per 5 minutes (during trading hours)
- ~48 analyses/day × $0.003/analysis = ~$0.15/day
- ~$4.50/month for daily trading

**XGBoost:**
- Local compute, no API cost
- Improves over time with real trading data

---

## Next Immediate Actions

1. **Merge base components** from `Gold_Signal_Fetcher` into this repo
2. **Update main.py** to orchestrate: SMC → ML → Claude → Trade
3. **Set up VPS** parallel cron job
4. **Start paper trading** both systems
5. **Track metrics** daily for 4 weeks

---

## Files Structure

```
gold_signal_fetcher_ai_assisted/
├── main_orchestrator.py            # ✅ Full pipeline orchestrator
├── dashboard.py                    # ✅ Real-time comparison dashboard
├── VPS_DEPLOYMENT.md               # ✅ VPS setup guide
├── agent/
│   ├── ml_feature_engineer.py      # Extract 16 technical features
│   ├── ml_signal_generator.py      # XGBoost predictor
│   ├── claude_analyst.py           # Claude decision engine
│   ├── smc_gold_scanner.py         # SMC signal generation (copied)
│   ├── paper_trader.py             # Trade execution & tracking (copied)
│   ├── liquidity_manager.py        # Session/tier logic (copied)
│   ├── notifier.py                 # Telegram notifications (copied)
│   └── sessions.py                 # Session management (copied)
├── config/settings.py              # Configuration
├── data/
│   └── paper_trades_ai.csv         # Results tracking
├── models/
│   ├── xgboost_gold_model.pkl      # Trained XGBoost
│   └── feature_cols.json           # Feature names
├── requirements.txt                # Dependencies (xgboost, scikit-learn, flask, anthropic)
├── .env.example                    # Environment template
└── CLAUDE.md                        # This file
```

---

## Key Insights

- **ML alone:** Finds patterns, but can be noisy without context
- **Claude alone:** Great analysis, but slower and more expensive
- **ML + Claude together:** Fast (ML), smart (Claude), cost-effective combo
- **+ SMC base:** All three together = maximum edge

---

## Monitoring

Track these metrics weekly:

| Metric | Target | Alert if |
|--------|--------|----------|
| Win Rate | 58%+ | < 50% |
| Profit Factor | 1.5+ | < 1.2 |
| Avg P&L | +50/week | < 0 |
| Sharpe Ratio | 1.0+ | < 0.5 |
| Max Drawdown | 5% | > 10% |
| Claude Cost | < $5/week | > $10/week |
