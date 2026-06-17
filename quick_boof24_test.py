"""Quick BOOF 24 Test - 1 Week Alpaca Data"""
import alpaca_trade_api as tradeapi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Your Alpaca credentials
ALPACA_API_KEY = "AKAQMRBMRXN6676IET6N5VOCTH"
ALPACA_SECRET_KEY = "AbAnxL7xjfZH5MiTYZcjFnL3YkqxnYTNnwkJpnHWGBiC"
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

# Just test SPY for 1 week
end = datetime.now()
start = end - timedelta(days=7)

print("Fetching SPY 5m data (1 week)...")
try:
    bars = api.get_bars(
        'SPY',
        '5Min',
        start=start.strftime('%Y-%m-%d'),
        end=end.strftime('%Y-%m-%d'),
        limit=10000,
        feed='iex'
    ).df
    print(f"Got {len(bars)} bars")
    print(bars.head())
    print("\n✅ Alpaca connection working!")
except Exception as e:
    print(f"Error: {e}")
