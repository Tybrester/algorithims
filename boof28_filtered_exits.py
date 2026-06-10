"""
BOOF 28 - Filtered Strategy with Multiple Exit Methods
Opening 5m candle filter + 20min hold / 30min hold / EMA trail
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

SYMBOLS = ['AAPL', 'NVDA', 'AMZN', 'META', 'AVGO', 'GOOGL', 'TSLA']

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
            bar_high = bar['high']
            bar_low = bar['low']
            
            # Calculate move percentage
            move_pct = abs(close_price - open_price) / open_price * 100
            opening_bar_red = close_price < open_price
            
            # Apply filters
            direction = None
            filter_reason = ""
            
            if 0.25 <= move_pct < 0.75:
                # Trade direction of bar
                if close_price > open_price:
                    direction = 'LONG'
                else:
                    direction = 'SHORT'
                filter_reason = f"0.25-0.75% move"
            elif move_pct >= 0.75:
                if opening_bar_red:
                    direction = 'SHORT'
                    filter_reason = f"0.75%+ red bar"
                else:
                    # Skip big green bars
                    continue
            else:
                # Move < 0.25%, skip
                continue
            
            entry_price = close_price
            
            # Get rest of day for exits
            day_market = day_df[day_df['time_et'] >= 930].reset_index(drop=True)
            if len(day_market) < 8:  # Need enough bars
                continue
            
            # Entry is at index 0 (close of 9:30 bar)
            # We need to recalc EMA9 for this day's data
            day_market['ema9'] = calculate_ema(day_market['close'], 9)
            
            # EXIT 1: 20 minute hold (bar at index 4 = 9:50)
            exit_20m_price = None
            exit_20m_pnl = None
            if len(day_market) > 4:
                exit_20m_price = day_market.iloc[4]['close']
                if direction == 'LONG':
                    exit_20m_pnl = (exit_20m_price - entry_price) / entry_price * 100
                else:
                    exit_20m_pnl = (entry_price - exit_20m_price) / entry_price * 100
            
            # EXIT 2: 30 minute hold (bar at index 6 = 10:00)
            exit_30m_price = None
            exit_30m_pnl = None
            if len(day_market) > 6:
                exit_30m_price = day_market.iloc[6]['close']
                if direction == 'LONG':
                    exit_30m_pnl = (exit_30m_price - entry_price) / entry_price * 100
                else:
                    exit_30m_pnl = (entry_price - exit_30m_price) / entry_price * 100
            
            # EXIT 3: EMA trail (exit when price crosses EMA9 against position)
            # Look for first bar where close crosses EMA9 against us
            exit_ema_price = None
            exit_ema_pnl = None
            exit_ema_time = None
            
            for i in range(1, min(len(day_market), 12)):  # Max 1 hour (12 bars)
                bar_i = day_market.iloc[i]
                price = bar_i['close']
                ema = bar_i['ema9']
                
                if pd.isna(ema):
                    continue
                
                # For LONG: exit when close < EMA9
                # For SHORT: exit when close > EMA9
                if direction == 'LONG' and price < ema:
                    exit_ema_price = price
                    exit_ema_pnl = (exit_ema_price - entry_price) / entry_price * 100
                    exit_ema_time = i * 5  # minutes
                    break
                elif direction == 'SHORT' and price > ema:
                    exit_ema_price = price
                    exit_ema_pnl = (entry_price - exit_ema_price) / entry_price * 100
                    exit_ema_time = i * 5
                    break
            
            # If no EMA cross, use last bar we checked (max 1 hour)
            if exit_ema_price is None and len(day_market) > 1:
                last_idx = min(11, len(day_market) - 1)
                exit_ema_price = day_market.iloc[last_idx]['close']
                exit_ema_time = last_idx * 5
                if direction == 'LONG':
                    exit_ema_pnl = (exit_ema_price - entry_price) / entry_price * 100
                else:
                    exit_ema_pnl = (entry_price - exit_ema_price) / entry_price * 100
            
            # MFE/MAE calculation for this trade (bars 1-12)
            window = day_market.iloc[1:min(13, len(day_market))]
            max_high = window['high'].max()
            min_low = window['low'].min()
            
            if direction == 'LONG':
                mfe = (max_high - entry_price) / entry_price * 100
                mae = (entry_price - min_low) / entry_price * 100
            else:
                mfe = (entry_price - min_low) / entry_price * 100
                mae = (max_high - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'direction': direction,
                'move_pct': round(move_pct, 2),
                'filter': filter_reason,
                'entry': entry_price,
                'mfe': round(mfe, 2),
                'mae': round(mae, 2),
                'pnl_20m': exit_20m_pnl,
                'pnl_30m': exit_30m_pnl,
                'pnl_ema': exit_ema_pnl,
                'ema_hold_time': exit_ema_time
            })
        
        return trades
    except Exception as e:
        print(f"  {symbol}: {str(e)[:50]}")
        return []

def run_study():
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('FILTERED STRATEGY WITH MULTIPLE EXITS')
    print('Entry: 9:35 based on opening 5m bar')
    print('Filter: 0.25-0.75% trade direction | >=0.75% red only short')
    print('Exits: 20min hold | 30min hold | EMA9 trail')
    print(f'Stocks: {", ".join(SYMBOLS)}')
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
    
    # Overall comparison
    print('\n' + '='*100)
    print('EXIT METHOD COMPARISON:')
    print('='*100)
    print(f"{'Exit Method':20} {'Avg P&L':12} {'Win%':10} {'Total P&L':12} {'Best':10} {'Worst':10}")
    print('-'*100)
    
    for exit_name, col in [('20min Hold', 'pnl_20m'), ('30min Hold', 'pnl_30m'), ('EMA9 Trail', 'pnl_ema')]:
        pnl = df[col].dropna()
        if len(pnl) > 0:
            wins = len(pnl[pnl > 0])
            win_pct = wins / len(pnl) * 100
            total = pnl.sum()
            print(f"{exit_name:20} {pnl.mean():+10.3f}% {win_pct:9.1f}% {total:+10.3f}% {pnl.max():+8.2f}% {pnl.min():+8.2f}%")
    
    # By filter type
    print('\n' + '='*100)
    print('BY FILTER TYPE:')
    print('='*100)
    
    for filter_type in df['filter'].unique():
        filter_data = df[df['filter'] == filter_type]
        print(f"\n{filter_type} ({len(filter_data)} trades):")
        print(f"{'Exit':15} {'Avg P&L':12} {'Win%':10}")
        print('-'*45)
        
        for exit_name, col in [('20min', 'pnl_20m'), ('30min', 'pnl_30m'), ('EMA', 'pnl_ema')]:
            pnl = filter_data[col].dropna()
            if len(pnl) > 0:
                wins = len(pnl[pnl > 0])
                win_pct = wins / len(pnl) * 100
                print(f"{exit_name:15} {pnl.mean():+10.3f}% {win_pct:9.1f}%")
    
    # By symbol
    print('\n' + '='*100)
    print('BY SYMBOL (30min hold P&L):')
    print('='*100)
    print(f"{'Symbol':10} {'Trades':8} {'30min Avg':12} {'Win%':10} {'Total':12}")
    print('-'*80)
    
    for sym in SYMBOLS:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) == 0:
            continue
        
        pnl = sym_data['pnl_30m'].dropna()
        if len(pnl) > 0:
            wins = len(pnl[pnl > 0])
            win_pct = wins / len(pnl) * 100
            print(f"{sym:10} {len(sym_data):8} {pnl.mean():+10.3f}% {win_pct:9.1f}% {pnl.sum():+10.3f}%")
    
    # EMA hold time stats
    ema_times = df['ema_hold_time'].dropna()
    if len(ema_times) > 0:
        print('\n' + '='*100)
        print(f'EMA TRAIL HOLD TIME: {ema_times.mean():.1f} min avg | {ema_times.median():.1f} min median')
        print('='*100)
    
    # All trades
    print('\n' + '='*100)
    print(f'ALL {len(df)} TRADES:')
    print('='*100)
    print(f"{'Date':12} {'Sym':6} {'Dir':5} {'Move':7} {'Filter':18} {'20min':8} {'30min':8} {'EMA':8}")
    print('-'*100)
    
    for _, row in df.iterrows():
        p20 = f"{row['pnl_20m']:+.2f}" if pd.notna(row['pnl_20m']) else "N/A"
        p30 = f"{row['pnl_30m']:+.2f}" if pd.notna(row['pnl_30m']) else "N/A"
        pem = f"{row['pnl_ema']:+.2f}" if pd.notna(row['pnl_ema']) else "N/A"
        print(f"{row['date']!s:12} {row['symbol']:6} {row['direction']:5} {row['move_pct']:6.2f}% {row['filter']:18} {p20:>8} {p30:>8} {pem:>8}")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
