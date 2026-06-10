"""
Boof 26.0 Quick Test - 3 symbols, 1 month
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime
import numpy as np

SYMBOLS = ['SPY', 'QQQ', 'NVDA']
START = datetime(2026, 5, 1)
END = datetime(2026, 5, 15)

CREDS = {
    'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU',
    'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'
}

print('=' * 60)
print('Boof 26.0 Quick Test - May 1-15 2026')
print(f'Symbols: {SYMBOLS}')
print('=' * 60)

for sym in SYMBOLS:
    print(f'\nFetching {sym}...', end=' ')
    df = fetch_alpaca_bars(sym, START, END, '5Min', CREDS['api_key'], CREDS['secret_key'])
    if df is not None:
        print(f'{len(df)} bars')
        # Simple check - just show we got data
        if len(df) > 0:
            print(f'  Date range: {df.index[0]} to {df.index[-1]}')
            print(f'  Price range: ${df["low"].min():.2f} - ${df["high"].max():.2f}')
    else:
        print('FAILED')

print('\n' + '=' * 60)
print('Data fetch test complete')
print('=' * 60)
