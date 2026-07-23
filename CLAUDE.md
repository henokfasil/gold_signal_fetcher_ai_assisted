# Gold Signal Fetcher — Unified AI-Assisted Research System

Last reviewed: 2026-07-23

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
- Canonical candidate/target dataset is
  `data/research/xauusd_smc_candidates_v4.csv`: the same 40,792 frozen SMC
  candidates, with 40,623 matured unambiguous bid/ask outcomes, 156 ambiguous
  outcomes and 13 unmatured outcomes. Dataset SHA-256 is
  `0b74895cbd58917e485043acaee470815b1149a7d1647a662d93f08cda919520`.
  It also contains registered 1h/4h/12h/48h after-cost return and MFE/MAE
  targets.
- The purged/calibrated walk-forward result is `REJECT_MODEL`: overall ROC-AUC
  0.489 and Brier score worse than its prevalence baseline. No model artifact
  was created or deployed. Never rename this result as validated ML.
- Like-for-like prevalence, direction-only, SMC-score logistic, all-feature
  logistic and XGBoost baselines all have dependence-aware AUC intervals that
  include chance and selected-return intervals that include zero. This
  localizes the failure to the tested information/target rather than showing
  that a more fashionable model class will fix it.
- Replacing the barrier label with 1h/4h/12h/48h after-cost return/ranking
  targets also produced `NO_EXPLORATORY_SIGNAL`. Constant, direction, SMC-score,
  all-feature ridge and XGBoost regressors used chronological actual-exit
  purging, prior-slice thresholds and uniqueness weights. None passed all four
  exploratory gates. The strongest-looking 48h ridge point estimate selected
  +0.114%, but its weekly 95% interval was -0.061% to +0.281% and selection
  collapsed to four rows in 2026; it is not a usable model.
- Context contract v1 was rejected at source preflight because `VOL.IDX/USD`
  returned no ask candles. No outcome was joined or inspected. The replacement
  information experiment was registered as `gold-context-20260719-v2` in
  `config/gold_context_v2.json` (SHA-256
  `a8d2f252ce2b4f06a0828a8b0639088e5fae216b8559134a79e89175e5462e50`).
  It uses precise Dukascopy dollar-index, silver, volatility-index and
  Treasury-bond CFD proxy identities with completed-candle availability and
  backward-only as-of joins. Volatility is explicitly bid-only; the other
  three use matched bid/ask midpoints. Source-data commercial rights are not
  yet reviewed; do not redistribute or sell it.
- Context v2 preserved all 40,792 candidates and added 26 backward-as-of
  features. Dataset SHA-256 is
  `6dd876a46b673edfbb02a172a3853ab105c148f1f21031f60cac9f0f83a806b0`.
  Dollar, silver and Treasury missingness is below 0.06%; the volatility proxy
  begins 2022-10-05 and is missing for 30.8% of candidates as registered.
- Context v2 result is `REJECT_CONTEXT_MODELS`. On the primary 4h target, the
  strongest context-only Ridge selected +0.0028% mean return and rank IC 0.036,
  but their weekly 95% intervals were -0.028% to +0.035% and -0.003 to 0.073.
  It passed three of five gates, not all five. BUY selected mean was +0.0226%
  with interval -0.0132% to +0.0661%; SELL was negative. No context model
  artifact may be created or deployed.
- Execution-state v1 is complete under the pre-analysis contract
  `config/execution_state_v1.json` (SHA-256
  `e2931d0f80525ca9f9b16d3f9ab2ca5c710b99f41a70dfd08ac8921adecf2232`).
  The exact-close dataset preserves all 40,792 candidates and adds all 29
  registered completed-bar spread, volatility, fixed-UTC window, range/gap and
  feed-specific tick-volume fields with no missing candidate values. Dataset
  SHA-256 is
  `6f53daabc9ccf06c958d5bf3115eb76ffbc5e541085bf233d2676d36a2b506a5`.
