"""
BOOF 28 - 6 Month Chunked Backtest (25 symbols, 5-minute bars)
Fetches data in 2-week chunks to avoid API limits
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# 25 symbols
UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "PEP", "COST",
    "NFLX", "AMD", "INTC", "CRM", "ADBE", "PYPL", "CSCO", "CMCSA", "TXN", "QCOM",
    "AMAT", "INTU", "HON", "AMGN", "GILD"
]

# Strategy params
OPENING_MOVE_MIN = 0.0025   # +0.25%
STOP_LOSS = -0.004          # -0.40%
TRAIL_ACTIVATE = 0.01       # +1.00%
TRAIL_DISTANCE = 0.002      # 0.20%
MAX_HOLD_BARS = 12          # 60 minutes on 5m data

def ema(series, length=9):
    return series.ewm(span=length, adjust=False).mean()

def get_opening_move(df):
    """Get 9:30-9:35 opening move"""
    opening = df.between_time("09:30", "09:34")
    if len(opening) == 0:
        return None
    return (opening.iloc[-1]["close"] - opening.iloc[0]["open"]) / opening.iloc[0]["open"]

def run_strategy(stock_df, qqq_df, symbol):
    """Run hybrid exit strategy"""
    if symbol not in UNIVERSE:
        return None
    
    stock_df = stock_df.copy()
    stock_df["ema9"] = ema(stock_df["close"], 9)
    
    stock_move = get_opening_move(stock_df)
    qqq_move = get_opening_move(qqq_df)
    
    if stock_move is None or qqq_move is None:
        return None
    
    # Filters
    if stock_move <= OPENING_MOVE_MIN or qqq_move <= 0:
        return None
    
    # Entry at 9:35
    entry_data = stock_df.between_time("09:35", "09:35")
    if len(entry_data) == 0:
        return None
    
    entry_price = entry_data.iloc[0]["close"]
    trade_bars = stock_df.loc[entry_data.index[0]:].iloc[:MAX_HOLD_BARS]
    
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
            return {"symbol": symbol, "entry": entry_price, "exit": price, 
                    "pnl": pnl, "exit_type": "SL", "stock_move": stock_move, "qqq_move": qqq_move}
        
        # Activate trailing
        if pnl >= TRAIL_ACTIVATE:
            trailing_active = True
        
        # Trailing stop
        if trailing_active and pnl <= (peak_pnl - TRAIL_DISTANCE):
            return {"symbol": symbol, "entry": entry_price, "exit": price,
                    "pnl": pnl, "exit_type": "TRAIL", "stock_move": stock_move, "qqq_move": qqq_move}
        
        # EMA exit
        if price < row["ema9"]:
            return {"symbol": symbol, "entry": entry_price, "exit": price,
                    "pnl": pnl, "exit_type": "EMA", "stock_move": stock_move, "qqq_move": qqq_move}
    
    # Time exit
    last = trade_bars.iloc[-1]
    return {"symbol": symbol, "entry": entry_price, "exit": last["close"],
            "pnl": (last["close"] - entry_price) / entry_price, "exit_type": "TIME",
            "stock_move": stock_move, "qqq_move": qqq_move}

def fetch_chunked_data(symbol, start_date, end_date):
    """Fetch data in 2-week chunks"""
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
            print(f"  Error fetching {symbol} {chunk_start.date()}: {str(e)[:50]}")
        
        chunk_start = chunk_end
        time.sleep(0.5)
    
    if all_data:
        return pd.concat(all_data).sort_index()
    return None

def run_backtest():
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 6, 30, tzinfo=timezone.utc)
    
    print('='*100)
    print('6-MONTH CHUNKED BACKTEST (25 symbols, 5-minute bars)')
    print(f'Period: {start_date.date()} to {end_date.date()}')
    print('='*100)
    
    # Fetch all data
    print('\nFetching 6 months of data in 2-week chunks...')
    all_data = {}
    
    # QQQ first
    print('  QQQ...', end=' ')
    qqq_df = fetch_chunked_data('QQQ', start_date, end_date)
    if qqq_df is None:
        print('FAILED')
        return
    print(f'{len(qqq_df)} bars, {len(qqq_df.index.date)} days')
    all_data['QQQ'] = qqq_df
    
    # Stocks
    for i, sym in enumerate(UNIVERSE, 1):
        print(f'  {sym} ({i}/25)...', end=' ')
        df = fetch_chunked_data(sym, start_date, end_date)
        if df is not None:
            all_data[sym] = df
            print(f'{len(df)} bars')
        else:
            print('FAILED')
    
    # Run strategy
    print('\n' + '='*100)
    print('RUNNING STRATEGY...')
    print('='*100)
    
    all_trades = []
    qqq_df['date'] = qqq_df.index.date
    trading_days = sorted(qqq_df['date'].unique())
    
    print(f'Total trading days: {len(trading_days)}')
    
    for trade_date in trading_days:
        day_qqq = qqq_df[qqq_df['date'] == trade_date]
        
        for sym in UNIVERSE:
            if sym not in all_data:
                continue
            
            stock_df = all_data[sym]
            day_stock = stock_df[stock_df.index.date == trade_date]
            
            if len(day_stock) < 5:
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
    
    pnl = df['pnl'].dropna()
    wins = len(pnl[pnl > 0])
    
    print(f'\nPERFORMANCE:')
    print(f'  Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)')
    print(f'  Avg P&L: {pnl.mean():+.3f}%')
    print(f'  Total P&L: {pnl.sum():+.3f}%')
    print(f'  Best: {pnl.max():+.2f}% | Worst: {pnl.min():+.2f}%')
    
    # By symbol
    print('\nBY SYMBOL (top 15):')
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
    for sym, trades, win_pct, avg, total in symbol_stats[:15]:
        print(f"{sym:8} {trades:8} {win_pct:7.1f}% {avg:+9.3f}% {total:+9.3f}%")
    
    # By month
    df['month'] = pd.to_datetime(df['trade_date']).dt.to_period('M')
    print('\nBY MONTH:')
    print(f"{'Month':10} {'Trades':8} {'Win%':8} {'Avg P&L':10} {'Total':10}")
    print('-'*70)
    
    for month in sorted(df['month'].unique()):
        month_data = df[df['month'] == month]
        pnl_m = month_data['pnl']
        wins_m = len(pnl_m[pnl_m > 0])
        print(f"{str(month):10} {len(month_data):8} {wins_m/len(pnl_m)*100:7.1f}% {pnl_m.mean():+9.3f}% {pnl_m.sum():+9.3f}%")
    
    # Exit breakdown
    print('\nEXIT BREAKDOWN:')
    for exit_type in ['SL', 'EMA', 'TRAIL', 'TIME']:
        exit_data = df[df['exit_type'] == exit_type]
        if len(exit_data) == 0:
            continue
        pnl_exit = exit_data['pnl']
        wins_exit = len(pnl_exit[pnl_exit > 0])
        print(f"{exit_type:8}: {len(exit_data):3} ({len(exit_data)/len(df)*100:5.1f}%) | Win: {wins_exit/len(pnl_exit)*100:5.1f}% | Avg: {pnl_exit.mean():+6.3f}%")
    
    # Top/bottom trades
    print('\nTOP 10 TRADES:')
    top10 = df.nlargest(10, 'pnl')
    for _, row in top10.iterrows():
        print(f"  {row['trade_date']!s:12} {row['symbol']:8} {row['stock_move']*100:+.2f}% → {row['pnl']*100:+.2f}% ({row['exit_type']})")
    
    print('\nBOTTOM 10 TRADES:')
    bottom10 = df.nsmallest(10, 'pnl')
    for _, row in bottom10.iterrows():
        print(f"  {row['trade_date']!s:12} {row['symbol']:8} {row['stock_move']*100:+.2f}% → {row['pnl']*100:+.2f}% ({row['exit_type']})")
    
    print('='*100)

if __name__ == '__main__':
    run_backtest()
