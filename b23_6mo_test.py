"""
Boof 23 — 6-Month Backtest (Dec 2025 – May 2026)
No ETFs (QQQ/SPY excluded) — BOOFINGTON23 symbols only
ATR_MULT = 0.6 (fixed config)
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof23 as bt
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime
from collections import defaultdict
import numpy as np

TRADE = 200
TP_PCT = 0.40
SL_PCT = -0.10

# BOOFINGTON23 — no ETFs
SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'PLTR']

# Hardcoded Alpaca paper credentials (updated Jun 8 2026)
creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Last 6 months
months = [
    ('Dec 25', datetime(2025,12,1), datetime(2025,12,31), 23),
    ('Jan 26', datetime(2026,1,1), datetime(2026,1,31), 23),
    ('Feb 26', datetime(2026,2,1), datetime(2026,2,28), 20),
    ('Mar 26', datetime(2026,3,1), datetime(2026,3,31), 21),
    ('Apr 26', datetime(2026,4,1), datetime(2026,4,30), 22),
    ('May 26', datetime(2026,5,1), datetime(2026,5,31), 21),
]

print('=' * 60)
print('BOOF 23.0 — 6-Month Backtest (ATR_MULT=0.6)')
print('Symbols: ' + ', '.join(SYMBOLS))
print('=' * 60)
print()

all_trades = []

for label, start, end, days in months:
    print(f'  {label}...', end=' ', flush=True)
    month_trades = 0
    for sym in SYMBOLS:
        df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
        if df is None or len(df) < 100:
            continue
        trades = bt.run_boof23(df, symbol=sym)
        for t in trades:
            sz = TRADE
            pnl = TP_PCT * sz if t['exit_type'] == 'tp' else SL_PCT * sz if t['exit_type'] == 'sl' else 0.08 * sz
            t['pnl_dollar'] = pnl
            t['month'] = label
            all_trades.append(t)
            month_trades += 1
    print(f'{month_trades} trades')

print()
print('=' * 60)
print('RESULTS')
print('=' * 60)

if not all_trades:
    print('No trades generated')
else:
    pnls = np.array([t['pnl_dollar'] for t in all_trades])
    pos = pnls[pnls > 0]
    neg = pnls[pnls < 0]
    
    n = len(pnls)
    wr = len(pos) / n * 100
    pf = pos.sum() / abs(neg.sum()) if len(neg) > 0 else 999
    ev = pnls.mean()
    total = pnls.sum()
    
    tdays = sum(d for _,_,_,d in months)
    
    print(f'  Total trades:  {n}')
    print(f'  Trades/day:    {n/tdays:.1f}')
    print(f'  Win rate:      {wr:.1f}%')
    print(f'  Profit factor: {pf:.2f}')
    print(f'  EV/trade:      ${ev:.2f}')
    print(f'  6-month P&L:   ${total:,.0f}')
    print(f'  Annualized:    ${total*2:,.0f}')
    print()
    
    by_month = defaultdict(list)
    for t in all_trades:
        by_month[t['month']].append(t['pnl_dollar'])
    
    print('Monthly breakdown:')
    print(f'  {"Month":<10} {"Trades":>8} {"WR":>8} {"P&L":>12}')
    print('  ' + '-' * 40)
    running = 0
    for label,_,_,_ in months:
        if label in by_month:
            mpnls = np.array(by_month[label])
            mpos = mpnls[mpnls > 0]
            mwr = len(mpos) / len(mpnls) * 100
            mtot = mpnls.sum()
            running += mtot
            print(f'  {label:<10} {len(mpnls):>8} {mwr:>7.1f}% ${mtot:>10,.0f} (cum ${running:,.0f})')
    
    print()
    
    by_sym = defaultdict(list)
    for t in all_trades:
        by_sym[t['symbol']].append(t['pnl_dollar'])
    
    print('Per-symbol:')
    print(f'  {"Symbol":<8} {"Trades":>8} {"WR":>8} {"6mo P&L":>12}')
    print('  ' + '-' * 40)
    for sym in SYMBOLS:
        if sym in by_sym:
            spnls = np.array(by_sym[sym])
            spos = spnls[spnls > 0]
            swr = len(spos) / len(spnls) * 100
            stot = spnls.sum()
            print(f'  {sym:<8} {len(spnls):>8} {swr:>7.1f}% ${stot:>10,.0f}')

print('=' * 60)
