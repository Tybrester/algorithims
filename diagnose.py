import numpy as np
import pandas as pd
from datetime import datetime
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

creds   = get_alpaca_credentials()
symbols = ['SPY', 'QQQ', 'TSLA', 'NVDA', 'AMD']

print(f"{'SYM':<5} {'AVG_VOL':>12} {'%>1.5x':>7} {'%LowATR':>8} {'%BOTH':>7} {'AvgATR$':>9}")
print("-" * 55)

for sym in symbols:
    df = fetch_alpaca_bars(sym, datetime(2026,4,1), datetime(2026,4,30), '1Min',
                           api_key=creds['api_key'], secret_key=creds['secret_key'])
    df['atr']     = (df['high'] - df['low']).rolling(14).mean()
    df['vol_avg'] = df['volume'].rolling(20).mean()
    df['atr_pct'] = df['atr'].rolling(100).rank(pct=True) * 100

    fixed_pct   = (df['volume'] > df['vol_avg'] * 1.5).mean() * 100
    low_atr_pct = (df['atr_pct'] <= 40).mean() * 100
    both        = ((df['volume'] > df['vol_avg'] * 1.5) & (df['atr_pct'] <= 40)).mean() * 100
    avg_vol     = df['volume'].mean()
    avg_atr_usd = df['atr'].mean()

    print(f"{sym:<5} {avg_vol:>12.0f} {fixed_pct:>6.1f}% {low_atr_pct:>7.1f}% {both:>6.1f}% {avg_atr_usd:>9.3f}")
