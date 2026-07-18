# Gold Signal Fetcher — Unified AI-Assisted Research System

Last reviewed: 2026-07-19

## Claude restart handoff

A copy-ready session prompt is available in
[`CLAUDE_RESTART_PROMPT.md`](CLAUDE_RESTART_PROMPT.md).

Read this file completely, then read `RESEARCH_PROTOCOL.md`, before changing
strategy logic, labels, thresholds, features or deployment state. This handoff
is model-agnostic; do not assume a model name or capability that is not present
in the active Anthropic API configuration.

Current research state at handoff:

- Raw account-free Dukascopy XAUUSD bid/ask history contains 154,709 15-minute
  bars from 2020-01-01 through 2026-07-17. It is local research data and is not
  committed to Git.
- Canonical candidate dataset is
  `data/research/xauusd_smc_candidates_v3.csv`: 40,792 candidates, 40,623
  bid/ask-labelled outcomes, 168 ambiguous outcomes and one unmatured outcome.
  Dataset SHA-256 is
  `8d0444dd86d10bb87f6532711b310c06753892afdb34bbe4a81600d0b045a77e`.
- The purged/calibrated walk-forward result is `REJECT_MODEL`: overall ROC-AUC
  0.490 and Brier score worse than its prevalence baseline. No model artifact
  was created or deployed. Never rename this result as validated ML.
- Like-for-like prevalence, direction-only, SMC-score logistic, all-feature
  logistic and XGBoost baselines all have dependence-aware AUC intervals that
  include chance and selected-return intervals that include zero. This
  localizes the failure to the tested information/target rather than showing
  that a more fashionable model class will fix it.
- The lifecycle portfolio diagnostic opens 2,695 positions from 40,792 raw
  candidates after cooldown/risk gates. It returns -0.41%, profit factor 0.999
  and maximum drawdown 34.55%. BUY contributes +$1,396.99; SELL contributes
  -$1,437.82. This is a rejected development result, not an edge.
- Overlap-aware evidence reduces the 11,843 eligible labels to Kish effective
  sample size about 5,478 (summed uniqueness about 2,898). BUY-only returns
  +22.53% developmentally, but its weekly-bootstrap 95% interval includes a
  large loss (-28.09% to +80.77%) and drawdown is 25.25%. SELL-only returns
  -14.72%. Liquidity sweep is only a forward hypothesis; it is not validated.
- Runtime paper controls now use a four-hour same-direction/nearby-entry
  cooldown and account-level realized-USD daily/weekly loss caps.
- Historical 2020-2026 results have influenced research decisions and can
  never again be called an untouched final test.
- The TradingView MCP five-timeframe snapshot was invalid: all five requested
  frames contained the same 15-minute payload. Runtime now rejects it instead
  of silently analysing false higher-timeframe data.
- Runtime paper research uses account-free Dukascopy public XAUUSD bid/ask
  candles. A full five-timeframe snapshot takes about 3.3 seconds locally,
  retains exactly 200 complete candles per frame and validates source identity,
  cadence, ordering, OHLC, bid/ask spreads, uniqueness and open-market bar lag.
- Forward pilot collection covers both directions. ML remains required for
  approval and unavailable, so no candidate can become an approved paper
  signal merely because Claude likes it.
- Prospective experiment `forward-pilot-20260719-v2` is frozen in
  `config/research_variants.json` (SHA-256
  `8e7e6155b89fb893cc1b12218229a8f1e5f0f5ce87f682465278642f2bd75a83`). It
  compares the unchanged BUY/SELL baseline with a BUY + point-in-time 1H
  liquidity-sweep shadow variant. It has a single 26-week cutoff at
  2027-01-16 22:35:57 UTC, no interim performance evaluation and no
  confirmatory edge claim. Assignments cannot approve a paper trade, send
  Telegram or select/train a model.

Resume in this order:

1. Verify `git status`, run the verification commands below and confirm the
   canonical VPS revision/services without touching secrets or historical data.
2. Monitor snapshot cadence, latest-complete-bar lag and append-only pilot
   assignments/outcomes; operational monitoring must not reveal interim
   profitability.
3. Build the separately versioned point-in-time `gold_context` source contract
   and multi-horizon/utility targets. Do not modify the frozen pilot.
