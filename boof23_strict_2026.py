"""
Strict 4-rule Boof 23 backtest on the 46 pre-screened symbols — 2026 YTD only.
Skips Phase 1 screen (already done). Runs directly to results.
"""
import pandas as pd, numpy as np, importlib.util

spec = importlib.util.spec_from_file_location("b23", "boof23_analysis.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ET = mod.ET
Y26_START = pd.Timestamp("2026-01-01", tz=ET)
Y26_END   = pd.Timestamp("2026-06-09", tz=ET)

PASSING = [
    'TOST','HOOD','ORCL','MSFT','V','JPM','SOUN','PODD','ENTG','GE',
    'MRNA','AI','PATH','GS','BSX','SIMO','SCHW','TEM','AMD','ABNB',
    'NEM','GILD','MCHP','UNP','ETN','LRCX','SMTC','INCY','ITW','LLY',
    'MAR','QRVO','MPC','BKR','TMO','CAT','NVDA','SOFI','XOM','DPZ',
    'FCX','VRTX','S','CSCO','DE','HUM'
]

print("=" * 65)
print(f"STRICT Boof 23 — {len(PASSING)} screened symbols — 2026 YTD")
print(f"  R1: one trade per pivot  R2: lockout  R3: 10-bar cooldown  R4: cross")
print(f"Period: {Y26_START.date()} to {Y26_END.date()}")
print("=" * 65)

all_trades  = []
sym_results = []

for sym in PASSING:
    df = mod.load_symbol(sym, Y26_START, Y26_END)
    if df is None:
        print(f"  {sym}: no data")
        continue
    t = mod.run_boof23_strict(df, sym)
    if not t:
        print(f"  {sym}:  0 trades")
        continue
    td   = pd.DataFrame(t)
    pnl  = td['pnl_pct']
    wr   = (pnl > 0).mean() * 100
    wins = pnl[pnl > 0].sum()
    loss = pnl[pnl <= 0].abs().sum()
    pf   = wins / loss if loss > 0 else float('inf')
    ret  = pnl.sum() * 100
    conf = td['same_bar_conflict'].mean() * 100
    sym_results.append(dict(sym=sym, n=len(t), wr=wr, pf=pf, ret=ret, conf=conf))
    all_trades += t
    print(f"  {sym:<6} {len(t):>4} trades  WR={wr:.1f}%  PF={pf:.2f}  ret={ret:+.2f}%  conflict={conf:.1f}%")

print(f"\n{'='*65}")
print(f"  {'SYM':<6} {'N':>5} {'WR':>7} {'PF':>6} {'RET':>8} {'CONFLICT':>9}")
print("  " + "-"*50)
sr = sorted(sym_results, key=lambda x: -x['wr'])
for r in sr:
    print(f"  {r['sym']:<6} {r['n']:>5} {r['wr']:>6.1f}%"
          f" {r['pf']:>6.2f} {r['ret']:>+7.2f}%  {r['conf']:>6.1f}%")

mod.report(all_trades, f"STRICT Boof 23 — {len(PASSING)} filtered syms — 2026 YTD")
