import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime

print('Fetching SPY May 2026...')
df = fetch_alpaca_bars('SPY', datetime(2026, 5, 1), datetime(2026, 5, 7), '5Min', 
                       'AKXYPKTGTYKE2PN2GPP4U5VJHU', 
                       '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W')
print(f'Result: {len(df) if df is not None else "None"} rows')
if df is not None and len(df) > 0:
    print(f'Columns: {list(df.columns)}')
    print(df.head())
