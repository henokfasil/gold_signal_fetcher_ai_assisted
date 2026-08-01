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

#### Frozen evidence-integrity monitor: `evidence-integrity-20260719-v1`

The machine-readable operational contract is
`config/evidence_integrity_v1.json`. It reconciles in-scope canonical candidate
IDs, timestamps and directions against the technical-feature, shadow-outcome,
variant-assignment and context ledgers. Missing rows, duplicates, orphans,
identity drift, schema drift and contract drift are operational failures.

Input-distribution drift uses reference-only decile bins and population
stability index after at least 200 prospective rows: the first 100 are the
fixed reference and the latest non-overlapping 100 are current. PSI 0.10 is a
warning and PSI 0.25 is degraded; these are monitoring heuristics, not claims
about model decay or profitability. Outcome return, P&L, win-rate and
profit-factor columns are forbidden inputs. The monitor cannot affect scoring,
approval, Claude, Telegram, paper positions, training or model promotion.

#### Registered execution-state experiment: `execution-state-20260719-v1`

The machine-readable pre-analysis contract is
`config/execution_state_v1.json`. It registers 29 candidate-time XAUUSD
features derived from completed Dukascopy 15-minute bid/ask bars: observed
spread state, traded-bar returns and realized volatility, causal rolling
percentiles, true range and gaps, fixed-UTC liquidity-window state, range and
level distance, bars since a market gap, cyclic time and source-specific side
tick-volume diagnostics. The liquidity-window names are descriptive and are
not official exchange sessions. Tick volume is not exchange volume or signed
order flow.

The primary target is the existing executable-side 1h after-cost return;
4h/12h/48h are secondary diagnostics that cannot select a model or horizon.
The fixed model ladder begins with constant, direction and SMC-score controls,
then compares execution-only Ridge and technical-plus-execution Ridge/XGBoost
against matched no-execution controls. Thresholds come from prior calibration,
folds purge by actual exits, training uses uniqueness weights and uncertainty
uses calendar-week blocks. A primary pass additionally requires the selected
return lower bound to remain positive at 0.25 points slippage per side and at
least one separately eligible BUY or SELL direction. A development pass can
only register a future shadow hypothesis; failure creates no model artifact or
runtime behavior.

This registered experiment is complete. The exact-close joined dataset has
40,792 rows, no missing registered candidate features and SHA-256
`6f53daabc9ccf06c958d5bf3115eb76ffbc5e541085bf233d2676d36a2b506a5`.
The canonical report is `data/research/execution_state_benchmarks_v1.json`,
SHA-256 `6142e374e18fd1c77c6a5baa111e48f7a3e4e1403e93c1f09947d111b2221e3c`,
with decision `REJECT_EXECUTION_STATE_MODELS`.

On the primary 1h target, execution-only Ridge selected -0.0282% mean after
cost (weekly 95% interval -0.0420% to -0.0131%); technical-plus-execution
Ridge selected -0.0240% (-0.0393% to -0.0103%); and
technical-plus-execution XGBoost selected -0.0258% (-0.0392% to -0.0133%).
All had zero positive-return test folds. Their rank-IC, selected-excess,
paired-improvement and stressed-return lower bounds also failed the applicable
gates, and neither BUY nor SELL was independently eligible.

Execution-only Ridge's secondary 4h diagnostic ranked positively (rank IC
0.0419) and selected +0.0105%, but its selected-return interval was -0.0197%
to +0.0418%. This does not override the primary rejection. Under the frozen
contract it cannot choose a new primary horizon, model, threshold or shadow
variant. No execution-state artifact or runtime behavior was created.

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

## Registered experiment: candidate generation v2

`candidate-generation-20260719-v2` is registered before its outcome comparison
in `config/candidate_generation_v2.json`. Its machine-readable pre-analysis
contract fixes all of the following:

- causal setup-family definitions derived from candidate-time SMC objects;
- an unchanged trade-all control and frozen simple-rule baselines;
- separate BUY and SELL hypotheses and promotion decisions;
- executable bid/ask targets, costs and cost-stress assumptions;
- fixed calendar-year evaluation folds restricted by actual label exit, with
  no fitting or calibration, plus explicit uniqueness/dependence treatment;
- minimum sample/effective-sample requirements, fold stability and weekly
  block-bootstrap confidence gates; and
- an attempt registry that retains every family tested, including failures.

The single promotable development hypothesis is direction-specific liquidity
sweep plus direction-appropriate 4H value location plus an order-block or FVG
retest. Trade-all, score >= 85 and sweep-only are fixed controls. Value,
retest, CHoCH, multi-timeframe alignment and their other registered combinations
are secondary diagnostics and cannot be selected after their outcomes are
seen. BUY and SELL must pass separately using 97.5% lower confidence bounds to
account for the two primary directional hypotheses.

