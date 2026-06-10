"""
BOOF 28 v2 - 1 Week, 100 Stocks, 5m Candles
Logic: 2.5x vol spike → 5min wait → 0.30% move + 0.55 trend eff + EMA9 check
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

STOCKS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    "AMD","INTC","QCOM","MU","TXN","ADI","MRVL","SNPS","CDNS","KLAC",
    "JPM","V","MA","BAC","GS","WFC","C","AXP","BLK","SPGI",
    "UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT","DHR","BMY",
    "AMGN","GILD","REGN","VRTX","ZTS","ISRG","ELV","CI","HUM","CVS",
    "WMT","COST","HD","PG","KO","PEP","MCD","NKE","TJX","LOW",
    "SBUX","TGT","DG","ROST","BKNG","MAR","HLT","ABNB","DASH","UBER",
    "XOM","CVX","COP","EOG","SLB","OXY","MPC","VLO","PSX","KMI",
    "GE","HON","UPS","BA","CAT","DE","LMT","NOC","RTX","UNP","SPY"
]

def calculate_ema(df, period=9):
    """Calculate EMA9"""
    return df['close'].ewm(span=period, adjust=False).mean()

def calculate_same_time_avg_volume(df, lookback_days=60):
    """Calculate average volume for same time slot across lookback days"""
    df['time'] = df['timestamp'].dt.time
    df['date'] = df['timestamp'].dt.date
    
    dates = sorted(df['date'].unique())
    if len(dates) > lookback_days:
        recent_dates = dates[-lookback_days:]
    else:
        recent_dates = dates
    
    # Exclude current day from average
    hist_df = df[df['date'].isin(recent_dates[:-1])]
    if len(hist_df) == 0:
        return pd.Series(df['volume'].mean(), index=df.index)
    
    time_groups = hist_df.groupby('time')['volume'].mean()
    
    avg_volumes = []
    for idx, row in df.iterrows():
        t = row['time']
        if t in time_groups and time_groups[t] > 0:
            avg_volumes.append(time_groups[t])
        else:
            avg_volumes.append(row['volume'])
    
    return pd.Series(avg_volumes, index=df.index)

def run_backtest():
    # One week: Jan 13-17, 2026
    start_date = datetime(2026, 1, 13, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 17, tzinfo=timezone.utc)
    
    # Fetch extra 60 days for volume baseline
    fetch_start = start_date - timedelta(days=65)
    fetch_end = end_date + timedelta(days=1)
    
    print('='*80)
    print('BOOF 28 v2 - 1 WEEK TEST (Jan 13-17, 2026)')
    print('5m candles | 100 stocks')
    print('Entry: 2.5x vol spike → 5min wait → 0.30% move + 0.55 trend eff + EMA9')
    print('Exit: +0.75% TP / -0.40% SL / 15min time stop')
    print('='*80)
    
    # Generate trading days
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    
    all_trades = []
    
    for day in days:
        print(f'\n{day.date()}:')
        day_trade_count = 0
        
        for sym in STOCKS:
            try:
                # Get 5m data
                df = fetch_alpaca_bars(sym, fetch_start, fetch_end, '5Min', 
                                       creds['api_key'], creds['secret_key'])
                if df is None or len(df) < 50:
                    continue
                
                # Standardize columns
                if 'open' not in df.columns:
                    df.columns = [c.lower() for c in df.columns]
                df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
                
                # Calculate EMA9 and seasonal volume
                df['ema9'] = calculate_ema(df, 9)
                avg_vol = calculate_same_time_avg_volume(df, lookback_days=60)
                df['avg_vol'] = avg_vol
                df['vol_ratio'] = df['volume'] / df['avg_vol']
                
                # Filter to market hours (9:30 AM - 12:00 PM ET = 14:30-17:00 UTC)
                df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24  # Convert to ET
                df['minute'] = df['timestamp'].dt.minute
                df['time_et'] = df['hour_et'] * 100 + df['minute']
                
                # Get just today, market hours only (9:30-12:00 = 930-1200)
                today_mask = (df['timestamp'].dt.date == day.date()) & (df['time_et'] >= 930) & (df['time_et'] <= 1200)
                today = df[today_mask].reset_index(drop=True)
                
                if len(today) < 6:  # Need at least spike bar + 5min wait + exit room
                    continue
                
                # Calculate EMA9 for today
                today['ema9'] = calculate_ema(today, 9)
                
                # Check first 12 bars (up to 11:00 AM) for spikes
                for i in range(min(12, len(today) - 4)):
                    # Stage 1: Volume spike >= 2.5x
                    if pd.isna(today['vol_ratio'].iloc[i]) or today['vol_ratio'].iloc[i] < 2.5:
                        continue
                    
                    spike_close = today['close'].iloc[i]
                    spike_price = spike_close
                    
                    # Stage 2: Wait 5 minutes (1 bar of 5m = 5 min)
                    confirm_bar = i + 1
                    if confirm_bar >= len(today):
                        continue
                    
                    close_now = today['close'].iloc[confirm_bar]
                    ema9_now = today['ema9'].iloc[confirm_bar]
                    
                    # Window for trend efficiency (spike bar + confirmation bar)
                    window_high = today['high'].iloc[i:confirm_bar+1].max()
                    window_low = today['low'].iloc[i:confirm_bar+1].min()
                    window_range = window_high - window_low
                    
                    # Calculate metrics
                    confirm_return = (close_now - spike_close) / spike_close
                    
                    if window_range > 0:
                        trend_efficiency = abs(close_now - spike_close) / window_range
                    else:
                        trend_efficiency = 0
                    
                    # Check entry conditions
                    long_ok = (confirm_return >= 0.003 and 
                               trend_efficiency >= 0.55 and 
                               close_now > ema9_now)
                    
                    short_ok = (confirm_return <= -0.003 and 
                                trend_efficiency >= 0.55 and 
                                close_now < ema9_now)
                    
                    direction = None
                    if long_ok:
                        direction = 'LONG'
                    elif short_ok:
                        direction = 'SHORT'
                    
                    if not direction:
                        continue
                    
                    # Entry at confirm_bar
                    entry_idx = confirm_bar
                    entry_price = close_now
                    
                    # Exit logic: TP +0.75% / SL -0.40% / Time 15min (3 bars of 5m)
                    tp_pct = 0.0075 if direction == 'LONG' else -0.0075
                    sl_pct = -0.0040 if direction == 'LONG' else 0.0040
                    
                    tp_price = entry_price * (1 + tp_pct)
                    sl_price = entry_price * (1 + sl_pct)
                    
                    exit_price = None
                    exit_type = None
                    
                    # Check next 3 bars (15 minutes of 5m data)
                    for j in range(entry_idx + 1, min(entry_idx + 4, len(today))):
                        if direction == 'LONG':
                            if today['high'].iloc[j] >= tp_price:
                                exit_price = tp_price
                                exit_type = 'TP'
                                break
                            if today['low'].iloc[j] <= sl_price:
                                exit_price = sl_price
                                exit_type = 'SL'
                                break
                        else:  # SHORT
                            if today['low'].iloc[j] <= tp_price:
                                exit_price = tp_price
                                exit_type = 'TP'
                                break
                            if today['high'].iloc[j] >= sl_price:
                                exit_price = sl_price
                                exit_type = 'SL'
                                break
                    
                    # Time stop at 15 min (3 bars)
                    if exit_price is None:
                        time_idx = min(entry_idx + 3, len(today) - 1)
                        exit_price = today['close'].iloc[time_idx]
                        exit_type = 'TIME'
                    
                    # Calculate P&L
                    if direction == 'LONG':
                        pnl = (exit_price - entry_price) / entry_price * 100
                    else:
                        pnl = (entry_price - exit_price) / entry_price * 100
                    
                    # Print trade
                    print(f"  {sym:5s} {direction:5s} | Entry: ${entry_price:.2f} | Exit: ${exit_price:.2f} ({exit_type}) | P&L: {pnl:+.2f}%")
                    
                    all_trades.append({
                        'day': day.date(),
                        'sym': sym,
                        'dir': direction,
                        'entry': entry_price,
                        'exit': exit_price,
                        'exit_type': exit_type,
                        'pnl': pnl,
                        'vol_ratio': today['vol_ratio'].iloc[i],
                        'trend_eff': trend_efficiency,
                        'confirm_ret': confirm_return
                    })
                    day_trade_count += 1
                
                time.sleep(0.02)
                
            except Exception as e:
                pass
        
        if day_trade_count == 0:
            print("  No trades")
    
    # Final summary
    print('\n' + '='*80)
    if all_trades:
        df_trades = pd.DataFrame(all_trades)
        wins = len(df_trades[df_trades['pnl'] > 0])
        total_pnl = df_trades['pnl'].sum()
        
        tp_exits = len(df_trades[df_trades['exit_type'] == 'TP'])
        sl_exits = len(df_trades[df_trades['exit_type'] == 'SL'])
        time_exits = len(df_trades[df_trades['exit_type'] == 'TIME'])
        
        print(f'WEEK RESULTS: {len(df_trades)} trades')
        print(f'Win Rate: {wins/len(df_trades)*100:.1f}%')
        print(f'Total P&L: {total_pnl:+.2f}%')
        print(f'Avg P&L: {total_pnl/len(df_trades):.3f}%')
        print(f'\nExit Types: TP={tp_exits} | SL={sl_exits} | TIME={time_exits}')
        print(f'Avg Vol Ratio: {df_trades["vol_ratio"].mean():.2f}x')
        print(f'Avg Trend Eff: {df_trades["trend_eff"].mean():.3f}')
        
        print(f'\nTop 5 Trades:')
        top5 = df_trades.nlargest(5, 'pnl')
        for _, t in top5.iterrows():
            print(f"  {t['day']} {t['sym']:5s} {t['dir']:5s} +{t['pnl']:.2f}% ({t['exit_type']})")
        
        print(f'\nWorst 5 Trades:')
        bot5 = df_trades.nsmallest(5, 'pnl')
        for _, t in bot5.iterrows():
            print(f"  {t['day']} {t['sym']:5s} {t['dir']:5s} {t['pnl']:.2f}% ({t['exit_type']})")
    else:
        print('No trades found')
    print('='*80)

if __name__ == '__main__':
    run_backtest()
