"""
BOOF 28 - QQQ Bucket Analysis
Break QQQ opening move into buckets and analyze performance
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

SYMBOLS = ['NVDA', 'AVGO', 'GOOGL', 'META']

def get_qqq_moves(start_date, end_date):
    """Fetch QQQ opening moves"""
    try:
        df = fetch_alpaca_bars('QQQ', start_date, end_date, '5Min',
                               creds['api_key'], creds['secret_key'])
        if df is None or len(df) == 0:
            return None
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        
        df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
        df['minute'] = df['timestamp'].dt.minute
        df['time_et'] = df['hour_et'] * 100 + df['minute']
        df['date'] = df['timestamp'].dt.date
        
        qqq_moves = {}
        for trade_date in df['date'].unique():
            day_df = df[df['date'] == trade_date]
            open_bar = day_df[day_df['time_et'] == 930]
            if len(open_bar) > 0:
                bar = open_bar.iloc[0]
                move = (bar['close'] - bar['open']) / bar['open'] * 100
                qqq_moves[trade_date] = move
        
        return qqq_moves
    except:
        return None

def get_qqq_bucket(qqq_move):
    """Assign QQQ move to bucket"""
    if qqq_move < 0:
        return "QQQ < 0%"
    elif qqq_move < 0.10:
        return "QQQ 0-0.10%"
    elif qqq_move < 0.25:
        return "QQQ 0.10-0.25%"
    elif qqq_move < 0.50:
        return "QQQ 0.25-0.50%"
    else:
        return "QQQ > 0.50%"

def analyze_symbol(symbol, start_date, end_date, qqq_moves):
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
            
            stock_move = (close_price - open_price) / open_price * 100
            
            # Only stock > +0.25%
            if stock_move <= 0.25:
                continue
            
            entry_price = close_price
            
            # Get QQQ move for this date
            qqq_move = qqq_moves.get(trade_date, 0) if qqq_moves else 0
            qqq_bucket = get_qqq_bucket(qqq_move)
            
            # Get 30-minute exit
            day_market = day_df[day_df['time_et'] >= 930].reset_index(drop=True)
            if len(day_market) < 7:
                continue
            
            exit_price = day_market.iloc[6]['close']
            pnl = (exit_price - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'stock_move': round(stock_move, 2),
                'qqq_move': round(qqq_move, 2),
                'qqq_bucket': qqq_bucket,
                'pnl': round(pnl, 2)
            })
        
        return trades
    except Exception as e:
        print(f"  {symbol}: {str(e)[:50]}")
        return []

def run_study():
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('QQQ BUCKET ANALYSIS')
    print('Universe: NVDA, AVGO, GOOGL, META')
    print('Entry: Stock > +0.25%, Exit: 30-min hold')
    print('='*100)
    
    print('\nFetching QQQ data...')
    qqq_moves = get_qqq_moves(start_date - timedelta(days=1), end_date)
    if qqq_moves:
        print(f'  QQQ data: {len(qqq_moves)} days')
    
    all_trades = []
    
    for sym in SYMBOLS:
        print(f'\nAnalyzing {sym}...', end=' ')
        trades = analyze_symbol(sym, start_date, end_date, qqq_moves)
        print(f'{len(trades)} trades')
        all_trades.extend(trades)
        time.sleep(0.3)
    
    if not all_trades:
        print('\nNo trades found')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*100)
    print(f'TOTAL TRADES: {len(df)}')
    print('='*100)
    
    # Bucket analysis
    buckets = ["QQQ < 0%", "QQQ 0-0.10%", "QQQ 0.10-0.25%", "QQQ 0.25-0.50%", "QQQ > 0.50%"]
    
    print('\n' + '='*100)
    print('PERFORMANCE BY QQQ BUCKET:')
    print('='*100)
    print(f"{'Bucket':20} {'Trades':8} {'Win%':10} {'Avg P&L':12} {'Total':12} {'Best':10}")
    print('-'*100)
    
    bucket_stats = []
    for bucket in buckets:
        bucket_data = df[df['qqq_bucket'] == bucket]
        if len(bucket_data) == 0:
            print(f"{bucket:20} {'0':>8}")
            bucket_stats.append({'bucket': bucket, 'count': 0, 'avg_pnl': 0, 'win_rate': 0})
            continue
        
        pnl = bucket_data['pnl'].dropna()
        if len(pnl) > 0:
            wins = len(pnl[pnl > 0])
            win_rate = wins / len(pnl) * 100
            avg_pnl = pnl.mean()
            total = pnl.sum()
            
            print(f"{bucket:20} {len(bucket_data):8} {win_rate:9.1f}% {avg_pnl:+10.3f}% {total:+10.3f}% {pnl.max():+8.2f}%")
            
            bucket_stats.append({
                'bucket': bucket,
                'count': len(bucket_data),
                'avg_pnl': avg_pnl,
                'win_rate': win_rate,
                'total': total
            })
    
    # Rank by avg P&L
    print('\n' + '='*100)
    print('BUCKET RANKING (by Avg P&L):')
    print('='*100)
    
    valid_stats = [s for s in bucket_stats if s['count'] > 0]
    valid_stats.sort(key=lambda x: x['avg_pnl'], reverse=True)
    
    for i, stat in enumerate(valid_stats, 1):
        print(f"{i}. {stat['bucket']:20} - {stat['avg_pnl']:+.3f}% avg, {stat['win_rate']:.1f}% win ({stat['count']} trades)")
    
    # By symbol within best bucket
    if len(valid_stats) > 0:
        best_bucket = valid_stats[0]['bucket']
        best_data = df[df['qqq_bucket'] == best_bucket]
        
        print(f"\nBY SYMBOL IN BEST BUCKET ({best_bucket}):")
        print('='*100)
        print(f"{'Symbol':10} {'Trades':8} {'Win%':10} {'Avg P&L':12}")
        print('-'*100)
        
        for sym in SYMBOLS:
            sym_data = best_data[best_data['symbol'] == sym]
            if len(sym_data) == 0:
                continue
            
            pnl = sym_data['pnl'].dropna()
            if len(pnl) > 0:
                wins = len(pnl[pnl > 0])
                win_rate = wins / len(pnl) * 100
                print(f"{sym:10} {len(sym_data):8} {win_rate:9.1f}% {pnl.mean():+10.3f}%")
    
    # All trades sorted by QQQ bucket
    print('\n' + '='*100)
    print('ALL TRADES (by QQQ bucket):')
    print('='*100)
    print(f"{'Date':12} {'Symbol':8} {'Stock':8} {'QQQ':8} {'Bucket':20} {'P&L':8}")
    print('-'*100)
    
    df_sorted = df.sort_values(['qqq_bucket', 'date'])
    for _, row in df_sorted.iterrows():
        print(f"{row['date']!s:12} {row['symbol']:8} {row['stock_move']:+7.2f}% {row['qqq_move']:+7.2f}% {row['qqq_bucket']:20} {row['pnl']:+7.2f}%")
    
    # Distribution
    print('\n' + '='*100)
    print('QQQ MOVE DISTRIBUTION:')
    print('='*100)
    
    qqq_values = df['qqq_move'].dropna()
    print(f"  Min QQQ move:   {qqq_values.min():+.2f}%")
    print(f"  Max QQQ move:   {qqq_values.max():+.2f}%")
    print(f"  Avg QQQ move:   {qqq_values.mean():+.2f}%")
    print(f"  Median QQQ:     {qqq_values.median():+.2f}%")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
