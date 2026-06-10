"""BOOF 24 ORB - Quick 6 Month Backtest"""
import alpaca_trade_api as tradeapi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Alpaca credentials
ALPACA_API_KEY = "AKAQMRBMRXN6676IET6N5VOCTH"
ALPACA_SECRET_KEY = "AbAnxL7xjfZH5MiTYZcjFnL3YkqxnYTNnwkJpnHWGBiC"
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

# Config matching TypeScript
ORB_MINUTES = 15  # 9:30-9:45 ET
VOL_LOOKBACK = 20
REL_VOL_MIN = 0.50  # No volume filter - just need some volume
TP_PCT = 0.01   # 1% take profit
SL_PCT = 0.005  # 0.5% stop loss (2:1 RR)

SYMBOLS = ['SPY', 'QQQ', 'NVDA', 'META', 'AAPL', 'TSLA']

def compute_vwap(df):
    """Calculate VWAP"""
    typical = (df['high'] + df['low'] + df['close']) / 3
    cumtpv = (typical * df['volume']).cumsum()
    cumvol = df['volume'].cumsum()
    return cumtpv / cumvol

def calc_rel_volume(df, idx, lookback=20):
    """Relative volume"""
    if idx < lookback:
        return 1.0
    avg_vol = df['volume'].iloc[idx-lookback:idx].mean()
    if avg_vol == 0:
        return 1.0
    return df['volume'].iloc[idx] / avg_vol

def is_orb_time(timestamp, orb_minutes=15):
    """Check if within ORB window (9:30-9:45 ET)
    Alpaca returns UTC timestamps. ET is UTC-4 (EDT) or UTC-5 (EST)"""
    # Convert to ET: UTC hour - 4 (EDT) or -5 (EST)
    # For simplicity, assume EDT (-4) which covers most trading days
    et_hour = timestamp.hour - 4
    et_minute = timestamp.minute
    # Handle day boundary cases (e.g., UTC hour 0-4 is previous day in ET)
    if et_hour < 0:
        et_hour += 24
    minutes_since_open = (et_hour - 9) * 60 + et_minute
    return 0 <= minutes_since_open < orb_minutes

def is_after_orb(timestamp, orb_minutes=15):
    """Check if after ORB but before close"""
    et_hour = timestamp.hour - 4
    et_minute = timestamp.minute
    if et_hour < 0:
        et_hour += 24
    minutes_since_open = (et_hour - 9) * 60 + et_minute
    return orb_minutes <= minutes_since_open < 390  # 6.5 hours

def get_market_trend(spy_df):
    """Get SPY trend from last 10 bars"""
    if len(spy_df) < 20:
        return 'neutral'
    recent = spy_df['close'].iloc[-10:].mean()
    earlier = spy_df['close'].iloc[-20:-10].mean()
    change = (recent - earlier) / earlier
    if change > 0.001:
        return 'up'
    if change < -0.001:
        return 'down'
    return 'neutral'

def backtest_orb(symbol, start_date, end_date, spy_df=None, debug=False):
    """Backtest ORB for one symbol"""
    trades = []
    orb_attempts = 0
    vol_fails = 0
    vwap_fails = 0
    trend_fails = 0
    
    try:
        # Fetch 5m data
        df = api.get_bars(
            symbol, '5Min',
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            limit=10000,
            feed='iex'
        ).df
        
        if len(df) < 50:
            if debug:
                print(f"  {symbol}: Not enough data ({len(df)} bars)")
            return trades
            
        df = df.reset_index()
        if 'timestamp' in df.columns:
            df['time'] = pd.to_datetime(df['timestamp'])
        elif 'index' in df.columns:
            df['time'] = pd.to_datetime(df['index'])
        
        df['vwap'] = compute_vwap(df)
        
        # Group by trading day
        df['date'] = df['time'].dt.date
        
        for date, day_df in df.groupby('date'):
            if len(day_df) < ORB_MINUTES + 5:
                continue
            
            # Check if first bar is near market open (9:30 AM ET = 13:30 UTC)
            first_bar_time = day_df['time'].iloc[0]
            first_bar_et_hour = first_bar_time.hour - 4
            if first_bar_et_hour < 0:
                first_bar_et_hour += 24
            
            # Skip if first bar is not near market open (9-10 AM ET)
            if not (9 <= first_bar_et_hour <= 10):
                continue
                
            # Calculate ORB range from first 15 bars
            orb_bars = day_df.iloc[:ORB_MINUTES]
            orb_high = orb_bars['high'].max()
            orb_low = orb_bars['low'].min()
            
            # After ORB - look for breakouts
            after_orb = day_df.iloc[ORB_MINUTES:]
            
            for i, (idx, row) in enumerate(after_orb.iterrows()):
                if i > 30:  # Only first 2.5 hours after ORB
                    break
                    
                price = row['close']
                vwap = row['vwap']
                
                # Check breakout
                break_above = price > orb_high
                break_below = price < orb_low
                
                if not break_above and not break_below:
                    continue
                
                orb_attempts += 1
                
                # Volume filter (DISABLED)
                # rel_vol = calc_rel_volume(df, idx, VOL_LOOKBACK)
                # if rel_vol < REL_VOL_MIN:
                #     vol_fails += 1
                #     continue
                
                # VWAP confirmation (DISABLED FOR RAW ORB TEST)
                # vwap_ok = (price > vwap and break_above) or (price < vwap and break_below)
                # if not vwap_ok:
                #     vwap_fails += 1
                #     continue
                
                # Market trend filter (DISABLED FOR RAW ORB TEST)
                # spy_trend = get_market_trend(spy_df) if spy_df is not None else 'neutral'
                # trend_ok = spy_trend == 'neutral' or (spy_trend == 'up' and break_above) or (spy_trend == 'down' and break_below)
                # if not trend_ok:
                #     trend_fails += 1
                #     continue
                
                # Enter trade
                direction = 'LONG' if break_above else 'SHORT'
                entry = price
                
                if debug and len(trades) < 5:
                    print(f"\n    ENTRY {direction} @ {entry:.2f} (ORB: {orb_low:.2f}-{orb_high:.2f})")
                
                # Simulate to exit
                remaining = after_orb.iloc[i+1:]
                
                if direction == 'LONG':
                    tp = entry * (1 + TP_PCT)
                    sl = entry * (1 - SL_PCT)
                    
                    for _, exit_row in remaining.iterrows():
                        if exit_row['high'] >= tp:
                            trades.append({'symbol': symbol, 'dir': 'LONG', 'entry': entry, 'exit': tp, 'pnl_pct': TP_PCT, 'r': 2.0})
                            break
                        elif exit_row['low'] <= sl:
                            trades.append({'symbol': symbol, 'dir': 'LONG', 'entry': entry, 'exit': sl, 'pnl_pct': -SL_PCT, 'r': -1.0})
                            break
                else:
                    tp = entry * (1 - TP_PCT)
                    sl = entry * (1 + SL_PCT)
                    
                    for _, exit_row in remaining.iterrows():
                        if exit_row['low'] <= tp:
                            trades.append({'symbol': symbol, 'dir': 'SHORT', 'entry': entry, 'exit': tp, 'pnl_pct': TP_PCT, 'r': 2.0})
                            break
                        elif exit_row['high'] >= sl:
                            trades.append({'symbol': symbol, 'dir': 'SHORT', 'entry': entry, 'exit': sl, 'pnl_pct': -SL_PCT, 'r': -1.0})
                            break
                
                break  # One trade per day max
                
    except Exception as e:
        print(f"  {symbol} error: {e}")
    
    if debug:
        return trades, {'attempts': orb_attempts, 'vol_fails': vol_fails, 'vwap_fails': vwap_fails, 'trend_fails': trend_fails}
    return trades

