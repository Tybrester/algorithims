"""
Fetch full year 2022 (Jan 1 - Dec 31) 1m bars for all 21 Version H symbols.
Saves as boof53_{sym}_1m_2022.csv
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

SYMS = [
    "UPST","APP","SMCI","HIMS","ARM","GOOGL",  # PMH
    "META","AFRM",                              # PDH
    "TSLA","CLSK","HOOD",                       # 10m
    "ADBE","PANW","MU","AMD","COIN","NVDA",     # 30m
    "MRVL","AVGO",                              # 2H
    "PLTR",                                     # 4H
    "CRM",                                      # Daily
]

client = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
start  = datetime.datetime(2022, 1, 1, tzinfo=ET)
end    = datetime.datetime(2022, 12, 31, 23, 59, tzinfo=ET)

print(f"Fetching 2022 data: {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')}")
print(f"Symbols ({len(SYMS)}): {SYMS}\n")

for sym in SYMS:
    out = f"boof53_{sym}_1m_2022.csv"
    if os.path.exists(out):
        import pandas as _pd
        existing = _pd.read_csv(out)
        print(f"{sym}: already exists ({len(existing):,} bars), skipping")
        continue
    print(f"{sym}: fetching...", end=" ", flush=True)
    try:
        req = StockBarsRequest(
            symbol_or_symbols=sym,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            start=start, end=end
        )
        df = client.get_stock_bars(req).df.reset_index()
        df = df.rename(columns={"timestamp": "time"})
        df["time"] = pd.to_datetime(df["time"]).dt.tz_convert(ET)
        df.to_csv(out, index=False)
        print(f"saved {len(df):,} bars")
    except Exception as e:
        print(f"ERROR: {e}")

print("\nDone.")
