"""
BOOF 28 - Focused Strategy (4 Stocks)
Stocks: AVGO, NVDA, GOOGL, META
Filter: Opening move 0.25% - 0.75%
Entry: Trade opening direction
Exit: 30-minute hold
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

SYMBOLS = ['AVGO', 'NVDA', 'GOOGL', 'META']

def analyze_symbol(symbol, start_date, end_date):
    try:
        df = fetch_alpaca_bars(symbol, start_date, end_date, '5Min',
                               creds['api_key'], creds['secret_key'])
        
        if df is None or len(df) < 50:
            return []
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        
        # Time in ET
        df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
        df['minute'] = df['timestamp'].dt.minute
        df['time_et'] = df['hour_et'] * 100 + df['minute']
        df['date'] = df['timestamp'].dt.date
        
        trades = []
        dates = sorted(df['date'].unique())
        
        for trade_date in dates:
            day_df = df[df['date'] == trade_date].copy()
            
            # Find 9:30 AM bar
            open_bar = day_df[day_df['time_et'] == 930]
            if len(open_bar) == 0:
                continue
            
            bar = open_bar.iloc[0]
            open_price = bar['open']
            close_price = bar['close']
            bar_high = bar['high']
            bar_low = bar['low']
            
            # Calculate opening move
            opening_move = (close_price - open_price) / open_price * 100
            
            # Filter: 0.25% - 0.75%
            abs_move = abs(opening_move)
            if abs_move < 0.25 or abs_move >= 0.75:
                continue
            
            # Direction based on bar color
            if close_price > open_price:
                direction = 'LONG'
            elif close_price < open_price:
                direction = 'SHORT'
            else:
                continue
            
            entry_price = close_price
            
            # Get 30-minute exit (bar at index 6 = 10:00)
            day_market = day_df[day_df['time_et'] >= 930].reset_index(drop=True)
            if len(day_market) < 7:
                continue
            
            exit_price = day_market.iloc[6]['close']
            
            # Calculate P&L
            if direction == 'LONG':
                pnl = (exit_price - entry_price) / entry_price * 100
                mfe = (day_market.iloc[1:7]['high'].max() - entry_price) / entry_price * 100
                mae = (entry_price - day_market.iloc[1:7]['low'].min()) / entry_price * 100
            else:
                pnl = (entry_price - exit_price) / entry_price * 100
                mfe = (entry_price - day_market.iloc[1:7]['low'].min()) / entry_price * 100
                mae = (day_market.iloc[1:7]['high'].max() - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'opening_move': round(opening_move, 2),
                'direction': direction,
                'entry': round(entry_price, 2),
                'exit': round(exit_price, 2),
                'pnl': round(pnl, 2),
                'mfe': round(mfe, 2),
                'mae': round(mae, 2)
            })
        
        return trades
    except Exception as e:
        print(f"  {symbol}: {str(e)[:50]}")
        return []

def run_study():
    # 3 months: March 1 - May 31, 2026
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('FOCUSED STRATEGY: AVGO, NVDA, GOOGL, META')
    print('Filter: Opening move 0.25% - 0.75%')
    print('Entry: 9:35 | Exit: 30-min hold (10:05)')
    print(f'Period: {start_date.date()} to {end_date.date()} (3 months)')
    print('='*100)
    
    all_trades = []
    
    for sym in SYMBOLS:
        print(f'\nAnalyzing {sym}...', end=' ')
        trades = analyze_symbol(sym, start_date, end_date)
        print(f'{len(trades)} trades')
        all_trades.extend(trades)
        time.sleep(0.3)
    
    if not all_trades:
        print('\nNo trades found')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*100)
    print(f'TOTAL TRADES: {len(df)}')
    print('='*100)
    
    # Overall stats
    pnl_values = df['pnl'].dropna()
    if len(pnl_values) > 0:
        wins = len(pnl_values[pnl_values > 0])
        print(f'\nOVERALL PERFORMANCE:')
        print(f'  Win Rate: {wins}/{len(pnl_values)} ({wins/len(pnl_values)*100:.1f}%)')
        print(f'  Avg P&L: {pnl_values.mean():+.3f}%')
        print(f'  Total P&L: {pnl_values.sum():+.3f}%')
        print(f'  Best: {pnl_values.max():+.2f}% | Worst: {pnl_values.min():+.2f}%')
        
        mfe_values = df['mfe'].dropna()
        mae_values = df['mae'].dropna()
        print(f'\nMFE/MAE:')
        print(f'  Avg MFE: {mfe_values.mean():.2f}%')
        print(f'  Avg MAE: {mae_values.mean():.2f}%')
        print(f'  MFE > MAE: {len(df[df["mfe"] > df["mae"]])}/{len(df)} ({len(df[df["mfe"] > df["mae"]])/len(df)*100:.1f}%)')
    
    # By symbol
    print('\n' + '='*100)
    print('BY SYMBOL:')
    print('='*100)
    print(f"{'Symbol':10} {'Trades':8} {'Win%':10} {'Avg P&L':12} {'Total':12} {'Best':10} {'Worst':10}")
    print('-'*100)
    
    for sym in SYMBOLS:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) == 0:
            continue
        
        pnl = sym_data['pnl'].dropna()
        if len(pnl) > 0:
            wins = len(pnl[pnl > 0])
            win_pct = wins / len(pnl) * 100
            print(f"{sym:10} {len(sym_data):8} {win_pct:9.1f}% {pnl.mean():+10.3f}% {pnl.sum():+10.3f}% {pnl.max():+8.2f}% {pnl.min():+8.2f}%")
    
    # By direction
    print('\n' + '='*100)
    print('BY DIRECTION:')
    print('='*100)
    print(f"{'Direction':10} {'Count':8} {'Win%':10} {'Avg P&L':12}")
    print('-'*100)
    
    for direction in ['LONG', 'SHORT']:
        dir_data = df[df['direction'] == direction]
        if len(dir_data) == 0:
            continue
        
        pnl = dir_data['pnl'].dropna()
        if len(pnl) > 0:
            wins = len(pnl[pnl > 0])
            win_pct = wins / len(pnl) * 100
            print(f"{direction:10} {len(dir_data):8} {win_pct:9.1f}% {pnl.mean():+10.3f}%")
    
    # All trades
    print('\n' + '='*100)
    print(f'ALL {len(df)} TRADES:')
    print('='*100)
    print(f"{'Date':12} {'Symbol':8} {'Move':8} {'Dir':6} {'Entry':10} {'Exit':10} {'P&L':8} {'MFE':7} {'MAE':7}")
    print('-'*100)
    
    df_sorted = df.sort_values('date')
    for _, row in df_sorted.iterrows():
        print(f"{row['date']!s:12} {row['symbol']:8} {row['opening_move']:+7.2f}% {row['direction']:6} "
              f"{row['entry']:9.2f} {row['exit']:9.2f} {row['pnl']:+7.2f}% {row['mfe']:6.2f}% {row['mae']:6.2f}%")
    
    # Best trades
    print('\n' + '='*100)
    print('TOP 5 TRADES:')
    print('='*100)
    top5 = df.nlargest(5, 'pnl')
    for _, row in top5.iterrows():
        print(f"  {row['date']!s:12} {row['symbol']:6} {row['direction']:5} {row['pnl']:+6.2f}% (Move: {row['opening_move']:+5.2f}%)")
    
    # Worst trades
    print('\n' + '='*100)
    print('BOTTOM 5 TRADES:')
    print('='*100)
    bottom5 = df.nsmallest(5, 'pnl')
    for _, row in bottom5.iterrows():
        print(f"  {row['date']!s:12} {row['symbol']:6} {row['direction']:5} {row['pnl']:+6.2f}% (Move: {row['opening_move']:+5.2f}%)")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
