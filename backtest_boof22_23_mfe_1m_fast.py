"""
BOOF 22 & 23 — MFE Analysis on 1m (FAST VERSION)
3 months | 1m | 5 key symbols
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

SYMBOLS = ['SPY', 'QQQ', 'AAPL', 'NVDA', 'TSLA']

def fetch_data(symbol, start, end):
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    
    chunk_size = 30
    current_start = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    
    while current_start < end_dt:
        chunk_end = min(current_start + timedelta(days=chunk_size), end_dt)
        params = {
            'timeframe': '1Min', 'start': current_start.strftime('%Y-%m-%d'),
            'end': chunk_end.strftime('%Y-%m-%d'), 'limit': 10000, 'feed': 'iex'
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                bars = resp.json().get('bars', [])
                if bars:
                    all_bars.extend(bars)
        except:
            pass
        current_start = chunk_end
        time.sleep(0.15)
    
    if not all_bars:
        return None
    
    df = pd.DataFrame(all_bars)
    df['t'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'})
    return df.set_index('timestamp').sort_index()

def boof22_signals(df):
    df = df.copy()
    tr = pd.concat([df['high'] - df['low'], (df['high'] - df['close'].shift(1)).abs(), (df['low'] - df['close'].shift(1)).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['vol_sma'] = df['volume'].rolling(50).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma']
    df['fractal_high'] = (df['high'] > df['high'].shift(1)) & (df['high'] > df['high'].shift(-1))
    df['fractal_low'] = (df['low'] < df['low'].shift(1)) & (df['low'] < df['low'].shift(-1))
    
    signals = []
    for i in range(30, len(df) - 1):
        window = df.iloc[i-20:i]
        highs = window[window['fractal_high']]['high'].tail(3).values
        lows = window[window['fractal_low']]['low'].tail(3).values
        if len(highs) < 2 or len(lows) < 2:
            continue
        current = df.iloc[i]
        prev = df.iloc[i-1]
        if current['vol_ratio'] < 1.3 or pd.isna(current['atr']):
            continue
        atr = current['atr']
        for h in highs:
            if abs(current['close'] - h) < atr * 0.6 and current['close'] < prev['close']:
                signals.append({'direction': 'short', 'entry': df.iloc[i+1]['open'], 'idx': i + 1})
                break
        for l in lows:
            if abs(current['close'] - l) < atr * 0.6 and current['close'] > prev['close']:
                signals.append({'direction': 'long', 'entry': df.iloc[i+1]['open'], 'idx': i + 1})
                break
    return signals

def boof23_signals(df):
    df = df.copy()
    tr = pd.concat([df['high'] - df['low'], (df['high'] - df['close'].shift(1)).abs(), (df['low'] - df['close'].shift(1)).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['vol_sma'] = df['volume'].rolling(50).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma']
    df['zz_high'] = (df['high'] > df['high'].shift(1)) & (df['high'] > df['high'].shift(2)) & (df['high'] > df['high'].shift(-1)) & (df['high'] > df['high'].shift(-2))
    df['zz_low'] = (df['low'] < df['low'].shift(1)) & (df['low'] < df['low'].shift(2)) & (df['low'] < df['low'].shift(-1)) & (df['low'] < df['low'].shift(-2))
    df['trend'] = 0
    for i in range(10, len(df)):
        recent_highs = df.iloc[i-10:i]['zz_high'].sum()
        recent_lows = df.iloc[i-10:i]['zz_low'].sum()
        if recent_highs > recent_lows:
            df.iloc[i, df.columns.get_loc('trend')] = 1
        elif recent_lows > recent_highs:
            df.iloc[i, df.columns.get_loc('trend')] = -1
    df['bull_engulf'] = (df['close'] > df['open']) & (df['open'] < df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
    df['bear_engulf'] = (df['close'] < df['open']) & (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))
    
    signals = []
    for i in range(20, len(df) - 1):
        current = df.iloc[i]
        if current['vol_ratio'] < 1.3 or pd.isna(current['atr']):
            continue
        if current['trend'] == -1 and current['bull_engulf']:
            signals.append({'direction': 'long', 'entry': df.iloc[i+1]['open'], 'idx': i + 1})
        elif current['trend'] == 1 and current['bear_engulf']:
            signals.append({'direction': 'short', 'entry': df.iloc[i+1]['open'], 'idx': i + 1})
    return signals

def backtest_mfe(df, signals, max_bars=30):
    if not signals:
        return []
    
    results = []
    levels = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.15, 0.20]
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 2:
            continue
        entry = sig['entry']
        direction = sig['direction']
        max_fav = 0
        
        for j in range(idx + 1, min(idx + max_bars, len(df))):
            bar = df.iloc[j]
            if direction == 'long':
                current = (bar['high'] - entry) / entry * 100
            else:
                current = (entry - bar['low']) / entry * 100
            if current > max_fav:
                max_fav = current
        
        final_idx = min(idx + max_bars - 1, len(df) - 1)
        final_price = df.iloc[final_idx]['close']
        final_pnl = (final_price - entry) / entry * 100 if direction == 'long' else (entry - final_price) / entry * 100
        
        results.append({'max_fav': max_fav, 'final_pnl': final_pnl})
    
    return results

def analyze_mfe(results, name):
    if not results:
        print(f"[{name}] No trades")
        return
    
    df_res = pd.DataFrame(results)
    total = len(df_res)
    
    print(f"\n[{name}] MFE — {total} trades")
    print("-" * 65)
    print(f"{'Level':>10} {'Hit':>8} {'% Trades':>10} {'Avg Final':>12} {'Win Rate':>10}")
    print("-" * 65)
    
    levels = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.15, 0.20]
    
    for level in levels:
        hit = df_res[df_res['max_fav'] >= level]
        count = len(hit)
        pct = count / total * 100
        avg_final = hit['final_pnl'].mean() if len(hit) > 0 else 0
        win_rate = len(hit[hit['final_pnl'] > 0]) / len(hit) * 100 if len(hit) > 0 else 0
        print(f"{level:>9.2f}% {count:>8} {pct:>9.1f}% {avg_final:>+11.3f}% {win_rate:>9.1f}%")
    
    print("-" * 65)
    print(f"Never hit 0.03%: {len(df_res[df_res['max_fav'] < 0.03])} ({len(df_res[df_res['max_fav'] < 0.03])/total*100:.1f}%)")
    print(f"Max MFE: {df_res['max_fav'].max():.3f}% | Avg MFE: {df_res['max_fav'].mean():.3f}%")
    print(f"Avg Final: {df_res['final_pnl'].mean():+.3f}% | Win Rate: {len(df_res[df_res['final_pnl'] > 0])/total*100:.1f}%")

def main():
    print("="*70)
    print("BOOF 22 & 23 — MFE on 1Min (3 months, 5 symbols)")
    print("="*70)
    
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=90)
    
    all_22, all_23 = [], []
    
    for symbol in SYMBOLS:
        print(f"\n[{symbol}] Fetching...")
        df = fetch_data(symbol, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df is None:
            continue
        print(f"  {len(df)} bars")
        
        sig_22 = boof22_signals(df)
        mfe_22 = backtest_mfe(df, sig_22)
        all_22.extend(mfe_22)
        print(f"  Boof 22: {len(sig_22)} signals")
        
        sig_23 = boof23_signals(df)
        mfe_23 = backtest_mfe(df, sig_23)
        all_23.extend(mfe_23)
        print(f"  Boof 23: {len(sig_23)} signals")
    
    print("\n" + "="*70)
    print("AGGREGATE 1MIN MFE (3 months, 5 symbols)")
    print("="*70)
    analyze_mfe(all_22, "Boof 22 — 1Min")
    analyze_mfe(all_23, "Boof 23 — 1Min")
    
    # Save
    date_str = datetime.now().strftime('%Y%m%d')
    pd.DataFrame(all_22).to_csv(f'mfe_22_1m_{date_str}.csv', index=False)
    pd.DataFrame(all_23).to_csv(f'mfe_23_1m_{date_str}.csv', index=False)
    print(f"\n[SAVED] mfe_*_1m_{date_str}.csv")

if __name__ == '__main__':
    main()