The purpose is to test whether the candidate universe is too heterogeneous and
can be defined more coherently using causal information. It is not permission
to mine arbitrary SMC combinations on the full 2020-2026 outcomes. The frozen
forward pilot and context observation continue unchanged in parallel.

The registered comparison is complete with
`REJECT_CANDIDATE_GENERATION_V2`. The canonical report is
`data/research/candidate_generation_benchmarks_v2.json`, SHA-256
`f6d2b68a0794c751772d57a07446ec956f2b8d71800d1394bed51298789941a0`.
The contract was committed as `8b851ea` before the evaluator and outcome run.

The primary BUY family opened 653 candidates, returned +12.09% at the fixed
paper notional, had PF 1.20 and 6.70% maximum drawdown. Its point estimate did
not pass: only two of five folds were positive; the weekly-block 97.5% interval
for mean return was -0.044% to +0.135%; the PF lower bound was 0.79; and the
cost-stressed and paired improvements versus trade-all and sweep-only all had
lower bounds below zero. SELL opened 618 candidates, returned -21.10%, had PF
0.65 and was negative in all five folds. Neither direction passed every gate.

No model, runtime filter, prospective variant, approval or Telegram behavior
is authorized. Secondary families remain non-selectable. The next experiment
must obtain genuinely new upstream information by regenerating a pre-score,
event-first universe with unique structural event identity and continuous
candidate-time geometry; it must be separately registered before evaluation.

## Registered experiment: event-first candidate universe v1

`event-candidate-universe-20260719-v1` is registered before dataset generation
or outcome inspection in `config/event_candidate_universe_v1.json`. It removes
the existing 4H-direction, minimum-score and minimum-R:R gates from universe
formation. A unique event is emitted only when a new completed-bar 1H sweep,
1H CHoCH, 1H FVG, 4H BOS or 4H CHoCH becomes observable. Stable IDs bind event
type, direction and source event-bar time so repeated scans cannot become new
observations.

Every event uses fixed 1H-ATR research geometry (one ATR stop, two ATR target)
and retains observed bid/ask for executable-side targets. The 55 registered
features measure continuous event/object geometry, including sweep depth and
reclaim, displacement, time since BOS/CHoCH, structure transitions,
ATR-normalized order-block/FVG age/width/distance, mitigation state, value
location and spread. Missing objects remain explicit rather than becoming
invented neutral values.

The primary target is 4h after-cost return. Direction/event-type Ridge is the
simple learned control; geometry Ridge and fixed shallow XGBoost are the only
gate-eligible models. Folds, actual-exit purge, prior calibration threshold,
uniqueness weighting, weekly blocks, cost stress and separate directional
eligibility are frozen. Secondary horizons and event-type diagnostics cannot
select a replacement target, model or event family. At registration time the
new event dataset and its outcomes did not exist.

The outcome-free extractor subsequently emitted 6,368 stable events with all
55 registered fields. The data-quality decision passed: 6,346 barrier-matured
unambiguous events, at least 434 per event type, at least 2,988 per direction,
zero duplicate IDs, zero source events after their decision time, zero invalid
identities and zero infinite registered feature values. The feature dataset
SHA-256 is
`f6333fec4957e8f383a4e3192e8c3da24eb543c34e61ea113ee7e7a1736dddfe`.

The frozen result is `REJECT_EVENT_CANDIDATE_UNIVERSE_MODELS` in
`data/research/event_candidate_universe_benchmarks_v1.json` (SHA-256
`e39f38e456f2ed24335231242fe529f3b57406bbc4d7d53dafeb0f4eb78f979c`).
The primary 4h geometry XGBoost selected +0.0046% mean after-cost return, but
the calendar-week 95% interval was -0.0255% to +0.0325%; rank IC was 0.0013
with interval -0.0311 to +0.0373. Its paired improvement over the registered
direction/event-type Ridge crossed zero, the 0.25-point-per-side stress median
was negative and neither BUY nor SELL passed separate eligibility. Geometry
Ridge selected a negative mean. Secondary horizons remain diagnostic and
cannot be used to choose a target, model, event type or threshold.

No event model artifact, historical filter, shadow approval, runtime decision,
Claude rule, Telegram behavior or broker path is authorized. Further work on
this event representation must be prospective or introduce genuinely new
pre-registered information; the inspected 2020-2026 event outcomes cannot be
mined into a replacement rule.

## Frozen prospective event observation v1

The outcome-blind operational contract
`forward-event-observation-20260723-v1` is frozen in
`config/forward_event_observation_v1.json`, SHA-256
`bdc69d70bf4aa7e0b340d4d9825ffded7567fd2bf7743881f7fb548490fed7fd`.
Collection begins no earlier than 2026-07-23 21:00:00 UTC.

