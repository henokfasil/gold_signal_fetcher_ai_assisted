# Gold Signal Fetcher — Unified AI-Assisted Research System

Last reviewed: 2026-07-18

## Status

This repository is a **paper-trading research system**, not a live execution
system and not evidence of a profitable strategy. `PAPER_TRADING=true` is a
mandatory runtime invariant. The system records SMC candidates and requires
validated ML plus an available Claude review before it can mark a candidate as
an approved paper trade.

The previous documentation called the system “production ready.” That claim
was removed after a code audit found disconnected and placeholder components.

Canonical VPS facts as of 2026-07-18:

- Canonical host: `187.55.229.4` (`srv1831821`).
- Dashboard: `http://187.55.229.4:8502/` via
  `gold-signal-fetcher.service`.
- Repository: `/root/gold_signal_fetcher_ai_assisted`.
- The paper scanner cron is paused until the TradingView session is signed in
  and the five-timeframe snapshot contract passes end-to-end verification.
- The former host `72.60.133.179` is not the canonical deployment and must
  remain inactive for System C.
- TradingView Desktop 3.3.0 and `tradingview-mcp` run on the canonical VPS under
  the unprivileged `tvfetcher` account. CDP is bound to `127.0.0.1:9222` only.
- Before this revision, the migrated VPS had local changes using Yahoo Finance
  `GC=F`. That is a gold-futures proxy rather than broker XAUUSD, and its 4H and
  15M interval adaptation was incomplete. The selected live research source is
  now TradingView `OANDA:XAUUSD`; MetaApi is an optional legacy provider only.

## What “edge” means

An edge is a repeatable positive expected value after spreads, slippage and
losses, demonstrated on data that was not used to select the strategy. Signal
count, training accuracy and an attractive in-sample dashboard are not proof of
an edge.

## Runtime pipeline

```text
Atomic TradingView OANDA:XAUUSD snapshot (W/D/4H/1H/15M)
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

## Directional strategy

The scanner implements separate mirrored mechanics for both directions. BUY
uses bullish BOS/CHoCH, downside liquidity sweeps, bullish order blocks/FVGs,
SL below entry and TP above. SELL uses bearish BOS/CHoCH, upside liquidity
sweeps, bearish order blocks/FVGs, SL above entry and TP below. The 4H
structure selects the side; ranging 4H structure fails closed. Never relabel a
candidate to manufacture the opposite direction.

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

## TradingView price snapshot contract

`ops/collect_tradingview_snapshot.py` uses the installed TradingView MCP CLI to
select the exact `OANDA:XAUUSD` symbol, collect 200 bars at W, D, 240, 60 and 15
minute resolutions, validate OHLC and strictly increasing timestamps, and then
atomically replace `/tmp/tradingview_snapshot.json`. The scanner rejects stale,
malformed, short, wrong-symbol or wrong-resolution snapshots. It never falls
back to Yahoo Finance or silently substitutes another timeframe.

TradingView Desktop runs on a private Xvfb display using
`ops/systemd/tradingview-display.service` and
`ops/systemd/tradingview-session.service`. The optional VNC unit binds to
localhost and must be accessed only through an SSH tunnel; it is not enabled at
boot and should be stopped after login/layout maintenance. TradingView login
state lives in `/home/tvfetcher`, outside the repository.

The scheduled live research collector does not require an authenticated
TradingView account: the MCP successfully provides the required 200 bars for
all five timeframes from the exact `OANDA:XAUUSD` chart in an anonymous
session. Premium authentication is therefore deferred to separate historical
research, where deeper history may matter; it is not a dependency of forward
paper trading. The MCP itself currently caps extraction at 500 bars.

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
python -m compileall -q agent config main.py main_orchestrator.py dashboard.py send_daily_metrics.py
python -m unittest discover -s tests -v
python validate_code.py
```

Do not describe the system as profitable or production ready based on these
engineering tests. Research acceptance additionally requires point-in-time
datasets, leakage-safe backtesting, execution costs, out-of-sample calibration,
forward paper trading and stable performance across regimes.

## Next research milestones

1. Obtain deep, exact-symbol 15-minute XAUUSD history and build a versioned
   candidate dataset with `research/build_historical_dataset.py`. The builder
   treats input timestamps as candle opens by default, exposes each bar only at
   close, replays the live SMC candidate generator, applies spread/slippage,
   excludes same-bar TP/SL ambiguity, and emits a SHA-256 manifest.
2. Add purging/embargo and combinatorial purged cross-validation.
3. Build tick or lower-timeframe bid/ask execution replay.
4. Validate BUY and SELL performance separately across market regimes.
5. Build the DXY/real-yield/VIX snapshot producer with timestamp and source
   provenance.
6. Add model/prompt/dataset lineage, drift and calibration monitoring.
7. Freeze a research revision and forward paper trade it for 3–6 months before
   considering any live-capital design.

## Dataset and forward evidence workflow

Historical source files must be exact XAUUSD OHLCV with UTC timestamps and
documented candle-open/close semantics. A TradingView Premium chart export is
acceptable for initial research if the export license permits this use and the
symbol/provider remain `OANDA:XAUUSD`; do not mix it silently with futures or
another broker feed. Example:

The default account-free research source is Dukascopy XAUUSD. It is explicitly
recorded as a different broker feed from runtime `OANDA:XAUUSD`; cross-feed
stability must be measured. Download resumably (bid, ask and midpoint) with:

```bash
python -m research.download_dukascopy_xauusd \
  data/raw/dukascopy_xauusd_15m_2020_2026.csv \
  --start 2020-01-01 --end 2026-07-18
```

Then build candidates from its midpoint OHLC while retaining bid/ask columns
for later execution-cost research:

```bash
python -m research.build_historical_dataset \
  data/raw/oanda_xauusd_15m.csv \
  data/research/xauusd_candidates_v1.csv \
  --timestamp-is open --scan-minutes 15 --expiry-hours 48 \
  --spread-points 0.35 --slippage-points 0.10
```

Costs above are explicit research assumptions, not universal broker facts, and
must be replaced with empirical bid/ask distributions. Do not train until the
candidate dataset has at least 500 matured, unambiguous observations and both
labels in chronological train/test partitions.

Forward collection writes exact candidate-time features to
`data/forward_candidate_features.csv` and outcomes to
`data/forward_candidate_outcomes.csv`. This shadow ledger follows every SMC
candidate—including candidates rejected by unavailable ML or Claude—without
approving a paper trade or sending Telegram. Export matured joins with:

```bash
python -m research.export_forward_dataset data/research/forward_matured.csv
```

Historical and forward observations must remain separate. Never use forward
results to repeatedly retune the frozen model being evaluated.

## Security and operations

- Never commit `.env`, API keys, Telegram tokens or account identifiers.
- Telegram sends only approved paper signals and unified paper metrics. It
  never places broker orders. Rejected candidates remain visible in the ledger
  and dashboard without creating notification spam.
- Preserve the paper ledger before deployment or schema migration.
- Use a non-overlapping lock around scheduled runs.
- Keep CDP (`9222`) and maintenance VNC (`5900`) bound to localhost only.
- The canonical wrapper is `ops/run_gold_scanner_ai.sh`; it uses `flock`,
  forces `PAPER_TRADING=true`, and writes logs inside the project by default.
- Keep System C stopped after deployment if resource or integrity checks fail.
- Production deployment and strategy profitability are separate acceptance
  decisions.
