#!/usr/bin/env python3
"""Derive the runtime macro snapshot from the already-collected gold-context
snapshot so the Claude reviewer receives point-in-time DXY / real-yield-proxy /
VIX context instead of always reporting 'macro unavailable'.

Sources (Dukascopy public proxies — the same feed as the context ledger):
  dxy_return_pct         <- dollar_idx analysis_close, 24x1H return
  vix_return_pct         <- volatility_idx analysis_close, 24x1H return
  real_yield_change_bps  <- treasury_bond CFD, 24x1H return, sign-flipped proxy
                            (bond price up => yield down).

Honesty note: real_yield_change_bps is derived from a NOMINAL long-bond CFD, not
TIPS, so it is a loose directional proxy, not a validated real-yield series. It
is used only as point-in-time context for the paper research reviewer; macro
thresholds remain unvalidated hypotheses. If the context snapshot is missing or
lacks an instrument, no macro snapshot is written, so the validator correctly
reports 'unavailable' rather than a fabricated value.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

from config import settings

LOOKBACK = 24  # 1H bars ~= 1 trading day


def _closes(inst):
    return [float(b["analysis_close"]) for b in inst.get("bars", []) if "analysis_close" in b]


def _ret_pct(closes, n=LOOKBACK):
    if len(closes) <= 1:
        return None
    n = min(n, len(closes) - 1)
    prev = closes[-1 - n]
    if prev == 0:
        return None
    return (closes[-1] / prev - 1.0) * 100.0


def main():
    ctx_path = settings.GOLD_CONTEXT_SNAPSHOT_PATH
    if not ctx_path.exists():
        print("context snapshot missing; macro snapshot not written")
        return 0
    try:
        ctx = json.loads(ctx_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"context snapshot unreadable ({exc}); macro snapshot not written")
        return 0

    inst = ctx.get("instruments", {})
    dxy = _ret_pct(_closes(inst.get("dollar_idx", {})))
    vix = _ret_pct(_closes(inst.get("volatility_idx", {})))
    bond_ret = _ret_pct(_closes(inst.get("treasury_bond", {})))
    if dxy is None or vix is None or bond_ret is None:
        print("insufficient context instruments; macro snapshot not written")
        return 0

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dxy_return_pct": round(dxy, 4),
        "real_yield_change_bps": round(-bond_ret * 10.0, 4),
        "vix_return_pct": round(vix, 4),
        "_source": "derived from gold_context_snapshot Dukascopy proxies",
        "_lookback_bars_1h": LOOKBACK,
        "_note": ("real_yield_change_bps is a nominal treasury_bond CFD proxy, "
                  "not TIPS; loose directional hypothesis only"),
    }

    path = settings.MACRO_SNAPSHOT_PATH
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(snapshot, handle)
        os.replace(tmp, str(path))
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print("macro snapshot written:", {k: snapshot[k] for k in
          ("dxy_return_pct", "real_yield_change_bps", "vix_return_pct")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