The observer uses the exact stable IDs and ordered 55-feature geometry schema
from `event-candidate-universe-20260719-v1`. It converts the five validated
Dukascopy snapshot frames from candle-open timestamps to completed-close
timestamps, evaluates each newly completed 1H decision time once and writes:

- unique event rows to `data/forward_event_observations_v1.csv`; and
- one scan row, including valid zero-event hours, to
  `data/forward_event_scans_v1.csv`.

Both files are append-only. Snapshot content hash, provider, symbol, bid/ask
availability, exact 15M decision close, event source time, duplicate IDs and
the frozen geometry schema fail closed. The observer contains no outcome
columns and has no SMC, ML, Claude, paper approval, Telegram, broker, training
or model-promotion effect. Failure is logged but cannot alter the existing
candidate pipeline.

Historical/runtime feature concordance is not yet passed, including the
weekly-frame timestamp convention. Until an independently replayed set of
matching completed decision times agrees, prospective event fields may be
monitored only for cadence, counts, missingness, non-finite values and
provenance. A later outcome comparison requires a separately frozen contract;
this observation contract cannot establish or test profitability.

## Frozen event-feature concordance v1

The operational contract `event-feature-concordance-20260723-v1` is frozen in
`config/event_feature_concordance_v1.json`, SHA-256
`eb93d931d3e93650633c7010b59618670f8c9815a49033cb1e3698ccc7daab95`.
Its collection scope begins at 2026-07-24 00:00:00 UTC.

For every new in-scope 1H scan, the runtime retains the full validated
native-timeframe snapshot under its content SHA-256. The monitor first
recomputes that archived snapshot and requires exact agreement with the scan
and event ledgers. It then compares the same decision time with all five native
timeframes fetched again after the UTC-day cutoff. The same provider and
detector are disclosed limitations: this is a delayed source-revision,
timestamp, membership and feature-value test, not independent economic
information or an independently implemented detector.

Each delayed reference retains 400 bars per timeframe. At each historical
decision the comparator causally tails the same 200 bars used by runtime. The
200-bar surplus prevents a next-day fetch from discarding the earlier
decision's runtime window, especially the 96 possible intervening 15M bars.

The required preflight is stored in
`data/research/event_feature_concordance_preflight_v1.json`. Across 100
requested recent decisions, 38 had sufficient replay coverage. Event membership
matched for eight events, but the native runtime versus 15M-resampled
historical path produced 107 numeric and 10 missingness mismatches, including
different liquidity-sweep object presence. The canonical decision is
`REJECT_15M_RESAMPLED_FEATURES_FOR_NATIVE_RUNTIME_PROMOTION`. The old rejected
event models cannot be repackaged as runtime-compatible, and tolerances were
not loosened after observing the discrepancy.

A corrected 400-bar native reference was then sliced to the exact 200-bar
runtime window at 2026-07-23 21:00 UTC. All five timestamp windows and every
bid/ask/midpoint OHLC value matched exactly. That decision contained zero
registered events, so this is source-window validation only; the prospective
event coverage gates remain entirely unpassed.

Prospective native-path concordance requires at least 120 compared decision times, 30
compared events, BUY and SELL, all five registered event types, no archive or
self-replay failures, exact stable-ID membership, exact identity/missingness
and all numeric values within absolute and relative tolerance `1e-9`. The
scheduled artifact becomes stale after 30 hours or when replay lag exceeds 36
hours. It reads no outcomes or performance columns.

Even `PASS` can only set `shadow_registration_eligible`; it cannot authorize
event input to an existing model or Claude request, paper approval, Telegram,
model promotion or broker execution. `feature_use_authorized` remains false
even after technical concordance passes.

## Runtime AI and sentiment safety correction — 2026-07-23

The duplicate Claude decision optimizer is removed from the canonical path.
Each new SMC candidate receives at most one structured Claude review, and a
request is attempted only after deterministic ML, threshold, macro, market and
hard-risk gates pass. Each candidate still receives one provenance row;
precondition skips are explicitly distinguished from unavailable attempted
reviews. Exact attempted payloads, normalized responses, hashes, model and
prompt version are written to `data/forward_ai_reviews_v2.csv`. Claude is a
contextual review/veto only: its self-reported confidence is excluded from the
numeric approval score and cannot override ML, macro or hard risk gates.

A model is loadable for paper approval only when its metadata explicitly
records `PASS_DEVELOPMENT_GATES`, authorizes paper signals, freezes a selection
threshold and lists separately eligible directions. The simple chronological
trainer remains research-only and emits non-authorizing metadata.

The July 20 Yahoo-based observer is disabled in the canonical scheduler. Its
daily GC futures, EURUSD, nominal-yield and VIX momentum heuristics did not
implement the registered TradingView/news sentiment contract, did not record
real source staleness and did not produce an eligible point-in-time historical
comparison. Its synthetic fast benchmark reused SMC indicators and is not
evidence of independent sentiment. No sentiment value affects decisions.

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
