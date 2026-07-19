# Claude Research Restart Prompt

Copy the prompt below into the new Claude session from the repository root.

---

You are continuing an existing XAUUSD AI-assisted paper-trading research
project. Do not restart the project, assume profitability, or deploy live
trading.

Repository: `gold_signal_fetcher_ai_assisted`

Before taking any action:

1. Read `CLAUDE.md` completely.
2. Read `RESEARCH_PROTOCOL.md` completely.
3. Inspect `git status` and preserve all user-owned/untracked files.
4. Run the documented compile, unit-test and validation commands.
5. Confirm the canonical VPS is `187.55.229.4`, but do not access or mutate it
   until the local change is tested and the requested action authorizes
   deployment.

Important evidence already established:

- Historical source: local Dukascopy XAUUSD bid/ask 15-minute data, 2020-2026.
- Canonical development dataset:
  `data/research/xauusd_smc_candidates_v4.csv`.
- Dataset SHA-256:
  `0b74895cbd58917e485043acaee470815b1149a7d1647a662d93f08cda919520`.
- Walk-forward ML decision: `REJECT_MODEL`; overall ROC-AUC is approximately
  0.490 and calibrated probabilities do not beat the prevalence baseline.
- Simple prevalence/direction/SMC-score/all-feature logistic benchmarks do not
  reveal predictive signal either; their dependence-aware uncertainty includes
  chance/zero.
- Alternative 1h/4h/12h/48h after-cost return/ranking targets also returned
  `NO_EXPLORATORY_SIGNAL` across constant, direction/SMC-score ridge,
  all-feature ridge and fixed XGBoost regressors. The 48h ridge's positive point
  estimate has an interval spanning zero and unstable fold selection.
- Context v1 failed source preflight because the volatility proxy had no ask
  candles. The active experiment is pre-registered as
  `gold-context-20260719-v2` in `config/gold_context_v2.json`; it explicitly
  registers that proxy as bid-only and the other three as bid/ask midpoints.
  Contract SHA-256 is
  `a8d2f252ce2b4f06a0828a8b0639088e5fae216b8559134a79e89175e5462e50`.
  Preserve its exact instruments, timing, joins, features and gates or create a
  new version before inspecting affected outcomes.
- Context v2 is complete and rejected. Context-only Ridge passed three of five
  primary gates but failed rank-IC and selected-return lower bounds. Its BUY
  selected return was +0.0226% with a 95% interval spanning zero; SELL was
  negative. Do not tune or deploy this result.
- Prospective context observation is implemented under the frozen contract
  `forward-context-buy-20260719-v1` (SHA-256
  `97e7d3b4bf2ad00809c00c9e2b6cb6dfd6961b40c70e26da7772b42ef8048b70`).
  It appends all 26 registered backward-as-of fields plus source provenance to
  `data/forward_candidate_context_v1.csv` for both BUY and SELL candidates.
  Failures become explicit missing rows. It has no scoring, approval, Claude,
  Telegram, broker or training effect and no interim returns may be inspected.
- No validated ML model exists. Do not create metadata claiming otherwise.
- Lifecycle portfolio result: -2.33% return, profit factor 0.992, maximum
  drawdown 36.42%; BUY P&L positive and SELL P&L negative.
- 2020-2026 has influenced development and is not an untouched final test.
- The system is paper-only, fail-closed and contains no authorized broker
  execution path.
- TradingView MCP returned duplicated 15-minute payloads for every requested
  timeframe and is rejected for automated runtime use.
- Runtime source: account-free Dukascopy public XAUUSD bid/ask snapshots at
  1W/1D/4H/1H/15M with forming-bar, cadence, OHLC, quote and freshness checks.
- The legacy 48-hour label used 192 traded candles rather than a fixed UTC
  horizon. Corrected v4 targets monitor barriers only through the UTC cutoff,
  expire at the first executable close at/after it and purge folds by actual
  label exit time.
- Frozen experiment: `forward-pilot-20260719-v3`; assignment cutoff is
  2027-01-16 23:04:38 UTC and fixed evaluation after the maturity buffer is
  2027-01-23 23:04:38 UTC. No interim performance analysis or confirmation
  claim is permitted. Continue independent feature/target research while it
  runs.

Continue with these objectives in order:

1. Verify the active source snapshot, cron, dashboard, append-only pilot files
   and frozen contract hash without inspecting interim return performance.
2. Preserve context v2 and monitor prospective context source health,
   staleness, counts and missingness without inspecting interim performance or
   changing approval/Telegram behavior.
3. Use the existing registered multi-horizon after-cost return/MFE/MAE targets
   as diagnostics; do not rerun or tune them until genuinely new point-in-time
   information has been added.
4. Run each new feature experiment through the same simple-baseline-first
   chronological folds, purge, calibration and weekly-block uncertainty.
5. Keep SELL shadow-only unless its separate pre-registered research track
   passes all gates.
6. Update `CLAUDE.md`, `RESEARCH_PROTOCOL.md`, tests, Git and the canonical VPS
   together only after local verification.

Required methodological constraints:

- Strict chronological evaluation; no random split.
- Purge every train/calibration/test boundary using actual label exit times;
  nominal row counts or candle counts are not sufficient.
- Bid/ask execution labels when available.
- BUY and SELL reported independently.
- All failed results preserved and reported honestly.
- No threshold changes after viewing a test fold.
- No claim of production readiness or profitable edge.
- The 26-week pilot is underpowered and cannot confirm an edge. Use its variance
  to design a separately frozen, adequately powered confirmation if warranted.

Begin by summarizing your understanding of the current state in no more than
ten bullets. Then show the exact local verification results and propose the
smallest next implementation step. Proceed autonomously with safe read-only
diagnostics and locally authorized research changes, but stop before any live
trading, secret handling, destructive operation or unrequested external
action.

---
