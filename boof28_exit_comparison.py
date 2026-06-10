"""
BOOF 28 - Exit Strategy Comparison
Version A: Fixed TP +0.50%, SL -0.40%
Version B: BE at +0.50%, Trail at +1.00% (0.20% trail)
Version C: Exit below 9 EMA
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
            
            # Get rest of day for exits (max 2 hours = 24 bars)
            day_market = day_df[day_df['time_et'] > 930].reset_index(drop=True)
            if len(day_market) < 3:
                continue
            
            # Recalculate EMA9 for this day's data
            day_market['ema9'] = calculate_ema(day_market['close'], 9)
            
            # ==========================================
            # VERSION A: Fixed TP +0.50%, SL -0.40%
            # ==========================================
            tp_price_a = entry_price * 1.005
            sl_price_a = entry_price * 0.996
            exit_price_a = None
            exit_type_a = ""
            
            for i in range(len(day_market)):
                bar_i = day_market.iloc[i]
                
                # Check TP hit
                if bar_i['high'] >= tp_price_a:
                    exit_price_a = tp_price_a
                    exit_type_a = "TP"
                    break
                
                # Check SL hit
                if bar_i['low'] <= sl_price_a:
                    exit_price_a = sl_price_a
                    exit_type_a = "SL"
                    break
            
            # If neither hit, use last bar close
            if exit_price_a is None:
                exit_price_a = day_market.iloc[-1]['close']
                exit_type_a = "TIME"
            
            pnl_a = (exit_price_a - entry_price) / entry_price * 100
            
            # ==========================================
            # VERSION B: BE at +0.50%, Trail at +1.00%
            # ==========================================
            be_price = entry_price
            trail_active = False
            trail_stop = entry_price
            high_water = entry_price
            exit_price_b = None
            exit_type_b = ""
            
            for i in range(len(day_market)):
                bar_i = day_market.iloc[i]
                current_high = bar_i['high']
                current_low = bar_i['low']
                
                # Update high water mark
                if current_high > high_water:
                    high_water = current_high
                    
                    # Check if we hit +1.00% to activate trailing
                    if not trail_active and high_water >= entry_price * 1.01:
                        trail_active = True
                        trail_stop = high_water * 0.998  # 0.20% trail
                    elif trail_active:
                        # Update trailing stop
                        new_stop = high_water * 0.998
                        if new_stop > trail_stop:
                            trail_stop = new_stop
                
                # Check if we hit +0.50% to move to breakeven
                if not trail_active and high_water >= entry_price * 1.005:
                    be_price = entry_price
                
                # Check exit conditions
                if trail_active and current_low <= trail_stop:
                    exit_price_b = trail_stop
                    exit_type_b = "TRAIL"
                    break
                elif not trail_active and current_low <= be_price and high_water > entry_price * 1.005:
                    # Hit breakeven stop after reaching +0.50%
                    exit_price_b = be_price
                    exit_type_b = "BE"
                    break
                elif current_low <= entry_price * 0.996:  # -0.40% initial SL
                    exit_price_b = entry_price * 0.996
                    exit_type_b = "SL"
                    break
            
            if exit_price_b is None:
                exit_price_b = day_market.iloc[-1]['close']
                exit_type_b = "TIME"
            
            pnl_b = (exit_price_b - entry_price) / entry_price * 100
            
            # ==========================================
            # VERSION C: Exit when close below 9 EMA
            # ==========================================
            exit_price_c = None
            exit_type_c = ""
            
            for i in range(len(day_market)):
                bar_i = day_market.iloc[i]
                
                # Check if close below EMA9
                if bar_i['close'] < bar_i['ema9'] and not pd.isna(bar_i['ema9']):
                    exit_price_c = bar_i['close']
                    exit_type_c = "EMA"
                    break
            
            if exit_price_c is None:
                exit_price_c = day_market.iloc[-1]['close']
                exit_type_c = "TIME"
            
            pnl_c = (exit_price_c - entry_price) / entry_price * 100
            
            # Calculate MFE/MAE for context
            mfe = (day_market['high'].max() - entry_price) / entry_price * 100
            mae = (entry_price - day_market['low'].min()) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'opening_move': round(opening_move, 2),
                'entry': round(entry_price, 2),
                'pnl_a': round(pnl_a, 2),
                'exit_a': exit_type_a,
                'pnl_b': round(pnl_b, 2),
                'exit_b': exit_type_b,
                'pnl_c': round(pnl_c, 2),
                'exit_c': exit_type_c,
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
    
    print('='*110)
    print('EXIT STRATEGY COMPARISON')
    print('Universe: NVDA, AVGO, GOOGL, META')
    print('Entry: 9:35 if 5m bar > +0.25%')
    print('-'*110)
    print('Version A: TP +0.50%, SL -0.40%')
    print('Version B: BE at +0.50%, Trail at +1.00% (0.20% trail)')
    print('Version C: Exit when close below 9 EMA')
    print('='*110)
    
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
    
    print('\n' + '='*110)
    print(f'TOTAL TRADES: {len(df)}')
    print('='*110)
    
    # Comparison table
    print('\n' + '='*110)
    print('EXIT COMPARISON:')
    print('='*110)
    print(f"{'Version':20} {'Trades':8} {'Win%':10} {'Avg P&L':12} {'Total':12} {'Best':10} {'Worst':10}")
    print('-'*110)
    
    versions = [
        ('Version A (TP/SL)', 'pnl_a'),
        ('Version B (Trail)', 'pnl_b'),
        ('Version C (EMA)', 'pnl_c')
    ]
    
    for version_name, col in versions:
        pnl = df[col].dropna()
        if len(pnl) > 0:
            wins = len(pnl[pnl > 0])
            win_pct = wins / len(pnl) * 100
            print(f"{version_name:20} {len(pnl):8} {win_pct:9.1f}% {pnl.mean():+10.3f}% {pnl.sum():+10.3f}% {pnl.max():+8.2f}% {pnl.min():+8.2f}%")
    
    # Exit type breakdown
    print('\n' + '='*110)
    print('EXIT TYPE BREAKDOWN:')
    print('='*110)
    
    for version_name, exit_col in [('Version A', 'exit_a'), ('Version B', 'exit_b'), ('Version C', 'exit_c')]:
        print(f"\n{version_name}:")
        exit_counts = df[exit_col].value_counts()
        for exit_type, count in exit_counts.items():
            pct = count / len(df) * 100
            print(f"  {exit_type:10}: {count:3} ({pct:5.1f}%)")
    
    # By symbol
    print('\n' + '='*110)
    print('BY SYMBOL:')
    print('='*110)
    print(f"{'Symbol':10} {'V-A Avg':10} {'V-B Avg':10} {'V-C Avg':10} {'Trades':8}")
    print('-'*110)
    
    for sym in SYMBOLS:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) == 0:
            continue
        
        pnl_a = sym_data['pnl_a'].mean()
        pnl_b = sym_data['pnl_b'].mean()
        pnl_c = sym_data['pnl_c'].mean()
        
        print(f"{sym:10} {pnl_a:+9.3f}% {pnl_b:+9.3f}% {pnl_c:+9.3f}% {len(sym_data):8}")
    
    # All trades
    print('\n' + '='*110)
    print(f'ALL {len(df)} TRADES:')
    print('='*110)
    print(f"{'Date':12} {'Symbol':8} {'Move':8} {'V-A':8} {'Exit':6} {'V-B':8} {'Exit':6} {'V-C':8} {'Exit':6}")
    print('-'*110)
    
    df_sorted = df.sort_values('date')
    for _, row in df_sorted.iterrows():
        print(f"{row['date']!s:12} {row['symbol']:8} {row['opening_move']:+7.2f}% "
              f"{row['pnl_a']:+7.2f}% {row['exit_a']:6} {row['pnl_b']:+7.2f}% {row['exit_b']:6} "
              f"{row['pnl_c']:+7.2f}% {row['exit_c']:6}")
    
    # Top trades for each version
    print('\n' + '='*110)
    print('TOP 5 TRADES BY VERSION:')
    print('='*110)
    
    for version_name, col in versions:
        print(f"\n{version_name}:")
        top5 = df.nlargest(5, col)
        for _, row in top5.iterrows():
            print(f"  {row['date']!s:12} {row['symbol']:6} {row[col]:+6.2f}%")
    
    print('='*110)

if __name__ == '__main__':
    run_study()
