"""
BOOF60 Realistic Option Multiplier Test
1DTE ATM options: delta ~0.50, but gamma effect on 1DTE means
a 1% stock move = 20-40% option move (not 2%)
Test multipliers: 2x, 3x, 4x, 5x on the best filter combo
Best filter: longs gap>2%, entry 09:30-10:00, TP=12%, SL=-12%
"""
import pickle
import pandas as pd
from itertools import product

BUDGET = 750.0
PKL    = "boof60_v2_paths.pkl"

with open(PKL, 'rb') as f:
    raw_trades = pickle.load(f)

# Best filter
trades = [t for t in raw_trades
          if t['signal'] == 'BOOF55'
          and t['gap_pct'] >= 2.0
          and t.get('entry_time','00:00') <= '10:00']

print(f"Trades after filter: {len(trades)}")
print(f"Gap range: {min(t['gap_pct'] for t in trades):.1f}% – {max(t['gap_pct'] for t in trades):.1f}%\n")

def sim_mult(trades, mult, tp_pct, sl_pct):
    results = []
    for t in trades:
        pnl = None; exit_type = 'TIMEOUT'
        for b in t['bars']:
            mfe = b['mfe_opt'] / 2.0 * mult   # rescale from base 2x to test mult
            mae = b['mae_opt'] / 2.0 * mult
            cur = b['opt_pct']  / 2.0 * mult
            if mfe >= tp_pct:  pnl = BUDGET * tp_pct / 100;  exit_type = 'TP'; break
            if mae <= sl_pct:  pnl = BUDGET * sl_pct / 100;  exit_type = 'SL'; break
        if pnl is None:
            last = t['bars'][-1]
            pnl  = BUDGET * (last['opt_pct'] / 2.0 * mult) / 100
        results.append({'pnl': pnl, 'exit': exit_type})
    df = pd.DataFrame(results)
    wins   = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    wr  = len(wins)/len(df) if len(df) else 0
    pf  = wins['pnl'].sum()/abs(losses['pnl'].sum()) if losses['pnl'].sum()!=0 else 999
    ev  = df['pnl'].mean()
    return {
        'mult': mult, 'tp': tp_pct, 'sl': sl_pct,
        'n': len(df), 'wr': round(wr*100,1),
        'pf': round(pf,2), 'ev': round(ev,2),
        'total_6mo': round(df['pnl'].sum(),2),
        'ann': round(df['pnl'].sum()/6*12, 2),
        'tp_hits': len(df[df['exit']=='TP']),
        'sl_hits': len(df[df['exit']=='SL']),
    }

print("="*70)
print("MULTIPLIER SWEEP  (filter: longs gap>2%, entry ≤10:00, TP=12, SL=-12)")
print("="*70)
print(f"{'mult':>5}  {'wr':>6}  {'pf':>5}  {'ev':>7}  {'6mo':>9}  {'ann':>10}  {'tp':>4}  {'sl':>4}")
print("-"*70)
for mult in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
    r = sim_mult(trades, mult, 12.0, -12.0)
    print(f"  {mult:>3}x  {r['wr']:>5}%  {r['pf']:>5}x  ${r['ev']:>6.2f}  ${r['total_6mo']:>8.2f}  ${r['ann']:>9.2f}/yr  {r['tp_hits']:>4}  {r['sl_hits']:>4}")

print("\n")
print("="*70)
print("TP/SL SWEEP AT 3x MULTIPLIER (realistic 1DTE ATM estimate)")
print("="*70)
rows = []
for tp, sl in product([10,15,20,25,35,50,75,100], [-10,-15,-20,-25,-35,-50]):
    r = sim_mult(trades, 3.0, tp, sl)
    rows.append(r)
df_sweep = pd.DataFrame(rows).sort_values('total_6mo', ascending=False)
print(df_sweep.head(15)[['tp','sl','wr','pf','ev','total_6mo','ann','tp_hits','sl_hits']].to_string(index=False))

print("\n")
print("="*70)
print("TP/SL SWEEP AT 4x MULTIPLIER")
print("="*70)
rows4 = []
for tp, sl in product([10,15,20,25,35,50,75,100], [-10,-15,-20,-25,-35,-50]):
    r = sim_mult(trades, 4.0, tp, sl)
    rows4.append(r)
df4 = pd.DataFrame(rows4).sort_values('total_6mo', ascending=False)
print(df4.head(15)[['tp','sl','wr','pf','ev','total_6mo','ann','tp_hits','sl_hits']].to_string(index=False))

print("\n")
print("="*70)
print("BEST COMBO SUMMARY (top result per multiplier)")
print("="*70)
for mult in [2.0, 3.0, 4.0, 5.0]:
    best = None
    for tp, sl in product([10,15,20,25,35,50,75,100],[-10,-15,-20,-25,-35,-50]):
        r = sim_mult(trades, mult, tp, sl)
        if best is None or r['total_6mo'] > best['total_6mo']:
            best = r
    print(f"  {mult}x mult  TP={best['tp']}%  SL={best['sl']}%  "
          f"WR={best['wr']}%  PF={best['pf']}x  "
          f"6mo=${best['total_6mo']}  ann=${best['ann']}/yr  "
          f"TP_hits={best['tp_hits']}")
