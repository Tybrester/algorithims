"""
boof23_c_quality.py
Variant C (touch & reject) + one quality filter at a time:
  C        — baseline (no extra filter)
  C+RVOL15 — RVOL > 1.5 at signal bar
  C+FIRST  — first touch only (pivot not seen before)
  C+ADX20  — ADX(14) > 20 at signal bar
  C+TIME   — 9:45-11:30 or 14:00-15:30 ET only
  C+RVOL+TIME — best combo
"""
import pandas as pd, numpy as np, os, pytz
from boof23_analysis import (
    resample_to_5min, compute_atr, compute_vol_sma, compute_rvol,
    build_zigzag, build_clusters, nearest_cluster_dist, BOOF23_CFG
)

ET     = pytz.timezone("America/New_York")
TP_PCT = 0.005
SL_PCT = 0.0025

SYMS = ["HOOD","AMD","NVDA","MSFT","ORCL","LLY","PLTR","SMCI","META","TSLA","GOOGL","MU"]

def load(sym):
    f = f"boof51_{sym}_1m.csv"
    if not os.path.exists(f): return None, 0
    df = pd.read_csv(f)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df = df.sort_values("time").reset_index(drop=True)
    hm = df["time"].dt.strftime("%H:%M")
    rth = df[(hm >= "09:30") & (hm <= "16:00")].copy()
    return rth, rth["time"].dt.date.nunique()

def compute_adx(df, period=14):
    high = df["high"].values; low = df["low"].values; close = df["close"].values
    n = len(df)
    tr = np.zeros(n); pdm = np.zeros(n); ndm = np.zeros(n)
    for i in range(1, n):
        tr[i]  = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
        pdm[i] = max(high[i]-high[i-1], 0) if high[i]-high[i-1] > low[i-1]-low[i] else 0
        ndm[i] = max(low[i-1]-low[i], 0)   if low[i-1]-low[i] > high[i]-high[i-1] else 0
    atr_ = pd.Series(tr).ewm(span=period, adjust=False).mean()
    pdi  = 100 * pd.Series(pdm).ewm(span=period, adjust=False).mean() / atr_.replace(0, np.nan)
    ndi  = 100 * pd.Series(ndm).ewm(span=period, adjust=False).mean() / atr_.replace(0, np.nan)
    dx   = 100 * abs(pdi - ndi) / (pdi + ndi).replace(0, np.nan)
    adx  = dx.ewm(span=period, adjust=False).mean()
    return adx.values

