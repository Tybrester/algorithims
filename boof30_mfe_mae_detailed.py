"""
BOOF 30 — 2-Bar Short MFE/MAE with RVOL & VWAP Filters
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
LOOKBACK_VOL = 20
END_TIME = time(11, 0)


def fetch_data():
    all_data = []
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=180)
    
    print("Fetching 1m data...")
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
    
    return pd.concat(all_data, ignore_index=True) if all_data else None


def add_vwap_and_slope(df):
    df = df.copy()
    df['date'] = df['datetime'].dt.date
    
    # VWAP
    tp = (df['high'] + df['low'] + df['close']) / 3
    df['pv'] = tp * df['volume']
    df['cum_pv'] = df.groupby('date')['pv'].cumsum()
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['vwap'] = df['cum_pv'] / df['cum_vol']
    
    # VWAP slope (change over last 3 bars)
    df['vwap_slope'] = df.groupby('date')['vwap'].diff(3)
    
    return df


def get_all_signals(data):
    """Get all 2-bar short signals with full context."""
    signals = []
    
    for symbol, df in data.groupby('symbol'):
        df = add_vwap_and_slope(df)
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
                if i < 1 or i < LOOKBACK_VOL:
                    continue
                
                bar1, bar2 = day.iloc[i-1], day.iloc[i]
                avg_vol = day["volume"].iloc[i-LOOKBACK_VOL:i-1].mean()
                if avg_vol == 0:
                    continue
                
                bar1_body = abs(bar1["close"] - bar1["open"]) / bar1["open"]
                bar1_rvol = bar1["volume"] / avg_vol
                bar2_rvol = bar2["volume"] / avg_vol
                
                if not (bar1["close"] < bar1["open"] and bar2["close"] < bar2["open"] and
                        bar1_body >= BAR1_BODY_MIN and bar2["close"] < bar1["close"] and
                        bar1_rvol >= 2.0 and bar2_rvol >= 1.5):
                    continue
                
                entry = row['close']
                
                # Calculate MFE/MAE
                future_60 = day.iloc[i+1:i+61] if i+61 < len(day) else day.iloc[i+1:]
                if len(future_60) == 0:
                    continue
                
                mfe_60 = (entry - future_60['low'].min()) / entry
                mae_60 = (future_60['high'].max() - entry) / entry
                
                # 15m and 30m
                future_15 = day.iloc[i+1:i+16] if i+16 < len(day) else day.iloc[i+1:]
                future_30 = day.iloc[i+1:i+31] if i+31 < len(day) else day.iloc[i+1:]
                
                mfe_15 = (entry - future_15['low'].min()) / entry if len(future_15) > 0 else None
                mae_15 = (future_15['high'].max() - entry) / entry if len(future_15) > 0 else None
                mfe_30 = (entry - future_30['low'].min()) / entry if len(future_30) > 0 else None
                mae_30 = (future_30['high'].max() - entry) / entry if len(future_30) > 0 else None
                
                signals.append({
                    'symbol': symbol,
                    'date': date,
                    'entry': entry,
                    'bar1_rvol': bar1_rvol,
                    'bar2_rvol': bar2_rvol,
                    'above_vwap': entry > row['vwap'],
                    'vwap_slope': row['vwap_slope'],
                    'vwap': row['vwap'],
                    'mfe_15': mfe_15,
                    'mae_15': mae_15,
                    'mfe_30': mfe_30,
                    'mae_30': mae_30,
                    'mfe_60': mfe_60,
                    'mae_60': mae_60
                })
                found = True
    
    return pd.DataFrame(signals)


def analyze_signals(df):
    """Run all filter combinations."""
    print(f"\nTotal signals: {len(df)}")
    
    # Define filter sets
    rvol_filters = [
        ('RVOL 2-3', (df['bar1_rvol'] >= 2) & (df['bar1_rvol'] < 3)),
        ('RVOL 3-5', (df['bar1_rvol'] >= 3) & (df['bar1_rvol'] < 5)),
        ('RVOL 5+', df['bar1_rvol'] >= 5)
    ]
    
    vwap_pos_filters = [
        ('Above VWAP', df['above_vwap'] == True),
        ('Below VWAP', df['above_vwap'] == False)
    ]
    
    vwap_slope_filters = [
        ('VWAP Slope Up', df['vwap_slope'] > 0),
        ('VWAP Slope Down', df['vwap_slope'] < 0)
    ]
    
    # Run all combinations
    results = []
    
    for rvol_name, rvol_mask in rvol_filters:
        for vwap_name, vwap_mask in vwap_pos_filters:
            for slope_name, slope_mask in vwap_slope_filters:
                mask = rvol_mask & vwap_mask & slope_mask
                subset = df[mask]
                
                if len(subset) < 5:
                    continue
                
                # Calculate stats
                mfe_gt_mae = (subset['mfe_60'] > subset['mae_60']).mean() * 100
                perfect_trade = ((subset['mfe_60'] > 0.01) & (subset['mae_60'] < 0.005)).mean() * 100
                
                results.append({
                    'Filter': f"{rvol_name} | {vwap_name} | {slope_name}",
                    'Count': len(subset),
                    'MFE_60_Avg': subset['mfe_60'].mean() * 100,
                    'MAE_60_Avg': subset['mae_60'].mean() * 100,
                    'MFE>MAE_%': mfe_gt_mae,
                    'Perfect_Trade_%': perfect_trade
                })
    
    return pd.DataFrame(results)


def print_results(results_df):
    """Print formatted results."""
    print("\n" + "="*90)
    print("MFE/MAE ANALYSIS BY FILTER COMBINATION (60-minute window)")
    print("="*90)
    print(f"{'Filter':<50} {'N':<5} {'MFE%':<7} {'MAE%':<7} {'MFE>MAE':<9} {'Perfect%':<10}")
    print("-"*90)
    
    for _, r in results_df.iterrows():
        print(f"{r['Filter']:<50} {r['Count']:<5} {r['MFE_60_Avg']:>6.2f} {r['MAE_60_Avg']:>6.2f} "
              f"{r['MFE>MAE_%']:>8.1f} {r['Perfect_Trade_%']:>9.1f}")
    
    # Top performers
    print("\n" + "="*90)
    print("🏆 TOP BY 'MFE > MAE' RATE")
    print("="*90)
    top_mfe = results_df.nlargest(5, 'MFE>MAE_%')
    for _, r in top_mfe.iterrows():
        print(f"{r['MFE>MAE_%']:>5.1f}% | {r['Filter']}")
    
    print("\n" + "="*90)
    print("🏆 TOP BY 'PERFECT TRADE' RATE (MFE>1% & MAE<0.5%)")
    print("="*90)
    top_perf = results_df.nlargest(5, 'Perfect_Trade_%')
    for _, r in top_perf.iterrows():
        print(f"{r['Perfect_Trade_%']:>5.1f}% | {r['Filter']}")


def main():
    print("="*90)
    print("BOOF 30 — Detailed MFE/MAE with RVOL & VWAP Filters (9:30-11:00 AM)")
    print("="*90)
    
    data = fetch_data()
    if data is None:
        print("No data!")
        return
    
    signals_df = get_all_signals(data)
    if len(signals_df) == 0:
        print("No signals found!")
        return
    
    results = analyze_signals(signals_df)
    print_results(results)
    
    # Save
    signals_df.to_csv('boof30_detailed_signals.csv', index=False)
    results.to_csv('boof30_filter_analysis.csv', index=False)
    print("\n" + "="*90)
    print("Saved: boof30_detailed_signals.csv | boof30_filter_analysis.csv")
    print("="*90)


if __name__ == "__main__":
    main()
