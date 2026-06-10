"""
backtest_boof_21_22_23_compare.py
=================================
Compare Boof 21, 22, 23 with 0.1% TP / 0.05% SL
Period: Jan 2026 - Apr 2026
Uses underlying price movement to simulate option scalps
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from volume_cluster_sr import build_levels, retest_signals
import sys

# Alpaca credentials
creds = get_alpaca_credentials()
API_KEY = creds['api_key']
API_SECRET = creds['secret_key']

# =============================================================================
# CONFIG
# =============================================================================
START_DATE = datetime(2026, 1, 1)
END_DATE   = datetime(2026, 4, 30)

# TP/SL - convert option premium % to underlying price % using 0.5 delta
# 40% option gain ≈ 0.8% underlying (40% / 0.5 delta / 100)
# 10% option loss ≈ 0.2% underlying (10% / 0.5 delta / 100)
OPTION_TP_PCT = 0.40   # +40% option premium
OPTION_SL_PCT = 0.10   # -10% option premium
DELTA = 0.50           # option delta
TP_PCT = OPTION_TP_PCT / DELTA / 100  # 0.008 = 0.8% underlying
SL_PCT = OPTION_SL_PCT / DELTA / 100  # 0.002 = 0.2% underlying

SYMBOLS = ['NVDA', 'AAPL', 'META', 'GOOGL', 'AMD', 'TSLA', 'QQQ', 'SPY']

# Position sizing
BASE_AMOUNT = 200  # per trade
CORE_MULT = 2.0    # 2x for core signals
SLACK_THRESHOLD = 0.8

# =============================================================================
# BOOF 21 - Volume Cluster S/R Retest
# =============================================================================
def backtest_boof21(symbol, bars):
    """Boof 21: S/R retest with volume confirmation"""
    trades = []
    if len(bars) < 200:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    # Calculate metrics
    df['hl2'] = (df['high'] + df['low']) / 2
    df['rvol'] = df['volume'] / df['volume'].rolling(20).mean()
    
    # Simple EMA for trend
    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    
    in_trade = False
    entry_price = 0
    entry_time = None
    entry_slack = 0
    position_size = 0
    
    for i in range(50, len(df)):
        if in_trade:
            # Check exit
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            
            if change_pct >= TP_PCT:
                pnl = position_size * OPTION_TP_PCT
                trades.append({
                    'symbol': symbol,
                    'entry_time': entry_time,
                    'exit_time': current['timestamp'],
                    'entry': entry_price,
                    'exit': entry_price * (1 + TP_PCT),
                    'pnl': pnl,
                    'slack': entry_slack,
                    'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                    'result': 'win'
                })
                in_trade = False
            elif change_pct <= -SL_PCT:
                pnl = -position_size * OPTION_SL_PCT
                trades.append({
                    'symbol': symbol,
                    'entry_time': entry_time,
                    'exit_time': current['timestamp'],
                    'entry': entry_price,
                    'exit': entry_price * (1 - SL_PCT),
                    'pnl': pnl,
                    'slack': entry_slack,
                    'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                    'result': 'loss'
                })
                in_trade = False
            continue
        
        # Look for entry signal
        window = df.iloc[i-20:i]
        current = df.iloc[i]
        
        # Find support/resistance levels (simple approach)
        highs = window['high'].nlargest(3).values
        lows = window['low'].nsmallest(3).values
        
        price = current['close']
        trend_up = current['ema20'] > current['ema50']
        
        # Long signal: price near support with volume
        support_dist = min(abs(price - level) for level in lows) if len(lows) > 0 else 999
        resistance_dist = min(abs(price - level) for level in highs) if len(highs) > 0 else 999
        
        # Calculate slack based on level strength and volume
        level_strength = 10.0 - min(support_dist / price * 100, 10.0)  # closer = stronger
        rvol_ratio = current['rvol'] if not pd.isna(current['rvol']) else 1.0
        slack = (level_strength / 10) * min(rvol_ratio, 2.0)
        
        signal = None
        if trend_up and support_dist < price * 0.002 and current['rvol'] > 1.2:
            signal = 'long'
        elif not trend_up and resistance_dist < price * 0.002 and current['rvol'] > 1.2:
            signal = 'short'
        
        if signal:
            in_trade = True
            entry_price = price
            entry_time = current['timestamp']
            entry_slack = slack
            is_core = slack >= SLACK_THRESHOLD
            position_size = BASE_AMOUNT * (CORE_MULT if is_core else 1.0)
    
    return trades


# =============================================================================
# BOOF 22 - Volume Cluster + ZigZag Reversal
# =============================================================================
def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def find_fractal_peaks(highs, lows, atr, bars=3):
    """Find fractal peaks and troughs"""
    peaks = []
    troughs = []
    
    for i in range(bars, len(highs) - bars):
        # Peak: higher than N bars on each side
        if all(highs[i] > highs[i-j] for j in range(1, bars+1)) and \
           all(highs[i] > highs[i+j] for j in range(1, bars+1)):
            peaks.append(i)
        
        # Trough: lower than N bars on each side  
        if all(lows[i] < lows[i-j] for j in range(1, bars+1)) and \
           all(lows[i] < lows[i+j] for j in range(1, bars+1)):
            troughs.append(i)
    
    return peaks, troughs

def backtest_boof22(symbol, bars):
    """Boof 22: Fractal reversal at volume clusters"""
    trades = []
    if len(bars) < 100:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    atr = compute_atr(df)
    df['atr'] = atr
    
    # Find clusters (high volume areas)
    vol_sma = df['volume'].rolling(50).mean()
    df['hi_vol'] = df['volume'] > vol_sma * 1.3
    
    peaks, troughs = find_fractal_peaks(df['high'].values, df['low'].values, atr.values, 3)
    
    in_trade = False
    entry_price = 0
    entry_time = None
    entry_slack = 0
    position_size = 0
    trade_direction = None
    
    for i in range(50, len(df) - 1):
        if in_trade:
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            
            # Reverse for shorts
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= TP_PCT:
                pnl = position_size * OPTION_TP_PCT
                trades.append({
                    'symbol': symbol,
                    'entry_time': entry_time,
                    'exit_time': current['timestamp'],
                    'entry': entry_price,
                    'exit': entry_price * (1 + TP_PCT),
                    'pnl': pnl,
                    'slack': entry_slack,
                    'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                    'result': 'win'
                })
                in_trade = False
            elif change_pct <= -SL_PCT:
                pnl = -position_size * OPTION_SL_PCT
                trades.append({
                    'symbol': symbol,
                    'entry_time': entry_time,
                    'exit_time': current['timestamp'],
                    'entry': entry_price,
                    'exit': entry_price * (1 - SL_PCT),
                    'pnl': pnl,
                    'slack': entry_slack,
                    'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                    'result': 'loss'
                })
                in_trade = False
            continue
        
        # Check for fractal signal
        if i in peaks or i in troughs:
            current = df.iloc[i]
            is_peak = i in peaks
            
            # Calculate slack (wick rejection strength)
            if is_peak:
                wick = current['high'] - max(current['open'], current['close'])
                slack = wick / current['atr'] if current['atr'] > 0 else 0
                
                # Short signal at peak
                if slack >= 0.6:  # min threshold
                    in_trade = True
                    trade_direction = 'short'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
                    is_core = slack >= SLACK_THRESHOLD
                    position_size = BASE_AMOUNT * (CORE_MULT if is_core else 1.0)
            else:
                wick = min(current['open'], current['close']) - current['low']
                slack = wick / current['atr'] if current['atr'] > 0 else 0
                
                # Long signal at trough
                if slack >= 0.6:
                    in_trade = True
                    trade_direction = 'long'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
                    is_core = slack >= SLACK_THRESHOLD
                    position_size = BASE_AMOUNT * (CORE_MULT if is_core else 1.0)
    
    return trades


# =============================================================================
# BOOF 23 - ZigZag Regime + SR Cluster (Same as 22 with regime filter)
# =============================================================================
def backtest_boof23(symbol, bars):
    """Boof 23: Same as 22 but with ZigZag regime confirmation"""
    trades = []
    if len(bars) < 100:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    atr = compute_atr(df)
    df['atr'] = atr
    
    # Simple ZigZag trend detection
    df['swing_high'] = df['high'].rolling(5).max()
    df['swing_low'] = df['low'].rolling(5).min()
    df['trend'] = np.where(df['close'] > df['swing_high'].shift(5), 'up',
                  np.where(df['close'] < df['swing_low'].shift(5), 'down', None))
    df['trend'] = df['trend'].ffill().fillna('neutral')
    
    peaks, troughs = find_fractal_peaks(df['high'].values, df['low'].values, atr.values, 3)
    
    in_trade = False
    entry_price = 0
    entry_time = None
    entry_slack = 0
    position_size = 0
    trade_direction = None
    
    for i in range(50, len(df) - 1):
        if in_trade:
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= TP_PCT:
                pnl = position_size * OPTION_TP_PCT
                trades.append({
                    'symbol': symbol,
                    'entry_time': entry_time,
                    'exit_time': current['timestamp'],
                    'entry': entry_price,
                    'exit': entry_price * (1 + TP_PCT),
                    'pnl': pnl,
                    'slack': entry_slack,
                    'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                    'result': 'win'
                })
                in_trade = False
            elif change_pct <= -SL_PCT:
                pnl = -position_size * OPTION_SL_PCT
                trades.append({
                    'symbol': symbol,
                    'entry_time': entry_time,
                    'exit_time': current['timestamp'],
                    'entry': entry_price,
                    'exit': entry_price * (1 - SL_PCT),
                    'pnl': pnl,
                    'slack': entry_slack,
                    'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                    'result': 'loss'
                })
                in_trade = False
            continue
        
        if i in peaks or i in troughs:
            current = df.iloc[i]
            trend = df.iloc[i-1]['trend']
            is_peak = i in peaks
            
            if is_peak:
                wick = current['high'] - max(current['open'], current['close'])
                slack = wick / current['atr'] if current['atr'] > 0 else 0
                
                # Boof 23: Only short when trend is up (fading the up move)
                if slack >= 0.6 and trend == 'up':
                    in_trade = True
                    trade_direction = 'short'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
                    is_core = slack >= SLACK_THRESHOLD
                    position_size = BASE_AMOUNT * (CORE_MULT if is_core else 1.0)
            else:
                wick = min(current['open'], current['close']) - current['low']
                slack = wick / current['atr'] if current['atr'] > 0 else 0
                
                # Boof 23: Only long when trend is down (fading the down move)
                if slack >= 0.6 and trend == 'down':
                    in_trade = True
                    trade_direction = 'long'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
                    is_core = slack >= SLACK_THRESHOLD
                    position_size = BASE_AMOUNT * (CORE_MULT if is_core else 1.0)
    
    return trades


# =============================================================================
# ANALYSIS
# =============================================================================
def analyze_trades(trades, name):
    if not trades:
        return {'name': name, 'trades': 0, 'win_rate': 0, 'avg_pnl': 0, 'total_pnl': 0}
    
    df = pd.DataFrame(trades)
    wins = len(df[df['result'] == 'win'])
    total = len(df)
    win_rate = wins / total if total > 0 else 0
    avg_pnl = df['pnl'].mean()
    total_pnl = df['pnl'].sum()
    
    # Slack bucket analysis
    df['slack_bucket'] = pd.cut(df['slack'], bins=[0, 0.6, 0.9, 1.2, 1.4, 10], 
                                 labels=['0.0-0.6', '0.6-0.9', '0.9-1.2', '1.2-1.4', '1.4+'])
    bucket_stats = df.groupby('slack_bucket').agg({
        'pnl': ['count', 'mean', 'sum'],
        'result': lambda x: (x == 'win').mean()
    }).round(2)
    
    pf = abs(df[df['pnl'] > 0]['pnl'].sum() / df[df['pnl'] < 0]['pnl'].sum()) if len(df[df['pnl'] < 0]) > 0 and df[df['pnl'] < 0]['pnl'].sum() != 0 else 999
    return {
        'name': name,
        'trades': total,
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'total_pnl': total_pnl,
        'pf': pf,
        'core_trades': len(df[df['tier'] == 'core']),
        'expanded_trades': len(df[df['tier'] == 'expanded']),
        'bucket_stats': bucket_stats
    }


# =============================================================================
# MAIN
# =============================================================================
def main():
    print("=" * 70)
    print("BOOF 21 / 22 / 23 COMPARISON BACKTEST")
    print(f"Period: {START_DATE.date()} to {END_DATE.date()}")
    print(f"TP: {TP_PCT*100:.2f}% | SL: {SL_PCT*100:.2f}%")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print("=" * 70)
    
    all_results = {'boof21': [], 'boof22': [], 'boof23': []}
    
    for symbol in SYMBOLS:
        print(f"\nFetching data for {symbol}...")
        try:
            df_bars = fetch_alpaca_bars(symbol, START_DATE, END_DATE, '1Min', API_KEY, API_SECRET)
            if df_bars is None or len(df_bars) < 100:
                print(f"  Insufficient data for {symbol}")
                continue
            
            # Convert DataFrame to list of dicts with timestamp field
            df_bars = df_bars.reset_index()
            df_bars = df_bars.rename(columns={'time': 'timestamp'})
            bars = df_bars.to_dict('records')
            
            print(f"  Loaded {len(bars)} bars")
            
            # Run all three strategies
            trades21 = backtest_boof21(symbol, bars)
            trades22 = backtest_boof22(symbol, bars)
            trades23 = backtest_boof23(symbol, bars)
            
            all_results['boof21'].extend(trades21)
            all_results['boof22'].extend(trades22)
            all_results['boof23'].extend(trades23)
            
            print(f"  Boof 21: {len(trades21)} trades")
            print(f"  Boof 22: {len(trades22)} trades")
            print(f"  Boof 23: {len(trades23)} trades")
            
        except Exception as e:
            print(f"  Error: {e}")
            continue
    
    # Analyze results
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    
    for name, trades in all_results.items():
        stats = analyze_trades(trades, name)
        print(f"\n{stats['name'].upper()}")
        print(f"  Total Trades:     {stats['trades']}")
        print(f"  Win Rate:         {stats['win_rate']*100:.1f}%")
        print(f"  Avg P&L:          ${stats['avg_pnl']:.2f}")
        print(f"  Total P&L:        ${stats['total_pnl']:.2f}")
        print(f"  Profit Factor:    {stats['pf']:.1f}")
        print(f"  Core Trades:      {stats['core_trades']} (slack >= {SLACK_THRESHOLD})")
        print(f"  Expanded Trades:  {stats['expanded_trades']}")
        
        if stats['trades'] > 0:
            print(f"\n  Slack Bucket Analysis:")
            print(stats['bucket_stats'])
    
    # Save detailed results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for name, trades in all_results.items():
        if trades:
            df = pd.DataFrame(trades)
            df.to_csv(f'backtest_{name}_results_{timestamp}.csv', index=False)
            print(f"\nSaved {name} results to backtest_{name}_results_{timestamp}.csv")


if __name__ == '__main__':
    main()
