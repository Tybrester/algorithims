"""
BOOF23 MFE/MAE Study — 6 months, full 46-symbol universe
Run: python boof23_mfe_mae.py
"""

import importlib.util, datetime, pandas as pd
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

PAPER_KEY    = "PK7N52NHGPS2GBVZU64BCUEDNO"
PAPER_SECRET = "B3uwbzRDHZeDwt5riUd3G4U9oxnELTukfCKGovZx9K9E"
ET           = pytz.timezone("America/New_York")

SYMS = [
    'TOST','HOOD','ORCL','MSFT','V','JPM','SOUN','PODD','ENTG','GE',
    'MRNA','AI','PATH','GS','BSX','SIMO','SCHW','TEM','AMD','ABNB',
    'NEM','GILD','MCHP','UNP','ETN','LRCX','SMTC','INCY','ITW','LLY',
    'MAR','QRVO','MPC','BKR','TMO','CAT','NVDA','SOFI','XOM','DPZ',
    'FCX','VRTX','S','CSCO','DE','HUM',
]

# Load signal engine
spec = importlib.util.spec_from_file_location("b23", "boof23_analysis.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

data_client = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)

now   = datetime.datetime.now(ET)
start = now - datetime.timedelta(days=182)  # ~6 months

print(f"Fetching 6-month 5-min bars for {len(SYMS)} symbols...")
print(f"Range: {start.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')}\n")

all_trades = []
errors = []

for i in range(0, len(SYMS), 10):
    chunk = SYMS[i:i+10]
    try:
        req  = StockBarsRequest(
            symbol_or_symbols=chunk,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            start=start, end=now,
        )
        resp = data_client.get_stock_bars(req).df.reset_index()
    except Exception as e:
        print(f"  Fetch error {chunk}: {e}")
        errors.extend(chunk)
        continue

    for sym in chunk:
        df = resp[resp["symbol"] == sym].copy().reset_index(drop=True)
        if df.empty or len(df) < 200:
            print(f"  {sym}: not enough data ({len(df)} bars)")
            errors.append(sym)
            continue
        df = df.rename(columns={"timestamp": "time"})
        df["time"] = pd.to_datetime(df["time"]).dt.tz_convert(ET)
        try:
            trades = mod.run_boof23_freerun(df, sym)
            print(f"  {sym}: {len(trades)} signals")
            all_trades.extend(trades)
        except Exception as e:
            print(f"  {sym} error: {e}")
            errors.append(sym)

print(f"\nTotal signals: {len(all_trades)}")
if errors:
    print(f"Errors/skipped: {errors}")

if all_trades:
    mod.report_freerun(all_trades, "BOOF23 MFE/MAE — 6 Months, 46 Symbols")

    # Also save raw to CSV for further analysis
    df_out = pd.DataFrame(all_trades)
    df_out.to_csv("boof23_mfe_mae_results.csv", index=False)
    print(f"\nSaved to boof23_mfe_mae_results.csv")

    # Per-symbol summary
    print(f"\n{'='*65}")
    print(f"  PER-SYMBOL BREAKDOWN")
    print(f"{'='*65}")
    grp = df_out.groupby("symbol").agg(
        signals=("mfe_pct", "count"),
        mfe_mean=("mfe_pct", "mean"),
        mae_mean=("mae_pct", "mean"),
        final_mean=("final_pct", "mean"),
    ).sort_values("mfe_mean", ascending=False)
    print(grp.to_string())
