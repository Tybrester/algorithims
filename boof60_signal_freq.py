import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

ET = pytz.timezone('America/New_York')

# Combined universe
SYMBOLS = [
    # BOOF55 (gap-up breakout)
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    # Extra high-vol names
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX'
]

LOOKBACK_DAYS = 10

def get_daily(sym):
    t = yf.Ticker(sym)
    h = t.history(period='30d', interval='1d')
    return h

def get_intraday(sym):
    t = yf.Ticker(sym)
    h = t.history(period='5d', interval='1m', prepost=True)
    if h.index.tz is None:
        h.index = h.index.tz_localize('UTC')
    h.index = h.index.tz_convert(ET)
    return h

print(f"Analyzing signal frequency across {len(SYMBOLS)} symbols over {LOOKBACK_DAYS} days...\n")

long_signals = 0
short_signals = 0
total_days = 0
signal_log = []

for sym in SYMBOLS:
    try:
        daily = get_daily(sym)
        if len(daily) < 3:
            continue

        for i in range(1, min(LOOKBACK_DAYS, len(daily)-1)):
            prev  = daily.iloc[-(i+1)]
            today = daily.iloc[-i]

            pdh       = prev['High']
            prev_close = prev['Close']
            today_open = today['Open']
            today_close = today['Close']
            today_high = today['High']

            gap_pct = (today_open - prev_close) / prev_close * 100

            # LONG signal: gap up > 1% + broke PDH during day
            if gap_pct > 1.0 and today_high > pdh:
                long_signals += 1
                signal_log.append((sym, 'LONG', round(gap_pct,2), daily.index[-i].date()))

            # SHORT signal: opened near/above PDH and rejected (closed below open)
            near_pdh = abs(today_open - pdh) / pdh < 0.015  # within 1.5% of PDH
            rejected = today_close < today_open * 0.995     # closed 0.5% below open
            if near_pdh and rejected:
                short_signals += 1
                signal_log.append((sym, 'SHORT', round(gap_pct,2), daily.index[-i].date()))

        total_days = LOOKBACK_DAYS

    except Exception as e:
        pass

print(f"Results over ~{total_days} trading days across {len(SYMBOLS)} symbols:")
print(f"  LONG signals (gap-up + PDH break): {long_signals}")
print(f"  SHORT signals (PDH reject):        {short_signals}")
print(f"  TOTAL signals:                     {long_signals + short_signals}")
print(f"  Avg signals/day:                   {(long_signals + short_signals) / total_days:.1f}")
print(f"  Avg long/day:                      {long_signals / total_days:.1f}")
print(f"  Avg short/day:                     {short_signals / total_days:.1f}")

print(f"\nTop signals:")
df = pd.DataFrame(signal_log, columns=['sym','dir','gap%','date'])
print(df.groupby(['sym','dir']).size().sort_values(ascending=False).head(20).to_string())
