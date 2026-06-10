"""
BOOF 28 - Clean LONG Strategy
Universe: NVDA, AVGO, GOOGL, META
Entry: 9:35 if 5m bar > +0.25%
Exits: 20min hold | 30min hold | Trailing stop
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

SYMBOLS = ['NVDA', 'AVGO', 'GOOGL', 'META']

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
            
            # Calculate opening move
            opening_move = (close_price - open_price) / open_price * 100
            
            # Filter: LONG only if > +0.25%
            if opening_move <= 0.25:
                continue
            
            entry_price = close_price
            direction = 'LONG'
            
            # Get market data for exits
            day_market = day_df[day_df['time_et'] >= 930].reset_index(drop=True)
            if len(day_market) < 7:
                continue
            
            # EXIT 1: 20-minute hold (bar at index 4 = 9:55)
            exit_20m_price = day_market.iloc[4]['close']
            pnl_20m = (exit_20m_price - entry_price) / entry_price * 100
            
            # EXIT 2: 30-minute hold (bar at index 6 = 10:05)
            exit_30m_price = day_market.iloc[6]['close']
            pnl_30m = (exit_30m_price - entry_price) / entry_price * 100
            
            # EXIT 3: Trailing stop (20% retracement from high water mark)
            # Track running high and exit when we retrace 20% from peak
            high_water_mark = entry_price
            trailing_stop_price = None
            trailing_triggered = False
            
            for i in range(1, min(len(day_market), 13)):  # Max 1 hour
                current_high = day_market.iloc[i]['high']
                current_low = day_market.iloc[i]['low']
                
                # Update high water mark
                if current_high > high_water_mark:
                    high_water_mark = current_high
                
                # Calculate trailing stop level (20% retracement)
                stop_level = high_water_mark - (high_water_mark - entry_price) * 0.20
                
                # Check if we hit the trailing stop
                if current_low <= stop_level and high_water_mark > entry_price:
                    # Hit trailing stop - use stop level as exit
                    trailing_stop_price = stop_level
                    trailing_triggered = True
                    break
            
            # If trailing stop not triggered, use 60min close
            if not trailing_triggered:
                last_idx = min(12, len(day_market) - 1)
                trailing_stop_price = day_market.iloc[last_idx]['close']
            
            pnl_trail = (trailing_stop_price - entry_price) / entry_price * 100
            
            # MFE/MAE for 30min window
            window_30m = day_market.iloc[1:7]
            mfe = (window_30m['high'].max() - entry_price) / entry_price * 100
            mae = (entry_price - window_30m['low'].min()) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'opening_move': round(opening_move, 2),
                'entry': round(entry_price, 2),
                'pnl_20m': round(pnl_20m, 2),
                'pnl_30m': round(pnl_30m, 2),
                'pnl_trail': round(pnl_trail, 2),
                'mfe': round(mfe, 2),
                'mae': round(mae, 2),
                'max_price': round(bar_high, 2)
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
    print('CLEAN LONG STRATEGY')
    print('Universe: NVDA, AVGO, GOOGL, META')
    print('Entry: 9:35 if 5m bar > +0.25%')
    print('Exits: 20min | 30min | 20% Trailing Stop')
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
    
    # Exit comparison
    print('\n' + '='*100)
    print('EXIT METHOD COMPARISON:')
    print('='*100)
    print(f"{'Exit Method':20} {'Trades':8} {'Win%':10} {'Avg P&L':12} {'Total':12} {'Best':10}")
    print('-'*100)
    
    for exit_name, col in [('20min Hold', 'pnl_20m'), ('30min Hold', 'pnl_30m'), ('20% Trailing Stop', 'pnl_trail')]:
        pnl = df[col].dropna()
        if len(pnl) > 0:
            wins = len(pnl[pnl > 0])
            win_pct = wins / len(pnl) * 100
            total = pnl.sum()
            print(f"{exit_name:20} {len(pnl):8} {win_pct:9.1f}% {pnl.mean():+10.3f}% {total:+10.3f}% {pnl.max():+8.2f}%")
    
    # By symbol
    print('\n' + '='*100)
    print('BY SYMBOL (30min hold):')
    print('='*100)
    print(f"{'Symbol':10} {'Trades':8} {'Win%':10} {'Avg P&L':12} {'Total':12} {'Avg Move':12}")
    print('-'*100)
    
    for sym in SYMBOLS:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) == 0:
            continue
        
        pnl = sym_data['pnl_30m'].dropna()
        if len(pnl) > 0:
            wins = len(pnl[pnl > 0])
            win_pct = wins / len(pnl) * 100
            print(f"{sym:10} {len(sym_data):8} {win_pct:9.1f}% {pnl.mean():+10.3f}% {pnl.sum():+10.3f}% {sym_data['opening_move'].mean():+10.2f}%")
    
    # MFE/MAE
    print('\n' + '='*100)
    print('RISK METRICS (30min window):')
    print('='*100)
    mfe = df['mfe'].dropna()
    mae = df['mae'].dropna()
    print(f'  Average MFE: {mfe.mean():.2f}%')
    print(f'  Average MAE: {mae.mean():.2f}%')
    print(f'  MFE/MAE Ratio: {mfe.mean() / mae.mean():.2f}')
    print(f'  MFE > MAE: {len(df[df["mfe"] > df["mae"]])}/{len(df)} ({len(df[df["mfe"] > df["mae"]])/len(df)*100:.1f}%)')
    
    # All trades
    print('\n' + '='*100)
    print(f'ALL {len(df)} TRADES:')
    print('='*100)
    print(f"{'Date':12} {'Symbol':8} {'Move':8} {'Entry':10} {'20m':8} {'30m':8} {'Trail':8}")
    print('-'*100)
    
    df_sorted = df.sort_values('date')
    for _, row in df_sorted.iterrows():
        print(f"{row['date']!s:12} {row['symbol']:8} {row['opening_move']:+7.2f}% {row['entry']:9.2f} "
              f"{row['pnl_20m']:+7.2f}% {row['pnl_30m']:+7.2f}% {row['pnl_trail']:+7.2f}%")
    
    # Best trades
    print('\n' + '='*100)
    print('TOP 5 TRADES (by 30min P&L):')
    print('='*100)
    top5 = df.nlargest(5, 'pnl_30m')
    for _, row in top5.iterrows():
        print(f"  {row['date']!s:12} {row['symbol']:6} {row['opening_move']:+5.2f}% → {row['pnl_30m']:+5.2f}%")
    
    # Worst trades
    print('\n' + '='*100)
    print('BOTTOM 5 TRADES:')
    print('='*100)
    bottom5 = df.nsmallest(5, 'pnl_30m')
    for _, row in bottom5.iterrows():
        print(f"  {row['date']!s:12} {row['symbol']:6} {row['opening_move']:+5.2f}% → {row['pnl_30m']:+5.2f}%")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
