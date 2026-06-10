"""Debug ORB timing"""
import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta
import pandas as pd

ALPACA_API_KEY = "AKAQMRBMRXN6676IET6N5VOCTH"
ALPACA_SECRET_KEY = "AbAnxL7xjfZH5MiTYZcjFnL3YkqxnYTNnwkJpnHWGBiC"
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

# Fetch one day
end = datetime.now()
start = end - timedelta(days=7)

print("Fetching SPY 5m data...")
df = api.get_bars(
    'SPY', '5Min',
    start=start.strftime('%Y-%m-%d'),
    end=end.strftime('%Y-%m-%d'),
    limit=1000,
    feed='iex'
).df

df = df.reset_index()
print(f"Got {len(df)} bars")
print("\nFirst 20 timestamps:")
print(df.head(20))

# Check timezone
print(f"\nTimestamp column: {df.columns[0]}")
print(f"Type: {type(df.iloc[0, 0])}")

# Parse timestamps
df['time'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.iloc[:, 0])
print(f"\nParsed times (first 30):")
for i in range(min(30, len(df))):
    t = df['time'].iloc[i]
    print(f"  {t} (hour={t.hour}, minute={t.minute})")
