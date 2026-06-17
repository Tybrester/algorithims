"""
Quick Boof 24 Validation - 1 Month Test
Uses yfinance for faster data fetch
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

SYMBOLS = ['SPY', 'QQQ', 'NVDA', 'META', 'AAPL', 'TSLA']

def compute_atr(df, period=14):
    high, low, close = df['High'], df['Low'], df['Close']
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def compute_vwap(df):
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    return (tp * df['Volume']).cumsum() / df['Volume'].cumsum()

def find_swings(df, atr, atr_mult=0.75):
    swings = []
    last_high = {'idx': 0, 'price': df['High'].iloc[0]}
    last_low = {'idx': 0, 'price': df['Low'].iloc[0]}
    direction = ''
    
    for i in range(1, len(df)):
        current_atr = atr.iloc[i] if pd.notna(atr.iloc[i]) else 0.01
        threshold = current_atr * atr_mult
        
        if df['High'].iloc[i] > last_high['price']:
            last_high = {'idx': i, 'price': df['High'].iloc[i]}
        if df['Low'].iloc[i] < last_low['price']:
            last_low = {'idx': i, 'price': df['Low'].iloc[i]}
        
        close = df['Close'].iloc[i]
        
        if direction == 'up' and last_high['price'] - close > threshold:
            swings.append({'idx': last_high['idx'], 'price': last_high['price'], 'type': 'high'})
            direction = 'down'
            last_low = {'idx': i, 'price': df['Low'].iloc[i]}
        elif direction == 'down' and close - last_low['price'] > threshold:
            swings.append({'idx': last_low['idx'], 'price': last_low['price'], 'type': 'low'})
            direction = 'up'
            last_high = {'idx': i, 'price': df['High'].iloc[i]}
        elif direction == '':
            if close > df['High'].iloc[0] + threshold:
                direction = 'up'
            elif close < df['Low'].iloc[0] - threshold:
                direction = 'down'
    
    return swings

def analyze_structure(df, swings):
    if len(swings) < 4:
        return None
    
    recent = swings[-4:]
    highs = [s for s in recent if s['type'] == 'high']
    lows = [s for s in recent if s['type'] == 'low']
    
    if len(highs) < 2 or len(lows) < 2:
        return None
    
    trend = 'neutral'
    if highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']:
        trend = 'bullish'
    elif highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
        trend = 'bearish'
    
    close = df['Close'].iloc[-1]
    msb_bull = False
    msb_bear = False
    msb_price = 0
    
    if trend == 'bearish' and close > highs[-1]['price']:
        msb_bull = True
        msb_price = highs[-1]['price']
    elif trend == 'bullish' and close < lows[-1]['price']:
        msb_bear = True
        msb_price = lows[-1]['price']
    
    return {
        'trend': trend,
        'msb_bull': msb_bull,
        'msb_bear': msb_bear,
        'msb_price': msb_price,
        'last_high': highs[-1]['price'],
        'last_low': lows[-1]['price']
    }

def backtest_symbol(symbol, period="1mo"):
    print(f"  {symbol}: ", end="")
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval="5m")
        
        if len(df) < 100:
            print("No data")
            return []
        
        trades = []
        atr = compute_atr(df)
        vwap = compute_vwap(df)
        
        for i in range(100, len(df) - 5):
            window = df.iloc[:i+1]
            window_atr = atr.iloc[:i+1]
            
            swings = find_swings(window, window_atr, 0.75)
            if len(swings) < 6:
                continue
            
            ms = analyze_structure(window, swings)
            if not ms or (not ms['msb_bull'] and not ms['msb_bear']):
                continue
            
            # Volume (1.25x)
            vol_sma = df['Volume'].iloc[i-20:i].mean()
            if df['Volume'].iloc[i] <= vol_sma * 1.25:
                continue
            
            # Retest
            direction = 'LONG' if ms['msb_bull'] else 'SHORT'
            found = False
            for j in range(max(0, i-10), i):
                if direction == 'LONG':
                    if df['Low'].iloc[j] <= ms['msb_price'] * 1.005 and df['Close'].iloc[j] > ms['msb_price']:
                        found = True
                        break
                else:
                    if df['High'].iloc[j] >= ms['msb_price'] * 0.995 and df['Close'].iloc[j] < ms['msb_price']:
                        found = True
                        break
            if not found:
                continue
            
            # VWAP
            if direction == 'LONG' and df['Close'].iloc[i] < vwap.iloc[i]:
                continue
            if direction == 'SHORT' and df['Close'].iloc[i] > vwap.iloc[i]:
                continue
            
            entry = df['Close'].iloc[i]
            current_atr = window_atr.iloc[i] if pd.notna(window_atr.iloc[i]) else 0.01
            
            if direction == 'LONG':
                sl = max(ms['last_low'], entry - current_atr * 1.5)
                risk = entry - sl
                tp = entry + risk * 2.0
            else:
                sl = min(ms['last_high'], entry + current_atr * 1.5)
                risk = sl - entry
                tp = entry - risk * 2.0
            
            if risk <= 0 or risk / entry > 0.05:
                continue
            
            # Simple simulation (next 20 bars)
            for j in range(i+1, min(i+20, len(df))):
                high, low = df['High'].iloc[j], df['Low'].iloc[j]
                
                if direction == 'LONG':
                    if low <= sl:
                        trades.append(-1.0)
                        break
                    if high >= tp:
                        trades.append(2.0)
                        break
                else:
                    if high >= sl:
                        trades.append(-1.0)
                        break
                    if low <= tp:
                        trades.append(2.0)
                        break
        
        print(f"{len(trades)} trades")
        return trades
        
    except Exception as e:
        print(f"Error: {e}")
        return []

print("=" * 70)
print("BOOF 24.0 - QUICK VALIDATION (1 Month, 5m bars)")
print("=" * 70)
print("\nConfig: 0.75x ATR | 1.25x Volume | Retest | VWAP")
print("=" * 70)

all_trades = {}
for symbol in SYMBOLS:
    trades = backtest_symbol(symbol, "1mo")
    all_trades[symbol] = trades

print("\n" + "=" * 70)
print("RESULTS BY SYMBOL")
print("=" * 70)
print(f"\n{'Symbol':<8} {'Trades':<8} {'Win Rate':<10} {'R/T':<8} {'Total R':<10}")
print("-" * 50)

total_all = 0
wins_all = 0
sum_r = 0

for symbol, trades in all_trades.items():
    if trades:
        total = len(trades)
        wins = sum(1 for t in trades if t > 0)
        wr = wins / total * 100
        total_r = sum(trades)
        rpt = total_r / total
        
        total_all += total
        wins_all += wins
        sum_r += total_r
        
        print(f"{symbol:<8} {total:<8} {wr:<10.1f} {rpt:<8.3f} {total_r:<+10.1f}")
    else:
        print(f"{symbol:<8} {'0':<8} {'N/A':<10} {'N/A':<8} {'0.0':<10}")

print("-" * 50)
if total_all > 0:
    wr_all = wins_all / total_all * 100
    rpt_all = sum_r / total_all
    print(f"{'TOTAL':<8} {total_all:<8} {wr_all:<10.1f} {rpt_all:<8.3f} {sum_r:<+10.1f}")

print("\n" + "=" * 70)
print("VALIDATION ASSESSMENT")
print("=" * 70)

if total_all > 0:
    if rpt_all >= 0.10:
        print(f"✅ EXCELLENT: R/T = {rpt_all:.3f} (> 0.10)")
    elif rpt_all >= 0.05:
        print(f"✅ GOOD: R/T = {rpt_all:.3f} (0.05 - 0.10)")
    elif rpt_all > 0:
        print(f"⚠️ MARGINAL: R/T = {rpt_all:.3f} (0 - 0.05)")
    else:
        print(f"❌ FAIL: R/T = {rpt_all:.3f} (< 0)")
    
    # Check all symbols profitable
    all_profitable = all(sum(t) > 0 for t in all_trades.values() if t)
    if all_profitable:
        print("✅ All symbols profitable")
    else:
        print("⚠️ Some symbols negative")

print("=" * 70)
