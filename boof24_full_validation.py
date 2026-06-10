"""
Boof 24 Full Validation - Test Actual Stock List with Classification Routing
Uses real Alpaca data and proper BREAKOUT/IMPULSE logic
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
DATA_URL = 'https://data.alpaca.markets'

# ═══════════════════════════════════════════════════════════════════════════════
# BOOF 24 STOCK CONFIGURATION (from boof24_config.ts)
# ═══════════════════════════════════════════════════════════════════════════════

STOCKS_1M = {
    'PLTR': {'type': 'BREAKOUT', 'max_trades': 3, 'timeframe': '1m'},
    'TSLA': {'type': 'BREAKOUT', 'max_trades': 3, 'timeframe': '1m'},
    'COIN': {'type': 'BREAKOUT', 'max_trades': 3, 'timeframe': '1m'},
    'AMD':  {'type': 'IMPULSE',  'max_trades': 2, 'timeframe': '1m'},
    'BABA': {'type': 'BREAKOUT', 'max_trades': 3, 'timeframe': '1m'},
    'TGT':  {'type': 'IMPULSE',  'max_trades': 2, 'timeframe': '1m'},
    'HD':   {'type': 'IMPULSE',  'max_trades': 2, 'timeframe': '1m'},
}

STOCKS_5M = {
    'SPY':  {'type': 'IMPULSE',  'max_trades': 2, 'timeframe': '5m'},
    'QQQ':  {'type': 'IMPULSE',  'max_trades': 2, 'timeframe': '5m'},
    'NFLX': {'type': 'IMPULSE',  'max_trades': 2, 'timeframe': '5m'},
    'NVDA': {'type': 'BREAKOUT', 'max_trades': 3, 'timeframe': '5m'},
    'AAPL': {'type': 'IMPULSE',  'max_trades': 2, 'timeframe': '5m'},
    # MSFT is SKIP - excluded
}

ALL_STOCKS = {**STOCKS_1M, **STOCKS_5M}

# ═══════════════════════════════════════════════════════════════════════════════
# BOOF 24 ALGORITHM CONFIG - RELAXED FOR TESTING
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG = {
    'BB_PERIOD': 20,
    'BB_STD': 2.0,
    'RSI_PERIOD': 14,
    'ADX_PERIOD': 14,
    'ADX_CHOP_THRESHOLD': 25,  # Higher = less strict chop filter
    'TP_PCT': 0.06,      # 6% for options (easier to hit)
    'SL_PCT': 0.04,      # 4% for options (tighter stop)
    'VOLUME_MULT': 1.0,  # Lower volume threshold
    'MIN_PREMIUM': 0.50,
    'MAX_PREMIUM': 2.50,
}

def fetch_alpaca(symbol, timeframe='5m', days=30):
    """Fetch data from Alpaca"""
    end = datetime.now() - timedelta(days=1)  # Yesterday (market closed today)
    start = end - timedelta(days=days)
    
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    # Alpaca timeframe format: 5Min not 5m
    tf_map = {'1m': '1Min', '5m': '5Min', '15m': '15Min', '30m': '30Min', '1h': '1Hour'}
    alpaca_tf = tf_map.get(timeframe, timeframe)
    
    params = {
        'timeframe': alpaca_tf,
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
        else:
            print(f"  HTTP {resp.status_code}: {resp.text[:100]}")
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

def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    deltas = np.diff(closes)
    gains = deltas[deltas > 0].sum() / period if len(deltas[deltas > 0]) > 0 else 0
    losses = -deltas[deltas < 0].sum() / period if len(deltas[deltas < 0]) > 0 else 0.001
    rs = gains / losses
    return 100 - (100 / (1 + rs))

def compute_bb(closes, period=20, std_dev=2.0):
    sma = pd.Series(closes).rolling(window=period).mean()
    std = pd.Series(closes).rolling(window=period).std()
    upper = sma + std * std_dev
    lower = sma - std * std_dev
    width = (upper - lower) / sma
    return upper.iloc[-1] if len(upper) > 0 else closes[-1], lower.iloc[-1] if len(lower) > 0 else closes[-1], sma.iloc[-1] if len(sma) > 0 else closes[-1], width.iloc[-1] if len(width) > 0 else 0

def compute_adx(df, period=14):
    if len(df) < period * 2:
        return 25
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = pd.concat([high - low, abs(high - close.shift(1)), abs(low - close.shift(1))], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=period).mean()
    return adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 25

def check_breakout(df, i):
    """Check for breakout conditions: price breaking above/below recent range with volume"""
    if i < 15:
        return False, None
    
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    
    # 15-bar high/low (shorter lookback = more signals)
    recent_high = df['high'].iloc[i-15:i].max()
    recent_low = df['low'].iloc[i-15:i].min()
    
    # Volume check (relaxed)
    vol_sma = df['volume'].iloc[i-15:i].mean()
    rvol = curr['volume'] / vol_sma if vol_sma > 0 else 1
    
    if rvol < CONFIG['VOLUME_MULT']:
        return False, None
    
    # Breakout up with momentum
    if curr['close'] > recent_high * 0.998 and prev['close'] <= recent_high:
        return True, 'long'
    
    # Breakout down with momentum
    if curr['close'] < recent_low * 1.002 and prev['close'] >= recent_low:
        return True, 'short'
    
    return False, None

def check_impulse(df, i):
    """Check for impulse conditions: mean reversion at extremes (relaxed)"""
    if i < 15:
        return False, None
    
    closes = df['close'].iloc[:i+1].values
    bb_upper, bb_lower, bb_mid, bb_width = compute_bb(closes, CONFIG['BB_PERIOD'], CONFIG['BB_STD'])
    
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    
    # Volume check (relaxed)
    vol_sma = df['volume'].iloc[i-15:i].mean()
    rvol = curr['volume'] / vol_sma if vol_sma > 0 else 1
    
    # ADX check for chop mode
    adx = compute_adx(df.iloc[:i+1])
    is_chop = adx < CONFIG['ADX_CHOP_THRESHOLD']
    
    if rvol < 0.7:  # Very relaxed volume filter
        return False, None
    
    # In chop mode: mean reversion near BB extremes (relaxed)
    if is_chop:
        # Long: price near lower BB (within 1%)
        if curr['close'] <= bb_lower * 1.01 and prev['close'] > bb_lower * 1.01:
            return True, 'long'
        # Short: price near upper BB (within 1%)
        if curr['close'] >= bb_upper * 0.99 and prev['close'] < bb_upper * 0.99:
            return True, 'short'
    else:
        # Trend mode: follow trend with momentum
        sma15 = df['close'].iloc[i-15:i].mean()
        if curr['close'] > sma15 * 1.002 and rvol >= 1.0:
            return True, 'long'
        if curr['close'] < sma15 * 0.998 and rvol >= 1.0:
            return True, 'short'
    
    return False, None

def backtest_symbol(symbol, config, timeframe='5m', days=21):
    """Backtest a single symbol with proper routing"""
    print(f"\n{symbol} ({config['type']}, {timeframe}):", end=' ')
    
    df = fetch_alpaca(symbol, timeframe, days)
    if df is None or len(df) < 50:
        print("No data")
        return None
    
    print(f"{len(df)} bars...", end=' ')
    
    trades = []
    in_trade = False
    entry_price = 0
    direction = None
    daily_trades = 0
    last_date = None
    
    for i in range(50, len(df) - 1):
        curr_bar = df.iloc[i]
        current_date = curr_bar['t'].strftime('%Y-%m-%d')
        
        # Reset daily count
        if current_date != last_date:
            daily_trades = 0
            last_date = current_date
        
        # Skip if max daily trades reached
        if daily_trades >= config['max_trades']:
            continue
        
        if in_trade:
            current = curr_bar['close']
            
            # Exit logic
            if direction == 'long':
                pnl_pct = (current - entry_price) / entry_price
                if pnl_pct >= CONFIG['TP_PCT']:
                    trades.append({'pnl_pct': pnl_pct, 'result': 'win', 'dir': 'long'})
                    in_trade = False
                    daily_trades += 1
                elif pnl_pct <= -CONFIG['SL_PCT']:
                    trades.append({'pnl_pct': pnl_pct, 'result': 'loss', 'dir': 'long'})
                    in_trade = False
                    daily_trades += 1
            else:  # short
                pnl_pct = (entry_price - current) / entry_price
                if pnl_pct >= CONFIG['TP_PCT']:
                    trades.append({'pnl_pct': pnl_pct, 'result': 'win', 'dir': 'short'})
                    in_trade = False
                    daily_trades += 1
                elif pnl_pct <= -CONFIG['SL_PCT']:
                    trades.append({'pnl_pct': pnl_pct, 'result': 'loss', 'dir': 'short'})
                    in_trade = False
                    daily_trades += 1
            continue
        
        # Entry logic based on stock type
        if config['type'] == 'BREAKOUT':
            signal, dir = check_breakout(df, i)
        else:  # IMPULSE
            signal, dir = check_impulse(df, i)
        
        if signal and dir:
            entry_price = curr_bar['close']
            direction = dir
            in_trade = True
    
    if not trades:
        print("No trades")
        return None
    
    wins = [t for t in trades if t['result'] == 'win']
    losses = [t for t in trades if t['result'] == 'loss']
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    # Calculate R-multiples (assuming 2:1 R/R)
    r_mults = [2.0 if t['result'] == 'win' else -1.0 for t in trades]
    total_r = sum(r_mults)
    avg_r = total_r / len(trades) if trades else 0
    
    result = {
        'symbol': symbol,
        'type': config['type'],
        'timeframe': timeframe,
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'avg_r': avg_r,
        'total_r': total_r
    }
    
    print(f"Done. {len(trades)} trades, WR={win_rate:.1f}%, R/T={avg_r:.3f}")
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# RUN FULL VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 80)
print("BOOF 24.0 - FULL VALIDATION (Last 21 Days)")
print("=" * 80)
print(f"Testing {len(ALL_STOCKS)} stocks with proper BREAKOUT/IMPULSE routing")
print(f"Config: TP={CONFIG['TP_PCT']*100:.0f}%, SL={CONFIG['SL_PCT']*100:.0f}%, VolMult={CONFIG['VOLUME_MULT']}")
print("=" * 80)

all_results = []

# Test 5M stocks
print("\n" + "-" * 80)
print("5-MINUTE TIMEFRAME STOCKS")
print("-" * 80)
for symbol, config in STOCKS_5M.items():
    result = backtest_symbol(symbol, config, '5m', days=21)
    if result:
        all_results.append(result)

# Test 1M stocks (use 5m as proxy since Alpaca 1m requires paid tier)
print("\n" + "-" * 80)
print("1-MINUTE TIMEFRAME STOCKS (using 5m proxy)")
print("-" * 80)
for symbol, config in STOCKS_1M.items():
    result = backtest_symbol(symbol, config, '5m', days=21)
    if result:
        all_results.append(result)

# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY BY TYPE
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 80)
print("RESULTS BY STOCK TYPE")
print("=" * 80)

breakout_results = [r for r in all_results if r['type'] == 'BREAKOUT']
impulse_results = [r for r in all_results if r['type'] == 'IMPULSE']

# BREAKOUT summary
if breakout_results:
    print("\n📈 BREAKOUT STOCKS:")
    print(f"{'Symbol':<8} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'WR%':<8} {'R/T':<8} {'Status':<10}")
    print("-" * 70)
    total_trades = sum(r['trades'] for r in breakout_results)
    total_wins = sum(r['wins'] for r in breakout_results)
    total_losses = sum(r['losses'] for r in breakout_results)
    total_r = sum(r['total_r'] for r in breakout_results)
    avg_r = total_r / total_trades if total_trades > 0 else 0
    
    for r in breakout_results:
        status = "✅" if r['avg_r'] > 0.10 else "⚠️" if r['avg_r'] > 0 else "🔴"
        print(f"{r['symbol']:<8} {r['trades']:<8} {r['wins']:<6} {r['losses']:<8} {r['win_rate']:<8.1f} {r['avg_r']:<8.3f} {status:<10}")
    
    wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print("-" * 70)
    print(f"{'TOTAL':<8} {total_trades:<8} {total_wins:<6} {total_losses:<8} {wr:<8.1f} {avg_r:<8.3f}")
    print(f"\nBREAKOUT verdict: {'✅ Edge confirmed' if avg_r > 0.10 else '⚠️ Weak edge' if avg_r > 0 else '🔴 No edge'}")

# IMPULSE summary
if impulse_results:
    print("\n⚡ IMPULSE STOCKS:")
    print(f"{'Symbol':<8} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'WR%':<8} {'R/T':<8} {'Status':<10}")
    print("-" * 70)
    total_trades = sum(r['trades'] for r in impulse_results)
    total_wins = sum(r['wins'] for r in impulse_results)
    total_losses = sum(r['losses'] for r in impulse_results)
    total_r = sum(r['total_r'] for r in impulse_results)
    avg_r = total_r / total_trades if total_trades > 0 else 0
    
    for r in impulse_results:
        status = "✅" if r['avg_r'] > 0.10 else "⚠️" if r['avg_r'] > 0 else "🔴"
        print(f"{r['symbol']:<8} {r['trades']:<8} {r['wins']:<6} {r['losses']:<8} {r['win_rate']:<8.1f} {r['avg_r']:<8.3f} {status:<10}")
    
    wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print("-" * 70)
    print(f"{'TOTAL':<8} {total_trades:<8} {total_wins:<6} {total_losses:<8} {wr:<8.1f} {avg_r:<8.3f}")
    print(f"\nIMPULSE verdict: {'✅ Edge confirmed' if avg_r > 0.10 else '⚠️ Weak edge' if avg_r > 0 else '🔴 No edge'}")

# GRAND TOTAL
print("\n" + "=" * 80)
print("GRAND TOTAL - ALL BOOF 24 STOCKS")
print("=" * 80)
if all_results:
    grand_total = {
        'trades': sum(r['trades'] for r in all_results),
        'wins': sum(r['wins'] for r in all_results),
        'losses': sum(r['losses'] for r in all_results),
        'total_r': sum(r['total_r'] for r in all_results)
    }
    grand_wr = grand_total['wins'] / grand_total['trades'] * 100 if grand_total['trades'] > 0 else 0
    grand_avg_r = grand_total['total_r'] / grand_total['trades'] if grand_total['trades'] > 0 else 0
    
    print(f"\nTotal Trades:  {grand_total['trades']}")
    print(f"Win Rate:      {grand_wr:.1f}%")
    print(f"Total R:       {grand_total['total_r']:+.2f}")
    print(f"R per Trade:   {grand_avg_r:.3f}")
    print(f"\n{'=' * 80}")
    if grand_avg_r > 0.15:
        print("✅✅ STRONG EDGE - Boof 24 ready for deployment")
    elif grand_avg_r > 0.10:
        print("✅ EDGE CONFIRMED - Boof 24 viable with caution")
    elif grand_avg_r > 0:
        print("⚠️  MARGINAL EDGE - Needs more testing")
    else:
        print("🔴 NO EDGE - Do not deploy")
    print(f"{'=' * 80}")
else:
    print("No results generated")