- The canonical result is `REJECT_EXECUTION_STATE_MODELS` in
  `data/research/execution_state_benchmarks_v1.json` (SHA-256
  `6142e374e18fd1c77c6a5baa111e48f7a3e4e1403e93c1f09947d111b2221e3c`).
  On the primary 1h target, execution-only Ridge selected -0.0282% mean return
  with weekly 95% interval -0.0420% to -0.0131%. Technical-plus-execution
  Ridge selected -0.0240% (-0.0393% to -0.0103%), and the matching XGBoost
  selected -0.0258% (-0.0392% to -0.0133%). Every primary model had zero
  positive test folds; no direction was eligible and no model passed.
- The secondary 4h execution-only Ridge diagnostic had positive rank IC 0.0419
  and selected +0.0105%, but its selected-return interval was -0.0197% to
  +0.0418%. The contract forbids using secondary diagnostics to select a
  horizon, model or threshold. It is not a shadow authorization or an edge.
- Candidate generation v2 is complete under the outcome-blind pre-analysis
  contract `config/candidate_generation_v2.json` (SHA-256
  `484246c8c1c4cc464a7da9059fac9da1235ebf4d5ad90442fbb2c68642130da9`).
  The contract was committed as `8b851ea` before the evaluator or outcome
  comparison. It fixed one promotable setup: direction-matched 1H liquidity
  sweep, direction-appropriate 4H value location, and an order-block or FVG
  retest. All other setup families were controls or non-selectable diagnostics.
- The canonical result is `REJECT_CANDIDATE_GENERATION_V2` in
  `data/research/candidate_generation_benchmarks_v2.json` (SHA-256
  `f6d2b68a0794c751772d57a07446ec956f2b8d71800d1394bed51298789941a0`).
  BUY opened 653 candidates, returned +12.09% at fixed paper notional, PF 1.20
  and 6.70% maximum drawdown, but only two of five calendar folds were positive
  and its mean-return 97.5% interval was -0.044% to +0.135%. Its cost-stressed
  interval and paired improvement intervals against trade-all and sweep-only
  also crossed zero. SELL opened 618, returned -21.10%, had PF 0.65 and every
  calendar fold was negative. Neither direction passed.
- No candidate-generation model, runtime filter, shadow variant, paper
  approval or Telegram change was created. The positive BUY point estimate is
  not an edge, and the secondary setup family results cannot be mined into a
  replacement primary rule under the frozen contract.
- Event-first candidate-universe v1 is complete under the pre-analysis contract
  `config/event_candidate_universe_v1.json` (SHA-256
  `2b57fac00d70b60452a19e14b2daa8d264316016d89fc2425bebf3e05ad40c12`).
  The outcome-free extractor generated 6,368 unique first-observable events
  across 1H sweeps/CHoCH/FVG and 4H BOS/CHoCH, with all 55 registered causal
  geometry fields. Feature dataset SHA-256 is
  `f6333fec4957e8f383a4e3192e8c3da24eb543c34e61ea113ee7e7a1736dddfe`.
  There are no duplicate IDs, future source-event times, invalid event types or
  infinite feature values; all sample-size and data-quality gates passed.
- The canonical event-first result is
  `REJECT_EVENT_CANDIDATE_UNIVERSE_MODELS` in
  `data/research/event_candidate_universe_benchmarks_v1.json` (SHA-256
  `e39f38e456f2ed24335231242fe529f3b57406bbc4d7d53dafeb0f4eb78f979c`).
  On 5,247 primary 4h out-of-sample events, geometry XGBoost selected 1,045
  with +0.0046% mean after-cost return, but its weekly 95% interval was
  -0.0255% to +0.0325%; rank IC was 0.0013 with interval -0.0311 to +0.0373.
  Its paired improvement versus direction/event-type Ridge also crossed zero,
  cost stress turned the bootstrap median negative, and neither direction was
  separately eligible. Geometry Ridge was negative. No model, runtime filter,
  shadow approval, Claude rule or Telegram behavior was created.
