"""Rigorous multi-strategy search on 2020-2026 gold with anti-overfitting stats.

Pipeline (advisor-grade):
  1. Strategy zoo: 7 entry families x R:R grid x {both/long/short} ~ 84 configs.
  2. Backtest each on 15M bid/ask with executable sides, 0.10pt slippage,
     adverse-first same-bar, 48h expiry, one-open-per-config (no pyramiding).
  3. In-sample (2020 -> 2025) selection vs out-of-sample (2025 -> 2026) validation.
  4. Bootstrap Monte-Carlo: 2000 resamples -> 95% CI on expectancy + one-sided
     p-value for H0: expectancy <= 0.
  5. Benjamini-Hochberg FDR (q=0.10) across all configs' in-sample p-values to
     correct for data mining (testing 84 rules inflates false positives).
  6. Survivor = FDR-significant IN-SAMPLE *and* positive OUT-OF-SAMPLE (n>=30).
  7. Monte-Carlo drawdown for the best config.
Positive-looking rules that fail OOS or FDR are data-mining artifacts, reported
as such. This does not pre-assume any rule works.
"""
import numpy as np
import pandas as pd

RAW = "data/raw/dukascopy_xauusd_15m_2020_2026.csv"
SLIP = 0.10
EXPIRY = 192
OOS_START = np.datetime64("2025-01-01")
B = 2000
rng = np.random.default_rng(42)

def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def rma(s, n): return s.ewm(alpha=1/n, adjust=False).mean()
def rsi(c, n=14):
    d = c.diff(); up = rma(d.clip(lower=0), n); dn = rma(-d.clip(upper=0), n)
    return (100 - 100/(1+up/dn.replace(0, np.nan))).fillna(50)
