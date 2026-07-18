# Independent Review — Actions and Decisions

Status: implemented engineering/research response; no validated trading edge.

This document records the response to the skeptical external review. It is not
marketing material and must not be used to claim profitability.

## What the additional evidence established

### The ML rejection remains correct

`research/benchmark_candidate_models.py` compares constant prevalence,
direction-only logistic, SMC-score-only logistic, all-feature logistic and the
existing XGBoost model under identical expanding folds, 48-hour purge,
calibration and economic selection. The committed report is
`data/research/candidate_model_benchmarks_v1.json`.

| Model | OOS AUC | Brier | Selected mean net return |
|---|---:|---:|---:|
| Prevalence | 0.4836 | 0.1963 | -0.0062% |
| Direction logistic | 0.5109 | 0.1953 | -0.0048% |
| SMC-score logistic | 0.4811 | 0.1966 | -0.0052% |
| All-feature logistic | 0.5093 | 0.1970 | +0.0023% |
| XGBoost | 0.4899 | 0.1971 | -0.0093% |

Every dependence-aware AUC interval includes 0.50 and every selected-return
interval includes zero. XGBoost selected mean probability is 26.36% versus a
22.30% win rate, a 4.06-point gap—not the approximately 14 points inferred in
the external review. The economic conclusion is unchanged: there is no useful
validated model in this feature/target experiment.

### Gate provenance and future gate correction

Git history shows the original gate code predates the v3 result, but local file
times indicate v2 existed before the gate commit. The gates are therefore
development thresholds, not pristine pre-registration. Future promotion
requires superiority to a registered simple baseline and a weekly-block-
bootstrap lower confidence bound above zero; a merely positive point estimate
does not pass.

### BUY liquidity-sweep uncertainty

The lifecycle-filtered BUY + 1H liquidity-sweep variant opens 1,086 historical
positions, returns +43.20%, has PF 1.37 and 14.01% maximum drawdown. Its weekly
bootstrap 95% intervals are -5.76% to +101.28% for return and 0.95 to 1.86 for
PF. This remains a promising contaminated hypothesis, not an edge.

### Six months is a pilot, not validation

`research/plan_forward_experiment.py` estimates weekly-cluster power. At the
historical approximately +0.08% mean return per candidate, a 26-week run has
only about 14.4% power; a 200-candidate run has about 17.4%. Waiting and then
calling either result definitive would be scientifically wrong.

The replacement contract `forward-pilot-20260719-v2` has one fixed evaluation
time, 2027-01-16 22:35:57 UTC, no interim performance analysis and no
confirmation claim. It estimates event rate, feed reliability and forward
variance while separately versioned feature/target research continues now.

## Runtime defect found and repaired

The TradingView MCP snapshot contained the same exact 15-minute bars for every
requested timeframe. Its UI state changed, but its extracted OHLC payload did
not. The previous system therefore did not have valid multi-timeframe runtime
data. Cadence and duplicate-frame validation now fails closed.

The active paper-research source is account-free Dukascopy XAUUSD. The new
collector retrieves independent bid and ask candles at 1W, 1D, 4H, 1H and 15M,
excludes forming bars, validates 200 bars per frame, and writes an atomic
snapshot. A local full collection completed in approximately 3.3 seconds.
Forward BUY labels enter at ask and test TP/SL/expiry on bid; SELL labels enter
at bid and test on ask. The dashboard reports source, symbol, age, latest-bar
age, OHLC, bid/ask, cadence, ordering and uniqueness rather than bar counts
alone.

## What happens next without waiting

The fixed pilot runs in the background. Independent work proceeds on a
registered `gold_context` dataset, point-in-time macro/related-market features,
multi-horizon after-cost return and utility targets, and the same baseline-first
chronological harness. More complex models are considered only after new
information or a new target beats simple baselines. Broker execution remains
out of scope.
