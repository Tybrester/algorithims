"""
Two parallel tests on 46 screened symbols, last 6 months:
  A) Strict 4-rule | 5-min signal + 1-min execution | TP=0.40% SL=0.20%
  B) Strict 4-rule | 5-min signal + 1-min execution | TP=0.45% SL=0.18%
     + Leaderboard: WR>36%, P&L>40%, Trades>1000
"""
import pandas as pd, numpy as np, importlib.util

spec = importlib.util.spec_from_file_location("b23", "boof23_analysis.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ET    = mod.ET
START = pd.Timestamp("2025-12-09", tz=ET)
END   = pd.Timestamp("2026-06-09", tz=ET)

SYMS = [
    'TOST','HOOD','ORCL','MSFT','V','JPM','SOUN','PODD','ENTG','GE',
    'MRNA','AI','PATH','GS','BSX','SIMO','SCHW','TEM','AMD','ABNB',
    'NEM','GILD','MCHP','UNP','ETN','LRCX','SMTC','INCY','ITW','LLY',
    'MAR','QRVO','MPC','BKR','TMO','CAT','NVDA','SOFI','XOM','DPZ',
    'FCX','VRTX','S','CSCO','DE','HUM'
]

def run_test(tp, sl, label):
    print(f"\n{'='*65}")
    print(f"{label}  |  TP={tp*100:.2f}%  SL={sl*100:.2f}%")
    print(f"Period: {START.date()} to {END.date()}  |  {len(SYMS)} symbols")
    print("="*65)
    all_pnl = []; rows = []
    for sym in SYMS:
        df = mod.load_symbol(sym, START, END)
        if df is None: continue
        t = mod.run_boof23_strict_5sig_1exec(df, sym, tp_pct=tp, sl_pct=sl)
        if not t: continue
        pnl  = [x['pnl_pct'] for x in t]
        wins = [p for p in pnl if p > 0]
        loss = [p for p in pnl if p <= 0]
        wr   = len(wins) / len(pnl) * 100
        pf   = sum(wins) / abs(sum(loss)) if loss else float('inf')
        ret  = sum(pnl) * 100
        all_pnl += pnl
        rows.append(dict(sym=sym, n=len(t), wr=wr, pf=pf, ret=ret))
        print(f"  {sym:<6} {len(t):>4}  WR={wr:.1f}%  PF={pf:.2f}  P&L={ret:+.2f}%")

    # Summary
    if all_pnl:
        wins_all = [p for p in all_pnl if p > 0]
        loss_all = [p for p in all_pnl if p <= 0]
        pf_all   = sum(wins_all) / abs(sum(loss_all)) if loss_all else float('inf')
        print(f"\n  TOTAL  {len(all_pnl)} trades  "
              f"WR={len(wins_all)/len(all_pnl)*100:.1f}%  "
              f"PF={pf_all:.2f}  P&L={sum(all_pnl)*100:+.2f}%")
    return rows

def leaderboard(rows, tp, sl):
    filtered = [r for r in rows if r['wr'] > 36 and r['ret'] > 40 and r['n'] > 1000]
    filtered.sort(key=lambda x: -x['ret'])
    print(f"\n{'='*65}")
    print(f"LEADERBOARD  TP={tp*100:.2f}%  SL={sl*100:.2f}%")
    print(f"Filter: WR>36%  P&L>40%  Trades>1000  ({len(filtered)} qualify)")
    print(f"{'='*65}")
    print(f"  {'#':<3} {'SYM':<6} {'TRADES':>7} {'WR':>7} {'PF':>6} {'P&L':>8}")
    print("  " + "-"*44)
    for i, r in enumerate(filtered, 1):
        print(f"  {i:<3} {r['sym']:<6} {r['n']:>7} {r['wr']:>6.1f}%"
              f" {r['pf']:>6.2f} {r['ret']:>+7.2f}%")
    if not filtered:
        print("  (none passed all filters)")

# ── Run Test A: TP=0.40% SL=0.20% ────────────────────────────────────
rows_a = run_test(0.0040, 0.0020, "TEST A  |  STRICT 4-rule  |  5-min sig + 1-min exec")

# ── Run Test B: TP=0.45% SL=0.18% ────────────────────────────────────
rows_b = run_test(0.0045, 0.0018, "TEST B  |  STRICT 4-rule  |  5-min sig + 1-min exec")
leaderboard(rows_b, 0.0045, 0.0018)
