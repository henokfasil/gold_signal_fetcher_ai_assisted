# Gold Signal Research Protocol

Status: development research; no validated edge and no live execution.

## Evidence boundaries

- Dukascopy 2020-2026 has been inspected and influenced development. It is a
  development set, never an untouched final test.
- A rule change must be registered here with its rationale before another
  evaluation. Historical improvements are hypothesis evidence only.
- Final confirmation requires a frozen revision and future OANDA/TradingView
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

### 6. Frozen forward paper confirmation

Forward candidate features and shadow outcomes remain append-only and separate
from historical data. Each record needs strategy, feature-schema, dataset/model
and prompt versions. Before any final claim:

- minimum 3-6 calendar months;
- minimum 200 matured candidates for the proposed side, with longer collection
  if dependence reduces effective sample size;
- bid/ask or conservative executable-cost treatment;
- stable feed/source monitoring and cross-feed comparison;
- no threshold or feature changes during the frozen evaluation;
- positive block-bootstrap lower confidence bound for after-cost expectancy,
  acceptable drawdown and no single regime dominating results.

Any change resets the forward evaluation clock for the changed revision.

#### Frozen prospective experiment: `forward-shadow-20260718-v1`

Frozen at 2026-07-18 21:18:05 UTC. The binding machine-readable contract is
`config/research_variants.json`, SHA-256
`f2a9e6dd7880b10195fc3f2e0367ed9561e5354fa96af25c732887805287fff0`.
Runtime verifies this hash before collection and refuses a changed contract.

- Candidate universe: unique SMC candidates recorded after the existing
  four-hour same-direction/nearby-entry cooldown.
- `baseline_v1`: every BUY and SELL member of that candidate universe.
- `buy_liquidity_v1`: BUY members for which the 1H downside liquidity-sweep
  object existed using only candidate-time data.
- Common eligibility: R/R >= 2.0. Membership and eligibility are stored
  separately so exclusions remain auditable.
- Common lifecycle: 48-hour barrier/expiry horizon, 0.35 spread points, 0.10
  slippage points per side and the same four-hour setup cooldown.
- SELL remains in the baseline and outcome collection but cannot be relabelled
  into the BUY variant.
- Assignment has no effect on Claude/ML approval, the paper ledger status,
  Telegram or model training/selection.

Assignments are appended once to `data/forward_variant_assignments.csv` and
joined to immutable features/outcomes by `candidate_id`. The calendar clock
starts at the first assignment after deployment—not at contract authoring—and
continues unchanged for at least 3–6 months. Formal review additionally waits
for at least 200 matured, R/R-eligible `buy_liquidity_v1` candidates and may
require longer when label overlap reduces effective sample size. Until then the
dashboard may show collection counts only, never an interim validation claim.

## Current model decision

The calibrated purged walk-forward XGBoost v3 result is `REJECT_MODEL`.
No model artifact may be created or deployed from it. Hyperparameter search on
the same years is prohibited until the event lifecycle, dependence weighting
and directional research questions above are implemented.

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
- structure + liquidity sweep: +34.40%, PF 1.15, drawdown 19.26%, but only 3/6
  positive years and selected from contaminated development history;
- order-block, FVG and CHoCH filtered variants have negative total development
  returns.

Liquidity sweep is therefore a registered forward hypothesis, not an accepted
edge. The bootstrap lower bound is negative, BUY drawdown remains excessive and
no ablation result authorizes ML training or approval.
