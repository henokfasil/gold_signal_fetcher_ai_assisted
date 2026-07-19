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

Observed corrected-v4 eligible rate is about 40.8/week versus the intended
8-15/week.
Repeated scans of the same setup must not be treated as new discoveries.

Planned operational hypothesis `H1` (not selected for profitability): one
candidate per direction/nearby-entry setup during a four-hour cooldown, unless
the prior setup resolves or a new 4H structure event is observed. Replay and
runtime deduplication must use the same rule.

### 2. Dependence and portfolio capacity

Median concurrent labelled outcomes are 4, 95th percentile 22 and maximum 46.
All statistical summaries must report event dependence. Model fitting will use
label-interval uniqueness weights. Economic simulation must enforce the same
maximum open positions, position sizing, loss caps and cooldown as runtime.
Weekly/block bootstrap intervals—not row-wise confidence intervals—will be used
for uncertainty.

### 3. Separate directional systems

- BUY: remains research-eligible; positive mean development expectancy is not
  final evidence.
- SELL: remains shadow-only because corrected-v4 expectancy and selected
  expectancy are
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

#### Registered context experiment: `gold-context-20260719-v1`

The machine-readable pre-analysis contract is
`config/gold_context_v1.json`. It registers four account-free Dukascopy
cross-asset proxies before historical outcomes are joined: `DOLLAR.IDX/USD`,
`XAG/USD`, `VOL.IDX/USD` and `USTBOND.TR/USD`. These are respectively a
Dukascopy dollar-index CFD, silver, a volatility-index CFD and a Treasury-bond
total-return CFD. They must not be relabelled as official ICE DXY, official
CBOE VIX or real yields.

Only completed 1H bid/ask candles are permitted. Candle-open timestamps become
observable at open plus one hour; context is joined backward only when
`available_at <= candidate_time`. Nearest/future joins are forbidden. Values
older than 4,320 minutes remain missing, with explicit missingness and
staleness features. The fixed features are 1h/4h/24h returns, 24h realized
volatility and availability fields per instrument, plus 4h/24h gold-silver
ratio returns. Raw nonstationary proxy levels are not model inputs.

The primary target is the existing executable-side 4h after-cost return.
Context models must improve on their matching no-context model under a paired
weekly bootstrap in addition to the existing rank-IC, selected-return,
selected-excess and fold-stability gates. Results on 2020-2026 remain
development-contaminated even if every gate passes. Source-data commercial
rights have not been reviewed, so raw data may not be redistributed or sold.

Source preflight rejected v1 before any historical outcome join: Dukascopy
returned no ask candles for `VOL.IDX/USD`, so the v1 assumption that every
instrument supplied bid and ask was false. The active contract is therefore
`gold-context-20260719-v2` in `config/gold_context_v2.json`. It preserves every
feature, target and gate above while registering `VOL.IDX/USD` as a bid-only
context series. No synthetic ask or midpoint is permitted for that proxy.

Context v2 collection produced 35,297 dollar-index, 38,691 silver, 19,865
volatility-proxy and 38,585 Treasury-bond 1H observations. The volatility proxy
begins 2022-10-05, so its earlier values remain missing rather than backfilled.
The joined dataset preserved all 40,792 frozen candidates and the exact
registered 26-feature schema.

The pre-registered primary 4h result is `REJECT_CONTEXT_MODELS`. Context-only
Ridge achieved rank IC 0.036 and selected mean +0.0028%, but weekly-block 95%
intervals were -0.003 to 0.073 and -0.028% to +0.035%. It passed selected
excess, fold-count and paired-control gates, but failed rank-IC and absolute
selected-return uncertainty. BUY selected mean was +0.0226% with interval
-0.0132% to +0.0661%; SELL selected mean was negative. This is a possible
future BUY hypothesis, not a model authorization. No threshold, feature or
directional refit may be selected from these same outcomes under v2.

#### Frozen prospective context observation: `forward-context-buy-20260719-v1`

The machine-readable contract is
`config/forward_context_observation_v1.json`. It records the registered 26
context fields for every unique paper candidate and marks BUY candidates as a
weak, development-mined hypothesis. It creates no model score and has no
approval, Claude, Telegram, paper-ledger or broker effect. SELL is collected as
an observational baseline and is not relabelled as a passing hypothesis.

Assignments stop at 2027-01-17 12:49:25 UTC and evaluation occurs once after
the fixed maturity buffer at 2027-01-24 12:49:25 UTC. Interim performance is
forbidden; only source health, staleness, missingness and counts may be
monitored. The historical BUY effect is too uncertain for this pilot to claim
confirmation, so its purpose is prospective availability, stability and
variance evidence.

Runtime collection writes the atomic raw snapshot to
`/tmp/gold_context_snapshot.json` and one append-only candidate row to
`data/forward_candidate_context_v1.csv`. A validated capture contains the exact
contract and snapshot hashes, 26 registered backward-as-of fields, explicit
per-instrument missingness/staleness, and raw point-in-time levels for audit.
Collection or validation failure must create a missing observation and must
not veto or approve the underlying paper candidate.

### 6. Frozen forward paper pilot and later confirmation

Forward candidate features and shadow outcomes remain append-only and separate
from historical data. Each record needs strategy, feature-schema, dataset/model
and prompt versions. The current 26-week experiment is explicitly a pilot. A
later confirmatory experiment must be powered from pilot variance and frozen
under its own version before it begins. Candidate count is not an optional
stopping rule.

