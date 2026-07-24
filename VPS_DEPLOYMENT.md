# Canonical VPS Deployment

The only active deployment is `187.55.229.4` in
`/root/gold_signal_fetcher_ai_assisted`. The former host must remain inactive.

## Runtime

- Dashboard backend: `gold-signal-fetcher.service`, loopback
  `127.0.0.1:8510`.
- Public boundary: nginx on HTTPS `443`, trusted short-lived Let's Encrypt IP
  certificate, HTTP Basic authentication and request limiting.
- Certificate renewal: `gold-signal-cert-renew.timer`, twice daily.
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

The stable user-facing address is `http://187.55.229.4:8502/`. Authentication
is required. HTTPS remains available at `https://187.55.229.4/`.
The credential is deliberately stored outside Git:

- VPS: `/root/gold-signal-dashboard-credentials.txt`, mode `0600`;
- operator workstation: `~/gold_signal_dashboard_credentials.txt`, mode
  `0600`.

Flask listens only on `127.0.0.1:8510`; nginx is the sole public dashboard
boundary. Public port `8502` is the stable authenticated HTTP endpoint. Port
`80` serves ACME challenges and redirects all other traffic to HTTPS. The
checked-in nginx configuration is
`ops/nginx/gold-signal-fetcher.conf`.

The IP certificate is a short-lived certificate. The renewal timer must remain
enabled and its next run and certificate expiry must be monitored.

## First-time TLS/authentication installation

Install nginx, the password utility and a current Certbot in its own virtual
environment. The Certbot release must support short-lived IP certificates.

```bash
apt-get update
apt-get install -y nginx apache2-utils python3-venv
python3 -m venv /opt/certbot
/opt/certbot/bin/pip install 'certbot>=5.4,<6'
install -d -m 0755 /var/www/letsencrypt/.well-known/acme-challenge
```

Create `/etc/nginx/gold-signal-fetcher.htpasswd` for user `goldresearch` and
save the generated password only in the root-owned credential file. The nginx
worker needs read access to the bcrypt hash file, but never to the plaintext
credential:

```bash
chown root:www-data /etc/nginx/gold-signal-fetcher.htpasswd
chmod 0640 /etc/nginx/gold-signal-fetcher.htpasswd
chmod 0600 /root/gold-signal-dashboard-credentials.txt
```

Start nginx with a temporary port-80 ACME webroot server, then request the
certificate:

```bash
/opt/certbot/bin/certbot certonly \
  --webroot --webroot-path /var/www/letsencrypt \
  --preferred-profile shortlived \
  --ip-address 187.55.229.4 \
  --cert-name 187.55.229.4 \
  --register-unsafely-without-email --agree-tos --non-interactive
```

After issuance, install and validate the versioned boundary and renewal units:

```bash
install -m 0644 ops/nginx/gold-signal-fetcher.conf \
  /etc/nginx/conf.d/gold-signal-fetcher.conf
rm /etc/nginx/conf.d/gold-signal-bootstrap.conf
install -m 0644 ops/systemd/gold-signal-cert-renew.service \
  /etc/systemd/system/gold-signal-cert-renew.service
install -m 0644 ops/systemd/gold-signal-cert-renew.timer \
  /etc/systemd/system/gold-signal-cert-renew.timer
nginx -t
systemctl daemon-reload
systemctl enable --now nginx gold-signal-cert-renew.timer
```

## Deploy

```bash
cd /root/gold_signal_fetcher_ai_assisted
git pull --ff-only
venv/bin/pip install -r requirements.txt
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
nginx -t
systemctl reload nginx
```

Do not overwrite `.env`, `data/`, `logs/`, the TradingView profile, or the
paper ledger during deployment.

## Verify

```bash
systemctl is-active gold-signal-fetcher.service
systemctl is-active nginx
systemctl is-enabled gold-signal-cert-renew.timer
systemctl list-timers gold-signal-cert-renew.timer --no-pager
ss -lntp | grep -E ':(8502)[[:space:]]'
crontab -l
curl -fsS http://127.0.0.1:8510/ >/dev/null
curl -sS -o /dev/null -w '%{http_code}\n' http://187.55.229.4:8502/
curl -sS -o /dev/null -w '%{http_code}\n' https://187.55.229.4/
/opt/certbot/bin/certbot certificates
tail -50 logs/gold_scanner_ai.log
```

Expected: the backend is bound only to `127.0.0.1:8510`, unauthenticated public
port `8502` returns `401`, valid credentials return `200`, the certificate
verifies without `-k`, and scanner cron remains present. The dashboard feed panel should be
HEALTHY with five cadence and bid/ask checks passing. During the weekend, the
latest bar may be old while the panel correctly reports market CLOSED. The
feature-concordance panel must begin as AWAITING/COLLECTING, never PASS before
its 120-decision, 30-event, direction and event-type coverage gates.

## Telegram

`TELEGRAM_BOT_TOKEN` (legacy `TELEGRAM_TOKEN` is accepted) and
`TELEGRAM_CHAT_ID` remain in `.env`. Approved paper candidates are announced
with BUY/SELL geometry and an explicit paper-only warning. Unified metrics use
`send_daily_metrics.py`. Telegram never executes trades.

## Rollback

Revert only to a known tested git revision, rerun tests, reinstall the
collector, and restart the dashboard. Keep the TLS/authentication boundary in
place during application rollback. Keep the scanner paused if snapshot, ledger,
model metadata, or paper-mode checks fail.
