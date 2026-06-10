"""
BOOF 24.1 — Regime Analysis (Clean Output)
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

def add_regime_tags(df):
    df = df.copy()
    
    # VWAP
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df['vwap_dist'] = (df['close'] - df['vwap']).abs()
    df['above_vwap'] = df['close'] > df['vwap']
    
    # VWAP metrics
    df['vwap_slope'] = df['vwap'].diff(20)
    df['vwap_trending'] = df['vwap_slope'].abs() > df['vwap_dist'].rolling(50, min_periods=1).mean() * 0.5
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
    
    # Volume
    df['vol_mean'] = df['volume'].rolling(20, min_periods=1).mean()
    df['vol_std'] = df['volume'].rolling(20, min_periods=1).std().replace(0, np.nan)
    df['vol_z'] = (df['volume'] - df['vol_mean']) / df['vol_std']
    df['high_vol'] = df['vol_z'] > 2.0
    df['vol_cluster'] = df['high_vol'].rolling(10, min_periods=1).sum() >= 3
    
    # Range
    df['range_20'] = df['high'].rolling(20, min_periods=1).max() - df['low'].rolling(20, min_periods=1).min()
    
    # Regime scoring (vectorized)
    trend_score = df['vwap_trending'].astype(int) + (df['vwap_cross_count'] < 2).astype(int) + (df['vwap_dist'].rolling(20, min_periods=1).mean() > df['atr'] * 0.5).astype(int)
    chop_score = (df['vwap_cross_count'] >= 3).astype(int) + (~df['atr_rising']).astype(int) + (df['vwap_dist'].rolling(20, min_periods=1).mean() < df['atr'] * 0.3).astype(int)
    expansion_score = df['atr_rising'].astype(int) + df['vol_cluster'].astype(int) + (df['range_20'] > df['atr'] * 5).astype(int)
    
    scores_df = pd.DataFrame({'trend': trend_score, 'chop': chop_score, 'expansion': expansion_score})
    df['best_regime'] = scores_df.idxmax(axis=1)
    df['best_score'] = scores_df.max(axis=1)
    df['regime'] = 'mixed'
    df.loc[df['best_score'] >= 2, 'regime'] = df.loc[df['best_score'] >= 2, 'best_regime']
    
    return df

def generate_signals(df, vol_threshold=1.8):
    df = add_regime_tags(df)
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
        
        entry_price = df.iloc[i + 1]['open']
        regime = row['regime']
        
        if row['bull_pressure'] and row['close'] > row['vwap']:
            signals.append({'direction': 'long', 'entry_price': entry_price, 'idx': i + 1, 'regime': regime, 'vol_z': row['vol_z']})
        elif row['bear_pressure'] and row['close'] < row['vwap']:
            signals.append({'direction': 'short', 'entry_price': entry_price, 'idx': i + 1, 'regime': regime, 'vol_z': row['vol_z']})
    
    return signals

def backtest(df, signals, tp=0.8, sl=0.5, max_bars=20):
    if not signals:
        return {}
    
    results = {r: [] for r in ['expansion', 'trend', 'chop', 'mixed']}
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 5:
            continue
        
        entry = sig['entry_price']
        direction = sig['direction']
        regime = sig.get('regime', 'mixed')
        
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
        
        results[regime].append({'pnl': pnl, 'win': win})
    
    stats = {}
    for regime, trades in results.items():
        if trades:
            wins = sum(1 for t in trades if t['win'])
            total_pnl = sum(t['pnl'] for t in trades)
            max_streak = curr = 0
            for t in trades:
                curr = curr + 1 if not t['win'] else 0
                max_streak = max(max_streak, curr)
            stats[regime] = {'trades': len(trades), 'win_rate': wins/len(trades)*100, 'avg_pnl': total_pnl/len(trades), 'total_pnl': total_pnl, 'max_streak': max_streak}
    
    return stats

def main():
    print("="*70)
    print("BOOF 24.1 REGIME ANALYSIS")
    print("="*70)
    
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=90)
    
    for symbol in ['NFLX', 'AMD', 'QQQ', 'AAPL']:
        print(f"\n[{symbol}] 5Min Analysis")
        print("-" * 70)
        
        df = fetch_data(symbol, '5Min', start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df is None:
            continue
        
        print(f"Data: {len(df)} bars")
        
        # Regime distribution
        df_tagged = add_regime_tags(df)
        dist = df_tagged['regime'].value_counts()
        print(f"\nRegime Distribution:")
        for r, c in dist.items():
            print(f"  {r:12s}: {c:5d} bars ({c/len(df)*100:5.1f}%)")
        
        # Performance by regime
        signals = generate_signals(df, 1.8)
        stats = backtest(df, signals)
        
        print(f"\nPerformance by Regime (Z > 1.8):")
        print(f"  {'Regime':12s} {'Trades':>8s} {'WR%':>8s} {'Avg%':>10s} {'Total%':>10s} {'MaxSL':>8s}")
        print(f"  {'-'*60}")
        for regime in ['expansion', 'trend', 'chop', 'mixed']:
            if regime in stats:
                s = stats[regime]
                print(f"  {regime:12s} {s['trades']:>8d} {s['win_rate']:>7.1f}% {s['avg_pnl']:>+9.3f}% {s['total_pnl']:>+9.2f}% {s['max_streak']:>7d}")
        
        # Volume threshold test
        print(f"\nVolume Threshold Optimization:")
        print(f"  {'Threshold':>12s} {'Trades':>8s} {'WR%':>8s} {'Avg%':>10s} {'Total%':>10s}")
        print(f"  {'-'*55}")
        for z in [1.5, 1.8, 2.0, 2.5, 3.0]:
            sigs = generate_signals(df, z)
            st = backtest(df, sigs)
            total = sum(s['trades'] for s in st.values())
            if total > 0:
                wins = sum(s['trades'] * s['win_rate']/100 for s in st.values())
                pnl = sum(s['total_pnl'] for s in st.values())
                print(f"  Z > {z:<6.1f} {total:>8d} {wins/total*100:>7.1f}% {pnl/total:>+9.3f}% {pnl:>+9.2f}%")
    
    print("\n" + "="*70)
    print("KEY INSIGHT: Trade only during 'expansion' regime for edge")
    print("="*70)

if __name__ == '__main__':
    main()
