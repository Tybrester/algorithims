"""
Boof 23 — 6-Month Backtest (Jan–Jun 2025)
Clean baseline run: CLUSTER_COMPLETION=False, LOW_VOL_FILTER=False
9 symbols from expanded list.
"""
import pickle, sys
import numpy as np
from collections import defaultdict

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof23 as b23

b23.CLUSTER_COMPLETION = False
b23.LOW_VOL_FILTER     = False

SYMS   = ['NVDA','AAPL','MSFT','AMZN','GOOGL','AVGO','META','TSLA','LLY']
MONTHS = ['Jan','Feb','Mar','Apr','May','Jun']
MDAYS  = [23, 20, 21, 22, 21, 21]
TOTAL_DAYS = sum(MDAYS)
B23_EXP = 200; B23_CORE = 500

print('Loading cache...')
cache = pickle.load(open('_boof22_cache.pkl','rb'))
print('  Done.\n')

all_trades = []
by_month   = defaultdict(list)
by_sym     = defaultdict(list)

for mo in MONTHS:
    for sym in SYMS:
        df = cache.get((sym, mo))
        if df is None or len(df) < 100: continue
        for t in b23.run_boof23(df, symbol=sym):
            size = B23_CORE if t['tier']=='core' else B23_EXP
            pnl  = t['pnl_pct'] * size
            t['pnl_dollar'] = pnl
            t['month']      = mo
            all_trades.append(t)
            by_month[mo].append(pnl)
            by_sym[sym].append(pnl)

def stats(pnl_list):
    if not pnl_list: return 0, 0.0, 0.0, 0.0, 0.0
    p   = np.array(pnl_list)
    pos = p[p>0]; neg = p[p<0]
    wr  = len(pos)/len(p)*100
    ev  = float(np.mean(p))
    pf  = float(sum(pos)/max(abs(sum(neg)),0.01))
    tot = float(sum(p))
    return len(p), round(wr,1), round(ev,2), round(pf,2), round(tot,0)

SEP = '=' * 68

n_all, wr_all, ev_all, pf_all, tot_all = stats([t['pnl_dollar'] for t in all_trades])
half_annual = tot_all * 2   # annualized from 6mo

print(SEP)
print('  BOOF 23 — 6-MONTH BACKTEST  (Jan – Jun 2025)')
print(SEP)
print(f'  Total trades:   {n_all}')
print(f'  Trades/day:     {n_all/TOTAL_DAYS:.1f}')
print(f'  Win rate:       {wr_all:.1f}%')
print(f'  EV / trade:     ${ev_all:.2f}')
print(f'  Profit factor:  {pf_all:.2f}')
print(f'  6-month P&L:    ${tot_all:,.0f}')
print(f'  Annualized est: ${half_annual:,.0f}')

# Exit type breakdown
by_exit = defaultdict(list)
for t in all_trades:
    by_exit[t['exit_type']].append(t['pnl_dollar'])
print(f'\n  Exit breakdown:')
print(f'  {"Type":<10}  {"Count":>7}  {"WR":>7}  {"EV":>10}  {"Total":>12}')
print(f'  {"-"*48}')
for et in ['tp','sl','time']:
    pnls = by_exit[et]
    if not pnls: continue
    n, wr, ev, _, tot = stats(pnls)
    print(f'  {et:<10}  {n:>7}  {wr:>6.1f}%  ${ev:>9.2f}  ${tot:>11,.0f}')

# Tier breakdown
by_tier = defaultdict(list)
for t in all_trades:
    by_tier[t['tier']].append(t['pnl_dollar'])
print(f'\n  Tier breakdown:')
print(f'  {"Tier":<12}  {"Count":>7}  {"WR":>7}  {"EV":>10}  {"Total":>12}  {"Size":>7}')
print(f'  {"-"*56}')
for tier, size in [('core', B23_CORE),('expanded', B23_EXP)]:
    pnls = by_tier[tier]
    if not pnls: continue
    n, wr, ev, _, tot = stats(pnls)
    print(f'  {tier:<12}  {n:>7}  {wr:>6.1f}%  ${ev:>9.2f}  ${tot:>11,.0f}  ${size:>6}')

