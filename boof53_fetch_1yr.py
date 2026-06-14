"""
Fetch 1 year of 1m bars for GOOGL, META, HIMS, RIOT
Saves as boof53_{sym}_1m_1yr.csv (separate from 6m files)
"""
import datetime, os
import pandas as pd
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

PAPER_KEY    = "PK7N52NHGPS2GBVZU64BCUEDNO"
PAPER_SECRET = "B3uwbzRDHZeDwt5riUd3G4U9oxnELTukfCKGovZx9K9E"
ET           = pytz.timezone("America/New_York")

SYMS = ["GOOGL", "META", "HIMS", "RIOT"]

client = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
now    = datetime.datetime.now(ET)
start  = now - datetime.timedelta(days=365)

print(f"Fetching {start.strftime('%Y-%m-%d')} -> {now.strftime('%Y-%m-%d')}")
print(f"Symbols: {SYMS}\n")

for sym in SYMS:
    out = f"boof53_{sym}_1m_1yr.csv"
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
        print(f"saved {len(df):,} bars  ({start.strftime('%Y-%m-%d')} -> {now.strftime('%Y-%m-%d')})")
    except Exception as e:
        print(f"ERROR: {e}")

print("\nDone.")
