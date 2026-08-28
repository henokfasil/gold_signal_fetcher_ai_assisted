"""
Backtest of the Growth Club / Kabeer management model on v4 SMC candidates.

Kabeer's described method (from growthclubpk.com):
  - XAU/USD only, London & New York sessions
  - 3 take-profit levels, scale out in thirds
  - Move SL to breakeven after TP1
Instantiated here as TP1=1R, TP2=2R, TP3=3R (R = entry->SL distance).

Executable sides (repo methodology):
  BUY  enters at ask, exits/tests barriers on bid
  SELL enters at bid, exits/tests barriers on ask
Conservative: within a single bar, adverse (SL/BE) is assumed to trigger
BEFORE favorable (TP). Slippage 0.10 pt per fill. Spread is baked in via sides.

Reports R-multiples (1R = full-position initial risk), BUY/SELL separately,
with and without the session filter, vs a single-TP baseline on the same bars.
"""
import csv, json, bisect
from datetime import datetime, timezone

RAW = "data/raw/dukascopy_xauusd_15m_2020_2026.csv"
CAND = "data/research/xauusd_smc_candidates_v4.csv"
EXPIRY_BARS = 192          # 48h of 15m bars
SLIP = 0.10                # points slippage per fill
SESSION_HOURS = set(range(7, 21))   # London+NY union, 07:00-20:59 UTC entries

def parse_ts(s):
    return datetime.fromisoformat(s.replace("T", " ")).timestamp()

# ---- load raw bars into parallel arrays ----
ts=[]; bh=[]; bl=[]; ah=[]; al=[]; bc=[]; ac=[]
with open(RAW) as f:
    r=csv.DictReader(f)
    for row in r:
        ts.append(parse_ts(row["timestamp"]))
        bh.append(float(row["bid_high"])); bl.append(float(row["bid_low"]))
        ah.append(float(row["ask_high"])); al.append(float(row["ask_low"]))
        bc.append(float(row["bid_close"])); ac.append(float(row["ask_close"]))
N=len(ts)
print(f"loaded {N} raw bars")

def sim_candidate(entry, sl, direction, start_i):
    """Return dict of R-contributions for the Kabeer 3-TP/BE model."""
    Rdist = abs(entry - sl)
    if Rdist <= 0: return None
    if direction == "BUY":
        tp1, tp2, tp3 = entry+1*Rdist, entry+2*Rdist, entry+3*Rdist
    else:
        tp1, tp2, tp3 = entry-1*Rdist, entry-2*Rdist, entry-3*Rdist
    stop = sl
    units_open = [True, True, True]        # unit0->tp1, unit1->tp2, unit2->tp3
    realized = 0.0                          # in R (each unit is 1/3 position)
    tp1_hit = False
    def unit_R(exit_px):
        # signed R-distance moved, times 1/3 position
        move = (exit_px-entry) if direction=="BUY" else (entry-exit_px)
        return (move/Rdist)/3.0
    end = min(start_i+EXPIRY_BARS, N)
    for i in range(start_i, end):
        if direction=="BUY":
            hi_fav, lo_adv = bh[i], bl[i]      # close on bid
        else:
            hi_fav, lo_adv = al[i], ah[i]      # close on ask (fav=low, adv=high)
        # ADVERSE FIRST (conservative): check stop for all still-open units
        if direction=="BUY":
            stop_hit = lo_adv <= stop
        else:
            stop_hit = hi_fav >= stop if False else ah[i] >= stop
        # recompute cleanly per direction
        if direction=="BUY":
            stop_hit = bl[i] <= stop
            tp1ok = bh[i] >= tp1; tp2ok = bh[i] >= tp2; tp3ok = bh[i] >= tp3
        else:
            stop_hit = ah[i] >= stop
            tp1ok = al[i] <= tp1; tp2ok = al[i] <= tp2; tp3ok = al[i] <= tp3
        if stop_hit:
            # every still-open unit exits at stop (BE if tp1_hit else initial SL)
            exit_px = stop - (SLIP if direction=="BUY" else -SLIP)
            for u in range(3):
                if units_open[u]:
                    realized += unit_R(exit_px); units_open[u]=False
            return {"R":realized,"tp1":tp1_hit,"closed":"STOP" if not tp1_hit else "BE"}
        # favorable fills (after confirming no stop this bar)
        if units_open[0] and tp1ok:
            realized += unit_R(tp1 - (SLIP if direction=="BUY" else -SLIP)); units_open[0]=False
            tp1_hit=True; stop=entry     # move to breakeven
        if units_open[1] and tp2ok:
            realized += unit_R(tp2 - (SLIP if direction=="BUY" else -SLIP)); units_open[1]=False
        if units_open[2] and tp3ok:
            realized += unit_R(tp3 - (SLIP if direction=="BUY" else -SLIP)); units_open[2]=False
        if not any(units_open):
            return {"R":realized,"tp1":True,"closed":"TP3"}
    # expiry: close remaining at last executable close
    j=end-1
    exit_px = bc[j] if direction=="BUY" else ac[j]
    for u in range(3):
        if units_open[u]:
            realized += unit_R(exit_px); units_open[u]=False
    return {"R":realized,"tp1":tp1_hit,"closed":"EXPIRY"}

