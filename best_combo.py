"""
Best Combo: Early (9:30-10:00) + RVOL >= 1.5 + 2hr fixed hold
Also tests: TP/SL vs fixed hold side by side
Splits by gap bucket and per symbol
"""
import pandas as pd
import numpy as np

df = pd.read_csv("ideas_backtest_results.csv")

TP = 0.010
SL = 0.005

# ── Filters ───────────────────────────────────────────────────────────────────
early     = df[df.time_bucket == "early"]
rvol15    = df[df.rvol >= 1.5]
combo     = df[(df.time_bucket == "early") & (df.rvol >= 1.5)]
combo_gap = combo[combo.gap_bucket == "gap_1_2"]

def hold_stats(sub, col, label):
    sub = sub.dropna(subset=[col])
    if len(sub) == 0:
        print(f"  {label:<40} N=   0  (no data)")
        return
    n    = len(sub)
    wr   = (sub[col] > 0).sum() / n * 100
    ev   = sub[col].mean()
    med  = sub[col].median()
    w    = sub[sub[col] > 0][col].sum()
    l    = sub[sub[col] < 0][col].abs().sum()
    pf   = w / l if l > 0 else 999.0
    tot  = sub[col].sum()
    best = sub[col].max()
    worst= sub[col].min()
    print(f"  {label:<40} N={n:>4}  WR={wr:>5.1f}%  EV={ev:>+6.3f}%  Med={med:>+6.3f}%  PF={pf:.3f}  Tot={tot:>+7.2f}%  Best={best:>+5.2f}%  Worst={worst:>+6.2f}%")

def rr_stats(sub, label):
    if len(sub) == 0:
        print(f"  {label:<40} N=   0  (no data)")
        return
    tp_n = (sub.std_result == "TP").sum()
    sl_n = (sub.std_result == "SL").sum()
    n    = len(sub)
    wr   = tp_n / (tp_n + sl_n) * 100 if (tp_n + sl_n) > 0 else 0
    ev   = sub.std_ret.mean()
    w    = sub[sub.std_ret > 0].std_ret.sum()
    l    = sub[sub.std_ret < 0].std_ret.abs().sum()
    pf   = w / l if l > 0 else 999.0
    tot  = sub.std_ret.sum()
    print(f"  {label:<40} N={n:>4}  WR={wr:>5.1f}%  EV={ev:>+6.3f}%           PF={pf:.3f}  Tot={tot:>+7.2f}%")

print("=" * 100)
print("BEST COMBO: Early (9:30-10:00) + RVOL >= 1.5 + 2hr Hold  |  TP=1%/SL=0.5% comparison")
print("=" * 100)

print("\n-- All trades (baseline) --")
rr_stats(df,   "All trades, TP/SL")
hold_stats(df, "ret_2h", "All trades, 2hr hold")

print("\n-- Early only --")
rr_stats(early,   "Early, TP/SL")
hold_stats(early, "ret_2h", "Early, 2hr hold")

print("\n-- RVOL >= 1.5 only --")
rr_stats(rvol15,   "RVOL>=1.5, TP/SL")
hold_stats(rvol15, "ret_2h", "RVOL>=1.5, 2hr hold")

print("\n-- EARLY + RVOL >= 1.5 (the combo) --")
rr_stats(combo,   "Early+RVOL>=1.5, TP/SL")
hold_stats(combo, "ret_2h", "Early+RVOL>=1.5, 2hr hold")

print("\n-- EARLY + RVOL >= 1.5 + Gap 1-2% only --")
rr_stats(combo_gap,   "Early+RVOL>=1.5+Gap1-2%, TP/SL")
hold_stats(combo_gap, "ret_2h", "Early+RVOL>=1.5+Gap1-2%, 2hr hold")

print("\n-- EARLY + RVOL >= 1.5 + Gap >2% only --")
combo_gap2 = combo[combo.gap_bucket == "gap_2plus"]
rr_stats(combo_gap2,   "Early+RVOL>=1.5+Gap>2%, TP/SL")
hold_stats(combo_gap2, "ret_2h", "Early+RVOL>=1.5+Gap>2%, 2hr hold")

# ── Hold time ladder on best combo ────────────────────────────────────────────
print(f"\n{'='*100}")
print("HOLD TIME LADDER — Early + RVOL>=1.5")
print("="*100)
for col, lbl in [("ret_30m","30 min"),("ret_1h","1 hour"),("ret_2h","2 hour"),("ret_3h","3 hour")]:
    hold_stats(combo, col, lbl)

# ── Per symbol on best combo ──────────────────────────────────────────────────
print(f"\n{'='*100}")
print("PER SYMBOL — Early + RVOL>=1.5, 2hr hold, sorted by EV")
print("="*100)
print(f"  {'Sym':<7} {'N':>4}  {'WR':>6}  {'EV':>8}  {'Median':>8}  {'PF':>6}  {'TotRet':>9}")
print("  "+"-"*55)
sym_rows = []
for sym, g in combo.groupby("sym"):
    g2 = g.dropna(subset=["ret_2h"])
    if len(g2) < 2:
        continue
    n    = len(g2)
    wr   = (g2.ret_2h > 0).sum() / n * 100
    ev   = g2.ret_2h.mean()
    med  = g2.ret_2h.median()
    w    = g2[g2.ret_2h > 0].ret_2h.sum()
    l    = g2[g2.ret_2h < 0].ret_2h.abs().sum()
    pf   = w / l if l > 0 else 999.0
    tot  = g2.ret_2h.sum()
    sym_rows.append((sym, n, wr, ev, med, pf, tot))

sym_rows.sort(key=lambda x: x[3], reverse=True)
for sym, n, wr, ev, med, pf, tot in sym_rows:
    mark = " +" if ev > 0 else "  "
    print(f"  {sym:<7} {n:>4}  {wr:>5.1f}%  {ev:>+7.3f}%  {med:>+7.3f}%  {pf:>6.3f}  {tot:>+8.2f}%{mark}")

# ── Distribution of 2hr returns on best combo ─────────────────────────────────
print(f"\n{'='*100}")
print("RETURN DISTRIBUTION — Early + RVOL>=1.5, 2hr hold")
print("="*100)
sub = combo.dropna(subset=["ret_2h"])
buckets = [("<-1%", sub.ret_2h < -1),
           ("-1% to -0.5%", (sub.ret_2h >= -1) & (sub.ret_2h < -0.5)),
           ("-0.5% to 0%",  (sub.ret_2h >= -0.5) & (sub.ret_2h < 0)),
           ("0% to +0.5%",  (sub.ret_2h >= 0) & (sub.ret_2h < 0.5)),
           ("+0.5% to +1%", (sub.ret_2h >= 0.5) & (sub.ret_2h < 1.0)),
           ("+1% to +2%",   (sub.ret_2h >= 1.0) & (sub.ret_2h < 2.0)),
           (">+2%",         sub.ret_2h >= 2.0)]
for lbl, mask in buckets:
    cnt = mask.sum()
    print(f"  {lbl:<18} {cnt:>4} trades  ({cnt/len(sub)*100:>5.1f}%)")
