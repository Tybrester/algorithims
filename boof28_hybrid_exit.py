"""
BOOF 28 - Hybrid Exit Strategy
Stop: -0.40%
Exit: close < EMA9
Activate: P&L > 1.0% → trailing stop
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

SYMBOLS = ['NVDA', 'AVGO', 'GOOGL', 'META']

def calculate_ema(prices, period=9):
    return prices.ewm(span=period, adjust=False).mean()

def analyze_symbol(symbol, start_date, end_date):
    try:
        df = fetch_alpaca_bars(symbol, start_date, end_date, '5Min',
                               creds['api_key'], creds['secret_key'])
        
        if df is None or len(df) < 50:
            return []
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        
        # Calculate EMA9
        df['ema9'] = calculate_ema(df['close'], 9)
        
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
            
            # Calculate opening move
            opening_move = (close_price - open_price) / open_price * 100
            
            # Filter: LONG only if > +0.25%
            if opening_move <= 0.25:
                continue
            
            entry_price = close_price
            sl_price = entry_price * 0.996  # -0.40% stop
            
            # Get rest of day for exits
            day_market = day_df[day_df['time_et'] > 930].reset_index(drop=True)
            if len(day_market) < 3:
                continue
            
            # Recalculate EMA9 for this day's data
            day_market['ema9'] = calculate_ema(day_market['close'], 9)
            
            # HYBRID EXIT LOGIC
            trailing_active = False
            high_water = entry_price
            trail_stop = entry_price
            exit_price = None
            exit_type = ""
            
            for i in range(len(day_market)):
                bar_i = day_market.iloc[i]
                current_high = bar_i['high']
                current_low = bar_i['low']
                current_close = bar_i['close']
                current_ema = bar_i['ema9']
                
                # Update high water mark
                if current_high > high_water:
                    high_water = current_high
                
                # Calculate current P&L
                current_pnl = (current_high - entry_price) / entry_price * 100
                
                # Check if we hit +1.0% to activate trailing
                if not trailing_active and current_pnl > 1.0:
                    trailing_active = True
                    trail_stop = high_water * 0.998  # 0.20% trail
                
                # Update trailing stop if active
                if trailing_active:
                    new_trail = high_water * 0.998
                    if new_trail > trail_stop:
                        trail_stop = new_trail
                
                # EXIT CHECKS (in priority order)
                
                # 1. Hard stop -0.40%
                if current_low <= sl_price:
                    exit_price = sl_price
                    exit_type = "SL"
                    break
                
                # 2. Trailing stop hit (only if activated)
                if trailing_active and current_low <= trail_stop:
                    exit_price = trail_stop
                    exit_type = "TRAIL"
                    break
                
                # 3. Close below EMA9
                if current_close < current_ema and not pd.isna(current_ema):
                    exit_price = current_close
                    exit_type = "EMA"
                    break
            
            # If no exit triggered, use last bar close
            if exit_price is None:
                exit_price = day_market.iloc[-1]['close']
                exit_type = "TIME"
            
            pnl = (exit_price - entry_price) / entry_price * 100
            
            # Calculate MFE/MAE
            mfe = (day_market['high'].max() - entry_price) / entry_price * 100
            mae = (entry_price - day_market['low'].min()) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'opening_move': round(opening_move, 2),
                'entry': round(entry_price, 2),
                'exit': round(exit_price, 2),
                'pnl': round(pnl, 2),
                'exit_type': exit_type,
                'trailing_active': trailing_active,
                'mfe': round(mfe, 2),
                'mae': round(mae, 2)
            })
        
        return trades
    except Exception as e:
        print(f"  {symbol}: {str(e)[:50]}")
        return []

def run_study():
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('HYBRID EXIT STRATEGY')
    print('Universe: NVDA, AVGO, GOOGL, META')
    print('Entry: 9:35 if 5m bar > +0.25%')
    print('-'*100)
    print('Exit Rules:')
    print('  1. STOP = -0.40% (hard stop)')
    print('  2. if close < EMA9: exit')
    print('  3. if P&L > 1.0%: activate trailing stop (0.20% trail)')
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
    
    # Performance summary
    pnl = df['pnl'].dropna()
    if len(pnl) > 0:
        wins = len(pnl[pnl > 0])
        print(f'\nPERFORMANCE:')
        print(f'  Win Rate: {wins}/{len(pnl)} ({wins/len(pnl)*100:.1f}%)')
        print(f'  Avg P&L: {pnl.mean():+.3f}%')
        print(f'  Total P&L: {pnl.sum():+.3f}%')
        print(f'  Best: {pnl.max():+.2f}% | Worst: {pnl.min():+.2f}%')
    
    # Exit type breakdown
    print('\n' + '='*100)
    print('EXIT TYPE BREAKDOWN:')
    print('='*100)
    
    exit_counts = df['exit_type'].value_counts()
    for exit_type, count in exit_counts.items():
        pct = count / len(df) * 100
        avg_pnl = df[df['exit_type'] == exit_type]['pnl'].mean()
        print(f"  {exit_type:10}: {count:3} ({pct:5.1f}%) - Avg P&L: {avg_pnl:+.3f}%")
    
    # Trailing activation stats
    trail_count = len(df[df['trailing_active'] == True])
    print(f"\n  Trailing Activated: {trail_count}/{len(df)} ({trail_count/len(df)*100:.1f}%)")
    if trail_count > 0:
        trail_pnl = df[df['trailing_active'] == True]['pnl'].mean()
        print(f"  Avg P&L when trailing: {trail_pnl:+.3f}%")
    
    # By symbol
    print('\n' + '='*100)
    print('BY SYMBOL:')
    print('='*100)
    print(f"{'Symbol':10} {'Trades':8} {'Win%':10} {'Avg P&L':12} {'Total':12} {'Best':10}")
    print('-'*100)
    
    for sym in SYMBOLS:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) == 0:
            continue
        
        pnl_sym = sym_data['pnl'].dropna()
        if len(pnl_sym) > 0:
            wins = len(pnl_sym[pnl_sym > 0])
            win_pct = wins / len(pnl_sym) * 100
            print(f"{sym:10} {len(sym_data):8} {win_pct:9.1f}% {pnl_sym.mean():+10.3f}% {pnl_sym.sum():+10.3f}% {pnl_sym.max():+8.2f}%")
    
    # Risk metrics
    print('\n' + '='*100)
    print('RISK METRICS:')
    print('='*100)
    mfe = df['mfe'].dropna()
    mae = df['mae'].dropna()
    print(f'  Avg MFE: {mfe.mean():.2f}%')
    print(f'  Avg MAE: {mae.mean():.2f}%')
    print(f'  MFE/MAE Ratio: {mfe.mean()/mae.mean():.2f}')
    
    # All trades
    print('\n' + '='*100)
    print(f'ALL {len(df)} TRADES:')
    print('='*100)
    print(f"{'Date':12} {'Symbol':8} {'Move':8} {'Entry':10} {'Exit':10} {'P&L':8} {'Exit':8} {'Trail':6}")
    print('-'*100)
    
    df_sorted = df.sort_values('date')
    for _, row in df_sorted.iterrows():
        trail_flag = "YES" if row['trailing_active'] else "NO"
        print(f"{row['date']!s:12} {row['symbol']:8} {row['opening_move']:+7.2f}% {row['entry']:9.2f} "
              f"{row['exit']:9.2f} {row['pnl']:+7.2f}% {row['exit_type']:8} {trail_flag:6}")
    
    # Best/worst trades
    print('\n' + '='*100)
    print('TOP 5 TRADES:')
    print('='*100)
    top5 = df.nlargest(5, 'pnl')
    for _, row in top5.iterrows():
        print(f"  {row['date']!s:12} {row['symbol']:6} {row['pnl']:+6.2f}% ({row['exit_type']})")
    
    print('\n' + '='*100)
    print('BOTTOM 5 TRADES:')
    print('='*100)
    bottom5 = df.nsmallest(5, 'pnl')
    for _, row in bottom5.iterrows():
        print(f"  {row['date']!s:12} {row['symbol']:6} {row['pnl']:+6.2f}% ({row['exit_type']})")
    
    # Comparison with previous versions
    print('\n' + '='*100)
    print('COMPARISON WITH PREVIOUS VERSIONS:')
    print('='*100)
    print(f"{'Version':25} {'Win%':10} {'Avg P&L':12} {'Total':12}")
    print('-'*100)
    print(f"{'Version A (TP/SL)':25} {'55.6%':10} {'+0.089%':12} {'+1.60%':12}")
    print(f"{'Version B (Trail)':25} {'50.0%':10} {'+0.139%':12} {'+2.50%':12}")
    print(f"{'Version C (EMA)':25} {'61.1%':10} {'+0.167%':12} {'+3.01%':12}")
    
    hybrid_pnl = df['pnl'].dropna()
    hybrid_wins = len(hybrid_pnl[hybrid_pnl > 0])
    print(f"{'HYBRID (This Test)':25} {hybrid_wins/len(hybrid_pnl)*100:9.1f}% {hybrid_pnl.mean():+11.3f}% {hybrid_pnl.sum():+11.3f}%")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
