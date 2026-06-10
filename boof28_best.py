"""
BOOF 28 - FINAL OPTIMAL STRATEGY
Best Version: 0.50-0.75% move bucket, 10am hold, semi/tech universe
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import pickle
import os
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# 27 Semiconductor/Tech stocks - the edge is here
UNIVERSE = [
    "NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU", "TSM", "ASML", "KLAC", "LRCX",
    "INTC", "MRVL", "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "NFLX",
    "ARM", "ANET", "DELL", "SMCI", "PLTR", "SNOW", "CRWD", "DDOG"
]

# Strategy Parameters
OPENING_MOVE_MIN = 0.0050  # 0.50%
OPENING_MOVE_MAX = 0.0075  # 0.75%
OPENING_RANGE_MAX = 0.015  # 1.50%

def load_cached(symbol, start_date, end_date, cache_dir='boof_cache'):
    """Load from cache if exists, return None otherwise"""
    cache_file = f"{cache_dir}/{symbol}_{start_date.date()}_{end_date.date()}.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def fetch_and_cache(symbol, start_date, end_date, cache_dir='boof_cache'):
    """Fetch in 2-week chunks and cache"""
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = f"{cache_dir}/{symbol}_{start_date.date()}_{end_date.date()}.pkl"
    
    all_data = []
    chunk_start = start_date
    
    while chunk_start < end_date:
        chunk_end = min(chunk_start + timedelta(days=14), end_date)
        
        try:
            df = fetch_alpaca_bars(symbol, chunk_start, chunk_end, '5Min',
                                   creds['api_key'], creds['secret_key'])
            if df is not None and len(df) > 0:
                if 'open' not in df.columns:
                    df.columns = [c.lower() for c in df.columns]
                df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
                df = df.set_index('timestamp')
                df.index = df.index - pd.Timedelta(hours=5)  # Convert to ET
                all_data.append(df)
        except Exception as e:
            print(f"  Error: {str(e)[:50]}")
        
        chunk_start = chunk_end
        time.sleep(0.3)
    
    if all_data:
        combined = pd.concat(all_data).sort_index()
        with open(cache_file, 'wb') as f:
            pickle.dump(combined, f)
        return combined
    return None

def run_strategy():
    """Run Boof 28 optimal strategy"""
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 6, 30, tzinfo=timezone.utc)
    
    print('='*100)
    print('BOOF 28 - FINAL OPTIMAL STRATEGY')
    print('='*100)
    print(f'Universe: {len(UNIVERSE)} Semi/Tech stocks')
    print(f'Filters: {OPENING_MOVE_MIN*100:.2f}% <= move <= {OPENING_MOVE_MAX*100:.2f}% | range < {OPENING_RANGE_MAX*100:.1f}% | QQQ > 0%')
    print(f'Entry: 9:35 ET | Exit: 10:00 ET (60 min hold)')
    print('='*100)
    
    # Load data (fetch if not cached)
    print('\nLoading data...')
    all_data = {}
    
    for sym in ['QQQ'] + UNIVERSE:
        df = load_cached(sym, start_date, end_date)
        if df is None:
            print(f'  Fetching {sym}...', end=' ')
            df = fetch_and_cache(sym, start_date, end_date)
            if df is None:
                print('FAILED')
                continue
            print(f'{len(df)} bars')
        else:
            print(f'  {sym}: Loaded {len(df)} bars')
        all_data[sym] = df
    
    if 'QQQ' not in all_data:
        print('ERROR: No QQQ data')
        return
    
    # Run strategy
    all_trades = []
    
    qqq_df = all_data['QQQ']
    qqq_df['date'] = qqq_df.index.date
    trading_days = sorted(qqq_df['date'].unique())
    
    print(f'\nTesting {len(trading_days)} trading days...')
    
    for trade_date in trading_days:
        day_qqq = qqq_df[qqq_df['date'] == trade_date]
        qqq_open = day_qqq.between_time('09:30', '09:34')
        
        if len(qqq_open) == 0:
            continue
        
        qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']
        
        # Market filter: QQQ > 0%
        if qqq_move <= 0:
            continue
        
        for sym in UNIVERSE:
            if sym not in all_data:
                continue
            
            stock_df = all_data[sym]
            day_stock = stock_df[stock_df.index.date == trade_date]
            
            if len(day_stock) < 5:
                continue
            
            stock_open = day_stock.between_time('09:30', '09:34')
            
            if len(stock_open) == 0:
                continue
            
            # Calculate metrics
            open_price = stock_open.iloc[0]['open']
            close_price = stock_open.iloc[-1]['close']
            high_price = stock_open['high'].max()
            low_price = stock_open['low'].min()
            
            stock_move = (close_price - open_price) / open_price
            stock_range = (high_price - low_price) / open_price
            
            # THE EDGE: 0.50-0.75% moves (not 0.25-0.50%)
            if not (OPENING_MOVE_MIN <= stock_move <= OPENING_MOVE_MAX):
                continue
            
            # Range filter
            if stock_range >= OPENING_RANGE_MAX:
                continue
            
            # Entry at 9:35, Exit at 10:00
            entry_data = day_stock.between_time('09:35', '09:35')
            exit_data = day_stock.between_time('10:00', '10:00')
            
            if len(entry_data) == 0 or len(exit_data) == 0:
                continue
            
            entry_price = entry_data.iloc[0]['close']
            exit_price = exit_data.iloc[0]['close']
            pnl = (exit_price - entry_price) / entry_price * 100
            
            all_trades.append({
                'date': trade_date,
                'symbol': sym,
                'stock_move': stock_move,
                'stock_range': stock_range,
                'qqq_move': qqq_move,
                'entry': entry_price,
                'exit': exit_price,
                'pnl': pnl
            })
    
    # Results
    if not all_trades:
        print('\nNO TRADES')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*100)
    print(f'RESULTS: {len(df)} trades')
    print('='*100)
    
    pnl = df['pnl']
    wins = len(pnl[pnl > 0])
    
    print(f'Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)')
    print(f'Avg P&L: {pnl.mean():+.2f}%')
    print(f'Total P&L: {pnl.sum():+.2f}%')
    print(f'Best: {pnl.max():+.2f}% | Worst: {pnl.min():+.2f}%')
    print(f'Avg Move: {df["stock_move"].mean()*100:.2f}%')
    print(f'Avg Range: {df["stock_range"].mean()*100:.2f}%')
    
    # By symbol
    print('\n' + '='*100)
    print('BY SYMBOL:')
    print('='*100)
    print(f"{'Symbol':8} {'Trades':8} {'Win%':8} {'Avg P&L':10} {'Total':10}")
    print('-'*70)
    
    symbol_stats = []
    for sym in UNIVERSE:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) == 0:
            continue
        pnl_sym = sym_data['pnl']
        wins_sym = len(pnl_sym[pnl_sym > 0])
        symbol_stats.append((sym, len(sym_data), wins_sym/len(pnl_sym)*100, pnl_sym.mean(), pnl_sym.sum()))
    
    symbol_stats.sort(key=lambda x: x[4], reverse=True)
    for sym, trades, win_pct, avg, total in symbol_stats:
        print(f"{sym:8} {trades:8} {win_pct:7.1f}% {avg:+9.2f}% {total:+9.2f}%")
    
    # By month
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    print('\n' + '='*100)
    print('BY MONTH:')
    print('='*100)
    print(f"{'Month':10} {'Trades':8} {'Win%':8} {'Avg P&L':10} {'Total':10}")
    print('-'*70)
    
    for month in sorted(df['month'].unique()):
        month_data = df[df['month'] == month]
        pnl_m = month_data['pnl']
        wins_m = len(pnl_m[pnl_m > 0])
        print(f"{str(month):10} {len(month_data):8} {wins_m/len(pnl_m)*100:7.1f}% {pnl_m.mean():+9.2f}% {pnl_m.sum():+9.2f}%")
    
    # All trades
    print('\n' + '='*100)
    print('ALL TRADES:')
    print('='*100)
    print(f"{'Date':12} {'Sym':8} {'Move':7} {'Range':7} {'P&L':7}")
    print('-'*50)
    for _, row in df.iterrows():
        print(f"{row['date']!s:12} {row['symbol']:8} {row['stock_move']*100:+.2f}% {row['stock_range']*100:+.2f}% {row['pnl']:+.2f}%")
    
    print('='*100)

if __name__ == '__main__':
    run_strategy()
