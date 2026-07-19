# Independent Review — Actions and Decisions

Status: implemented engineering/research response; no validated trading edge.

This document records the response to the skeptical external review. It is not
marketing material and must not be used to claim profitability.

## What the additional evidence established

### The ML rejection remains correct

`research/benchmark_candidate_models.py` compares constant prevalence,
direction-only logistic, SMC-score-only logistic, all-feature logistic and the
existing XGBoost model under identical expanding folds, actual-label-exit
purging,
calibration and economic selection. The committed report is
`data/research/candidate_model_benchmarks_v2.json`.

| Model | OOS AUC | Brier | Selected mean net return |
|---|---:|---:|---:|
| Prevalence | 0.4829 | 0.2036 | -0.0064% |
| Direction logistic | 0.5029 | 0.2028 | +0.0016% |
| SMC-score logistic | 0.4794 | 0.2040 | -0.0079% |
| All-feature logistic | 0.5052 | 0.2052 | +0.0045% |
| XGBoost | 0.4888 | 0.2062 | -0.0143% |

Every dependence-aware AUC interval includes 0.50 and every selected-return
interval includes zero. The economic conclusion is unchanged: there is no
useful validated model in this feature/target experiment.

### Gate provenance and future gate correction

Git history shows the original gate code predates the v3 result, but local file
times indicate v2 existed before the gate commit. The gates are therefore
development thresholds, not pristine pre-registration. Future promotion
requires superiority to a registered simple baseline and a weekly-block-
bootstrap lower confidence bound above zero; a merely positive point estimate
does not pass.

### BUY liquidity-sweep uncertainty

The lifecycle-filtered BUY + 1H liquidity-sweep variant opens 1,086 historical
positions, returns +40.34%, has PF 1.36 and 13.70% maximum drawdown. Its weekly
bootstrap 95% intervals are -3.81% to +90.11% for return and 0.97 to 1.79 for
PF. This remains a promising contaminated hypothesis, not an edge.

### Six months is a pilot, not validation

`research/plan_forward_experiment.py` estimates weekly-cluster power. At the
historical corrected +0.0743% mean return per candidate, a 26-week run has
only about 15.3% power; a 200-candidate run has about 18.6%. Waiting and then
calling either result definitive would be scientifically wrong.

The replacement contract `forward-pilot-20260719-v3` stops new assignments at
2027-01-16 23:04:38 UTC and has one fixed evaluation time after its maturity
buffer, 2027-01-23 23:04:38 UTC. It permits no interim performance analysis and
no confirmation claim. It estimates event rate, feed reliability and forward
variance while separately versioned feature/target research continues now.

### Clock-horizon defect and correction

The external review accepted the stated 48-hour purge, but code inspection
found that the historical label used 192 traded candles rather than 48 UTC
clock hours. Weekend closures made 4,019 labels run longer than 48 clock hours;
1,071 comparable outcomes changed when corrected. Dataset v4 now monitors
barriers only through the fixed cutoff, expires at the first executable close
at/after cutoff without using that post-cutoff candle's range, and purges
training/calibration/test boundaries using actual exit times. The prospective
contract was upgraded before any assignments or outcomes existed.

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

The fixed pilot runs in the background. The first independent target redesign
is complete: 1h/4h/12h/48h after-cost returns were evaluated with a constant
baseline, direction/SMC-score ridge, all-feature ridge and fixed XGBoost under
actual-exit purging, uniqueness weights, prior-calibration thresholds and
weekly block uncertainty. No target/model passed the exploratory gates. The
48h all-feature ridge selected +0.114% on its point estimate, but its 95%
interval was -0.061% to +0.281% and its 2026 fold selected only four rows.

Independent work therefore proceeds on a registered `gold_context` dataset and
genuinely new point-in-time macro/related-market features. More complex models
are considered only after new information beats simple baselines. Broker
execution remains out of scope.

That first `gold_context` experiment is now complete. Four precisely identified
Dukascopy proxies were joined backward at their completed-candle availability
times. Context-only Ridge improved selected excess over a constant control, but
its primary 4h rank-IC and selected-return intervals still crossed zero. It
therefore passed three of five gates and was rejected. BUY is a weak prospective
hypothesis; SELL remains negative. The next engineering step is append-only
prospective context capture, not retrospective threshold tuning.

The append-only context capture and evidence-integrity monitor are now
implemented. The subsequent registered execution-state experiment also
completed and was rejected: all primary 1-hour execution-state models selected
negative after-cost returns in every test fold, and no direction qualified.
Its positive-looking 4-hour secondary diagnostic has an uncertainty interval
spanning zero and cannot be promoted under the frozen contract.

The next local research priority is therefore candidate generation rather than
another model-class substitution. A new `candidate-generation-20260719-v2`
contract must freeze causal SMC setup families and compare them with trade-all
and simple-rule controls separately for BUY and SELL before any ML ranking is
attempted. The prospective pilot continues unchanged while this independent
development work proceeds.
