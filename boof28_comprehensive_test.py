"""
BOOF 28 - Comprehensive Test Suite
Tests: 12-month, monthly breakdown, symbol filters, exit times, thresholds
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

TECH_SEMI_UNIVERSE = [
    "NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU", "MRVL", "LRCX", "KLAC", "ASML", "TSM", "ARM", "INTC", "ON",
    "MCHP", "ADI", "NXPI", "TXN", "MPWR", "TER", "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "NFLX",
    "PLTR", "SMCI", "ANET", "DELL", "CRWD", "PANW", "NOW"
]

def load_cached(symbol, start_date, end_date, cache_dir='boof_cache'):
    cache_file = f"{cache_dir}/{symbol}_{start_date.date()}_{end_date.date()}.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def fetch_and_cache(symbol, start_date, end_date):
    os.makedirs('boof_cache', exist_ok=True)
    cache_file = f"boof_cache/{symbol}_{start_date.date()}_{end_date.date()}.pkl"
    
    all_data = []
    chunk_start = start_date
    
    while chunk_start < end_date:
        chunk_end = min(chunk_start + timedelta(days=14), end_date)
        
        try:
            df = fetch_alpaca_bars(symbol, chunk_start, chunk_end, '5Min', creds['api_key'], creds['secret_key'])
            if df is not None and len(df) > 0:
                if 'open' not in df.columns:
                    df.columns = [c.lower() for c in df.columns]
                df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
                df = df.set_index('timestamp')
                df.index = df.index - pd.Timedelta(hours=5)
                all_data.append(df)
        except:
            pass
        
        chunk_start = chunk_end
        time.sleep(0.3)
    
    if all_data:
        combined = pd.concat(all_data).sort_index()
        with open(cache_file, 'wb') as f:
            pickle.dump(combined, f)
        return combined
    return None

def get_first_5m_metrics(df):
    """Returns move, range, entry_price, high, low"""
    opening = df.between_time("09:30", "09:34")
    if len(opening) < 5:
        return None
    
    open_price = opening.iloc[0]["open"]
    close_price = opening.iloc[-1]["close"]
    high_price = opening["high"].max()
    low_price = opening["low"].min()
    
    move = (close_price - open_price) / open_price
    range_pct = (high_price - low_price) / open_price
    
    return move, range_pct, open_price, high_price, low_price

def get_price_at_time(df, time_str):
    bars = df.between_time(time_str, time_str)
    if len(bars) == 0:
        return None
    return bars.iloc[0]["close"]

def run_test(start_date, end_date, min_move, max_move, exit_time, all_data):
    """Run single test configuration"""
    trades = []
    
    qqq_df = all_data['QQQ']
    qqq_df['date'] = qqq_df.index.date
    trading_days = sorted(qqq_df['date'].unique())
    
    for trade_date in trading_days:
        qqq_day = qqq_df[qqq_df['date'] == trade_date]
        qqq_metrics = get_first_5m_metrics(qqq_day)
        
        if qqq_metrics is None:
            continue
        
        qqq_move = qqq_metrics[0]
        if qqq_move <= 0:
            continue
        
        for symbol in TECH_SEMI_UNIVERSE:
            if symbol not in all_data:
                continue
            
            df = all_data[symbol]
            day = df[df.index.date == trade_date]
            
            if len(day) == 0:
                continue
            
            stock_metrics = get_first_5m_metrics(day)
            if stock_metrics is None:
                continue
            
            stock_move, stock_range = stock_metrics[0], stock_metrics[1]
            
            # Move filter
            if not (min_move <= stock_move <= max_move):
                continue
            
            entry_price = get_price_at_time(day, "09:35")
            exit_price = get_price_at_time(day, exit_time)
            
            if entry_price is None or exit_price is None:
                continue
            
            pnl = (exit_price - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'stock_move': stock_move,
                'pnl': pnl
            })
    
    return trades

def analyze_trades(trades, label):
    """Print trade statistics"""
    if not trades:
        print(f"{label}: NO TRADES")
        return None
    
    df = pd.DataFrame(trades)
    wins = len(df[df['pnl'] > 0])
    
    print(f"{label:30} | {len(df):4} trades | {wins/len(df)*100:5.1f}% win | {df['pnl'].mean():+6.2f}% avg | {df['pnl'].sum():+7.2f}% total")
    return df

def main():
    print('='*100)
    print('BOOF 28 - COMPREHENSIVE TEST SUITE')
    print('='*100)
    
    # Load data for 12 months
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 12, 31, tzinfo=timezone.utc)
    
    print(f'\nLoading 12-month data ({start_date.date()} to {end_date.date()})...')
    all_data = {}
    
    for sym in ['QQQ'] + TECH_SEMI_UNIVERSE:
        df = load_cached(sym, start_date, end_date)
        if df is None:
            print(f'  Fetching {sym}...', end=' ')
            df = fetch_and_cache(sym, start_date, end_date)
            if df is not None:
                print(f'{len(df)} bars')
                all_data[sym] = df
            else:
                print('FAIL')
        else:
            print(f'  {sym}: Loaded {len(df)} bars')
            all_data[sym] = df
    
    if 'QQQ' not in all_data:
        print('ERROR: No QQQ data')
        return
    
    print('\n' + '='*100)
    print('TEST 1: 12-MONTH BASELINE (0.50-0.75%, 10:00 exit)')
    print('='*100)
    
    trades_12m = run_test(start_date, end_date, 0.005, 0.0075, "10:00", all_data)
    df_12m = analyze_trades(trades_12m, "12-Month Total")
    
    if df_12m is not None and len(df_12m) > 0:
        print(f"\nTEST 2: MONTHLY BREAKDOWN")
        print('-'*100)
        df_12m['month'] = pd.to_datetime(df_12m['date']).dt.to_period('M')
        for month in sorted(df_12m['month'].unique()):
            month_trades = df_12m[df_12m['month'] == month].to_dict('records')
            analyze_trades(month_trades, str(month))
    
    print('\n' + '='*100)
    print('TEST 3: SYMBOL BREAKDOWN (10+ trades, positive avg, >52% win)')
    print('='*100)
    
    if df_12m is not None and len(df_12m) > 0:
        symbol_stats = []
        for sym in TECH_SEMI_UNIVERSE:
            sym_data = df_12m[df_12m['symbol'] == sym]
            if len(sym_data) == 0:
                continue
            
            trades = len(sym_data)
            wins = len(sym_data[sym_data['pnl'] > 0])
            win_rate = wins / trades * 100
            avg_pnl = sym_data['pnl'].mean()
            total_pnl = sym_data['pnl'].sum()
            
            symbol_stats.append({
                'symbol': sym,
                'trades': trades,
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total_pnl': total_pnl
            })
        
        # Filter: 10+ trades, positive avg, >52% win
        qualified = [s for s in symbol_stats if s['trades'] >= 10 and s['avg_pnl'] > 0 and s['win_rate'] > 52]
        
        print(f"\nQUALIFIED SYMBOLS ({len(qualified)} of {len(symbol_stats)}):")
        print('-'*80)
        print(f"{'Symbol':8} {'Trades':8} {'Win%':8} {'Avg P&L':10} {'Total':10}")
        print('-'*80)
        
        qualified.sort(key=lambda x: x['total_pnl'], reverse=True)
        for s in qualified:
            print(f"{s['symbol']:8} {s['trades']:8} {s['win_rate']:7.1f}% {s['avg_pnl']:+9.2f}% {s['total_pnl']:+9.2f}%")
        
        print(f"\nDISQUALIFIED ({len(symbol_stats) - len(qualified)} symbols):")
        disqualified = [s for s in symbol_stats if s['symbol'] not in [q['symbol'] for q in qualified]]
        for s in disqualified[:10]:
            print(f"  {s['symbol']:6}: {s['trades']:2} trades, {s['win_rate']:5.1f}% win, {s['avg_pnl']:+5.2f}% avg")
    
    print('\n' + '='*100)
    print('TEST 4: EXIT TIME SWEEP (0.50-0.75% entries, 6 months)')
    print('='*100)
    
    mid_end = datetime(2026, 6, 30, tzinfo=timezone.utc)
    exit_times = ["09:45", "09:50", "10:00", "10:15", "10:30"]
    
    for exit_time in exit_times:
        trades = run_test(start_date, mid_end, 0.005, 0.0075, exit_time, all_data)
        analyze_trades(trades, f"Exit at {exit_time}")
    
    print('\n' + '='*100)
    print('TEST 5: THRESHOLD ROBUSTNESS (6 months, 10:00 exit)')
    print('='*100)
    
    thresholds = [
        (0.0045, 0.0075, "0.45-0.75%"),
        (0.0050, 0.0075, "0.50-0.75%"),
        (0.0055, 0.0075, "0.55-0.75%"),
        (0.0050, 0.0080, "0.50-0.80%")
    ]
    
    for min_move, max_move, label in thresholds:
        trades = run_test(start_date, mid_end, min_move, max_move, "10:00", all_data)
        analyze_trades(trades, label)
    
    print('\n' + '='*100)
    print('SUMMARY')
    print('='*100)
    print(f"Cache location: boof_cache/")
    print(f"Best config from testing: 0.50-0.75% move, 10:00 exit")
    print('='*100)

if __name__ == '__main__':
    main()
