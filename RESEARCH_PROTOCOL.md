# Gold Signal Research Protocol

Status: development research; no validated edge and no live execution.

## Evidence boundaries

- Dukascopy 2020-2026 has been inspected and influenced development. It is a
  development set, never an untouched final test.
- A rule change must be registered here with its rationale before another
  evaluation. Historical improvements are hypothesis evidence only.
- Final confirmation requires a frozen revision and future executable-side
  paper observations that were unavailable when the revision was selected.
- BUY and SELL are separate research tracks. Passing one side never validates
  the other.

## Six workstreams

### 1. Candidate lifecycle and rate

Observed v3 eligible rate is about 40.8/week versus the intended 8-15/week.
Repeated scans of the same setup must not be treated as new discoveries.

Planned operational hypothesis `H1` (not selected for profitability): one
candidate per direction/nearby-entry setup during a four-hour cooldown, unless
the prior setup resolves or a new 4H structure event is observed. Replay and
runtime deduplication must use the same rule.

### 2. Dependence and portfolio capacity

Median concurrent labelled outcomes are 4, 95th percentile 22 and maximum 49.
All statistical summaries must report event dependence. Model fitting will use
label-interval uniqueness weights. Economic simulation must enforce the same
maximum open positions, position sizing, loss caps and cooldown as runtime.
Weekly/block bootstrap intervals—not row-wise confidence intervals—will be used
for uncertainty.

### 3. Separate directional systems

- BUY: remains research-eligible; positive mean development expectancy is not
  final evidence.
- SELL: remains shadow-only because v3 expectancy and selected expectancy are
  negative. It must obtain its own feature/logic hypothesis and pass every gate
  separately before approval is possible.

The product may display and study both sides while only a validated side can
ever pass the ML approval gate.

### 4. SMC ablation and falsification

Full-period diagnostics suggest liquidity sweep is useful for BUY, while FVG,
CHoCH and price-at-order-block are not consistently additive. These are
hypotheses, not accepted filters. Ablations must use expanding walk-forward
folds and compare against simple baselines. A component is retained as
predictive evidence only if its benefit is stable across multiple folds and
survives costs and block-bootstrap uncertainty.

### 5. Causal regimes and sessions

No filter may use future-known calendar performance. Candidate-time regimes may
use only rolling values such as ATR percentile, trend strength, spread,
session/hour and higher-timeframe alignment. Cutoffs are selected inside each
training fold, calibrated on its later calibration slice, and applied unchanged
to the following test fold.

### 6. Frozen forward paper pilot and later confirmation

Forward candidate features and shadow outcomes remain append-only and separate
from historical data. Each record needs strategy, feature-schema, dataset/model
and prompt versions. The current 26-week experiment is explicitly a pilot. A
later confirmatory experiment must be powered from pilot variance and frozen
under its own version before it begins. Candidate count is not an optional
stopping rule.

#### Frozen prospective pilot: `forward-pilot-20260719-v2`

Frozen at 2026-07-18 22:35:57 UTC and evaluated once after the fixed cutoff at
2027-01-16 22:35:57 UTC, allowing the final assignments 48 hours to mature. The
binding machine-readable contract is `config/research_variants.json`, SHA-256
`8e7e6155b89fb893cc1b12218229a8f1e5f0f5ce87f682465278642f2bd75a83`.
Runtime verifies this hash before collection and refuses a changed contract.

- Candidate universe: unique SMC candidates recorded after the existing
  four-hour same-direction/nearby-entry cooldown.
- `baseline_v1`: every BUY and SELL member of that candidate universe.
- `buy_liquidity_v1`: BUY members for which the 1H downside liquidity-sweep
  object existed using only candidate-time data.
- Common eligibility: R/R >= 2.0. Membership and eligibility are stored
  separately so exclusions remain auditable.
- Source: Dukascopy public XAUUSD with independent 1W/1D/4H/1H/15M midpoint
  analysis bars and retained bid/ask execution fields. Forming candles are
  excluded.
- Common lifecycle: 48-hour barrier/expiry horizon, executable ask entry/bid
  barrier for BUY, executable bid entry/ask barrier for SELL, 0.10 slippage
  points per side and the same four-hour setup cooldown. Midpoint fixed-spread
  fallback is prohibited for this pilot.
