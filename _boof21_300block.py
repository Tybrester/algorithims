"""
Boof 21.0 — Rolling 300-trade blocks over last 6 months (Dec 25 → May 26)
Fixed +35% TP / -18% SL / +8% time exit
"""
import pickle, sys
import numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21

TRADE  = 200
TP     = 0.35
SL     = -0.18
TM     = 0.08
BLOCK  = 300

SYMBOLS = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']

MONTHS = [
    ('Dec 25', 'Dec 25', 23, '_boof21_cache.pkl'),
    ('Jan 26', 'Jan 26', 22, '_boof_2026_cache.pkl'),
    ('Feb 26', 'Feb 26', 20, '_boof_2026_cache.pkl'),
    ('Mar 26', 'Mar 26', 21, '_boof_2026_cache.pkl'),
    ('Apr 26', 'Apr 26', 22, '_boof_2026_cache.pkl'),
    ('May 26', 'May 26', 18, '_boof_2026_cache.pkl'),
]

print('Loading caches...')
cache25 = pickle.load(open('_boof21_cache.pkl','rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl','rb'))

def get_df(sym, mo_key, cache_file):
    if cache_file == '_boof21_cache.pkl':
        return cache25.get((sym, mo_key))
    return cache26.get((sym, mo_key))

print('Collecting signals...')
all_signals = []

for mo_label, mo_key, tdays, cache_file in MONTHS:
    mo_sigs = []
    for sym in SYMBOLS:
        df = get_df(sym, mo_key, cache_file)
        if df is None or len(df) < 100: continue
        trades = bt21.backtest(df, symbol=sym)
        for t in trades:
            et = t['exit_type']
            pnl = TRADE*TP if et=='tp' else TRADE*SL if et=='stop' else TRADE*TM
            mo_sigs.append({'pnl': pnl, 'exit_type': et, 'month': mo_label, 'sym': sym})
    all_signals.extend(mo_sigs)
    print(f'  {mo_label}: {len(mo_sigs)} signals')

print(f'\nTotal signals: {len(all_signals)}')
print(f'Block size: {BLOCK} trades')
print(f'Total blocks: {len(all_signals) // BLOCK}\n')

def block_stats(pnls):
    arr   = np.array(pnls)
    wins  = arr[arr > 0]; losses = arr[arr < 0]
    n     = len(arr)
    wr    = round(len(wins)/n*100, 1)
    pf    = round(float(sum(wins)/max(abs(sum(losses)), 0.01)), 2)
    ev    = round(float(np.mean(arr)), 2)
    total = round(float(sum(arr)), 2)
    cum   = np.cumsum(arr)
    peak  = np.maximum.accumulate(cum)
    dd    = round(float((peak - cum).max()), 2)
    sharpe= round((np.mean(arr)/np.std(arr, ddof=1))*np.sqrt(n), 2) if np.std(arr, ddof=1) > 0 else 0
    return wr, pf, ev, total, dd, sharpe

print(f'{"="*80}')
print(f'BOOF 21.0 | Rolling {BLOCK}-Trade Blocks | Dec 25 → May 26')
print(f'+35% TP / -18% SL / +8% time exit | $200/trade')
print(f'{"="*80}')
print(f'{"Block":<8} {"Trades":<8} {"Months":<22} {"WR%":<7} {"PF":<7} {"EV":>7} {"Total$":>9} {"MaxDD$":>8} {"Sharpe":>8}')
print(f'{"-"*80}')

block_results = []
for b in range(len(all_signals) // BLOCK):
    start_i = b * BLOCK
    block   = all_signals[start_i : start_i + BLOCK]
    pnls    = [s['pnl'] for s in block]
    wr, pf, ev, total, dd, sharpe = block_stats(pnls)
    mo_start = block[0]['month']; mo_end = block[-1]['month']
    mo_range = mo_start if mo_start == mo_end else f'{mo_start}→{mo_end}'
    flag = '▼' if total < 0 else ' '
    block_results.append((b+1, wr, pf, ev, total, dd, sharpe, mo_range))
    print(f'#{b+1:<7} {BLOCK:<8} {mo_range:<22} {wr:<7} {pf:<7} ${ev:>6} {flag}${total:>8,.2f} ${dd:>7,.2f} {sharpe:>8}')

# Remainder
remainder = all_signals[(len(all_signals)//BLOCK)*BLOCK:]
if remainder:
    pnls = [s['pnl'] for s in remainder]
    wr, pf, ev, total, dd, sharpe = block_stats(pnls)
    mo_start = remainder[0]['month']; mo_end = remainder[-1]['month']
    mo_range = mo_start if mo_start == mo_end else f'{mo_start}→{mo_end}'
    flag = '▼' if total < 0 else ' '
    print(f'#{len(block_results)+1:<7} {len(remainder):<8} {mo_range:<22} {wr:<7} {pf:<7} ${ev:>6} {flag}${total:>8,.2f} ${dd:>7,.2f} {sharpe:>8}  (partial)')

print(f'{"-"*80}')

# Summary
all_pnls = [s['pnl'] for s in all_signals]
arr_all  = np.array(all_pnls)
wins_all = arr_all[arr_all>0]; losses_all = arr_all[arr_all<0]
pf_all   = round(float(sum(wins_all)/max(abs(sum(losses_all)),0.01)),2)
wr_all   = round(len(wins_all)/len(arr_all)*100,1)
ev_all   = round(float(np.mean(arr_all)),2)
total_all= round(float(sum(arr_all)),2)
pfs = [r[2] for r in block_results]

print(f'\n{"="*80}')
print(f'6-MONTH SUMMARY ({len(all_signals)} total signals, {len(block_results)} full blocks)')
print(f'{"="*80}')
print(f'  Overall WR:        {wr_all}%')
print(f'  Overall PF:        {pf_all}')
print(f'  Overall EV/trade:  ${ev_all}')
print(f'  Total P&L:         ${total_all:,.2f}')
print(f'  PF range:          {min(pfs):.2f} – {max(pfs):.2f}  (across all blocks)')
print(f'  Winning blocks:    {sum(1 for r in block_results if r[4]>0)}/{len(block_results)}')
print(f'  Min block P&L:     ${min(r[4] for r in block_results):,.2f}')
print(f'  Max block P&L:     ${max(r[4] for r in block_results):,.2f}')
print(f'{"="*80}')