def run_variant(df1, filters):
    cfg = BOOF23_CFG; F = cfg["FRACTAL_BARS"]
    df5 = resample_to_5min(df1)
    if len(df5) < cfg["VOL_LEN"]+cfg["ATR_LEN"]+F*2+cfg["MAX_LOOKBACK"]+10: return []

    df5["atr"]     = compute_atr(df5, cfg["ATR_LEN"])
    df5["vol_sma"] = compute_vol_sma(df5, cfg["VOL_LEN"])
    df5["rvol"]    = compute_rvol(df5, cfg["VOL_LEN"])
    adx5           = compute_adx(df5)
    trend, zz_high_bar, zz_low_bar = build_zigzag(df5)
    atr5     = df5["atr"].values
    clusters = build_clusters(df5, atr5)
    highs5   = df5["high"].values;  lows5   = df5["low"].values
    closes5  = df5["close"].values; opens5  = df5["open"].values
    times5   = pd.to_datetime(df5["time"].values)

    trades = []; used_pivots = set(); touched_pivots = set()
    min_i5 = cfg["VOL_LEN"]+cfg["ATR_LEN"]+F*2+cfg["MAX_LOOKBACK"]+5
    i5 = min_i5

    while i5 < len(df5) - 2:
        atr_i = atr5[i5]
        if pd.isna(atr_i) or atr_i == 0: i5 += 1; continue
        if df5.iloc[i5]["rvol"] < cfg["RVOL_MIN"]: i5 += 1; continue

        direction = None; chosen_p = -1

        for offset in range(F+2, F+2+cfg["MAX_LOOKBACK"]+1):
            p = i5 - offset + 1
            if p < F+cfg["VOL_LEN"] or p+F >= i5: continue
            if p-F < 0 or p+F+1 > len(highs5): continue
            if p in used_pivots: continue

            atr_p = atr5[p]
            if pd.isna(atr_p) or atr_p == 0: continue
            if df5.iloc[p]["rvol"] < cfg["RVOL_MIN"]: continue

            fp = (highs5[p] > highs5[p-F:p].max()) and (highs5[p] > highs5[p+1:p+F+1].max())
            ft = (lows5[p]  < lows5[p-F:p].min())  and (lows5[p]  < lows5[p+1:p+F+1].min())
            if not fp and not ft: continue

            if fp:
                zh = int(zz_high_bar[p])
                if zh < 0 or abs(p-zh) > cfg["ZZ_PROX_BARS"]: continue
            else:
                zl = int(zz_low_bar[p])
                if zl < 0 or abs(p-zl) > cfg["ZZ_PROX_BARS"]: continue

            if nearest_cluster_dist(closes5[p], clusters, atr_p) > cfg["SR_DIST_MAX"]: continue

            atr_rej = closes5[p] < highs5[p] - atr_p*cfg["ATR_MULT"]
            atr_bnc = closes5[p] > lows5[p]  + atr_p*cfg["ATR_MULT"]
            if fp and not atr_rej: continue
            if ft and not atr_bnc: continue

            # Variant C — touch & reject
            level = highs5[p] if fp else lows5[p]
            cur_h = highs5[i5]; cur_l = lows5[i5]; cur_c = closes5[i5]
            if fp and not (cur_h >= level and cur_c < level): continue
            if ft and not (cur_l <= level and cur_c > level): continue

            # ── Quality filters ───────────────────────────────────────────
            if "RVOL15" in filters:
                if df5.iloc[i5]["rvol"] < 1.5: continue

            if "FIRST" in filters:
                if p in touched_pivots: continue   # already touched this pivot before

            if "ADX20" in filters:
                if pd.isna(adx5[i5]) or adx5[i5] < 20: continue

            if "TIME" in filters:
                t = times5[i5]
                hm = t.hour*60 + t.minute
                # 9:45-11:30 or 14:00-15:30
                if not ((585 <= hm <= 690) or (840 <= hm <= 930)): continue

            direction = "short" if fp else "long"
            chosen_p  = p; break

        if direction is None: i5 += 1; continue
        used_pivots.add(chosen_p)
        touched_pivots.add(chosen_p)

        if i5+1 >= len(df5): i5 += 1; continue
        entry = opens5[i5+1]
        tp = entry*(1-TP_PCT) if direction=="short" else entry*(1+TP_PCT)
        sl = entry*(1+SL_PCT) if direction=="short" else entry*(1-SL_PCT)

        exit_pnl = None
        for j in range(i5+1, min(i5+61, len(df5))):
            h = highs5[j]; lo = lows5[j]
            if direction=="short":
                if lo <= tp: exit_pnl =  TP_PCT; break
                if h  >= sl: exit_pnl = -SL_PCT; break
            else:
                if h  >= tp: exit_pnl =  TP_PCT; break
                if lo <= sl: exit_pnl = -SL_PCT; break
        if exit_pnl is None:
            ep = closes5[min(i5+60, len(df5)-1)]
            exit_pnl = (entry-ep)/entry if direction=="short" else (ep-entry)/entry

        trades.append(exit_pnl)
        i5 += 1

    return trades

def stats(trades, n_days):
    if not trades: return "   0 trades              "
    wins = [p for p in trades if p > 0]; loss = [p for p in trades if p <= 0]
    wr   = len(wins)/len(trades)*100
    pf   = sum(wins)/abs(sum(loss)) if loss else 99.0
    ev   = np.mean(trades)*100
    tpd  = len(trades)/n_days
    return f"N={len(trades):4d}  T/day={tpd:4.1f}  WR={wr:5.1f}%  PF={pf:5.2f}  EV={ev:+.3f}%"

VARIANTS = {
    "C          (baseline)      ": [],
    "C + RVOL>1.5               ": ["RVOL15"],
    "C + First touch only       ": ["FIRST"],
    "C + ADX>20                 ": ["ADX20"],
    "C + Time filter (9:45-11:30, 14:00-15:30)": ["TIME"],
    "C + RVOL>1.5 + Time filter ": ["RVOL15","TIME"],
    "C + First + Time filter    ": ["FIRST","TIME"],
}

print("Loading data...")
all_trades = {k: [] for k in VARIANTS}
total_days = 0; sym_count = 0

for sym in SYMS:
    df1, n_days = load(sym)
    if df1 is None or len(df1) < 500: continue
    total_days += n_days; sym_count += 1
    for label, filters in VARIANTS.items():
        all_trades[label].extend(run_variant(df1, filters))

avg_days = total_days / sym_count if sym_count else 1

print()
print("=" * 72)
print(f"BOOF23 Variant C + Quality Filters  |  {sym_count} syms  |  ~{avg_days:.0f} days")
print(f"Baseline A (close cross): N=966  T/day=7.8  WR=37.9%  PF=1.22")
print("=" * 72)
for label, trades in all_trades.items():
    print(f"  {label}  {stats(trades, avg_days)}")
