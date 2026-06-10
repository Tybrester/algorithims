"""
Boof 23 — Cluster Completion Logic Backtest
============================================
Compares 3 configs:
  A) Baseline         — CLUSTER_COMPLETION=False (current live)
  B) Cluster Completion — middle=tight SL, late=1.5x size if activated
  C) Cluster Completion + late=2.0x size (more aggressive scale)

Reports: trades/day, WR, EV/trade, PF, monthly, annual.
Also breaks down by cluster position to verify the mechanics.
"""
import pickle, sys
import numpy as np
from collections import defaultdict

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof23 as b23

B23_SYMS   = ['NVDA','AAPL','MSFT','AMZN','GOOGL','AVGO','META','TSLA','LLY']
MONTHS     = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MONTH_DAYS = [23,20,21,22,21,21,23,21,22,23,20,23]
TOTAL_DAYS = sum(MONTH_DAYS)
B23_EXP    = 200; B23_CORE = 500

print('Loading cache...')
cache = pickle.load(open('_boof22_cache.pkl','rb'))
print('  Done.\n')

CONFIGS = [
    ('A  Baseline',         False, 1.5),
    ('B  Cluster 1.5x late', True,  1.5),
    ('C  Cluster 2.0x late', True,  2.0),
]

def run_config(enabled, late_mult):
    b23.CLUSTER_COMPLETION = enabled
    b23.LATE_SIZE_MULT     = late_mult
    trades_all = []
    trades_by_month = defaultdict(list)
    for mo in MONTHS:
        for sym in B23_SYMS:
            df = cache.get((sym, mo))
            if df is None or len(df) < 100: continue
            for t in b23.run_boof23(df, symbol=sym):
                size = (B23_CORE if t['tier']=='core' else B23_EXP) * t.get('size_mult', 1.0)
                pnl  = t['pnl_pct'] * size
                t['pnl_dollar'] = pnl
                trades_by_month[mo].append(pnl)
                trades_all.append(t)
    return trades_by_month, trades_all

results = {}
for name, enabled, lm in CONFIGS:
    print(f'  Running {name}...')
    by_mo, all_t = run_config(enabled, lm)
    results[name] = {'by_mo': by_mo, 'all': all_t}

def stats(pnl_list):
    if not pnl_list: return 0, 0.0, 0.0, 0.0, 0.0
    p = np.array(pnl_list)
    pos = p[p>0]; neg = p[p<0]
    return (len(p), round(len(pos)/len(p)*100,1),
            round(float(np.mean(p)),2),
            round(float(sum(pos)/max(abs(sum(neg)),0.01)),2),
            round(float(sum(p)),0))

SEP = '=' * 82

# ── Annual summary ────────────────────────────────────────────────
print(f'\n{SEP}')
print('  CONFIGURATION COMPARISON — Annual Summary')
print(SEP)
print(f'  {"Config":<26}  {"Trades":>7}  {"T/day":>6}  {"WR":>7}  '
      f'{"EV/trade":>10}  {"PF":>7}  {"Annual":>12}  {"vs Base":>8}')
print(f'  {"-"*82}')
base_annual = None
for name, _, _ in CONFIGS:
    all_pnl = [t['pnl_dollar'] for t in results[name]['all']]
    n, wr, ev, pf, tot = stats(all_pnl)
    annual = tot * 2
    tpd    = n / TOTAL_DAYS
    vs     = f'{(annual-base_annual)/base_annual*100:+.1f}%' if base_annual else 'base'
    if base_annual is None: base_annual = annual
    print(f'  {name:<26}  {n:>7}  {tpd:>6.1f}  {wr:>6.1f}%  '
          f'${ev:>9.2f}  {pf:>7.2f}  ${annual:>11,.0f}  {vs:>8}')

# ── Monthly breakdown ─────────────────────────────────────────────
print(f'\n{SEP}')
print('  MONTHLY P&L BREAKDOWN')
print(SEP)
header = f'  {"Month":<8}'
for name, _, _ in CONFIGS:
    short = name.split()[0]
    header += f'  {short:>13}'
print(header)
print(f'  {"-"*62}')
for mo, days in zip(MONTHS, MONTH_DAYS):
    row = f'  {mo:<8}'
    reds = []
    for name, _, _ in CONFIGS:
        pnl = sum(results[name]['by_mo'][mo]) * 2
        row += f'  ${pnl:>11,.0f}'
        if pnl < 0: reds.append(name.split()[0])
    if reds: row += f'  << RED: {",".join(reds)}'
    print(row)