- Prospective context observation is frozen as
  `forward-context-buy-20260719-v1` in
  `config/forward_context_observation_v1.json` (SHA-256
  `97e7d3b4bf2ad00809c00c9e2b6cb6dfd6961b40c70e26da7772b42ef8048b70`).
  The runtime collector retains 200 completed 1H bars for the four exact v2
  proxies and validates source, sides, cadence and OHLC. Every unique BUY or
  SELL candidate receives the 26 backward-as-of fields, raw audit levels and
  snapshot/contract provenance in `data/forward_candidate_context_v1.csv`;
  failures are explicit missing rows. Context has no score, approval, Claude,
  Telegram, broker or training effect. Assignment ends 2027-01-17 12:49:25
  UTC and evaluation is once on 2027-01-24 12:49:25 UTC. Do not inspect
  interim returns.
- Evidence reconciliation is frozen as `evidence-integrity-20260719-v1` in
  `config/evidence_integrity_v1.json` (SHA-256
  `7aa62452c2cfd8e0c454163d35b82eb0e45612daa04ad2b88cd27d2c93550934`).
  After every scan it checks candidate coverage across technical features,
  shadow outcomes, variant assignments and context; it also detects duplicate
  IDs, orphans, timestamp/direction mismatches, invalid lifecycle states,
  missing context, and frozen schema/contract drift. The dashboard exposes
  these counts. Outcome returns, P&L, win rate and profit factor are excluded
  from the monitor's CSV reads, so it cannot reveal interim performance.
- Prospective input PSI begins only after 200 rows per ledger. The immutable
  first 100 rows define reference-only decile bins and the latest 100 form the
  non-overlapping current window. Registered PSI warning/alert thresholds are
  0.10/0.25. PSI is an operational distribution heuristic, not proof of model
  decay, predictive skill or profitability.
- The lifecycle portfolio diagnostic opens 2,695 positions from 40,792 raw
  candidates after cooldown/risk gates. It returns -2.33%, profit factor 0.992
  and maximum drawdown 36.42%. BUY contributes +$1,576.10; SELL contributes
  -$1,809.12. This is a rejected development result, not an edge.
- Overlap-aware evidence reduces the 11,844 eligible labels to Kish effective
  sample size about 5,614 (summed uniqueness about 2,996). BUY-only returns
  +20.02% developmentally, but its weekly-bootstrap 95% interval includes a
  large loss (-24.98% to +72.13%) and drawdown is 23.84%. SELL-only returns
  -18.09%. Liquidity sweep is only a forward hypothesis; it is not validated.
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
- A timing audit found the old “48-hour” historical label meant 192 traded
  candles: 4,019 labels exceeded 48 UTC hours and 1,071 comparable labels
  changed after correction. Runtime and research now monitor barriers only to
  the fixed cutoff, liquidate at the first executable close at/after it and
  purge folds using actual label exit times.
- Prospective experiment `forward-pilot-20260719-v3` is frozen in
  `config/research_variants.json` (SHA-256
  `1af9f22e4fe21bacbc6766d85911a65c206fb857a512c782888133b8c1dfdcba`). It
  compares the unchanged BUY/SELL baseline with a BUY + point-in-time 1H
  liquidity-sweep shadow variant. It has a single 26-week cutoff at
  2027-01-16 23:04:38 UTC assignment cutoff and one fixed evaluation after its
  maturity buffer at 2027-01-23 23:04:38 UTC. There is no interim performance
  evaluation or confirmatory edge claim. Assignments cannot approve a paper
  trade, send Telegram or select/train a model.

Completion checkpoint:

- The engineering baseline is operating: the dashboard, scheduled paper
  scanner, fail-closed Dukascopy collection, append-only evidence ledgers,
  Telegram integration, tests and integrity monitoring are in place.
- The research objective is **not complete**. No tested ML model has passed the
  promotion gates, no profitable edge has been demonstrated and the system is
  not ready for live capital or commercial claims.
