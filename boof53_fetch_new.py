"""
Fetch 1m bars for missing symbols needed for BOOF53 Version F universe test.
Fetches ~6 months of data (same window as existing files).
"""
import datetime, sys, os
import pandas as pd
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

PAPER_KEY    = "PK7N52NHGPS2GBVZU64BCUEDNO"
PAPER_SECRET = "B3uwbzRDHZeDwt5riUd3G4U9oxnELTukfCKGovZx9K9E"
ET           = pytz.timezone("America/New_York")

MISSING = ["ASTS","LUNR","AFRM","UPST","MRVL","ANET","CRWD","PANW","MSTR","CLSK","RIOT"]

client = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
now    = datetime.datetime.now(ET)
start  = now - datetime.timedelta(days=182)

print(f"Fetching {start.strftime('%Y-%m-%d')} -> {now.strftime('%Y-%m-%d')}")
print(f"Symbols: {MISSING}\n")

for sym in MISSING:
    out = f"boof51_{sym}_1m.csv"
    if os.path.exists(out):
        print(f"{sym}: already exists, skipping")
        continue
    print(f"{sym}: fetching...", end=" ", flush=True)
    try:
        req = StockBarsRequest(
            symbol_or_symbols=sym,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            start=start, end=now
        )
        df = client.get_stock_bars(req).df.reset_index()
        df = df.rename(columns={"timestamp": "time"})
        df["time"] = pd.to_datetime(df["time"]).dt.tz_convert(ET)
        df.to_csv(out, index=False)
        print(f"saved {len(df):,} bars")
    except Exception as e:
        print(f"ERROR: {e}")

print("\nDone.")
