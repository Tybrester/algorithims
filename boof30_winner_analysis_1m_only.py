"""
BOOF 30 — Winner vs Non-Runner (1m only, till 11am)
Group A: MFE 60m >= 2% | Group B: MFE 60m <= 0.5%
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

API_KEY = "PKAJ7LELQVQMPJPEJTGZDRT3XP"
SECRET_KEY = "53BHpMNadsdZ6gUx4DmU7wHD7eGu1SNwnHKPqFHhqwhZ"

ET = ZoneInfo("America/New_York")
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

SYMBOLS = ["NVDA", "TSLA", "AAPL"]
BAR1_BODY_MIN = 0.004
BAR1_RVOL_MIN = 2.0
BAR2_RVOL_MIN = 1.5
LOOKBACK_VOL = 20
END_TIME = time(11, 0)

print("="*80)
print("BOOF 30 — Winner vs Non-Runner (1m only, 3 symbols, 9:30-11am)")
print("="*80)

# Fetch 1m data only
all_data = []
end_date = datetime.now(ET)
start_date = end_date - timedelta(days=180)

print("\nFetching 1m data...")
for sym in SYMBOLS:
    try:
        req = StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Minute, start=start_date, end=end_date)
        df = data_client.get_stock_bars(req).df
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(sym)
        df = df.reset_index()
        if 't' in df.columns:
            df = df.rename(columns={'t': 'timestamp'})
        df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
        df['datetime'] = pd.to_datetime(df['timestamp'])
        df['symbol'] = sym
        all_data.append(df[['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume']])
        print(f"  {sym}: {len(df)} bars")
    except Exception as e:
        print(f"  {sym}: {e}")

data = pd.concat(all_data, ignore_index=True) if all_data else None
if data is None:
    print("No data!")
    exit()

# Add VWAP
def add_metrics(df):
    df = df.copy()
    df['date'] = df['datetime'].dt.date
    tp = (df['high'] + df['low'] + df['close']) / 3
    df['pv'] = tp * df['volume']
    df['cum_pv'] = df.groupby('date')['pv'].cumsum()
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['vwap'] = df['cum_pv'] / df['cum_vol']
    df['vwap_slope'] = df.groupby('date')['vwap'].diff(3)
    df['vwap_dist'] = (df['close'] - df['vwap']) / df['vwap']
    return df

# Get signals
signals = []
for symbol, df in data.groupby('symbol'):
    df = add_metrics(df)
    df['date'] = df['datetime'].dt.date
    df['time'] = df['datetime'].dt.time
    
    for date, day in df.groupby('date'):
        day = day.reset_index(drop=True)
        found = False
        
        for i in range(LOOKBACK_VOL, len(day) - 60):
            if found:
                break
            
            row = day.iloc[i]
            if not (time(9, 30) <= row['time'] <= END_TIME):
                continue
            
            if i < 1:
                continue
            
            bar1, bar2 = day.iloc[i-1], day.iloc[i]
            avg_vol = day["volume"].iloc[i-LOOKBACK_VOL:i-1].mean()
            if avg_vol == 0:
                continue
            
            bar1_body = abs(bar1["close"] - bar1["open"]) / bar1["open"]
            bar2_body = abs(bar2["close"] - bar2["open"]) / bar2["open"]
            bar1_rvol = bar1["volume"] / avg_vol
            bar2_rvol = bar2["volume"] / avg_vol
            
            if not (bar1["close"] < bar1["open"] and bar2["close"] < bar2["open"] and
                    bar1_body >= BAR1_BODY_MIN and bar2["close"] < bar1["close"] and
                    bar1_rvol >= BAR1_RVOL_MIN and bar2_rvol >= BAR2_RVOL_MIN and
                    bar1["close"] < bar1["vwap"] and bar2["close"] < bar2["vwap"] and
                    bar2["high"] < bar1["open"]):
                continue
            
            entry = row['close']
            future_60 = day.iloc[i+1:i+61] if i+61 < len(day) else day.iloc[i+1:]
            if len(future_60) < 30:
                continue
            
            mfe_60 = (entry - future_60['low'].min()) / entry
            
            if mfe_60 >= 0.02:
                group = 'A'
            elif mfe_60 <= 0.005:
                group = 'B'
            else:
                continue
            
            signals.append({
                'symbol': symbol,
                'group': group,
                'mfe_60': mfe_60,
                'bar1_rvol': bar1_rvol,
                'bar2_rvol': bar2_rvol,
                'bar1_body': bar1_body * 100,
                'bar2_body': bar2_body * 100,
                'vwap_dist': row['vwap_dist'] * 100,
                'vwap_slope': row['vwap_slope'],
                'time_of_day': row['time'].strftime('%H:%M')
            })
            found = True

df_sig = pd.DataFrame(signals)
print(f"\n{'='*80}")
print(f"RESULTS: {len(df_sig)} signals")
print(f"{'='*80}")

group_a = df_sig[df_sig['group'] == 'A']
group_b = df_sig[df_sig['group'] == 'B']

print(f"\nGroup A (Winners, MFE>=2%): {len(group_a)} signals")
print(f"Group B (Non-runners, MFE<=0.5%): {len(group_b)} signals")

if len(group_a) >= 3 and len(group_b) >= 3:
    metrics = [
        ('RVOL Bar 1', 'bar1_rvol'),
        ('RVOL Bar 2', 'bar2_rvol'),
        ('Bar 1 Body %', 'bar1_body'),
        ('Bar 2 Body %', 'bar2_body'),
        ('VWAP Distance %', 'vwap_dist'),
        ('VWAP Slope', 'vwap_slope'),
    ]
    
    print(f"\n{'Metric':<25} {'Group A (Winners)':<30} {'Group B (Non-runners)':<30}")
    print("-"*85)
    
    for label, col in metrics:
        a_vals = group_a[col].dropna()
        b_vals = group_b[col].dropna()
        a_str = f"Avg={a_vals.mean():.3f} Med={a_vals.median():.3f}"
        b_str = f"Avg={b_vals.mean():.3f} Med={b_vals.median():.3f}"
        print(f"{label:<25} {a_str:<30} {b_str:<30}")
    
    # Time of day distribution
    print(f"\n{'Time of Day Distribution':<25}")
    print("-"*85)
    print(f"{'Group A (Winners)':<30} {group_a['time_of_day'].value_counts().head(3).to_dict()}")
    print(f"{'Group B (Non-runners)':<30} {group_b['time_of_day'].value_counts().head(3).to_dict()}")
    
    df_sig.to_csv('boof30_winner_analysis_results.csv', index=False)
    print(f"\nSaved: boof30_winner_analysis_results.csv")
else:
    print("\nInsufficient data for comparison")

print("\n" + "="*80)
print("DONE")
print("="*80)