- Rejected experiments are useful completed work: they prevent the same weak
  information from being repackaged under another model name. They do not mean
  that the whole AI-assisted research program failed.
- The event-first extraction milestone is complete and rejected at its model
  gates. Its append-only, outcome-blind prospective journal is registered and
  implemented under `forward-event-observation-20260723-v1`. Monitor event
  rate, cadence, missingness and provenance; independently validate Dukascopy
  historical/runtime feature concordance before any outcome experiment. Any
  TradingView/Pine/Claude
  annotation must be a separate prospective ledger with exact symbol,
  timeframe, completed-bar timestamp, prompt/model and source provenance; it
  has no decision effect unless a later frozen experiment passes.

Resume in this order:

1. Verify `git status`, run the verification commands below and confirm the
   canonical VPS revision/services without touching secrets or historical data.
2. Monitor snapshot cadence, latest-complete-bar lag and append-only pilot
   assignments/outcomes plus evidence-integrity status; operational monitoring
   must not reveal interim profitability.
3. Preserve context v2 as a failed-but-informative experiment; do not tune its
   features or thresholds on the same outcomes. Do not modify the frozen pilot.
4. Preserve execution-state v1 as rejected. Do not promote its secondary 4h
   diagnostic, tune its features or change its gates after seeing the result.
5. Monitor prospective context source health, counts and missingness without
   inspecting interim returns or giving the fields approval/Telegram effect.
6. Preserve candidate-generation v2 as rejected. Do not promote its BUY point
   estimate or choose a replacement rule from its secondary diagnostics.
7. Preserve event-candidate-universe v1 as rejected. Do not select its positive
   XGBoost point estimate, its three positive folds, a direction, event type,
   target horizon or threshold from the inspected diagnostics.
8. Keep the prospective event journal isolated from approval, Claude, Telegram
   and broker logic. Validate cadence, exact-close availability, duplicates,
   missingness and historical/runtime feature concordance without outcomes.
9. Add genuinely new causal regime/session or independently sourced
   information only under a new pre-analysis contract. Fit inside chronological
   folds. Register every proposed filter before examining its next-fold result.
10. Freeze a revision only if the underlying non-ML baseline and any ML filter
   pass development gates. Final evidence must come from future forward paper
   observations with no mid-test changes.

Prohibited shortcuts: random train/test splits, synthetic training fallbacks,
midpoint-only execution labels when bid/ask exists, counting overlapping rows
as independent trials, combining BUY and SELL performance to hide a weak side,
optimizing on 2020-2026 then calling it out of sample, deploying a failed model,
or enabling broker execution.

## Sentiment experiment correction — 2026-07-23

The July 20 sentiment implementation is not an eligible experiment and is
disabled in the canonical scanner wrapper. Its runtime code used Yahoo daily
price momentum for GC futures, EURUSD, nominal Treasury yields and VIX; it did
not implement the registered TradingView/news contract, point-in-time
historical join or true staleness semantics. The “fast” benchmark synthesized
sentiment from existing SMC indicators and cannot establish independent
information.

Do not deploy, score, approve, notify or make claims from those sentiment
files. A replacement needs a new hash-locked contract with exact source
identities, publication/availability timestamps, licensing, historical
coverage and a leakage-safe comparison before any outcome is inspected.

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
- `0.0.0.0:8502` is the process's server-side bind address, not a replacement
  dashboard URL. It means “accept port 8502 traffic arriving on any VPS network
  interface”; users still browse only to `http://187.55.229.4:8502/`.
  Binding to `127.0.0.1:8502` would make the dashboard reachable only from the
  VPS itself. Do not change the working bind merely to make it resemble the
  public URL.
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

The corrected like-for-like benchmark in
`data/research/candidate_model_benchmarks_v2.json` localizes the failure:

- all-feature XGBoost: overall ROC-AUC 0.4888, Brier 0.2062 and selected mean
  after-cost return -0.0143%;
