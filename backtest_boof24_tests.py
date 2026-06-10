"""
BOOF 24.1 — Next Tests: Trend-only + VWAP Slope Filter
Test 1: Trend regime only vs Trend+Expansion
Test 2: Volume threshold sweep (trend only)
Test 3: VWAP slope alignment filter
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

def fetch_data(symbol, timeframe, start, end):
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    
    chunk_size = 60
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
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")
        
        current_start = chunk_end
        time.sleep(0.3)
    
    if not all_bars:
        return None
    
    df = pd.DataFrame(all_bars)
    df['t'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'})
    return df.set_index('timestamp').sort_index()

def add_regime_and_vwap(df):
    df = df.copy()
    
    # VWAP
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df['vwap_dist'] = (df['close'] - df['vwap']).abs()
    df['above_vwap'] = df['close'] > df['vwap']
    
    # VWAP slope (trend strength)
    df['vwap_slope'] = df['vwap'].diff(20)
    df['vwap_slope_pct'] = df['vwap_slope'] / df['vwap'] * 100
    df['vwap_trending'] = df['vwap_slope'].abs() > df['vwap_dist'].rolling(50, min_periods=1).mean() * 0.5
    
    # VWAP crossings
    df['vwap_cross'] = df['above_vwap'] != df['above_vwap'].shift(1)
    df['vwap_cross_count'] = df['vwap_cross'].rolling(20, min_periods=1).sum()
    
    # ATR
    tr = pd.concat([
        df['high'] - df['low'], 
        (df['high'] - df['close'].shift(1)).abs(), 
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14, min_periods=1).mean()
    df['atr_sma'] = df['atr'].rolling(20, min_periods=1).mean()
    df['atr_rising'] = df['atr'] > df['atr_sma']
    
    # Volume z-score
    df['vol_mean'] = df['volume'].rolling(20, min_periods=1).mean()
    df['vol_std'] = df['volume'].rolling(20, min_periods=1).std().replace(0, np.nan)
    df['vol_z'] = (df['volume'] - df['vol_mean']) / df['vol_std']
    df['high_vol'] = df['vol_z'] > 2.0
    df['vol_cluster'] = df['high_vol'].rolling(10, min_periods=1).sum() >= 3
    
    # Range
    df['range_20'] = df['high'].rolling(20, min_periods=1).max() - df['low'].rolling(20, min_periods=1).min()
    
    # Regime scoring
    trend_score = df['vwap_trending'].astype(int) + (df['vwap_cross_count'] < 2).astype(int) + (df['vwap_dist'].rolling(20, min_periods=1).mean() > df['atr'] * 0.5).astype(int)
    chop_score = (df['vwap_cross_count'] >= 3).astype(int) + (~df['atr_rising']).astype(int) + (df['vwap_dist'].rolling(20, min_periods=1).mean() < df['atr'] * 0.3).astype(int)
    expansion_score = df['atr_rising'].astype(int) + df['vol_cluster'].astype(int) + (df['range_20'] > df['atr'] * 5).astype(int)
    
    scores_df = pd.DataFrame({'trend': trend_score, 'chop': chop_score, 'expansion': expansion_score})
    df['best_regime'] = scores_df.idxmax(axis=1)
    df['best_score'] = scores_df.max(axis=1)
    df['regime'] = 'mixed'
    df.loc[df['best_score'] >= 2, 'regime'] = df.loc[df['best_score'] >= 2, 'best_regime']
    
    return df

def generate_signals(df, vol_threshold, regime_filter=None, vwap_slope_filter=False):
    """
    regime_filter: 'trend', 'expansion', or None (both)
    vwap_slope_filter: only trade when price direction aligns with VWAP slope
    """
    df = add_regime_and_vwap(df)
    df['bull_pressure'] = df['close'] > df['open']
    df['bear_pressure'] = df['close'] < df['open']
    df['body_size'] = (df['close'] - df['open']).abs()
    df['vol_spike'] = df['vol_z'] > vol_threshold
    
    signals = []
    for i in range(50, len(df) - 1):
        row = df.iloc[i]
        if pd.isna(row['atr']) or pd.isna(row['vol_z']):
            continue
        if not row['vol_spike'] or row['body_size'] < row['atr'] * 0.3:
            continue
        
        # Regime filter
        if regime_filter and row['regime'] != regime_filter:
            continue
        
        entry_price = df.iloc[i + 1]['open']
        regime = row['regime']
        
        # LONG: bull pressure + above VWAP
        if row['bull_pressure'] and row['close'] > row['vwap']:
            # VWAP slope filter: only trade if VWAP is rising (uptrend)
            if vwap_slope_filter and row['vwap_slope'] <= 0:
                continue
            signals.append({'direction': 'long', 'entry_price': entry_price, 'idx': i + 1, 'regime': regime, 'vol_z': row['vol_z']})
        
        # SHORT: bear pressure + below VWAP
        elif row['bear_pressure'] and row['close'] < row['vwap']:
            # VWAP slope filter: only trade if VWAP is falling (downtrend)
            if vwap_slope_filter and row['vwap_slope'] >= 0:
                continue
            signals.append({'direction': 'short', 'entry_price': entry_price, 'idx': i + 1, 'regime': regime, 'vol_z': row['vol_z']})
    
    return signals

def backtest(df, signals, tp=0.8, sl=0.5, max_bars=20):
    if not signals:
        return None
    
    wins, losses = 0, 0
    total_pnl = 0
    max_streak, curr_streak = 0, 0
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 5:
            continue
        
        entry = sig['entry_price']
        direction = sig['direction']
        
        tp_price = entry * (1 + (tp if direction == 'long' else -tp) / 100)
        sl_price = entry * (1 - (sl if direction == 'long' else -sl) / 100)
        
        pnl = 0
        win = False
        
        for j in range(idx + 1, min(idx + max_bars, len(df))):
            bar = df.iloc[j]
            if direction == 'long':
                if bar['low'] <= sl_price:
                    pnl, win = -sl, False
                    break
                if bar['high'] >= tp_price:
                    pnl, win = tp, True
                    break
            else:
                if bar['high'] >= sl_price:
                    pnl, win = -sl, False
                    break
                if bar['low'] <= tp_price:
                    pnl, win = tp, True
                    break
        
        if pnl == 0:
            exit_p = df.iloc[min(idx + max_bars - 1, len(df) - 1)]['close']
            pnl = (exit_p - entry) / entry * 100 if direction == 'long' else (entry - exit_p) / entry * 100
            win = pnl > 0
        
        total_pnl += pnl
        if win:
            wins += 1
            curr_streak = 0
        else:
            losses += 1
            curr_streak += 1
            max_streak = max(max_streak, curr_streak)
    
    total = wins + losses
    return {
        'trades': total, 'win_rate': wins/total*100 if total > 0 else 0,
        'avg_pnl': total_pnl/total if total > 0 else 0,
        'total_pnl': total_pnl, 'max_streak': max_streak
    }

def run_tests(symbol, df):
    print(f"\n[{symbol}] 5Min — Running Tests")
    print("=" * 60)
    
    results = {}
    
    # TEST 1: Trend-only vs Trend+Expansion
    print("\nTEST 1: Trend-Only vs Trend+Expansion (Z > 1.8)")
    print("-" * 60)
    
    # Baseline: Trend + Expansion
    sigs_baseline = generate_signals(df, 1.8, regime_filter=None)
    baseline = backtest(df, sigs_baseline)
    
    # Trend only
    sigs_trend = generate_signals(df, 1.8, regime_filter='trend')
    trend_only = backtest(df, sigs_trend)
    
    print(f"  Baseline (trend+expansion): {baseline['trades']} trades, {baseline['win_rate']:.1f}% WR, {baseline['avg_pnl']:+.3f}% avg")
    print(f"  Trend-only:                 {trend_only['trades']} trades, {trend_only['win_rate']:.1f}% WR, {trend_only['avg_pnl']:+.3f}% avg")
    
    if trend_only['avg_pnl'] > baseline['avg_pnl']:
        print(f"  >>> TREND-ONLY WINS: +{trend_only['avg_pnl'] - baseline['avg_pnl']:.3f}% better expectancy")
    else:
        print(f"  >>> BASELINE WINS: +{baseline['avg_pnl'] - trend_only['avg_pnl']:.3f}% better expectancy")
    
    results['baseline'] = baseline
    results['trend_only'] = trend_only
    
    # TEST 2: Volume threshold sweep (trend only)
    print(f"\nTEST 2: Volume Threshold Sweep (Trend Only)")
    print("-" * 60)
    print(f"  {'Z Threshold':>12} {'Trades':>8} {'WR%':>8} {'Avg%':>10} {'Total%':>10}")
    print(f"  {'-'*55}")
    
    best_z, best_avg = None, -999
    for z in [1.5, 1.8, 2.0, 2.5, 3.0]:
        sigs = generate_signals(df, z, regime_filter='trend')
        res = backtest(df, sigs)
        if res:
            print(f"  Z > {z:<6.1f} {res['trades']:>8} {res['win_rate']:>7.1f}% {res['avg_pnl']:>+9.3f}% {res['total_pnl']:>+9.2f}%")
            if res['avg_pnl'] > best_avg:
                best_avg = res['avg_pnl']
                best_z = z
    
    print(f"  >>> BEST: Z > {best_z} with {best_avg:+.3f}% avg")
    results['best_z'] = best_z
    
    # TEST 3: VWAP slope filter
    print(f"\nTEST 3: VWAP Slope Filter (Trend Only, Z > 1.8)")
    print("-" * 60)
    
    # Without slope filter
    sigs_no_slope = generate_signals(df, 1.8, regime_filter='trend', vwap_slope_filter=False)
    res_no_slope = backtest(df, sigs_no_slope)
    
    # With slope filter (only trade when price direction aligns with VWAP slope)
    sigs_slope = generate_signals(df, 1.8, regime_filter='trend', vwap_slope_filter=True)
    res_slope = backtest(df, sigs_slope)
    
    print(f"  Without slope filter: {res_no_slope['trades']} trades, {res_no_slope['win_rate']:.1f}% WR, {res_no_slope['avg_pnl']:+.3f}% avg")
    print(f"  With slope filter:    {res_slope['trades']} trades, {res_slope['win_rate']:.1f}% WR, {res_slope['avg_pnl']:+.3f}% avg")
    
    if res_slope['avg_pnl'] > res_no_slope['avg_pnl']:
        print(f"  >>> VWAP Slope Filter WINS: +{res_slope['avg_pnl'] - res_no_slope['avg_pnl']:.3f}% better expectancy")
    else:
        print(f"  >>> No Filter WINS: +{res_no_slope['avg_pnl'] - res_slope['avg_pnl']:.3f}% better expectancy")
    
    results['no_slope'] = res_no_slope
    results['with_slope'] = res_slope
    
    return results

def main():
    print("=" * 70)
    print("BOOF 24.1 — TESTS: Trend-Only + VWAP Slope Filter")
    print("=" * 70)
    
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=90)
    
    all_results = {}
    
    for symbol in ['NFLX', 'AAPL', 'AMD', 'NVDA']:
        df = fetch_data(symbol, '5Min', start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df is None:
            print(f"[{symbol}] No data")
            continue
        
        print(f"[{symbol}] Loaded {len(df)} bars")
        all_results[symbol] = run_tests(symbol, df)
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY: Best Configuration per Symbol")
    print("=" * 70)
    print(f"{'Symbol':<8} {'Best Config':<25} {'Avg%':>10} {'Trades':>8}")
    print("-" * 70)
    
    for symbol, res in all_results.items():
        if res:
            # Find best config
            configs = {
                'baseline': res.get('baseline', {}),
                'trend_only': res.get('trend_only', {}),
                'with_slope': res.get('with_slope', {})
            }
            best_config = max(configs.items(), key=lambda x: x[1].get('avg_pnl', -999))
            print(f"{symbol:<8} {best_config[0]:<25} {best_config[1].get('avg_pnl', 0):>+9.3f}% {best_config[1].get('trades', 0):>7}")

if __name__ == '__main__':
    main()
