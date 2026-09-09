"""Honest historical backtest of four candidate strategies on 2020-2026 gold.

All four share IDENTICAL fixed-R:R geometry (SL = 1.5*ATR, TP = 3.0*ATR = 1:2)
so we compare the ENTRY SIGNAL quality, not TP luck (this also sidesteps the
SMC 'next-swing TP' flaw). Signals are generated on 1H bars; each trade is then
simulated on 15M bid/ask bars with executable sides, adverse-first same-bar
resolution, 0.10pt slippage and a 48h expiry. One open position per strategy at
a time (no pyramiding), which is what the live per-strategy cooldown will do.

Strategies (distinct entry triggers):
  trend_following : EMA50/200 regime + pullback-and-resume through EMA50
  bollinger       : fade a close outside the 2-sigma Bollinger band
  mean_reversion  : RSI<30/>70 while stretched >1 ATR from EMA20
  momentum        : MACD cross in the direction of the EMA50/200 regime
"""
import numpy as np
import pandas as pd

RAW = "data/raw/dukascopy_xauusd_15m_2020_2026.csv"
ATR_SL = 1.5      # stop = 1.5 ATR
RR = 2.0          # fixed 1:2 -> TP = 3.0 ATR
SLIP = 0.10
EXPIRY_BARS = 192  # 48h of 15M bars

# ---------- indicators ----------
def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def rma(s, n): return s.ewm(alpha=1/n, adjust=False).mean()

def rsi(close, n=14):
    d = close.diff()
    up = rma(d.clip(lower=0), n)
    dn = rma(-d.clip(upper=0), n)
    rs = up / dn.replace(0, np.nan)
    return (100 - 100/(1+rs)).fillna(50)

