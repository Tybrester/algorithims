"""
Simple Boof 24 Backtest - Run this directly
"""

import yfinance as yf
import pandas as pd
import numpy as np

print("="*60)
print("BOOF 24.0 - SIMPLE BACKTEST")
print("="*60)

symbol = "SPY"
print(f"\nTesting {symbol}...")

# Get 5m data
df = yf.Ticker(symbol).history(period="5d", interval="5m")
print(f"Downloaded {len(df)} bars")

if len(df) < 100:
    print("Not enough data")
    exit()

# Compute ATR
high, low, close = df['High'], df['Low'], df['Close']
tr1 = high - low
tr2 = abs(high - close.shift(1))
tr3 = abs(low - close.shift(1))
tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
atr = tr.rolling(window=14).mean()

# Simple swing detection
swings = []
last_high = {'idx': 0, 'price': df['High'].iloc[0]}
last_low = {'idx': 0, 'price': df['Low'].iloc[0]}
direction = ''

for i in range(1, len(df)):
    current_atr = atr.iloc[i] if pd.notna(atr.iloc[i]) else 0.01
    threshold = current_atr * 0.75
    
    if df['High'].iloc[i] > last_high['price']:
        last_high = {'idx': i, 'price': df['High'].iloc[i]}
    if df['Low'].iloc[i] < last_low['price']:
        last_low = {'idx': i, 'price': df['Low'].iloc[i]}
    
    close_price = df['Close'].iloc[i]
    
    if direction == 'up' and last_high['price'] - close_price > threshold:
        swings.append({'idx': last_high['idx'], 'price': last_high['price'], 'type': 'high'})
        direction = 'down'
        last_low = {'idx': i, 'price': df['Low'].iloc[i]}
    elif direction == 'down' and close_price - last_low['price'] > threshold:
        swings.append({'idx': last_low['idx'], 'price': last_low['price'], 'type': 'low'})
        direction = 'up'
        last_high = {'idx': i, 'price': df['High'].iloc[i]}
    elif direction == '':
        if close_price > df['High'].iloc[0] + threshold:
            direction = 'up'
        elif close_price < df['Low'].iloc[0] - threshold:
            direction = 'down'

print(f"Found {len(swings)} swings")

# Count MSB signals
msb_signals = 0
for i in range(100, len(df)):
    window_swings = [s for s in swings if s['idx'] <= i][-4:]
    if len(window_swings) < 4:
        continue
    
    highs = [s for s in window_swings if s['type'] == 'high']
    lows = [s for s in window_swings if s['type'] == 'low']
    
    if len(highs) < 2 or len(lows) < 2:
        continue
    
    trend = 'neutral'
    if highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']:
        trend = 'bullish'
    elif highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
        trend = 'bearish'
    
    current_close = df['Close'].iloc[i]
    
    if trend == 'bearish' and current_close > highs[-1]['price']:
        msb_signals += 1
    elif trend == 'bullish' and current_close < lows[-1]['price']:
        msb_signals += 1

print(f"MSB signals detected: {msb_signals}")
print("\nBacktest complete!")
print("="*60)
