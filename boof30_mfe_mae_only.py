"""
BOOF 30 — 2-Bar Short Ignition MFE/MAE Analysis Only
Detects pattern, logs MFE/MAE without TP/SL exits
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

SYMBOLS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMZN"]

# Parameters
BAR1_BODY_MIN = 0.004  # 0.40%
BAR1_RVOL_MIN = 3.0    # 3x
BAR2_RVOL_MIN = 1.5    # 1.5x
LOOKBACK_VOL = 20


def fetch_data():
    all_data = []
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=180)
    
    print("Fetching 6 months of data...")
    for symbol in SYMBOLS:
        try:
            req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start_date, end=end_date)
            df = data_client.get_stock_bars(req).df
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol)
            df = df.reset_index()
            if 't' in df.columns:
                df = df.rename(columns={'t': 'timestamp'})
            df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
            df['datetime'] = pd.to_datetime(df['timestamp'])
            df['symbol'] = symbol
            all_data.append(df[['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume']])
            print(f"  {symbol}: {len(df)} bars")
        except Exception as e:
            print(f"  {symbol}: ERROR - {e}")
    
    return pd.concat(all_data, ignore_index=True) if all_data else None


def add_vwap(df):
    df = df.copy()
    df['date'] = df['datetime'].dt.date
    tp = (df['high'] + df['low'] + df['close']) / 3
    df['pv'] = tp * df['volume']
    df['cum_pv'] = df.groupby('date')['pv'].cumsum()
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['vwap'] = df['cum_pv'] / df['cum_vol']
    return df


def detect_2bar_short(df, i):
    """Detect 2-bar short ignition pattern."""
    if i < 1 or i < LOOKBACK_VOL:
        return False
    
    bar1 = df.iloc[i - 1]
    bar2 = df.iloc[i]
    
    avg_vol = df["volume"].iloc[i-LOOKBACK_VOL:i-1].mean()
    if avg_vol == 0:
        return False
    
    bar1_body_pct = abs(bar1["close"] - bar1["open"]) / bar1["open"]
    bar1_red = bar1["close"] < bar1["open"]
    bar2_red = bar2["close"] < bar2["open"]
    bar1_rvol = bar1["volume"] / avg_vol
    bar2_rvol = bar2["volume"] / avg_vol
    
    bar1_big = bar1_body_pct >= BAR1_BODY_MIN
    bar2_follow = bar2["close"] < bar1["close"]
    below_vwap = bar1["close"] < bar1["vwap"] and bar2["close"] < bar2["vwap"]
    no_reclaim = bar2["high"] < bar1["open"]
    
    return (bar1_red and bar2_red and bar1_big and bar2_follow and
            bar1_rvol >= BAR1_RVOL_MIN and bar2_rvol >= BAR2_RVOL_MIN and
            below_vwap and no_reclaim)


def get_mfe_mae(day, entry_idx, entry_price):
    """Get MFE and MAE for 15m, 30m, 60m."""
    results = {}
    
    for minutes in [15, 30, 60]:
        future_idx = entry_idx + minutes
        if future_idx < len(day):
            future_slice = day.iloc[entry_idx+1:future_idx+1]
            if len(future_slice) > 0:
                max_high = future_slice['high'].max()
                min_low = future_slice['low'].min()
                
                # For short: MFE = price drops (good), MAE = price rises (bad)
                mfe = (entry_price - min_low) / entry_price
                mae = (max_high - entry_price) / entry_price
                
                results[f'mfe_{minutes}m'] = mfe
                results[f'mae_{minutes}m'] = mae
            else:
                results[f'mfe_{minutes}m'] = None
                results[f'mae_{minutes}m'] = None
        else:
            results[f'mfe_{minutes}m'] = None
            results[f'mae_{minutes}m'] = None
    
    return results


def main():
    print("="*60)
    print("BOOF 30 — 2-Bar Short MFE/MAE Analysis")
    print(f"Bar1: {BAR1_BODY_MIN*100:.1f}% body, {BAR1_RVOL_MIN:.0f}x RVOL")
    print(f"Bar2: {BAR2_RVOL_MIN:.1f}x RVOL")
    print("="*60)
    
    data = fetch_data()
    if data is None:
        print("No data!")
        return
    
    signals = []
    
    for symbol, df in data.groupby('symbol'):
        df = add_vwap(df)
        df['date'] = df['datetime'].dt.date
        df['time'] = df['datetime'].dt.time
        df['avg_vol'] = df.groupby('date')['volume'].rolling(LOOKBACK_VOL).mean().reset_index(level=0, drop=True)
        df['rvol'] = df['volume'] / df['avg_vol']
        
        for date, day in df.groupby('date'):
            day = day.reset_index(drop=True)
            found = False
            
            for i in range(LOOKBACK_VOL, len(day) - 60):
                if found:
                    break
                
                row = day.iloc[i]
                if not (time(9, 30) <= row['time'] <= time(15, 55)):
                    continue
                if pd.isna(row['rvol']):
                    continue
                
                if not detect_2bar_short(day, i):
                    continue
                
                entry = row['close']
                mfe_mae = get_mfe_mae(day, i, entry)
                
                signals.append({
                    'symbol': symbol,
                    'date': date,
                    'time': row['time'].strftime('%H:%M'),
                    'entry_price': entry,
                    'rvol': row['rvol'],
                    **mfe_mae
                })
                found = True  # One signal per symbol per day
    
    if not signals:
        print("\nNo signals found!")
        return
    
    df_signals = pd.DataFrame(signals)
    
    print(f"\n{'='*60}")
    print(f"FOUND {len(signals)} SIGNALS")
    print(f"{'='*60}")
    
    # MFE/MAE Statistics
    for period in ['15m', '30m', '60m']:
        mfe_col = f'mfe_{period}'
        mae_col = f'mae_{period}'
        
        mfe_vals = df_signals[mfe_col].dropna()
        mae_vals = df_signals[mae_col].dropna()
        
        if len(mfe_vals) > 0:
            print(f"\n{period}:")
            print(f"  MFE (favorable for short):")
            print(f"    Average:   {mfe_vals.mean()*100:.2f}%")
            print(f"    Median:    {mfe_vals.median()*100:.2f}%")
            print(f"    90th %ile: {mfe_vals.quantile(0.90)*100:.2f}%")
            print(f"  MAE (adverse for short):")
            print(f"    Average:   {mae_vals.mean()*100:.2f}%")
            print(f"    Median:    {mae_vals.median()*100:.2f}%")
    
    # Save
    df_signals.to_csv('boof30_mfe_mae_signals.csv', index=False)
    print(f"\nSaved {len(signals)} signals to boof30_mfe_mae_signals.csv")


if __name__ == "__main__":
    main()