def atr(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return rma(tr, n)

# ---------- load + 1H frame ----------
print("loading 15M...")
raw = pd.read_csv(RAW, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
h1 = raw[["open","high","low","close"]].resample("1h").agg(
    {"open":"first","high":"max","low":"min","close":"last"}).dropna()
c = h1["close"]
h1["ema20"], h1["ema50"], h1["ema200"] = ema(c,20), ema(c,50), ema(c,200)
h1["rsi"] = rsi(c,14)
h1["atr"] = atr(h1["high"], h1["low"], c, 14)
sma20 = c.rolling(20).mean(); sd20 = c.rolling(20).std()
h1["bb_up"], h1["bb_lo"] = sma20 + 2*sd20, sma20 - 2*sd20
macd = ema(c,12) - ema(c,26); sig = ema(macd,9)
h1["macd"], h1["macd_sig"] = macd, sig
h1 = h1.dropna()
print(f"1H bars: {len(h1)}  ({h1.index[0].date()} -> {h1.index[-1].date()})")

# ---------- signal triggers (return 'BUY'/'SELL'/None per row) ----------
def sig_trend(r, p):
    up = r.ema50 > r.ema200; dn = r.ema50 < r.ema200
    if up and p.low <= p.ema50 and r.close > r.ema50: return "BUY"
    if dn and p.high >= p.ema50 and r.close < r.ema50: return "SELL"
    return None

def sig_bollinger(r, p):
    if r.close < r.bb_lo: return "BUY"
    if r.close > r.bb_up: return "SELL"
    return None

def sig_meanrev(r, p):
    if r.rsi < 30 and r.close < r.ema20 - r.atr: return "BUY"
    if r.rsi > 70 and r.close > r.ema20 + r.atr: return "SELL"
    return None

def sig_momentum(r, p):
    up = r.ema50 > r.ema200; dn = r.ema50 < r.ema200
    if up and p.macd <= p.macd_sig and r.macd > r.macd_sig: return "BUY"
    if dn and p.macd >= p.macd_sig and r.macd < r.macd_sig: return "SELL"
    return None

STRATS = {"trend_following":sig_trend, "bollinger":sig_bollinger,
          "mean_reversion":sig_meanrev, "momentum":sig_momentum}

# ---------- 15M arrays for simulation ----------
ts15 = raw.index.astype("int64").to_numpy()
bh, bl = raw["bid_high"].to_numpy(), raw["bid_low"].to_numpy()
ah, al = raw["ask_high"].to_numpy(), raw["ask_low"].to_numpy()
bc, ac = raw["bid_close"].to_numpy(), raw["ask_close"].to_numpy()
N = len(ts15)

def simulate(entry, sl, tp, direction, start_i):
    """Return realized R (1R = entry->SL risk) and exit-timestamp index."""
    risk = abs(entry - sl)
    if risk <= 0: return None
    end = min(start_i + EXPIRY_BARS, N)
    for i in range(start_i, end):
        if direction == "BUY":
            if bl[i] <= sl: return (-(entry-sl)-SLIP)/risk, i
            if bh[i] >= tp: return ((tp-entry)-SLIP)/risk, i
        else:
            if ah[i] >= sl: return (-(sl-entry)-SLIP)/risk, i
            if al[i] <= tp: return ((entry-tp)-SLIP)/risk, i
    j = end-1
    px = bc[j] if direction=="BUY" else ac[j]
    move = (px-entry) if direction=="BUY" else (entry-px)
    return (move-SLIP)/risk, j

# ---------- run each strategy ----------
rows = h1.itertuples()
prev = None
h1_ts = h1.index.astype("int64").to_numpy()
recs = list(h1.itertuples(index=True))

results = {}
for name, trig in STRATS.items():
    trades = []
    busy_until_ts = -1
    for k in range(1, len(recs)):
        r, p = recs[k], recs[k-1]
        t_ns = h1_ts[k]
        if t_ns <= busy_until_ts:   # one open position per strategy
            continue
        d = trig(r, p)
        if not d: continue
        entry = float(r.close)
        a = float(r.atr)
        if a <= 0: continue
        if d == "BUY":
            sl = entry - ATR_SL*a; tp = entry + RR*ATR_SL*a
        else:
            sl = entry + ATR_SL*a; tp = entry - RR*ATR_SL*a
        si = int(np.searchsorted(ts15, t_ns, side="right"))
        if si >= N: continue
        out = simulate(entry, sl, tp, d, si)
        if out is None: continue
        R, exit_i = out
        trades.append((d, R))
        busy_until_ts = int(ts15[exit_i])
    results[name] = trades

# ---------- report ----------
def stats(trades):
    n = len(trades)
    if not n: return None
    Rs = [r for _, r in trades]
    wins = [r for r in Rs if r > 0]; losses = [r for r in Rs if r <= 0]
    totalR = sum(Rs)
    gw, gl = sum(wins), abs(sum(losses))
    return dict(n=n, buys=sum(1 for d,_ in trades if d=="BUY"),
        wr=100*len(wins)/n, avgW=(gw/len(wins) if wins else 0),
        avgL=(gl/len(losses) if losses else 0),
        pf=(gw/gl if gl else float("inf")), expR=totalR/n, totalR=totalR)

print("\n%-16s %6s %5s %6s %7s %7s %5s %7s %8s" %
      ("strategy","trades","buy%","win%","avgW_R","avgL_R","PF","exp_R","total_R"))
print("-"*78)
for name in STRATS:
    s = stats(results[name])
    if not s: print(f"{name:16s}  no trades"); continue
    print("%-16s %6d %5.0f %6.1f %7.2f %7.2f %5.2f %7.3f %8.1f" %
          (name, s["n"], 100*s["buys"]/s["n"], s["wr"], s["avgW"], -s["avgL"],
           s["pf"], s["expR"], s["totalR"]))
print("\nNote: per-candidate R (one-open-per-strategy). Positive exp_R = edge before "
      "portfolio effects; ~0 or negative = no edge. All share fixed 1:2 geometry.")
