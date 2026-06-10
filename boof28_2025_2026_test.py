"""
BOOF 28 - 2025 Full Year + 2026 YTD Test
Exact config: QQQ>0, 0.50-0.80% move, 9:35 entry, 10:15 exit
Metrics: Trades, Win Rate, Profit Factor, Max Drawdown, Monthly Returns
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
from datetime import datetime
import pickle
import os

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

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

def load_cached(symbol):
    """Load 2-year data from cache"""
    # Look for 2-year file (2025-01-01 to 2026-12-31)
    cache_file = f"boof_cache/{symbol}_2025-01-01_2026-12-31.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def run_period(label, start_date, end_date, all_data):
    """Run strategy for a specific period"""
    print(f"\n{'='*100}")
    print(f"{label}: {start_date} to {end_date}")
    print(f"Config: QQQ>0, {MIN_MOVE*100:.2f}%-{MAX_MOVE*100:.2f}% move, {ENTRY_TIME} entry, {EXIT_TIME} exit")
    print(f"{'='*100}")
    
    if 'QQQ' not in all_data:
        print("ERROR: No QQQ data")
        return None
    
    trades = []
    
    # Convert date strings to datetime for filtering (UTC to match cached data)
    start_dt = pd.to_datetime(start_date).tz_localize('UTC')
    end_dt = pd.to_datetime(end_date).tz_localize('UTC') + pd.Timedelta(days=1)  # Include full end date
    
    # Filter QQQ data by date range
    qqq_df = all_data['QQQ'].copy()
    qqq_df = qqq_df[(qqq_df.index >= start_dt) & (qqq_df.index <= end_dt)]
    qqq_df['date'] = qqq_df.index.date
    dates = sorted(qqq_df['date'].unique())
    
    for trade_date in dates:
        qqq_day = qqq_df[qqq_df['date'] == trade_date]
        qqq_open = qqq_day.between_time('09:30', '09:34')
        
        if len(qqq_open) == 0:
            continue
        
        qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']
        if qqq_move <= 0:
            continue
        
        for sym in SYMBOLS:
            if sym not in all_data:
                continue
            
            # Filter stock data by date range and get specific day
            df = all_data[sym].copy()
            df = df[(df.index >= start_dt) & (df.index <= end_dt)]
            day = df[df.index.date == trade_date]
            
            if len(day) == 0:
                continue
            
            stock_open = day.between_time('09:30', '09:34')
            if len(stock_open) == 0:
                continue
            
            open_p = stock_open.iloc[0]['open']
            close_p = stock_open.iloc[-1]['close']
            stock_move = (close_p - open_p) / open_p
            
            if not (MIN_MOVE <= stock_move <= MAX_MOVE):
                continue
            
            entry = day.between_time(ENTRY_TIME, ENTRY_TIME)
            exit_bars = day.between_time(EXIT_TIME, EXIT_TIME)
            
            if len(entry) == 0 or len(exit_bars) == 0:
                continue
            
            entry_price = entry.iloc[0]['close']
            exit_price = exit_bars.iloc[0]['close']
            pnl = (exit_price - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': sym,
                'pnl': pnl,
                'entry': entry_price,
                'exit': exit_price
            })
    
    if not trades:
        print("No trades found")
        return None
    
    df = pd.DataFrame(trades)
    df['date'] = pd.to_datetime(df['date'])
    
    # Basic metrics
    wins = len(df[df['pnl'] > 0])
    losses = len(df[df['pnl'] <= 0])
    win_rate = wins / len(df) * 100
    avg_pnl = df['pnl'].mean()
    total_pnl = df['pnl'].sum()
    
    # Profit Factor
    gross_profit = df[df['pnl'] > 0]['pnl'].sum()
    gross_loss = abs(df[df['pnl'] <= 0]['pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Max Drawdown (simplified - cumulative P&L)
    df_sorted = df.sort_values('date')
    df_sorted['cum_pnl'] = df_sorted['pnl'].cumsum()
    running_max = df_sorted['cum_pnl'].expanding().max()
    drawdown = df_sorted['cum_pnl'] - running_max
    max_drawdown = drawdown.min()
    
    # Print summary
    print(f"\n{'='*100}")
    print(f"RESULTS: {label}")
    print(f"{'='*100}")
    print(f"Trades: {len(df)}")
    print(f"Win Rate: {wins}/{len(df)} ({win_rate:.1f}%)")
    print(f"Avg P&L: {avg_pnl:+.2f}%")
    print(f"Total P&L: {total_pnl:+.2f}%")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Max Drawdown: {max_drawdown:.2f}%")
    print(f"Best: {df['pnl'].max():+.2f}% | Worst: {df['pnl'].min():+.2f}%")
    
    # Monthly breakdown
    print(f"\n{'='*100}")
    print(f"MONTHLY RETURNS")
    print(f"{'='*100}")
    print(f"{'Month':10} {'Trades':8} {'Win%':8} {'Avg P&L':10} {'Total':10} {'Cum P&L':10}")
    print('-'*100)
    
    df['month'] = df['date'].dt.to_period('M')
    cum_pnl = 0
    
    for month in sorted(df['month'].unique()):
        month_df = df[df['month'] == month]
        month_wins = len(month_df[month_df['pnl'] > 0])
        month_win_rate = month_wins / len(month_df) * 100
        month_avg = month_df['pnl'].mean()
        month_total = month_df['pnl'].sum()
        cum_pnl += month_total
        
        print(f"{str(month):10} {len(month_df):8} {month_win_rate:7.1f}% {month_avg:+9.2f}% {month_total:+9.2f}% {cum_pnl:+10.2f}%")
    
    print(f"{'='*100}")
    
    return df

def main():
    print('='*100)
    print('BOOF 28 - 2025 FULL YEAR + 2026 YTD TEST')
    print('='*100)
    
    # Load all cached data
    print("\nLoading cached data...")
    all_data = {}
    
    for sym in ['QQQ'] + SYMBOLS:
        df = load_cached(sym)
        if df is not None:
            all_data[sym] = df
            print(f"  {sym}: Loaded")
    
    print(f"\nLoaded {len(all_data)} symbols")
    
    # Test 2025 full year
    df_2025 = run_period("2025 FULL YEAR", "2025-01-01", "2025-12-31", all_data)
    
    # Test 2026 YTD (Jan-Jun)
    df_2026 = run_period("2026 YTD (Jan-Jun)", "2026-01-01", "2026-06-30", all_data)
    
    print(f"\n{'='*100}")
    print("TEST COMPLETE")
    print(f"{'='*100}")

if __name__ == '__main__':
    main()