def sim_baseline(entry, sl, tp, direction, start_i):
    """Single full-position TP/SL (repo style), same bars, R terms."""
    Rdist=abs(entry-sl)
    if Rdist<=0: return None
    end=min(start_i+EXPIRY_BARS,N)
    for i in range(start_i,end):
        if direction=="BUY":
            if bl[i]<=sl: return (-(entry-sl)-SLIP)/Rdist   # ~ -1R
            if bh[i]>=tp: return ((tp-entry)-SLIP)/Rdist
        else:
            if ah[i]>=sl: return (-(sl-entry)-SLIP)/Rdist
            if al[i]<=tp: return ((entry-tp)-SLIP)/Rdist
    j=end-1
    exit_px=bc[j] if direction=="BUY" else ac[j]
    move=(exit_px-entry) if direction=="BUY" else (entry-exit_px)
    return (move-SLIP)/Rdist

# ---- run over candidates ----
def agg():
    return {"n":0,"R":0.0,"wins":0,"loss":0,"be":0,"tp3":0,"stop":0,"expiry":0}
buckets={}   # (model, side, session) -> agg
def add(key, r, closed=None, is_baseline=False):
    a=buckets.setdefault(key,agg())
    a["n"]+=1; a["R"]+=r
    if r>0.001: a["wins"]+=1
    elif r<-0.001: a["loss"]+=1
    else: a["be"]+=1
    if closed=="TP3": a["tp3"]+=1
    if closed=="STOP": a["stop"]+=1
    if closed=="BE": a["be_stop"]=a.get("be_stop",0)+1
    if closed=="EXPIRY": a["expiry"]+=1

with open(CAND) as f:
    rows=list(csv.DictReader(f))
done=0; skipped=0
for row in rows:
    try:
        entry=float(row["entry"]); sl=float(row["stop_loss"]); tp=float(row["take_profit"])
        direction=row["direction"]
        cts=parse_ts(row["timestamp"])
    except: skipped+=1; continue
    si=bisect.bisect_right(ts, cts)
    if si>=N: skipped+=1; continue
    hour=datetime.fromtimestamp(cts,tz=timezone.utc).hour
    in_sess = hour in SESSION_HOURS
    k=sim_candidate(entry,sl,direction,si)
    b=sim_baseline(entry,sl,tp,direction,si)
    if k is None or b is None: skipped+=1; continue
    add(("KABEER",direction,"ALL"), k["R"], k["closed"])
    add(("BASE",direction,"ALL"), b)
    if in_sess:
        add(("KABEER",direction,"SESS"), k["R"], k["closed"])
        add(("BASE",direction,"SESS"), b)
    done+=1
print(f"simulated {done}, skipped {skipped}")

def show(model,session):
    print(f"\n===== {model}  (session={session}) =====")
    for side in ("BUY","SELL"):
        a=buckets.get((model,side,session))
        if not a or a["n"]==0: continue
        n=a["n"]; R=a["R"]
        wr=100*a["wins"]/n
        exp=R/n
        line=(f"{side}: n={n:5d}  totalR={R:8.1f}  expR/trade={exp:+.3f}  "
              f"winrate={wr:4.1f}%  wins={a['wins']} be={a['be']} loss={a['loss']}")
        if model=="KABEER":
            line+=f"  [TP3={a['tp3']} BEstop={a.get('be_stop',0)} fullSL={a['stop']} exp={a['expiry']}]"
        print(line)
    # combined
    ca=agg()
    for side in ("BUY","SELL"):
        a=buckets.get((model,side,session))
        if a:
            for kk in ("n","R","wins","loss","be"): ca[kk]+=a[kk]
    if ca["n"]:
        print(f"BOTH: n={ca['n']} totalR={ca['R']:.1f} expR/trade={ca['R']/ca['n']:+.3f} winrate={100*ca['wins']/ca['n']:.1f}%")

for m in ("BASE","KABEER"):
    for s in ("ALL","SESS"):
        show(m,s)

json.dump({str(k):v for k,v in buckets.items()}, open("data/research/sim_kabeer_management_result.json","w"), indent=2)
print("\nwrote data/research/sim_kabeer_management_result.json")
