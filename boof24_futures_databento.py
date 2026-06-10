"""
Boof 24 Futures Test - Using Databento Data
Tests Boof 24 algorithm on ES, NQ, MES, MNQ futures
"""
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import warnings
warnings.filterwarnings('ignore')

# Databento API Key - from environment
DATABENTO_KEY = os.getenv('DATABENTO_KEY', '')
DATABENTO_URL = 'https://hist.databento.com/v0'

# ═══════════════════════════════════════════════════════════════════════════════
# FUTURES CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

FUTURES_CONFIG = {
    'ES':   {'symbol': 'ES.c.0', 'tick_value': 12.50, 'type': 'IMPULSE',  'name': 'E-mini S&P'},
    'MES':  {'symbol': 'MES.c.0', 'tick_value': 1.25, 'type': 'IMPULSE',  'name': 'Micro E-mini S&P'},
    'NQ':   {'symbol': 'NQ.c.0', 'tick_value': 5.00, 'type': 'BREAKOUT', 'name': 'E-mini Nasdaq'},
    'MNQ':  {'symbol': 'MNQ.c.0', 'tick_value': 0.50, 'type': 'BREAKOUT', 'name': 'Micro E-mini Nasdaq'},
}

# ═══════════════════════════════════════════════════════════════════════════════
# BOOF 24 CONFIG FOR FUTURES
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG = {
    'TP_R': 2.0,         # 2R target
    'SL_R': 1.0,         # 1R stop
    'BB_PERIOD': 20,
    'BB_STD': 2.0,
    'VOLUME_MULT': 1.0,  # Relative volume threshold
    'MAX_TRADES_PER_DAY': 5,
    'TIME_EXIT_BARS': 20,  # ~20 minutes on 1m
}

def fetch_databento(symbol, start_date, end_date, schema='ohlcv-1m'):
    """Fetch historical data from Databento"""
    if not DATABENTO_KEY:
        print("[ERROR] No DATABENTO_KEY set in environment")
        print("Set it with: $env:DATABENTO_KEY='your-key'")
        return None
    
    url = f"{DATABENTO_URL}/timeseries.get_range"
    headers = {'Authorization': DATABENTO_KEY}
    
    start_dt = f"{start_date}T00:00:00"
    end_dt = f"{end_date}T23:59:59"
    
    params = {
        'dataset': 'GLBX.MDP3',
        'symbols': symbol,
        'schema': schema,
        'start': start_dt,
        'end': end_dt,
        'stype_in': 'raw_symbol',
    }
    
    print(f"  Fetching {symbol}...", end=' ')
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data and len(data['data']) > 0:
                print(f"Got {len(data['data'])} bars")
                return process_databento_data(data['data'])
            else:
                print("No data returned")
                return None
        else:
            print(f"HTTP {resp.status_code}: {resp.text[:100]}")
            return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def process_databento_data(data):
    """Convert Databento response to DataFrame"""
    df = pd.DataFrame(data)
    # Databento columns: ts_event, rtype, publisher_id, instrument_id, open, high, low, close, volume
    df['ts'] = pd.to_datetime(df['ts_event'], unit='ns')
    df = df.rename(columns={
        'open': 'open', 'high': 'high', 'low': 'low', 
        'close': 'close', 'volume': 'volume'
    })
    return df[['ts', 'open', 'high', 'low', 'close', 'volume']].sort_values('ts')

def compute_bb(closes, period=20, std_dev=2.0):
    """Bollinger Bands"""
    sma = pd.Series(closes).rolling(window=period).mean()
    std = pd.Series(closes).rolling(window=period).std()
    upper = sma + std * std_dev
    lower = sma - std * std_dev
    return upper.iloc[-1], lower.iloc[-1], sma.iloc[-1]

def check_breakout(df, i):
    """Breakout detection for futures"""
    if i < 15:
        return False, None
    
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    
    # 15-bar range
    recent_high = df['high'].iloc[i-15:i].max()
    recent_low = df['low'].iloc[i-15:i].min()
    
    # Volume check
    vol_sma = df['volume'].iloc[i-15:i].mean()
    rvol = curr['volume'] / vol_sma if vol_sma > 0 else 1
    
    if rvol < CONFIG['VOLUME_MULT']:
        return False, None
    
    # Breakout with momentum
    if curr['close'] > recent_high * 0.9995 and prev['close'] <= recent_high:
        return True, 'long'
    if curr['close'] < recent_low * 1.0005 and prev['close'] >= recent_low:
        return True, 'short'
    
    return False, None

def check_impulse(df, i):
    """Mean reversion at BB extremes for futures"""
    if i < 20:
        return False, None
    
    closes = df['close'].iloc[:i+1].values
    bb_upper, bb_lower, bb_mid = compute_bb(closes, CONFIG['BB_PERIOD'], CONFIG['BB_STD'])
    
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    
    # Volume check
    vol_sma = df['volume'].iloc[i-20:i].mean()
    rvol = curr['volume'] / vol_sma if vol_sma > 0 else 1
    
    if rvol < 0.8:
        return False, None
    
    # Mean reversion at BB extremes
    if curr['close'] <= bb_lower * 1.005 and prev['close'] > bb_lower * 1.005:
        return True, 'long'
    if curr['close'] >= bb_upper * 0.995 and prev['close'] < bb_upper * 0.995:
        return True, 'short'
    
    return False, None

