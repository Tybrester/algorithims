"""Check what data we actually got"""
import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta

ALPACA_API_KEY = "AKAQMRBMRXN6676IET6N5VOCTH"
ALPACA_SECRET_KEY = "AbAnxL7xjfZH5MiTYZcjFnL3YkqxnYTNnwkJpnHWGBiC"
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

end = datetime.now()
start = end - timedelta(days=14)

print(f"Checking SPY data from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}")
print("="*50)

try:
    df = api.get_bars(
        'SPY', '5Min',
        start=start.strftime('%Y-%m-%d'),
        end=end.strftime('%Y-%m-%d'),
        limit=10000, feed='iex'
    ).df
    
    print(f"Got {len(df)} bars")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")
    print(f"\nFirst 5 rows:")
    print(df.head())
    print(f"\nLast 5 rows:")
    print(df.tail())
    
except Exception as e:
    print(f"Error: {e}")
