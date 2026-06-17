"""
Fetch 2022-01-01 to 2024-12-31 (3 years) of 1-min bars for the full candidate universe
Save to data/train/ as parquet files
Uses Alpaca SIP feed
"""
import os, time
import pandas as pd
from alpaca_trade_api import REST
from alpaca_trade_api.rest import TimeFrame

API_KEY    = "PKKPME54QJA3KBPAJ3QZZOJXDF"
API_SECRET = "J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y"
BASE_URL   = "https://paper-api.alpaca.markets"

TRAIN_DIR = "data/train"
os.makedirs(TRAIN_DIR, exist_ok=True)

# Full candidate universe — all symbols we've ever tested
SYMBOLS = sorted(set([
    'AAPL','ACN','AMZN','APH','AXP','BKNG','BLK','BSX','CAT','CVX',
    'DHR','GS','HD','HON','IBM','KO','LRCX','MCHP','MDT','META',
    'MS','MSFT','ORCL','PANW','PCAR','PG','PLTR','PM','SO','TXN',
    # extras for selection
    'INTU','ABNB','JPM','GOOGL','GE','NVDA','ABT','TSLA','SCHW','BAC',
    'AMAT','FTNT','CL','USB','FAST','ABBV','DHR','HD','ACN','MS',
    'COIN','AMD','CRWD','SMCI','ENPH','FCX','MU','ON','NXPI','MRVL',
    'AVGO','ARM','NOW','WDAY','ADSK','CRM','DASH','DDOG','HOOD',
    'RIVN','MRNA','RBLX','TTWO','LCID','FANG','APP'
]))

START = "2022-01-01"
END   = "2024-12-31"

api = REST(API_KEY, API_SECRET, BASE_URL)

print(f"Fetching {START} to {END} for {len(SYMBOLS)} symbols -> {TRAIN_DIR}/")
print("NOTE: 3 years of 1-min data is large. Expect 60-120 min.\n")

for i, sym in enumerate(SYMBOLS, 1):
    out = os.path.join(TRAIN_DIR, f"{sym}.parquet")
    if os.path.exists(out):
        print(f"[{i}/{len(SYMBOLS)}] {sym}: already exists, skipping")
        continue
    try:
        bars = api.get_bars(
            sym, TimeFrame.Minute,
            start=START, end=END,
            adjustment="all", feed="sip",
            limit=10000000
        ).df
        if len(bars) == 0:
            print(f"[{i}/{len(SYMBOLS)}] {sym}: no data")
            continue
        bars.to_parquet(out)
        print(f"[{i}/{len(SYMBOLS)}] {sym}: {len(bars):,} bars saved")
        time.sleep(0.3)
    except Exception as e:
        print(f"[{i}/{len(SYMBOLS)}] {sym}: ERROR {e}")
        time.sleep(1)

print("\nDone.")