4. Run new feature/target experiments through identical simple baselines,
   chronological folds, purge, calibration and dependence-aware uncertainty.
5. Add causal regime/session diagnostics only inside chronological training
   folds. Register every proposed filter before examining its next-fold result.
6. Freeze a revision only if the underlying non-ML baseline and any ML filter
   pass development gates. Final evidence must come from future forward paper
   observations with no mid-test changes.

Prohibited shortcuts: random train/test splits, synthetic training fallbacks,
midpoint-only execution labels when bid/ask exists, counting overlapping rows
as independent trials, combining BUY and SELL performance to hide a weak side,
optimizing on 2020-2026 then calling it out of sample, deploying a failed model,
or enabling broker execution.

## Status

This repository is a **paper-trading research system**, not a live execution
system and not evidence of a profitable strategy. `PAPER_TRADING=true` is a
mandatory runtime invariant. The system records SMC candidates and requires
validated ML plus an available Claude review before it can mark a candidate as
an approved paper trade.

The previous documentation called the system “production ready.” That claim
was removed after a code audit found disconnected and placeholder components.

Canonical VPS facts as of 2026-07-19:

- Canonical host: `187.55.229.4` (`srv1831821`).
- Dashboard: `http://187.55.229.4:8502/` via
  `gold-signal-fetcher.service`.
- Repository: `/root/gold_signal_fetcher_ai_assisted`.
- The paper scanner is designed to run every 15 minutes through the canonical
  wrapper. Dukascopy collection failure or any source/cadence/quote/freshness
  violation aborts that scan before candidate analysis.
- The former host `72.60.133.179` is not the canonical deployment and must
  remain inactive for System C.
- TradingView Desktop and `tradingview-mcp` remain installed for optional
  interactive research, but their display/session units are disabled and
  stopped to save CPU/RAM. They are not the automated paper data source.
- Before this revision, the migrated VPS had local changes using Yahoo Finance
  `GC=F`. That is a gold-futures proxy rather than broker XAUUSD, and its 4H and
  15M interval adaptation was incomplete. The selected live paper-research
  source is now Dukascopy public `XAUUSD`; MetaApi is an optional legacy
  provider only.

## What “edge” means

An edge is a repeatable positive expected value after spreads, slippage and
losses, demonstrated on data that was not used to select the strategy. Signal
count, training accuracy and an attractive in-sample dashboard are not proof of
an edge.

## Runtime pipeline