#### Frozen prospective pilot: `forward-pilot-20260719-v3`

Frozen at 2026-07-18 23:04:38 UTC. Assignment stops once at
2027-01-16 23:04:38 UTC and the experiment is evaluated once after its fixed
seven-day maturity buffer at 2027-01-23 23:04:38 UTC. The binding
machine-readable contract is `config/research_variants.json`, SHA-256
`1af9f22e4fe21bacbc6766d85911a65c206fb857a512c782888133b8c1dfdcba`.
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
- Common lifecycle: fixed 48 UTC-clock-hour barrier horizon; if the market is
  closed at cutoff, expiry is the first executable close at/after cutoff and
  that post-cutoff candle's high/low cannot manufacture a barrier hit.
  Executable ask entry/bid barrier is used for BUY, executable bid entry/ask
  barrier for SELL, with 0.10 slippage points per side and the same four-hour
  setup cooldown. Midpoint fixed-spread fallback is prohibited for this pilot.
- SELL remains in the baseline and outcome collection but cannot be relabelled
  into the BUY variant.
- Assignment has no effect on Claude/ML approval, the paper ledger status,
  Telegram or model training/selection.

Assignments are appended once to `data/forward_variant_assignments.csv` and
joined to immutable features/outcomes by `candidate_id`. Operational health and
counts may be monitored. Directional performance, expectancy, PF, win rate and
variant comparisons must not be inspected before the fixed evaluation. The
pilot's estimated power for the corrected historical +0.0743% mean return per
candidate is only 15.3%, and estimated power after 200 candidates is only
18.6%. Neither a null nor a positive point estimate is confirmatory. Its
purpose is plumbing, feed stability, event-rate, falsification and forward
variance estimation.

The v3 contract superseded v2 before any forward assignments or outcomes
existed. It was necessary because the legacy historical target implemented
"48 hours" as 192 traded 15-minute candles. The corrected target monitors
barriers only through a fixed UTC cutoff and fold purging uses each label's
actual exit timestamp.

## Current model decision

The calibrated purged walk-forward XGBoost result on corrected v4 targets is
`REJECT_MODEL`.
No model artifact may be created or deployed from it. Hyperparameter search on
the same years is prohibited until the event lifecycle, dependence weighting
and directional research questions above are implemented.

`research/benchmark_candidate_models.py` runs prevalence, direction-only,
SMC-score-only logistic, all-feature logistic and XGBoost through the same
folds, purge, calibration and selection rule. No model has an AUC interval
excluding chance or a selected-return interval excluding zero. All-feature
logistic reaches AUC 0.5052 and +0.0045% selected mean; XGBoost reaches AUC
0.4888 and -0.0143%. This favors a feature/target research problem over model
shopping. The original gates are development thresholds, not a pristine
pre-registration: their code predates v3 but the local v2 artifact predates the
gate commit.

`research/benchmark_return_targets.py` tests whether the fixed candidate-time
features rank 1h/4h/12h/48h executable-side after-cost returns. It uses a
constant calibration-mean baseline, direction-only and SMC-score ridge
baselines, all-feature ridge and a fixed XGBoost regressor. Folds are
chronological, every boundary is purged by actual target exit, training rows
receive inverse-concurrency uniqueness weights and the live-feasible selection
threshold comes only from the prior calibration slice. The result is
`NO_EXPLORATORY_SIGNAL`: no model/horizon has a positive lower 95% bound for
rank IC, selected return and selected excess while also showing positive
selected return in at least three folds. The 48h all-feature ridge point
estimate (+0.114% selected mean) is unstable and its weekly interval
(-0.061% to +0.281%) includes zero. Target redesign alone therefore did not
rescue the current information set.

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

## Lifecycle portfolio diagnostic v5

The pre-registered four-hour nearby-entry cooldown and runtime-aligned gates
reduced 40,792 raw candidates to 2,702 opened development positions. With
$10,000 starting paper capital and $5,000 fixed notional per position:

- ending return: -2.33%;
- profit factor: 0.992;
- maximum drawdown: 36.42%;
- maximum concurrent positions: 11;
- BUY P&L: +$1,576.10;
- SELL P&L: -$1,809.12.

This is a rejection, not an edge. The near-flat ending return does not excuse
the unacceptable path drawdown, and SELL offsets BUY. Results remain
development-only because the period influenced the research design.

## Direction, dependence and ablation diagnostic

`research/analyze_research_evidence.py` reproduces direction-only portfolios,
label-interval uniqueness, deterministic weekly block bootstraps and fixed SMC
variant comparisons. Current development findings:

- 11,844 eligible labels have Kish effective sample size about 5,614, summed
  uniqueness about 2,996 and maximum label concurrency 46;
- BUY-only: +20.02%, PF 1.12, maximum drawdown 23.84%; weekly-bootstrap 95%
  return interval is -24.98% to +72.13%, so positive expectancy is not
  established;
- SELL-only: -18.09%, PF 0.88, maximum drawdown 39.36%; it remains shadow-only;
- BUY + liquidity sweep after lifecycle gates: +40.34%, PF 1.36 and 13.70%
  drawdown across 1,086 opened candidates, but its weekly-bootstrap 95% return
  interval is -3.81% to +90.11% and PF interval is 0.97 to 1.79;
- order-block, FVG and CHoCH filtered variants have negative total development
  returns.

Liquidity sweep is therefore a registered forward hypothesis, not an accepted
edge. The bootstrap lower bound is negative and no ablation result authorizes
ML training or approval.
