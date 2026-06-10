"""
BOOF 28 - Single Day Test (FAST)
Test logic on one day only - no long backtest
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Just 20 stocks for speed
STOCKS = [
    "AAPL","MSFT","NVDA","AMZN","META","TSLA","AMD","JPM","NFLX","COIN",
    "GME","PLTR","SPY","QQQ","IWM","XOM","DIS","UBER","BABA","JD"
]

test_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
fetch_start = test_date - timedelta(days=25)
fetch_end = test_date + timedelta(days=1)

print('='*80)
print(f'SINGLE DAY TEST: {test_date.date()}')
print(f'20 stocks | 2-hour window | 1% target')
print('='*80)

total_trades = 0
total_pnl = 0

for sym in STOCKS:
    try:
        df = fetch_alpaca_bars(sym, fetch_start, fetch_end, '5Min', creds['api_key'], creds['secret_key'])
        if df is None or len(df) < 20:
            continue
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        
        # Get just today
        today = df[df['timestamp'].dt.date == test_date.date()].reset_index(drop=True)
        if len(today) < 24:
            continue
        
        # Simple volume spike detection
        avg_vol = today['volume'].mean()
        
        for i in range(min(19, len(today) - 6)):
            vol_ratio = today['volume'].iloc[i] / avg_vol
            if vol_ratio < 3.0:
                continue
            
            # 5-bar move
            move = (today['close'].iloc[i+5] - today['close'].iloc[i]) / today['close'].iloc[i]
            if abs(move) < 0.01:  # Need 1% move
                continue
            
            # Direction
            direction = 'LONG' if move > 0 else 'SHORT'
            entry_price = today['close'].iloc[i+5]
            
            # Simulate 1% TP / 0.5% SL
            pnl = None
            if direction == 'LONG':
                for j in range(i+6, min(i+18, len(today))):
                    if today['high'].iloc[j] >= entry_price * 1.01:
                        pnl = 1.0
                        break
                    if today['low'].iloc[j] <= entry_price * 0.995:
                        pnl = -0.5
                        break
            else:
                for j in range(i+6, min(i+18, len(today))):
                    if today['low'].iloc[j] <= entry_price * 0.99:
                        pnl = 1.0
                        break
                    if today['high'].iloc[j] >= entry_price * 1.005:
                        pnl = -0.5
                        break
            
            if pnl:
                total_trades += 1
                total_pnl += pnl
                print(f"{sym:5s} {direction:5s} bar {i:2d} | {vol_ratio:.1f}x vol | {move*100:+.2f}% move | P&L: {pnl:+.1f}%")
        
        time.sleep(0.02)
    except:
        pass

print('='*80)
if total_trades > 0:
    print(f"TOTAL: {total_trades} trades, {total_pnl:+.2f}% P&L, {total_pnl/total_trades:.2f}% avg")
else:
    print("No trades found")
print('='*80)
