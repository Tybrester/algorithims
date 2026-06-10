"""
Quick test - Count trades across all 5 symbols for 1 day
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof23 as bt
from backtest_signals import fetch_alpaca_bars
from datetime import datetime

creds = {
    'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU',
    'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'
}

symbols = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']
start = datetime(2026, 3, 10)
end = datetime(2026, 3, 11)

total_trades = 0
print("Testing March 10, 2026:")
print("-" * 40)

for sym in symbols:
    df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
    if df is not None and len(df) > 0:
        trades = bt.run_boof23(df, symbol=sym)
        print(f'{sym}: {len(trades)} trades')
        total_trades += len(trades)
    else:
        print(f'{sym}: NO DATA')

print("-" * 40)
print(f'TOTAL: {total_trades} trades across 5 symbols')
print(f'Expected: 50+ trades/day')
if total_trades >= 50:
    print('Status: GOOD ✓')
else:
    print('Status: LOW ✗')
