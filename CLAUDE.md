# Gold Signal Fetcher — AI-Assisted Research System (System C)

Last reviewed: 2026-07-18

## Status

This repository is a **paper-trading research system**, not a live execution
system and not evidence of a profitable strategy. `PAPER_TRADING=true` is a
mandatory runtime invariant. The system records SMC candidates and requires
validated ML plus an available Claude review before it can mark a candidate as
an approved paper trade.

The previous documentation called the system “production ready.” That claim
was removed after a code audit found disconnected and placeholder components.

Current VPS facts as of 2026-07-18:

- The previously documented `/root/gold_signal_fetcher_ai_assisted` directory
  was absent.
- System A and System C scanner cron entries had been deliberately paused on
  2026-07-10 for CPU reasons.
- The older System A dashboard remained active on port 8501.
- Deployment of this revision must remain stopped until local and VPS
  verification pass. Do not silently unpause an operator-paused cron entry.

## What “edge” means

An edge is a repeatable positive expected value after spreads, slippage and
losses, demonstrated on data that was not used to select the strategy. Signal
count, training accuracy and an attractive in-sample dashboard are not proof of
an edge.

## Runtime pipeline

```text
MetaApi point-in-time XAUUSD candles
              ↓
Bullish SMC candidate generator
              ↓
Signal geometry and research risk gates
              ↓
Validated historical-data ML inference (required)
              ↓
Fresh external macro snapshot (context/veto when available)
              ↓
Claude structured review using supplied facts only (required)
              ↓
OPEN or REJECTED paper-ledger record with provenance
              ↓
Observation-time TP/SL/expiry updates and explicit limitations
```

## Important strategy limitation

The current SMC scanner implements a **bullish candidate path**: bullish BOS,
CHoCH, liquidity sweep, stop below entry and target above entry. The
orchestrator therefore accepts only `BUY` geometry (`SL < entry < TP`). A
separate mirrored and tested bearish scanner must be built before System C can
issue SELL candidates. Never relabel a non-bullish result as SELL.

## ML policy

- Runtime model: `models/xgboost_gold_model_v2.pkl`
- Required metadata: `models/xgboost_gold_model_v2.metadata.json`
- Metadata must declare `training_data_kind=historical_point_in_time` and an
  exact feature-schema match.
- Missing or invalid models are unavailable and veto approval.
- There is no random or synthetic training fallback.
- `agent/train_gold_ml.py` requires a chronological historical dataset with at
  least 500 observations and reports holdout ROC-AUC, Brier score and log loss.
- Its simple 80/20 chronological holdout is only a first research gate; CPCV or
  purged walk-forward evaluation and a final untouched test set are still
  required before claiming an edge.

## Macro snapshot contract

`agent/gold_correlations.py` reads a fresh JSON snapshot from
`MACRO_SNAPSHOT_PATH` (default `/tmp/gold_macro_snapshot.json`):

```json
{
  "timestamp": "2026-07-18T12:00:00+00:00",
  "dxy_return_pct": -0.20,
  "real_yield_change_bps": -2.0,
  "vix_return_pct": 1.0
}
```

Missing, malformed or stale snapshots are reported as unavailable. The system
must never replace them with invented constants. Macro thresholds are research
hypotheses and must be estimated out of sample.

## Claude policy

Claude receives structured signal, technical, ML and macro data. It must use
only those supplied facts. API errors, missing credentials and invalid JSON
fail closed. Its explicit rejection is a veto, and confidence is never raised
to an artificial floor. LLM confidence is not assumed to be statistically
calibrated.

## Paper ledger

The canonical ledger is `data/paper_trades_ai.csv`. Every candidate has:

- immutable candidate ID and UTC timestamp;
- entry, SL, TP, direction and R:R;
- SMC/ML/Claude/macro availability and scores;
- decision, threshold and veto/rejection reason;
- explicit `REJECTED`, `OPEN`, `WIN`, `LOSS` or `EXPIRED` status;
- exit price/time/reason plus separate percentage and USD P&L;
- `paper_trading=true` provenance.

Current exits based on periodic price snapshots are labelled
`*_OBSERVED_AT_SCAN`; they are not tick-accurate and can miss an intraperiod
touch. An event-driven bid/ask replay is required for scientifically reliable
performance measurement.

## Risk controls

The orchestrator enforces maximum open trades, minimum R:R, daily loss cap and
weekly loss cap. Configuration lives in `config/gold_strategy_params.json` and
environment overrides live in `.env`. Position sizing is paper notional only;
no broker order method is present.

## Verification

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
python validate_code.py
```

Do not describe the system as profitable or production ready based on these
engineering tests. Research acceptance additionally requires point-in-time
datasets, leakage-safe backtesting, execution costs, out-of-sample calibration,
forward paper trading and stable performance across regimes.

## Next research milestones

1. Produce a versioned historical candidate dataset and triple-barrier/net-cost
   labels.
2. Add purging/embargo and combinatorial purged cross-validation.
3. Build tick or lower-timeframe bid/ask execution replay.
4. Add a separately tested bearish SMC candidate generator.
5. Build the DXY/real-yield/VIX snapshot producer with timestamp and source
   provenance.
6. Add model/prompt/dataset lineage, drift and calibration monitoring.
7. Freeze a research revision and forward paper trade it for 3–6 months before
   considering any live-capital design.

## Security and operations

- Never commit `.env`, API keys, Telegram tokens or account identifiers.
- Preserve the paper ledger before deployment or schema migration.
- Use a non-overlapping lock around scheduled runs.
- The canonical wrapper is `ops/run_gold_scanner_ai.sh`; it uses `flock`,
  forces `PAPER_TRADING=true`, and writes logs inside the project by default.
- Keep System C stopped after deployment if resource or integrity checks fail.
- Production deployment and strategy profitability are separate acceptance
  decisions.