```text
Atomic Dukascopy XAUUSD bid/ask snapshot (W/D/4H/1H/15M)
              ↓
Directional BUY/SELL SMC candidate generator
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

## Professional ML research roadmap — 2026-07-19 decision

### Interpretation of the rejected model

Do not interpret `REJECT_MODEL` as proof that machine learning cannot assist a
gold strategy. It rejects one specific experiment: a fixed XGBoost classifier
trained primarily on 33 correlated SMC, OHLC, indicator and calendar features
to predict the existing bid/ask execution-aware barrier label.

The completed like-for-like benchmark in
`data/research/candidate_model_benchmarks_v1.json` localizes the failure:

- all-feature XGBoost: overall ROC-AUC 0.4899, Brier 0.1971 and selected mean
  after-cost return -0.0093%;
- all-feature logistic regression: overall ROC-AUC 0.5093, Brier 0.1970 and
  selected mean after-cost return +0.0023%;
- direction-only logistic regression: overall ROC-AUC 0.5109 and selected mean
  after-cost return -0.0048%;
- XGBoost weekly-block-bootstrap 95% intervals include both chance for ROC-AUC
  (0.4541 to 0.5269) and zero for selected return (-0.0602% to +0.0480%).

Therefore a model-class substitution alone is not the next experiment. XGBoost
is a legitimate professional baseline for a medium-sized tabular dataset.
Replacing it with an LSTM, Transformer or larger tree ensemble while preserving
the same features, labels and evaluation period is low-information model
shopping and risks backtest overfitting. The next program must seek new,
point-in-time information and test alternative economic targets.

### Research hypotheses and required information

The current features are mostly different transformations of the same gold
OHLC path. A larger column count does not create independent information. Build
a versioned, synchronized `gold_context` dataset whose rows contain only values
available at the candidate timestamp and whose source, symbol, timestamp
semantics, publication lag and missing-data policy are recorded.

Prioritize these feature families:

1. Gold state: multi-horizon returns, realized volatility, range, spread,
   trend strength, gap, session range and normalized distance to recent levels.
2. Dollar/rates: point-in-time dollar-index or liquid USD proxy returns,
   Treasury yield changes and real-yield proxies. Never forward-fill a release
   through a period when it was not yet observable.
3. Related markets: silver, gold/silver ratio, broad risk proxies and other
   instruments included under a pre-registered economic hypothesis. Timestamp
   and holiday alignment are mandatory.
4. Futures context when legally and reliably available: GC volume, open
   interest, curve/basis and roll state. Do not mix futures and spot levels as
   if they were the same executable instrument.
5. Event clock: distance to CPI, NFP, FOMC and other registered releases;
   actual-minus-consensus surprise only when consensus and release timestamps
   are archived point in time.
6. Execution state: empirical bid/ask spread, session liquidity, expected
   slippage and cost stress. Tick volume remains feed-specific and must pass
   cross-feed stability checks before promotion.

Free/account-free sources may be used for exploratory research when their
license and timestamp semantics permit it. They must not be described as
commercial-grade merely because they are convenient. Do not purchase data,
create paid accounts or silently substitute providers. Intraday order-book
research requires genuine trades/depth data; TradingView OHLC bars cannot be
treated as a limit order book.

### Pre-registered model ladder

Every model must run through the same chronological folds, purge, costs,
selection rule and uncertainty calculations. Evaluate in this order and stop
adding complexity when the new information does not beat the simpler model:

1. constant prevalence, trade-all, direction-only and frozen SMC/rule ranking;
2. regularized logistic regression and elastic-net return regression;
3. shallow XGBoost, LightGBM and CatBoost with comparable complexity budgets;
4. expected-return or learning-to-rank models that select only the highest
   ranked candidates and explicitly abstain from the rest;
5. a simple regime descriptor, such as a pre-registered volatility/trend state
   or HMM, used as a feature or routing gate—not advertised as alpha itself;
6. diverse, calibrated ensembles only if each component adds incremental
   fold-level evidence;
7. TCN/LSTM/TFT sequence experiments only after the synchronized sequence
   dataset and effective sample size justify them;
8. DeepLOB-style CNN/recurrent research only if genuine GC order-book and trade
   events become available with an execution simulator.

Hyperparameters must be selected inside training data using nested
chronological validation or frozen before the next fold. Record every attempted
feature set, target, model and threshold in an experiment registry. Never
report only the winning run.

### Target redesign

Retain the existing execution-aware TP-before-SL barrier target as a legacy
benchmark, but do not assume it is the only learnable or economically useful
target. Construct point-in-time targets from the same bid/ask replay for:

- after-cost return at fixed 1h, 4h, 12h and 48h horizons;
- maximum favourable excursion and maximum adverse excursion;
- barrier outcome together with time to TP, SL or expiry;
- direction-specific expected utility under the frozen paper position-sizing
  rule; and
- candidate ranking by realized after-cost utility.

Target construction must resolve or explicitly exclude ambiguous same-bar
touches, preserve the label interval for purge/uniqueness calculations and use
the executable side of the market. Optimize no target on the final untouched
period. Multi-horizon targets are separate research questions, not permission
to choose the best-looking horizon afterward.

### Promotion gates

Do not weaken a gate to force an AI component into the product. Before a model
can approve even a paper signal, it must demonstrate all of the following on
the registered evaluation:

- data-integrity, feature-availability and cadence checks pass;
- discrimination or ranking lift beats the registered simple baseline;
- calibrated classifiers beat chronological prevalence on Brier score;
- selected after-cost expectancy is positive and its dependence-aware
  block-bootstrap lower confidence bound is above zero;
- sufficient raw and effective observations exist for the selected subset;
- results are not concentrated in one accidental fold, session or volatility
  regime;
- realistic spread/slippage stress does not erase the result; and
- dataset, feature schema, code revision, parameters and calibration artifact
  are hash-locked before forward use.

BUY and SELL are separate promotable strategies. A validated BUY component may
remain enabled while SELL stays rejected; combining them must never hide a
weak side. The current BUY result does not qualify: its XGBoost AUC is below
chance and its return uncertainty spans loss. Passing development gates still
means `research candidate`, not `proven edge`, until a frozen forward paper
test confirms it.

### Correct role of Claude/LLMs

Claude is an assistant and structured decision layer, not a source of assumed
alpha. Do not give an LLM an arbitrary percentage vote and call the composite
statistically validated. Its defensible research roles are:

- transform timestamped macro/news inputs into a fixed structured schema;
- identify stale, missing or internally conflicting evidence;
- apply explicit, pre-registered exceptional-risk vetoes;
- explain deterministic/ML decisions for the dashboard and Telegram; and
- help generate research code, tests, documentation and skeptical reviews.

Any directional Claude score is a candidate feature. Archive the exact prompt,
model identifier, supplied facts, response and timestamps, then evaluate it
chronologically against a no-LLM baseline. API unavailability must fail closed
and must not be filled with a neutral invented score.

### Immediate autonomous work; do not wait six months to research

The frozen forward pilot runs unchanged in parallel, but it does not prohibit
development on a separately named experiment family. Resume the following work
immediately on local capacity:

1. verify all price/timeframe/feed invariants and stop on any fabricated,
   duplicated or wrong-cadence series;
2. create the `gold_context` source contract and availability matrix before
   downloading or joining new variables;
3. implement synchronized point-in-time joins and missingness diagnostics;
4. generate the registered multi-horizon/utility targets from bid/ask data;
5. run the complete simple-baseline and tree-model ladder with identical folds;
6. report fold metrics, dependence-aware intervals, regime attribution,
   calibration and cost sensitivity—not just one aggregate return;
7. freeze only a variant that passes every applicable development gate; and
8. shadow that variant prospectively without changing the existing frozen
   experiment or enabling broker execution.

Claude/Codex may autonomously perform reversible local research, implement
tests and documentation, run leakage-safe experiments, and reject failed
variants without waiting for confirmation. It must stop for paid data or new
account creation, secrets/credentials, destructive operations, changes to a
frozen experiment, external publication, live-capital execution, or any action
that expands financial risk. VPS deployment is an engineering decision made
only after local verification; it never changes a research result from failed
to validated.

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

## Price snapshot contract

The active collector is `ops/collect_dukascopy_snapshot.py`. It obtains
independent public Dukascopy bid and ask candles for exact XAUUSD at 1W, 1D,
4H, 1H and 15M, derives midpoint OHLC for SMC analysis, excludes forming bars
and atomically replaces `/tmp/dukascopy_snapshot.json`. Every frame must contain
200 ordered, unique, valid candles at the expected cadence. Bid/ask OHLC,
non-negative spread, exact provider/symbol, snapshot age, cross-timeframe
distinctness and open-market latest-bar lag also fail closed.

Forward barrier labels use the direction-correct executable side: BUY enters
at ask and exits/tests barriers on bid; SELL enters at bid and exits/tests on
ask. Two-sided slippage remains explicit. The fixed-spread midpoint fallback is
prohibited for the frozen Dukascopy pilot.

TradingView MCP is not an automated price dependency. A direct VPS audit found
that its W, D, 4H, 1H and 15M requests all returned the same 15-minute bars even
while the UI resolution changed. The legacy collector now exposes that failure
through cadence/duplicate checks and aborts. TradingView Desktop may be used
interactively, but Premium login does not repair or validate this MCP behavior.

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

Frozen shadow outcomes use direction-correct Dukascopy 15-minute bid/ask
barriers and mark same-bar TP+SL as ambiguous. They still lack tick ordering
inside a candle. Separately, any approved paper-ledger exit is labelled
`*_OBSERVED_AT_SCAN`; it is not tick-accurate and may miss an intraperiod touch.
Do not mix these two evidence qualities in performance claims.

## Risk controls

The orchestrator enforces maximum open trades, minimum R:R, daily loss cap and
weekly loss cap. Configuration lives in `config/gold_strategy_params.json` and
environment overrides live in `.env`. Position sizing is paper notional only;
no broker order method is present.

Duplicate setup suppression uses a four-hour same-direction/nearby-entry
cooldown. Daily and weekly caps are calculated from realized paper USD P&L as a
percentage of the paper account—not by incorrectly summing instrument returns.
The historical portfolio simulator in `research/simulate_portfolio.py` applies
the same lifecycle, capacity and loss-cap ordering.

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

The binding methodology and hypothesis registry is
[`RESEARCH_PROTOCOL.md`](RESEARCH_PROTOCOL.md). Changes to candidate lifecycle,
directional logic, SMC components, regime filters or final acceptance must be
registered there before evaluation.

## Next research milestones

1. Collect `forward-pilot-20260719-v2` unchanged until its fixed
   2027-01-16 22:35:57 UTC cutoff; monitor only operational integrity and counts.
2. Do not inspect interim pilot performance and do not stop at a convenient
   candidate count. Allow the final assigned candidates 48 hours to mature.
3. Treat the pilot as feed/plumbing/event-rate/variance evidence. Its estimated
   power for the historical +0.08% per-candidate effect is only about 14%; it
   cannot by itself confirm profitability.
4. Continue independent research now: construct new point-in-time context
   features and economic targets under separately named protocols.
5. Build the DXY/real-yield/VIX snapshot producer with timestamp and source
   provenance.
6. Add model/prompt/dataset lineage, drift and calibration monitoring.
7. Do not design live-capital execution unless a later frozen forward test
   passes the registered gates; this experiment remains paper-only.

### Validation decision rule

`research/validate_walk_forward.py` performs expanding-year walk-forward
evaluation with a 48-hour purge around train/calibration/test boundaries and a
separate chronological probability-calibration slice. Development gates require
overall ROC-AUC >= 0.55, Brier score better than the prevalence baseline, no
year-fold ROC-AUC below 0.45, and positive selected expectancy for BUY and SELL.
Failure means **no model artifact is created or deployed**. Passing these gates
would still not prove an edge because 2020-2026 influenced development; only a
frozen future paper test can provide final confirmation.

Gate provenance is not a pristine pre-registration: the gate code predates the
v3 result but the local v2 artifact appears earlier than the gate commit. Treat
the original thresholds as development gates. Future promotion additionally
requires a dependence-aware lower confidence bound above zero and superiority
to a registered simple baseline. The XGBoost selected-subset mean probability
was 26.36% versus a 22.30% win rate, a 4.06 percentage-point calibration gap;
do not repeat the external review's approximate 14-point claim.

## Dataset and forward evidence workflow

Historical source files must be exact XAUUSD OHLCV with UTC timestamps and
documented candle-open/close semantics. Never mix spot, CFD and futures symbols
silently. The default account-free historical and forward paper-research source
is Dukascopy XAUUSD; collection-path stability and future regime drift still
require monitoring. Download resumably (bid, ask and midpoint) with:

```bash
python -m research.download_dukascopy_xauusd \
  data/raw/dukascopy_xauusd_15m_2020_2026.csv \
  --start 2020-01-01 --end 2026-07-18
```

Then build candidates from its midpoint OHLC while retaining bid/ask columns
for later execution-cost research:

```bash
python -m research.build_historical_dataset \
  data/raw/dukascopy_xauusd_15m_2020_2026.csv \
  data/research/xauusd_smc_candidates_v3.csv \
  --timestamp-is open --scan-minutes 15 --expiry-hours 48 \
  --spread-points 0.83 --slippage-points 0.10
```

Costs above are explicit research assumptions, not universal broker facts, and
must be replaced with empirical bid/ask distributions. Do not train until the
candidate dataset has at least 500 matured, unambiguous observations and both
labels in chronological train/test partitions.

Forward collection writes exact candidate-time features to
`data/forward_candidate_features_v2.csv` and outcomes to
`data/forward_candidate_outcomes.csv`. Frozen membership is written separately
to `data/forward_variant_assignments.csv` under the hash-locked contract in
`config/research_variants.json`. This shadow ledger follows every unique SMC
candidate—including candidates rejected by unavailable ML or Claude—without
approving a paper trade or sending Telegram. Assignment records distinguish
raw membership from minimum-R/R eligibility. Export matured, assigned joins
with:

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
