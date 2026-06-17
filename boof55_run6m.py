"""
BOOF55 6-month backtest — Dec 2025 → Jun 2026
55A: gap-up days | 30m reclaim | 1H reclaim  (no RVOL)
55B: all days    | 30m + 1H    | RVOL > 1.5
TP=1%  SL=0.5%  Time=90 bars  First reclaim per level per day only
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
SYMBOLS  = ["TSLA","NVDA","AMD","HOOD","COIN","APP","MSFT","AMZN","META","PLTR","UPST","SMCI","MSTR","CRWD","AVGO"]
TP, SL, MAXB         = 0.010, 0.005, 90
TOUCH, BRK, RET      = 0.0025, 0.0030, 0.0025
CACHE                = "cache55_6m"

# ── load ──────────────────────────────────────────────────────────────────────
print("Loading 6m cache...")
data = {}
for sym in SYMBOLS:
    df = pd.read_parquet(f"{CACHE}/{sym}.parquet").tz_convert(ET)
    df = df.between_time("09:30","16:00").copy()
    df["hi30"] = df["high"].rolling(30).max().shift(1)
    df["hi60"] = df["high"].rolling(60).max().shift(1)
    df["rvol"]  = df["volume"] / df["volume"].rolling(20).mean()
    data[sym]  = df
DAYS = max(df.index.normalize().nunique() for df in data.values())
print(f"done — {DAYS} trading days\n")

# ── gap-up dates ──────────────────────────────────────────────────────────────
def gap_up_dates(df):
    gd    = set()
    dates = sorted(df.index.normalize().unique())
    for i in range(1, len(dates)):
        prev = df[df.index.normalize() == dates[i-1]]
        curr = df[df.index.normalize() == dates[i]]
        if prev.empty or curr.empty: continue
        if (curr["open"].iloc[0] - prev["close"].iloc[-1]) / prev["close"].iloc[-1] >= 0.001:
            gd.add(dates[i])
    return gd

# ── state machine ─────────────────────────────────────────────────────────────
def run_sm(df, level_col, gap_days=None, min_rvol=0.0):
    close = df["close"].values;  lo   = df["low"].values
    hi    = df["high"].values;   op   = df["open"].values
    rvol  = df["rvol"].values;   lvls = df[level_col].values
    dates = df.index.normalize();ts   = df.index;  n = len(df)

    trades   = []
    cur_date = None
    state    = "IDLE"
    fired    = False
    skip_to  = 0

    for i in range(n):
        d = dates[i]
        if d != cur_date:
            cur_date = d; state = "IDLE"; fired = False; skip_to = 0
            if gap_days is not None and d not in gap_days:
                skip_to = i + 999999
        if i < skip_to or fired: continue
        if min_rvol > 0 and (np.isnan(rvol[i]) or rvol[i] < min_rvol): continue
        lvl = lvls[i]
        if np.isnan(lvl) or lvl <= 0: continue
        dist = (close[i] - lvl) / lvl

        if   state == "IDLE":
            if abs(dist) <= TOUCH:               state = "TOUCH"
        elif state == "TOUCH":
            if   dist  >  BRK:                   state = "BREAK"
            elif abs(dist) > TOUCH * 4:          state = "IDLE"
        elif state == "BREAK":
            if abs(dist) <= RET:                 state = "RETEST"
        elif state == "RETEST":
            if dist > RET:
                ei = i + 1
                if ei < n:
                    entry = op[ei]; tp_p = entry*(1+TP); sl_p = entry*(1-SL)
                    result = "TIME"; pnl = 0; bars = MAXB
                    for j in range(ei, min(ei+MAXB, n)):
                        if lo[j] <= sl_p: result="SL"; pnl=-SL; bars=j-ei; break
                        if hi[j] >= tp_p: result="TP"; pnl= TP; bars=j-ei; break
                    else:
                        pnl = (close[min(ei+MAXB,n-1)] - entry) / entry
                    trades.append({
                        "sym": df.index.name or "", "date": str(ts[ei].date()),
                        "result": result, "pnl": pnl, "bars": bars,
                        "level": level_col
                    })
                    fired = True; skip_to = ei + bars
                state = "IDLE"
            elif abs(dist) > RET * 4:
                state = "IDLE"
    return trades

# ── metrics ───────────────────────────────────────────────────────────────────
def report(label, trades):
    if not trades:
        print(f"  {label:<28}  --"); return
    df  = pd.DataFrame(trades)
    n   = len(df)
    w   = (df["result"]=="TP").sum()
    l   = (df["result"]=="SL").sum()
    ti  = (df["result"]=="TIME").sum()
    wr  = w / n
    pf  = (w*TP)/(l*SL) if l else float("inf")
    ev  = df["pnl"].mean()
    ab  = df["bars"].mean()
    print(f"  {label:<28}  {n:>5}  {n/DAYS:>5.2f}/d  {wr*100:>5.1f}%  "
          f"{pf:>5.2f}  {ev*100:>+6.3f}%  {ab:>5.0f}b  {w}W/{l}L/{ti}T")

# ── run ───────────────────────────────────────────────────────────────────────
A30=[]; A1H=[]; B30=[]; B1H=[]
sym_stats = {}

for sym, df in data.items():
    df.index.name = sym
    gd = gap_up_dates(df)
    gap_pct = round(len(gd)/DAYS*100, 0)

    a30 = run_sm(df, "hi30", gap_days=gd)
    a1h = run_sm(df, "hi60", gap_days=gd)
    b30 = run_sm(df, "hi30", min_rvol=1.5)
    b1h = run_sm(df, "hi60", min_rvol=1.5)

    for t in a30: t["sym"]=sym; A30.append(t)
    for t in a1h: t["sym"]=sym; A1H.append(t)
    for t in b30: t["sym"]=sym; B30.append(t)
    for t in b1h: t["sym"]=sym; B1H.append(t)

    sym_stats[sym] = {"gap_days": len(gd), "gap_pct": gap_pct,
                      "A30": len(a30), "A1H": len(a1h)}
    print(f"  {sym:<6}  gap_days={len(gd)} ({gap_pct:.0f}%)  A30={len(a30)}  A1H={len(a1h)}  B30={len(b30)}  B1H={len(b1h)}", flush=True)

# ── report ────────────────────────────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"BOOF55  TP=1%  SL=0.5%  Hold=90bars  |  15 syms  {DAYS} days  Dec2025→Jun2026")
print(f"{'='*90}")
print(f"  {'Variant':<28}  {'N':>5}  {'T/d':>7}  {'WR':>6}  {'PF':>5}  {'EV':>7}  {'Hold':>5}  Outcomes")
print(f"  {'-'*85}")
print("55A — Gap-up days only:")
report("  30m reclaim", A30)
report("  1H  reclaim", A1H)
print("55B — RVOL > 1.5, all days:")
report("  30m reclaim", B30)
report("  1H  reclaim", B1H)

# per-symbol for best variant (55A 1H)
print(f"\nPer-symbol 55A 1H reclaim:")
print(f"  {'Sym':<6}  {'N':>4}  {'WR':>6}  {'EV':>8}  W/L/T")
print(f"  {'-'*45}")
for sym in SYMBOLS:
    t = [x for x in A1H if x["sym"]==sym]
    if not t: continue
    d  = pd.DataFrame(t)
    n  = len(d); w=(d.result=="TP").sum(); l=(d.result=="SL").sum(); ti=(d.result=="TIME").sum()
    wr = w/n; ev=d.pnl.mean()
    print(f"  {sym:<6}  {n:>4}  {wr*100:>5.1f}%  {ev*100:>+7.3f}%  {w}/{l}/{ti}")
