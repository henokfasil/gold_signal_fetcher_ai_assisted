# Independent AI Review Packet — Gold Signal Fetcher

Prepared: 2026-07-18

Repository revision: `9114ce76e2a1d94825f9c7a932cd7ab1a50e4959`

Scope: research methodology, historical evidence, ML rejection and proposed
forward experiment. This packet contains no secrets or credentials.

## Instructions to the independent reviewer

Act as a skeptical quantitative-research reviewer. Do not assume that the
existing conclusion is correct, and do not assume that a more complicated AI
model will create an edge. Separate verified facts, reasonable inferences and
unknowns. Identify fatal flaws separately from improvements that are unlikely
to change the conclusion.

Please answer these questions:

1. Is rejecting the current ML model justified by the evidence below?
2. Are the acceptance gates sensible, too strict or too weak?
3. Is there leakage, target contamination, invalid timing or execution-label
   bias in the described design or referenced code?
4. Could combining BUY and SELL, unweighted overlapping labels or the chosen
   target plausibly explain the failure?
5. Is the frozen BUY + 1H liquidity-sweep forward comparison scientifically
   useful, and what would invalidate it?
6. What is the smallest defensible next experiment? Rank recommendations by
   expected information value, not novelty.
7. Based only on this evidence, what claims may and may not be made about a
   trading edge, paper readiness, live readiness and commercial readiness?

When possible, inspect the referenced source and result files rather than
relying only on this summary. Report any numerical discrepancy.

## Neutral executive state

- This is an AI-assisted XAUUSD paper-research system. It cannot submit broker
  orders and enforces `PAPER_TRADING=true`.
- Runtime candidates come from TradingView MCP, exact symbol
  `OANDA:XAUUSD`, using W/D/4H/1H/15M snapshots.
- SMC creates directional BUY and SELL candidates. A validated ML filter and
  available Claude review are both required before a paper approval.
- The current historical XGBoost candidate classifier failed its development
  gates. No model artifact was deployed; therefore ML currently vetoes all
  approvals.
- Claude is a structured context reviewer/veto, not a source of price data and
  not evidence of statistical edge.
- A frozen forward shadow experiment is collecting future candidate outcomes.
  Shadow membership cannot approve a trade, send Telegram or train/select a
  model.
- No current result demonstrates a profitable or live-ready strategy.

## Data lineage

### Raw historical feed

- Provider: Dukascopy Bank SA public historical feed.
- Instrument: XAUUSD with bid, ask and midpoint OHLC.
- Timeframe: 15 minutes; timestamps are candle-open UTC.
- Requested interval: 2020-01-01 through 2026-07-18 exclusive.
- Actual first/last bars: 2020-01-01 23:00 UTC / 2026-07-17 20:45 UTC.
- Rows: 154,709; duplicate timestamps: zero.
- Mean close spread: 0.4644 points; 95th percentile: 0.8300 points.
- File: `data/raw/dukascopy_xauusd_15m_2020_2026.csv`.
- SHA-256:
  `c61a27b37628972377aff01817a223631fb57253ddc5dcd217cf0a6f6d3ddeeb`.
- Manifest: `data/raw/dukascopy_xauusd_15m_2020_2026.csv.manifest.json`.

This provider differs from runtime TradingView `OANDA:XAUUSD`. Cross-feed
stability has not yet been established.

### Candidate dataset v3

- File: `data/research/xauusd_smc_candidates_v3.csv`.
- SHA-256:
  `8d0444dd86d10bb87f6532711b310c06753892afdb34bbe4a81600d0b045a77e`.
- Candidates: 40,792.
- Bid/ask-labelled outcomes: 40,623.
- Ambiguous same-bar TP/SL: 168, excluded from binary training.
- Unmatured: one.
- Decision features are generated from information available at candidate
  time. A candle-open timestamp is shifted to candle close before visibility.
- BUY execution labels use ask entry and bid barrier/exit; SELL labels use bid
  entry and ask barrier/exit. Two-sided slippage is additionally deducted.
- Horizon: 48 hours. A TP and SL touched in the same 15-minute bar is labelled
  ambiguous rather than assigned optimistically.
- Dataset generation code: `research/build_historical_dataset.py`.

The full 2020–2026 period has influenced development decisions. It is not an
untouched final test, regardless of chronological folds inside that period.

## Strategy and feature definition