def atr(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return rma(tr, n)

print("loading 15M...")
raw = pd.read_csv(RAW, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
H = raw[["open","high","low","close"]].resample("1h").agg(
    {"open":"first","high":"max","low":"min","close":"last"}).dropna()
c, hi, lo = H["close"], H["high"], H["low"]
e20, e50, e200 = ema(c,20), ema(c,50), ema(c,200)
r = rsi(c,14); a = atr(hi,lo,c,14)
sma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
bbu, bbl = sma20+2*sd20, sma20-2*sd20
macd = ema(c,12)-ema(c,26); msig = ema(macd,9)
don_hi = hi.rolling(20).max().shift(1); don_lo = lo.rolling(20).min().shift(1)
# supertrend (mult=3)
hl2 = (hi+lo)/2; ub = hl2+3*a; lb = hl2-3*a
st_dir = np.ones(len(H)); ubv, lbv = ub.to_numpy(), lb.to_numpy(); cv = c.to_numpy()
fu, fl = ubv.copy(), lbv.copy()
for i in range(1, len(H)):
    fu[i] = ubv[i] if (ubv[i]<fu[i-1] or cv[i-1]>fu[i-1]) else fu[i-1]
    fl[i] = lbv[i] if (lbv[i]>fl[i-1] or cv[i-1]<fl[i-1]) else fl[i-1]
    st_dir[i] = 1 if cv[i]>fu[i-1] else (-1 if cv[i]<fl[i-1] else st_dir[i-1])
st = pd.Series(st_dir, index=H.index)

def col(s): return s.to_numpy()
C, HIx, LOx = col(c), col(hi), col(lo)
E20, E50, E200 = col(e20), col(e50), col(e200)
R_, A = col(r), col(a); BBU, BBL = col(bbu), col(bbl)
MA, MS = col(macd), col(msig); DHI, DLO = col(don_hi), col(don_lo)
ST = st_dir; n1 = len(H)

# ---- family signal arrays: +1 BUY, -1 SELL, 0 none (per 1H bar) ----
def fam_signals():
    fam = {}
    s = np.zeros(n1)
    up = E50>E200; dn = E50<E200
    for i in range(1,n1):
        if up[i] and LOx[i-1]<=E50[i-1] and C[i]>E50[i]: s[i]=1
        elif dn[i] and HIx[i-1]>=E50[i-1] and C[i]<E50[i]: s[i]=-1
    fam["ema_trend"]=s.copy()
    s=np.zeros(n1)
    for i in range(1,n1):
        if C[i]>DHI[i]: s[i]=1
        elif C[i]<DLO[i]: s[i]=-1
    fam["donchian_breakout"]=s.copy()
    s=np.where(C<BBL,1,np.where(C>BBU,-1,0)).astype(float); fam["bollinger_fade"]=s.copy()
    s=np.where(C>BBU,1,np.where(C<BBL,-1,0)).astype(float); fam["bollinger_breakout"]=s.copy()
    s=np.where((R_<30)&(C<E20-A),1,np.where((R_>70)&(C>E20+A),-1,0)).astype(float)
    fam["rsi_meanrev"]=s.copy()
    s=np.zeros(n1); up=E50>E200; dn=E50<E200
    for i in range(1,n1):
        if up[i] and MA[i-1]<=MS[i-1] and MA[i]>MS[i]: s[i]=1
        elif dn[i] and MA[i-1]>=MS[i-1] and MA[i]<MS[i]: s[i]=-1
    fam["macd_momentum"]=s.copy()
    s=np.zeros(n1)
    for i in range(1,n1):
        if ST[i]==1 and ST[i-1]==-1: s[i]=1
        elif ST[i]==-1 and ST[i-1]==1: s[i]=-1
    fam["supertrend"]=s.copy()
    return fam

FAM = fam_signals()
print("families:", list(FAM))

# ---- 15M sim arrays ----
ts15 = raw.index.astype("int64").to_numpy()
bh,bl2 = raw["bid_high"].to_numpy(), raw["bid_low"].to_numpy()
ah,al = raw["ask_high"].to_numpy(), raw["ask_low"].to_numpy()
bc,ac = raw["bid_close"].to_numpy(), raw["ask_close"].to_numpy()
N=len(ts15); H_ts=H.index.astype("int64").to_numpy()
H_dt=H.index.values

def sim(entry,sl,tp,d,si):
    risk=abs(entry-sl)
    if risk<=0: return None,None
    end=min(si+EXPIRY,N)
    for i in range(si,end):
        if d==1:
            if bl2[i]<=sl: return (-(entry-sl)-SLIP)/risk,i
            if bh[i]>=tp: return ((tp-entry)-SLIP)/risk,i
        else:
            if ah[i]>=sl: return (-(sl-entry)-SLIP)/risk,i
            if al[i]<=tp: return ((entry-tp)-SLIP)/risk,i
    j=end-1; px=bc[j] if d==1 else ac[j]
    mv=(px-entry) if d==1 else (entry-px)
    return (mv-SLIP)/risk,j

def run(sig, rr, slm, dirf):
    trades=[]; busy=-1
    for k in range(1,n1):
        if H_ts[k]<=busy: continue
        d=sig[k]
        if d==0: continue
        if dirf=="long" and d<0: continue
        if dirf=="short" and d>0: continue
        entry=C[k]; av=A[k]
        if av<=0 or np.isnan(av): continue
        if d==1: sl=entry-slm*av; tp=entry+rr*slm*av
        else: sl=entry+slm*av; tp=entry-rr*slm*av
        si=int(np.searchsorted(ts15,H_ts[k],side="right"))
        if si>=N: continue
        R,ei=sim(entry,sl,tp,int(d),si)
        if R is None: continue
        trades.append((H_dt[k],R)); busy=int(ts15[ei])
    return trades

def boot_p_ci(Rs):
    Rs=np.asarray(Rs)
    if len(Rs)<10: return (np.mean(Rs) if len(Rs) else 0.0), 1.0, (np.nan,np.nan)
    idx=rng.integers(0,len(Rs),size=(B,len(Rs)))
    means=Rs[idx].mean(axis=1)
    p=float((means<=0).mean())            # one-sided H0: mean<=0
    return float(Rs.mean()), p, (float(np.percentile(means,2.5)),float(np.percentile(means,97.5)))

def stat(trades):
    if not trades: return None
    dt=np.array([t for t,_ in trades]); Rs=np.array([x for _,x in trades])
    ism=dt<OOS_START; oos=~ism
    def blk(mask):
        rr=Rs[mask]; n=len(rr)
        if n==0: return dict(n=0)
        w=rr[rr>0]; l=rr[rr<=0]
        pf=(w.sum()/-l.sum()) if len(l) and l.sum()!=0 else float("inf")
        m,p,ci=boot_p_ci(rr)
        return dict(n=n,exp=m,pf=pf,wr=100*len(w)/n,p=p,lo=ci[0])
    return blk(ism),blk(oos),blk(np.ones(len(Rs),bool))

# ---- run zoo ----
RRS=[1.0,1.5,2.0,3.0]; DIRS=["both","long","short"]; SLM=1.5
configs=[]
for fname,sig in FAM.items():
    for rr in RRS:
        for dirf in DIRS:
            tr=run(sig,rr,SLM,dirf)
            st_=stat(tr)
            if st_ is None: continue
            IS,OO,ALL=st_
            configs.append(dict(name=f"{fname}|rr{rr}|{dirf}",fam=fname,rr=rr,dir=dirf,
                                IS=IS,OOS=OO,ALL=ALL))

# ---- BH-FDR on in-sample p-values ----
valid=[c for c in configs if c["IS"].get("n",0)>=30]
ps=sorted([(c["IS"]["p"],c) for c in valid], key=lambda x:x[0])
m=len(ps); q=0.10; fdr_sig=set()
for i,(p,c) in enumerate(ps,1):
    if p<= (i/m)*q:
        for j in range(i): fdr_sig.add(id(ps[j][1]))
for c in configs: c["fdr"]= id(c) in fdr_sig

# ---- report ----
configs.sort(key=lambda c: c["IS"].get("exp",-9), reverse=True)
print(f"\n{'config':34s} {'IS_n':>5} {'IS_exp':>7} {'IS_p':>6} {'IS_lo':>7} {'OOS_n':>5} {'OOS_exp':>7} {'OOS_pf':>6} FDR OOS+")
print("-"*104)
survivors=[]
for c in configs[:24]:
    IS,OO=c["IS"],c["OOS"]
    oos_pos = OO.get("n",0)>=30 and OO.get("exp",-9)>0
    surv = c["fdr"] and oos_pos
    if surv: survivors.append(c)
    print(f"{c['name']:34s} {IS['n']:5d} {IS['exp']:+7.3f} {IS['p']:6.3f} {IS['lo']:+7.3f} "
          f"{OO.get('n',0):5d} {OO.get('exp',0):+7.3f} {OO.get('pf',0):6.2f} "
          f"{'Y' if c['fdr'] else '.':>3} {'Y' if oos_pos else '.':>4}")

print(f"\nConfigs tested: {len(configs)} | passed n>=30 IS: {len(valid)} | "
      f"FDR-significant IS (q=0.10): {sum(c['fdr'] for c in configs)} | "
      f"SURVIVORS (FDR IS & positive OOS): {len(survivors)}")
if survivors:
    print("\n=== SURVIVORS -> paper candidates ===")
    for c in survivors:
        print(f"  {c['name']}: IS exp {c['IS']['exp']:+.3f} (lo {c['IS']['lo']:+.3f}), "
              f"OOS exp {c['OOS']['exp']:+.3f} pf {c['OOS']['pf']:.2f} n {c['OOS']['n']}")
    # ---- Monte-Carlo risk (Jesse-style): 1% fixed-fractional, bootstrap order ----
    def montecarlo(Rs, sims=5000, risk=0.01):
        Rs=np.asarray(Rs); dd=[]; fin=[]
        for _ in range(sims):
            seq=Rs[rng.integers(0,len(Rs),len(Rs))]
            eq=np.cumprod(1+risk*seq); peak=np.maximum.accumulate(eq)
            dd.append(((eq-peak)/peak).min()*100); fin.append((eq[-1]-1)*100)
        return np.median(dd), np.percentile(dd,5), np.median(fin), float((np.array(fin)>0).mean()*100)
    print(f"\n{'survivor':28s} {'n':>4} {'win%':>5} {'expR':>6} {'PF':>5} {'medDD%':>7} {'DD5%':>7} {'medRet%':>8} {'P(profit)':>9}")
    print("-"*92)
    for c in survivors:
        tr=run(FAM[c['fam']], c['rr'], SLM, c['dir'])
        Rs=np.array([x for _,x in tr]); wr=100*(Rs>0).mean()
        medDD,dd5,medRet,pprof=montecarlo(Rs)
        print(f"{c['name']:28s} {len(Rs):4d} {wr:5.1f} {Rs.mean():+6.3f} "
              f"{(Rs[Rs>0].sum()/-Rs[Rs<=0].sum()):5.2f} {medDD:7.1f} {dd5:7.1f} {medRet:8.1f} {pprof:8.1f}%")
    print("\n(1% fixed-fractional risk/trade; 1R=risk; bootstrap trade order, 5000 sims; full-sample R.)")
else:
    print("\nNO strategy survived out-of-sample after multiple-testing correction.")
    print("The best in-sample rules are data-mining artifacts: their edge vanishes")
    print("on 2025-2026 data they were not selected on. This is the honest result.")
