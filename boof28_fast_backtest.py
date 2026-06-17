"""
BOOF 28 - Fast Backtest (reads from local parquet files)
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import os
import glob

DATA_DIR = 'c:/Users/tybre/Desktop/aivibe/boof_data'

def load_stock_data(symbol, start_date, end_date):
    """Load data from local parquet file"""
    # Look for matching file
    pattern = f"{DATA_DIR}/{symbol}_5m_*.parquet"
    files = glob.glob(pattern)
    
    if not files:
        return None
    
    # Load first matching file
    df = pd.read_parquet(files[0])
    
    # Filter to date range
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    mask = (df['timestamp'].dt.date >= start_date.date()) & (df['timestamp'].dt.date <= end_date.date())
    return df[mask].copy()

def calculate_same_time_avg_volume(df, lookback_days=20):
    """Calculate seasonal volume average"""
    df['time'] = df['timestamp'].dt.time
    df['date'] = df['timestamp'].dt.date
    
    dates = sorted(df['date'].unique())
    if len(dates) > lookback_days:
        recent_dates = dates[-lookback_days:]
    else:
        recent_dates = dates
    
    hist_df = df[df['date'].isin(recent_dates[:-1])]
    time_groups = hist_df.groupby('time')['volume'].mean()
    
    avg_volumes = []
    for idx, row in df.iterrows():
        t = row['time']
        if t in time_groups:
            avg_volumes.append(time_groups[t])
        else:
            avg_volumes.append(row['volume'])
    
    return pd.Series(avg_volumes, index=df.index)

def run_backtest(start_date, end_date, symbols, vol_threshold=3.0):
    """Run fast backtest from local data"""
    
    print('='*80)
    print('BOOF 28 - FAST BACKTEST (Local Data)')
    print(f'Period: {start_date.date()} to {end_date.date()}')
    print(f'Stocks: {len(symbols)}')
    print('='*80)
    
    # Generate trading days
    trading_days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            trading_days.append(current)
        current += timedelta(days=1)
    
    print(f'\nScanning {len(trading_days)} days...\n')
    
    all_trades = []
    
    for day_num, trade_date in enumerate(trading_days, 1):
        day_trades = []
        
        for sym in symbols:
            try:
                # Load from local file (FAST)
                df = load_stock_data(sym, trade_date - timedelta(days=25), trade_date + timedelta(days=1))
                if df is None or len(df) < 20:
                    continue
                
                # Calculate seasonal average
                avg_vol = calculate_same_time_avg_volume(df, lookback_days=20)
                
                # Get today's data
                today_mask = df['timestamp'].dt.date == trade_date.date()
                today_df = df[today_mask].reset_index(drop=True)
                today_avg = avg_vol[today_mask].reset_index(drop=True)
                
                if len(today_df) < 10:
                    continue
                
                # Check first 9 bars for spikes
                for i in range(min(9, len(today_df))):
                    if pd.isna(today_avg.iloc[i]) or today_avg.iloc[i] == 0:
                        continue
                    
                    vol_ratio = today_df['volume'].iloc[i] / today_avg.iloc[i]
                    
                    if vol_ratio < vol_threshold:
                        continue
                    
                    # Clean continuation (5 bars)
                    if i + 5 >= len(today_df):
                        continue
                    
                    close_i = today_df['close'].iloc[i]
                    close_i5 = today_df['close'].iloc[i + 5]
                    
                    five_min_move = (close_i5 - close_i) / close_i
                    
                    range_high = today_df['high'].iloc[i+1:i+6].max()
                    range_low = today_df['low'].iloc[i+1:i+6].min()
                    range_chop = range_high - range_low
                    
                    net_move = abs(close_i5 - close_i)
                    trend_efficiency = net_move / range_chop if range_chop > 0 else 0
                    clean_trend = trend_efficiency >= 0.45
                    
                    direction = None
                    if clean_trend and five_min_move > 0.002:
                        direction = 'LONG'
                    elif clean_trend and five_min_move < -0.002:
                        direction = 'SHORT'
                    
                    if not direction:
                        continue
                    
                    # Simulate trade
                    entry_idx = i + 5
                    entry_price = close_i5
                    
                    pnl = None
                    if direction == 'SHORT':
                        tp = entry_price * 0.99
                        sl = entry_price * 1.005
                        for j in range(entry_idx + 1, min(entry_idx + 6, len(today_df))):
                            if today_df['low'].iloc[j] <= tp:
                                pnl = 1.0
                                break
                            if today_df['high'].iloc[j] >= sl:
                                pnl = -0.5
                                break
                    else:
                        tp = entry_price * 1.01
                        sl = entry_price * 0.995
                        for j in range(entry_idx + 1, min(entry_idx + 6, len(today_df))):
                            if today_df['high'].iloc[j] >= tp:
                                pnl = 1.0
                                break
                            if today_df['low'].iloc[j] <= sl:
                                pnl = -0.5
                                break
                    
                    if pnl is None:
                        exit_price = today_df['close'].iloc[min(entry_idx + 5, len(today_df) - 1)]
                        if direction == 'SHORT':
                            pnl = (entry_price - exit_price) / entry_price * 100
                        else:
                            pnl = (exit_price - entry_price) / entry_price * 100
                    
                    if pnl is not None:
                        day_trades.append({
                            'date': trade_date,
                            'symbol': sym,
                            'direction': direction,
                            'pnl': pnl
                        })
                
            except Exception as e:
                pass
        
        if day_trades:
            day_pnl = sum(t['pnl'] for t in day_trades)
            print(f"{trade_date.date()}: {len(day_trades)} trades, P&L: {day_pnl:+.2f}%")
            all_trades.extend(day_trades)
        elif day_num % 10 == 0:
            print(f"{trade_date.date()}: No trades")
    
    print('='*80)
    
    if all_trades:
        df_results = pd.DataFrame(all_trades)
        wins = len(df_results[df_results['pnl'] > 0])
        total_pnl = df_results['pnl'].sum()
        
        print(f'\nFINAL RESULTS:')
        print(f'Total Trades: {len(df_results)}')
        print(f'Win Rate: {wins/len(df_results)*100:.1f}%')
        print(f'Total P&L: {total_pnl:+.2f}%')
        print(f'Avg P&L: {total_pnl/len(df_results):.3f}%')
        
        shorts = df_results[df_results['direction'] == 'SHORT']
        longs = df_results[df_results['direction'] == 'LONG']
        
        if len(shorts) > 0:
            print(f'\nSHORTS: {len(shorts)} trades, {shorts["pnl"].sum():+.2f}%')
        if len(longs) > 0:
            print(f'LONGS: {len(longs)} trades, {longs["pnl"].sum():+.2f}%')
        
        print(f'\nTop Symbols:')
        sym_pnl = df_results.groupby('symbol')['pnl'].sum().sort_values(ascending=False).head(10)
        for sym, pnl in sym_pnl.items():
            count = len(df_results[df_results['symbol'] == sym])
            print(f'  {sym}: {count} trades, {pnl:+.2f}%')
    else:
        print('\nNo trades generated')
    
    print('='*80)

if __name__ == '__main__':
    # Check if data exists
    if not os.path.exists(DATA_DIR) or len(os.listdir(DATA_DIR)) == 0:
        print('\n' + '='*80)
        print('ERROR: No local data found!')
        print(f'Run: python download_data.py')
        print('Then run this backtest.')
        print('='*80)
    else:
        # Run 3-month backtest
        start = datetime(2025, 12, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 28, tzinfo=timezone.utc)
        
        # Get list of available symbols
        files = glob.glob(f'{DATA_DIR}/*.parquet')
        symbols = [os.path.basename(f).split('_')[0] for f in files]
        
        run_backtest(start, end, symbols[:100])  # Top 100 for speed