def backtest_futures(symbol, config, days=14):
    """Backtest a single futures contract"""
    print(f"\n{symbol} ({config['name']}, {config['type']}):", end=' ')
    
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=days)
    
    df = fetch_databento(config['symbol'], start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
    if df is None or len(df) < 100:
        print("Insufficient data")
        return None
    
    print(f"Backtesting...", end=' ')
    
    trades = []
    in_trade = False
    entry_price = 0
    direction = None
    bars_in_trade = 0
    daily_trades = 0
    last_date = None
    
    # Calculate R value in points (approximate)
    avg_range = (df['high'] - df['low']).mean()
    r_points = max(avg_range * 0.3, 2.0)  # Minimum 2 points R
    
    for i in range(50, len(df) - 1):
        curr_bar = df.iloc[i]
        current_date = curr_bar['ts'].strftime('%Y-%m-%d')
        
        if current_date != last_date:
            daily_trades = 0
            last_date = current_date
        
        if daily_trades >= CONFIG['MAX_TRADES_PER_DAY']:
            continue
        
        if in_trade:
            bars_in_trade += 1
            current = curr_bar['close']
            
            if direction == 'long':
                pnl_points = current - entry_price
                
                # TP hit (2R)
                if pnl_points >= r_points * CONFIG['TP_R']:
                    trades.append({'pnl_r': CONFIG['TP_R'], 'result': 'win', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
                    daily_trades += 1
                # SL hit (1R)
                elif pnl_points <= -r_points * CONFIG['SL_R']:
                    trades.append({'pnl_r': -CONFIG['SL_R'], 'result': 'loss', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
                    daily_trades += 1
                # Time exit
                elif bars_in_trade >= CONFIG['TIME_EXIT_BARS']:
                    pnl_r = pnl_points / r_points
                    trades.append({'pnl_r': pnl_r, 'result': 'win' if pnl_r > 0 else 'loss', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
                    daily_trades += 1
            else:  # short
                pnl_points = entry_price - current
                
                if pnl_points >= r_points * CONFIG['TP_R']:
                    trades.append({'pnl_r': CONFIG['TP_R'], 'result': 'win', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
                    daily_trades += 1
                elif pnl_points <= -r_points * CONFIG['SL_R']:
                    trades.append({'pnl_r': -CONFIG['SL_R'], 'result': 'loss', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
                    daily_trades += 1
                elif bars_in_trade >= CONFIG['TIME_EXIT_BARS']:
                    pnl_r = pnl_points / r_points
                    trades.append({'pnl_r': pnl_r, 'result': 'win' if pnl_r > 0 else 'loss', 'bars': bars_in_trade})
                    in_trade = False
                    bars_in_trade = 0
                    daily_trades += 1
            continue
        
        # Entry based on type
        if config['type'] == 'BREAKOUT':
            signal, dir = check_breakout(df, i)
        else:
            signal, dir = check_impulse(df, i)
        
        if signal and dir:
            entry_price = curr_bar['close']
            direction = dir
            in_trade = True
            bars_in_trade = 0
    
    if not trades:
        print("No trades")
        return None
    
    wins = [t for t in trades if t['result'] == 'win']
    losses = [t for t in trades if t['result'] == 'loss']
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    total_r = sum(t['pnl_r'] for t in trades)
    avg_r = total_r / len(trades) if trades else 0
    
    # Dollar P&L per contract
    dollar_pnl = total_r * config['tick_value'] * 10  # Approximate
    
    result = {
        'symbol': symbol,
        'name': config['name'],
        'type': config['type'],
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'avg_r': avg_r,
        'total_r': total_r,
        'tick_value': config['tick_value'],
        'dollar_pnl': dollar_pnl
    }
    
    print(f"Done. {len(trades)} trades, WR={win_rate:.1f}%, R/T={avg_r:.3f}, ${dollar_pnl:+.0f}")
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# RUN VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 80)
print("BOOF 24.0 - FUTURES VALIDATION (Databento)")
print("=" * 80)
print(f"Contracts: ES, MES, NQ, MNQ (Last 14 Days)")
print(f"Config: TP={CONFIG['TP_R']}R, SL={CONFIG['SL_R']}R, TimeExit={CONFIG['TIME_EXIT_BARS']} bars")
print("=" * 80)

if not DATABENTO_KEY:
    print("\n⚠️  DATABENTO_KEY not found in environment!")
    print("Please set it with: $env:DATABENTO_KEY='your-api-key'")
    print("Then run this script again.")
    exit(1)

all_results = []

for symbol, config in FUTURES_CONFIG.items():
    result = backtest_futures(symbol, config, days=14)
    if result:
        all_results.append(result)
    time.sleep(0.5)  # Rate limit

# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 80)
print("FUTURES RESULTS BY TYPE")
print("=" * 80)

breakout_results = [r for r in all_results if r['type'] == 'BREAKOUT']
impulse_results = [r for r in all_results if r['type'] == 'IMPULSE']

if breakout_results:
    print("\n📈 BREAKOUT FUTURES (NQ, MNQ):")
    print(f"{'Contract':<10} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'WR%':<8} {'R/T':<8} {'$PnL':<10}")
    print("-" * 75)
    total_trades = sum(r['trades'] for r in breakout_results)
    total_wins = sum(r['wins'] for r in breakout_results)
    total_losses = sum(r['losses'] for r in breakout_results)
    total_r = sum(r['total_r'] for r in breakout_results)
    avg_r = total_r / total_trades if total_trades > 0 else 0
    total_dollar = sum(r['dollar_pnl'] for r in breakout_results)
    
    for r in breakout_results:
        status = "✅" if r['avg_r'] > 0.10 else "⚠️" if r['avg_r'] > 0 else "🔴"
        print(f"{r['symbol']:<10} {r['trades']:<8} {r['wins']:<6} {r['losses']:<8} {r['win_rate']:<8.1f} {r['avg_r']:<8.3f} ${r['dollar_pnl']:<+9.0f} {status}")
    
    wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print("-" * 75)
    print(f"{'TOTAL':<10} {total_trades:<8} {total_wins:<6} {total_losses:<8} {wr:<8.1f} {avg_r:<8.3f} ${total_dollar:<+9.0f}")
    print(f"\nBREAKOUT verdict: {'✅ Edge confirmed' if avg_r > 0.10 else '⚠️ Weak edge' if avg_r > 0 else '🔴 No edge'}")

if impulse_results:
    print("\n⚡ IMPULSE FUTURES (ES, MES):")
    print(f"{'Contract':<10} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'WR%':<8} {'R/T':<8} {'$PnL':<10}")
    print("-" * 75)
    total_trades = sum(r['trades'] for r in impulse_results)
    total_wins = sum(r['wins'] for r in impulse_results)
    total_losses = sum(r['losses'] for r in impulse_results)
    total_r = sum(r['total_r'] for r in impulse_results)
    avg_r = total_r / total_trades if total_trades > 0 else 0
    total_dollar = sum(r['dollar_pnl'] for r in impulse_results)
    
    for r in impulse_results:
        status = "✅" if r['avg_r'] > 0.10 else "⚠️" if r['avg_r'] > 0 else "🔴"
        print(f"{r['symbol']:<10} {r['trades']:<8} {r['wins']:<6} {r['losses']:<8} {r['win_rate']:<8.1f} {r['avg_r']:<8.3f} ${r['dollar_pnl']:<+9.0f} {status}")
    
    wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print("-" * 75)
    print(f"{'TOTAL':<10} {total_trades:<8} {total_wins:<6} {total_losses:<8} {wr:<8.1f} {avg_r:<8.3f} ${total_dollar:<+9.0f}")
    print(f"\nIMPULSE verdict: {'✅ Edge confirmed' if avg_r > 0.10 else '⚠️ Weak edge' if avg_r > 0 else '🔴 No edge'}")

# GRAND TOTAL
print("\n" + "=" * 80)
print("GRAND TOTAL - ALL FUTURES")
print("=" * 80)
if all_results:
    grand_total = {
        'trades': sum(r['trades'] for r in all_results),
        'wins': sum(r['wins'] for r in all_results),
        'losses': sum(r['losses'] for r in all_results),
        'total_r': sum(r['total_r'] for r in all_results),
        'dollar_pnl': sum(r['dollar_pnl'] for r in all_results)
    }
    grand_wr = grand_total['wins'] / grand_total['trades'] * 100 if grand_total['trades'] > 0 else 0
    grand_avg_r = grand_total['total_r'] / grand_total['trades'] if grand_total['trades'] > 0 else 0
    
    print(f"\nTotal Trades:  {grand_total['trades']}")
    print(f"Win Rate:      {grand_wr:.1f}%")
    print(f"Total R:       {grand_total['total_r']:+.2f}")
    print(f"R per Trade:   {grand_avg_r:.3f}")
    print(f"Est. Dollar:   ${grand_total['dollar_pnl']:+.0f}")
    print(f"\n{'=' * 80}")
    if grand_avg_r > 0.15:
        print("✅✅ STRONG EDGE - Boof 24 Futures ready")
    elif grand_avg_r > 0.10:
        print("✅ EDGE CONFIRMED - Boof 24 Futures viable")
    elif grand_avg_r > 0:
        print("⚠️  MARGINAL EDGE - Needs more testing")
    else:
        print("🔴 NO EDGE - Do not trade")
    print(f"{'=' * 80}")
else:
    print("No results generated")

print("\n💡 Futures Trading Notes:")
print("   - ES: $12.50/tick, ~$12K margin/contract")
print("   - MES: $1.25/tick, ~$1.2K margin/contract")
print("   - NQ: $5.00/tick, ~$18K margin/contract")
print("   - MNQ: $0.50/tick, ~$1.8K margin/contract")
print("   - 23.5hr trading, high liquidity")
