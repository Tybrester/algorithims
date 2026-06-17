"""
Fetch 6 months of 1m bar data for top 100 SP500 + top 50 Nasdaq by mktcap.
Saves to data/1m/<SYM>.parquet
"""
import os, time, warnings
import pandas as pd
from datetime import datetime, timedelta
warnings.filterwarnings("ignore")

import alpaca_trade_api as tradeapi

API_KEY    = "PKKPME54QJA3KBPAJ3QZZOJXDF"
API_SECRET = "J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y"
BASE_URL   = "https://paper-api.alpaca.markets"

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL)

# ── Universe ──────────────────────────────────────────────────────────────────
SP500_TOP100 = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","BRK-B","TSLA","AVGO","JPM",
    "LLY","UNH","V","XOM","MA","JNJ","COST","PG","HD","WMT",
    "ABBV","NFLX","BAC","CRM","ORCL","CVX","MRK","KO","AMD","PEP",
    "TMO","ACN","LIN","MCD","CSCO","ABT","GE","DHR","IBM","TXN",
    "INTU","PM","NOW","CAT","ISRG","QCOM","GS","VZ","AMGN","RTX",
    "SPGI","NEE","HON","T","UNP","LOW","AMAT","MS","SYK","BKNG",
    "BLK","AXP","VRTX","GILD","ELV","PLD","ADI","CB","DE","SCHW",
    "PANW","REGN","MDT","BSX","SO","DUK","MU","MMC","ZTS","CI",
    "CME","SHW","ITW","TJX","ICE","WM","CL","EQIX","AON","PH",
    "NOC","HCA","MCO","USB","WELL","APH","GD","FCX","EMR","FI"
]

NDX_TOP50 = [
    "PLTR","MELI","SNPS","KLAC","LRCX","CDNS","MRVL","FTNT","ADSK","CRWD",
    "ABNB","WDAY","DXCM","TEAM","SGEN","PYPL","NXPI","MCHP","ON","ENPH",
    "FANG","IDXX","ILMN","MRNA","BIIB","DLTR","FAST","ROST","PCAR","CTAS",
    "VRSK","ANSS","CPRT","ODFL","GEHC","KDP","TTWO","DASH","DDOG","ZS",
    "COIN","RBLX","HOOD","RIVN","LCID","APP","SMCI","ARM","ALAB","CRWV"
]

SYMBOLS = sorted(set(SP500_TOP100 + NDX_TOP50))
print(f"Universe: {len(SYMBOLS)} symbols")

# ── Date range: 6 months back ─────────────────────────────────────────────────
END   = datetime(2026, 6, 15)
START = datetime(2025, 12, 15)

OUT_DIR = "data/1m"
os.makedirs(OUT_DIR, exist_ok=True)

def fetch_sym(sym):
    out_path = f"{OUT_DIR}/{sym}.parquet"
    if os.path.exists(out_path):
        sz = os.path.getsize(out_path)
        if sz > 10_000:
            print(f"  {sym}: cached ({sz//1024}KB) — skip")
            return True

    try:
        df = api.get_bars(
            sym, "1Min",
            start=START.strftime("%Y-%m-%d"),
            end=END.strftime("%Y-%m-%d"),
            feed="sip",
            limit=100000
        ).df

        if df is None or len(df) == 0:
            print(f"  {sym}: no data")
            return False

        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_convert("America/New_York")
        else:
            df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")

        df = df[["open","high","low","close","volume"]]
        df.to_parquet(out_path)
        print(f"  {sym}: {len(df):,} bars saved ({os.path.getsize(out_path)//1024}KB)")
        return True

    except Exception as e:
        print(f"  {sym}: ERROR — {e}")
        return False

print(f"\nFetching {START.date()} -> {END.date()} ...\n")
ok, fail = 0, []
for i, sym in enumerate(SYMBOLS, 1):
    print(f"[{i}/{len(SYMBOLS)}]", end=" ")
    success = fetch_sym(sym)
    if success:
        ok += 1
    else:
        fail.append(sym)
    time.sleep(0.4)

print(f"\nDone. {ok} ok, {len(fail)} failed.")
if fail:
    print(f"Failed: {fail}")
