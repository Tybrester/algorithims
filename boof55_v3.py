"""
BOOF55 Final — precomputed levels, no per-bar filtering
55A: gap-up days, 30m / 1H reclaim, no RVOL
55B: all days, 30m / 1H reclaim, RVOL > 1.5
55C: top movers only, 30m / 1H reclaim
"""
import pandas as pd
import numpy as np
import pytz, os

ET = pytz.timezone("America/New_York")

SYMBOLS  = ["TSLA","NVDA","AMD","HOOD","COIN","APP","MSFT","AMZN","META","PLTR","UPST","SMCI","MSTR","CRWD","AVGO"]
TP       = 0.010
SL       = 0.005
MAX_BARS = 90
TOUCH    = 0.0025
BREAK    = 0.0030
RETEST   = 0.0025

# ── load ──────────────────────────────────────────────────────────────────────
print("Loading cache...")
data = {}
for sym in SYMBOLS:
    df = pd.read_parquet(f"cache55/{sym}.parquet").tz_convert(ET)
    df = df.between_time("09:30","16:00").copy()
    data[sym] = df
print("done\n")

# ── precompute rolling levels ──────────────────────────────────────────────────
def add_levels(df):
    df = df.copy()
    df["rvol"]   = df["volume"] / df["volume"].rolling(20).mean()
    df["hi30"]   = df["high"].rolling(30).max().shift(1)   # 30m high (prior bars)
    df["hi60"]   = df["high"].rolling(60).max().shift(1)   # 1H high
    # PDH: prior day high — merge from daily
    dates        = df.index.normalize()
    daily_high   = df.groupby(dates)["high"].max()
    pdh_map      = daily_high.shift(1)                     # prior day high
    df["pdh"]    = dates.map(pdh_map)
    return df

# ── trade sim ─────────────────────────────────────────────────────────────────
def sim(df, ei):
    if ei >= len(df): return None
    entry    = df["open"].iloc[ei]
    tp_price = entry * (1 + TP)
    sl_price = entry * (1 - SL)
    end      = min(ei + MAX_BARS, len(df))
    for j in range(ei, end):
        lo = df["low"].iloc[j]; hi = df["high"].iloc[j]
        if lo <= sl_price: return {"result":"SL",  "pnl":-SL,  "bars":j-ei}
        if hi >= tp_price: return {"result":"TP",  "pnl": TP,  "bars":j-ei}
    ep = df["close"].iloc[end-1]
    return {"result":"TIME","pnl":(ep-entry)/entry,"bars":MAX_BARS}

# ── state machine per level column ────────────────────────────────────────────
def run(df, level_col, gap_up_dates=None, min_rvol=0.0):
    trades = []
    dates  = sorted(df.index.normalize().unique())
    for date in dates:
        if gap_up_dates is not None and date not in gap_up_dates:
            continue
        day   = df[df.index.normalize() == date].reset_index(drop=True)
        state = "IDLE"
        fired = False
        skip_until = 0
        for i in range(len(day)):
            if fired: break
            if i < skip_until: continue
            close = day["close"].iloc[i]
            rvol  = day["rvol"].iloc[i]
            if min_rvol > 0 and (np.isnan(rvol) or rvol < min_rvol):
                continue
            lvl = day[level_col].iloc[i]
            if not lvl or np.isnan(lvl) or lvl <= 0: continue
            dist = (close - lvl) / lvl
            if state == "IDLE":
                if abs(dist) <= TOUCH: state = "TOUCH"
            elif state == "TOUCH":
                if   dist >  BREAK:          state = "BREAK"
                elif abs(dist) > TOUCH * 4:  state = "IDLE"
            elif state == "BREAK":
                if abs(dist) <= RETEST:      state = "RETEST"
            elif state == "RETEST":
                if dist > RETEST:
                    # find global index for entry
                    gi = df.index.normalize() == date
                    gi_indices = df[gi].index
                    if i + 1 < len(gi_indices):
                        ei = df.index.get_loc(gi_indices[i + 1])
                        t  = sim(df, ei)
                        if t:
                            t["level"] = level_col
                            trades.append(t)
                            fired = True
                    state = "IDLE"
                elif abs(dist) > RETEST * 4:
                    state = "IDLE"
    return trades

# ── gap-up helper ─────────────────────────────────────────────────────────────
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

# ── run all ───────────────────────────────────────────────────────────────────
r = {k: [] for k in ["A30","A1H","B30","B1H","C30","C1H"]}
ranges = {}
DAYS = 51

print("Running strategies...")
for sym in SYMBOLS:
    df = add_levels(data[sym])
    rth = df.between_time("09:30","16:00")
    ranges[sym] = (rth["high"].max() - rth["low"].min()) / rth["open"].iloc[0] if len(rth) else 0
    gd = gap_up_dates(df)

    for t in run(df, "hi30", gap_up_dates=gd):             r["A30"].append(t)
    for t in run(df, "hi60", gap_up_dates=gd):             r["A1H"].append(t)
    for t in run(df, "hi30", min_rvol=1.5):                r["B30"].append(t)
    for t in run(df, "hi60", min_rvol=1.5):                r["B1H"].append(t)
    print(f"  {sym} done", flush=True)

top8 = sorted(ranges, key=ranges.get, reverse=True)[:8]
print(f"\nTop movers: {top8}")
for sym in top8:
    df = add_levels(data[sym])
    for t in run(df, "hi30"):  r["C30"].append(t)
    for t in run(df, "hi60"):  r["C1H"].append(t)

# ── report ────────────────────────────────────────────────────────────────────
def report(label, trades):
    if not trades:
        print(f"  {label:<22} NO TRADES"); return
    df  = pd.DataFrame(trades)
    n   = len(df)
    w   = (df["result"]=="TP").sum()
    l   = (df["result"]=="SL").sum()
    ti  = (df["result"]=="TIME").sum()
    wr  = w/n
    avg_w = TP;  avg_l = SL
    pf  = (w*avg_w)/(l*avg_l) if l else float("inf")
    ev  = df["pnl"].mean()
    ab  = df["bars"].mean()
    print(f"  {label:<22} {n:>4}  {n/DAYS:>4.1f}/d  {wr*100:>5.1f}%  {pf:>5.2f}  {ev*100:>+6.3f}%  {ab:>5.0f}b  {w}W {l}L {ti}T")

print(f"\n{'='*85}")
print(f"BOOF55  TP={TP*100:.0f}%  SL={SL*100:.1f}%  Hold={MAX_BARS}bars  |  15 syms  51 days")
print(f"{'='*85}")
print(f"  {'Variant':<22} {'N':>4}  {'T/d':>6}  {'WR':>6}  {'PF':>5}  {'EV':>7}  {'Hold':>6}  Outcomes")
print(f"  {'-'*80}")
print("55A — Gap-up days only:")
report("  30m reclaim", r["A30"])
report("  1H  reclaim", r["A1H"])
print("55B — RVOL > 1.5, all days:")
report("  30m reclaim", r["B30"])
report("  1H  reclaim", r["B1H"])
print("55C — Top 8 movers, all days:")
report("  30m reclaim", r["C30"])
report("  1H  reclaim", r["C1H"])
