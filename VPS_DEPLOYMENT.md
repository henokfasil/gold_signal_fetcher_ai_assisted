# Canonical VPS Deployment

The only active deployment is `187.55.229.4` in
`/root/gold_signal_fetcher_ai_assisted`. The former host must remain inactive.

## Runtime

- Dashboard: `gold-signal-fetcher.service`, port `8502`.
- TradingView display: `tradingview-display.service`.
- TradingView Desktop: `tradingview-session.service` under `tvfetcher`.
- CDP: `127.0.0.1:9222` only.
- VNC: maintenance only, disabled and normally stopped.
- Paper scan: `ops/run_gold_scanner_ai.sh` at minutes 5/20/35/50.
- Price source: TradingView MCP, exact `OANDA:XAUUSD`.
- Snapshot: `/tmp/tradingview_snapshot.json`, 200 bars each for W/D/4H/1H/15M.

The locked wrapper collects and validates a fresh atomic snapshot before every
scan. Collection failure aborts the scan. `PAPER_TRADING=true` is forced by the
wrapper and no broker execution method exists.

## Deploy

```bash
cd /root/gold_signal_fetcher_ai_assisted
git pull --ff-only
venv/bin/python -m unittest discover -s tests -v
venv/bin/python validate_code.py
install -m 0755 ops/collect_tradingview_snapshot.py \
  /usr/local/lib/gold-signal-fetcher/collect_tradingview_snapshot.py
systemctl restart gold-signal-fetcher.service
```

Do not overwrite `.env`, `data/`, `logs/`, the TradingView profile, or the
paper ledger during deployment.

## Verify

```bash
systemctl is-active gold-signal-fetcher.service \
  tradingview-display.service tradingview-session.service
ss -lntp | grep -E ':(8502|9222)[[:space:]]'
crontab -l
curl -fsS http://127.0.0.1:8502/ >/dev/null
tail -50 logs/gold_scanner_ai.log
```

Expected: dashboard HTTP 200, CDP on localhost only, VNC absent, scanner cron
present, and the dashboard feed panel HEALTHY.

## Telegram

`TELEGRAM_BOT_TOKEN` (legacy `TELEGRAM_TOKEN` is accepted) and
`TELEGRAM_CHAT_ID` remain in `.env`. Approved paper candidates are announced
with BUY/SELL geometry and an explicit paper-only warning. Unified metrics use
`send_daily_metrics.py`. Telegram never executes trades.

## Rollback

Revert only to a known tested git revision, rerun tests, reinstall the
collector, and restart the dashboard. Keep the scanner paused if snapshot,
ledger, model metadata, or paper-mode checks fail.
