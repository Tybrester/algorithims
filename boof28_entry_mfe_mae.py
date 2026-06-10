"""
BOOF 28 - Entry After Confirmation with MFE/MAE/Time-to-MFE
Signal: volume spike -> Wait 5min -> If direction intact -> Enter -> Measure MFE/MAE
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
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
        
        trades = []
        SPIKE_THRESHOLD = 2.0
        
        for i in range(len(df_market) - 7):  # Need room for wait + MFE window
            if pd.isna(df_market['vol_ratio'].iloc[i]):
                continue
            
            vol_ratio = df_market['vol_ratio'].iloc[i]
            
            # Stage 1: Volume spike >= 2.0x
            if vol_ratio < SPIKE_THRESHOLD:
                continue
            
            spike_price = df_market['close'].iloc[i]
            spike_open = df_market['open'].iloc[i]
            spike_close = df_market['close'].iloc[i]
            spike_direction = 'UP' if spike_close >= spike_open else 'DOWN'
            
            spike_time = df_market['timestamp'].iloc[i]
            spike_time_et = spike_time - timedelta(hours=5)
            
            # Stage 2: Wait 5 minutes (1 bar of 5m)
            wait_bar = i + 1
            if wait_bar >= len(df_market):
                continue
            
            wait_price = df_market['close'].iloc[wait_bar]
            wait_move = (wait_price - spike_price) / spike_price
            
            # Check if direction still intact
            direction = None
            if spike_direction == 'UP' and wait_move > 0:
                direction = 'LONG'
            elif spike_direction == 'DOWN' and wait_move < 0:
                direction = 'SHORT'
            
            if not direction:
                continue  # Direction not intact, skip
            
            # ENTRY at wait_bar close
            entry_price = wait_price
            entry_bar = wait_bar
            
            # Stage 3: Measure MFE/MAE for next 30 minutes (6 bars of 5m)
            mfe_window_end = min(entry_bar + 7, len(df_market))
            mfe_window = df_market.iloc[entry_bar:mfe_window_end]
            
            if len(mfe_window) < 2:
                continue
            
            max_high = mfe_window['high'].max()
            min_low = mfe_window['low'].min()
            
            # Calculate MFE and MAE from entry point
            if direction == 'LONG':
                mfe = (max_high - entry_price) / entry_price * 100
                mae = (entry_price - min_low) / entry_price * 100
            else:  # SHORT
                mfe = (entry_price - min_low) / entry_price * 100
                mae = (max_high - entry_price) / entry_price * 100
            
            # Find time-to-MFE (which bar reached max favorable)
            time_to_mfe = None
            if direction == 'LONG':
                for idx_bar, (idx, row) in enumerate(mfe_window.iterrows()):
                    if row['high'] >= max_high * 0.999:  # Within 0.1% of max
                        time_to_mfe = idx_bar * 5  # Convert bars to minutes
                        break
            else:
                for idx_bar, (idx, row) in enumerate(mfe_window.iterrows()):
                    if row['low'] <= min_low * 1.001:  # Within 0.1% of min
                        time_to_mfe = idx_bar * 5
                        break
            
            # Also get 10/20/30 min returns from entry
            ret_10m = None
            ret_20m = None
            ret_30m = None
            
            if entry_bar + 2 < len(df_market):
                ret_10m = (df_market['close'].iloc[entry_bar + 2] - entry_price) / entry_price * 100
            if entry_bar + 4 < len(df_market):
                ret_20m = (df_market['close'].iloc[entry_bar + 4] - entry_price) / entry_price * 100
            if entry_bar + 6 < len(df_market):
                ret_30m = (df_market['close'].iloc[entry_bar + 6] - entry_price) / entry_price * 100
            
            trades.append({
                'date': spike_time_et.strftime('%Y-%m-%d'),
                'time': spike_time_et.strftime('%H:%M'),
                'symbol': symbol,
                'rvol': round(vol_ratio, 2),
                'direction': direction,
                'entry_price': entry_price,
                'mfe': round(mfe, 2),
                'mae': round(mae, 2),
                'time_to_mfe': time_to_mfe,
                'ret_10m': ret_10m,
                'ret_20m': ret_20m,
                'ret_30m': ret_30m
            })
        
        return trades
    except Exception as e:
        return []

def run_study():
    # 3 months: March 1 - May 31, 2026
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('ENTRY-AFTER-CONFIRMATION MFE/MAE STUDY')
    print(f'Stocks: {", ".join(SYMBOLS)}')
    print(f'Period: {start_date.date()} to {end_date.date()} (3 months)')
    print(f'Signal: 2.0x vol spike -> Wait 5min -> If direction intact -> Enter')
    print(f'Measure: MFE, MAE, Time-to-MFE over next 30min')
    print('='*100)
    
    all_trades = []
    
    for sym in SYMBOLS:
        print(f'\nAnalyzing {sym}...', end=' ')
        trades = analyze_symbol(sym, start_date, end_date)
        print(f'{len(trades)} trades')
        all_trades.extend(trades)
        time.sleep(0.3)
    
    if not all_trades:
        print('\nNo trades found')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*100)
    print(f'TOTAL: {len(df)} trades')
    print('='*100)
    
    # MFE Statistics
    mfe_values = df['mfe'].dropna()
    if len(mfe_values) > 0:
        print(f'\nMFE STATISTICS (from entry point):')
        print(f'  Average MFE: {mfe_values.mean():.2f}%')
        print(f'  Median MFE: {mfe_values.median():.2f}%')
        print(f'  Max MFE: {mfe_values.max():.2f}%')
        print(f'  MFE > 1%: {len(mfe_values[mfe_values > 1])}/{len(mfe_values)} ({len(mfe_values[mfe_values > 1])/len(mfe_values)*100:.1f}%)')
        print(f'  MFE > 2%: {len(mfe_values[mfe_values > 2])}/{len(mfe_values)} ({len(mfe_values[mfe_values > 2])/len(mfe_values)*100:.1f}%)')
    
    # MAE Statistics  
    mae_values = df['mae'].dropna()
    if len(mae_values) > 0:
        print(f'\nMAE STATISTICS (from entry point):')
        print(f'  Average MAE: {mae_values.mean():.2f}%')
        print(f'  Median MAE: {mae_values.median():.2f}%')
        print(f'  95th percentile MAE: {mae_values.quantile(0.95):.2f}%')
        print(f'  Max MAE: {mae_values.max():.2f}%')
    
    # Time-to-MFE
    ttm_values = df['time_to_mfe'].dropna()
    if len(ttm_values) > 0:
        print(f'\nTIME-TO-MFE:')
        print(f'  Average: {ttm_values.mean():.1f} minutes')
        print(f'  Median: {ttm_values.median():.1f} minutes')
        print(f'  Fastest: {ttm_values.min():.0f} minutes')
        print(f'  Slowest: {ttm_values.max():.0f} minutes')
    
    # By direction
    print('\n' + '='*100)
    print('BY DIRECTION:')
    print('='*100)
    
    for direction in ['LONG', 'SHORT']:
        dir_data = df[df['direction'] == direction]
        if len(dir_data) == 0:
            continue
        
        dir_mfe = dir_data['mfe'].dropna()
        dir_mae = dir_data['mae'].dropna()
        
        print(f'\n{direction} ({len(dir_data)} trades):')
        if len(dir_mfe) > 0:
            print(f'  MFE: {dir_mfe.mean():.2f}% avg, {dir_mfe.median():.2f}% median')
        if len(dir_mae) > 0:
            print(f'  MAE: {dir_mae.mean():.2f}% avg, {dir_mae.median():.2f}% median')
    
    # By symbol
    print('\n' + '='*100)
    print('BY SYMBOL:')
    print('='*100)
    print(f"{'Symbol':10} {'Trades':8} {'Avg MFE':12} {'Avg MAE':12} {'MFE>MAE':10}")
    print('-'*100)
    
    for sym in SYMBOLS:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) == 0:
            continue
        
        sym_mfe = sym_data['mfe'].dropna()
        sym_mae = sym_data['mae'].dropna()
        
        avg_mfe = sym_mfe.mean() if len(sym_mfe) > 0 else 0
        avg_mae = sym_mae.mean() if len(sym_mae) > 0 else 0
        
        # Count where MFE > MAE (good trades)
        mfe_gt_mae = len(sym_data[sym_data['mfe'] > sym_data['mae']])
        
        print(f"{sym:10} {len(sym_data):8} {avg_mfe:11.2f}% {avg_mae:11.2f}% {mfe_gt_mae:5}/{len(sym_data):<4}")
    
    # Top 20 by MFE
    print('\n' + '='*100)
    print('TOP 20 TRADES BY MFE:')
    print('='*100)
    print(f"{'Date':12} {'Time':8} {'Symbol':8} {'RVOL':8} {'Dir':6} {'MFE':8} {'MAE':8} {'TTM':6}")
    print('-'*100)
    
    top20 = df.nlargest(20, 'mfe')
    for _, row in top20.iterrows():
        ttm = f"{row['time_to_mfe']:.0f}m" if pd.notna(row['time_to_mfe']) else "N/A"
        print(f"{row['date']:12} {row['time']:8} {row['symbol']:8} {row['rvol']:8.2f} {row['direction']:6} {row['mfe']:7.2f}% {row['mae']:7.2f}% {ttm:6}")
    
    print('\n' + '='*100)

if __name__ == '__main__':
    run_study()