- SELL remains in the baseline and outcome collection but cannot be relabelled
  into the BUY variant.
- Assignment has no effect on Claude/ML approval, the paper ledger status,
  Telegram or model training/selection.

Assignments are appended once to `data/forward_variant_assignments.csv` and
joined to immutable features/outcomes by `candidate_id`. Operational health and
counts may be monitored. Directional performance, expectancy, PF, win rate and
variant comparisons must not be inspected before the fixed evaluation. The
pilot's estimated power for the historically observed approximately +0.08%
mean return per candidate is only 14.4%, so neither a null nor a positive point
estimate is confirmatory. Its purpose is plumbing, feed stability, event-rate,
falsification and forward variance estimation.

## Current model decision

The calibrated purged walk-forward XGBoost v3 result is `REJECT_MODEL`.
No model artifact may be created or deployed from it. Hyperparameter search on
the same years is prohibited until the event lifecycle, dependence weighting
and directional research questions above are implemented.

`research/benchmark_candidate_models.py` runs prevalence, direction-only,
SMC-score-only logistic, all-feature logistic and XGBoost through the same
folds, purge, calibration and selection rule. No model has an AUC interval
excluding chance or a selected-return interval excluding zero. All-feature
logistic reaches AUC 0.5093 and +0.0023% selected mean; XGBoost reaches AUC
0.4899 and -0.0093%. This favors a feature/target research problem over model
shopping. The original gates are development thresholds, not a pristine
pre-registration: their code predates v3 but the local v2 artifact predates the
gate commit.

## Runtime source validity

The TradingView MCP runtime attempt is rejected. All requested W/D/4H/1H/15M
payloads were byte-identical 15-minute candles despite UI timeframe changes.
The scanner and dashboard now fail closed on wrong cadence or duplicate frames.

The frozen pilot uses the account-free Dukascopy public feed instead. Each scan
collects exactly 200 complete bid/ask candles independently for all five
timeframes and derives midpoint analysis candles. Exact source identity,
cadence, ordering, uniqueness, OHLC, spread and open-market latest-bar lag are
validated before SMC analysis. A local full bid+ask collection completed in
about 3.3 seconds; this is engineering evidence only, not alpha.

## Lifecycle portfolio diagnostic v4

The pre-registered four-hour nearby-entry cooldown and runtime-aligned gates
reduced 40,792 raw candidates to 2,695 opened development positions. With
$10,000 starting paper capital and $5,000 fixed notional per position:

- ending return: -0.41%;
- profit factor: 0.999;
- maximum drawdown: 34.55%;
- maximum concurrent positions: 12;
- BUY P&L: +$1,396.99;
- SELL P&L: -$1,437.82.

This is a rejection, not an edge. The near-flat ending return does not excuse
the unacceptable path drawdown, and SELL offsets BUY. Results remain
development-only because the period influenced the research design.

## Direction, dependence and ablation diagnostic

`research/analyze_research_evidence.py` reproduces direction-only portfolios,
label-interval uniqueness, deterministic weekly block bootstraps and fixed SMC
variant comparisons. Current development findings:

- 11,843 eligible labels have Kish effective sample size about 5,478, summed
  uniqueness about 2,898 and maximum label concurrency 50;
- BUY-only: +22.53%, PF 1.13, maximum drawdown 25.25%; weekly-bootstrap 95%
  return interval is -28.09% to +80.77%, so positive expectancy is not
  established;
- SELL-only: -14.72%, PF 0.90, maximum drawdown 38.28%; it remains shadow-only;
- BUY + liquidity sweep after lifecycle gates: +43.20%, PF 1.37 and 14.01%
  drawdown across 1,086 opened candidates, but its weekly-bootstrap 95% return
  interval is -5.76% to +101.28% and PF interval is 0.95 to 1.86;
- order-block, FVG and CHoCH filtered variants have negative total development
  returns.

Liquidity sweep is therefore a registered forward hypothesis, not an accepted
edge. The bootstrap lower bound is negative and no ablation result authorizes
ML training or approval.
