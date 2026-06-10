"""
BOOF 28 - Advanced Tests
1. Move buckets (0.25-0.50% vs 0.50-0.75%)
2. Top N ranking by opening move
3. Hybrid exit on existing trades
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import pickle
import os

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

UNIVERSE = [
    "NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU", "TSM", "ASML", "KLAC", "LRCX",
    "INTC", "MRVL", "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "NFLX",
    "ARM", "ANET", "DELL", "SMCI", "PLTR", "SNOW", "CRWD", "DDOG"
]

def load_cached(symbol, start_date, end_date, cache_dir='boof_cache'):
    cache_file = f"{cache_dir}/{symbol}_{start_date.date()}_{end_date.date()}.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def ema(series, length=9):
    return series.ewm(span=length, adjust=False).mean()

def run_tests():
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 6, 30, tzinfo=timezone.utc)
    
    print('='*100)
    print('ADVANCED TESTS: Move Buckets, Top N Ranking, Hybrid Exit')
    print('='*100)
    
    # Load data
    print('\nLoading cached data...')
    all_data = {}
    for sym in ['QQQ'] + UNIVERSE:
        df = load_cached(sym, start_date, end_date)
        if df is not None:
            all_data[sym] = df
            print(f'  {sym}: {len(df)} bars')
    
    if 'QQQ' not in all_data:
        print('ERROR: No QQQ data')
        return
    
    # Collect all candidates
    print('\n' + '='*100)
    print('COLLECTING ALL CANDIDATES (Test 1 & 2)')
    print('='*100)
    
    all_candidates = []
    
    qqq_df = all_data['QQQ']
    qqq_df['date'] = qqq_df.index.date
    trading_days = sorted(qqq_df['date'].unique())
    
    for trade_date in trading_days:
        day_qqq = qqq_df[qqq_df['date'] == trade_date]
        qqq_open = day_qqq.between_time('09:30', '09:34')
        
        if len(qqq_open) == 0:
            continue
        
        qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']
        
        if qqq_move <= 0:
            continue
        
        day_candidates = []
        
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
            
            open_price = stock_open.iloc[0]['open']
            close_price = stock_open.iloc[-1]['close']
            high_price = stock_open['high'].max()
            low_price = stock_open['low'].min()
            
            stock_move = (close_price - open_price) / open_price
            stock_range = (high_price - low_price) / open_price
            
            # Passes filters: 0.25% <= move <= 0.75% AND range < 1.5%
            if (0.0025 <= stock_move <= 0.0075) and (stock_range < 0.015):
                entry_data = day_stock.between_time('09:35', '09:35')
                exit_10 = day_stock.between_time('10:00', '10:00')
                
                if len(entry_data) > 0 and len(exit_10) > 0:
                    entry_price = entry_data.iloc[0]['close']
                    exit_10_price = exit_10.iloc[0]['close']
                    pnl_10 = (exit_10_price - entry_price) / entry_price * 100
                    
                    day_candidates.append({
                        'date': trade_date,
                        'symbol': sym,
                        'stock_move': stock_move,
                        'stock_range': stock_range,
                        'entry': entry_price,
                        'exit_10': exit_10_price,
                        'pnl_10': pnl_10,
                        'day_stock': day_stock  # Store for hybrid exit calc
                    })
        
        all_candidates.extend(day_candidates)
    
    if not all_candidates:
        print('No candidates found')
        return
    
    df_candidates = pd.DataFrame([{k: v for k, v in c.items() if k != 'day_stock'} for c in all_candidates])
    
    print(f'\nTotal candidates: {len(df_candidates)}')
    
    # TEST 1: Move Buckets
    print('\n' + '='*100)
    print('TEST 1: MOVE BUCKETS')
    print('='*100)
    
    bucket_1 = df_candidates[(df_candidates['stock_move'] >= 0.0025) & (df_candidates['stock_move'] < 0.0050)]
    bucket_2 = df_candidates[(df_candidates['stock_move'] >= 0.0050) & (df_candidates['stock_move'] <= 0.0075)]
    
    print(f"\nBucket 1 (0.25% - 0.50%): {len(bucket_1)} trades")
    if len(bucket_1) > 0:
        pnl = bucket_1['pnl_10']
        wins = len(pnl[pnl > 0])
        print(f"  Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)")
        print(f"  Avg P&L: {pnl.mean():+.2f}%")
        print(f"  Total: {pnl.sum():+.2f}%")
    
    print(f"\nBucket 2 (0.50% - 0.75%): {len(bucket_2)} trades")
    if len(bucket_2) > 0:
        pnl = bucket_2['pnl_10']
        wins = len(pnl[pnl > 0])
        print(f"  Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)")
        print(f"  Avg P&L: {pnl.mean():+.2f}%")
        print(f"  Total: {pnl.sum():+.2f}%")
    
    # TEST 2: Top N Ranking
    print('\n' + '='*100)
    print('TEST 2: TOP N RANKING BY OPENING MOVE')
    print('='*100)
    
    # Group by date and take top N
    for top_n in [5, 10, 15, 20]:
        top_trades = []
        
        for trade_date in df_candidates['date'].unique():
            day_trades = df_candidates[df_candidates['date'] == trade_date]
            if len(day_trades) == 0:
                continue
            
            # Sort by opening move and take top N
            top_day = day_trades.nlargest(min(top_n, len(day_trades)), 'stock_move')
            top_trades.extend(top_day.to_dict('records'))
        
        if top_trades:
            df_top = pd.DataFrame(top_trades)
            pnl = df_top['pnl_10']
            wins = len(pnl[pnl > 0])
            print(f"\nTop {top_n} per day: {len(df_top)} total trades")
            print(f"  Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)")
            print(f"  Avg P&L: {pnl.mean():+.2f}%")
            print(f"  Total: {pnl.sum():+.2f}%")
    
    # TEST 3: Hybrid Exit on All Candidates
    print('\n' + '='*100)
    print('TEST 3: HYBRID EXIT ON ALL CANDIDATES')
    print('='*100)
    print('Exit: SL -0.4% | EMA9 | Trail +1% act, 0.2% dist | Time 60m')
    print('='*100)
    
    hybrid_results = []
    
    for candidate in all_candidates:
        day_stock = candidate['day_stock']
        entry_price = candidate['entry']
        
        # Calculate EMA9
        day_stock = day_stock.copy()
        day_stock['ema9'] = ema(day_stock['close'], 9)
        
        # Get trade bars from entry
        entry_time = day_stock[day_stock['close'] == entry_price].index[0]
        trade_bars = day_stock.loc[entry_time:].iloc[:12]  # 60 minutes
        
        if len(trade_bars) == 0:
            continue
        
        peak_pnl = 0
        trailing_active = False
        exit_found = False
        
        for time, row in trade_bars.iterrows():
            price = row['close']
            pnl = (price - entry_price) / entry_price * 100
            peak_pnl = max(peak_pnl, pnl)
            
            # Hard stop -0.4%
            if pnl <= -0.40:
                hybrid_results.append({
                    **{k: v for k, v in candidate.items() if k != 'day_stock'},
                    'pnl_hybrid': pnl,
                    'exit_type': 'SL'
                })
                exit_found = True
                break
            
            # Activate trailing at +1%
            if pnl >= 1.0:
                trailing_active = True
            
            # Trailing stop
            if trailing_active and pnl <= (peak_pnl - 0.20):
                hybrid_results.append({
                    **{k: v for k, v in candidate.items() if k != 'day_stock'},
                    'pnl_hybrid': pnl,
                    'exit_type': 'TRAIL'
                })
                exit_found = True
                break
            
            # EMA exit
            if price < row['ema9']:
                hybrid_results.append({
                    **{k: v for k, v in candidate.items() if k != 'day_stock'},
                    'pnl_hybrid': pnl,
                    'exit_type': 'EMA'
                })
                exit_found = True
                break
        
        # Time exit
        if not exit_found:
            last = trade_bars.iloc[-1]
            pnl = (last['close'] - entry_price) / entry_price * 100
            hybrid_results.append({
                **{k: v for k, v in candidate.items() if k != 'day_stock'},
                'pnl_hybrid': pnl,
                'exit_type': 'TIME'
            })
    
    if hybrid_results:
        df_hybrid = pd.DataFrame(hybrid_results)
        pnl = df_hybrid['pnl_hybrid']
        wins = len(pnl[pnl > 0])
        
        print(f'\nHybrid Exit Results: {len(df_hybrid)} trades')
        print(f'  Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)')
        print(f'  Avg P&L: {pnl.mean():+.2f}%')
        print(f'  Total: {pnl.sum():+.2f}%')
        print(f'  Best: {pnl.max():+.2f}% | Worst: {pnl.min():+.2f}%')
        
        # Exit breakdown
        print('\n  Exit Breakdown:')
        for exit_type in ['SL', 'EMA', 'TRAIL', 'TIME']:
            exit_data = df_hybrid[df_hybrid['exit_type'] == exit_type]
            if len(exit_data) > 0:
                pnl_exit = exit_data['pnl_hybrid']
                wins_exit = len(pnl_exit[pnl_exit > 0])
                print(f"    {exit_type:6}: {len(exit_data):3} ({len(exit_data)/len(df_hybrid)*100:5.1f}%) | Win: {wins_exit/len(pnl_exit)*100:5.1f}% | Avg: {pnl_exit.mean():+6.2f}%")
    
    print('\n' + '='*100)

if __name__ == '__main__':
    run_tests()