# Monthly P&L
print(f'\n{SEP}')
print('  MONTHLY BREAKDOWN')
print(SEP)
print(f'  {"Month":<8}  {"Trades":>7}  {"WR":>7}  {"EV":>10}  {"PF":>7}  {"P&L":>12}  {"Running":>12}')
print(f'  {"-"*66}')
running = 0.0
for mo, days in zip(MONTHS, MDAYS):
    pnls = by_month[mo]
    if not pnls:
        print(f'  {mo:<8}  {"—":>7}')
        continue
    n, wr, ev, pf, tot = stats(pnls)
    running += tot * 2
    print(f'  {mo:<8}  {n:>7}  {wr:>6.1f}%  ${ev:>9.2f}  {pf:>7.2f}  ${tot*2:>11,.0f}  ${running:>11,.0f}')

# Per-symbol
print(f'\n{SEP}')
print('  PER-SYMBOL BREAKDOWN')
print(SEP)
print(f'  {"Symbol":<8}  {"Trades":>7}  {"WR":>7}  {"EV":>10}  {"PF":>7}  {"6mo P&L":>12}  {"Ann est":>12}')
print(f'  {"-"*68}')
sym_rows = []
for sym in SYMS:
    pnls = by_sym[sym]
    if not pnls: continue
    n, wr, ev, pf, tot = stats(pnls)
    sym_rows.append((sym, n, wr, ev, pf, tot))
sym_rows.sort(key=lambda x: -x[5])
for sym, n, wr, ev, pf, tot in sym_rows:
    print(f'  {sym:<8}  {n:>7}  {wr:>6.1f}%  ${ev:>9.2f}  {pf:>7.2f}  ${tot*2:>11,.0f}  ${tot*4:>11,.0f}')

# Rolling 30-day EV (every 30 trades as proxy)
print(f'\n{SEP}')
print('  ROLLING EV (every 50 trades)')
print(SEP)
print(f'  {"Window":<14}  {"Trades":>7}  {"WR":>7}  {"EV":>10}  {"Cumulative":>12}')
print(f'  {"-"*52}')
window = 50
cum = 0.0
all_pnls = [t['pnl_dollar'] for t in all_trades]
for start in range(0, len(all_pnls), window):
    chunk = all_pnls[start:start+window]
    if not chunk: break
    n, wr, ev, _, tot = stats(chunk)
    cum += tot
    label = f'T{start+1}-T{start+len(chunk)}'
    bar = '#' * int(max(0, ev) / 1) + ('-' if ev < 0 else '')
    print(f'  {label:<14}  {n:>7}  {wr:>6.1f}%  ${ev:>9.2f}  ${cum:>11,.0f}  {bar}')

# Summary verdict
print(f'\n{SEP}')
print('  6-MONTH SUMMARY')
print(SEP)
avg_monthly = tot_all / len(MONTHS)
print(f'  Avg monthly P&L:  ${avg_monthly:,.0f}')
print(f'  Best month:       {max(MONTHS, key=lambda m: sum(by_month[m]))} '
      f'(${max(sum(by_month[m])*2 for m in MONTHS if by_month[m]):,.0f})')
print(f'  Worst month:      {min(MONTHS, key=lambda m: sum(by_month[m]) if by_month[m] else 0)} '
      f'(${min(sum(by_month[m])*2 for m in MONTHS if by_month[m]):,.0f})')
print(f'  Red months:       {sum(1 for m in MONTHS if sum(by_month[m])*2 < 0)}')
print(f'  Annualized EV:    ${half_annual:,.0f}')
print(f'  EV / trade:       ${ev_all:.2f}')
print(f'  Win rate:         {wr_all:.1f}%')
print(f'  Profit factor:    {pf_all:.2f}')
print(SEP)
