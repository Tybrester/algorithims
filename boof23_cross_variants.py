"""
boof23_cross_variants.py
Test 4 cross filter variants on cached 1m data.

A — Current: prev_close on one side, cur_close crosses through
B — Intrabar cross: prev bar one side, cur HIGH/LOW crosses + close confirms
C — Touch & reject: high crosses level, close back below (short) / low crosses, close back above (long)
D — No cross: zigzag + ATR bounce + SR + RVOL only (upper bound)
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
    if not os.path.exists(f): return None
    df = pd.read_csv(f)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df = df.sort_values("time").reset_index(drop=True)
    hm = df["time"].dt.strftime("%H:%M")
    rth = df[(hm >= "09:30") & (hm <= "16:00")].copy()
    n_days = rth["time"].dt.date.nunique()
    return rth, n_days

def run_variant(df1, variant):
    cfg = BOOF23_CFG
    F   = cfg["FRACTAL_BARS"]
    df5 = resample_to_5min(df1)
    if len(df5) < cfg["VOL_LEN"] + cfg["ATR_LEN"] + F*2 + cfg["MAX_LOOKBACK"] + 10:
        return []

    df5["atr"]     = compute_atr(df5, cfg["ATR_LEN"])
    df5["vol_sma"] = compute_vol_sma(df5, cfg["VOL_LEN"])
    df5["rvol"]    = compute_rvol(df5, cfg["VOL_LEN"])
    trend, zz_high_bar, zz_low_bar = build_zigzag(df5)
    atr5     = df5["atr"].values
    clusters = build_clusters(df5, atr5)
    highs5   = df5["high"].values
    lows5    = df5["low"].values
    closes5  = df5["close"].values
    opens5   = df5["open"].values

    trades      = []
    used_pivots = set()
    min_i5 = cfg["VOL_LEN"] + cfg["ATR_LEN"] + F*2 + cfg["MAX_LOOKBACK"] + 5
    i5 = min_i5

    while i5 < len(df5) - 2:
        atr_i = atr5[i5]
        if pd.isna(atr_i) or atr_i == 0: i5 += 1; continue
        if df5.iloc[i5]["rvol"] < cfg["RVOL_MIN"]: i5 += 1; continue

        direction = None; chosen_p = -1

        for offset in range(F+2, F+2+cfg["MAX_LOOKBACK"]+1):
            p = i5 - offset + 1
            if p < F + cfg["VOL_LEN"] or p + F >= i5: continue
            if p - F < 0 or p + F + 1 > len(highs5): continue
            if p in used_pivots: continue

            atr_p = atr5[p]
            if pd.isna(atr_p) or atr_p == 0: continue
            if df5.iloc[p]["rvol"] < cfg["RVOL_MIN"]: continue

            fp = (highs5[p] > highs5[p-F:p].max()) and (highs5[p] > highs5[p+1:p+F+1].max())
            ft = (lows5[p]  < lows5[p-F:p].min())  and (lows5[p]  < lows5[p+1:p+F+1].min())
            if not fp and not ft: continue

            # ZZ proximity
            if fp:
                zh = int(zz_high_bar[p])
                if zh < 0 or abs(p - zh) > cfg["ZZ_PROX_BARS"]: continue
            else:
                zl = int(zz_low_bar[p])
                if zl < 0 or abs(p - zl) > cfg["ZZ_PROX_BARS"]: continue

            # S/R distance
            if nearest_cluster_dist(closes5[p], clusters, atr_p) > cfg["SR_DIST_MAX"]: continue

            # ATR rejection/bounce
            atr_rej = closes5[p] < highs5[p] - atr_p * cfg["ATR_MULT"]
            atr_bnc = closes5[p] > lows5[p]  + atr_p * cfg["ATR_MULT"]
            if fp and not atr_rej: continue
            if ft and not atr_bnc: continue

            # ── Cross filter variants ──────────────────────────────────────
            level = highs5[p] if fp else lows5[p]
            prev_c = closes5[i5-1]
            cur_c  = closes5[i5]
            cur_h  = highs5[i5]
            cur_l  = lows5[i5]

            passed = False

            if variant == "A":
                # Current: close must cross level
                if fp: passed = (prev_c >= level and cur_c < level)
                else:  passed = (prev_c <= level and cur_c > level)

            elif variant == "B":
                # Intrabar: prev bar on one side, cur HIGH/LOW crosses, close confirms
                if fp:
                    passed = (prev_c >= level        # prev close above level
                              and cur_h >= level      # current bar tags level
                              and cur_c < level)      # close confirms below
                else:
                    passed = (prev_c <= level
                              and cur_l <= level
                              and cur_c > level)

            elif variant == "C":
                # Touch & reject: high pokes through, close back below (short)
                if fp:
                    passed = (cur_h >= level and cur_c < level)   # wick up, closed below
                else:
                    passed = (cur_l <= level and cur_c > level)   # wick down, closed above

            elif variant == "D":
                # No cross — just zigzag + ATR + SR + RVOL
                passed = True

            if not passed: continue

            direction = "short" if fp else "long"
            chosen_p  = p; break

        if direction is None: i5 += 1; continue
        used_pivots.add(chosen_p)

        if i5 + 1 >= len(df5): i5 += 1; continue
        entry = opens5[i5+1]
        if direction == "short":
            tp = entry * (1 - TP_PCT); sl = entry * (1 + SL_PCT)
        else:
            tp = entry * (1 + TP_PCT); sl = entry * (1 - SL_PCT)

        exit_pnl = None
        for j in range(i5+1, min(i5+61, len(df5))):
            h = highs5[j]; lo = lows5[j]
            if direction == "short":
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
    if not trades:
        return "   0 trades"
    wins = [p for p in trades if p > 0]
    loss = [p for p in trades if p <= 0]
    wr   = len(wins)/len(trades)*100
    pf   = sum(wins)/abs(sum(loss)) if loss else 99.0
    ev   = np.mean(trades)*100
    tpd  = len(trades)/n_days
    return f"N={len(trades):4d}  T/day={tpd:4.1f}  WR={wr:5.1f}%  PF={pf:5.2f}  EV={ev:+.3f}%"

VARIANTS = {
    "A — Close cross (current)  ": "A",
    "B — Intrabar cross+confirm ": "B",
    "C — Touch & reject         ": "C",
    "D — No cross (upper bound) ": "D",
}

print("Loading data...")
all_trades   = {v: [] for v in VARIANTS}
total_days   = 0

for sym in SYMS:
    result = load(sym)
    if result is None: continue
    df1, n_days = result
    if len(df1) < 500: continue
    total_days += n_days
    for label, v in VARIANTS.items():
        t = run_variant(df1, v)
        all_trades[label].extend(t)

avg_days = total_days / len(SYMS)

print()
print("=" * 70)
print(f"BOOF23 Cross Filter Variants  |  {len(SYMS)} symbols  |  ~{avg_days:.0f} days  |  TP=0.5% SL=0.25%")
print("=" * 70)
for label, trades in all_trades.items():
    print(f"  {label}  {stats(trades, avg_days)}")
print()
print("Notes:")
print("  A = current live logic (exact close cross)")
print("  B = intrabar: prev on one side, cur H/L tags, close confirms")
print("  C = touch & reject: wick through level, close back (no prev req)")
print("  D = no cross at all — upper bound on what the zigzag+ATR finds")
