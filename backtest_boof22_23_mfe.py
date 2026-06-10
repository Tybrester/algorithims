"""
BOOF 22 & 23 — Maximum Favorable Excursion (MFE) Analysis
Tracks how far each trade goes before exit
Target levels: 0.03%, 0.04%, 0.05%, 0.06%, 0.07%, 0.08%, 0.10%
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

SYMBOLS = ['SPY', 'QQQ', 'AAPL', 'NVDA', 'META', 'MSFT', 'TSLA', 'AMD', 'NFLX']
TIMEFRAMES = ['1Min', '5Min']

def fetch_data(symbol, timeframe, start, end):
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

def boof22_signals(df):
    """Boof 22: Volume cluster + fractal detection + SR proximity"""
    df = df.copy()
    
    # ATR
    tr = pd.concat([df['high'] - df['low'], (df['high'] - df['close'].shift(1)).abs(), (df['low'] - df['close'].shift(1)).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # Volume
    df['vol_sma'] = df['volume'].rolling(50).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma']
    
    # Fractals
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
        
        # SHORT: near resistance + bearish
        for h in highs:
            if abs(current['close'] - h) < atr * 0.6 and current['close'] < prev['close']:
                signals.append({
                    'direction': 'short', 'entry': df.iloc[i+1]['open'], 'idx': i + 1,
                    'timestamp': df.index[i+1], 'reason': 'boof22_short'
                })
                break
        
        # LONG: near support + bullish
        for l in lows:
            if abs(current['close'] - l) < atr * 0.6 and current['close'] > prev['close']:
                signals.append({
                    'direction': 'long', 'entry': df.iloc[i+1]['open'], 'idx': i + 1,
                    'timestamp': df.index[i+1], 'reason': 'boof22_long'
                })
                break
    
    return signals

def boof23_signals(df):
    """Boof 23: SR cluster + ZigZag regime + engulfing"""
    df = df.copy()
    
    # ATR
    tr = pd.concat([df['high'] - df['low'], (df['high'] - df['close'].shift(1)).abs(), (df['low'] - df['close'].shift(1)).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # Volume
    df['vol_sma'] = df['volume'].rolling(50).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma']
    
    # Zigzag (3-bar pivot)
    df['zz_high'] = (df['high'] > df['high'].shift(1)) & (df['high'] > df['high'].shift(2)) & (df['high'] > df['high'].shift(-1)) & (df['high'] > df['high'].shift(-2))
    df['zz_low'] = (df['low'] < df['low'].shift(1)) & (df['low'] < df['low'].shift(2)) & (df['low'] < df['low'].shift(-1)) & (df['low'] < df['low'].shift(-2))
    
    # Trend
    df['trend'] = 0
    for i in range(10, len(df)):
        recent_highs = df.iloc[i-10:i]['zz_high'].sum()
        recent_lows = df.iloc[i-10:i]['zz_low'].sum()
        if recent_highs > recent_lows:
            df.iloc[i, df.columns.get_loc('trend')] = 1
        elif recent_lows > recent_highs:
            df.iloc[i, df.columns.get_loc('trend')] = -1
    
    # Engulfing
    df['bull_engulf'] = (df['close'] > df['open']) & (df['open'] < df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
    df['bear_engulf'] = (df['close'] < df['open']) & (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))
    
    signals = []
    
    for i in range(20, len(df) - 1):
        current = df.iloc[i]
        
        if current['vol_ratio'] < 1.3 or pd.isna(current['atr']):
            continue
        
        # LONG: downtrend + engulfing
        if current['trend'] == -1 and current['bull_engulf']:
            signals.append({
                'direction': 'long', 'entry': df.iloc[i+1]['open'], 'idx': i + 1,
                'timestamp': df.index[i+1], 'reason': 'boof23_long'
            })
        
        # SHORT: uptrend + engulfing
        elif current['trend'] == 1 and current['bear_engulf']:
            signals.append({
                'direction': 'short', 'entry': df.iloc[i+1]['open'], 'idx': i + 1,
                'timestamp': df.index[i+1], 'reason': 'boof23_short'
            })
    
    return signals

def backtest_mfe(df, signals, max_bars=30):
    """
    Track Maximum Favorable Excursion (MFE) for each trade
    How far does price go in favor before exit or time out?
    """
    if not signals:
        return []
    
    results = []
    
    # Target levels to check
    levels = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.15, 0.20, 0.30]
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 2:
            continue
        
        entry = sig['entry']
        direction = sig['direction']
        
        max_favorable_pct = 0
        max_unfavorable_pct = 0
        exit_price = None
        exit_idx = None
        
        for j in range(idx + 1, min(idx + max_bars, len(df))):
            bar = df.iloc[j]
            
            # Calculate current P&L %
            if direction == 'long':
                current_high_pct = (bar['high'] - entry) / entry * 100
                current_low_pct = (bar['low'] - entry) / entry * 100
            else:
                current_high_pct = (entry - bar['low']) / entry * 100
                current_low_pct = (entry - bar['high']) / entry * 100
            
            # Track max favorable (best profit)
            if current_high_pct > max_favorable_pct:
                max_favorable_pct = current_high_pct
            
            # Track max unfavorable (worst drawdown)
            if current_low_pct < max_unfavorable_pct:
                max_unfavorable_pct = current_low_pct
            
            # Check if we hit a level
            if exit_price is None:
                for level in levels:
                    if max_favorable_pct >= level:
                        exit_price = entry * (1 + level/100) if direction == 'long' else entry * (1 - level/100)
                        exit_idx = j
                        break
        
        # If no level hit, use final close
        if exit_price is None:
            exit_idx = min(idx + max_bars - 1, len(df) - 1)
            exit_price = df.iloc[exit_idx]['close']
        
        # Final P&L
        if direction == 'long':
            final_pnl = (exit_price - entry) / entry * 100
        else:
            final_pnl = (entry - exit_price) / entry * 100
        
        # Determine which level was hit (if any)
        level_hit = None
        for level in levels:
            if max_favorable_pct >= level:
                level_hit = level
        
        results.append({
            'direction': direction,
            'entry': entry,
            'max_fav_pct': max_favorable_pct,
            'max_unfav_pct': max_unfavorable_pct,
            'final_pnl': final_pnl,
            'level_hit': level_hit,
            'bars_held': exit_idx - idx if exit_idx else 0,
            'timestamp': sig['timestamp'],
            'reason': sig['reason']
        })
    
    return results

def analyze_mfe(results, name):
    """Analyze MFE distribution"""
    if not results:
        print(f"[{name}] No trades")
        return
    
    df_res = pd.DataFrame(results)
    total = len(df_res)
    
    print(f"\n[{name}] MFE Analysis — {total} trades")
    print("-" * 60)
    
    # Distribution by level hit
    levels = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.15, 0.20, 0.30]
    
    print(f"{'Level':>10} {'Hit':>8} {'% of Trades':>12} {'Avg Final P&L':>15}")
    print("-" * 60)
    
    cumulative = 0
    for level in levels:
        hit = df_res[df_res['max_fav_pct'] >= level]
        count = len(hit)
        pct = count / total * 100
        cumulative += count
        avg_final = hit['final_pnl'].mean() if len(hit) > 0 else 0
        print(f"{level:>9.2f}% {count:>8} {pct:>11.1f}% {avg_final:>+14.3f}%")
    
    # Summary stats
    print("-" * 60)
    print(f"Never hit 0.03%: {len(df_res[df_res['max_fav_pct'] < 0.03])} trades ({len(df_res[df_res['max_fav_pct'] < 0.03])/total*100:.1f}%)")
    print(f"Max MFE seen: {df_res['max_fav_pct'].max():.3f}%")
    print(f"Avg MFE: {df_res['max_fav_pct'].mean():.3f}%")
    print(f"Avg Final P&L: {df_res['final_pnl'].mean():+.3f}%")
    print(f"Win Rate: {len(df_res[df_res['final_pnl'] > 0])/total*100:.1f}%")

def main():
    print("="*70)
    print("BOOF 22 & 23 — Maximum Favorable Excursion (MFE) Analysis")
    print("1 Year | 1m & 5m | Tracking price excursions")
    print("="*70)
    
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=365)
    
    all_mfe_22_1m = []
    all_mfe_22_5m = []
    all_mfe_23_1m = []
    all_mfe_23_5m = []
    
    for symbol in SYMBOLS:
        print(f"\n{'='*70}")
        print(f"[{symbol}] Fetching 1 year data...")
        
        # 1m data
        df_1m = fetch_data(symbol, '1Min', start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df_1m is not None:
            print(f"  1m: {len(df_1m)} bars")
            
            sig_22 = boof22_signals(df_1m)
            mfe_22 = backtest_mfe(df_1m, sig_22)
            all_mfe_22_1m.extend(mfe_22)
            
            sig_23 = boof23_signals(df_1m)
            mfe_23 = backtest_mfe(df_1m, sig_23)
            all_mfe_23_1m.extend(mfe_23)
        
        # 5m data
        df_5m = fetch_data(symbol, '5Min', start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df_5m is not None:
            print(f"  5m: {len(df_5m)} bars")
            
            sig_22 = boof22_signals(df_5m)
            mfe_22 = backtest_mfe(df_5m, sig_22)
            all_mfe_22_5m.extend(mfe_22)
            
            sig_23 = boof23_signals(df_5m)
            mfe_23 = backtest_mfe(df_5m, sig_23)
            all_mfe_23_5m.extend(mfe_23)
    
    # Aggregate analysis
    print("\n" + "="*70)
    print("AGGREGATE MFE RESULTS (All Symbols Combined)")
    print("="*70)
    
    analyze_mfe(all_mfe_22_1m, "Boof 22 — 1Min")
    analyze_mfe(all_mfe_22_5m, "Boof 22 — 5Min")
    analyze_mfe(all_mfe_23_1m, "Boof 23 — 1Min")
    analyze_mfe(all_mfe_23_5m, "Boof 23 — 5Min")
    
    # Save detailed results
    date_str = datetime.now().strftime('%Y%m%d')
    pd.DataFrame(all_mfe_22_1m).to_csv(f'mfe_boof22_1m_{date_str}.csv', index=False)
    pd.DataFrame(all_mfe_22_5m).to_csv(f'mfe_boof22_5m_{date_str}.csv', index=False)
    pd.DataFrame(all_mfe_23_1m).to_csv(f'mfe_boof23_1m_{date_str}.csv', index=False)
    pd.DataFrame(all_mfe_23_5m).to_csv(f'mfe_boof23_5m_{date_str}.csv', index=False)
    
    print(f"\n[SAVED] mfe_*_{date_str}.csv files with detailed trade data")

if __name__ == '__main__':
    main()
