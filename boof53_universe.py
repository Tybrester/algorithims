"""BOOF53 — Locked Universe Summary"""
import pandas as pd

S_TIER = ["RKLB","HIMS","MU","ARM","APP","SMCI"]
A_TIER = ["COIN","AMD","PLTR","HOOD","CRM","AVGO"]
B_TIER = ["TSLA","NVDA","META","AMZN","LLY","ADBE"]
ALL    = S_TIER + A_TIER + B_TIER

df    = pd.read_csv("boof53_leaderboard_all.csv")
b     = df[(df["bounced"]==True) & (df["touch_lbl"]=="1st") & (df["sym"].isin(ALL))]
WEEKS = df["date"].nunique() / 5
DAYS  = df["date"].nunique()

HDR = (f"  {'Sym':<6} {'N':>5} {'T/Wk':>6}  "
       f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
SEP = f"  {'-'*76}"

def print_tier(label, syms):
    ts = b[b["sym"].isin(syms)]
    tpw = len(ts) / WEEKS
    print(f"\n  {label}")
    print(HDR); print(SEP)
    rows = []
    for sym in syms:
        s = ts[ts["sym"]==sym]
        if len(s) < 3: continue
        rows.append((sym, len(s), len(s)/WEEKS,
                     s["mfe15"].mean(), s["mfe30"].mean(), s["mfe60"].mean(),
                     s["hit_>=0.50%"].mean()*100, s["hit_>=0.75%"].mean()*100))
    for sym,n,tpw_s,m15,m30,m60,h50,h75 in sorted(rows, key=lambda x: -x[4]):
        mk = " <<<" if h50>=55 else ("  <<" if h50>=40 else "")
        print(f"  {sym:<6} {n:>5} {tpw_s:>6.2f}  "
              f"{m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%  {h50:>8.1f}%  {h75:>8.1f}%{mk}")
    print(SEP)
    print(f"  {'TOTAL':<6} {len(ts):>5} {tpw:>6.2f}  "
          f"{ts['mfe15'].mean():>6.3f}%  {ts['mfe30'].mean():>6.3f}%  "
          f"{ts['mfe60'].mean():>6.3f}%  "
          f"{ts['hit_>=0.50%'].mean()*100:>8.1f}%  "
          f"{ts['hit_>=0.75%'].mean()*100:>8.1f}%")

W = 84
print(f"\n{'='*W}")
print(f"  BOOF53 LOCKED UNIVERSE — {len(ALL)} symbols  |  {DAYS}d (~{WEEKS:.1f}wk)")
print(f"  Levels: PML PMH PDL PDH 1H_Sup 1H_Res 4H_Sup 4H_Res")
print(f"  Filter: 1st touch, bounce>=0.15%, entry=open[i+1] after zone exit")
print(f"  Pivots: RTH-only (09:30-16:00), left-edge confirmation, no look-ahead")
print(f"{'='*W}")

print_tier("S TIER — RKLB  HIMS  MU  ARM  APP  SMCI", S_TIER)
print_tier("A TIER — COIN  AMD  PLTR  HOOD  CRM  AVGO", A_TIER)
print_tier("B TIER — TSLA  NVDA  META  AMZN  LLY  ADBE", B_TIER)

# Combined S+A
sa = b[b["sym"].isin(S_TIER+A_TIER)]
print(f"\n{'='*W}")
print(f"  S+A TIER COMBINED ({len(S_TIER+A_TIER)} symbols)")
print(f"{'='*W}")
print(f"  N={len(sa):,}  T/Wk={len(sa)/WEEKS:.1f}  "
      f"MFE30={sa['mfe30'].mean():.3f}%  "
      f">=0.50%={sa['hit_>=0.50%'].mean()*100:.1f}%  "
      f">=0.75%={sa['hit_>=0.75%'].mean()*100:.1f}%")

# Full 18
all18 = b[b["sym"].isin(ALL)]
print(f"\n  ALL 18 SYMBOLS COMBINED")
print(f"  N={len(all18):,}  T/Wk={len(all18)/WEEKS:.1f}  "
      f"MFE30={all18['mfe30'].mean():.3f}%  "
      f">=0.50%={all18['hit_>=0.50%'].mean()*100:.1f}%  "
      f">=0.75%={all18['hit_>=0.75%'].mean()*100:.1f}%")

# Long vs Short split for 18
for side in ["long","short"]:
    s = all18[all18["side"]==side]
    print(f"  {side.upper():<6}   N={len(s):,}  T/Wk={len(s)/WEEKS:.1f}  "
          f"MFE30={s['mfe30'].mean():.3f}%  "
          f">=0.50%={s['hit_>=0.50%'].mean()*100:.1f}%  "
          f">=0.75%={s['hit_>=0.75%'].mean()*100:.1f}%")
