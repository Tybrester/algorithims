"""
BOOF 28 - 6 Month Backtest (100 Stocks)
1-minute data with hybrid exit
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Top 100 stocks (liquid large caps)
UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "PEP", "COST",
    "NFLX", "AMD", "INTC", "CRM", "ADBE", "PYPL", "CSCO", "CMCSA", "TXN", "QCOM",
    "AMAT", "INTU", "HON", "AMGN", "GILD", "BKNG", "SBUX", "MDLZ", "ISRG", "VRTX",
    "PDD", "MU", "LRCX", "SNPS", "KLAC", "ADI", "MRVL", "CTAS", "MAR", "ABNB",
    "FTNT", "ADP", "PANW", "CDNS", "NXPI", "WDAY", "ORLY", "MCHP", "MRNA", "KDP",
    "CHTR", "ROST", "AZN", "CSX", "BIIB", "DXCM", "PCAR", "EXC", "IDXX", "XEL",
    "EA", "ILMN", "LCID", "WBD", "CTSH", "MDB", "TEAM", "DDOG", "ZS", "CRWD",
    "OKTA", "PLTR", "RBLX", "SNOW", "NET", "FTNT", "CFLT", "DASH", "COIN", "SQ",
    "SHOP", "TWLO", "ZM", "DOCU", "U", "APP", "RIVN", "IOT", "S", "GTLB",
    "FIVN", "FSLR", "ENPH", "RUN", "SEDG", "NOVA", "SPWR", "MAXN", "ARRY", "SHLS"
]

OPENING_MOVE_MIN = 0.0025   # +0.25%
STOP_LOSS = -0.004          # -0.40%
TRAIL_ACTIVATE = 0.01       # +1.00%
TRAIL_DISTANCE = 0.002      # 0.20%
MAX_HOLD_BARS = 60          # 60 minutes on 1m data

def ema(series, length=9):
    return series.ewm(span=length, adjust=False).mean()

def get_opening_move(df):
    """Uses 9:30 to 9:35 ET (14:30 to 14:35 UTC)"""
    if len(df) == 0:
        return None
    
    # Convert UTC to ET (subtract 5 hours)
    df_copy = df.copy()
    df_copy.index = df_copy.index - pd.Timedelta(hours=5)
    
    # Get 9:30-9:35 ET data
    opening = df_copy.between_time('09:30', '09:35')
    
    if len(opening) == 0:
        return None
    
    open_price = opening.iloc[0]["open"]
    close_price = opening.iloc[-1]["close"]
    
    return (close_price - open_price) / open_price

def run_strategy(stock_df, qqq_df, symbol):
    """Run strategy on 1-minute data"""
    
    if symbol not in UNIVERSE:
        return None
    
    stock_df = stock_df.copy()
    
    # Calculate EMA9
    stock_df["ema9"] = ema(stock_df["close"], 9)
    
    # Get opening moves
    stock_open_move = get_opening_move(stock_df)
    qqq_open_move = get_opening_move(qqq_df)
    
    if stock_open_move is None or qqq_open_move is None:
        return None
    
    # ENTRY FILTERS
    if stock_open_move <= OPENING_MOVE_MIN:
        return None
    
    if qqq_open_move <= 0:
        return None
    
    # Enter at 9:35 ET (14:35 UTC)
    df_copy = stock_df.copy()
    df_copy.index = df_copy.index - pd.Timedelta(hours=5)
    entry_data = df_copy.between_time('09:35', '09:35')
    
    if len(entry_data) == 0:
        return None
    
    entry_time_et = entry_data.index[0]
    entry_price = entry_data.iloc[0]["close"]
    
    # Convert back to UTC for indexing original df
    entry_time_utc = entry_time_et + pd.Timedelta(hours=5)
    
    # Get trade bars (max 60 minutes) - use UTC time
    trade_bars = stock_df.loc[entry_time_utc:].iloc[:MAX_HOLD_BARS]
    
    if len(trade_bars) == 0:
        return None
    
    peak_pnl = 0
    trailing_active = False
    
    for time, row in trade_bars.iterrows():
        price = row["close"]
        pnl = (price - entry_price) / entry_price
        
        peak_pnl = max(peak_pnl, pnl)
        
        # Hard stop
        if pnl <= STOP_LOSS:
            return {
                "symbol": symbol,
                "entry_time": entry_time_utc,
                "exit_time": time,
                "entry": entry_price,
                "exit": price,
                "pnl": pnl,
                "exit_type": "SL",
                "stock_move": stock_open_move,
                "qqq_move": qqq_open_move
            }
        
        # Activate trailing after +1%
        if pnl >= TRAIL_ACTIVATE:
            trailing_active = True
        
        # Trailing stop
        if trailing_active:
            trail_stop = peak_pnl - TRAIL_DISTANCE
            if pnl <= trail_stop:
                return {
                    "symbol": symbol,
                    "entry_time": entry_time_utc,
                    "exit_time": time,
                    "entry": entry_price,
                    "exit": price,
                    "pnl": pnl,
                    "exit_type": "TRAIL",
                    "stock_move": stock_open_move,
                    "qqq_move": qqq_open_move
                }
        
        # EMA exit
        if price < row["ema9"]:
            return {
                "symbol": symbol,
                "entry_time": entry_time_utc,
                "exit_time": time,
                "entry": entry_price,
                "exit": price,
                "pnl": pnl,
                "exit_type": "EMA",
                "stock_move": stock_open_move,
                "qqq_move": qqq_open_move
            }
    
    # Time exit
    last = trade_bars.iloc[-1]
    
    return {
        "symbol": symbol,
        "entry_time": entry_time_utc,
        "exit_time": trade_bars.index[-1],
        "entry": entry_price,
        "exit": last["close"],
        "pnl": (last["close"] - entry_price) / entry_price,
        "exit_type": "TIME",
        "stock_move": stock_open_move,
        "qqq_move": qqq_open_move
    }

def fetch_data(symbol, start_date, end_date):
    """Fetch 1-minute data"""
    try:
        df = fetch_alpaca_bars(symbol, start_date, end_date, '1Min',
                               creds['api_key'], creds['secret_key'])
        if df is None or len(df) == 0:
            return None
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        df = df.set_index('timestamp')
        
        # Market hours only
        df = df.between_time('09:30', '16:00')
        
        return df
    except Exception as e:
        print(f"Error fetching {symbol}: {str(e)[:50]}")
        return None

def run_study():
    # 6 months: Jan 1 - Jun 30, 2026
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 6, 30, tzinfo=timezone.utc)
    
    print('='*100)
    print('6-MONTH BACKTEST (100 STOCKS)')
    print('1-minute data with hybrid exit')
    print(f'Period: {start_date.date()} to {end_date.date()}')
    print('-'*100)
    print('Filters: Stock > +0.25%, QQQ > 0%')
    print('Exit: EMA9 | Trail (+1% act, 0.2% dist) | Stop (-0.4%) | Time (60m)')
    print('='*100)
    
    # Fetch QQQ data once
    print('\nFetching QQQ data (6 months of 1m bars)...')
    qqq_df = fetch_data('QQQ', start_date, end_date)
    if qqq_df is None:
        print('Failed to fetch QQQ data')
        return
    print(f'  QQQ: {len(qqq_df)} bars')
    
    all_trades = []
    
    print(f'\nProcessing {len(UNIVERSE)} stocks...')
    for i, sym in enumerate(UNIVERSE, 1):
        print(f'{i:3d}/{len(UNIVERSE)}: {sym}...', end=' ')
        
        stock_df = fetch_data(sym, start_date, end_date)
        if stock_df is None:
            print('SKIP (no data)')
            continue
        
        # Group by date and run strategy for each day
        stock_df['date'] = stock_df.index.date
        qqq_df['date'] = qqq_df.index.date
        
        for trade_date in stock_df['date'].unique():
            day_stock = stock_df[stock_df['date'] == trade_date]
            day_qqq = qqq_df[qqq_df['date'] == trade_date]
            
            if len(day_stock) < 60 or len(day_qqq) < 60:
                continue
            
            result = run_strategy(day_stock, day_qqq, sym)
            if result:
                result['trade_date'] = trade_date
                all_trades.append(result)
        
        print(f'{len([t for t in all_trades if t["symbol"] == sym])} trades')
        time.sleep(0.2)
    
    if not all_trades:
        print('\nNo trades found')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*100)
    print(f'TOTAL TRADES: {len(df)}')
    print('='*100)
    
    # Performance
    pnl = df['pnl'].dropna()
    if len(pnl) > 0:
        wins = len(pnl[pnl > 0])
        print(f'\nPERFORMANCE:')
        print(f'  Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)')
        print(f'  Avg P&L: {pnl.mean():+.3f}%')
        print(f'  Total P&L: {pnl.sum():+.3f}%')
        print(f'  Best: {pnl.max():+.2f}% | Worst: {pnl.min():+.2f}%')
    
    # Exit breakdown
    print('\n' + '='*100)
    print('EXIT TYPE BREAKDOWN:')
    print('='*100)
    
    for exit_type in ['SL', 'EMA', 'TRAIL', 'TIME']:
        exit_data = df[df['exit_type'] == exit_type]
        if len(exit_data) == 0:
            continue
        
        pnl_exit = exit_data['pnl']
        wins = len(pnl_exit[pnl_exit > 0])
        print(f"  {exit_type:6}: {len(exit_data):4} trades ({len(exit_data)/len(df)*100:5.1f}%) | "
              f"Win: {wins/len(pnl_exit)*100:5.1f}% | Avg: {pnl_exit.mean():+6.3f}%")
    
    # By symbol (top 20 by trade count)
    print('\n' + '='*100)
    print('BY SYMBOL (top 20 by trade count):')
    print('='*100)
    print(f"{'Symbol':8} {'Trades':8} {'Win%':8} {'Avg P&L':10} {'Total':10}")
    print('-'*80)
    
    symbol_counts = df['symbol'].value_counts().head(20)
    for sym in symbol_counts.index:
        sym_data = df[df['symbol'] == sym]
        pnl_sym = sym_data['pnl']
        wins = len(pnl_sym[pnl_sym > 0])
        print(f"{sym:8} {len(sym_data):8} {wins/len(pnl_sym)*100:7.1f}% {pnl_sym.mean():+9.3f}% {pnl_sym.sum():+9.3f}%")
    
    # By month
    df['month'] = pd.to_datetime(df['entry_time']).dt.to_period('M')
    print('\n' + '='*100)
    print('BY MONTH:')
    print('='*100)
    print(f"{'Month':10} {'Trades':8} {'Win%':8} {'Avg P&L':10} {'Total':10}")
    print('-'*80)
    
    for month in sorted(df['month'].unique()):
        month_data = df[df['month'] == month]
        pnl_m = month_data['pnl']
        wins = len(pnl_m[pnl_m > 0])
        print(f"{str(month):10} {len(month_data):8} {wins/len(pnl_m)*100:7.1f}% {pnl_m.mean():+9.3f}% {pnl_m.sum():+9.3f}%")
    
    # Top trades
    print('\n' + '='*100)
    print('TOP 10 TRADES:')
    print('='*100)
    top10 = df.nlargest(10, 'pnl')
    for _, row in top10.iterrows():
        print(f"  {row['trade_date']!s:12} {row['symbol']:8} {row['pnl']:+6.2f}% ({row['exit_type']})")
    
    # Worst trades
    print('\n' + '='*100)
    print('BOTTOM 10 TRADES:')
    print('='*100)
    bottom10 = df.nsmallest(10, 'pnl')
    for _, row in bottom10.iterrows():
        print(f"  {row['trade_date']!s:12} {row['symbol']:8} {row['pnl']:+6.2f}% ({row['exit_type']})")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
