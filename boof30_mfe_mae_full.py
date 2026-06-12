"""
BOOF 30 — 2-Bar Short MFE/MAE (1m & 5m, 9:30-11 AM)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

API_KEY = "PKAJ7LELQVQMPJPEJTGZDRT3XP"
SECRET_KEY = "53BHpMNadsdZ6gUx4DmU7wHD7eGu1SNwnHKPqFHhqwhZ"

ET = ZoneInfo("America/New_York")
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

SYMBOLS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMZN"]
BAR1_BODY_MIN = 0.004
BAR1_RVOL_MIN = 3.0
BAR2_RVOL_MIN = 1.5
LOOKBACK_VOL = 20
END_TIME = time(11, 0)


def fetch_data(tf_str):
    all_data = []
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=180)
    
    tf = TimeFrame.Minute if tf_str == "1Min" else TimeFrame(5, TimeFrameUnit.Minute)
    
    print(f"Fetching {tf_str} data...")
    for sym in SYMBOLS:
        try:
            req = StockBarsRequest(symbol_or_symbols=sym, timeframe=tf, start=start_date, end=end_date)
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
    if i < 1 or i < LOOKBACK_VOL:
        return False
    bar1, bar2 = df.iloc[i-1], df.iloc[i]
    avg_vol = df["volume"].iloc[i-LOOKBACK_VOL:i-1].mean()
    if avg_vol == 0:
        return False
    
    bar1_body = abs(bar1["close"] - bar1["open"]) / bar1["open"]
    bar1_rvol = bar1["volume"] / avg_vol
    bar2_rvol = bar2["volume"] / avg_vol
    
    return (bar1["close"] < bar1["open"] and bar2["close"] < bar2["open"] and
            bar1_body >= BAR1_BODY_MIN and bar2["close"] < bar1["close"] and
            bar1_rvol >= BAR1_RVOL_MIN and bar2_rvol >= BAR2_RVOL_MIN and
            bar1["close"] < bar1["vwap"] and bar2["close"] < bar2["vwap"] and
            bar2["high"] < bar1["open"])


def get_mfe_mae(day, entry_idx, entry, bars_list):
    results = {}
    for bars in bars_list:
        future_idx = entry_idx + bars
        if future_idx < len(day):
            future = day.iloc[entry_idx+1:future_idx+1]
            if len(future) > 0:
                results[f'mfe_{bars}'] = (entry - future['low'].min()) / entry
                results[f'mae_{bars}'] = (future['high'].max() - entry) / entry
            else:
                results[f'mfe_{bars}'] = results[f'mae_{bars}'] = None
        else:
            results[f'mfe_{bars}'] = results[f'mae_{bars}'] = None
    return results


def analyze(tf_str, bar_mult, bars_list):
    print(f"\n{'='*60}")
    print(f"{tf_str} (bar = {bar_mult} minutes)")
    print(f"{'='*60}")
    
    data = fetch_data(tf_str)
    if data is None:
        return None
    
    signals = []
    for symbol, df in data.groupby('symbol'):
        df = add_vwap(df)
        df['date'] = df['datetime'].dt.date
        df['time'] = df['datetime'].dt.time
        
        for date, day in df.groupby('date'):
            day = day.reset_index(drop=True)
            found = False
            for i in range(LOOKBACK_VOL, len(day)):
                if found:
                    break
                row = day.iloc[i]
                if not (time(9, 30) <= row['time'] <= END_TIME):
                    continue
                if detect_2bar_short(day, i):
                    entry = row['close']
                    mfe_mae = get_mfe_mae(day, i, entry, bars_list)
                    signals.append({'symbol': symbol, 'date': str(date), 'entry': entry, **mfe_mae})
                    found = True
    
    if not signals:
        print("No signals!")
        return None
    
    df_sig = pd.DataFrame(signals)
    print(f"Signals: {len(signals)}")
    
    for bars in bars_list:
        mins = bars * bar_mult
        mfe = df_sig[f'mfe_{bars}'].dropna()
        mae = df_sig[f'mae_{bars}'].dropna()
        if len(mfe) == 0:
            continue
        print(f"\n{mins}m ({bars} bars):")
        print(f"  MFE: Avg={mfe.mean()*100:.2f}% Med={mfe.median()*100:.2f}% P90={mfe.quantile(0.90)*100:.2f}%")
        print(f"  MAE: Avg={mae.mean()*100:.2f}% Med={mae.median()*100:.2f}%")
    
    return df_sig


print("="*60)
print("BOOF 30 — 2-Bar Short (9:30-11:00 AM)")
print(f"Bar1: {BAR1_BODY_MIN*100:.1f}% body, {BAR1_RVOL_MIN:.0f}x RVOL")
print("="*60)

# 1-minute: 15, 30, 60 minutes = 15, 30, 60 bars
df_1m = analyze("1Min", 1, [15, 30, 60])
if df_1m is not None:
    df_1m.to_csv('boof30_mfe_mae_1m_11am.csv', index=False)

# 5-minute: 15, 30, 60 minutes = 3, 6, 12 bars  
df_5m = analyze("5Min", 5, [3, 6, 12])
if df_5m is not None:
    df_5m.to_csv('boof30_mfe_mae_5m_11am.csv', index=False)

print("\n" + "="*60)
print("DONE — CSVs saved")
print("="*60)
