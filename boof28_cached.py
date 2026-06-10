"""
BOOF 28 - Cached Data Version
Saves data after first fetch, reuses for strategy testing
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

UNIVERSE = ["NVDA", "GOOGL", "META", "AVGO", "AAPL", "MSFT", "AMZN", "TSLA", "NFLX", "AMD",
            "CRM", "ADBE", "INTC", "PYPL", "CSCO", "CMCSA", "QCOM", "TXN", "AMAT", "INTU",
            "HON", "AMGN", "GILD", "BKNG", "SBUX"]

def load_or_fetch(symbol, start_date, end_date, cache_dir='boof_cache'):
    """Load from cache or fetch and save"""
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = f"{cache_dir}/{symbol}_{start_date.date()}_{end_date.date()}.pkl"
    
    if os.path.exists(cache_file):
        print(f'  {symbol}: Loaded from cache', end=' ')
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    
    # Fetch in chunks
    all_data = []
    chunk_start = start_date
    
    while chunk_start < end_date:
        chunk_end = min(chunk_start + timedelta(days=14), end_date)
        
        df = fetch_alpaca_bars(symbol, chunk_start, chunk_end, '5Min', creds['api_key'], creds['secret_key'])
        if df is not None and len(df) > 0:
            if 'open' not in df.columns:
                df.columns = [c.lower() for c in df.columns]
            df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
            df = df.set_index('timestamp')
            df.index = df.index - pd.Timedelta(hours=5)  # ET
            all_data.append(df)
        
        chunk_start = chunk_end
        time.sleep(0.3)
    
    if all_data:
        combined = pd.concat(all_data).sort_index()
        with open(cache_file, 'wb') as f:
            pickle.dump(combined, f)
        return combined
    return None

def run_backtest():
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 6, 30, tzinfo=timezone.utc)
    
    print('6-MONTH BACKTEST - CACHED DATA (25 symbols)')
    print(f'Period: {start_date.date()} to {end_date.date()}\n')
    
    # Load all data
    print('Loading data (from cache or fetch)...')
    all_data = {}
    
    for sym in ['QQQ'] + UNIVERSE:
        df = load_or_fetch(sym, start_date, end_date)
        if df is not None:
            all_data[sym] = df
            print(f'{len(df)} bars')
        else:
            print('FAILED')
    
    if 'QQQ' not in all_data:
        print('ERROR: No QQQ data')
        return
    
    # Run strategy with new filters
    print('\n' + '='*80)
    print('RUNNING STRATEGY:')
    print('Filters: 0.25% <= move <= 0.75% | range < 1.5% | QQQ > 0%')
    print('Exit: 10:00 AM hold')
    print('='*80)
    
    all_trades = []
    qqq_df = all_data['QQQ']
    qqq_df['date'] = qqq_df.index.date
    trading_days = sorted(qqq_df['date'].unique())
    
    print(f'Total trading days: {len(trading_days)}')
    
    for trade_date in trading_days:
        day_qqq = qqq_df[qqq_df['date'] == trade_date]
        qqq_open = day_qqq.between_time('09:30', '09:34')
        
        if len(qqq_open) == 0:
            continue
        
        qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']
        
        if qqq_move <= 0:
            continue
        
        for sym in UNIVERSE:
            if sym not in all_data:
                continue
            
            stock_df = all_data[sym]
            day_stock = stock_df[stock_df.index.date == trade_date]
            
            if len(day_stock) == 0:
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
            
            # NEW FILTERS: 0.25% <= move <= 0.75% AND range < 1.5%
            if not (0.0025 <= stock_move <= 0.0075):
                continue
            
            if stock_range >= 0.015:
                continue
            
            # Entry/Exit
            entry_data = day_stock.between_time('09:35', '09:35')
            exit_data = day_stock.between_time('10:00', '10:00')
            
            if len(entry_data) > 0 and len(exit_data) > 0:
                entry_price = entry_data.iloc[0]['close']
                exit_price = exit_data.iloc[0]['close']
                pnl = (exit_price - entry_price) / entry_price * 100
                
                all_trades.append({
                    'date': trade_date,
                    'symbol': sym,
                    'pnl': pnl,
                    'stock_move': stock_move,
                    'stock_range': stock_range,
                    'qqq_move': qqq_move
                })
    
    # Results
    if not all_trades:
        print('\nNO TRADES FOUND')
        return
    
    df = pd.DataFrame(all_trades)
    
    print(f'\n\n{"="*80}')
    print(f'TOTAL TRADES: {len(df)}')
    print(f'Filters: 0.25-0.75% move, <1.5% range, QQQ>0%')
    print(f'{"="*80}')
    
    pnl = df['pnl']
    wins = len(pnl[pnl > 0])
    
    print(f'Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)')
    print(f'Avg P&L: {pnl.mean():+.2f}%')
    print(f'Total P&L: {pnl.sum():+.2f}%')
    print(f'Best: {pnl.max():+.2f}% | Worst: {pnl.min():+.2f}%')
    
    # By symbol
    print(f'\nBY SYMBOL (top 15 by trade count):')
    symbol_counts = df['symbol'].value_counts().head(15)
    for sym in symbol_counts.index:
        sym_data = df[df['symbol'] == sym]
        pnl_sym = sym_data['pnl']
        wins_sym = len(pnl_sym[pnl_sym > 0])
        avg_move = sym_data['stock_move'].mean() * 100
        avg_range = sym_data['stock_range'].mean() * 100
        print(f'{sym:6}: {len(sym_data):2} trades, {wins_sym/len(pnl_sym)*100:5.1f}% win, {pnl_sym.mean():+.2f}% avg, move:{avg_move:.2f}%, range:{avg_range:.2f}%')
    
    # Sample trades
    print(f'\nSample trades:')
    print(f"{'Date':12} {'Sym':6} {'Move':7} {'Range':7} {'P&L':7}")
    print('-'*50)
    for _, row in df.head(30).iterrows():
        print(f"{row['date']!s:12} {row['symbol']:6} {row['stock_move']*100:+.2f}% {row['stock_range']*100:+.2f}% {row['pnl']:+.2f}%")
    
    print(f'\nCache saved in: boof_cache/')

if __name__ == '__main__':
    run_backtest()
