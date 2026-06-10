"""
BOOF 24.1 — Regime-Based Analysis + Single Variable Optimization
Tags every trade: Trend / Chop / Volatility Expansion
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import time

ALPACA_KEY = os.getenv('ALPACA_KEY', 'PKGA4ZC63QX27XHF22CB6YP547')
ALPACA_SECRET = os.getenv('ALPACA_SECRET', 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q')
DATA_URL = 'https://data.alpaca.markets'

SYMBOLS = ['QQQ', 'SPY', 'AAPL', 'NVDA', 'META', 'AMD', 'NFLX']
TIMEFRAMES = ['5Min']  # Focus on best TF from last test

def fetch_data(symbol, timeframe, start, end):
    """Fetch bars from Alpaca"""
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    
    chunk_size = 30 if timeframe == '1Min' else 60
    current_start = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    
    while current_start < end_dt:
        chunk_end = min(current_start + timedelta(days=chunk_size), end_dt)
        params = {
            'timeframe': timeframe, 'start': current_start.strftime('%Y-%m-%d'),
            'end': chunk_end.strftime('%Y-%m-%d'), 'limit': 10000, 'feed': 'iex'
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                bars = resp.json().get('bars', [])
                if bars:
                    all_bars.extend(bars)
            else:
                print(f"  [WARN] {symbol}: Status {resp.status_code}")
        except Exception as e:
            print(f"  [ERROR] {symbol}: {e}")
        
        current_start = chunk_end
        time.sleep(0.3)
    
    if not all_bars:
        return None
    
    df = pd.DataFrame(all_bars)
    df['t'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'})
    return df.set_index('timestamp').sort_index()

def add_regime_tags(df):
    """
    Tag each bar with regime:
    - trend: price stays directional vs VWAP, VWAP slope significant
    - chop: frequent VWAP crossings, low ATR
    - expansion: high volume spikes, rising ATR
    """
    df = df.copy()
    
    # VWAP
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df['vwap_dist'] = (df['close'] - df['vwap']).abs()
    df['above_vwap'] = df['close'] > df['vwap']
    
    # VWAP slope (20-bar)
    df['vwap_slope'] = df['vwap'].diff(20)
    df['vwap_trending'] = df['vwap_slope'].abs() > df['vwap_dist'].rolling(50).mean() * 0.5
    
    # VWAP crossings (rolling 20-bar window)
    df['vwap_cross'] = df['above_vwap'] != df['above_vwap'].shift(1)
    df['vwap_cross_count'] = df['vwap_cross'].rolling(20).sum()
    
    # ATR
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['atr_sma'] = df['atr'].rolling(20).mean()
    df['atr_rising'] = df['atr'] > df['atr_sma']
    
    # Volume z-score
    df['vol_mean'] = df['volume'].rolling(20).mean()
    df['vol_std'] = df['volume'].rolling(20).std()
    df['vol_z'] = (df['volume'] - df['vol_mean']) / df['vol_std']
    df['high_vol'] = df['vol_z'] > 2.0
    df['vol_cluster'] = df['high_vol'].rolling(10).sum() >= 3  # 3+ high vol bars in 10
    
    # Vectorized regime scoring (much faster)
    df['regime'] = 'unknown'
    
    # TREND score components
    trend_score = df['vwap_trending'].astype(int)
    trend_score += (df['vwap_cross_count'] < 2).astype(int)
    trend_score += (df['vwap_dist'].rolling(20, min_periods=1).mean() > df['atr'] * 0.5).astype(int)
    
    # CHOP score components  
    chop_score = (df['vwap_cross_count'] >= 3).astype(int)
    chop_score += (~df['atr_rising']).astype(int)
    chop_score += (df['vwap_dist'].rolling(20, min_periods=1).mean() < df['atr'] * 0.3).astype(int)
    
    # EXPANSION score components
    expansion_score = df['atr_rising'].astype(int)
    expansion_score += df['vol_cluster'].astype(int)
    df['range_20'] = (df['high'].rolling(20, min_periods=1).max() - df['low'].rolling(20, min_periods=1).min())
    expansion_score += (df['range_20'] > df['atr'] * 5).astype(int)
    
    # Assign regime based on highest score
    df['trend_score'] = trend_score
    df['chop_score'] = chop_score
    df['expansion_score'] = expansion_score
    
    # Find best regime for each row
    scores_df = pd.DataFrame({'trend': trend_score, 'chop': chop_score, 'expansion': expansion_score})
    df['best_regime'] = scores_df.idxmax(axis=1)
    df['best_score'] = scores_df.max(axis=1)
    
    # Require score >= 2, otherwise 'mixed'
    df.loc[df['best_score'] >= 2, 'regime'] = df.loc[df['best_score'] >= 2, 'best_regime']
    df.loc[df['best_score'] < 2, 'regime'] = 'mixed'
    
    return df

def generate_signals_with_regime(df, vol_threshold=1.8, impulse_mult=0.3):
    """Generate signals with regime tags"""
    df = add_regime_tags(df)
    
    # Direction pressure
    df['bull_pressure'] = df['close'] > df['open']
    df['bear_pressure'] = df['close'] < df['open']
    df['body_size'] = (df['close'] - df['open']).abs()
    
    # Volume spike
    df['vol_spike'] = df['vol_z'] > vol_threshold
    
    signals = []
    
    for i in range(50, len(df) - 1):
        row = df.iloc[i]
        
        if pd.isna(row['atr']) or pd.isna(row['vol_z']):
            continue
        
        if not row['vol_spike']:
            continue
        
        # Impulse filter
        if row['body_size'] < row['atr'] * impulse_mult:
            continue
        
        entry_price = df.iloc[i + 1]['open']
        timestamp = df.index[i + 1]
        regime = row['regime']
        
        # LONG
        if row['bull_pressure'] and row['close'] > row['vwap']:
            signals.append({
                'direction': 'long', 'entry_price': entry_price, 'timestamp': timestamp,
                'idx': i + 1, 'regime': regime, 'vol_z': row['vol_z'],
                'body_atr_ratio': row['body_size'] / row['atr'] if row['atr'] > 0 else 0
            })
        
        # SHORT
        elif row['bear_pressure'] and row['close'] < row['vwap']:
            signals.append({
                'direction': 'short', 'entry_price': entry_price, 'timestamp': timestamp,
                'idx': i + 1, 'regime': regime, 'vol_z': row['vol_z'],
                'body_atr_ratio': row['body_size'] / row['atr'] if row['atr'] > 0 else 0
            })
    
    return signals

def backtest_by_regime(df, signals, tp_pct=0.8, sl_pct=0.5, max_bars=20):
    """Backtest and split results by regime"""
    if not signals:
        return None
    
    regime_results = {'trend': [], 'chop': [], 'expansion': [], 'mixed': [], 'unknown': []}
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 5:
            continue
        
        entry = sig['entry_price']
        direction = sig['direction']
        regime = sig.get('regime', 'unknown')
        
        if direction == 'long':
            tp_price = entry * (1 + tp_pct / 100)
            sl_price = entry * (1 - sl_pct / 100)
        else:
            tp_price = entry * (1 - tp_pct / 100)
            sl_price = entry * (1 + sl_pct / 100)
        
        pnl_pct = 0
        win = False
        exit_type = None
        
        for j in range(idx + 1, min(idx + max_bars, len(df))):
            bar = df.iloc[j]
            
            if direction == 'long':
                if bar['low'] <= sl_price:
                    pnl_pct = -sl_pct
                    win = False
                    exit_type = 'sl'
                    break
                if bar['high'] >= tp_price:
                    pnl_pct = tp_pct
                    win = True
                    exit_type = 'tp'
                    break
            else:
                if bar['high'] >= sl_price:
                    pnl_pct = -sl_pct
                    win = False
                    exit_type = 'sl'
                    break
                if bar['low'] <= tp_price:
                    pnl_pct = tp_pct
                    win = True
                    exit_type = 'tp'
                    break
        
        if exit_type is None:
            exit_price = df.iloc[min(idx + max_bars - 1, len(df) - 1)]['close']
            if direction == 'long':
                pnl_pct = (exit_price - entry) / entry * 100
            else:
                pnl_pct = (entry - exit_price) / entry * 100
            win = pnl_pct > 0
            exit_type = 'time'
        
        regime_results[regime].append({
            'pnl_pct': pnl_pct, 'win': win, 'direction': direction,
            'timestamp': sig['timestamp'], 'vol_z': sig.get('vol_z', 0)
        })
    
    # Calculate stats per regime
    stats = {}
    for regime, trades in regime_results.items():
        if not trades:
            continue
        wins = sum(1 for t in trades if t['win'])
        total = len(trades)
        total_pnl = sum(t['pnl_pct'] for t in trades)
        
        # Max streak
        max_streak, curr_streak = 0, 0
        for t in trades:
            if not t['win']:
                curr_streak += 1
                max_streak = max(max_streak, curr_streak)
            else:
                curr_streak = 0
        
        stats[regime] = {
            'trades': total, 'wins': wins, 'win_rate': wins / total * 100,
            'total_pnl': total_pnl, 'avg_pnl': total_pnl / total,
            'max_streak': max_streak
        }
    
    return stats

def test_vol_thresholds(df):
    """Test 1: Volume spike threshold optimization"""
    thresholds = [1.5, 1.8, 2.0, 2.5, 3.0]
    results = []
    
    for z in thresholds:
        signals = generate_signals_with_regime(df, vol_threshold=z, impulse_mult=0.3)
        stats = backtest_by_regime(df, signals)
        if stats:
            total_trades = sum(s['trades'] for s in stats.values())
            total_wins = sum(s['wins'] for s in stats.values())
            total_pnl = sum(s['total_pnl'] for s in stats.values())
            
            results.append({
                'z_threshold': z,
                'trades': total_trades,
                'win_rate': total_wins / total_trades * 100 if total_trades > 0 else 0,
                'total_pnl': total_pnl,
                'avg_pnl': total_pnl / total_trades if total_trades > 0 else 0
            })
    
    return results

def main():
    print("="*80)
    print("BOOF 24.1 — REGIME ANALYSIS + SINGLE VARIABLE OPTIMIZATION")
    print("="*80)
    
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=90)
    
    # Run on best symbols from previous test
    for symbol in ['NFLX', 'AMD', 'QQQ', 'AAPL']:
        print(f"\n{'='*80}")
        print(f"[{symbol}] 5Min | Regime Analysis")
        print(f"{'='*80}")
        
        df = fetch_data(symbol, '5Min', start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        if df is None or len(df) < 1000:
            print(f"  [SKIP] No data")
            continue
        
        print(f"  Bars: {len(df)}")
        
        # === STEP 1: Regime distribution ===
        df = add_regime_tags(df)
        regime_counts = df['regime'].value_counts()
        print(f"\n  Regime Distribution:")
        for regime, count in regime_counts.items():
            pct = count / len(df) * 100
            print(f"    {regime}: {count} bars ({pct:.1f}%)")
        
        # === STEP 2: Performance BY regime ===
        print(f"\n  PERFORMANCE BY REGIME (Z > 1.8):")
        signals = generate_signals_with_regime(df, vol_threshold=1.8)
        stats = backtest_by_regime(df, signals)
        
        if stats:
            print(f"  {'Regime':<12} {'Trades':>8} {'WR%':>8} {'Avg P&L%':>12} {'Total%':>10}")
            print(f"  {'-'*60}")
            for regime in ['expansion', 'trend', 'chop', 'mixed']:
                if regime in stats:
                    s = stats[regime]
                    print(f"  {regime:<12} {s['trades']:>8} {s['win_rate']:>7.1f}% {s['avg_pnl']:>+10.3f}% {s['total_pnl']:>+9.2f}%")
        
        # === STEP 3: Volume threshold optimization ===
        print(f"\n  TEST 1: Volume Threshold Optimization")
        vol_results = test_vol_thresholds(df)
        
        if vol_results:
            print(f"  {'Z Threshold':<12} {'Trades':>8} {'WR%':>8} {'Avg P&L%':>12} {'Total%':>10}")
            print(f"  {'-'*60}")
            for r in vol_results:
                print(f"  Z > {r['z_threshold']:<8.1f} {r['trades']:>8} {r['win_rate']:>7.1f}% {r['avg_pnl']:>+10.3f}% {r['total_pnl']:>+9.2f}%")
    
    print(f"\n{'='*80}")
    print("KEY INSIGHT: Which regime is your edge?")
    print("If expansion has 60%+ WR, only trade high volatility days.")
    print("="*80)

if __name__ == '__main__':
    main()
