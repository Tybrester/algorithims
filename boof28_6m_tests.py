"""
BOOF 28 - 6-Month Comprehensive Tests (Using Cached Data)
Tests: Monthly breakdown, symbol filters, exit times, thresholds
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
from datetime import datetime, timezone
import pickle
import os

TECH_SEMI_UNIVERSE = [
    "NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU", "MRVL", "LRCX", "KLAC", "ASML", "TSM", "ARM", "INTC", "ON",
    "MCHP", "ADI", "NXPI", "TXN", "MPWR", "TER", "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "NFLX",
    "PLTR", "SMCI", "ANET", "DELL", "CRWD", "PANW", "NOW"
]

def load_cached(symbol, cache_dir='boof_cache'):
    """Load any cached file for symbol"""
    # Look for any cache file matching this symbol
    if not os.path.exists(cache_dir):
        return None
    
    for fname in os.listdir(cache_dir):
        if fname.startswith(f"{symbol}_"):
            with open(f"{cache_dir}/{fname}", 'rb') as f:
                return pickle.load(f)
    return None

def main():
    print('='*100)
    print('BOOF 28 - 6-MONTH TESTS (Using Cached Data)')
    print('='*100)
    
    # Load cached data
    print('\nLoading cached 6-month data...')
    all_data = {}
    
    for sym in ['QQQ'] + TECH_SEMI_UNIVERSE:
        df = load_cached(sym)
        if df is not None:
            all_data[sym] = df
            print(f'  {sym}: {len(df)} bars')
    
    if 'QQQ' not in all_data:
        print('ERROR: No QQQ data in cache. Run boof28_cached.py first.')
        return
    
    qqq_df = all_data['QQQ']
    print(f'\nData range: {qqq_df.index[0]} to {qqq_df.index[-1]}')
    
    # Run tests
    print('\n' + '='*100)
    print('TEST 1: BASELINE (0.50-0.75%, 10:00 exit)')
    print('='*100)
    
    # Simple test runner
    def run_test(min_move, max_move, exit_time):
        trades = []
        
        qqq_df['date'] = qqq_df.index.date
        dates = sorted(qqq_df['date'].unique())
        
        for date in dates:
            qqq_day = qqq_df[qqq_df['date'] == date]
            qqq_open = qqq_day.between_time('09:30', '09:34')
            
            if len(qqq_open) == 0:
                continue
            
            qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']
            if qqq_move <= 0:
                continue
            
            for sym in TECH_SEMI_UNIVERSE:
                if sym not in all_data:
                    continue
                
                df = all_data[sym]
                day = df[df.index.date == date]
                
                if len(day) == 0:
                    continue
                
                stock_open = day.between_time('09:30', '09:34')
                if len(stock_open) == 0:
                    continue
                
                open_p = stock_open.iloc[0]['open']
                close_p = stock_open.iloc[-1]['close']
                stock_move = (close_p - open_p) / open_p
                
                if not (min_move <= stock_move <= max_move):
                    continue
                
                entry = day.between_time('09:35', '09:35')
                exit_bars = day.between_time(exit_time, exit_time)
                
                if len(entry) == 0 or len(exit_bars) == 0:
                    continue
                
                entry_price = entry.iloc[0]['close']
                exit_price = exit_bars.iloc[0]['close']
                pnl = (exit_price - entry_price) / entry_price * 100
                
                trades.append({'date': date, 'symbol': sym, 'pnl': pnl, 'stock_move': stock_move})
        
        return trades
    
    def analyze(trades, label):
        if not trades:
            print(f"{label}: NO TRADES")
            return None
        
        df = pd.DataFrame(trades)
        wins = len(df[df['pnl'] > 0])
        
        print(f"{label:25} | {len(df):4} trades | {wins/len(df)*100:5.1f}% win | {df['pnl'].mean():+6.2f}% avg | {df['pnl'].sum():+7.2f}% total")
        return df
    
    # Test 1: Baseline
    trades_baseline = run_test(0.005, 0.0075, "10:00")
    df_baseline = analyze(trades_baseline, "Baseline 0.50-0.75%")
    
    # Test 2: Monthly breakdown
    if df_baseline is not None and len(df_baseline) > 0:
        print('\n' + '='*100)
        print('TEST 2: MONTHLY BREAKDOWN')
        print('='*100)
        
        df_baseline['month'] = pd.to_datetime(df_baseline['date']).dt.to_period('M')
        for month in sorted(df_baseline['month'].unique()):
            month_df = df_baseline[df_baseline['month'] == month]
            wins = len(month_df[month_df['pnl'] > 0])
            print(f"{str(month):10} | {len(month_df):4} trades | {wins/len(month_df)*100:5.1f}% win | {month_df['pnl'].mean():+6.2f}% avg | {month_df['pnl'].sum():+7.2f}% total")
    
    # Test 3: Symbol breakdown
    if df_baseline is not None and len(df_baseline) > 0:
        print('\n' + '='*100)
        print('TEST 3: SYMBOL FILTERS (10+ trades, positive avg, >52% win)')
        print('='*100)
        
        print(f"\n{'Symbol':8} {'Trades':8} {'Win%':8} {'Avg P&L':10} {'Total':10}")
        print('-'*60)
        
        qualified = []
        for sym in TECH_SEMI_UNIVERSE:
            sym_df = df_baseline[df_baseline['symbol'] == sym]
            if len(sym_df) == 0:
                continue
            
            trades = len(sym_df)
            wins = len(sym_df[sym_df['pnl'] > 0])
            win_rate = wins / trades * 100
            avg_pnl = sym_df['pnl'].mean()
            total = sym_df['pnl'].sum()
            
            status = "✓" if (trades >= 10 and avg_pnl > 0 and win_rate > 52) else "✗"
            print(f"{status} {sym:6} {trades:8} {win_rate:7.1f}% {avg_pnl:+9.2f}% {total:+9.2f}%")
            
            if trades >= 10 and avg_pnl > 0 and win_rate > 52:
                qualified.append(sym)
        
        print(f"\nQUALIFIED SYMBOLS ({len(qualified)}): {', '.join(qualified)}")
    
    # Test 4: Exit time sweep
    print('\n' + '='*100)
    print('TEST 4: EXIT TIME SWEEP')
    print('='*100)
    
    for exit_time in ["09:45", "09:50", "10:00", "10:15", "10:30"]:
        trades = run_test(0.005, 0.0075, exit_time)
        analyze(trades, f"Exit {exit_time}")
    
    # Test 5: Threshold robustness
    print('\n' + '='*100)
    print('TEST 5: THRESHOLD ROBUSTNESS')
    print('='*100)
    
    thresholds = [
        (0.0045, 0.0075, "0.45-0.75%"),
        (0.0050, 0.0075, "0.50-0.75%"),
        (0.0055, 0.0075, "0.55-0.75%"),
        (0.0050, 0.0080, "0.50-0.80%")
    ]
    
    for min_m, max_m, label in thresholds:
        trades = run_test(min_m, max_m, "10:00")
        analyze(trades, label)
    
    print('\n' + '='*100)
    print('COMPLETE')
    print('='*100)

if __name__ == '__main__':
    main()