- all-feature logistic regression: overall ROC-AUC 0.5052, Brier 0.2052 and
  selected mean after-cost return +0.0045%;
- direction-only logistic regression: overall ROC-AUC 0.5029 and selected mean
  after-cost return +0.0016%;
- XGBoost weekly-block-bootstrap 95% intervals include both chance for ROC-AUC
  (0.4547 to 0.5234) and zero for selected return (-0.0632% to +0.0403%).

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

1. Collect `forward-pilot-20260719-v3` unchanged until its fixed assignment
   cutoff at 2027-01-16 23:04:38 UTC; monitor only operational integrity/counts.
2. Do not inspect interim pilot performance and do not stop at a convenient
   candidate count. Evaluate once at 2027-01-23 23:04:38 UTC after the fixed
   maturity buffer.
3. Treat the pilot as feed/plumbing/event-rate/variance evidence. Its estimated
   power for the corrected historical +0.074% per-candidate effect is only
   about 15.3%; it
   cannot by itself confirm profitability.
4. Preserve the rejected context-v2 result; its weak BUY/context lead is
   hypothesis-generating only and cannot be tuned on the same years.
5. Preserve rejected execution-state v1. Its 1h models lost after cost in every
   test fold; its positive 4h diagnostic cannot select a new model or horizon.
6. Keep the prospective runtime context contract unchanged; monitor only exact
   source health, staleness, candidate counts and missingness until evaluation.
7. Preserve `REJECT_CANDIDATE_GENERATION_V2`. Its primary BUY point estimate
   was positive but failed fold stability, uncertainty, stress and paired-
   improvement gates; SELL was negative in every fold. Do not select a
   secondary family or fit another model on the same candidate rows.
8. Preserve `REJECT_EVENT_CANDIDATE_UNIVERSE_MODELS`. The broader upstream
   universe and continuous geometry passed integrity gates but did not beat the
   registered direction/event-type control with dependence-aware certainty.
   Do not mine secondary horizons or event families from this history.
9. Monitor the isolated prospective event journal's counts, source/cadence
   integrity and feature missingness. Complete historical/runtime concordance
   without interim return analysis or decision effect. Register any new
   information source before it can enter an outcome comparison.
10. Continue model/prompt/dataset lineage, drift and calibration monitoring.
11. Secure the public dashboard with a reverse proxy, HTTPS and authentication
   before treating it as a customer-facing service. This is an operations gate,
   not evidence of trading performance.
12. Do not design live-capital execution unless a later frozen forward test
   passes the registered gates; this experiment remains paper-only.

### Validation decision rule

`research/validate_walk_forward.py` performs expanding-year walk-forward
evaluation with actual-label-exit purging around train/calibration/test
boundaries and a separate chronological probability-calibration slice.
Development gates require
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

Then build frozen candidates from midpoint OHLC while retaining bid/ask columns
for execution-cost research, and relabel them with fixed-clock executable-side
targets:

