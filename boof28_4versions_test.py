"""
BOOF 28 - 4 Version Test (1 Year)
A: QQQ > 0
B: No QQQ filter  
C: QQQ > 0.10%
D: QQQ above daily 20 EMA
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
from datetime import datetime
import pickle
import os
import numpy as np

SYMBOLS = [
    "NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU", "MRVL", "LRCX", "KLAC", "ASML", "TSM", "ARM", "INTC", "ON",
    "MCHP", "ADI", "NXPI", "TXN", "MPWR", "TER", "SMCI", "ANET", "DELL", "HPE", "STM",
    "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "NFLX",
    "CRM", "ADBE", "INTU", "NOW", "SHOP", "ORCL", "IBM", "CSCO",
    "PLTR", "SNOW", "DDOG", "MDB", "NET", "CRWD", "PANW", "ZS", "ESTC", "S",
    "AI", "PATH", "DOCN", "FSLY", "AKAM",
    "PYPL", "SQ", "HOOD", "COIN", "ADP", "FIS", "FI", "GPN", "JKHY",
    "UBER", "ABNB", "DASH", "RBLX", "APP",
    "TTD", "DUOL", "CELH", "CAVA", "RKLB",
    "LLY", "NVO", "ABBV", "JNJ", "MRK", "AMGN", "GILD", "REGN", "VRTX", "ISRG",
    "BIIB", "BMY", "PFE", "MRNA", "NBIX",
    "GE", "CAT", "ETN", "PH", "TT", "DE", "HON", "EMR", "ROP", "URI"
]

# Strategy config
MIN_MOVE = 0.0050   # 0.50%
MAX_MOVE = 0.0080   # 0.80%
ENTRY_TIME = "09:35"
EXIT_TIME = "10:15"

def ema(series, length=20):
    return series.ewm(span=length, adjust=False).mean()

def load_cached(symbol):
    cache_file = f"boof_cache/{symbol}_2025-01-01_2026-12-31.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def get_first_5m_metrics(df):
    opening = df.between_time("09:30", "09:34")
    if len(opening) < 5:
        return None
    open_price = opening.iloc[0]["open"]
    close_price = opening.iloc[-1]["close"]
    return (close_price - open_price) / open_price

def get_price_at_time(df, time_str):
    bars = df.between_time(time_str, time_str)
    if len(bars) == 0:
        return None
    return bars.iloc[0]["close"]

def run_version(version_name, qqq_filter_type, start_date, end_date, all_data):
    """
    qqq_filter_type:
        'A': QQQ > 0
        'B': No filter
        'C': QQQ > 0.10%
        'D': QQQ above daily 20 EMA
    """
    print(f"\n{'='*100}")
    print(f"VERSION {version_name}: {qqq_filter_type}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"{'='*100}")
    
    if 'QQQ' not in all_data:
        print("ERROR: No QQQ data")
        return None
    
    trades = []
    
    # Filter by date range
    qqq_df = all_data['QQQ'].copy()
    qqq_df = qqq_df[(qqq_df.index >= start_date) & (qqq_df.index <= end_date)]
    qqq_df['date'] = qqq_df.index.date
    dates = sorted(qqq_df['date'].unique())
    
    # Calculate daily 20 EMA for Version D
    daily_qqq = qqq_df.resample('D')['close'].last().dropna()
    daily_ema20 = ema(daily_qqq, 20)
    
    for trade_date in dates:
        qqq_day = qqq_df[qqq_df['date'] == trade_date]
        qqq_open = qqq_day.between_time('09:30', '09:34')
        
        if len(qqq_open) == 0:
            continue
        
        qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']
        
        # Apply QQQ filter based on version
        if qqq_filter_type == 'A':  # QQQ > 0
            if qqq_move <= 0:
                continue
        elif qqq_filter_type == 'C':  # QQQ > 0.10%
            if qqq_move <= 0.001:
                continue
        elif qqq_filter_type == 'D':  # QQQ above daily 20 EMA
            qqq_price = qqq_open.iloc[-1]['close']
            ema20_today = daily_ema20.get(pd.Timestamp(trade_date))
            if ema20_today is None or qqq_price <= ema20_today:
                continue
        # Version B: No filter, continue always
        
        for sym in SYMBOLS:
            if sym not in all_data:
                continue
            
            df = all_data[sym].copy()
            df = df[(df.index >= start_date) & (df.index <= end_date)]
            day = df[df.index.date == trade_date]
            
            if len(day) == 0:
                continue
            
            stock_move = get_first_5m_metrics(day)
            if stock_move is None:
                continue
            
            if not (MIN_MOVE <= stock_move <= MAX_MOVE):
                continue
            
            entry_price = get_price_at_time(day, ENTRY_TIME)
            exit_price = get_price_at_time(day, EXIT_TIME)
            
            if entry_price is None or exit_price is None:
                continue
            
            pnl = (exit_price - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': sym,
                'pnl': pnl,
                'stock_move': stock_move,
                'qqq_move': qqq_move
            })
    
    if not trades:
        print(f"Version {version_name}: NO TRADES")
        return None
    
    df = pd.DataFrame(trades)
    
    # Metrics
    wins = len(df[df['pnl'] > 0])
    win_rate = wins / len(df) * 100
    avg_pnl = df['pnl'].mean()
    total_pnl = df['pnl'].sum()
    
    # Profit Factor
    gross_profit = df[df['pnl'] > 0]['pnl'].sum()
    gross_loss = abs(df[df['pnl'] <= 0]['pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Max Drawdown
    df_sorted = df.sort_values('date')
    df_sorted['cum_pnl'] = df_sorted['pnl'].cumsum()
    running_max = df_sorted['cum_pnl'].expanding().max()
    drawdown = df_sorted['cum_pnl'] - running_max
    max_drawdown = drawdown.min()
    
    print(f"\nRESULTS:")
    print(f"Trades: {len(df)}")
    print(f"Win Rate: {wins}/{len(df)} ({win_rate:.1f}%)")
    print(f"Avg P&L: {avg_pnl:+.2f}%")
    print(f"Total P&L: {total_pnl:+.2f}%")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Max Drawdown: {max_drawdown:.2f}%")
    
    # Monthly breakdown
    print(f"\nMonthly Returns:")
    print(f"{'Month':10} {'Trades':8} {'Win%':8} {'Total':10}")
    print("-" * 50)
    
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    for month in sorted(df['month'].unique()):
        month_df = df[df['month'] == month]
        m_wins = len(month_df[month_df['pnl'] > 0])
        m_wr = m_wins / len(month_df) * 100
        m_total = month_df['pnl'].sum()
        print(f"{str(month):10} {len(month_df):8} {m_wr:7.1f}% {m_total:+9.2f}%")
    
    return df

def main():
    print('='*100)
    print('BOOF 28 - 4 VERSION TEST (1 YEAR)')
    print('='*100)
    
    # Load data
    print("\nLoading cached data...")
    all_data = {}
    for sym in ['QQQ'] + SYMBOLS:
        df = load_cached(sym)
        if df is not None:
            all_data[sym] = df
    
    print(f"Loaded {len(all_data)} symbols")
    
    # Date range: 2025 full year
    start_date = pd.to_datetime('2025-01-01').tz_localize('UTC')
    end_date = pd.to_datetime('2025-12-31').tz_localize('UTC')
    
    # Run all 4 versions
    results = {}
    
    results['A'] = run_version('A', 'A', start_date, end_date, all_data)  # QQQ > 0
    results['B'] = run_version('B', 'B', start_date, end_date, all_data)  # No filter
    results['C'] = run_version('C', 'C', start_date, end_date, all_data)  # QQQ > 0.10%
    results['D'] = run_version('D', 'D', start_date, end_date, all_data)  # QQQ above 20 EMA
    
    # Summary comparison
    print('\n' + '='*100)
    print('SUMMARY COMPARISON')
    print('='*100)
    print(f"{'Version':10} {'Filter':25} {'Trades':8} {'Win%':8} {'Total':10} {'PF':6} {'MaxDD':8}")
    print('-'*100)
    
    filter_desc = {
        'A': 'QQQ > 0%',
        'B': 'No QQQ filter',
        'C': 'QQQ > 0.10%',
        'D': 'QQQ > 20 EMA'
    }
    
    for ver in ['A', 'B', 'C', 'D']:
        df = results.get(ver)
        if df is not None and len(df) > 0:
            wins = len(df[df['pnl'] > 0])
            wr = wins / len(df) * 100
            total = df['pnl'].sum()
            
            gross_profit = df[df['pnl'] > 0]['pnl'].sum()
            gross_loss = abs(df[df['pnl'] <= 0]['pnl'].sum())
            pf = gross_profit / gross_loss if gross_loss > 0 else 0
            
            df_sorted = df.sort_values('date')
            df_sorted['cum_pnl'] = df_sorted['pnl'].cumsum()
            running_max = df_sorted['cum_pnl'].expanding().max()
            drawdown = df_sorted['cum_pnl'] - running_max
            max_dd = drawdown.min()
            
            print(f"{ver:10} {filter_desc[ver]:25} {len(df):8} {wr:7.1f}% {total:+9.2f}% {pf:6.2f} {max_dd:8.2f}%")
        else:
            print(f"{ver:10} {filter_desc[ver]:25} {'NO TRADES':8}")
    
    print('='*100)

if __name__ == '__main__':
    main()
