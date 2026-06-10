"""
BOOF 28 - Strong Confirmation MFE/MAE Study
Filters: RVOL>2.5, 5min move>0.4%, trend eff>0.6, EMA20 alignment
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

def calculate_ema(prices, period=20):
    """Calculate EMA"""
    return prices.ewm(span=period, adjust=False).mean()

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
        
        # Calculate indicators
        avg_vol = calculate_same_time_avg_volume(df, lookback_days=20)
        df['vol_ratio'] = df['volume'] / avg_vol
        df['ema20'] = calculate_ema(df['close'], 20)
        
        # Morning window: 9:00-11:00 AM ET
        df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
        df['minute'] = df['timestamp'].dt.minute
        df['time_et'] = df['hour_et'] * 100 + df['minute']
        market_mask = (df['time_et'] >= 900) & (df['time_et'] <= 1100)
        df_market = df[market_mask].copy()
        
        if len(df_market) < 10:
            return []
        
        # Recalculate EMA20 for market hours data
        df_market = df_market.reset_index(drop=True)
        df_market['ema20'] = calculate_ema(df_market['close'], 20)
        
        trades = []
        
        # STRONGER FILTERS
        RVOL_THRESHOLD = 2.5
        MOVE_THRESHOLD = 0.004  # 0.4%
        EFF_THRESHOLD = 0.6
        
        for i in range(len(df_market) - 6):
            if pd.isna(df_market['vol_ratio'].iloc[i]):
                continue
            
            vol_ratio = df_market['vol_ratio'].iloc[i]
            
            # Filter 1: Volume spike >= 2.5x
            if vol_ratio < RVOL_THRESHOLD:
                continue
            
            spike_price = df_market['close'].iloc[i]
            spike_time = df_market['timestamp'].iloc[i]
            spike_time_et = spike_time - timedelta(hours=5)
            
            # Calculate 5-minute move (next bar)
            if i + 1 >= len(df_market):
                continue
            
            bar_5min = df_market.iloc[i + 1]
            move_5min = (bar_5min['close'] - spike_price) / spike_price
            
            # Calculate trend efficiency over spike + 5min
            window_high = df_market['high'].iloc[i:i+2].max()
            window_low = df_market['low'].iloc[i:i+2].min()
            window_range = max(window_high - window_low, 0.01)
            trend_eff = abs(bar_5min['close'] - spike_price) / window_range
            
            # Get EMA20 at 5min bar
            ema20_5min = bar_5min['ema20']
            
            # Determine direction and check filters
            direction = None
            entry_price = None
            
            if move_5min >= MOVE_THRESHOLD:
                # Potential LONG
                if trend_eff >= EFF_THRESHOLD and bar_5min['close'] > ema20_5min:
                    direction = 'LONG'
                    entry_price = bar_5min['close']
            elif move_5min <= -MOVE_THRESHOLD:
                # Potential SHORT
                if trend_eff >= EFF_THRESHOLD and bar_5min['close'] < ema20_5min:
                    direction = 'SHORT'
                    entry_price = bar_5min['close']
            
            if not direction:
                continue
            
            entry_bar = i + 1
            
            # Measure MFE/MAE for next 30 minutes (6 bars)
            mfe_window_end = min(entry_bar + 7, len(df_market))
            mfe_window = df_market.iloc[entry_bar:mfe_window_end]
            
            if len(mfe_window) < 2:
                continue
            
            max_high = mfe_window['high'].max()
            min_low = mfe_window['low'].min()
            
            if direction == 'LONG':
                mfe = (max_high - entry_price) / entry_price * 100
                mae = (entry_price - min_low) / entry_price * 100
            else:
                mfe = (entry_price - min_low) / entry_price * 100
                mae = (max_high - entry_price) / entry_price * 100
            
            # Time-to-MFE
            time_to_mfe = None
            if direction == 'LONG':
                for idx_bar, (idx, row_bar) in enumerate(mfe_window.iterrows()):
                    if row_bar['high'] >= max_high * 0.999:
                        time_to_mfe = idx_bar * 5
                        break
            else:
                for idx_bar, (idx, row_bar) in enumerate(mfe_window.iterrows()):
                    if row_bar['low'] <= min_low * 1.001:
                        time_to_mfe = idx_bar * 5
                        break
            
            # Returns at 10/20/30 min
            ret_10m = ret_20m = ret_30m = None
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
                'move_5m': round(move_5min * 100, 2),
                'trend_eff': round(trend_eff, 2),
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
        print(f"ERROR: {str(e)[:50]}")
        return []

def run_study():
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('STRONG CONFIRMATION MFE/MAE STUDY')
    print('Filters: RVOL>2.5, 5min move>0.4%, trend eff>0.6, EMA20 aligned')
    print(f'Stocks: {", ".join(SYMBOLS)}')
    print(f'Period: {start_date.date()} to {end_date.date()} (3 months)')
    print('='*100)
    
    all_trades = []
    
    for sym in SYMBOLS:
        print(f'\nAnalyzing {sym}...', end=' ')
        trades = analyze_symbol(sym, start_date, end_date)
        print(f'{len(trades)} trades')
        all_trades.extend(trades)
        time.sleep(0.3)
    
    if not all_trades:
        print('\nNo trades found with these filters')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*100)
    print(f'TOTAL: {len(df)} trades (strong confirmation only)')
    print('='*100)
    
    # MFE/MAE Stats
    mfe_values = df['mfe'].dropna()
    mae_values = df['mae'].dropna()
    
    if len(mfe_values) > 0:
        print(f'\nMFE STATISTICS:')
        print(f'  Average: {mfe_values.mean():.2f}%')
        print(f'  Median: {mfe_values.median():.2f}%')
        print(f'  Max: {mfe_values.max():.2f}%')
        print(f'  Trades with MFE>1%: {len(mfe_values[mfe_values > 1])}/{len(mfe_values)} ({len(mfe_values[mfe_values > 1])/len(mfe_values)*100:.1f}%)')
    
    if len(mae_values) > 0:
        print(f'\nMAE STATISTICS:')
        print(f'  Average: {mae_values.mean():.2f}%')
        print(f'  Median: {mae_values.median():.2f}%')
        print(f'  95th percentile: {mae_values.quantile(0.95):.2f}%')
        print(f'  Max: {mae_values.max():.2f}%')
    
    if len(mfe_values) > 0 and len(mae_values) > 0:
        print(f'\nMFE vs MAE:')
        print(f'  Avg MFE - Avg MAE = {mfe_values.mean() - mae_values.mean():+.2f}%')
        good_trades = len(df[df['mfe'] > df['mae']])
        print(f'  Trades where MFE > MAE: {good_trades}/{len(df)} ({good_trades/len(df)*100:.1f}%)')
    
    # Time-to-MFE
    ttm = df['time_to_mfe'].dropna()
    if len(ttm) > 0:
        print(f'\nTIME-TO-MFE:')
        print(f'  Average: {ttm.mean():.1f} min | Median: {ttm.median():.1f} min')
    
    # By symbol
    print('\n' + '='*100)
    print('BY SYMBOL:')
    print('='*100)
    print(f"{'Symbol':10} {'Trades':8} {'Avg MFE':10} {'Avg MAE':10} {'MFE>MAE':10} {'Best MFE':10}")
    print('-'*100)
    
    for sym in SYMBOLS:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) == 0:
            continue
        
        mfe_sym = sym_data['mfe'].dropna()
        mae_sym = sym_data['mae'].dropna()
        good = len(sym_data[sym_data['mfe'] > sym_data['mae']])
        
        print(f"{sym:10} {len(sym_data):8} {mfe_sym.mean():9.2f}% {mae_sym.mean():9.2f}% {good:5}/{len(sym_data):<4} {mfe_sym.max():9.2f}%")
    
    # All trades
    print('\n' + '='*100)
    print(f'ALL {len(df)} TRADES:')
    print('='*100)
    print(f"{'Date':12} {'Time':8} {'Sym':6} {'RVOL':6} {'Move':6} {'Eff':5} {'Dir':5} {'MFE':7} {'MAE':7} {'TTM':5}")
    print('-'*100)
    
    for _, row in df.iterrows():
        ttm = f"{row['time_to_mfe']:.0f}m" if pd.notna(row['time_to_mfe']) else "N/A"
        print(f"{row['date']:12} {row['time']:8} {row['symbol']:6} {row['rvol']:6.2f} {row['move_5m']:5.2f}% {row['trend_eff']:5.2f} {row['direction']:5} {row['mfe']:6.2f}% {row['mae']:6.2f}% {ttm:5}")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
