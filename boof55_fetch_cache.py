"""Fetch and cache all symbol data to parquet files for fast reuse."""
import alpaca_trade_api as tradeapi
import pandas as pd
import os
import pytz

ET  = pytz.timezone("America/New_York")
api = tradeapi.REST('PKKPME54QJA3KBPAJ3QZZOJXDF','J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y','https://paper-api.alpaca.markets')

SYMBOLS = ["TSLA","NVDA","AMD","HOOD","COIN","APP","MSFT","AMZN","META","PLTR","UPST","SMCI","MSTR","CRWD","AVGO"]
START = "2026-04-01"
END   = "2026-06-13"
os.makedirs("cache55", exist_ok=True)

for sym in SYMBOLS:
    path = f"cache55/{sym}.parquet"
    if os.path.exists(path):
        print(f"  {sym} already cached")
        continue
    print(f"  {sym} fetching...", flush=True)
    df = api.get_bars(sym, '1Min', start=START, end=END, feed='iex', limit=50000).df
    df.to_parquet(path)
    print(f"  {sym} saved {len(df)} bars")

print("done")
