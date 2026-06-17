"""Fetch missing symbols from Alpaca"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime
import pickle
import os

KEY    = 'AKXYPKTGTYKE2PN2GPP4U5VJHU'
SECRET = '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'

MISSING = ['SOFI','JPM','GS','MS','BAC','WFC','C','SCHW','BLK',
           'XOM','CVX','COP','SLB','EOG','MPC','VLO','PSX',
           'RCL','CCL','BKNG','EXPE']

start = datetime(2025, 1, 1)
end   = datetime(2026, 6, 9)

os.makedirs('boof_cache', exist_ok=True)

for sym in MISSING:
    out = f"boof_cache/{sym}_2025-01-01_2026-12-31.pkl"
    if os.path.exists(out):
        print(f"  {sym}: already cached")
        continue
    print(f"  Fetching {sym}...", end=' ')
    df = fetch_alpaca_bars(sym, start, end, '1Min', KEY, SECRET)
    if df is not None and len(df) > 0:
        with open(out, 'wb') as f:
            pickle.dump(df, f)
        print(f"OK ({len(df)} bars)")
    else:
        print("FAILED")
