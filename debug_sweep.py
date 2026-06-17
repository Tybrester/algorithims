"""Debug liquidity sweep"""
import alpaca_trade_api as tradeapi
from datetime import datetime
import pandas as pd

ALPACA_API_KEY = "AKAQMRBMRXN6676IET6N5VOCTH"
ALPACA_SECRET_KEY = "AbAnxL7xjfZH5MiTYZcjFnL3YkqxnYTNnwkJpnHWGBiC"
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

# Test one symbol, one day
df = api.get_bars(
    'NVDA', '5Min',
    start='2024-01-02',
    end='2024-01-03',
    limit=100,
    feed='iex'
).df

df = df.reset_index()
if 'timestamp' in df.columns:
    df['time'] = pd.to_datetime(df['timestamp'])
elif 'index' in df.columns:
    df['time'] = pd.to_datetime(df['index'])

print(f"Got {len(df)} bars")
print("\nFirst 10 timestamps:")
for i in range(min(10, len(df))):
    t = df['time'].iloc[i]
    
    # My new logic
    month = t.month
    is_dst = 3 <= month <= 11
    utc_offset = 4 if is_dst else 5
    et_hour = t.hour - utc_offset
    if et_hour < 0:
        et_hour += 24
    et_minute = t.minute
    mins_open = (et_hour - 9) * 60 + et_minute
    
    print(f"  {t} (month={month}, dst={is_dst}, offset={utc_offset}) -> ET {et_hour}:{et_minute:02d}, mins_open: {mins_open}")

print(f"\nDates in data:")
df['date'] = df['time'].dt.date
for d in df['date'].unique()[:3]:
    day_df = df[df['date'] == d]
    print(f"  {d}: {len(day_df)} bars, first={day_df['time'].iloc[0]}, last={day_df['time'].iloc[-1]}")
