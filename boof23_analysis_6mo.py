"""
Phase 1 — Screen all 264 cached symbols on last 6 months free-run.
           Score: MFE/MAE ratio + EOD positive rate.
           PASS: MFE/MAE > 1.05 AND EOD+ > 52%

Phase 2 — Run full Boof 23 backtest (with TP/SL) on passing symbols only.
"""
import os, pickle, pandas as pd, numpy as np, importlib.util

spec = importlib.util.spec_from_file_location("b23", "boof23_analysis.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ET     = mod.ET
SCREEN_START = pd.Timestamp('2025-12-09', tz=ET)
SCREEN_END   = pd.Timestamp('2026-06-09', tz=ET)
BT_START     = pd.Timestamp('2024-01-01', tz=ET)
BT_END       = pd.Timestamp('2026-06-09', tz=ET)

CACHE_DIR = mod.CACHE_DIR
ALL_SYMS  = sorted([
    f.replace('_2024-01-01_2026-12-31.pkl','')
    for f in os.listdir(CACHE_DIR)
    if f.endswith('_2024-01-01_2026-12-31.pkl')
])

MFE_MAE_MIN = 1.05
EOD_POS_MIN = 52.0
MIN_SIGNALS = 50   # ignore symbols with very few signals

# ─────────────────────────────────────────────────────────────────────
# PHASE 1: Screen
# ─────────────────────────────────────────────────────────────────────
print("=" * 65)
print("PHASE 1 — Free-run screen: all symbols, last 6 months")
print(f"Period : {SCREEN_START.date()} to {SCREEN_END.date()}")
print(f"Filter : MFE/MAE > {MFE_MAE_MIN}  AND  EOD+ > {EOD_POS_MIN}%")
print("=" * 65)

screen_rows = []
for i, sym in enumerate(ALL_SYMS):
    df = mod.load_symbol(sym, SCREEN_START, SCREEN_END)
    if df is None: continue
    t = mod.run_boof23_freerun(df, sym)
    if len(t) < MIN_SIGNALS: continue
    td    = pd.DataFrame(t)
    mfe   = td['mfe_pct']
    mae   = td['mae_pct']
    fin   = td['final_pct']
    ratio = (mfe / mae.replace(0, np.nan)).median()
    eodp  = (fin > 0).mean() * 100
    score = ratio * 0.5 + (eodp / 100) * 0.5
    screen_rows.append(dict(
        sym=sym, n=len(t),
        mfe_med=mfe.median(), mae_med=mae.median(),
        ratio=ratio, eod_pos=eodp, score=score,
        passes=(ratio > MFE_MAE_MIN and eodp > EOD_POS_MIN)
    ))
    status = "PASS" if (ratio > MFE_MAE_MIN and eodp > EOD_POS_MIN) else "    "
    print(f"  {status} {sym:<6} n={len(t):>3}  MFE/MAE={ratio:.2f}x  EOD+={eodp:.1f}%  score={score:.3f}")

sc = pd.DataFrame(screen_rows).sort_values('score', ascending=False)
passing = sc[sc['passes']]['sym'].tolist()

print(f"\n{'='*65}")
print(f"SCREEN RESULTS: {len(passing)} / {len(screen_rows)} symbols passed")
print(f"Passing: {passing}")

# ─────────────────────────────────────────────────────────────────────
# Score table — top 30
# ─────────────────────────────────────────────────────────────────────
print(f"\nTop 30 by score:")
print(f"  {'SYM':<6} {'N':>5} {'MFE/MAE':>8} {'EOD+':>7} {'SCORE':>7} {'PASS':>5}")
print("  " + "-"*42)
for _, r in sc.head(30).iterrows():
    flag = "YES" if r['passes'] else "-"
    print(f"  {r['sym']:<6} {int(r['n']):>5} {r['ratio']:>8.2f}x"
          f" {r['eod_pos']:>6.1f}% {r['score']:>7.3f}  {flag:>5}")

if not passing:
    print("\nNo symbols passed the filter. Exiting.")
    raise SystemExit

# ─────────────────────────────────────────────────────────────────────
# PHASE 2: Strict 4-rule backtest — 2026 only, passing symbols
# ─────────────────────────────────────────────────────────────────────
Y26_START = pd.Timestamp("2026-01-01", tz=ET)
Y26_END   = pd.Timestamp("2026-06-09", tz=ET)

print(f"\n{'='*65}")
print(f"PHASE 2 — STRICT (4 rules) on {len(passing)} symbols — 2026 YTD")
print(f"  Rule 1: one trade per pivot (used_pivots)")
print(f"  Rule 2: one open trade per symbol (lockout)")
print(f"  Rule 3: 10-bar cooldown after exit")
print(f"  Rule 4: close must CROSS pivot level (not just be past it)")
print(f"Period : {Y26_START.date()} to {Y26_END.date()}")
print("="*65)

all_trades  = []
sym_results = []

for sym in passing:
    df = mod.load_symbol(sym, Y26_START, Y26_END)
    if df is None: continue
    t = mod.run_boof23_strict(df, sym)
    if not t:
        print(f"  {sym}: 0 trades")
        continue
    td  = pd.DataFrame(t)
    pnl = td['pnl_pct']
    wr  = (pnl > 0).mean() * 100
    pf_num = pnl[pnl > 0].sum()
    pf_den = pnl[pnl <= 0].abs().sum()
    pf  = pf_num / pf_den if pf_den > 0 else float('inf')
    ret = pnl.sum() * 100
    conflicts = td['same_bar_conflict'].sum()
    conf_pct  = conflicts / len(td) * 100
    sym_results.append(dict(sym=sym, n=len(t), wr=wr, pf=pf,
                            ret=ret, conf_pct=conf_pct))
    all_trades += t
    print(f"  {sym}: {len(t):>4} trades  WR={wr:.1f}%  PF={pf:.2f}  ret={ret:+.2f}%  conflict={conf_pct:.1f}%")

# Per-symbol table sorted by WR
sr = pd.DataFrame(sym_results).sort_values('wr', ascending=False)
print(f"\n  {'SYM':<6} {'N':>5} {'WR':>7} {'PF':>6} {'RET':>8} {'CONFLICT':>9}")
print("  " + "-"*50)
for _, r in sr.iterrows():
    print(f"  {r['sym']:<6} {int(r['n']):>5} {r['wr']:>6.1f}%"
          f" {r['pf']:>6.2f} {r['ret']:>+7.2f}%  {r['conf_pct']:>6.1f}%")

mod.report(all_trades, f"STRICT Boof 23 — 46 filtered syms — 2026 YTD")