row = f'  {"ANNUAL":<8}'
for name, _, _ in CONFIGS:
    total = sum(p for mo in MONTHS for p in results[name]['by_mo'][mo]) * 2
    row += f'  ${total:>11,.0f}'
print(f'  {"-"*62}')
print(row)

# ── Cluster position breakdown for configs B and C ───────────────
print(f'\n{SEP}')
print('  CLUSTER POSITION BREAKDOWN (Configs B & C)')
print(SEP)
for name, enabled, _ in CONFIGS[1:]:
    print(f'\n  {name}:')
    print(f'  {"Position":<12}  {"Trades":>8}  {"WR":>7}  {"EV/trade":>10}  '
          f'{"PF":>7}  {"SL mult":>8}  {"Size mult":>10}')
    print(f'  {"-"*64}')
    by_pos = defaultdict(list)
    for t in results[name]['all']:
        by_pos[t.get('cluster_pos','first')].append(t['pnl_dollar'])
    for pos in ['first','middle','late']:
        pnls = by_pos.get(pos, [])
        n, wr, ev, pf, _ = stats(pnls)
        sl_note = f'{b23.ATR_SL_MIDDLE}x ATR' if pos=='middle' and enabled else f'{b23.ATR_SL}x ATR'
        sz_note = f'{b23.LATE_SIZE_MULT}x' if pos=='late' and enabled else '1.0x'
        print(f'  {pos:<12}  {n:>8}  {wr:>6.1f}%  ${ev:>9.2f}  {pf:>7.2f}  '
              f'{sl_note:>8}  {sz_note:>10}')

# ── Compare: what changed from baseline? ─────────────────────────
print(f'\n{SEP}')
print('  WHAT CHANGED VS BASELINE')
print(SEP)
base_trades = results['A  Baseline']['all']
base_ann    = sum(t['pnl_dollar'] for t in base_trades) * 2

for name, enabled, lm in CONFIGS[1:]:
    new_trades = results[name]['all']
    new_ann    = sum(t['pnl_dollar'] for t in new_trades) * 2
    # Middle: same count, but tighter SL — find trades that hit SL
    mid_base  = [t for t in base_trades if t.get('cluster_pos','first')=='middle']
    mid_new   = [t for t in new_trades  if t.get('cluster_pos','first')=='middle']
    late_base = [t for t in base_trades if t.get('cluster_pos','first')=='late']
    late_new  = [t for t in new_trades  if t.get('cluster_pos','first')=='late']
    _, _, ev_mb, _, tot_mb = stats([t['pnl_dollar'] for t in mid_base])
    _, _, ev_mn, _, tot_mn = stats([t['pnl_dollar'] for t in mid_new])
    _, _, ev_lb, _, tot_lb = stats([t['pnl_dollar'] for t in late_base])
    _, _, ev_ln, _, tot_ln = stats([t['pnl_dollar'] for t in late_new])
    print(f'\n  {name}:')
    print(f'    Annual delta:  ${new_ann-base_ann:+,.0f}')
    print(f'    Middle EV:     ${ev_mb:.2f} (base) → ${ev_mn:.2f}  '
          f'(SL tightened to {b23.ATR_SL_MIDDLE}x)')
    print(f'    Middle total:  ${tot_mb*2:+,.0f} → ${tot_mn*2:+,.0f}  '
          f'delta=${((tot_mn-tot_mb)*2):+,.0f}')
    print(f'    Late EV:       ${ev_lb:.2f} (base) → ${ev_ln:.2f}  '
          f'(size × {lm})')
    print(f'    Late total:    ${tot_lb*2:+,.0f} → ${tot_ln*2:+,.0f}  '
          f'delta=${((tot_ln-tot_lb)*2):+,.0f}')

# ── Verdict ───────────────────────────────────────────────────────
print(f'\n{SEP}')
print('  VERDICT')
print(SEP)
for name, enabled, lm in CONFIGS:
    all_pnl = [t['pnl_dollar'] for t in results[name]['all']]
    n, wr, ev, pf, tot = stats(all_pnl)
    red_months = sum(1 for mo in MONTHS
                     if sum(results[name]['by_mo'][mo])*2 < 0)
    print(f'  {name:<26}  EV=${ev:.2f}  WR={wr}%  Annual=${tot*2:,.0f}'
          f'  Red months={red_months}')
print(SEP)
