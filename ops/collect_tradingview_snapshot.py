#!/usr/bin/env python3
"""Collect an atomic five-timeframe OANDA:XAUUSD snapshot through TV MCP CLI."""

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

MCP_ROOT = Path(os.getenv("TRADINGVIEW_MCP_ROOT", "/opt/tradingview-mcp"))
OUTPUT = Path(os.getenv("TRADINGVIEW_SNAPSHOT_PATH", "/tmp/tradingview_snapshot.json"))
TV = ["node", str(MCP_ROOT / "src/cli/index.js")]
SYMBOL = "OANDA:XAUUSD"
TIMEFRAMES = {"1W": "W", "1D": "D", "4H": "240", "1H": "60", "15M": "15"}


def call(*args):
    result = subprocess.run(TV + list(args), cwd=MCP_ROOT, text=True,
                            capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    payload = json.loads(result.stdout)
    if not payload.get("success"):
        raise RuntimeError(payload.get("error", f"tv {' '.join(args)} failed"))
    return payload


def validate_bars(bars, name):
    if len(bars) < 200:
        raise ValueError(f"{name}: only {len(bars)} bars")
    times = [int(bar["time"]) for bar in bars]
    if times != sorted(set(times)):
        raise ValueError(f"{name}: timestamps are not unique and increasing")
    for bar in bars:
        values = [float(bar[key]) for key in ("open", "high", "low", "close")]
        if min(values) <= 0 or float(bar["high"]) < float(bar["low"]):
            raise ValueError(f"{name}: malformed OHLC bar")


def main():
    call("symbol", SYMBOL)
    time.sleep(3)
    frames = {}
    for name, tv_resolution in TIMEFRAMES.items():
        call("timeframe", tv_resolution)
        time.sleep(3)
        state = call("state")
        if state.get("symbol") != SYMBOL or str(state.get("resolution")) != tv_resolution:
            raise ValueError(f"chart state mismatch for {name}: {state}")
        data = call("ohlcv", "--count", "200")
        validate_bars(data["bars"], name)
        frames[name] = {"resolution": name, "tradingview_resolution": tv_resolution,
                        "bars": data["bars"], "bar_count": len(data["bars"])}

    quote = call("quote", SYMBOL)
    snapshot = {"schema_version": 1, "provider": "tradingview-mcp",
                "symbol": SYMBOL, "captured_at": datetime.now(timezone.utc).isoformat(),
                "quote": quote, "timeframes": frames}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=OUTPUT.name + ".", dir=OUTPUT.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(snapshot, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, OUTPUT)
        os.chmod(OUTPUT, 0o644)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


if __name__ == "__main__":
    main()
