# Gold Signal Fetcher — AI-Assisted Research System

Paper-trading research pipeline combining directional BUY/SELL SMC candidates, validated
historical-data ML inference, point-in-time macro context and a conservative
Claude review.

This repository does not execute broker orders and does not currently claim a
profitable edge. Missing ML or Claude evidence causes a candidate to be logged
as rejected rather than approved with fabricated fallback confidence.

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
