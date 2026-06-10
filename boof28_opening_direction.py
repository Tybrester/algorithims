"""
BOOF 28 - Opening Bar Direction Study
Simple: Green bar = LONG, Red bar = SHORT
Hold 20min and 30min, measure returns
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

SYMBOLS = ['AAPL', 'NVDA', 'AMZN', 'META', 'AVGO', 'GOOGL', 'TSLA']

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
            
            # Find 9:30 AM bar (market open)
            open_bar = day_df[day_df['time_et'] == 930]
            if len(open_bar) == 0:
                continue
            
            bar = open_bar.iloc[0]
            open_price = bar['open']
            close_price = bar['close']
            bar_high = bar['high']
            bar_low = bar['low']
            
            # Direction based on bar color
            if close_price > open_price:
                direction = 'LONG'
                entry_price = close_price  # Enter at 9:35 close
            elif close_price < open_price:
                direction = 'SHORT'
                entry_price = close_price  # Enter at 9:35 close
            else:
                continue  # Doji, skip
            
            # Need 7 more bars for 30min hold (9:35 to 10:05 = 6 bars)
            day_market = day_df[day_df['time_et'] >= 930].reset_index(drop=True)
            if len(day_market) < 7:
                continue
            
            # Returns at 20min (bar 4 from entry = bar 5 total) and 30min (bar 6 from entry = bar 7 total)
            # Entry is at close of bar 0 (9:35), so:
            # 20min later = bar 4 (10:00)
            # 30min later = bar 6 (10:05)
            
            ret_20m = None
            ret_30m = None
            
            if len(day_market) > 4:
                price_20m = day_market.iloc[4]['close']  # 9:30, 9:35, 9:40, 9:45, 9:50 = 20min from 9:30 open
                ret_20m = (price_20m - entry_price) / entry_price * 100
            
            if len(day_market) > 6:
                price_30m = day_market.iloc[6]['close']  # 30min from 9:30
                ret_30m = (price_30m - entry_price) / entry_price * 100
            
            # MFE/MAE from entry (bars 1-6 = 9:35 to 10:05)
            window = day_market.iloc[1:7]  # Skip bar 0 (entry bar)
            
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
                'open_930': open_price,
                'close_935': close_price,
                'bar_range': round((bar_high - bar_low) / open_price * 100, 2),
                'ret_20m': ret_20m,
                'ret_30m': ret_30m,
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
    print('OPENING BAR DIRECTION STUDY')
    print('Rule: Green 9:30 bar = LONG, Red 9:30 bar = SHORT')
    print('Entry: 9:35 close | Hold: 20min and 30min')
    print(f'Stocks: {", ".join(SYMBOLS)}')
    print(f'Period: {start_date.date()} to {end_date.date()} (3 months)')
    print('='*100)
    
    all_trades = []
    
    for sym in SYMBOLS:
        print(f'\nAnalyzing {sym}...', end=' ')
        trades = analyze_symbol(sym, start_date, end_date)
        print(f'{len(trades)} days')
        all_trades.extend(trades)
        time.sleep(0.3)
    
    if not all_trades:
        print('\nNo data found')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*100)
    print(f'TOTAL TRADES: {len(df)}')
    print('='*100)
    
    # Overall stats
    longs = df[df['direction'] == 'LONG']
    shorts = df[df['direction'] == 'SHORT']
    
    print(f'\nDIRECTION BREAKDOWN:')
    print(f'  LONG (green bars):  {len(longs)} ({len(longs)/len(df)*100:.1f}%)')
    print(f'  SHORT (red bars):   {len(shorts)} ({len(shorts)/len(df)*100:.1f}%)')
    
    # Returns
    ret_20m_all = df['ret_20m'].dropna()
    ret_30m_all = df['ret_30m'].dropna()
    
    if len(ret_20m_all) > 0:
        print(f'\n20-MINUTE HOLDS:')
        wins_20m = len(ret_20m_all[ret_20m_all > 0])
        print(f'  Avg Return: {ret_20m_all.mean():+.3f}%')
        print(f'  Win Rate: {wins_20m}/{len(ret_20m_all)} ({wins_20m/len(ret_20m_all)*100:.1f}%)')
        print(f'  Best: {ret_20m_all.max():+.2f}% | Worst: {ret_20m_all.min():+.2f}%')
    
    if len(ret_30m_all) > 0:
        print(f'\n30-MINUTE HOLDS:')
        wins_30m = len(ret_30m_all[ret_30m_all > 0])
        print(f'  Avg Return: {ret_30m_all.mean():+.3f}%')
        print(f'  Win Rate: {wins_30m}/{len(ret_30m_all)} ({wins_30m/len(ret_30m_all)*100:.1f}%)')
        print(f'  Best: {ret_30m_all.max():+.2f}% | Worst: {ret_30m_all.min():+.2f}%')
    
    # MFE/MAE
    mfe_all = df['mfe'].dropna()
    mae_all = df['mae'].dropna()
    
    print(f'\nMFE/MAE (30min window):')
    print(f'  Avg MFE: {mfe_all.mean():.2f}%')
    print(f'  Avg MAE: {mae_all.mean():.2f}%')
    print(f'  MFE > MAE: {len(df[df["mfe"] > df["mae"]])}/{len(df)} ({len(df[df["mfe"] > df["mae"]])/len(df)*100:.1f}%)')
    
    # By direction
    print('\n' + '='*100)
    print('BY DIRECTION:')
    print('='*100)
    
    for direction, label in [('LONG', 'LONG (Green 9:30 bar)'), ('SHORT', 'SHORT (Red 9:30 bar)')]:
        dir_data = df[df['direction'] == direction]
        if len(dir_data) == 0:
            continue
        
        ret_20 = dir_data['ret_20m'].dropna()
        ret_30 = dir_data['ret_30m'].dropna()
        mfe_dir = dir_data['mfe'].dropna()
        mae_dir = dir_data['mae'].dropna()
        
        print(f'\n{label} ({len(dir_data)} trades):')
        if len(ret_20) > 0:
            wins_20 = len(ret_20[ret_20 > 0])
            print(f'  20min: {ret_20.mean():+.3f}% avg | {wins_20}/{len(ret_20)} wins ({wins_20/len(ret_20)*100:.1f}%)')
        if len(ret_30) > 0:
            wins_30 = len(ret_30[ret_30 > 0])
            print(f'  30min: {ret_30.mean():+.3f}% avg | {wins_30}/{len(ret_30)} wins ({wins_30/len(ret_30)*100:.1f}%)')
        print(f'  MFE: {mfe_dir.mean():.2f}% | MAE: {mae_dir.mean():.2f}%')
    
    # By symbol
    print('\n' + '='*100)
    print('BY SYMBOL (30min returns):')
    print('='*100)
    print(f"{'Symbol':10} {'Trades':8} {'30min Avg':12} {'Win%':8} {'MFE':8} {'MAE':8}")
    print('-'*100)
    
    for sym in SYMBOLS:
        sym_data = df[df['symbol'] == sym]
        if len(sym_data) == 0:
            continue
        
        ret_30 = sym_data['ret_30m'].dropna()
        mfe_sym = sym_data['mfe'].dropna()
        mae_sym = sym_data['mae'].dropna()
        
        if len(ret_30) > 0:
            wins = len(ret_30[ret_30 > 0])
            win_pct = wins / len(ret_30) * 100
            print(f"{sym:10} {len(sym_data):8} {ret_30.mean():+10.3f}% {win_pct:7.1f}% {mfe_sym.mean():7.2f}% {mae_sym.mean():7.2f}%")
    
    # Top 10 best and worst
    print('\n' + '='*100)
    print('TOP 10 BEST 30-MIN RETURNS:')
    print('='*100)
    best = df.nlargest(10, 'ret_30m')
    for _, row in best.iterrows():
        print(f"{row['date']!s:12} {row['symbol']:6} {row['direction']:5} {row['ret_30m']:+6.2f}% (Range: {row['bar_range']:.2f}%)")
    
    print('\n' + '='*100)
    print('TOP 10 WORST 30-MIN RETURNS:')
    print('='*100)
    worst = df.nsmallest(10, 'ret_30m')
    for _, row in worst.iterrows():
        print(f"{row['date']!s:12} {row['symbol']:6} {row['direction']:5} {row['ret_30m']:+6.2f}% (Range: {row['bar_range']:.2f}%)")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
