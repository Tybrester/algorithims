"""
BOOF 28 - Quick 6-Month Test (simplified)
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

UNIVERSE = ["NVDA", "GOOGL", "META", "AVGO", "AAPL", "MSFT", "AMZN", "TSLA", "NFLX", "AMD",
            "CRM", "ADBE", "INTC", "PYPL", "CSCO", "CMCSA", "QCOM", "TXN", "AMAT", "INTU",
            "HON", "AMGN", "GILD", "BKNG", "SBUX"]

def run_backtest():
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 6, 30, tzinfo=timezone.utc)
    
    print('6-MONTH BACKTEST (25 symbols)')
    print('Fetching in 2-week chunks...\n')
    
    all_trades = []
    
    # Process each 2-week chunk
    chunk_start = start_date
    chunk_num = 1
    
    while chunk_start < end_date:
        chunk_end = min(chunk_start + timedelta(days=14), end_date)
        
        print(f'\n--- Chunk {chunk_num}: {chunk_start.date()} to {chunk_end.date()} ---')
        
        # Fetch QQQ
        qqq_df = fetch_alpaca_bars('QQQ', chunk_start, chunk_end, '5Min', creds['api_key'], creds['secret_key'])
        if qqq_df is None or len(qqq_df) == 0:
            chunk_start = chunk_end
            chunk_num += 1
            continue
        
        if 'open' not in qqq_df.columns:
            qqq_df.columns = [c.lower() for c in qqq_df.columns]
        qqq_df['timestamp'] = pd.to_datetime(qqq_df['timestamp'] if 'timestamp' in qqq_df.columns else qqq_df.index)
        qqq_df = qqq_df.set_index('timestamp')
        qqq_df.index = qqq_df.index - pd.Timedelta(hours=5)
        
        # Process each stock
        for sym in UNIVERSE:
            stock_df = fetch_alpaca_bars(sym, chunk_start, chunk_end, '5Min', creds['api_key'], creds['secret_key'])
            if stock_df is None or len(stock_df) == 0:
                continue
            
            if 'open' not in stock_df.columns:
                stock_df.columns = [c.lower() for c in stock_df.columns]
            stock_df['timestamp'] = pd.to_datetime(stock_df['timestamp'] if 'timestamp' in stock_df.columns else stock_df.index)
            stock_df = stock_df.set_index('timestamp')
            stock_df.index = stock_df.index - pd.Timedelta(hours=5)
            
            # Simple strategy: stock > +0.25%, QQQ > 0%, exit at 10:00
            stock_df['date'] = stock_df.index.date
            qqq_df['date'] = qqq_df.index.date
            
            for trade_date in set(stock_df['date']) & set(qqq_df['date']):
                day_stock = stock_df[stock_df['date'] == trade_date]
                day_qqq = qqq_df[qqq_df['date'] == trade_date]
                
                # Opening bars 9:30-9:35
                stock_open = day_stock.between_time('09:30', '09:34')
                qqq_open = day_qqq.between_time('09:30', '09:34')
                
                if len(stock_open) == 0 or len(qqq_open) == 0:
                    continue
                
                stock_open_price = stock_open.iloc[0]['open']
                stock_close_price = stock_open.iloc[-1]['close']
                stock_high_price = stock_open['high'].max()
                stock_low_price = stock_open['low'].min()
                
                stock_move = (stock_close_price - stock_open_price) / stock_open_price
                stock_range = (stock_high_price - stock_low_price) / stock_open_price
                
                qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']
                
                # Filters: 0.25% <= move <= 0.75% AND range < 1.5% AND QQQ > 0
                if (0.0025 <= stock_move <= 0.0075) and (stock_range < 0.015) and (qqq_move > 0):
                    # Entry at 9:35
                    entry_data = day_stock.between_time('09:35', '09:35')
                    exit_data = day_stock.between_time('10:00', '10:00')
                    
                    if len(entry_data) > 0 and len(exit_data) > 0:
                        entry_price = entry_data.iloc[0]['close']
                        exit_price = exit_data.iloc[0]['close']
                        pnl = (exit_price - entry_price) / entry_price * 100  # Convert to percentage
                        
                        all_trades.append({
                            'date': trade_date,
                            'symbol': sym,
                            'pnl': pnl,
                            'stock_move': stock_move,
                            'stock_range': stock_range,
                            'qqq_move': qqq_move
                        })
            
            time.sleep(0.3)
        
        chunk_start = chunk_end
        chunk_num += 1
        time.sleep(1)
    
    # Results
    if not all_trades:
        print('\nNo trades found')
        return
    
    df = pd.DataFrame(all_trades)
    
    print(f'\n\n{"="*80}')
    print(f'TOTAL TRADES: {len(df)}')
    print(f'{"="*80}')
    
    pnl = df['pnl']
    wins = len(pnl[pnl > 0])
    
    print(f'Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)')
    print(f'Avg P&L: {pnl.mean():+.2f}%')
    print(f'Total P&L: {pnl.sum():+.2f}%')
    print(f'Best: {pnl.max():+.2f}% | Worst: {pnl.min():+.2f}%')
    
    # By symbol
    print(f'\nBY SYMBOL:')
    for sym in UNIVERSE:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) > 0:
            pnl_sym = sym_data['pnl']
            wins_sym = len(pnl_sym[pnl_sym > 0])
            print(f'{sym:6}: {len(sym_data):2} trades, {wins_sym/len(pnl_sym)*100:5.1f}% win, {pnl_sym.mean():+.2f}% avg')
    
    # Sample trades
    print(f'\nSample trades:')
    print(f"{'Date':12} {'Sym':6} {'Move':7} {'Range':7} {'P&L':7}")
    print('-'*50)
    for _, row in df.head(20).iterrows():
        print(f"{row['date']!s:12} {row['symbol']:6} {row['stock_move']*100:+.2f}% {row['stock_range']*100:+.2f}% {row['pnl']:+.2f}%")

if __name__ == '__main__':
    run_backtest()
