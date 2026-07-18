# Gold Signal Fetcher — AI-Assisted Research System

Paper-trading research pipeline combining directional BUY/SELL SMC candidates, validated
historical-data ML inference, point-in-time macro context and a conservative
Claude review.

This repository does not execute broker orders and does not currently claim a
profitable edge. Missing ML or Claude evidence causes a candidate to be logged
as rejected rather than approved with fabricated fallback confidence.

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
