"""
BOOF 28 - Multi-Stock Volume Spike Study
7 stocks: AAPL, NVDA, AMZN, META, AVGO, GOOGL, TSLA
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
    """Analyze one symbol, return all spikes"""
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
        
        # Calculate volume ratio
        avg_vol = calculate_same_time_avg_volume(df, lookback_days=20)
        df['vol_ratio'] = df['volume'] / avg_vol
        
        # Morning window filter: 9:00-11:00 AM ET only
        df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
        df['minute'] = df['timestamp'].dt.minute
        df['time_et'] = df['hour_et'] * 100 + df['minute']
        market_mask = (df['time_et'] >= 900) & (df['time_et'] <= 1100)  # 9-11 AM
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
                
                # Returns at 5, 10, 15 min
                ret_5min = None
                ret_10min = None
                ret_15min = None
                
                if idx + 1 < len(df_market):
                    ret_5min = (df_market['close'].iloc[idx + 1] - spike_price) / spike_price * 100
                if idx + 2 < len(df_market):
                    ret_10min = (df_market['close'].iloc[idx + 2] - spike_price) / spike_price * 100
                if idx + 3 < len(df_market):
                    ret_15min = (df_market['close'].iloc[idx + 3] - spike_price) / spike_price * 100
                
                open_price = df_market['open'].iloc[idx]
                close_price = df_market['close'].iloc[idx]
                direction = 'UP' if close_price >= open_price else 'DOWN'
                
                spikes.append({
                    'symbol': symbol,
                    'date': spike_time_et.date(),
                    'time': spike_time_et.strftime('%H:%M'),
                    'rvol': round(vol_ratio, 2),
                    'direction': direction,
                    'ret_5min': ret_5min,
                    'ret_10min': ret_10min,
                    'ret_15min': ret_15min
                })
        
        return spikes
    except Exception as e:
        print(f"  {symbol}: ERROR - {str(e)[:50]}")
        return []

def run_study():
    # 3 months: March 1 - May 31, 2026
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('MULTI-STOCK VOLUME SPIKE STUDY - 3 MONTHS')
    print(f'Stocks: {", ".join(SYMBOLS)}')
    print(f'Period: {start_date.date()} to {end_date.date()} (3 months)')
    print(f'Window: 9:00-11:00 AM ET | Spike: 2.0x volume')
    print('='*100)
    
    all_spikes = []
    
    for sym in SYMBOLS:
        print(f'\nAnalyzing {sym}...')
        spikes = analyze_symbol(sym, start_date, end_date)
        print(f'  Found {len(spikes)} spikes')
        all_spikes.extend(spikes)
        time.sleep(0.5)
    
    if not all_spikes:
        print('\nNo spikes found across all symbols')
        return
    
    df_all = pd.DataFrame(all_spikes)
    
    print('\n' + '='*100)
    print(f'TOTAL: {len(df_all)} spikes across {len(SYMBOLS)} stocks')
    print('='*100)
    
    # Combined statistics
    for minutes, col in [('5-minute', 'ret_5min'), ('10-minute', 'ret_10min'), ('15-minute', 'ret_15min')]:
        valid_returns = df_all[col].dropna()
        
        if len(valid_returns) == 0:
            continue
        
        wins = len(valid_returns[valid_returns > 0])
        losses = len(valid_returns[valid_returns < 0])
        total = len(valid_returns)
        
        win_rate = wins / total * 100 if total > 0 else 0
        avg_return = valid_returns.mean()
        
        gross_wins = valid_returns[valid_returns > 0].sum()
        gross_losses = abs(valid_returns[valid_returns < 0].sum())
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        
        print(f'\n{minutes} Returns (All Stocks):')
        print(f'  Count: {total}')
        print(f'  Win Rate: {win_rate:.1f}% ({wins} wins, {losses} losses)')
        print(f'  Avg Return: {avg_return:+.3f}%')
        print(f'  Profit Factor: {profit_factor:.2f}')
        print(f'  Best: {valid_returns.max():+.2f}% | Worst: {valid_returns.min():+.2f}%')
    
    # Per-symbol stats - CLEAN TABLE
    print('\n' + '='*80)
    print('PER-SYMBOL SUMMARY (10-minute returns)')
    print('='*80)
    print(f"{'Symbol':10} {'Trades':8} {'Win Rate':10} {'Avg Return':12} {'PF':8}")
    print('-'*80)
    
    summary_rows = []
    for sym in SYMBOLS:
        sym_data = df_all[df_all['symbol'] == sym]['ret_10min'].dropna()
        if len(sym_data) == 0:
            continue
        
        wins = len(sym_data[sym_data > 0])
        total = len(sym_data)
        win_rate = wins / total * 100
        avg_ret = sym_data.mean()
        
        gross_wins = sym_data[sym_data > 0].sum()
        gross_losses = abs(sym_data[sym_data < 0].sum())
        pf = gross_wins / gross_losses if gross_losses > 0 else 999
        
        summary_rows.append({
            'symbol': sym,
            'trades': total,
            'win_rate': win_rate,
            'avg_ret': avg_ret,
            'pf': pf
        })
        
        print(f"{sym:10} {total:8} {win_rate:9.1f}% {avg_ret:+10.3f}% {pf:8.2f}")
    
    # TOTAL row
    all_data = df_all['ret_10min'].dropna()
    if len(all_data) > 0:
        total_wins = len(all_data[all_data > 0])
        total_trades = len(all_data)
        total_win_rate = total_wins / total_trades * 100
        total_avg_ret = all_data.mean()
        total_gross_wins = all_data[all_data > 0].sum()
        total_gross_losses = abs(all_data[all_data < 0].sum())
        total_pf = total_gross_wins / total_gross_losses if total_gross_losses > 0 else 999
        
        print('-'*80)
        print(f"{'TOTAL':10} {total_trades:8} {total_win_rate:9.1f}% {total_avg_ret:+10.3f}% {total_pf:8.2f}")
    
    print('='*80)
    
    # By direction
    print('\n' + '='*100)
    print('BY SPIKE DIRECTION (10-min returns):')
    print('='*100)
    
    for direction in ['UP', 'DOWN']:
        dir_data = df_all[df_all['direction'] == direction]['ret_10min'].dropna()
        if len(dir_data) == 0:
            continue
        
        wins = len(dir_data[dir_data > 0])
        print(f'\n{direction} spikes ({len(dir_data)}):')
        print(f'  Win Rate: {wins/len(dir_data)*100:.1f}%')
        print(f'  Avg Return: {dir_data.mean():+.3f}%')
        print(f'  Best: {dir_data.max():+.2f}% | Worst: {dir_data.min():+.2f}%')
    
    # Top 10 best spikes
    print('\n' + '='*100)
    print('TOP 10 SPIKES (10-min returns):')
    print('='*100)
    top10 = df_all.nlargest(10, 'ret_10min')
    for _, row in top10.iterrows():
        print(f"  {row['symbol']:6} {row['date']} {row['time']:5} {row['direction']:5} RVOL:{row['rvol']:.1f}x  +{row['ret_10min']:.2f}%")
    
    print('\n' + '='*100)

if __name__ == '__main__':
    run_study()
