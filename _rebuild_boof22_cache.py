"""
Rebuild Boof 22 cache with large TP/SL so ALL signals are captured as raw data.
We use tp_pct=0.99 (99%) so nothing hits TP during the session — all exits are 'time'.
This gives us the full bar-by-bar slice per signal to re-simulate any TP/SL combo.
"""
import sys, pickle
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

SYMBOLS = ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
months = [
    ('Jan', datetime(2025,1,1),  datetime(2025,1,31)),
    ('Feb', datetime(2025,2,1),  datetime(2025,2,28)),
    ('Mar', datetime(2025,3,1),  datetime(2025,3,31)),
    ('Apr', datetime(2025,4,1),  datetime(2025,4,30)),
    ('May', datetime(2025,5,1),  datetime(2025,5,31)),
    ('Jun', datetime(2025,6,1),  datetime(2025,6,30)),
    ('Jul', datetime(2025,7,1),  datetime(2025,7,31)),
    ('Aug', datetime(2025,8,1),  datetime(2025,8,31)),
    ('Sep', datetime(2025,9,1),  datetime(2025,9,30)),
    ('Oct', datetime(2025,10,1), datetime(2025,10,31)),
    ('Nov', datetime(2025,11,1), datetime(2025,11,30)),
    ('Dec', datetime(2025,12,1), datetime(2025,12,31)),
]

creds = get_alpaca_credentials()
cache = {}

total = len(SYMBOLS) * len(months)
done = 0
for label, start, end in months:
    for sym in SYMBOLS:
        done += 1
        print(f'[{done}/{total}] {sym} {label}...', end=' ', flush=True)
        df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
        if df is None or len(df) < 100:
            print('SKIP')
            continue
        cache[(sym, label)] = df
        print(f'OK ({len(df)} bars)')

print(f'\nSaving cache with {len(cache)} entries...')
with open('_boof22_cache.pkl', 'wb') as f:
    pickle.dump(cache, f)
print('Done. Cache saved to _boof22_cache.pkl')
