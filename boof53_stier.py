"""S-Tier deep dive — TP0.50/SL0.25 split by gap regime and side"""
import pandas as pd
import numpy as np

S_TIER = ["RKLB","HIMS","MU","ARM","APP","SMCI"]
df = pd.read_csv("boof53_tpsl_50_25.csv")
df = df[df["sym"].isin(S_TIER)]
WEEKS = 19.2

def metrics(s):
    if len(s) < 5: return None
    wins   = s[s["outcome"]=="win"]
    losses = s[s["outcome"]=="loss"]
    wr     = len(wins)/len(s)*100
    gw     = wins["pnl"].sum()
    gl     = abs(losses["pnl"].sum()) if len(losses) else 1e-9
    pf     = gw/gl
    ev     = s["pnl"].mean()
    tpw    = len(s)/WEEKS
    cum    = s["pnl"].cumsum().values
    peak   = np.maximum.accumulate(cum)
    maxdd  = (cum - peak).min()
    return dict(n=len(s), tpw=tpw, wr=wr, pf=pf, ev=ev, maxdd=maxdd)

def prow(label, s, w=22):
    m = metrics(s)
    if m is None: print(f"  {label:<{w}} <5"); return
    mk = " <<<" if m["pf"]>=2.0 else (" <<" if m["pf"]>=1.5 else "")
    print(f"  {label:<{w}} {m['n']:>5} {m['tpw']:>6.1f}  "
          f"{m['wr']:>5.1f}%  {m['pf']:>6.3f}  {m['ev']:>+7.4f}%  {m['maxdd']:>+8.2f}%{mk}")

HDR = (f"  {'Label':<22} {'N':>5} {'T/Wk':>6}  "
       f"{'WR':>6}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>8}")
SEP = f"  {'-'*74}"
W = 78

# ── 1. Overall S tier ───────────────────────────────────────────────────────
print(f"\n{'='*W}")
print(f"  S TIER — TP0.50% / SL0.25%  |  6 symbols  |  19.2 weeks")
print(f"{'='*W}")
print(HDR); print(SEP)
prow("S TIER ALL", df)
print(SEP)
for sym in S_TIER:
    prow(sym, df[df["sym"]==sym])

# ── 2. Gap regime ───────────────────────────────────────────────────────────
print(f"\n{'='*W}")
print(f"  S TIER — BY GAP REGIME")
print(f"{'='*W}")
print(HDR); print(SEP)
for regime in ["Gap Down","Flat","Gap Up"]:
    prow(regime, df[df["gap_regime"]==regime])
print(SEP)
# regime × sym
print(f"\n  BY REGIME × SYMBOL")
print(HDR); print(SEP)
for regime in ["Gap Down","Flat","Gap Up"]:
    print(f"  -- {regime} --")
    for sym in S_TIER:
        prow(f"  {sym}", df[(df["sym"]==sym)&(df["gap_regime"]==regime)])

# ── 3. Long vs Short ────────────────────────────────────────────────────────
print(f"\n{'='*W}")
print(f"  S TIER — LONG vs SHORT")
print(f"{'='*W}")
print(HDR); print(SEP)
for side in ["long","short"]:
    prow(side.upper(), df[df["side"]==side])
print(SEP)
for sym in S_TIER:
    for side in ["long","short"]:
        prow(f"{sym} {side}", df[(df["sym"]==sym)&(df["side"]==side)])

# ── 4. Side × Gap regime ────────────────────────────────────────────────────
print(f"\n{'='*W}")
print(f"  S TIER — SIDE × GAP REGIME")
print(f"{'='*W}")
print(HDR); print(SEP)
for side in ["long","short"]:
    print(f"  -- {side.upper()} --")
    for regime in ["Gap Down","Flat","Gap Up"]:
        prow(f"  {side} {regime}", df[(df["side"]==side)&(df["gap_regime"]==regime)])
    print(SEP)
