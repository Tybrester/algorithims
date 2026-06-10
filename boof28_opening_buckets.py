"""
BOOF 28 - Opening Move Bucket Analysis
Group by opening move magnitude and analyze performance
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

SYMBOLS = ['AAPL', 'NVDA', 'AMZN', 'META', 'AVGO', 'GOOGL', 'TSLA']

def get_bucket(move_pct):
    """Bucket the opening move percentage"""
    abs_move = abs(move_pct)
    if abs_move < 0.25:
        return "0.00-0.25%"
    elif abs_move < 0.50:
        return "0.25-0.50%"
    elif abs_move < 0.75:
        return "0.50-0.75%"
    else:
        return "0.75%+"

def analyze_symbol(symbol, start_date, end_date):
    try:
        df = fetch_alpaca_bars(symbol, start_date, end_date, '5Min', 
                               creds['api_key'], creds['secret_key'])
        
        if df is None or len(df) < 50:
            return []
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        
        df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
        df['minute'] = df['timestamp'].dt.minute
        df['time_et'] = df['hour_et'] * 100 + df['minute']
        df['date'] = df['timestamp'].dt.date
        
        trades = []
        dates = sorted(df['date'].unique())
        
        for trade_date in dates:
            day_df = df[df['date'] == trade_date].copy()
            
            open_bar = day_df[day_df['time_et'] == 930]
            if len(open_bar) == 0:
                continue
            
            bar = open_bar.iloc[0]
            open_price = bar['open']
            close_price = bar['close']
            bar_high = bar['high']
            bar_low = bar['low']
            
            # Calculate opening move
            opening_move = (close_price - open_price) / open_price * 100  # as percentage
            
            # Direction
            if opening_move > 0:
                direction = 'LONG'
                entry_price = close_price
            elif opening_move < 0:
                direction = 'SHORT'
                entry_price = close_price
            else:
                continue
            
            # Get bucket
            bucket = get_bucket(opening_move)
            
            # Need bars for 30min hold
            day_market = day_df[day_df['time_et'] >= 930].reset_index(drop=True)
            if len(day_market) < 7:
                continue
            
            # Returns at 20min and 30min
            ret_20m = None
            ret_30m = None
            
            if len(day_market) > 4:
                price_20m = day_market.iloc[4]['close']
                ret_20m = (price_20m - entry_price) / entry_price * 100
            
            if len(day_market) > 6:
                price_30m = day_market.iloc[6]['close']
                ret_30m = (price_30m - entry_price) / entry_price * 100
            
            # MFE/MAE
            window = day_market.iloc[1:7]
            max_high = window['high'].max()
            min_low = window['low'].min()
            
            if direction == 'LONG':
                mfe = (max_high - entry_price) / entry_price * 100
                mae = (entry_price - min_low) / entry_price * 100
            else:
                mfe = (entry_price - min_low) / entry_price * 100
                mae = (max_high - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'direction': direction,
                'opening_move': round(opening_move, 2),
                'bucket': bucket,
                'ret_20m': ret_20m,
                'ret_30m': ret_30m,
                'mfe': round(mfe, 2),
                'mae': round(mae, 2)
            })
        
        return trades
    except Exception as e:
        print(f"  {symbol}: {str(e)[:50]}")
        return []

def run_study():
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('OPENING MOVE BUCKET ANALYSIS')
    print('Buckets: 0.00-0.25% | 0.25-0.50% | 0.50-0.75% | 0.75%+')
    print(f'Stocks: {", ".join(SYMBOLS)}')
    print(f'Period: {start_date.date()} to {end_date.date()} (3 months)')
    print('='*100)
    
    all_trades = []
    
    for sym in SYMBOLS:
        print(f'\nAnalyzing {sym}...', end=' ')
        trades = analyze_symbol(sym, start_date, end_date)
        print(f'{len(trades)} days')
        all_trades.extend(trades)
        time.sleep(0.3)
    
    if not all_trades:
        print('\nNo data found')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*100)
    print(f'TOTAL TRADES: {len(df)}')
    print('='*100)
    
    # Overall bucket stats
    buckets = ["0.00-0.25%", "0.25-0.50%", "0.50-0.75%", "0.75%+"]
    
    print('\n' + '='*100)
    print('30-MINUTE RETURNS BY OPENING MOVE BUCKET:')
    print('='*100)
    print(f"{'Bucket':15} {'Count':8} {'30min Avg':12} {'Win%':10} {'MFE':10} {'MAE':10}")
    print('-'*100)
    
    for bucket in buckets:
        bucket_data = df[df['bucket'] == bucket]
        if len(bucket_data) == 0:
            print(f"{bucket:15} {'0':>8}")
            continue
        
        ret_30 = bucket_data['ret_30m'].dropna()
        mfe = bucket_data['mfe'].dropna()
        mae = bucket_data['mae'].dropna()
        
        if len(ret_30) > 0:
            wins = len(ret_30[ret_30 > 0])
            win_pct = wins / len(ret_30) * 100
            print(f"{bucket:15} {len(bucket_data):8} {ret_30.mean():+10.3f}% {win_pct:9.1f}% {mfe.mean():9.2f}% {mae.mean():9.2f}%")
    
    # By direction within buckets
    print('\n' + '='*100)
    print('BY BUCKET AND DIRECTION (30min returns):')
    print('='*100)
    
    for bucket in buckets:
        bucket_data = df[df['bucket'] == bucket]
        if len(bucket_data) == 0:
            continue
        
        print(f"\n{bucket} ({len(bucket_data)} trades):")
        print(f"{'Dir':8} {'Count':8} {'30min Avg':12} {'Win%':10}")
        print('-'*50)
        
        for direction in ['LONG', 'SHORT']:
            dir_data = bucket_data[bucket_data['direction'] == direction]
            if len(dir_data) == 0:
                continue
            
            ret_30 = dir_data['ret_30m'].dropna()
            if len(ret_30) > 0:
                wins = len(ret_30[ret_30 > 0])
                win_pct = wins / len(ret_30) * 100
                print(f"{direction:8} {len(dir_data):8} {ret_30.mean():+10.3f}% {win_pct:9.1f}%")
    
    # Best bucket summary
    print('\n' + '='*100)
    print('BUCKET RANKING (by 30-min avg return):')
    print('='*100)
    
    bucket_stats = []
    for bucket in buckets:
        bucket_data = df[df['bucket'] == bucket]
        if len(bucket_data) == 0:
            continue
        ret_30 = bucket_data['ret_30m'].dropna()
        if len(ret_30) > 0:
            bucket_stats.append({
                'bucket': bucket,
                'count': len(bucket_data),
                'avg_ret': ret_30.mean(),
                'win_rate': len(ret_30[ret_30 > 0]) / len(ret_30) * 100
            })
    
    bucket_stats.sort(key=lambda x: x['avg_ret'], reverse=True)
    
    for i, stat in enumerate(bucket_stats, 1):
        print(f"{i}. {stat['bucket']:15} - {stat['avg_ret']:+.3f}% avg, {stat['win_rate']:.1f}% win ({stat['count']} trades)")
    
    # Top trades by bucket
    print('\n' + '='*100)
    print('TOP 5 TRADES IN EACH BUCKET:')
    print('='*100)
    
    for bucket in buckets:
        bucket_data = df[df['bucket'] == bucket]
        if len(bucket_data) == 0:
            continue
        
        print(f"\n{bucket}:")
        print(f"{'Date':12} {'Sym':6} {'Dir':5} {'Move':8} {'30min':8}")
        print('-'*50)
        
        top5 = bucket_data.nlargest(5, 'ret_30m')
        for _, row in top5.iterrows():
            print(f"{row['date']!s:12} {row['symbol']:6} {row['direction']:5} {row['opening_move']:+6.2f}% {row['ret_30m']:+7.2f}%")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
