# Gold Signal Fetcher — AI-Assisted Research System

Paper-trading research pipeline combining directional BUY/SELL SMC candidates, validated
historical-data ML inference, point-in-time macro context and a conservative
Claude review.

This repository does not execute broker orders and does not currently claim a
profitable edge. Missing ML or Claude evidence causes a candidate to be logged
as rejected rather than approved with fabricated fallback confidence.

The canonical dashboard URL is `http://187.55.229.4:8502/`. Seeing the process
listen on `0.0.0.0:8502` does not change that URL: `0.0.0.0` is a server bind
setting that allows traffic addressed to the VPS public IP to reach the app.

A separate hash-locked observation layer captures 26 cross-market context
fields prospectively for every unique BUY and SELL paper candidate. It is
disconnected from scoring, approvals, Claude, Telegram and broker execution;
the dashboard reports only source health, staleness, missingness and counts
until the fixed evaluation date.

The dashboard also reconciles every in-scope candidate across the technical
feature, shadow-outcome, variant-assignment and context ledgers. It reports
missing rows, duplicates, orphans, identity/schema/contract drift and
prospective feature PSI, while deliberately never reading interim return or
P&L columns.

The registered `execution-state-20260719-v1` experiment added 29 causal
spread, volatility, fixed-UTC liquidity-window, range/gap and feed-specific
tick-volume fields to the frozen historical candidates. Its primary 1-hour
walk-forward result is `REJECT_EXECUTION_STATE_MODELS`: selected returns were
negative after costs in every test fold, so no model or runtime behavior was
created. The machine-readable result is
`data/research/execution_state_benchmarks_v1.json`.

The pre-registered candidate-generation v2 setup taxonomy is complete with
`REJECT_CANDIDATE_GENERATION_V2`. The primary BUY setup had a positive point
estimate and lower drawdown but failed fold-stability, uncertainty, cost-stress
and paired-control gates; SELL was negative in every fold. No model or runtime
behavior was created. The engineering baseline is running, but the research
program and profitable-edge objective are not complete.

The next research step is an upstream event-first candidate universe with
unique structural event identity and richer causal SMC geometry. It must be
registered before outcome comparison and beat simple fixed-rule baselines
before further ML is considered.

See [CLAUDE.md](CLAUDE.md) for architecture, data contracts, operational status
and the research roadmap. The skeptical-review response and implemented
decisions are in
[RESEARCH_REVIEW_ACTIONS_2026-07-19.md](RESEARCH_REVIEW_ACTIONS_2026-07-19.md).

The current paper-research runtime uses account-free Dukascopy XAUUSD bid/ask
candles and fails closed on invalid multi-timeframe cadence, source identity,
quote integrity or freshness. TradingView MCP is retained only as an
interactive/legacy research integration after its automated timeframe payloads
failed validation.

Historical dataset replay and forward-evidence export live under `research/`.
They preserve candidate-time features separately from later paper outcomes so
model development can be audited without look-ahead leakage.
