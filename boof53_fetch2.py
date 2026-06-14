"""Fetch 6-month 1m bars for new symbols"""
import datetime, os, sys
import pandas as pd
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

PAPER_KEY    = "PK7N52NHGPS2GBVZU64BCUEDNO"
PAPER_SECRET = "B3uwbzRDHZeDwt5riUd3G4U9oxnELTukfCKGovZx9K9E"
ET           = pytz.timezone("America/New_York")

NEW_SYMS = ["AVGO","NFLX","CRM","MU","ARM","COIN","SMCI","GOOGL",
            "ORCL","ADBE","APP","HIMS","RKLB","HOOD","TEM","JPM",
            "COST","WMT","LLY","UNH"]

SYMBOLS = [s for s in NEW_SYMS if not os.path.exists(f"boof51_{s}_1m.csv")]
if not SYMBOLS:
    print("All files already exist."); sys.exit(0)

client = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
now    = datetime.datetime.now(ET)
start  = now - datetime.timedelta(days=182)

print(f"Fetching {len(SYMBOLS)} symbols: {SYMBOLS}")
print(f"Range: {start.strftime('%Y-%m-%d')} -> {now.strftime('%Y-%m-%d')}\n")

for sym in SYMBOLS:
    print(f"  {sym}...", end=" ", flush=True)
    try:
        req = StockBarsRequest(
            symbol_or_symbols=sym,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            start=start, end=now
        )
        df = client.get_stock_bars(req).df.reset_index()
        df = df.rename(columns={"timestamp": "time"})
        df["time"] = pd.to_datetime(df["time"]).dt.tz_convert(ET)
        df = df[df["time"].dt.time >= datetime.time(4, 0)]
        df = df[df["time"].dt.time <= datetime.time(16, 0)]
        df.to_csv(f"boof51_{sym}_1m.csv", index=False)
        print(f"{len(df):,} bars saved")
    except Exception as e:
        print(f"ERROR: {e}")

print("\nDone.")
