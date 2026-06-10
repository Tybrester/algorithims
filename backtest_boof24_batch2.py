"""
BOOF 24.1 — Tests 4, 5, 6 on META, AMZN, TSLA, AAPL, MSFT, GOOGL, AMD, SHOP, COIN
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

SYMBOLS = ['META', 'AMZN', 'TSLA', 'AAPL', 'MSFT', 'GOOGL', 'AMD', 'SHOP', 'COIN']

def fetch_data(symbol, start, end):
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    
    chunk_size = 60
    current_start = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    
    while current_start < end_dt:
        chunk_end = min(current_start + timedelta(days=chunk_size), end_dt)
        params = {
            'timeframe': '5Min', 'start': current_start.strftime('%Y-%m-%d'),
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
    df = df.set_index('timestamp').sort_index()
    
    # Add time features
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['session'] = 'other'
    df.loc[(df['hour'] == 9) & (df['minute'] >= 30) | (df['hour'] == 10), 'session'] = 'open'
    df.loc[(df['hour'] >= 11) & (df['hour'] < 13), 'session'] = 'midday'
    df.loc[(df['hour'] >= 13) & (df['hour'] < 16), 'session'] = 'afternoon'
    
    return df

def add_indicators(df):
    df = df.copy()
    
    # VWAP
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df['vwap_slope'] = df['vwap'].diff(20)
    df['above_vwap'] = df['close'] > df['vwap']
    
    # Volume
    df['vol_mean'] = df['volume'].rolling(20, min_periods=1).mean()
    df['vol_std'] = df['volume'].rolling(20, min_periods=1).std().replace(0, np.nan)
    df['vol_z'] = (df['volume'] - df['vol_mean']) / df['vol_std']
    df['vol_prev'] = df['volume'].shift(1)
    df['vol_increasing'] = df['volume'] > df['vol_prev']
    df['vol_3bar'] = (df['volume'] > df['volume'].shift(1)) & (df['volume'].shift(1) > df['volume'].shift(2))
    
    # ATR
    tr = pd.concat([df['high'] - df['low'], (df['high'] - df['close'].shift(1)).abs(), (df['low'] - df['close'].shift(1)).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14, min_periods=1).mean()
    df['body_size'] = (df['close'] - df['open']).abs()
    
    # Breakout levels
    df['prev_10_high'] = df['high'].rolling(10, min_periods=1).max().shift(1)
    df['prev_10_low'] = df['low'].rolling(10, min_periods=1).min().shift(1)
    
    # Direction
    df['bull'] = df['close'] > df['open']
    df['bear'] = df['close'] < df['open']
    
    return df

def generate_signals(df, config):
    df = add_indicators(df)
    signals = []
    
    for i in range(30, len(df) - 1):
        row = df.iloc[i]
        
        if pd.isna(row['atr']) or pd.isna(row['vol_z']):
            continue
        if row['body_size'] < row['atr'] * 0.3:
            continue
        if row['vol_z'] < config.get('vol_z', 1.8):
            continue
        if config.get('session') and row['session'] != config['session']:
            continue
        if config.get('vol_trend') == 'increasing' and not row['vol_increasing']:
            continue
        if config.get('vol_trend') == '3bar' and not row['vol_3bar']:
            continue
        
        entry_price = df.iloc[i + 1]['open']
        session = row['session']
        
        # LONG
        if row['bull'] and row['close'] > row['vwap'] and row['vwap_slope'] > 0:
            if config.get('breakout') and row['close'] <= row['prev_10_high']:
                continue
            signals.append({'direction': 'long', 'entry_price': entry_price, 'idx': i + 1, 'session': session, 'timestamp': df.index[i + 1]})
        
        # SHORT
        elif row['bear'] and row['close'] < row['vwap'] and row['vwap_slope'] < 0:
            if config.get('breakout') and row['close'] >= row['prev_10_low']:
                continue
            signals.append({'direction': 'short', 'entry_price': entry_price, 'idx': i + 1, 'session': session, 'timestamp': df.index[i + 1]})
    
    return signals

def backtest(df, signals, tp=0.8, sl=0.5, max_bars=20):
    if not signals:
        return None, {}
    
    by_session = {'open': [], 'midday': [], 'afternoon': [], 'other': []}
    total_pnl = 0
    wins, losses = 0, 0
    max_streak, curr = 0, 0
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 5:
            continue
        
        entry = sig['entry_price']
        direction = sig['direction']
        session = sig.get('session', 'other')
        
        tp_price = entry * (1 + (tp if direction == 'long' else -tp) / 100)
        sl_price = entry * (1 - (sl if direction == 'long' else -sl) / 100)
        
        pnl, win = 0, False
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
            wins, curr = wins + 1, 0
        else:
            losses, curr = losses + 1, curr + 1
            max_streak = max(max_streak, curr)
        
        by_session[session].append({'pnl': pnl, 'win': win})
    
    total = wins + losses
    overall = {'trades': total, 'win_rate': wins/total*100 if total else 0, 'avg_pnl': total_pnl/total if total else 0, 'total_pnl': total_pnl, 'max_streak': max_streak}
    
    session_stats = {}
    for sess, trades in by_session.items():
        if trades:
            w = sum(1 for t in trades if t['win'])
            p = sum(t['pnl'] for t in trades)
            session_stats[sess] = {'trades': len(trades), 'win_rate': w/len(trades)*100, 'avg_pnl': p/len(trades), 'total_pnl': p}
    
    return overall, session_stats

def run_symbol(symbol, df):
    print(f"\n{'='*60}")
    print(f"[{symbol}] BOOF 24.1 Analysis")
    print(f"{'='*60}")
    
    # Test 4: Time-of-day
    print(f"\nTEST 4: Time-of-Day (Z > 1.8, VWAP slope)")
    print(f"{'Session':<12} {'Trades':>8} {'WR%':>8} {'Avg%':>10} {'Total%':>10}")
    print(f"{'-'*52}")
    
    sessions = ['open', 'midday', 'afternoon']
    for session in sessions:
        sigs = generate_signals(df, {'vol_z': 1.8, 'session': session})
        overall, _ = backtest(df, sigs)
        if overall:
            print(f"{session:<12} {overall['trades']:>8} {overall['win_rate']:>7.1f}% {overall['avg_pnl']:>+9.3f}% {overall['total_pnl']:>+9.2f}%")
    
    # All combined
    sigs_all = generate_signals(df, {'vol_z': 1.8})
    overall_all, _ = backtest(df, sigs_all)
    if overall_all:
        print(f"{'all':<12} {overall_all['trades']:>8} {overall_all['win_rate']:>7.1f}% {overall_all['avg_pnl']:>+9.3f}% {overall_all['total_pnl']:>+9.2f}%")
    
    # Test 5: Volume trend
    print(f"\nTEST 5: Volume Trend Filter")
    print(f"{'Filter':<20} {'Trades':>8} {'WR%':>8} {'Avg%':>10} {'Total%':>10}")
    print(f"{'-'*60}")
    
    configs = [('Baseline', {'vol_z': 1.8}), ('Vol > Prev', {'vol_z': 1.8, 'vol_trend': 'increasing'}), ('3-Bar', {'vol_z': 1.8, 'vol_trend': '3bar'})]
    for name, cfg in configs:
        sigs = generate_signals(df, cfg)
        res, _ = backtest(df, sigs)
        if res:
            print(f"{name:<20} {res['trades']:>8} {res['win_rate']:>7.1f}% {res['avg_pnl']:>+9.3f}% {res['total_pnl']:>+9.2f}%")
    
    # Test 6: Breakout
    print(f"\nTEST 6: Breakout Confirmation")
    print(f"{'Config':<20} {'Trades':>8} {'WR%':>8} {'Avg%':>10} {'Total%':>10}")
    print(f"{'-'*60}")
    
    breakout_configs = [('Baseline', {'vol_z': 1.8}), ('Breakout', {'vol_z': 1.8, 'breakout': True})]
    for name, cfg in breakout_configs:
        sigs = generate_signals(df, cfg)
        res, _ = backtest(df, sigs)
        if res:
            print(f"{name:<20} {res['trades']:>8} {res['win_rate']:>7.1f}% {res['avg_pnl']:>+9.3f}% {res['total_pnl']:>+9.2f}%")

def main():
    print("="*60)
    print("BOOF 24.1 — Batch 2: META, AMZN, TSLA, AAPL, MSFT, GOOGL, AMD, SHOP, COIN")
    print("="*60)
    
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=90)
    
    for symbol in SYMBOLS:
        df = fetch_data(symbol, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df is None:
            print(f"[{symbol}] No data")
            continue
        
        print(f"[{symbol}] Loaded {len(df)} bars")
        run_symbol(symbol, df)
    
    print("\n" + "="*60)
    print("DONE")
    print("="*60)

if __name__ == '__main__':
    main()
