"""
BOOF 28 - Volume Spike Study
MSFT: Track returns 5/10/15 min after every volume spike
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

def calculate_same_time_avg_volume(df, lookback_days=20):
    """Calculate average volume for same time slot"""
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

SYMBOLS = ['AAPL', 'NVDA', 'AMZN', 'META', 'AVGO', 'GOOGL', 'TSLA']

def run_study():
    # Last 2 weeks: May 26 - Jun 8, 2026
    start_date = datetime(2026, 5, 26, tzinfo=timezone.utc)
    end_date = datetime(2026, 6, 8, tzinfo=timezone.utc)
    
    # Fetch extra for volume baseline
    fetch_start = start_date - timedelta(days=25)
    fetch_end = end_date + timedelta(days=1)
    
    print('='*100)
    print(f'VOLUME SPIKE STUDY: {symbol}')
    print(f'Period: {start_date.date()} to {end_date.date()} (2 weeks)')
    print(f'Spike threshold: 2.0x average volume')
    print('='*100)
    
    # Get data
    print(f'\nFetching data...')
    df = fetch_alpaca_bars(symbol, fetch_start, fetch_end, '5Min', 
                           creds['api_key'], creds['secret_key'])
    
    if df is None or len(df) < 50:
        print('No data available')
        return
    
    # Standardize
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    
    # Calculate volume ratio
    avg_vol = calculate_same_time_avg_volume(df, lookback_days=20)
    df['vol_ratio'] = df['volume'] / avg_vol
    
    # Filter to market hours (9:30 AM - 4:00 PM ET)
    df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
    df['minute'] = df['timestamp'].dt.minute
    df['time_et'] = df['hour_et'] * 100 + df['minute']
    
    # Market hours: 9:30 - 16:00 ET
    market_mask = (df['time_et'] >= 930) & (df['time_et'] <= 1600)
    df_market = df[market_mask].copy()
    
    # Spike threshold
    SPIKE_THRESHOLD = 2.0
    
    # Find all spikes
    spikes = []
    
    for idx in range(len(df_market)):
        if pd.isna(df_market['vol_ratio'].iloc[idx]):
            continue
        
        vol_ratio = df_market['vol_ratio'].iloc[idx]
        
        if vol_ratio >= SPIKE_THRESHOLD:
            # Get spike details
            spike_price = df_market['close'].iloc[idx]
            spike_time = df_market['timestamp'].iloc[idx]
            spike_time_et = spike_time - timedelta(hours=5)
            
            # Calculate returns at 5, 10, 15 min (1, 2, 3 bars of 5m)
            ret_5min = None
            ret_10min = None
            ret_15min = None
            
            if idx + 1 < len(df_market):
                price_5min = df_market['close'].iloc[idx + 1]
                ret_5min = (price_5min - spike_price) / spike_price * 100
            
            if idx + 2 < len(df_market):
                price_10min = df_market['close'].iloc[idx + 2]
                ret_10min = (price_10min - spike_price) / spike_price * 100
            
            if idx + 3 < len(df_market):
                price_15min = df_market['close'].iloc[idx + 3]
                ret_15min = (price_15min - spike_price) / spike_price * 100
            
            # Determine direction of spike candle
            open_price = df_market['open'].iloc[idx]
            close_price = df_market['close'].iloc[idx]
            direction = 'UP' if close_price >= open_price else 'DOWN'
            
            spikes.append({
                'date': spike_time_et.date(),
                'time': spike_time_et.strftime('%H:%M'),
                'rvol': round(vol_ratio, 2),
                'direction': direction,
                'spike_price': spike_price,
                'ret_5min': ret_5min,
                'ret_10min': ret_10min,
                'ret_15min': ret_15min
            })
    
    if not spikes:
        print('\nNo volume spikes found')
        return
    
    # Convert to DataFrame
    df_spikes = pd.DataFrame(spikes)
    
    # Print all spikes
    print(f'\nFound {len(df_spikes)} volume spikes:\n')
    print(f"{'Date':12} {'Time':8} {'RVOL':6} {'Dir':5} {'5min':8} {'10min':8} {'15min':8}")
    print('-'*100)
    
    for _, row in df_spikes.iterrows():
        r5 = f"{row['ret_5min']:+.2f}%" if row['ret_5min'] is not None else "N/A"
        r10 = f"{row['ret_10min']:+.2f}%" if row['ret_10min'] is not None else "N/A"
        r15 = f"{row['ret_15min']:+.2f}%" if row['ret_15min'] is not None else "N/A"
        print(f"{row['date']!s:12} {row['time']:8} {row['rvol']:6.2f} {row['direction']:5} {r5:8} {r10:8} {r15:8}")
    
    # Calculate statistics
    print('\n' + '='*100)
    print('STATISTICS:')
    print('='*100)
    
    for minutes, col in [('5-minute', 'ret_5min'), ('10-minute', 'ret_10min'), ('15-minute', 'ret_15min')]:
        valid_returns = df_spikes[col].dropna()
        
        if len(valid_returns) == 0:
            continue
        
        wins = len(valid_returns[valid_returns > 0])
        losses = len(valid_returns[valid_returns < 0])
        total = len(valid_returns)
        
        win_rate = wins / total * 100 if total > 0 else 0
        avg_return = valid_returns.mean()
        
        # Profit factor (gross wins / gross losses)
        gross_wins = valid_returns[valid_returns > 0].sum()
        gross_losses = abs(valid_returns[valid_returns < 0].sum())
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        
        print(f'\n{minutes} Returns:')
        print(f'  Count: {total}')
        print(f'  Win Rate: {win_rate:.1f}% ({wins} wins, {losses} losses)')
        print(f'  Avg Return: {avg_return:+.3f}%')
        print(f'  Profit Factor: {profit_factor:.2f}')
        print(f'  Best: {valid_returns.max():+.2f}%')
        print(f'  Worst: {valid_returns.min():+.2f}%')
    
    # By spike direction
    print('\n' + '='*100)
    print('BY SPIKE DIRECTION (10-minute returns):')
    print('='*100)
    
    for direction in ['UP', 'DOWN']:
        dir_spikes = df_spikes[df_spikes['direction'] == direction]['ret_10min'].dropna()
        if len(dir_spikes) > 0:
            wins = len(dir_spikes[dir_spikes > 0])
            total = len(dir_spikes)
            print(f'\n{direction} spikes ({total}):')
            print(f'  Win Rate: {wins/total*100:.1f}%')
            print(f'  Avg Return: {dir_spikes.mean():+.3f}%')
            print(f'  Best: {dir_spikes.max():+.2f}%')
            print(f'  Worst: {dir_spikes.min():+.2f}%')
    
    print('\n' + '='*100)

if __name__ == '__main__':
    run_study()
