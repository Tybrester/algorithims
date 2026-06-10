"""Quick 1-week backtest - Boof 22 & 23 on 5 symbols"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']
start = datetime.now() - timedelta(days=7)
end = datetime.now()

print(f"\n{'='*50}")
print(f"1-WEEK BACKTEST: {start.date()} to {end.date()}")
print(f"Symbols: {', '.join(SYMBOLS)}")
print(f"{'='*50}\n")

all_trades = []

for sym in SYMBOLS:
    try:
        df = yf.download(sym, start=start, end=end, interval='5m', progress=False)
        if len(df) < 50:
            continue
        
        # Simple fractal detection
        highs = df['High'].values
        lows = df['Low'].values
        closes = df['Close'].values
        
        trades = 0
        wins = 0
        
        for i in range(3, len(df)-3):
            # Fractal peak (short signal)
            if highs[i] > max(highs[i-3:i]) and highs[i] > max(highs[i+1:i+4]):
                trades += 1
                # Check if price dropped 15% within 30 bars
                future_lows = lows[i+1:min(i+31, len(df))]
                if len(future_lows) > 0 and min(future_lows) < closes[i] * 0.985:
                    wins += 1
            
            # Fractal trough (long signal)
            if lows[i] < min(lows[i-3:i]) and lows[i] < min(lows[i+1:i+4]):
                trades += 1
                # Check if price rose 50% within 30 bars
                future_highs = highs[i+1:min(i+31, len(df))]
                if len(future_highs) > 0 and max(future_highs) > closes[i] * 1.50:
                    wins += 1
        
        wr = (wins/trades*100) if trades > 0 else 0
        print(f"{sym:5}: {trades:3} trades | {wr:5.1f}% WR")
        all_trades.append({'sym': sym, 'trades': trades, 'wins': wins})
    except:
        pass

if all_trades:
    total = sum(t['trades'] for t in all_trades)
    wins = sum(t['wins'] for t in all_trades)
    wr = wins/total*100 if total > 0 else 0
    print(f"{'-'*50}")
    print(f"TOTAL: {total} trades | {wr:.1f}% WR")
    print(f"Daily avg: {total/5:.1f} trades")

print(f"{'='*50}\n")
