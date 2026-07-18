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
  `data/research/xauusd_smc_candidates_v3.csv`.
- Dataset SHA-256:
  `8d0444dd86d10bb87f6532711b310c06753892afdb34bbe4a81600d0b045a77e`.
- Walk-forward ML decision: `REJECT_MODEL`; overall ROC-AUC is approximately
  0.490 and calibrated probabilities do not beat the prevalence baseline.
- No validated ML model exists. Do not create metadata claiming otherwise.
- Lifecycle portfolio result: -0.41% return, profit factor 0.999, maximum
  drawdown 34.55%; BUY P&L positive and SELL P&L negative.
- 2020-2026 has influenced development and is not an untouched final test.
- The system is paper-only, fail-closed and contains no authorized broker
  execution path.

Continue with these objectives in order:

1. Reproduce the lifecycle portfolio result from code and verify its manifest
   and assumptions.
2. Produce separate BUY-only and SELL-only portfolio reports using identical
   cooldown, bid/ask costs, capacity and account-level loss caps.
3. Implement label-interval uniqueness weights so overlapping outcomes are not
   treated as independent observations.
4. Add weekly block-bootstrap confidence intervals for after-cost expectancy,
   profit factor and drawdown-related summaries.
5. Implement pre-registered expanding walk-forward ablations for:
   structure-only, structure + liquidity sweep, structure + order block,
   structure + FVG, structure + CHoCH, and full SMC.
6. Compare each variant with a simple non-ML baseline. Do not tune XGBoost or
   select filters using the entire period.
7. Keep SELL shadow-only unless its separate pre-registered research track
   passes all gates.
8. Update `CLAUDE.md`, `RESEARCH_PROTOCOL.md`, tests, Git and the canonical VPS
   together only after local verification.

Required methodological constraints:

- Strict chronological evaluation; no random split.
- At least 48-hour purging/embargo around label-dependent boundaries.
- Bid/ask execution labels when available.
- BUY and SELL reported independently.
- All failed results preserved and reported honestly.
- No threshold changes after viewing a test fold.
- No claim of production readiness or profitable edge.
- Final confirmation requires a frozen future paper-trading period of at least
  3-6 months and sufficient matured, effectively independent observations.

Begin by summarizing your understanding of the current state in no more than
ten bullets. Then show the exact local verification results and propose the
smallest next implementation step. Proceed autonomously with safe read-only
diagnostics and locally authorized research changes, but stop before any live
trading, secret handling, destructive operation or unrequested external
action.

---
