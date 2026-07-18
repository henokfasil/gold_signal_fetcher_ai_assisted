#!/usr/bin/env bash
set -euo pipefail

# TradingView Desktop uses xdg-open for its one-time browser authorization.
# The research VPS is intentionally browserless, so retain the URL briefly for
# the operator to open through their normal local browser. Never log the URL.
umask 077
printf '%s' "${1:?authorization URL required}" > /tmp/tradingview_auth_url
