"""
BOOF 28 v3 - Relaxed Filters + Debug
1.5x vol, 3min wait, 0.15% move, 0.35 eff
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
    "AMD","INTC","QCOM","MU","TXN","ADI","JPM","V","MA","BAC",
    "GS","WFC","UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT",
    "WMT","COST","HD","PG","KO","PEP","MCD","NKE","TJX","LOW",
    "SBUX","XOM","CVX","COP","GE","HON","UPS","BA","CAT","VZ",
    "DIS","LIN","PLD","F","GM","DAL","UAL","COIN","GME","PLTR",
    "SOFI","RBLX","BABA","JD","SPY","QQQ","IWM","XLF","XLK","XLE",
    "ARKK","TLT","GLD","USO","SLV","BITO","MSTR"
]

def calculate_same_time_avg_volume(df, lookback_days=60):
    df['time'] = df['timestamp'].dt.time
    df['date'] = df['timestamp'].dt.date
    
    dates = sorted(df['date'].unique())
    if len(dates) > lookback_days:
        recent_dates = dates[-lookback_days:]
    else:
        recent_dates = dates
    
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
    
    fetch_start = start_date - timedelta(days=65)
    fetch_end = end_date + timedelta(days=1)
    
    # RELAXED PARAMS
    VOL_THRESHOLD = 1.5
    WAIT_BARS = 3  # 3 bars of 5m = 15 min (was 1 bar = 5 min)
    MOVE_THRESHOLD = 0.0015  # 0.15%
    EFF_THRESHOLD = 0.35
    
    print('='*80)
    print('BOOF 28 v3 - RELAXED FILTERS + DEBUG')
    print('1.5x vol | 15min wait | 0.15% move | 0.35 eff')
    print('70 stocks | 5m candles')
    print('='*80)
    
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    
    all_trades = []
    debug_count = {'spike': 0, 'move_fail': 0, 'eff_fail': 0, 'trade': 0}
    
    for day in days:
        print(f'\n{day.date()}:')
        day_trades = 0
        
        for sym in STOCKS:
            try:
                df = fetch_alpaca_bars(sym, fetch_start, fetch_end, '5Min', 
                                       creds['api_key'], creds['secret_key'])
                if df is None or len(df) < 50:
                    continue
                
                if 'open' not in df.columns:
                    df.columns = [c.lower() for c in df.columns]
                df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
                
                # Calculate seasonal volume
                avg_vol = calculate_same_time_avg_volume(df, lookback_days=60)
                df['vol_ratio'] = df['volume'] / avg_vol
                
                # Filter to market hours (9:30 AM - 12:00 PM ET)
                df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
                df['minute'] = df['timestamp'].dt.minute
                df['time_et'] = df['hour_et'] * 100 + df['minute']
                
                today_mask = (df['timestamp'].dt.date == day.date()) & (df['time_et'] >= 930) & (df['time_et'] <= 1200)
                today = df[today_mask].reset_index(drop=True)
                
                if len(today) < WAIT_BARS + 2:
                    continue
                
                # Check first 15 bars (up to 10:45 AM)
                for i in range(min(15, len(today) - WAIT_BARS)):
                    # Stage 1: Volume spike >= 1.5x
                    vol_ratio = today['vol_ratio'].iloc[i]
                    if pd.isna(vol_ratio) or vol_ratio < VOL_THRESHOLD:
                        continue
                    
                    debug_count['spike'] += 1
                    spike_time = today['timestamp'].iloc[i]
                    spike_time_et = spike_time - timedelta(hours=5)
                    time_str = spike_time_et.strftime('%H:%M')
                    
                    spike_close = today['close'].iloc[i]
                    
                    # Stage 2: Wait 3 bars (15 min)
                    confirm_bar = i + WAIT_BARS
                    if confirm_bar >= len(today):
                        continue
                    
                    close_now = today['close'].iloc[confirm_bar]
                    
                    # Calculate window metrics
                    window_high = today['high'].iloc[i:confirm_bar+1].max()
                    window_low = today['low'].iloc[i:confirm_bar+1].min()
                    window_range = max(window_high - window_low, 0.01)
                    
                    confirm_return = (close_now - spike_close) / spike_close
                    trend_efficiency = abs(close_now - spike_close) / window_range
                    
                    # Check conditions
                    long_ok = (confirm_return >= MOVE_THRESHOLD and trend_efficiency >= EFF_THRESHOLD)
                    short_ok = (confirm_return <= -MOVE_THRESHOLD and trend_efficiency >= EFF_THRESHOLD)
                    
                    # DEBUG PRINT - show all spikes and why they fail/pass
                    if not long_ok and not short_ok:
                        # Show failure reason
                        fail_reason = []
                        if abs(confirm_return) < MOVE_THRESHOLD:
                            fail_reason.append(f"move:{confirm_return*100:.3f}%")
                        if trend_efficiency < EFF_THRESHOLD:
                            fail_reason.append(f"eff:{trend_efficiency:.2f}")
                        
                        print(f"  {sym:5s} {time_str} | vol:{vol_ratio:.2f}x | {', '.join(fail_reason)} | SKIP")
                        
                        if abs(confirm_return) < MOVE_THRESHOLD:
                            debug_count['move_fail'] += 1
                        elif trend_efficiency < EFF_THRESHOLD:
                            debug_count['eff_fail'] += 1
                        continue
                    
                    # TRADE!
                    direction = 'LONG' if confirm_return > 0 else 'SHORT'
                    entry_price = close_now
                    
                    # Exit: +0.75% TP / -0.40% SL / 15min time
                    tp_pct = 0.0075 if direction == 'LONG' else -0.0075
                    sl_pct = -0.0040 if direction == 'LONG' else 0.0040
                    
                    tp_price = entry_price * (1 + tp_pct)
                    sl_price = entry_price * (1 + sl_pct)
                    
                    exit_price = None
                    exit_type = None
                    
                    for j in range(confirm_bar + 1, min(confirm_bar + 4, len(today))):
                        if direction == 'LONG':
                            if today['high'].iloc[j] >= tp_price:
                                exit_price = tp_price
                                exit_type = 'TP'
                                break
                            if today['low'].iloc[j] <= sl_price:
                                exit_price = sl_price
                                exit_type = 'SL'
                                break
                        else:
                            if today['low'].iloc[j] <= tp_price:
                                exit_price = tp_price
                                exit_type = 'TP'
                                break
                            if today['high'].iloc[j] >= sl_price:
                                exit_price = sl_price
                                exit_type = 'SL'
                                break
                    
                    if exit_price is None:
                        time_idx = min(confirm_bar + 3, len(today) - 1)
                        exit_price = today['close'].iloc[time_idx]
                        exit_type = 'TIME'
                    
                    if direction == 'LONG':
                        pnl = (exit_price - entry_price) / entry_price * 100
                    else:
                        pnl = (entry_price - exit_price) / entry_price * 100
                    
                    # Print trade
                    print(f"  >>> {sym:5s} {direction:5s} {time_str} | vol:{vol_ratio:.2f}x | ret:{confirm_return*100:.3f}% | eff:{trend_efficiency:.2f} | P&L:{pnl:+.2f}% ({exit_type})")
                    
                    all_trades.append({
                        'day': day.date(), 'sym': sym, 'dir': direction,
                        'entry': entry_price, 'exit': exit_price,
                        'exit_type': exit_type, 'pnl': pnl
                    })
                    debug_count['trade'] += 1
                    day_trades += 1
                
                time.sleep(0.02)
            except Exception as e:
                pass
        
        if day_trades == 0:
            print("  No trades")
    
    # Summary
    print('\n' + '='*80)
    print(f'DEBUG STATS:')
    print(f"  Volume spikes found: {debug_count['spike']}")
    print(f"  Failed move check: {debug_count['move_fail']}")
    print(f"  Failed eff check: {debug_count['eff_fail']}")
    print(f"  Trades taken: {debug_count['trade']}")
    
    if all_trades:
        df_trades = pd.DataFrame(all_trades)
        wins = len(df_trades[df_trades['pnl'] > 0])
        total_pnl = df_trades['pnl'].sum()
        
        tp_exits = len(df_trades[df_trades['exit_type'] == 'TP'])
        sl_exits = len(df_trades[df_trades['exit_type'] == 'SL'])
        time_exits = len(df_trades[df_trades['exit_type'] == 'TIME'])
        
        print(f'\nWEEK RESULTS: {len(df_trades)} trades')
        print(f'Win Rate: {wins/len(df_trades)*100:.1f}%')
        print(f'Total P&L: {total_pnl:+.2f}%')
        print(f'Avg P&L: {total_pnl/len(df_trades):.3f}%')
        print(f'Exit Types: TP={tp_exits} | SL={sl_exits} | TIME={time_exits}')
    else:
        print('\nNo trades found')
    print('='*80)

if __name__ == '__main__':
    run_backtest()
