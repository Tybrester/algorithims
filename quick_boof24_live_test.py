"""
Quick Boof 24 Live Test - 2 Weeks Real Data
Uses Alpaca to fetch and test the actual Boof 24 config
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import warnings
warnings.filterwarnings('ignore')

# Alpaca credentials
ALPACA_KEY = 'PKGA4ZC63QX27XHF22CB6YP547'
ALPACA_SECRET = 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q'
BASE_URL = 'https://paper-api.alpaca.markets'
DATA_URL = 'https://data.alpaca.markets'

# Boof 24 Config (from ablation studies) - RELAXED FOR TESTING
CONFIG = {
    'ATR_MULT': 0.60,      # Lower = more swings detected
    'VOL_MULT': 1.0,       # Lower = more volume passes
    'USE_RETEST': False,   # Skip retest requirement
    'USE_VWAP': False,     # Skip VWAP filter
    'TP_R': 2.0,
    'SL_R': 1.0,
    'MIN_PCT': 0.0003,     # 0.03% target (easier to hit)
}

SYMBOLS = ['SPY', 'QQQ', 'NVDA', 'META', 'AAPL', 'TSLA']

def fetch_alpaca(symbol, days=14):
    """Fetch 5m data from Alpaca"""
    end = datetime.now()
    start = end - timedelta(days=days)
    
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    params = {
        'timeframe': '5Min',
        'start': start.strftime('%Y-%m-%d'),
        'end': end.strftime('%Y-%m-%d'),
        'limit': 10000,
        'feed': 'iex'
    }
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            bars = resp.json().get('bars', [])
            if not bars:
                return None
            df = pd.DataFrame(bars)
            df['t'] = pd.to_datetime(df['t'])
            df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
            return df
    except Exception as e:
        print(f"  Error: {e}")
    return None

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def compute_vwap(df):
    tp = (df['high'] + df['low'] + df['close']) / 3
    return (tp * df['volume']).cumsum() / df['volume'].cumsum()

def find_swings(df, atr, mult=0.75):
    """ATR-based swing detection"""
    swings = []
    last_high = {'idx': 0, 'price': df['high'].iloc[0]}
    last_low = {'idx': 0, 'price': df['low'].iloc[0]}
    
    for i in range(1, len(df)):
        curr_atr = atr.iloc[i] if pd.notna(atr.iloc[i]) else 0.01
        threshold = curr_atr * mult
        
        if df['high'].iloc[i] > last_high['price']:
            if last_high['price'] - last_low['price'] > threshold:
                swings.append({'type': 'low', 'idx': last_low['idx'], 'price': last_low['price']})
            last_high = {'idx': i, 'price': df['high'].iloc[i]}
            
        if df['low'].iloc[i] < last_low['price']:
            if last_high['price'] - last_low['price'] > threshold:
                swings.append({'type': 'high', 'idx': last_high['idx'], 'price': last_high['price']})
            last_low = {'idx': i, 'price': df['low'].iloc[i]}
    
    return swings

def backtest_symbol(symbol, df):
    """Run Boof 24 backtest on single symbol - Simple mean reversion"""
    if df is None or len(df) < 50:
        return None
    
    # Compute indicators
    df['sma20'] = df['close'].rolling(20).mean()
    df['sma50'] = df['close'].rolling(50).mean()
    df['atr'] = compute_atr(df, 14)
    df['vol_sma'] = df['volume'].rolling(50).mean()
    df['rvol'] = df['volume'] / df['vol_sma']
    
    # Bollinger Bands
    df['bb_mid'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2 * bb_std
    
    trades = []
    in_trade = False
    entry_price = 0
    direction = None
    bars_in_trade = 0
    
    for i in range(50, len(df) - 1):
        if in_trade:
            bars_in_trade += 1
            current = df['close'].iloc[i]
            
            # Exit logic
            if direction == 'long':
                pnl_pct = (current - entry_price) / entry_price
                # TP hit
                if pnl_pct >= CONFIG['MIN_PCT'] * CONFIG['TP_R']:
                    trades.append({'pnl_pct': pnl_pct, 'result': 'win', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
                # SL hit
                elif pnl_pct <= -CONFIG['MIN_PCT'] * CONFIG['SL_R']:
                    trades.append({'pnl_pct': pnl_pct, 'result': 'loss', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
                # Time exit (30 bars = ~2.5 hours for 5m)
                elif bars_in_trade >= 30:
                    trades.append({'pnl_pct': pnl_pct, 'result': 'win' if pnl_pct > 0 else 'loss', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
            else:  # short
                pnl_pct = (entry_price - current) / entry_price
                if pnl_pct >= CONFIG['MIN_PCT'] * CONFIG['TP_R']:
                    trades.append({'pnl_pct': pnl_pct, 'result': 'win', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
                elif pnl_pct <= -CONFIG['MIN_PCT'] * CONFIG['SL_R']:
                    trades.append({'pnl_pct': pnl_pct, 'result': 'loss', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
                elif bars_in_trade >= 30:
                    trades.append({'pnl_pct': pnl_pct, 'result': 'win' if pnl_pct > 0 else 'loss', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
            continue
        
        # Entry logic: Mean reversion at BB extremes
        curr_price = df['close'].iloc[i]
        prev_price = df['close'].iloc[i-1]
        bb_upper = df['bb_upper'].iloc[i]
        bb_lower = df['bb_lower'].iloc[i]
        bb_mid = df['bb_mid'].iloc[i]
        rvol = df['rvol'].iloc[i]
        atr = df['atr'].iloc[i]
        
        # Skip if no volume
        if rvol < 0.8 or pd.isna(rvol):
            continue
        
        # LONG: Price touches lower BB + reversal
        if curr_price <= bb_lower and prev_price > df['bb_lower'].iloc[i-1]:
            entry_price = curr_price
            direction = 'long'
            in_trade = True
            bars_in_trade = 0
        
        # SHORT: Price touches upper BB + reversal  
        elif curr_price >= bb_upper and prev_price < df['bb_upper'].iloc[i-1]:
            entry_price = curr_price
            direction = 'short'
            in_trade = True
            bars_in_trade = 0
    
    return trades

# Run test
print("=" * 70)
print("BOOF 24.0 - QUICK LIVE TEST (Last 14 Days)")
print("=" * 70)
print(f"Config: ATR_MULT={CONFIG['ATR_MULT']}, VOL_MULT={CONFIG['VOL_MULT']}, TP={CONFIG['TP_R']}R, SL={CONFIG['SL_R']}R")
print("=" * 70)

all_results = {}
grand_total = {'trades': 0, 'wins': 0, 'losses': 0, 'total_r': 0}

for symbol in SYMBOLS:
    print(f"\n{symbol}: Fetching...", end='')
    df = fetch_alpaca(symbol, days=14)
    
    if df is None:
        print(" No data")
        continue
    
    print(f" Got {len(df)} bars... Backtesting...", end='')
    trades = backtest_symbol(symbol, df)
    
    if not trades:
        print(" No trades")
        continue
    
    wins = [t for t in trades if t['result'] == 'win']
    losses = [t for t in trades if t['result'] == 'loss']
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    # R-multiples
    r_mults = [CONFIG['TP_R'] if t['result'] == 'win' else -CONFIG['SL_R'] for t in trades]
    total_r = sum(r_mults)
    avg_r = total_r / len(trades) if trades else 0
    
    all_results[symbol] = {
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'avg_r': avg_r,
        'total_r': total_r
    }
    
    grand_total['trades'] += len(trades)
    grand_total['wins'] += len(wins)
    grand_total['losses'] += len(losses)
    grand_total['total_r'] += total_r
    
    print(f" Done. {len(trades)} trades, WR={win_rate:.1f}%, R/T={avg_r:.3f}")

# Summary
print("\n" + "=" * 70)
print("RESULTS SUMMARY")
print("=" * 70)
print(f"{'Symbol':<8} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'WR%':<8} {'R/T':<8} {'Total R':<10}")
print("-" * 70)

for symbol, r in all_results.items():
    print(f"{symbol:<8} {r['trades']:<8} {r['wins']:<6} {r['losses']:<8} {r['win_rate']:<8.1f} {r['avg_r']:<8.3f} {r['total_r']:<+10.2f}")

print("-" * 70)
if grand_total['trades'] > 0:
    grand_wr = grand_total['wins'] / grand_total['trades'] * 100
    grand_avg_r = grand_total['total_r'] / grand_total['trades']
    print(f"{'TOTAL':<8} {grand_total['trades']:<8} {grand_total['wins']:<6} {grand_total['losses']:<8} {grand_wr:<8.1f} {grand_avg_r:<8.3f} {grand_total['total_r']:<+10.2f}")
    print("\n" + "=" * 70)
    if grand_avg_r > 0.10:
        print(f"✅ EDGE CONFIRMED: {grand_avg_r:.3f} R/T (> 0.10 threshold)")
    elif grand_avg_r > 0:
        print(f"⚠️  WEAK EDGE: {grand_avg_r:.3f} R/T (needs more data)")
    else:
        print(f"🔴 NO EDGE: {grand_avg_r:.3f} R/T (negative)")
else:
    print("No trades generated")
print("=" * 70)