```bash
python -m research.build_historical_dataset \
  data/raw/dukascopy_xauusd_15m_2020_2026.csv \
  data/research/xauusd_smc_candidates_v3.csv \
  --timestamp-is open --scan-minutes 15 --expiry-hours 48 \
  --spread-points 0.83 --slippage-points 0.10

python -m research.relabel_candidate_targets \
  data/research/xauusd_smc_candidates_v3.csv \
  data/raw/dukascopy_xauusd_15m_2020_2026.csv \
  data/research/xauusd_smc_candidates_v4.csv \
  --timestamp-is open --expiry-hours 48 --slippage-points 0.10
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

The separate prospective context ledger is
`data/forward_candidate_context_v1.csv`, registered by
`config/forward_context_observation_v1.json`. The wrapper refreshes
`/tmp/gold_context_snapshot.json` at most about hourly; cached scans only
validate the existing file. The initial local collection took about 45 seconds
wall time because it fetched seven source/side series. Cached checks took about
one second and do not materially load the VPS. The dashboard reads these files
only and exposes health, exact symbols/sides, staleness, missingness and
counts—not interim performance.

`agent/evidence_integrity.py` reconciles candidate identity and coverage across
all forward ledgers without selecting outcome performance columns. The scanner
wrapper runs `python -m ops.check_evidence_integrity` after every completed
scan and atomically writes `data/evidence_integrity_status.json`; the file is a
generated operational artifact and is ignored by Git. A degraded audit is
visible in logs and the dashboard but cannot alter the already completed paper
decision. No-candidate state is reported as ready rather than as a failure.

Historical and forward observations must remain separate. Never use forward
results to repeatedly retune the frozen model being evaluated.

### Alternative return-target benchmark

`research/benchmark_return_targets.py` evaluates 1h/4h/12h/48h after-cost
returns with a constant calibration mean, direction-only ridge, SMC-score
ridge, all-feature ridge and fixed XGBoost regressor. It purges each boundary by
the target's actual executable exit, weights training rows by inverse interval
concurrency, fixes the selection threshold at the prior calibration slice's
80th score percentile, reports BUY/SELL separately and uses calendar-week block
bootstrap intervals. The canonical report is
`data/research/return_target_benchmarks_v1.json`; its result is
`NO_EXPLORATORY_SIGNAL`. This is evidence against the present information set,
not against ML in general.

### Gold-context v2 collection

The hash-locked downloader writes resumable local 1H inputs and a provenance
manifest without accessing candidate outcomes:

```bash
python -m research.download_gold_context data/raw/gold_context_v2 \
  --start 2020-01-01 --end 2026-07-18 --chunk-days 90
```

`DOLLAR.IDX/USD`, `XAG/USD` and `USTBOND.TR/USD` require matched bid/ask
candles and use midpoint analysis prices. `VOL.IDX/USD` is explicitly bid-only
because the source returned no ask history. Raw files remain local and may not
be redistributed or sold unless commercial rights are separately established.

Join the frozen candidates with backward-only as-of features and run the
registered comparison:

```bash
python -m research.build_gold_context_dataset \
  data/research/xauusd_smc_candidates_v4.csv \
  data/raw/dukascopy_xauusd_15m_2020_2026.csv \
  data/raw/gold_context_v2 \
  data/research/xauusd_smc_candidates_context_v2.csv

python -m research.benchmark_gold_context \
  data/research/xauusd_smc_candidates_context_v2.csv \
  --output data/research/gold_context_benchmarks_v1.json \
  --bootstrap-samples 500
```

The canonical result is `REJECT_CONTEXT_MODELS`. A weak context-only BUY lead
does not pass selected-return uncertainty and may be used only to register a
future hypothesis, never to deploy or retroactively relax the gates.

### Execution-state v1 benchmark

`research/build_execution_state_dataset.py` verifies the frozen raw/candidate
hashes, interprets raw timestamps as candle opens, makes fields available only
at open plus 15 minutes and requires an exact candidate-close join. It adds the
29 features registered by `config/execution_state_v1.json`; raw and joined CSVs
remain local because their redistribution rights have not been reviewed.

```bash
python -m research.build_execution_state_dataset \
  data/research/xauusd_smc_candidates_v4.csv \
  data/raw/dukascopy_xauusd_15m_2020_2026.csv \
  data/research/xauusd_smc_candidates_execution_state_v1.csv

python -m research.benchmark_execution_state \
  data/research/xauusd_smc_candidates_execution_state_v1.csv \
  --output data/research/execution_state_benchmarks_v1.json \
  --bootstrap-samples 500 --seed 42
