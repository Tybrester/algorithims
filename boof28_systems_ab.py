"""
BOOF 28 - System A vs System B Comparison
System A: Current (0.25% < move < 0.75%, range < 1.5%, QQQ > 0)
System B: Monster Open (>1.0% move, break above first 5m high)
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time
import pickle
import os

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

UNIVERSE = [
    "NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU", "TSM", "ASML", "KLAC", "LRCX",
    "INTC", "MRVL", "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "NFLX",
    "ARM", "ANET", "DELL", "SMCI", "PLTR", "SNOW", "CRWD", "DDOG"
]

def load_cached(symbol, start_date, end_date, cache_dir='boof_cache'):
    """Load from cache if exists"""
    cache_file = f"{cache_dir}/{symbol}_{start_date.date()}_{end_date.date()}.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def system_a(day_stock, day_qqq):
    """System A: 0.25-0.75% range, <1.5% range, QQQ > 0"""
    stock_open = day_stock.between_time('09:30', '09:34')
    qqq_open = day_qqq.between_time('09:30', '09:34')
    
    if len(stock_open) == 0 or len(qqq_open) == 0:
        return None
    
    open_price = stock_open.iloc[0]['open']
    close_price = stock_open.iloc[-1]['close']
    high_price = stock_open['high'].max()
    low_price = stock_open['low'].min()
    
    stock_move = (close_price - open_price) / open_price
    stock_range = (high_price - low_price) / open_price
    
    qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']
    
    # Filters: 0.25% <= move <= 0.75% AND range < 1.5% AND QQQ > 0
    if not (0.0025 <= stock_move <= 0.0075):
        return None
    if stock_range >= 0.015:
        return None
    if qqq_move <= 0:
        return None
    
    # Entry at 9:35, Exit at 10:00
    entry_data = day_stock.between_time('09:35', '09:35')
    exit_data = day_stock.between_time('10:00', '10:00')
    
    if len(entry_data) == 0 or len(exit_data) == 0:
        return None
    
    entry_price = entry_data.iloc[0]['close']
    exit_price = exit_data.iloc[0]['close']
    pnl = (exit_price - entry_price) / entry_price * 100
    
    return {
        'entry': entry_price,
        'exit': exit_price,
        'pnl': pnl,
        'stock_move': stock_move,
        'stock_range': stock_range
    }

def system_b2(day_stock, day_qqq):
    """Version B2: >1.0% move, enter if low at 9:36 >= first_low (pullback holds)"""
    stock_open = day_stock.between_time('09:30', '09:34')
    
    if len(stock_open) == 0:
        return None
    
    open_price = stock_open.iloc[0]['open']
    close_price = stock_open.iloc[-1]['close']
    first_high = stock_open['high'].max()
    first_low = stock_open['low'].min()
    
    stock_move = (close_price - open_price) / open_price
    
    # Filter: move >= 1.0%
    if stock_move < 0.01:
        return None
    
    # Check 9:36 bar
    bar_936 = day_stock.between_time('09:36', '09:36')
    if len(bar_936) == 0:
        return None
    
    low_936 = bar_936.iloc[0]['low']
    close_936 = bar_936.iloc[0]['close']
    
    # Enter if low >= first_low (pullback holds above the low)
    if low_936 < first_low:
        return None
    
    entry_price = close_936
    
    # Exit at 10:00
    exit_data = day_stock.between_time('10:00', '10:00')
    if len(exit_data) == 0:
        return None
    
    exit_price = exit_data.iloc[0]['close']
    pnl = (exit_price - entry_price) / entry_price * 100
    
    return {
        'entry': entry_price,
        'exit': exit_price,
        'pnl': pnl,
        'stock_move': stock_move,
        'first_low': first_low
    }

def system_b3(day_stock, day_qqq):
    """Version B3: >1.0% move, enter if close at 9:36 >= first_mid (midpoint)"""
    stock_open = day_stock.between_time('09:30', '09:34')
    
    if len(stock_open) == 0:
        return None
    
    open_price = stock_open.iloc[0]['open']
    close_price = stock_open.iloc[-1]['close']
    first_high = stock_open['high'].max()
    first_low = stock_open['low'].min()
    first_mid = (first_high + first_low) / 2
    
    stock_move = (close_price - open_price) / open_price
    
    # Filter: move >= 1.0%
    if stock_move < 0.01:
        return None
    
    # Check 9:36 bar
    bar_936 = day_stock.between_time('09:36', '09:36')
    if len(bar_936) == 0:
        return None
    
    close_936 = bar_936.iloc[0]['close']
    
    # Enter if close >= first_mid
    if close_936 < first_mid:
        return None
    
    entry_price = close_936
    
    # Exit at 10:00
    exit_data = day_stock.between_time('10:00', '10:00')
    if len(exit_data) == 0:
        return None
    
    exit_price = exit_data.iloc[0]['close']
    pnl = (exit_price - entry_price) / entry_price * 100
    
    return {
        'entry': entry_price,
        'exit': exit_price,
        'pnl': pnl,
        'stock_move': stock_move,
        'first_mid': first_mid
    }

def run_comparison():
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 6, 30, tzinfo=timezone.utc)
    
    print('='*100)
    print('SYSTEM A vs SYSTEM B COMPARISON')
    print('='*100)
    print('\nSystem A: 0.25% <= move <= 0.75%, range < 1.5%, QQQ > 0%')
    print('System B: move > 1.0%, enter above first 5m high')
    print('='*100)
    
    # Load cached data
    print('\nLoading cached data...')
    all_data = {}
    
    for sym in ['QQQ'] + UNIVERSE:
        df = load_cached(sym, start_date, end_date)
        if df is not None:
            all_data[sym] = df
            print(f'  {sym}: {len(df)} bars')
    
    if 'QQQ' not in all_data:
        print('ERROR: No QQQ data in cache. Run boof28_cached.py first.')
        return
    
    # Run all systems
    trades_a = []
    trades_b2 = []
    trades_b3 = []
    
    qqq_df = all_data['QQQ']
    qqq_df['date'] = qqq_df.index.date
    trading_days = sorted(qqq_df['date'].unique())
    
    print(f'\nTesting {len(trading_days)} trading days...')
    
    for trade_date in trading_days:
        day_qqq = qqq_df[qqq_df['date'] == trade_date]
        
        for sym in UNIVERSE:
            if sym not in all_data:
                continue
            
            stock_df = all_data[sym]
            day_stock = stock_df[stock_df.index.date == trade_date]
            
            if len(day_stock) < 5:
                continue
            
            # Test System A
            result_a = system_a(day_stock, day_qqq)
            if result_a:
                result_a['date'] = trade_date
                result_a['symbol'] = sym
                trades_a.append(result_a)
            
            # Test System B2 (pullback to low)
            result_b2 = system_b2(day_stock, day_qqq)
            if result_b2:
                result_b2['date'] = trade_date
                result_b2['symbol'] = sym
                trades_b2.append(result_b2)
            
            # Test System B3 (midpoint)
            result_b3 = system_b3(day_stock, day_qqq)
            if result_b3:
                result_b3['date'] = trade_date
                result_b3['symbol'] = sym
                trades_b3.append(result_b3)
    
    # Results
    df_a = pd.DataFrame(trades_a)
    df_b2 = pd.DataFrame(trades_b2)
    df_b3 = pd.DataFrame(trades_b3)
    
    print('\n' + '='*100)
    print('RESULTS COMPARISON')
    print('='*100)
    
    # System A
    if len(df_a) > 0:
        pnl_a = df_a['pnl']
        wins_a = len(pnl_a[pnl_a > 0])
        print(f'\nSystem A: {len(df_a)} trades')
        print(f'  Win Rate: {wins_a}/{len(pnl_a)} ({wins_a/len(pnl_a)*100:.1f}%)')
        print(f'  Avg P&L: {pnl_a.mean():+.2f}%')
        print(f'  Total: {pnl_a.sum():+.2f}%')
        print(f'  Best: {pnl_a.max():+.2f}% | Worst: {pnl_a.min():+.2f}%')
    else:
        print('\nSystem A: No trades')
    
    # System B2
    if len(df_b2) > 0:
        pnl_b2 = df_b2['pnl']
        wins_b2 = len(pnl_b2[pnl_b2 > 0])
        print(f'\nSystem B2 (Pullback to Low): {len(df_b2)} trades')
        print(f'  Win Rate: {wins_b2}/{len(pnl_b2)} ({wins_b2/len(pnl_b2)*100:.1f}%)')
        print(f'  Avg P&L: {pnl_b2.mean():+.2f}%')
        print(f'  Total: {pnl_b2.sum():+.2f}%')
        print(f'  Best: {pnl_b2.max():+.2f}% | Worst: {pnl_b2.min():+.2f}%')
    else:
        print('\nSystem B2: No trades')
    
    # System B3
    if len(df_b3) > 0:
        pnl_b3 = df_b3['pnl']
        wins_b3 = len(pnl_b3[pnl_b3 > 0])
        print(f'\nSystem B3 (Midpoint Entry): {len(df_b3)} trades')
        print(f'  Win Rate: {wins_b3}/{len(pnl_b3)} ({wins_b3/len(pnl_b3)*100:.1f}%)')
        print(f'  Avg P&L: {pnl_b3.mean():+.2f}%')
        print(f'  Total: {pnl_b3.sum():+.2f}%')
        print(f'  Best: {pnl_b3.max():+.2f}% | Worst: {pnl_b3.min():+.2f}%')
    else:
        print('\nSystem B3: No trades')
    
    print('='*100)

if __name__ == '__main__':
    run_comparison()
