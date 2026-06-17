"""Fetch yearly 1m bar data for BOOF55 symbols."""
import alpaca_trade_api as tradeapi
import pandas as pd
import os, pytz

api = tradeapi.REST('PKKPME54QJA3KBPAJ3QZZOJXDF','J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y','https://paper-api.alpaca.markets')

SYMBOLS = ["APP","NVDA","CRWD","HOOD","AMD","PLTR","COIN","TSLA"]
PERIODS = {
    "2022": ("2022-01-01","2022-12-31"),
    "2023": ("2023-01-01","2023-12-31"),
    "2024": ("2024-01-01","2024-12-31"),
    "2025_26": ("2025-01-01","2026-06-13"),
}

os.makedirs("cache55_years", exist_ok=True)

for sym in SYMBOLS:
    for label, (start, end) in PERIODS.items():
        path = f"cache55_years/{sym}_{label}.parquet"
        if os.path.exists(path):
            print(f"  {sym} {label} cached")
            continue
        print(f"  {sym} {label} fetching...", flush=True)
        try:
            df = api.get_bars(sym, '1Min', start=start, end=end, feed='iex', limit=100000).df
            df.to_parquet(path)
            print(f"  {sym} {label} saved {len(df)} bars")
        except Exception as e:
            print(f"  {sym} {label} FAILED: {e}")

print("done")
