"""
BOOF51 — Step 1: Fetch and save 6-month 1-min bars for SPY and QQQ
Run once: python boof51_fetch.py
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
SYMBOLS      = ["SPY", "QQQ"]

client = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
now    = datetime.datetime.now(ET)
start  = now - datetime.timedelta(days=182)

for sym in SYMBOLS:
    out = f"boof51_{sym}_1m.csv"
    print(f"{sym}: fetching {start.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')}...", flush=True)
    try:
        req  = StockBarsRequest(symbol_or_symbols=sym,
                                timeframe=TimeFrame(1, TimeFrameUnit.Minute),
                                start=start, end=now)
        df   = client.get_stock_bars(req).df.reset_index()
        df   = df.rename(columns={"timestamp": "time"})
        df["time"] = pd.to_datetime(df["time"]).dt.tz_convert(ET)
        df   = df[df["time"].dt.time >= datetime.time(9, 30)]
        df   = df[df["time"].dt.time <= datetime.time(16, 0)]
        df.to_csv(out, index=False)
        print(f"  saved {len(df):,} bars to {out}", flush=True)
    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        sys.exit(1)

print("Done.", flush=True)
