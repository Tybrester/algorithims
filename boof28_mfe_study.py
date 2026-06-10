"""
BOOF 28 - Maximum Favorable Excursion (MFE) Study
30-minute MFE for every volume spike
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
                spike_open = df_market['open'].iloc[idx]
                spike_close = df_market['close'].iloc[idx]
                direction = 'UP' if spike_close >= spike_open else 'DOWN'
                
                # Get next 30 minutes (6 bars of 5m)
                end_idx = min(idx + 6, len(df_market) - 1)
                window = df_market.iloc[idx+1:end_idx+1]
                
                if len(window) == 0:
                    continue
                
                # Calculate MFE and MAE
                max_high = window['high'].max()
                min_low = window['low'].min()
                
                # MFE - max favorable excursion
                if direction == 'UP':
                    mfe = (max_high - spike_price) / spike_price * 100
                    mae = (spike_price - min_low) / spike_price * 100  # How far against
                else:
                    mfe = (spike_price - min_low) / spike_price * 100
                    mae = (max_high - spike_price) / spike_price * 100  # How far against
                
                # Also calculate actual returns at 10/20/30 min
                ret_10m = None
                ret_20m = None
                ret_30m = None
                
                if idx + 2 < len(df_market):
                    ret_10m = (df_market['close'].iloc[idx + 2] - spike_price) / spike_price * 100
                if idx + 4 < len(df_market):
                    ret_20m = (df_market['close'].iloc[idx + 4] - spike_price) / spike_price * 100
                if idx + 6 < len(df_market):
                    ret_30m = (df_market['close'].iloc[idx + 6] - spike_price) / spike_price * 100
                
                # MFE capture ratio at 30min (if 30min close available)
                mfe_capture = None
                if ret_30m is not None and mfe > 0:
                    mfe_capture = (ret_30m / mfe * 100) if mfe != 0 else 0
                
                spikes.append({
                    'date': spike_time_et.strftime('%Y-%m-%d'),
                    'time': spike_time_et.strftime('%H:%M'),
                    'symbol': symbol,
                    'rvol': round(vol_ratio, 2),
                    'direction': direction,
                    'mfe_30m': round(mfe, 2),
                    'mae_30m': round(mae, 2),
                    'ret_10m': ret_10m,
                    'ret_20m': ret_20m,
                    'ret_30m': ret_30m,
                    'mfe_capture_30m': mfe_capture
                })
        
        return spikes
    except Exception as e:
        return []

def run_study():
    # 3 months: March 1 - May 31, 2026
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('MAXIMUM FAVORABLE EXCURSION (MFE) STUDY - 3 MONTHS')
    print(f'Stocks: {", ".join(SYMBOLS)}')
    print(f'Period: {start_date.date()} to {end_date.date()}')
    print(f'Window: 9:00-11:00 AM ET | Spike: 2.0x+ volume | MFE: 30min window')
    print('='*100)
    
    all_spikes = []
    
    for sym in SYMBOLS:
        print(f'Analyzing {sym}...', end=' ')
        spikes = analyze_symbol(sym, start_date, end_date)
        print(f'{len(spikes)} spikes')
        all_spikes.extend(spikes)
        time.sleep(0.3)
    
    if not all_spikes:
        print('No spikes found')
        return
    
    df = pd.DataFrame(all_spikes)
    
    print('\n' + '='*100)
    print(f'TOTAL: {len(df)} spikes analyzed')
    print('='*100)
    
    # Overall MFE stats
    mfe_values = df['mfe_30m'].dropna()
    if len(mfe_values) > 0:
        print(f'\nMFE STATISTICS (30-minute window):')
        print(f'  Average MFE: {mfe_values.mean():.2f}%')
        print(f'  Median MFE: {mfe_values.median():.2f}%')
        print(f'  Max MFE: {mfe_values.max():.2f}%')
        print(f'  Min MFE: {mfe_values.min():.2f}%')
        print(f'  MFE > 1%: {len(mfe_values[mfe_values > 1])}/{len(mfe_values)} ({len(mfe_values[mfe_values > 1])/len(mfe_values)*100:.1f}%)')
        print(f'  MFE > 2%: {len(mfe_values[mfe_values > 2])}/{len(mfe_values)} ({len(mfe_values[mfe_values > 2])/len(mfe_values)*100:.1f}%)')
    
    # MAE stats
    mae_values = df['mae_30m'].dropna()
    if len(mae_values) > 0:
        print(f'\nMAE STATISTICS (Maximum Adverse Excursion):')
        print(f'  Average MAE: {mae_values.mean():.2f}%')
        print(f'  Median MAE: {mae_values.median():.2f}%')
        print(f'  95th percentile MAE: {mae_values.quantile(0.95):.2f}%')
        print(f'  Max MAE: {mae_values.max():.2f}%')
    
    # By direction
    print('\n' + '='*100)
    print('MFE BY SPIKE DIRECTION:')
    print('='*100)
    
    for direction in ['UP', 'DOWN']:
        dir_mfe = df[df['direction'] == direction]['mfe_30m'].dropna()
        if len(dir_mfe) > 0:
            print(f'\n{direction} spikes ({len(dir_mfe)}):')
            print(f'  Avg MFE: {dir_mfe.mean():.2f}%')
            print(f'  Median MFE: {dir_mfe.median():.2f}%')
            print(f'  Max MFE: {dir_mfe.max():.2f}%')
            print(f'  MFE > 1%: {len(dir_mfe[dir_mfe > 1])}/{len(dir_mfe)} ({len(dir_mfe[dir_mfe > 1])/len(dir_mfe)*100:.1f}%)')
    
    # By symbol
    print('\n' + '='*100)
    print('MFE BY SYMBOL:')
    print('='*100)
    print(f"{'Symbol':10} {'Spikes':8} {'Avg MFE':12} {'Max MFE':10} {'MFE>1%':10}")
    print('-'*100)
    
    for sym in SYMBOLS:
        sym_mfe = df[df['symbol'] == sym]['mfe_30m'].dropna()
        if len(sym_mfe) == 0:
            continue
        
        avg_mfe = sym_mfe.mean()
        max_mfe = sym_mfe.max()
        mfe_gt_1 = len(sym_mfe[sym_mfe > 1])
        pct_gt_1 = mfe_gt_1 / len(sym_mfe) * 100
        
        print(f"{sym:10} {len(sym_mfe):8} {avg_mfe:11.2f}% {max_mfe:9.2f}% {mfe_gt_1:5}/{len(sym_mfe):<4} ({pct_gt_1:.0f}%)")
    
    # Top 20 by MFE
    print('\n' + '='*100)
    print('TOP 20 SPIKES BY MFE:')
    print('='*100)
    print(f"{'Date':12} {'Time':8} {'Symbol':8} {'RVOL':8} {'Dir':5} {'MFE':10} {'Ret30m':10} {'Capture':10}")
    print('-'*100)
    
    top20_mfe = df.nlargest(20, 'mfe_30m')
    for _, row in top20_mfe.iterrows():
        r30 = f"{row['ret_30m']:+.2f}%" if pd.notna(row['ret_30m']) else "N/A"
        cap = f"{row['mfe_capture_30m']:.0f}%" if pd.notna(row['mfe_capture_30m']) else "N/A"
        print(f"{row['date']:12} {row['time']:8} {row['symbol']:8} {row['rvol']:8.2f} {row['direction']:5} {row['mfe_30m']:9.2f}% {r30:10} {cap:10}")
    
    # MFE vs actual return comparison
    print('\n' + '='*100)
    print('MFE vs ACTUAL 30-MIN RETURN:')
    print('='*100)
    
    valid_both = df[df['mfe_30m'].notna() & df['ret_30m'].notna()]
    if len(valid_both) > 0:
        avg_mfe = valid_both['mfe_30m'].mean()
        avg_ret = valid_both['ret_30m'].mean()
        avg_capture = valid_both['mfe_capture_30m'].mean()
        
        print(f'  Average MFE: {avg_mfe:.2f}%')
        print(f'  Average 30min Return: {avg_ret:.2f}%')
        print(f'  Average MFE Capture: {avg_capture:.1f}%')
        print(f'\n  You captured {avg_capture:.0f}% of available MFE on average')
    
    print('='*100)

if __name__ == '__main__':
    run_study()
