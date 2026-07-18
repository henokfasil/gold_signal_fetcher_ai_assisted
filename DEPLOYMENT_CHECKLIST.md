# Gold Paper-Research Deployment Checklist

Status: engineering-verified paper research; no validated ML model, no proven
edge and no broker execution.

## Before deployment

- [ ] `PAPER_TRADING=true` remains set.
- [ ] `PRICE_DATA_PROVIDER=dukascopy` is set without changing secrets.
- [ ] `/tmp/dukascopy_snapshot.json` is produced atomically by the canonical
  collector.
- [ ] `config/research_variants.json` SHA-256 matches the hard-coded forward
  contract hash.
- [ ] Existing `data/`, logs, `.env` and paper ledgers are preserved.
- [ ] No failed or synthetic ML artifact exists in `models/`.

## Verification

```bash
venv/bin/python -m compileall -q agent config main_orchestrator.py dashboard.py research ops
venv/bin/python -m unittest discover -s tests -v
venv/bin/python validate_code.py
venv/bin/python ops/collect_dukascopy_snapshot.py
```

- [ ] All tests pass.
- [ ] The collector reports 200 bars for 1W, 1D, 4H, 1H and 15M.
- [ ] Dashboard reports exact `dukascopy-public` / `DUKASCOPY:XAUUSD`.
- [ ] Cadence, ordering, uniqueness, midpoint OHLC and bid/ask checks pass.
- [ ] Dashboard remains paper-only and does not claim validation or profit.
- [ ] Cron uses a non-overlapping lock and aborts if collection fails.
- [ ] Telegram can announce only an approved paper signal; unavailable ML is a
  veto, so the currently rejected model cannot generate an approval.

## Research acceptance is separate

Engineering deployment does not authorize live capital. ML promotion requires
a registered simple-baseline comparison, chronological purged evaluation,
calibration, dependence-aware positive after-cost lower confidence bound,
frozen artifacts and later forward evidence. BUY and SELL qualify separately.