The SMC implementation is in `agent/smc_gold_scanner.py`. The 4H structure
selects direction. BUY uses bullish structure/BOS/CHoCH, downside liquidity
sweeps, bullish order blocks/FVGs, stop below entry and target above. SELL uses
the mirrored bearish mechanics. Ranging 4H structure fails closed.

The classifier receives 33 candidate-time features, including RSI, MACD, ADX,
ATR, Bollinger position/width, momentum, volatility, volume, hour/day,
direction, R:R, SMC score, higher-timeframe structures, BOS/CHoCH flags, 1H
liquidity sweep, order-block location, FVG and premium/discount position. Exact
schema: `agent/ml_feature_engineer_gold.py`.

## ML validation design

Implementation: `research/validate_walk_forward.py`.

- Model: fixed XGBoost binary classifier; maximum depth 3, 250 trees, learning
  rate 0.03, subsample/column sample 0.8, minimum child weight 10 and L2=2.
- Eligible rows require R:R >= 2 and matured, unambiguous labels.
- Expanding-year tests cover 2022, 2023, 2024, 2025 and 2026-to-date.
- Training uses only prior years. The last 20% of the prior window is reserved
  for logistic probability calibration.
- A 48-hour purge separates training, calibration and test boundaries because
  labels can look 48 hours forward.
- Selection threshold is candidate-specific break-even probability
  `1 / (R:R + 1) + 0.03`.
- The model is fitted jointly on BUY and SELL; direction is a feature. Results
  are reported separately afterward, but separate directional models were not
  fitted.
- Label-overlap uniqueness was measured later but was not used as
  `sample_weight` in this v3 model fit.
- The only explicit probability baseline in this report is constant test-fold
  prevalence for Brier score. Logistic/SMC-score-only ranking baselines were
  not included in v3.

Registered development gates in the code are:

1. overall ROC-AUC >= 0.55;
2. Brier score better than constant prevalence;
3. no year-fold AUC below 0.45;
4. positive selected mean after-cost return for BUY;
5. positive selected mean after-cost return for SELL.

The whole historical period is development-contaminated. The reviewer should
not treat these gates as a substitute for future confirmation and should
scrutinize when/how the gates were chosen.

## Exact ML v3 results

Result file: `data/research/walk_forward_v3.json`

SHA-256:
`1ee650902eee5431cdf9ff2c14c58f338df888f3873f9c618174a51fc4b3269e`

Status: `REJECT_MODEL`.

| Test period | Rows | ROC-AUC | Brier | Constant Brier |
|---|---:|---:|---:|---:|
| 2022 | 2,144 | 0.5498 | 0.1897 | 0.1861 |
| 2023 | 2,517 | 0.5077 | 0.2020 | 0.2013 |
| 2024 | 1,752 | 0.4578 | 0.1828 | 0.1768 |
| 2025 | 2,220 | 0.4812 | 0.2177 | 0.2105 |
| 2026 partial | 1,370 | 0.5016 | 0.1846 | 0.1798 |
| Overall | 10,003 | **0.4899** | **0.1971** | **0.1936** |

Economic diagnostic for 4,573 selected rows:

- selection rate: 45.72%;
- mean net return: -0.00927%;
- win rate: 22.30%;
- BUY selected mean: +0.02198%, AUC 0.4882;
- SELL selected mean: -0.04764%, AUC 0.4952.

Passed gates: no fold below 0.45 and positive BUY selected mean.

Failed gates: overall AUC, Brier improvement and positive SELL expectancy.

## Portfolio lifecycle diagnostic

Result: `data/research/portfolio_v4_report.json`

SHA-256:
`00c6f3486de92b62a5b16d7287a6bc728e417224ac1701a581ca65cb1b6897b3`

This applies the four-hour same-direction/nearby-entry setup cooldown, minimum
R:R, open-position/capital-loss gates and fixed $5,000 paper notional to the
historical candidate sequence.

- Opened: 2,695 of 40,792 candidates.
- Starting/ending capital: $10,000 / $9,959.16.
- Return: -0.41%; profit factor: 0.9987.
- Maximum drawdown: 34.55%; maximum concurrent positions: 12.
- BUY: 1,463 trades, +$1,396.99.
- SELL: 1,232 trades, -$1,437.82.

This is a development diagnostic using fixed notional, without broker
execution, financing costs or an untouched period.

