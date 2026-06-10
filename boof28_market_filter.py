"""
BOOF 28 - Market Filter Test (SPY/QQQ)
Version A: Stock > +0.25%
Version B: Stock > +0.25% AND SPY green
Version C: Stock > +0.25% AND QQQ green
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

SYMBOLS = ['NVDA', 'AVGO', 'GOOGL', 'META']

def get_market_data(symbol, start_date, end_date):
    """Fetch SPY or QQQ opening bar data"""
    try:
        df = fetch_alpaca_bars(symbol, start_date, end_date, '5Min',
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
        
        # Get opening bar (9:30) for each date
        market_moves = {}
        for trade_date in df['date'].unique():
            day_df = df[df['date'] == trade_date]
            open_bar = day_df[day_df['time_et'] == 930]
            if len(open_bar) > 0:
                bar = open_bar.iloc[0]
                move = (bar['close'] - bar['open']) / bar['open'] * 100
                market_moves[trade_date] = move
        
        return market_moves
    except:
        return None

def analyze_symbol(symbol, start_date, end_date, spy_moves, qqq_moves):
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
            
            # Find 9:30 AM bar
            open_bar = day_df[day_df['time_et'] == 930]
            if len(open_bar) == 0:
                continue
            
            bar = open_bar.iloc[0]
            open_price = bar['open']
            close_price = bar['close']
            
            # Calculate stock opening move
            stock_move = (close_price - open_price) / open_price * 100
            
            # Get market data for this date
            spy_move = spy_moves.get(trade_date, 0) if spy_moves else 0
            qqq_move = qqq_moves.get(trade_date, 0) if qqq_moves else 0
            
            # Check which versions qualify
            version_a = stock_move > 0.25
            version_b = stock_move > 0.25 and spy_move > 0
            version_c = stock_move > 0.25 and qqq_move > 0
            
            if not version_a:
                continue
            
            entry_price = close_price
            
            # Get 30-minute exit (10:00)
            day_market = day_df[day_df['time_et'] >= 930].reset_index(drop=True)
            if len(day_market) < 7:
                continue
            
            exit_price = day_market.iloc[6]['close']
            pnl = (exit_price - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'stock_move': round(stock_move, 2),
                'spy_move': round(spy_move, 2),
                'qqq_move': round(qqq_move, 2),
                'pnl': round(pnl, 2),
                'version_a': version_a,
                'version_b': version_b,
                'version_c': version_c
            })
        
        return trades
    except Exception as e:
        print(f"  {symbol}: {str(e)[:50]}")
        return []

def run_study():
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('MARKET FILTER TEST (SPY/QQQ)')
    print('Universe: NVDA, AVGO, GOOGL, META')
    print('Exit: 30-minute hold')
    print('-'*100)
    print('Version A: Stock > +0.25%')
    print('Version B: Stock > +0.25% AND SPY green')
    print('Version C: Stock > +0.25% AND QQQ green')
    print('='*100)
    
    # Fetch market data
    print('\nFetching SPY data...')
    spy_moves = get_market_data('SPY', start_date - timedelta(days=1), end_date)
    if spy_moves:
        print(f'  SPY data: {len(spy_moves)} days')
    
    print('\nFetching QQQ data...')
    qqq_moves = get_market_data('QQQ', start_date - timedelta(days=1), end_date)
    if qqq_moves:
        print(f'  QQQ data: {len(qqq_moves)} days')
    
    all_trades = []
    
    for sym in SYMBOLS:
        print(f'\nAnalyzing {sym}...', end=' ')
        trades = analyze_symbol(sym, start_date, end_date, spy_moves, qqq_moves)
        print(f'{len(trades)} trades')
        all_trades.extend(trades)
        time.sleep(0.3)
    
    if not all_trades:
        print('\nNo trades found')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*100)
    print(f'TOTAL POTENTIAL TRADES (Version A): {len(df)}')
    print('='*100)
    
    # Version breakdown
    version_b_count = len(df[df['version_b'] == True])
    version_c_count = len(df[df['version_c'] == True])
    
    print(f'\nVERSION BREAKDOWN:')
    print(f'  Version A (Stock > +0.25%):          {len(df):3} trades')
    print(f'  Version B (+ SPY green):              {version_b_count:3} trades ({version_b_count/len(df)*100:.1f}%)')
    print(f'  Version C (+ QQQ green):              {version_c_count:3} trades ({version_c_count/len(df)*100:.1f}%)')
    
    # Performance comparison
    print('\n' + '='*100)
    print('PERFORMANCE COMPARISON (30-min hold):')
    print('='*100)
    print(f"{'Version':30} {'Trades':8} {'Win%':10} {'Avg P&L':12} {'Total':12}")
    print('-'*100)
    
    # Version A - all trades
    pnl_a = df['pnl'].dropna()
    wins_a = len(pnl_a[pnl_a > 0])
    print(f"{'Version A (Stock only)':30} {len(pnl_a):8} {wins_a/len(pnl_a)*100:9.1f}% {pnl_a.mean():+10.3f}% {pnl_a.sum():+10.3f}%")
    
    # Version B - with SPY filter
    df_b = df[df['version_b'] == True]
    if len(df_b) > 0:
        pnl_b = df_b['pnl'].dropna()
        wins_b = len(pnl_b[pnl_b > 0])
        print(f"{'Version B (Stock + SPY green)':30} {len(pnl_b):8} {wins_b/len(pnl_b)*100:9.1f}% {pnl_b.mean():+10.3f}% {pnl_b.sum():+10.3f}%")
    
    # Version C - with QQQ filter
    df_c = df[df['version_c'] == True]
    if len(df_c) > 0:
        pnl_c = df_c['pnl'].dropna()
        wins_c = len(pnl_c[pnl_c > 0])
        print(f"{'Version C (Stock + QQQ green)':30} {len(pnl_c):8} {wins_c/len(pnl_c)*100:9.1f}% {pnl_c.mean():+10.3f}% {pnl_c.sum():+10.3f}%")
    
    # Overlap analysis
    print('\n' + '='*100)
    print('FILTER OVERLAP ANALYSIS:')
    print('='*100)
    
    both_filters = len(df[(df['version_b'] == True) & (df['version_c'] == True)])
    spy_only = len(df[(df['version_b'] == True) & (df['version_c'] == False)])
    qqq_only = len(df[(df['version_b'] == False) & (df['version_c'] == True)])
    neither = len(df[(df['version_b'] == False) & (df['version_c'] == False)])
    
    print(f'  Both SPY and QQQ green:  {both_filters:3} trades')
    print(f'  Only SPY green:          {spy_only:3} trades')
    print(f'  Only QQQ green:          {qqq_only:3} trades')
    print(f'  Neither green:           {neither:3} trades')
    
    # Performance by market condition
    print('\n' + '='*100)
    print('PERFORMANCE BY MARKET CONDITION:')
    print('='*100)
    
    conditions = [
        ('Both SPY & QQQ green', df[(df['version_b'] == True) & (df['version_c'] == True)]),
        ('SPY green only', df[(df['version_b'] == True) & (df['version_c'] == False)]),
        ('QQQ green only', df[(df['version_b'] == False) & (df['version_c'] == True)]),
        ('Neither green', df[(df['version_b'] == False) & (df['version_c'] == False)])
    ]
    
    print(f"{'Condition':25} {'Count':8} {'Win%':10} {'Avg P&L':12}")
    print('-'*70)
    
    for label, data in conditions:
        if len(data) > 0:
            pnl = data['pnl'].dropna()
            wins = len(pnl[pnl > 0])
            print(f"{label:25} {len(data):8} {wins/len(pnl)*100:9.1f}% {pnl.mean():+10.3f}%")
    
    # By symbol with filters
    print('\n' + '='*100)
    print('BY SYMBOL (with QQQ filter - Version C):')
    print('='*100)
    print(f"{'Symbol':10} {'Trades':8} {'Win%':10} {'Avg P&L':12} {'Total':12}")
    print('-'*100)
    
    for sym in SYMBOLS:
        sym_data = df_c[df_c['symbol'] == sym] if len(df_c) > 0 else pd.DataFrame()
        if len(sym_data) == 0:
            continue
        
        pnl = sym_data['pnl'].dropna()
        if len(pnl) > 0:
            wins = len(pnl[pnl > 0])
            print(f"{sym:10} {len(sym_data):8} {wins/len(pnl)*100:9.1f}% {pnl.mean():+10.3f}% {pnl.sum():+10.3f}%")
    
    # All trades table
    print('\n' + '='*100)
    print('ALL TRADES (Version A baseline):')
    print('='*100)
    print(f"{'Date':12} {'Symbol':8} {'Stock':8} {'SPY':7} {'QQQ':7} {'P&L':8} {'B':4} {'C':4}")
    print('-'*100)
    
    df_sorted = df.sort_values('date')
    for _, row in df_sorted.iterrows():
        b_flag = "YES" if row['version_b'] else "NO"
        c_flag = "YES" if row['version_c'] else "NO"
        print(f"{row['date']!s:12} {row['symbol']:8} {row['stock_move']:+7.2f}% {row['spy_move']:+6.2f}% {row['qqq_move']:+6.2f}% {row['pnl']:+7.2f}% {b_flag:4} {c_flag:4}")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