```

The benchmark hard-fails if its registered feature schema, model ladder,
paired controls, XGBoost parameters, cost grid, bootstrap count or seed drift.
The canonical primary result is `REJECT_EXECUTION_STATE_MODELS`: all three
eligible execution models fail every positive-return gate, with zero positive
1h test folds and no separately eligible direction. No model artifact, runtime
score, approval rule or Telegram behavior may be created from this result.

### Candidate-generation v2 benchmark

The contract was committed before the outcome comparison and is enforced by an
exact hash in `research/benchmark_candidate_generation.py`. Reproduce the fixed
rule evaluation with:

```bash
python -m research.benchmark_candidate_generation \
  data/research/xauusd_smc_candidates_v4.csv \
  --output data/research/candidate_generation_benchmarks_v2.json \
  --bootstrap-samples 2000 --seed 42
```

The evaluator applies each registered setup family before the four-hour
same-direction/nearby-entry cooldown, uses the runtime-aligned paper portfolio,
reports BUY and SELL separately, resamples whole calendar weeks and applies
incremental two-sided slippage stress. Only `sweep_value_retest_primary` was
eligible to pass; all other families were fixed controls or diagnostics. The
canonical result is `REJECT_CANDIDATE_GENERATION_V2`, with no runtime effect.

### Event-first candidate-universe v1 benchmark

The contract was committed before extraction and outcome comparison. Rebuild
the outcome-free universe, apply fixed-clock executable-side labels and
reproduce the frozen evaluation with:

```bash
python -m research.build_event_candidate_universe \
  data/raw/dukascopy_xauusd_15m_2020_2026.csv \
  data/research/xauusd_event_features_v1.csv \
  --contract config/event_candidate_universe_v1.json

python -m research.relabel_candidate_targets \
  data/research/xauusd_event_features_v1.csv \
  data/raw/dukascopy_xauusd_15m_2020_2026.csv \
  data/research/xauusd_event_candidates_v1.csv \
  --timestamp-is open --expiry-hours 48 --slippage-points 0.10

python -m research.benchmark_event_candidate_universe \
  data/research/xauusd_event_candidates_v1.csv \
  --output data/research/event_candidate_universe_benchmarks_v1.json \
  --bootstrap-samples 500 --seed 42
```

The extractor emits a structural event only on its first observable completed
bar, hard-fails on duplicate/future IDs and stores continuous geometry without
outcomes. The evaluator verifies both manifests and every frozen evaluation
choice, uses actual-exit purging and uniqueness weights, and reports weekly
block uncertainty plus BUY/SELL eligibility. The canonical decision is
`REJECT_EVENT_CANDIDATE_UNIVERSE_MODELS`: both geometry models failed the
primary 4h gates and no direction was eligible. The CSVs remain local because
source-data commercial rights are not reviewed; the contract, manifests and
machine-readable benchmark report are versioned.

## Prospective event journal and AI safety correction — 2026-07-23

The next registered milestone is now implemented under
`config/forward_event_observation_v1.json`, SHA-256
`bdc69d70bf4aa7e0b340d4d9825ffded7567fd2bf7743881f7fb548490fed7fd`.
It records the same stable event IDs and 55 causal geometry fields as the
rejected historical event-first experiment, plus one valid zero-event scan row
per completed 1H decision time. It is outcome-blind and has no decision,
Claude, Telegram, broker, training or promotion effect. Historical/runtime
feature concordance remains pending.

The runtime now makes at most one structured Claude request per new SMC
candidate. Claude is an evidence-conflict reviewer and veto, not a numeric
alpha vote. Its self-reported confidence is excluded from approval arithmetic.
Exact request/response payloads, hashes, model and prompt version are appended
to `data/forward_ai_reviews_v2.csv`.

ML remains unavailable and mandatory. A future artifact is loadable for paper
approval only if its metadata explicitly records passed development gates,
paper authorization, a frozen selection threshold and separately eligible
directions. The existing simple-holdout trainer cannot create an authorized
runtime model.

The Yahoo daily-price observer previously called “sentiment” is disabled. It
did not implement its stated TradingView/news contract, and its synthetic
benchmark reused existing SMC indicators. Do not use its snapshot or report as
sentiment evidence.

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
