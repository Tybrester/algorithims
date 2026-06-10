"""
BOOF 28 - Clean 5-Minute Implementation
Exact algorithm as specified
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

UNIVERSE = ["NVDA", "GOOGL", "META", "AVGO"]

OPENING_MOVE_MIN = 0.0025   # +0.25%
STOP_LOSS = -0.004          # -0.40%
TRAIL_ACTIVATE = 0.01       # +1.00%
TRAIL_DISTANCE = 0.002      # 0.20%
MAX_HOLD_BARS = 12          # 60 minutes on 5m data (12 bars)

def ema(series, length=9):
    return series.ewm(span=length, adjust=False).mean()

def get_opening_move(df):
    """
    Uses 9:30 to 9:35 candle.
    df must have columns: datetime, open, high, low, close, volume
    """
    opening = df.between_time("09:30", "09:35")

    if len(opening) == 0:
        return None

    open_price = opening.iloc[0]["open"]
    close_price = opening.iloc[-1]["close"]

    return (close_price - open_price) / open_price

def run_strategy(stock_df, qqq_df, symbol):
    """
    stock_df and qqq_df should be 5-minute data indexed by datetime.
    """

    if symbol not in UNIVERSE:
        return None

    stock_df = stock_df.copy()
    qqq_df = qqq_df.copy()

    stock_df["ema9"] = ema(stock_df["close"], 9)

    stock_open_move = get_opening_move(stock_df)
    qqq_open_move = get_opening_move(qqq_df)

    if stock_open_move is None or qqq_open_move is None:
        return None

    # ENTRY FILTERS
    if stock_open_move <= OPENING_MOVE_MIN:
        return None

    if qqq_open_move <= 0:
        return None

    # Enter after first 5-minute candle
    entry_time = stock_df.between_time("09:35", "09:35").index

    if len(entry_time) == 0:
        return None

    entry_time = entry_time[0]
    entry_price = stock_df.loc[entry_time, "close"]

    trade_bars = stock_df.loc[entry_time:].iloc[:MAX_HOLD_BARS]

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
                "entry_time": entry_time,
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
                    "entry_time": entry_time,
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
                "entry_time": entry_time,
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
        "entry_time": entry_time,
        "exit_time": trade_bars.index[-1],
        "entry": entry_price,
        "exit": last["close"],
        "pnl": (last["close"] - entry_price) / entry_price,
        "exit_type": "TIME",
        "stock_move": stock_open_move,
        "qqq_move": qqq_open_move
    }

def run_backtest():
    """Run backtest on all days for all symbols"""
    
    # 6 months: Jan 1 - Jun 30, 2026
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 6, 30, tzinfo=timezone.utc)
    
    print('='*100)
    print('CLEAN 5-MINUTE BACKTEST')
    print('Universe: NVDA, GOOGL, META, AVGO')
    print(f'Period: {start_date.date()} to {end_date.date()} (6 months)')
    print('-'*100)
    print('Entry: Stock > +0.25%, QQQ > 0%')
    print('Exit: SL -0.4% | Trail +1% act, 0.2% dist | EMA9 | Time 60m')
    print('='*100)
    
    # Fetch all data first
    print('\nFetching data...')
    
    all_data = {}
    
    # QQQ
    print('  QQQ...', end=' ')
    qqq_df = fetch_alpaca_bars('QQQ', start_date, end_date, '5Min',
                               creds['api_key'], creds['secret_key'])
    if qqq_df is not None:
        if 'open' not in qqq_df.columns:
            qqq_df.columns = [c.lower() for c in qqq_df.columns]
        qqq_df['timestamp'] = pd.to_datetime(qqq_df['timestamp'] if 'timestamp' in qqq_df.columns else qqq_df.index)
        qqq_df = qqq_df.set_index('timestamp')
        # Convert UTC to ET
        qqq_df.index = qqq_df.index - pd.Timedelta(hours=5)
        all_data['QQQ'] = qqq_df
        print(f'{len(qqq_df)} bars')
    else:
        print('FAILED')
        return
    
    # Stocks
    for sym in UNIVERSE:
        print(f'  {sym}...', end=' ')
        df = fetch_alpaca_bars(sym, start_date, end_date, '5Min',
                               creds['api_key'], creds['secret_key'])
        if df is not None:
            if 'open' not in df.columns:
                df.columns = [c.lower() for c in df.columns]
            df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
            df = df.set_index('timestamp')
            # Convert UTC to ET
            df.index = df.index - pd.Timedelta(hours=5)
            all_data[sym] = df
            print(f'{len(df)} bars')
        else:
            print('FAILED')
        time.sleep(0.5)
    
    # Run strategy day by day
    print('\n' + '='*100)
    print('RUNNING STRATEGY...')
    print('='*100)
    
    all_trades = []
    
    # Get all unique trading days from QQQ data
    qqq_df['date'] = qqq_df.index.date
    trading_days = sorted(qqq_df['date'].unique())
    
    print(f'\nTotal trading days: {len(trading_days)}')
    
    for trade_date in trading_days:
        day_qqq = qqq_df[qqq_df['date'] == trade_date]
        
        for sym in UNIVERSE:
            if sym not in all_data:
                continue
            
            stock_df = all_data[sym]
            day_stock = stock_df[stock_df.index.date == trade_date]
            
            if len(day_stock) == 0:
                continue
            
            result = run_strategy(day_stock, day_qqq, sym)
            
            if result:
                result['trade_date'] = trade_date
                all_trades.append(result)
    
    # Results
    if not all_trades:
        print('\nNO TRADES FOUND')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*100)
    print(f'TOTAL TRADES: {len(df)}')
    print('='*100)
    
    # Performance
    pnl = df['pnl'].dropna()
    wins = len(pnl[pnl > 0])
    
    print(f'\nPERFORMANCE:')
    print(f'  Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)')
    print(f'  Avg P&L: {pnl.mean():+.3f}%')
    print(f'  Total P&L: {pnl.sum():+.3f}%')
    print(f'  Best: {pnl.max():+.2f}% | Worst: {pnl.min():+.2f}%')
    
    # By symbol
    print('\n' + '='*100)
    print('BY SYMBOL:')
    print('='*100)
    print(f"{'Symbol':10} {'Trades':8} {'Win%':10} {'Avg P&L':12} {'Total':12}")
    print('-'*80)
    
    for sym in UNIVERSE:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) == 0:
            continue
        pnl_sym = sym_data['pnl']
        wins_sym = len(pnl_sym[pnl_sym > 0])
        print(f"{sym:10} {len(sym_data):8} {wins_sym/len(pnl_sym)*100:9.1f}% {pnl_sym.mean():+10.3f}% {pnl_sym.sum():+10.3f}%")
    
    # By month
    df['month'] = pd.to_datetime(df['entry_time']).dt.to_period('M')
    print('\n' + '='*100)
    print('BY MONTH:')
    print('='*100)
    print(f"{'Month':10} {'Trades':8} {'Win%':10} {'Avg P&L':12} {'Total':12}")
    print('-'*80)
    
    for month in sorted(df['month'].unique()):
        month_data = df[df['month'] == month]
        pnl_m = month_data['pnl']
        wins_m = len(pnl_m[pnl_m > 0])
        print(f"{str(month):10} {len(month_data):8} {wins_m/len(pnl_m)*100:9.1f}% {pnl_m.mean():+10.3f}% {pnl_m.sum():+10.3f}%")
    
    # Exit breakdown
    print('\n' + '='*100)
    print('EXIT BREAKDOWN:')
    print('='*100)
    for exit_type in ['SL', 'EMA', 'TRAIL', 'TIME']:
        exit_data = df[df['exit_type'] == exit_type]
        if len(exit_data) == 0:
            continue
        pnl_exit = exit_data['pnl']
        wins_exit = len(pnl_exit[pnl_exit > 0])
        print(f"{exit_type:8}: {len(exit_data):3} trades ({len(exit_data)/len(df)*100:5.1f}%) | Win: {wins_exit/len(pnl_exit)*100:5.1f}% | Avg: {pnl_exit.mean():+6.3f}%")
    
    # All trades
    print('\n' + '='*100)
    print('ALL TRADES:')
    print('='*100)
    df_sorted = df.sort_values('trade_date')
    for _, row in df_sorted.iterrows():
        print(f"{row['trade_date']!s:12} {row['symbol']:8} {row['stock_move']*100:+.2f}% → {row['pnl']*100:+.2f}% ({row['exit_type']})")
    
    print('='*100)

if __name__ == '__main__':
    run_backtest()