print("="*60)
print("BOOF 24 ORB - 6 MONTH BACKTEST")
print("="*60)

end = datetime.now()
start = end - timedelta(days=180)  # 6 months

print(f"Period: {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}")
print(f"Symbols: {', '.join(SYMBOLS)}")
print(f"ORB: First {ORB_MINUTES} minutes (9:30-9:45 ET)")
print(f"TP: {TP_PCT*100:.2f}%, SL: {SL_PCT*100:.2f}%")
print(f"Vol Filter: {REL_VOL_MIN}x avg")
print("="*60)

# Fetch SPY for trend filter
print("\nFetching SPY for trend filter...")
try:
    spy_df = api.get_bars(
        'SPY', '5Min',
        start=start.strftime('%Y-%m-%d'),
        end=end.strftime('%Y-%m-%d'),
        limit=10000,
        feed='iex'
    ).df
    spy_df = spy_df.reset_index()
    if 'timestamp' in spy_df.columns:
        spy_df['time'] = pd.to_datetime(spy_df['timestamp'])
    print(f"SPY: {len(spy_df)} bars")
except Exception as e:
    print(f"SPY fetch failed: {e}")
    spy_df = None

# Run backtests (first one with debug)
all_trades = []
debug_stats = {}
for i, sym in enumerate(SYMBOLS):
    print(f"\n{sym}...", end=' ')
    if i == 0:  # Debug first symbol
        trades, stats = backtest_orb(sym, start, end, spy_df, debug=True)
        debug_stats[sym] = stats
        print(f"{len(trades)} trades (orb_attempts={stats['attempts']}, vol_fails={stats['vol_fails']}, vwap_fails={stats['vwap_fails']}, trend_fails={stats['trend_fails']})")
    else:
        trades = backtest_orb(sym, start, end, spy_df)
        print(f"{len(trades)} trades")
    all_trades.extend(trades)

print("\n" + "="*60)
print("RESULTS")
print("="*60)

if all_trades:
    df_trades = pd.DataFrame(all_trades)
    wins = len(df_trades[df_trades['r'] > 0])
    total = len(df_trades)
    win_rate = wins / total * 100
    total_r = df_trades['r'].sum()
    avg_r = total_r / total
    
    print(f"\nTotal Trades: {total}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Total R: {total_r:.2f}")
    print(f"Avg R/Trade: {avg_r:.3f}")
    
    # By symbol
    print("\nBy Symbol:")
    for sym in SYMBOLS:
        sym_trades = df_trades[df_trades['symbol'] == sym]
        if len(sym_trades) > 0:
            sym_wins = len(sym_trades[sym_trades['r'] > 0])
            print(f"  {sym}: {len(sym_trades)} trades, {sym_wins/len(sym_trades)*100:.1f}% WR, {sym_trades['r'].sum():.2f}R")
    
    # By direction
    longs = df_trades[df_trades['dir'] == 'LONG']
    shorts = df_trades[df_trades['dir'] == 'SHORT']
    if len(longs) > 0:
        print(f"\nLongs: {len(longs)} trades, {len(longs[longs['r']>0])/len(longs)*100:.1f}% WR")
    if len(shorts) > 0:
        print(f"Shorts: {len(shorts)} trades, {len(shorts[shorts['r']>0])/len(shorts)*100:.1f}% WR")
else:
    print("No trades generated")

print("="*60)
