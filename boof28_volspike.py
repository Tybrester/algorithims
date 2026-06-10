"""
BOOF 28 - 1-Minute Volume Spike System
vol_ratio = current_1m_volume / avg_volume_same_minute_60d
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    "AMD","INTC","QCOM","JPM","V","MA","BAC","UNH","JNJ","LLY",
    "WMT","COST","HD","PG","KO","XOM","CVX","GE","DIS","COIN",
    "GME","PLTR","SOFI","RBLX","BABA","JD","SPY","QQQ","IWM"
]

def get_1m_data(symbol, date, lookback=60):
    """Get 1m data with extended lookback for seasonal volume calc"""
    start = date - timedelta(days=lookback)
    end = date + timedelta(days=1)
    df = fetch_alpaca_bars(symbol, start, end, '1Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 10:
        return None
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    return df

def calculate_same_minute_avg_volume(df, target_date, minutes_back=60):
    """
    Calculate average volume for each minute of day across lookback period.
    For each bar, find same time-of-day bars in historical data.
    """
    # Get historical data (excluding target date)
    df['time'] = df['timestamp'].dt.time
    df['date'] = df['timestamp'].dt.date
    
    # Group by time of day and calculate average
    time_groups = df[df['date'] != target_date.date()].groupby('time')['volume'].mean()
    
    # Map back to each row
    avg_volumes = []
    for idx, row in df.iterrows():
        t = row['time']
        if t in time_groups:
            avg_volumes.append(time_groups[t])
        else:
            avg_volumes.append(row['volume'])  # Fallback
    
    return pd.Series(avg_volumes, index=df.index)

def stage1_detect_volume_spikes(df, target_date, vol_threshold=3.0):
    """
    STAGE 1: Volume Anomaly Detection
    
    vol_ratio = current_1m_volume / avg_volume_same_minute_60d
    spike = vol_ratio >= 3.0
    
    Only check first 45 minutes (9:30-10:15) = bars 0-44
    """
    if len(df) < 10:
        return None
    
    # Calculate seasonal average
    avg_vol_same_minute = calculate_same_minute_avg_volume(df, target_date)
    
    # Filter to target date and first 45 min
    day_df = df[df['timestamp'].dt.date == target_date.date()].reset_index(drop=True)
    
    if len(day_df) == 0:
        return None
    
    avg_vol_same_minute = avg_vol_same_minute[df['timestamp'].dt.date == target_date.date()].reset_index(drop=True)
    
    spikes = []
    
    # Check first 45 bars (9:30-10:15)
    for i in range(min(45, len(day_df))):
        if pd.isna(avg_vol_same_minute.iloc[i]) or avg_vol_same_minute.iloc[i] == 0:
            continue
        
        current_vol = day_df['volume'].iloc[i]
        avg_vol = avg_vol_same_minute.iloc[i]
        vol_ratio = current_vol / avg_vol
        
        if vol_ratio >= vol_threshold:
            spikes.append({
                'spike_idx': i,
                'time': day_df['timestamp'].iloc[i],
                'vol_ratio': vol_ratio,
                'volume': current_vol,
                'avg_volume': avg_vol,
                'price': day_df['close'].iloc[i],
                'df': day_df
            })
    
    return spikes if spikes else None

def stage2_five_min_confirmation(spike):
    """
    STAGE 2: 5-Minute Confirmation
    
    after_5min_return = (close_5min_later - spike_close) / spike_close
    
    SHORT: spike and after_5min_return <= -0.002 (0.20% down)
    LONG: spike and after_5min_return >= 0.002 (0.20% up)
    """
    df = spike['df']
    spike_idx = spike['spike_idx']
    spike_price = spike['price']
    
    # Need 5 more bars
    if spike_idx + 5 >= len(df):
        return None
    
    price_5min_later = df['close'].iloc[spike_idx + 5]
    after_5min_return = (price_5min_later - spike_price) / spike_price
    
    direction = None
    if after_5min_return <= -0.002:
        direction = 'SHORT'
    elif after_5min_return >= 0.002:
        direction = 'LONG'
    
    if direction:
        return {
            'direction': direction,
            'entry_idx': spike_idx + 5,
            'entry_price': price_5min_later,
            'spike_return': after_5min_return * 100
        }
    
    return None

def stage3_4_simulate(df, entry_idx, direction, target_pct=1.0, stop_pct=0.5, max_bars=15):
    """
    STAGE 3: Entry
    STAGE 4: Exit on TP/SL/Time
    
    Fixed targets: 1% TP, 0.5% SL, 15 bar max (15 min)
    """
    if entry_idx >= len(df) - 1:
        return None, None
    
    entry_price = df['close'].iloc[entry_idx]
    
    if direction == 'SHORT':
        tp = entry_price * (1 - target_pct/100)
        sl = entry_price * (1 + stop_pct/100)
        
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df))):
            if df['low'].iloc[i] <= tp:
                return target_pct, 'TP'
            if df['high'].iloc[i] >= sl:
                return -stop_pct, 'SL'
    
    else:  # LONG
        tp = entry_price * (1 + target_pct/100)
        sl = entry_price * (1 - stop_pct/100)
        
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df))):
            if df['high'].iloc[i] >= tp:
                return target_pct, 'TP'
            if df['low'].iloc[i] <= sl:
                return -stop_pct, 'SL'
    
    # Time exit
    exit_price = df['close'].iloc[min(entry_idx + max_bars - 1, len(df) - 1)]
    if direction == 'SHORT':
        return (entry_price - exit_price) / entry_price * 100, 'TIME'
    else:
        return (exit_price - entry_price) / entry_price * 100, 'TIME'

def run_scanner():
    test_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
    
    print('='*80)
    print('BOOF 28 - 1-MINUTE VOLUME SPIKE SCANNER')
    print('vol_ratio = current_1m_volume / avg_volume_same_minute_60d')
    print('Stage 1: Volume anomaly (3x spike)')
    print('Stage 2: 5-min confirmation (0.20% move)')
    print('Stage 3-4: Entry + Exit (1% TP / 0.5% SL)')
    print(f'Date: {test_date.date()}')
    print('='*80)
    
    print(f'\nScanning {len(UNIVERSE)} stocks...\n')
    
    all_results = []
    
    for sym in UNIVERSE:
        try:
            df = get_1m_data(sym, test_date, lookback=60)
            if df is None:
                continue
            
            # STAGE 1: Volume spikes
            spikes = stage1_detect_volume_spikes(df, test_date, vol_threshold=3.0)
            if not spikes:
                continue
            
            for spike in spikes[:3]:  # Max 3 spikes per stock
                # STAGE 2: 5-min confirmation
                confirmation = stage2_five_min_confirmation(spike)
                if not confirmation:
                    continue
                
                # STAGE 3-4: Entry and simulate
                pnl, exit_type = stage3_4_simulate(
                    spike['df'],
                    confirmation['entry_idx'],
                    confirmation['direction']
                )
                
                if pnl is not None:
                    all_results.append({
                        'symbol': sym,
                        'spike_time': spike['time'].strftime('%H:%M'),
                        'spike_vol_ratio': spike['vol_ratio'],
                        'direction': confirmation['direction'],
                        'spike_return_5min': confirmation['spike_return'],
                        'entry_price': confirmation['entry_price'],
                        'pnl': pnl,
                        'exit': exit_type
                    })
            
            time.sleep(0.05)
        except Exception as e:
            pass
    
    print('='*80)
    
    if all_results:
        wins = len([r for r in all_results if r['pnl'] > 0])
        total_pnl = sum(r['pnl'] for r in all_results)
        
        print(f'\nRESULTS: {len(all_results)} trades')
        print(f'Win Rate: {wins/len(all_results)*100:.1f}%')
        print(f'Total P&L: {total_pnl:+.2f}%')
        print(f'Avg P&L: {total_pnl/len(all_results):.3f}%')
        
        shorts = [r for r in all_results if r['direction'] == 'SHORT']
        longs = [r for r in all_results if r['direction'] == 'LONG']
        
        if shorts:
            short_pnl = sum(r['pnl'] for r in shorts)
            print(f'\nSHORTS: {len(shorts)} trades, {short_pnl:+.2f}%')
        if longs:
            long_pnl = sum(r['pnl'] for r in longs)
            print(f'LONGS: {len(longs)} trades, {long_pnl:+.2f}%')
        
        print(f"\n{'Sym':<6} {'Time':<6} {'VolRatio':>8} {'Dir':<6} {'5minRet':>8} {'Entry':>10} {'P&L':>8} {'Exit':<6}")
        print('-'*75)
        for r in all_results[:20]:  # Show first 20
            print(f"{r['symbol']:<6} {r['spike_time']:<6} {r['spike_vol_ratio']:>8.1f}x "
                  f"{r['direction']:<6} {r['spike_return_5min']:>+7.2f}% "
                  f"${r['entry_price']:>9.2f} {r['pnl']:>+7.2f}% {r['exit']:<6}")
        
        if len(all_results) > 20:
            print(f'... and {len(all_results) - 20} more trades')
    else:
        print('\nNo volume spikes met confirmation criteria')
    
    print('='*80)

if __name__ == '__main__':
    run_scanner()
