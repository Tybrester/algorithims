"""Quick 6-month sweep test only"""
import alpaca_trade_api as tradeapi
import pandas as pd
from datetime import datetime, timedelta

ALPACA_API_KEY = "AKAQMRBMRXN6676IET6N5VOCTH"
ALPACA_SECRET_KEY = "AbAnxL7xjfZH5MiTYZcjFnL3YkqxnYTNnwkJpnHWGBiC"
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

CORE_SYMBOLS = ['NVDA', 'TSLA', 'META', 'SPY', 'QQQ']

ORB_MINUTES = 15
SWEEP_LOOKBACK_BARS = 12
RECLAIM_BARS = 4
TP_PCT = 0.008
SL_PCT = 0.004
MAX_TIME_MINUTES = 90

def get_minutes_since_open(timestamp):
    month = timestamp.month
    is_dst = 3 <= month <= 11
    utc_offset = 4 if is_dst else 5
    et_hour = timestamp.hour - utc_offset
    et_minute = timestamp.minute
    if et_hour < 0:
        et_hour += 24
    return (et_hour - 9) * 60 + et_minute

def is_within_time_window(timestamp, max_minutes=90):
    mins = get_minutes_since_open(timestamp)
    return 0 <= mins < max_minutes

def compute_vwap(df):
    typical = (df['high'] + df['low'] + df['close']) / 3
    cumtpv = (typical * df['volume']).cumsum()
    cumvol = df['volume'].cumsum()
    return cumtpv / cumvol

def backtest_sweep_quick(symbol, start_date, end_date):
    trades = []
    stats = {'sweeps': 0, 'entered': 0}
    
    try:
        df = api.get_bars(
            symbol, '5Min',
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            limit=10000,
            feed='iex'
        ).df
        
        if len(df) < 50:
            return trades, stats
            
        df = df.reset_index()
        if 'timestamp' in df.columns:
            df['time'] = pd.to_datetime(df['timestamp'])
        elif 'index' in df.columns:
            df['time'] = pd.to_datetime(df['index'])
        
        df['vwap'] = compute_vwap(df)
        df['date'] = df['time'].dt.date
        
        print(f"{symbol}: {len(df)} bars, {len(df['date'].unique())} days")
        
        for date, day_df in df.groupby('date'):
            if len(day_df) < ORB_MINUTES + 10:
                continue
            
            # Check first bar is near market open (0-15 mins)
            first_mins = get_minutes_since_open(day_df['time'].iloc[0])
            if first_mins > 20:  # Skip if starts after 9:50
                continue
            
            orb_bars = day_df.iloc[:ORB_MINUTES]
            orb_high = orb_bars['high'].max()
            orb_low = orb_bars['low'].min()
            orb_mid = (orb_high + orb_low) / 2
            orb_range = orb_high - orb_low
            
            if orb_range / orb_mid < 0.002:
                continue
            
            post_orb = day_df.iloc[ORB_MINUTES:].reset_index(drop=True)
            if len(post_orb) < 5:
                continue
            
            # Look for sweep
            for i, (_, row) in enumerate(post_orb.iterrows()):
                if i >= SWEEP_LOOKBACK_BARS:
                    break
                if not is_within_time_window(row['time'], MAX_TIME_MINUTES):
                    continue
                
                # Sweep up (broke high, closed inside)
                if row['high'] > orb_high and row['close'] < orb_high:
                    stats['sweeps'] += 1
                    
                    # Look for entry in next bars
                    for j in range(i+1, min(i+1+RECLAIM_BARS, len(post_orb))):
                        entry_row = post_orb.iloc[j]
                        if not is_within_time_window(entry_row['time'], MAX_TIME_MINUTES):
                            continue
                        
                        if entry_row['close'] < orb_mid:
                            stats['entered'] += 1
                            # Simulate SHORT
                            tp = entry_row['close'] * (1 - TP_PCT)
                            sl = entry_row['close'] * (1 + SL_PCT)
                            
                            remaining = post_orb.iloc[j+1:]
                            for _, exit_row in remaining.iterrows():
                                if exit_row['low'] <= tp:
                                    trades.append({'symbol': symbol, 'dir': 'SHORT', 'r': 2.0, 'result': 'win'})
                                    break
                                elif exit_row['high'] >= sl:
                                    trades.append({'symbol': symbol, 'dir': 'SHORT', 'r': -1.0, 'result': 'loss'})
                                    break
                            break
                    break
                
                # Sweep down
                if row['low'] < orb_low and row['close'] > orb_low:
                    stats['sweeps'] += 1
                    
                    for j in range(i+1, min(i+1+RECLAIM_BARS, len(post_orb))):
                        entry_row = post_orb.iloc[j]
                        if not is_within_time_window(entry_row['time'], MAX_TIME_MINUTES):
                            continue
                        
                        if entry_row['close'] > orb_mid:
                            stats['entered'] += 1
                            # Simulate LONG
                            tp = entry_row['close'] * (1 + TP_PCT)
                            sl = entry_row['close'] * (1 - SL_PCT)
                            
                            remaining = post_orb.iloc[j+1:]
                            for _, exit_row in remaining.iterrows():
                                if exit_row['high'] >= tp:
                                    trades.append({'symbol': symbol, 'dir': 'LONG', 'r': 2.0, 'result': 'win'})
                                    break
                                elif exit_row['low'] <= sl:
                                    trades.append({'symbol': symbol, 'dir': 'LONG', 'r': -1.0, 'result': 'loss'})
                                    break
                            break
                    break
                    
    except Exception as e:
        print(f"  {symbol} error: {e}")
        
    return trades, stats

# Run 6-month test
print("="*60)
print("QUICK 6-MONTH LIQUIDITY SWEEP TEST")
print("="*60)

end = datetime.now()
start = end - timedelta(days=180)

print(f"\nPeriod: {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}")
print(f"Symbols: {', '.join(CORE_SYMBOLS)}")
print("-"*60)

all_trades = []
total_stats = {'sweeps': 0, 'entered': 0}

for sym in CORE_SYMBOLS:
    trades, stats = backtest_sweep_quick(sym, start, end)
    all_trades.extend(trades)
    total_stats['sweeps'] += stats['sweeps']
    total_stats['entered'] += stats['entered']
    
    wins = len([t for t in trades if t['r'] > 0])
    total_r = sum(t['r'] for t in trades)
    print(f"{sym}: {len(trades)} trades | {wins}/{len(trades)} wins | {total_r:+.1f}R")

# Totals
print("-"*60)
wins = len([t for t in all_trades if t['r'] > 0])
total_r = sum(t['r'] for t in all_trades)
pf = (wins * 2.0) / ((len(all_trades) - wins) * 1.0) if (len(all_trades) - wins) > 0 else 0
wr = wins / len(all_trades) * 100 if all_trades else 0

print(f"\nTOTAL: {len(all_trades)} trades | {total_stats['sweeps']} sweeps | {total_stats['entered']} entries")
print(f"Win Rate: {wr:.1f}% | PF: {pf:.2f} | R: {total_r:+.1f}")
