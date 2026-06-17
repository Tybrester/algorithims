"""
BOOF55 A/B/C — fast numpy state machine, loads from parquet cache
55A: gap-up days | 30m high reclaim | 1H high reclaim  (no RVOL)
55B: all days    | 30m + 1H         | RVOL > 1.5
55C: top movers  | 30m + 1H         | no extra filter
TP=1%  SL=0.5%  Time=90 bars
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
SYMBOLS  = ["TSLA","NVDA","AMD","HOOD","COIN","APP","MSFT","AMZN","META","PLTR","UPST","SMCI","MSTR","CRWD","AVGO"]
TP, SL, MAXB = 0.010, 0.005, 90
TOUCH, BRK, RET = 0.0025, 0.0030, 0.0025
DAYS = 51

# ── load ──────────────────────────────────────────────────────────────────────
print("Loading...")
data = {}
for sym in SYMBOLS:
    df = pd.read_parquet(f"cache55/{sym}.parquet").tz_convert(ET)
    df = df.between_time("09:30","16:00").copy()
    df["hi30"] = df["high"].rolling(30).max().shift(1)
    df["hi60"] = df["high"].rolling(60).max().shift(1)
    df["rvol"]  = df["volume"] / df["volume"].rolling(20).mean()
    # PDH
    dates_norm  = df.index.normalize()
    daily_high  = df.groupby(dates_norm)["high"].max()
    pdh_series  = daily_high.shift(1)
    df["pdh"]   = dates_norm.map(pdh_series)
    data[sym]   = df
print("done\n")

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

# ── state machine (pure numpy arrays) ────────────────────────────────────────
def run_sm(df, level_col, gap_days=None, min_rvol=0.0):
    close = df["close"].values
    lo    = df["low"].values
    hi    = df["high"].values
    op    = df["open"].values
    rvol  = df["rvol"].values
    lvls  = df[level_col].values
    dates = df.index.normalize()
    n     = len(df)

    trades    = []
    cur_date  = None
    state     = "IDLE"
    fired     = False
    skip_to   = 0

    for i in range(n):
        d = dates[i]
        if d != cur_date:
            cur_date = d
            state    = "IDLE"
            fired    = False
            skip_to  = 0  # reset skip per day
            if gap_days is not None and d not in gap_days:
                skip_to = i + 1000000  # skip whole day
        if i < skip_to or fired:
            continue
        if min_rvol > 0 and (np.isnan(rvol[i]) or rvol[i] < min_rvol):
            continue

        lvl = lvls[i]
        if np.isnan(lvl) or lvl <= 0:
            continue

        dist = (close[i] - lvl) / lvl

        if state == "IDLE":
            if abs(dist) <= TOUCH:                state = "TOUCH"
        elif state == "TOUCH":
            if   dist  >  BRK:                    state = "BREAK"
            elif abs(dist) > TOUCH * 4:           state = "IDLE"
        elif state == "BREAK":
            if abs(dist) <= RET:                  state = "RETEST"
        elif state == "RETEST":
            if dist > RET:
                ei = i + 1
                if ei < n:
                    entry  = op[ei]
                    tp_p   = entry * (1 + TP)
                    sl_p   = entry * (1 - SL)
                    result = "TIME"
                    pnl    = 0
                    bars   = MAXB
                    end    = min(ei + MAXB, n)
                    for j in range(ei, end):
                        if lo[j] <= sl_p: result="SL"; pnl=-SL; bars=j-ei; break
                        if hi[j] >= tp_p: result="TP"; pnl= TP; bars=j-ei; break
                    else:
                        ep  = close[min(ei + MAXB, n-1)]
                        pnl = (ep - entry) / entry
                    trades.append({"result": result, "pnl": pnl, "bars": bars, "level": level_col})
                    skip_to = ei + bars
                    fired   = True
                state = "IDLE"
            elif abs(dist) > RET * 4:
                state = "IDLE"

    return trades

# ── metrics ───────────────────────────────────────────────────────────────────
def report(label, trades):
    if not trades:
        print(f"  {label:<26}  --"); return
    df = pd.DataFrame(trades)
    n  = len(df)
    w  = (df["result"]=="TP").sum()
    l  = (df["result"]=="SL").sum()
    ti = (df["result"]=="TIME").sum()
    wr = w / n
    pf = (w * TP) / (l * SL) if l else float("inf")
    ev = df["pnl"].mean()
    ab = df["bars"].mean()
    print(f"  {label:<26}  {n:>4}  {n/DAYS:>4.1f}/d  {wr*100:>5.1f}%  {pf:>5.2f}  {ev*100:>+6.3f}%  {ab:>4.0f}b  {w}W/{l}L/{ti}T")

# ── run ───────────────────────────────────────────────────────────────────────
A30=[]; A1H=[]; B30=[]; B1H=[]; C30=[]; C1H=[]
ranges = {}

for sym, df in data.items():
    rng = (df["high"].max() - df["low"].min()) / df["open"].iloc[0]
    ranges[sym] = rng
    gd = gap_up_dates(df)

    for t in run_sm(df, "hi30", gap_days=gd):           A30.append(t)
    for t in run_sm(df, "hi60", gap_days=gd):           A1H.append(t)
    for t in run_sm(df, "hi30", min_rvol=1.5):          B30.append(t)
    for t in run_sm(df, "hi60", min_rvol=1.5):          B1H.append(t)
    print(f"  {sym} ✓", flush=True)

top8 = sorted(ranges, key=ranges.get, reverse=True)[:8]
print(f"\nTop 8 movers: {top8}")
for sym in top8:
    df = data[sym]
    for t in run_sm(df, "hi30"): C30.append(t)
    for t in run_sm(df, "hi60"): C1H.append(t)

# ── print ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*80}")
print(f"BOOF55  TP=1%  SL=0.5%  Hold=90bars  15syms  51days")
print(f"{'='*80}")
print(f"  {'Variant':<26}  {'N':>4}  {'T/d':>6}  {'WR':>6}  {'PF':>5}  {'EV':>7}  {'Hold':>5}  Outcomes")
print(f"  {'-'*78}")
print("55A (gap-up days only):")
report("  30m reclaim", A30)
report("  1H  reclaim", A1H)
print("55B (RVOL > 1.5, all days):")
report("  30m reclaim", B30)
report("  1H  reclaim", B1H)
print(f"55C (top 8 movers: {', '.join(top8)}):")
report("  30m reclaim", C30)
report("  1H  reclaim", C1H)
