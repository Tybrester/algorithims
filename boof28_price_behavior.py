"""
BOOF 28 - Price Behavior Study (Opening 5-min bar analysis)
Focus on price action: opening move + trend efficiency
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

def calculate_same_time_avg_volume(df, lookback_days=20):
    df['time_of_day'] = df['timestamp'].dt.time
    df['date'] = df['timestamp'].dt.date
    
    dates = sorted(df['date'].unique())
    if len(dates) > lookback_days:
        recent_dates = dates[-lookback_days:]
    else:
        recent_dates = dates
    
    hist_df = df[df['date'].isin(recent_dates[:-1])]
    if len(hist_df) == 0:
        return pd.Series(df['volume'].mean(), index=df.index)
    
    time_groups = hist_df.groupby('time_of_day')['volume'].mean()
    
    avg_volumes = []
    for idx, row in df.iterrows():
        t = row['time_of_day']
        if t in time_groups and time_groups[t] > 0:
            avg_volumes.append(time_groups[t])
        else:
            avg_volumes.append(row['volume'])
    
    return pd.Series(avg_volumes, index=df.index)

def analyze_symbol(symbol, start_date, end_date):
    fetch_start = start_date - timedelta(days=25)
    fetch_end = end_date + timedelta(days=1)
    
    try:
        df = fetch_alpaca_bars(symbol, fetch_start, fetch_end, '5Min', 
                               creds['api_key'], creds['secret_key'])
        
        if df is None or len(df) < 50:
            return []
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        
        # Calculate volume ratio
        avg_vol = calculate_same_time_avg_volume(df, lookback_days=20)
        df['vol_ratio'] = df['volume'] / avg_vol
        
        # Time in ET
        df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
        df['minute'] = df['timestamp'].dt.minute
        df['time_et'] = df['hour_et'] * 100 + df['minute']
        
        trades = []
        
        # Get unique dates
        df['date'] = df['timestamp'].dt.date
        dates = sorted(df['date'].unique())
        
        for trade_date in dates:
            day_df = df[df['date'] == trade_date].copy()
            
            # Find 9:30 AM bar (market open)
            open_930 = day_df[day_df['time_et'] == 930]
            if len(open_930) == 0:
                continue
            
            open_bar = open_930.iloc[0]
            open_price = open_bar['open']
            open_close = open_bar['close']
            open_high = open_bar['high']
            open_low = open_bar['low']
            open_vol_ratio = open_bar['vol_ratio']
            
            # Check if we have next bars for MFE measurement
            day_market = day_df[(day_df['time_et'] >= 930) & (day_df['time_et'] <= 1600)]
            if len(day_market) < 7:  # Need open + 6 more bars for 30min window
                continue
            
            # Calculate metrics
            opening_move = abs(open_close - open_price) / open_price
            price_range = open_high - open_low
            trend_efficiency = abs(open_close - open_price) / price_range if price_range > 0 else 0
            
            # Determine direction
            direction = 'LONG' if open_close > open_price else 'SHORT'
            
            # Entry at 9:35 close (first 5min bar close)
            entry_price = open_close
            
            # Measure MFE/MAE for next 30 minutes (bars 1-6 after open, so 9:35 to 10:00)
            window = day_market.iloc[1:7]  # Skip the 9:30 bar itself
            
            if len(window) < 3:
                continue
            
            max_high = window['high'].max()
            min_low = window['low'].min()
            
            if direction == 'LONG':
                mfe = (max_high - entry_price) / entry_price * 100
                mae = (entry_price - min_low) / entry_price * 100
            else:
                mfe = (entry_price - min_low) / entry_price * 100
                mae = (max_high - entry_price) / entry_price * 100
            
            # Time to MFE
            time_to_mfe = None
            if direction == 'LONG':
                for idx_bar, (idx, row) in enumerate(window.iterrows()):
                    if row['high'] >= max_high * 0.999:
                        time_to_mfe = (idx_bar + 1) * 5  # +1 because window starts at bar 1
                        break
            else:
                for idx_bar, (idx, row) in enumerate(window.iterrows()):
                    if row['low'] <= min_low * 1.001:
                        time_to_mfe = (idx_bar + 1) * 5
                        break
            
            # Returns at 10/20/30 min from entry
            ret_10m = ret_20m = ret_30m = None
            if len(day_market) > 3:
                ret_10m = (day_market.iloc[3]['close'] - entry_price) / entry_price * 100
            if len(day_market) > 5:
                ret_20m = (day_market.iloc[5]['close'] - entry_price) / entry_price * 100
            if len(day_market) > 7:
                ret_30m = (day_market.iloc[7]['close'] - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'rvol': round(open_vol_ratio, 2) if pd.notna(open_vol_ratio) else 0,
                'opening_move': round(opening_move * 100, 2),  # as percentage
                'trend_eff': round(trend_efficiency, 3),
                'direction': direction,
                'open_price': open_price,
                'entry_price': entry_price,
                'mfe': round(mfe, 2),
                'mae': round(mae, 2),
                'time_to_mfe': time_to_mfe,
                'ret_10m': ret_10m,
                'ret_20m': ret_20m,
                'ret_30m': ret_30m
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
    print('PRICE BEHAVIOR STUDY - Opening 5-Minute Bar Analysis')
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
    print(f'TOTAL OPENING BARS: {len(df)}')
    print('='*100)
    
    # Overall stats
    mfe_values = df['mfe'].dropna()
    mae_values = df['mae'].dropna()
    
    if len(mfe_values) > 0:
        print(f'\nALL OPENING BARS - MFE/MAE (next 30 min):')
        print(f'  Avg MFE: {mfe_values.mean():.2f}% | Median: {mfe_values.median():.2f}%')
        print(f'  Avg MAE: {mae_values.mean():.2f}% | Median: {mae_values.median():.2f}%')
        print(f'  MFE > MAE: {len(df[df["mfe"] > df["mae"]])}/{len(df)} ({len(df[df["mfe"] > df["mae"]])/len(df)*100:.1f}%)')
    
    # Apply candidate filter
    candidates = df[
        (df['rvol'] > 2.0) & 
        (df['opening_move'] > 0.75) & 
        (df['trend_eff'] > 0.70)
    ].copy()
    
    print('\n' + '='*100)
    print(f'CANDIDATES (RVOL>2, Move>0.75%, TrendEff>0.70): {len(candidates)}')
    print('='*100)
    
    if len(candidates) > 0:
        cand_mfe = candidates['mfe'].dropna()
        cand_mae = candidates['mae'].dropna()
        
        print(f'\nCANDIDATE MFE/MAE:')
        print(f'  Avg MFE: {cand_mfe.mean():.2f}% | Median: {cand_mfe.median():.2f}%')
        print(f'  Avg MAE: {cand_mae.mean():.2f}% | Median: {cand_mae.median():.2f}%')
        print(f'  MFE > MAE: {len(candidates[candidates["mfe"] > candidates["mae"]])}/{len(candidates)} ({len(candidates[candidates["mfe"] > candidates["mae"]])/len(candidates)*100:.1f}%)')
        
        ttm = candidates['time_to_mfe'].dropna()
        if len(ttm) > 0:
            print(f'\nTIME-TO-MFE: {ttm.mean():.1f} min avg | {ttm.median():.1f} min median')
    
    # By symbol
    print('\n' + '='*100)
    print('CANDIDATES BY SYMBOL:')
    print('='*100)
    print(f"{'Symbol':10} {'Count':8} {'Avg MFE':10} {'Avg MAE':10} {'MFE>MAE':10} {'Best':10}")
    print('-'*100)
    
    for sym in SYMBOLS:
        sym_cand = candidates[candidates['symbol'] == sym]
        if len(sym_cand) == 0:
            continue
        
        mfe_sym = sym_cand['mfe'].dropna()
        mae_sym = sym_cand['mae'].dropna()
        good = len(sym_cand[sym_cand['mfe'] > sym_cand['mae']])
        
        print(f"{sym:10} {len(sym_cand):8} {mfe_sym.mean():9.2f}% {mae_sym.mean():9.2f}% {good:5}/{len(sym_cand):<4} {mfe_sym.max():9.2f}%")
    
    # Print all candidates
    if len(candidates) > 0:
        print('\n' + '='*100)
        print(f'ALL {len(candidates)} CANDIDATES:')
        print('='*100)
        print(f"{'Date':12} {'Sym':6} {'RVOL':6} {'Move':7} {'Eff':6} {'Dir':5} {'MFE':7} {'MAE':7} {'TTM':5}")
        print('-'*100)
        
        for _, row in candidates.iterrows():
            ttm = f"{row['time_to_mfe']:.0f}m" if pd.notna(row['time_to_mfe']) else "N/A"
            print(f"{row['date']!s:12} {row['symbol']:6} {row['rvol']:6.2f} {row['opening_move']:6.2f}% {row['trend_eff']:6.3f} {row['direction']:5} {row['mfe']:6.2f}% {row['mae']:6.2f}% {ttm:5}")
        
        # Top by MFE
        print('\n' + '='*100)
        print('TOP 10 CANDIDATES BY MFE:')
        print('='*100)
        top10 = candidates.nlargest(10, 'mfe')
        for _, row in top10.iterrows():
            ttm = f"{row['time_to_mfe']:.0f}m" if pd.notna(row['time_to_mfe']) else "N/A"
            print(f"{row['date']!s:12} {row['symbol']:6} Move:{row['opening_move']:5.2f}% Eff:{row['trend_eff']:.2f} MFE:{row['mfe']:5.2f}% MAE:{row['mae']:5.2f}% {ttm}")
    
    print('='*100)

if __name__ == '__main__':
    run_study()
