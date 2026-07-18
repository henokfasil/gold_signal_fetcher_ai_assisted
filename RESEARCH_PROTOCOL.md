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

## Current model decision

The calibrated purged walk-forward XGBoost v3 result is `REJECT_MODEL`.
No model artifact may be created or deployed from it. Hyperparameter search on
the same years is prohibited until the event lifecycle, dependence weighting
and directional research questions above are implemented.
