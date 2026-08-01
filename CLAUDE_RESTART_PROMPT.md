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
- Execution-state v1 is complete under the frozen contract
  `config/execution_state_v1.json` (SHA-256
  `e2931d0f80525ca9f9b16d3f9ab2ca5c710b99f41a70dfd08ac8921adecf2232`).
  Its 29 completed-bar spread/volatility/window/range/volume fields preserve all
  40,792 candidates with exact-close joins and no missing feature values.
  The canonical decision is `REJECT_EXECUTION_STATE_MODELS`; all primary 1h
  execution models selected negative after-cost returns in every test fold.
  No model, score, approval or Telegram behavior was created.
- A positive-looking secondary 4h execution-only diagnostic is not eligible
  for promotion: its selected-return interval includes zero and the contract
  forbids using a secondary diagnostic to choose a horizon/model/threshold.
- Candidate generation v2 was registered before outcome inspection in
  `config/candidate_generation_v2.json` (SHA-256
  `484246c8c1c4cc464a7da9059fac9da1235ebf4d5ad90442fbb2c68642130da9`)
  and completed with `REJECT_CANDIDATE_GENERATION_V2`. The primary BUY
  sweep+value+retest family opened 653 candidates and returned +12.09% with PF
  1.20 and 6.70% drawdown, but only two of five folds were positive and its
  97.5% mean-return interval was -0.044% to +0.135%. It failed stress and both
  paired-improvement gates. SELL returned -21.10%, PF 0.65, with all folds
  negative. Result SHA-256 is
  `f6d2b68a0794c751772d57a07446ec956f2b8d71800d1394bed51298789941a0`.
- Candidate-generation v2 created no model, shadow variant, runtime approval or
  Telegram change. Do not select a replacement rule from its secondary
  diagnostics.
- Event-candidate-universe v1 is complete under
  `config/event_candidate_universe_v1.json` (SHA-256
  `2b57fac00d70b60452a19e14b2daa8d264316016d89fc2425bebf3e05ad40c12`).
  It generated 6,368 unique first-observable 1H/4H structural events with all
  55 registered causal geometry fields. All identity, timing, finiteness and
  minimum-sample data-quality gates passed.
- Its canonical result is `REJECT_EVENT_CANDIDATE_UNIVERSE_MODELS` in
  `data/research/event_candidate_universe_benchmarks_v1.json` (SHA-256
  `e39f38e456f2ed24335231242fe529f3b57406bbc4d7d53dafeb0f4eb78f979c`).
  Primary 4h geometry XGBoost selected +0.0046% mean, but its weekly interval
  was -0.0255% to +0.0325%; rank IC, paired improvement and cost stress also
  failed, and neither direction was eligible. Geometry Ridge was negative.
  Do not mine event types, directions, secondary horizons or thresholds from
  this inspected history, and do not create a model/runtime/Telegram rule.
- Prospective context observation is implemented under the frozen contract
  `forward-context-buy-20260719-v1` (SHA-256
  `97e7d3b4bf2ad00809c00c9e2b6cb6dfd6961b40c70e26da7772b42ef8048b70`).
  It appends all 26 registered backward-as-of fields plus source provenance to
  `data/forward_candidate_context_v1.csv` for both BUY and SELL candidates.
  Failures become explicit missing rows. It has no scoring, approval, Claude,
  Telegram, broker or training effect and no interim returns may be inspected.
- Evidence reconciliation and prospective input drift monitoring are frozen as
  `evidence-integrity-20260719-v1` (SHA-256
  `7aa62452c2cfd8e0c454163d35b82eb0e45612daa04ad2b88cd27d2c93550934`).
  Every scan checks missing, duplicate, orphan and mismatched candidate rows
  across all forward ledgers plus schema/contract drift. PSI is evaluated only
  after 200 rows using the fixed first 100 versus latest 100. The monitor never
  reads outcome returns or P&L and has no decision or notification effect.
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
- Dashboard users open `https://187.55.229.4/` and authenticate only over TLS.
  The legacy `http://187.55.229.4:8502/` listener redirects to that canonical
  address and must never present a Basic authentication challenge.
- The engineering baseline is operating, but the project is not finished: no
  validated profitable edge or deployable ML model exists. The event-first
  historical milestone is now complete and rejected. The next research task is
  isolated prospective collection of the same stable event schema and/or a
  separately registered genuinely new information source, not another remodel
  or post-hoc filter over the inspected rows.

Continue with these objectives in order:

1. Verify the active source snapshot, cron, dashboard, append-only pilot files
   and frozen contract hashes plus evidence-integrity status without inspecting
   interim return performance.
2. Preserve context v2 and monitor prospective context source health,
   staleness, counts and missingness without inspecting interim performance or
   changing approval/Telegram behavior.
3. Use the existing registered multi-horizon after-cost return/MFE/MAE targets
   as diagnostics; do not rerun or tune them until genuinely new point-in-time
   information has been added.
4. Preserve rejected execution-state v1 and do not tune or promote its 4h
   secondary diagnostic.
5. Preserve candidate-generation v2 as rejected; do not promote the BUY point
   estimate or any secondary setup family.
6. Preserve event-candidate-universe v1 as rejected. Do not promote the
   positive XGBoost point estimate or select a direction, event type, horizon,
   threshold or feature subset from the inspected diagnostics.
7. Implement an append-only prospective event journal using the exact frozen
   IDs and 55-field schema, initially disconnected from approval, Claude,
   Telegram and broker logic. Validate cadence, duplicates, missingness, drift
   and historical/runtime feature concordance without interim return analysis.
8. Run each later genuinely new-information experiment through the same
   simple-baseline-first chronological folds, purge, calibration and
   weekly-block uncertainty.
9. Keep SELL shadow-only unless its separate pre-registered research track
   passes all gates.
10. Keep the public dashboard at `https://187.55.229.4/`; keep Flask loopback
   only and redirect plaintext ports `80` and `8502` without requesting Basic
   credentials.
11. Update `CLAUDE.md`, `RESEARCH_PROTOCOL.md`, tests, Git and the canonical VPS
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
smallest isolated prospective event-journal contract; do not inspect interim
outcomes or connect it to decisions. Proceed
autonomously with safe read-only diagnostics and locally authorized research
changes, but stop before any live trading, secret handling, destructive
operation or unrequested external action.

---
