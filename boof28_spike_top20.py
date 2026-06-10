"""
BOOF 28 - Top 20 Spikes by RVOL (with 10/20/30 min returns)
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

SYMBOLS = ['AAPL', 'NVDA', 'AMZN', 'META', 'AVGO', 'GOOGL', 'TSLA']

def calculate_same_time_avg_volume(df, lookback_days=20):
    df['time_of_day'] = df['timestamp'].dt.time
    df['date'] = df['timestamp'].dt.date
    
    dates = sorted(df['date'].unique())
    if len(dates) > lookback_days:
        recent_dates = dates[-lookback_days:]
    else:
        recent_dates = dates
    
    hist_df = df[df['date'].isin(recent_dates[:-1])]
    if len(hist_df) == 0:
        return pd.Series(df['volume'].mean(), index=df.index)
    
    time_groups = hist_df.groupby('time_of_day')['volume'].mean()
    
    avg_volumes = []
    for idx, row in df.iterrows():
        t = row['time_of_day']
        if t in time_groups and time_groups[t] > 0:
            avg_volumes.append(time_groups[t])
        else:
            avg_volumes.append(row['volume'])
    
    return pd.Series(avg_volumes, index=df.index)

def analyze_symbol(symbol, start_date, end_date):
    fetch_start = start_date - timedelta(days=25)
    fetch_end = end_date + timedelta(days=1)
    
    try:
        df = fetch_alpaca_bars(symbol, fetch_start, fetch_end, '5Min', 
                               creds['api_key'], creds['secret_key'])
        
        if df is None or len(df) < 50:
            return []
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        
        avg_vol = calculate_same_time_avg_volume(df, lookback_days=20)
        df['vol_ratio'] = df['volume'] / avg_vol
        
        # Morning window: 9:00-11:00 AM ET
        df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
        df['minute'] = df['timestamp'].dt.minute
        df['time_et'] = df['hour_et'] * 100 + df['minute']
        market_mask = (df['time_et'] >= 900) & (df['time_et'] <= 1100)
        df_market = df[market_mask].copy()
        
        spikes = []
        SPIKE_THRESHOLD = 2.0
        
        for idx in range(len(df_market)):
            if pd.isna(df_market['vol_ratio'].iloc[idx]):
                continue
            
            vol_ratio = df_market['vol_ratio'].iloc[idx]
            
            if vol_ratio >= SPIKE_THRESHOLD:
                spike_price = df_market['close'].iloc[idx]
                spike_time = df_market['timestamp'].iloc[idx]
                spike_time_et = spike_time - timedelta(hours=5)
                
                # Returns at 10, 20, 30 min (2, 4, 6 bars of 5m)
                ret_10min = None
                ret_20min = None
                ret_30min = None
                
                if idx + 2 < len(df_market):
                    ret_10min = (df_market['close'].iloc[idx + 2] - spike_price) / spike_price * 100
                if idx + 4 < len(df_market):
                    ret_20min = (df_market['close'].iloc[idx + 4] - spike_price) / spike_price * 100
                if idx + 6 < len(df_market):
                    ret_30min = (df_market['close'].iloc[idx + 6] - spike_price) / spike_price * 100
                
                spikes.append({
                    'date': spike_time_et.strftime('%Y-%m-%d'),
                    'time': spike_time_et.strftime('%H:%M'),
                    'symbol': symbol,
                    'rvol': round(vol_ratio, 2),
                    'ret_10m': ret_10min,
                    'ret_20m': ret_20min,
                    'ret_30m': ret_30min
                })
        
        return spikes
    except Exception as e:
        return []

def run_study():
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*90)
    print('TOP 20 SPIKES BY RVOL - 3 MONTHS (Mar-May 2026)')
    print('Window: 9:00-11:00 AM ET | Spike: 2.0x+ volume')
    print('='*90)
    
    all_spikes = []
    
    for sym in SYMBOLS:
        spikes = analyze_symbol(sym, start_date, end_date)
        all_spikes.extend(spikes)
        time.sleep(0.3)
    
    if not all_spikes:
        print('No spikes found')
        return
    
    df = pd.DataFrame(all_spikes)
    
    # Sort by RVOL descending and take top 20
    top20 = df.nlargest(20, 'rvol')
    
    print(f'\nTotal spikes found: {len(df)}')
    print(f'Top 20 by RVOL:\n')
    
    # Header
    print(f"{'Date':12} {'Symbol':8} {'RVOL':8} {'10min':10} {'20min':10} {'30min':10}")
    print('-'*90)
    
    # Print each spike
    for _, row in top20.iterrows():
        r10 = f"{row['ret_10m']:+.2f}%" if pd.notna(row['ret_10m']) else "N/A"
        r20 = f"{row['ret_20m']:+.2f}%" if pd.notna(row['ret_20m']) else "N/A"
        r30 = f"{row['ret_30m']:+.2f}%" if pd.notna(row['ret_30m']) else "N/A"
        
        print(f"{row['date']:12} {row['symbol']:8} {row['rvol']:8.2f} {r10:10} {r20:10} {r30:10}")
    
    print('='*90)
    
    # Stats on top 20
    valid_10m = top20['ret_10m'].dropna()
    valid_20m = top20['ret_20m'].dropna()
    valid_30m = top20['ret_30m'].dropna()
    
    print(f'\nTOP 20 SPIKES - PERFORMANCE:')
    if len(valid_10m) > 0:
        print(f'  10min: {valid_10m.mean():+.3f}% avg | {len(valid_10m[valid_10m>0])}/{len(valid_10m)} wins')
    if len(valid_20m) > 0:
        print(f'  20min: {valid_20m.mean():+.3f}% avg | {len(valid_20m[valid_20m>0])}/{len(valid_20m)} wins')
    if len(valid_30m) > 0:
        print(f'  30min: {valid_30m.mean():+.3f}% avg | {len(valid_30m[valid_30m>0])}/{len(valid_30m)} wins')
    
    print('='*90)

if __name__ == '__main__':
    run_study()
