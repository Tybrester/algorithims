"""
Fetch 6-month 1m bars for BOOF53 symbol universe
Saves: boof51_{SYM}_1m.csv  (same format as existing QQQ/SPY files)
"""
import datetime, sys
import pandas as pd
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

PAPER_KEY    = "PK7N52NHGPS2GBVZU64BCUEDNO"
PAPER_SECRET = "B3uwbzRDHZeDwt5riUd3G4U9oxnELTukfCKGovZx9K9E"
ET           = pytz.timezone("America/New_York")

SYMBOLS = ["NVDA","TSLA","AMD","META","AAPL","MSFT","AMZN","PLTR","IWM"]
# SPY and QQQ already exist — skip them
import os
SYMBOLS = [s for s in SYMBOLS if not os.path.exists(f"boof51_{s}_1m.csv")]

client = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
now    = datetime.datetime.now(ET)
start  = now - datetime.timedelta(days=182)

print(f"Fetching {len(SYMBOLS)} symbols: {SYMBOLS}", flush=True)
print(f"Range: {start.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')}\n", flush=True)

for sym in SYMBOLS:
    out = f"boof51_{sym}_1m.csv"
    print(f"{sym}...", end=" ", flush=True)
    try:
        req = StockBarsRequest(
            symbol_or_symbols=sym,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            start=start, end=now
        )
        df = client.get_stock_bars(req).df.reset_index()
        df = df.rename(columns={"timestamp":"time"})
        df["time"] = pd.to_datetime(df["time"]).dt.tz_convert(ET)
        df = df[df["time"].dt.time >= datetime.time(9, 0)]   # include premarket
        df = df[df["time"].dt.time <= datetime.time(16, 0)]
        df.to_csv(out, index=False)
        print(f"{len(df):,} bars → {out}", flush=True)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)

print("\nDone.", flush=True)
