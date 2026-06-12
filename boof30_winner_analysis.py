"""
BOOF 30 — Winner vs Non-Runner Analysis
Group A: MFE 60m >= 2% (Winners)
Group B: MFE 60m <= 0.5% (Non-runners)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

API_KEY = "AKQZN2MID7NNEZM7PP52LLEJ2E"
SECRET_KEY = "3fDvtw2A6kcPgSRwexRdsug3P9Snwtax6ycy7gZvgPQp"

ET = ZoneInfo("America/New_York")
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

SYMBOLS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMZN"]
BAR1_BODY_MIN = 0.004
BAR1_RVOL_MIN = 2.0
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


def add_metrics(df):
    """Add VWAP, slope, and distance metrics."""
    df = df.copy()
    df['date'] = df['datetime'].dt.date
    
    # VWAP
    tp = (df['high'] + df['low'] + df['close']) / 3
    df['pv'] = tp * df['volume']
    df['cum_pv'] = df.groupby('date')['pv'].cumsum()
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['vwap'] = df['cum_pv'] / df['cum_vol']
    
    # VWAP slope (3-bar change)
    df['vwap_slope'] = df.groupby('date')['vwap'].diff(3)
    
    # VWAP distance
    df['vwap_dist'] = (df['close'] - df['vwap']) / df['vwap']
    
    return df


def get_signals(data, bar_mult):
    """Get all signals with full metrics."""
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
                
                # 2-bar detection
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
                
                # Calculate MFE 60m
                future_60 = day.iloc[i+1:i+61] if i+61 < len(day) else day.iloc[i+1:]
                if len(future_60) < 10:  # Need enough bars
                    continue
                
                mfe_60 = (entry - future_60['low'].min()) / entry
                
                # Categorize
                if mfe_60 >= 0.02:
                    group = 'A'  # Winner
                elif mfe_60 <= 0.005:
                    group = 'B'  # Non-runner
                else:
                    continue  # Middle ground - skip
                
                signals.append({
                    'symbol': symbol,
                    'date': str(date),
                    'time': row['time'].strftime('%H:%M'),
                    'entry': entry,
                    'group': group,
                    'mfe_60': mfe_60,
                    'bar1_rvol': bar1_rvol,
                    'bar2_rvol': bar2_rvol,
                    'bar1_body': bar1_body,
                    'bar2_body': bar2_body,
                    'vwap_dist': row['vwap_dist'],
                    'vwap_slope': row['vwap_slope'],
                    'minutes_from_open': int((row['datetime'].hour - 9) * 60 + row['datetime'].minute - 30)
                })
                found = True
    
    return pd.DataFrame(signals)


def compare_groups(df, timeframe_name):
    """Analyze only runners (Group A: MFE >= 2%)."""
    print(f"\n{'='*100}")
    print(f"{timeframe_name} — RUNNER ANALYSIS (MFE 60m >= 2%)")
    print(f"{'='*100}")
    
    runners = df[df['group'] == 'A']
    
    print(f"\nTotal Runners: {len(runners)} signals\n")
    
    if len(runners) == 0:
        print("No runners found!")
        return
    
    # Print all runner details
    print(f"{'Symbol':<8} {'Time':<8} {'RVOL1':<8} {'RVOL2':<8} {'Bar1Body':<10} {'Bar2Body':<10} {'VWAPDist':<12} {'VWAPSlope':<12} {'MFE60':<8}")
    print("-"*100)
    
    for _, row in runners.iterrows():
        print(f"{row['symbol']:<8} {row['time']:<8} {row['bar1_rvol']:<8.2f} {row['bar2_rvol']:<8.2f} "
              f"{row['bar1_body']:<10.4f} {row['bar2_body']:<10.4f} {row['vwap_dist']:<12.6f} "
              f"{row['vwap_slope']:<12.6f} {row['mfe_60']*100:<8.2f}%")
    
    # Summary stats
    print(f"\n{'='*100}")
    print("RUNNER STATISTICS (Averages)")
    print(f"{'='*100}")
    print(f"RVOL Bar 1:        {runners['bar1_rvol'].mean():.2f}")
    print(f"RVOL Bar 2:        {runners['bar2_rvol'].mean():.2f}")
    print(f"Bar 1 Body %:      {runners['bar1_body'].mean():.4f}")
    print(f"Bar 2 Body %:      {runners['bar2_body'].mean():.4f}")
    print(f"VWAP Distance %:   {runners['vwap_dist'].mean():.6f}")
    print(f"VWAP Slope:        {runners['vwap_slope'].mean():.6f}")
    print(f"Minutes from open: {runners['minutes_from_open'].mean():.0f}")
    print(f"MFE 60m:           {runners['mfe_60'].mean()*100:.2f}%")
    
    # Symbol distribution
    print(f"\n{'='*100}")
    print("SYMBOL DISTRIBUTION")
    print(f"{'='*100}")
    for sym, count in runners['symbol'].value_counts().items():
        print(f"  {sym}: {count}")
    
    # Save
    runners.to_csv(f'boof30_runners_{timeframe_name.lower().replace(" ", "_")}.csv', index=False)
    print(f"\n{'='*100}")
    print(f"Saved: boof30_runners_{timeframe_name.lower().replace(' ', '_')}.csv")
    print(f"{'='*100}")


def main():
    print("="*80)
    print("BOOF 30 — Winner vs Non-Runner Analysis (9:30-11:00 AM)")
    print("Group A: MFE 60m >= 2% | Group B: MFE 60m <= 0.5%")
    print("="*80)
    
    # 1-minute analysis
    data_1m = fetch_data("1Min")
    if data_1m is not None:
        df_1m = get_signals(data_1m, 1)
        if len(df_1m) > 0:
            compare_groups(df_1m, "1-Minute")
        else:
            print("\nNo 1m signals found")
    
    # 5-minute analysis
    data_5m = fetch_data("5Min")
    if data_5m is not None:
        df_5m = get_signals(data_5m, 5)
        if len(df_5m) > 0:
            compare_groups(df_5m, "5-Minute")
        else:
            print("\nNo 5m signals found")
    
    print("\n" + "="*80)
    print("DONE — CSVs saved")
    print("="*80)


if __name__ == "__main__":
    main()
