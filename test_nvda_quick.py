"""
Quick test - NVDA 1 month only
Boof 22, 22.5, 23, 23.5
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime
import numpy as np

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

print('Fetching NVDA Dec 2025...')
df = fetch_alpaca_bars('NVDA', datetime(2025, 12, 1), datetime(2025, 12, 31), '5Min', creds['api_key'], creds['secret_key'])

if df is None:
    print('NO DATA')
    exit()

if 'open' not in df.columns:
    df.columns = [c.lower() for c in df.columns]

print(f'Got {len(df)} bars')

# Simple ATR
def compute_atr(df, period=14):
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        h, l, c = df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i-1]
        tr = max(h-l, abs(h-c), abs(l-c))
        atr[i] = tr if i < period else atr[i-1]*(period-1)/period + tr/period
    return atr

atr = compute_atr(df)
vol_sma = df['volume'].rolling(50).mean().values

# Boof 22 - test
trades = []
for i in range(100, len(df)-20):
    if atr[i] == 0: continue
    # Simple cluster test
    if df['volume'].iloc[i] < vol_sma[i] * 1.3: continue
    close, current_atr = df['close'].iloc[i], atr[i]
    # Just test entry
    entry = close
    sl = entry - current_atr
    tp = entry + current_atr * 2
    # Check next 5 bars
    for j in range(i+1, min(i+5, len(df))):
        if df['low'].iloc[j] <= sl: trades.append(-1); break
        if df['high'].iloc[j] >= tp: trades.append(2); break
    else:
        trades.append(0)

print(f'Boof 22 test: {len(trades)} potential exits')
if trades:
    wins = sum(1 for t in trades if t > 0)
    print(f'  Wins: {wins}/{len(trades)} = {wins/len(trades)*100:.1f}%')
    print(f'  R-multiples: {trades[:10]}...')
print('Script works!')