## Dependence, direction and SMC diagnostic

Result: `data/research/research_evidence_v4.json`

SHA-256:
`1a7fdc6cd46c0f74ecb05022f7622b0047148a44303fc661bd77f8d793b41ce5`

- Eligible matured R:R rows: 11,843.
- Maximum simultaneous label intervals: 50.
- Sum of average uniqueness: 2,897.5.
- Kish effective sample size: 5,478.1.
- BUY-only lifecycle: +22.53%, PF 1.13, maximum drawdown 25.25%.
- BUY weekly block-bootstrap 95% return interval: -28.09% to +80.77%.
- SELL-only lifecycle: -14.72%, PF 0.90, maximum drawdown 38.28%.
- Structure + liquidity-sweep filter: +34.40%, PF 1.15, maximum drawdown
  19.26%, but only three of six evaluated years were positive.

The SMC ablations filter an already-generated candidate universe; they do not
regenerate signals after removing a component. The liquidity-sweep hypothesis
was selected after examining development history and is not independent
evidence.

## Frozen future paper comparison

Contract: `config/research_variants.json`

Experiment: `forward-shadow-20260718-v1`

Contract SHA-256:
`f2a9e6dd7880b10195fc3f2e0367ed9561e5354fa96af25c732887805287fff0`

- `baseline_v1`: all unique BUY and SELL SMC candidates after the existing
  four-hour duplicate cooldown.
- `buy_liquidity_v1`: BUY candidates with a point-in-time 1H downside
  liquidity-sweep object.
- Membership and R:R >= 2 eligibility are recorded separately.
- Outcomes use TP, SL or 48-hour expiry with the frozen cost assumptions.
- Assignments are immutable and joined by candidate ID to point-in-time
  features and shadow outcomes.
- Assignment has no effect on ML/Claude approval, paper status, Telegram or
  model training.
- Planned formal review requires both 3–6 calendar months and at least 200
  matured eligible BUY-variant candidates, extended if dependence materially
  reduces effective sample size.
- The clock starts with the first post-deployment assignment. At packet
  preparation time, the dashboard was awaiting that first assignment.

The forward contract compares future behavior but does not by itself solve
cross-feed differences, sparse BUY-variant frequency, repeated economic
exposure or the fact that the hypothesis came from inspected history.

## Known unresolved questions

1. Would separate BUY and SELL models materially outperform the joint model?
2. Would label-interval uniqueness weighting improve stability rather than
   merely alter fit?
3. Do simple baselines—direction/rule-only, logistic regression and SMC score—
   match or beat XGBoost?
4. Is binary barrier success the right target, or should the model rank
   after-cost return, MFE/MAE or a competing-risks outcome?
5. Are candidate-time session, volatility and trend regimes stable enough for
   forward use when selected strictly inside training folds?
6. How different are Dukascopy and OANDA candidate membership/outcomes over an
   overlapping sample?
7. Are costs conservative enough across spreads, news and rollover?
8. Is the target of 200 matured BUY-sweep candidates feasible within six
   months, and what stopping rule prevents optional peeking?
9. If ML continues to fail, should a validated rule-based system replace the
   mandatory ML gate rather than forcing an AI component?

## Reproduction commands

From the repository root with its virtual environment activated:

```bash
python -m research.validate_walk_forward \
  data/research/xauusd_smc_candidates_v3.csv \
  --output data/research/walk_forward_v3_reproduced.json

python -m research.simulate_portfolio \
  data/research/xauusd_smc_candidates_v3.csv \
  --events data/research/portfolio_v4_events_reproduced.csv \
  --report data/research/portfolio_v4_report_reproduced.json

python -m research.analyze_research_evidence \
  data/research/xauusd_smc_candidates_v3.csv \
  --output data/research/research_evidence_v4_reproduced.json

python -m unittest discover -s tests -v
python validate_code.py
```

## Additional repository documents

- `CLAUDE.md`: complete system handoff, current state and operational rules.
- `RESEARCH_PROTOCOL.md`: methodology, evidence boundaries and frozen
  hypothesis registry.
- `CLAUDE_RESTART_PROMPT.md`: session restart prompt; not independent evidence.
- `config/research_variants.json`: binding machine-readable forward contract.

Engineering tests show that code paths behave as specified. They do not prove
statistical validity, profitability, execution quality or production readiness.
