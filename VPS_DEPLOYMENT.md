# Canonical VPS Deployment

The only active deployment is `187.55.229.4` in
`/root/gold_signal_fetcher_ai_assisted`. The former host must remain inactive.

## Runtime

- Dashboard: `gold-signal-fetcher.service`, port `8502`.
- TradingView desktop/MCP: installed but disabled/stopped; optional interactive
  legacy research only. Re-enable only for a deliberate maintenance session.
- CDP and maintenance VNC, if enabled, remain localhost-only.
- Paper scan: `ops/run_gold_scanner_ai.sh` at minutes 5/20/35/50.
- Outcome-blind event-feature replay: `ops/run_event_concordance_daily.sh`
  at 00:30 UTC Tuesday through Saturday, after each trading UTC day is
  complete. Weekend-only fetch windows are deliberately skipped.
- Price source: Dukascopy public feed, exact XAUUSD bid/ask.
- Snapshot: `/tmp/dukascopy_snapshot.json`, 200 complete bars each for
  1W/1D/4H/1H/15M.

The locked wrapper collects and validates a fresh atomic snapshot before every
scan. Collection failure aborts the scan. `PAPER_TRADING=true` is forced by the
wrapper and no broker execution method exists.

The two canonical root-crontab entries are:

```cron
5,20,35,50 * * * * /root/gold_signal_fetcher_ai_assisted/ops/run_gold_scanner_ai.sh
30 0 * * 2-6 /root/gold_signal_fetcher_ai_assisted/ops/run_event_concordance_daily.sh
```

## Dashboard address and bind

The user-facing address is always `http://187.55.229.4:8502/`. The Flask
process intentionally listens on `0.0.0.0:8502`; `0.0.0.0` is not a URL and
does not replace the public IP. It tells Linux to accept port 8502 connections
on all VPS interfaces, including the interface reached through
`187.55.229.4`. A `127.0.0.1:8502` bind would pass the local curl check but
would make the dashboard unavailable from the user's browser.

The current direct-IP HTTP endpoint is suitable for controlled paper-research
access, not a customer-facing production service. Add a domain, reverse proxy,
TLS/HTTPS, authentication and a restrictive firewall policy before commercial
exposure. Do not change the working application bind as a substitute for those
controls.

## Deploy

```bash
cd /root/gold_signal_fetcher_ai_assisted
git pull --ff-only
venv/bin/python -m unittest discover -s tests -v
venv/bin/python validate_code.py
install -m 0755 ops/collect_dukascopy_snapshot.py \
  /usr/local/lib/gold-signal-fetcher/collect_dukascopy_snapshot.py
# The daily concordance job writes delayed native-timeframe references to its
# append-only, content-addressed data archive.
# Preserve secrets and edit only these source selectors in .env:
# PRICE_DATA_PROVIDER=dukascopy
# DUKASCOPY_SNAPSHOT_PATH=/tmp/dukascopy_snapshot.json
systemctl restart gold-signal-fetcher.service
```

Do not overwrite `.env`, `data/`, `logs/`, the TradingView profile, or the
paper ledger during deployment.

## Verify

```bash
systemctl is-active gold-signal-fetcher.service
ss -lntp | grep -E ':(8502)[[:space:]]'
crontab -l
curl -fsS http://127.0.0.1:8502/ >/dev/null
tail -50 logs/gold_scanner_ai.log
```

Expected: dashboard HTTP 200, scanner cron present, and the dashboard feed
panel HEALTHY with five cadence and bid/ask checks passing. During the weekend,
the latest bar may be old while the panel correctly reports market CLOSED.
The feature-concordance panel must begin as AWAITING/COLLECTING, never PASS
before its 120-decision, 30-event, direction and event-type coverage gates.

## Telegram

`TELEGRAM_BOT_TOKEN` (legacy `TELEGRAM_TOKEN` is accepted) and
`TELEGRAM_CHAT_ID` remain in `.env`. Approved paper candidates are announced
with BUY/SELL geometry and an explicit paper-only warning. Unified metrics use
`send_daily_metrics.py`. Telegram never executes trades.

## Rollback

Revert only to a known tested git revision, rerun tests, reinstall the
collector, and restart the dashboard. Keep the scanner paused if snapshot,
ledger, model metadata, or paper-mode checks fail.
