"""
BOOF 24.1 — Tests 4, 5, 6
#4: Time-of-day breakdown
#5: Relative Volume Trend (volume increasing)
#6: Breakout Confirmation (10-bar high/low)
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
    df = df.set_index('timestamp').sort_index()
    
    # Add time features
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['time_minutes'] = df['hour'] * 60 + df['minute']
    
    # Time sessions
    df['session'] = 'other'
    df.loc[(df['hour'] == 9) & (df['minute'] >= 30) | (df['hour'] == 10), 'session'] = 'open'  # 9:30-10:59
    df.loc[(df['hour'] >= 11) & (df['hour'] < 13), 'session'] = 'midday'  # 11:00-12:59
    df.loc[(df['hour'] >= 13) & (df['hour'] < 16), 'session'] = 'afternoon'  # 13:00-15:59
    
    return df

def add_indicators(df):
    """Add all technical indicators"""
    df = df.copy()
    
    # VWAP
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df['vwap_slope'] = df['vwap'].diff(20)
    df['above_vwap'] = df['close'] > df['vwap']
    
    # Volume metrics
    df['vol_mean'] = df['volume'].rolling(20, min_periods=1).mean()
    df['vol_std'] = df['volume'].rolling(20, min_periods=1).std().replace(0, np.nan)
    df['vol_z'] = (df['volume'] - df['vol_mean']) / df['vol_std']
    df['vol_prev'] = df['volume'].shift(1)
    df['vol_increasing'] = df['volume'] > df['vol_prev']
    df['vol_3bar_increasing'] = (df['volume'] > df['volume'].shift(1)) & (df['volume'].shift(1) > df['volume'].shift(2))
    
    # ATR
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14, min_periods=1).mean()
    df['body_size'] = (df['close'] - df['open']).abs()
    
    # Breakout levels
    df['prev_10_high'] = df['high'].rolling(10, min_periods=1).max().shift(1)
    df['prev_10_low'] = df['low'].rolling(10, min_periods=1).min().shift(1)
    
    # Direction
    df['bull_pressure'] = df['close'] > df['open']
    df['bear_pressure'] = df['close'] < df['open']
    
    return df

def generate_signals(df, config):
    """
    config options:
    - vol_z: volume z threshold (1.8)
    - vol_trend: None, 'increasing', '3bar'
    - breakout: False/True
    - session: None, 'open', 'midday', 'afternoon'
    """
    df = add_indicators(df)
    
    signals = []
    
    for i in range(30, len(df) - 1):
        row = df.iloc[i]
        
        # Basic filters
        if pd.isna(row['atr']) or pd.isna(row['vol_z']):
            continue
        if row['body_size'] < row['atr'] * 0.3:
            continue
        if row['vol_z'] < config.get('vol_z', 1.8):
            continue
        
        # Session filter
        if config.get('session') and row['session'] != config['session']:
            continue
        
        # Volume trend filter
        if config.get('vol_trend') == 'increasing' and not row['vol_increasing']:
            continue
        if config.get('vol_trend') == '3bar' and not row['vol_3bar_increasing']:
            continue
        
        entry_price = df.iloc[i + 1]['open']
        session = row['session']
        
        # LONG conditions
        if row['bull_pressure'] and row['close'] > row['vwap'] and row['vwap_slope'] > 0:
            # Breakout check
            if config.get('breakout') and row['close'] <= row['prev_10_high']:
                continue
            
            signals.append({
                'direction': 'long', 'entry_price': entry_price, 'idx': i + 1,
                'session': session, 'vol_z': row['vol_z'], 'timestamp': df.index[i + 1]
            })
        
        # SHORT conditions
        elif row['bear_pressure'] and row['close'] < row['vwap'] and row['vwap_slope'] < 0:
            # Breakout check
            if config.get('breakout') and row['close'] >= row['prev_10_low']:
                continue
            
            signals.append({
                'direction': 'short', 'entry_price': entry_price, 'idx': i + 1,
                'session': session, 'vol_z': row['vol_z'], 'timestamp': df.index[i + 1]
            })
    
    return signals

def backtest(df, signals, tp=0.8, sl=0.5, max_bars=20):
    if not signals:
        return None, {}
    
    by_session = {'open': [], 'midday': [], 'afternoon': [], 'other': []}
    wins, losses = 0, 0
    total_pnl = 0
    max_streak, curr_streak = 0, 0
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 5:
            continue
        
        entry = sig['entry_price']
        direction = sig['direction']
        session = sig.get('session', 'other')
        
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
        
        by_session[session].append({'pnl': pnl, 'win': win})
    
    total = wins + losses
    overall = {
        'trades': total, 'win_rate': wins/total*100 if total > 0 else 0,
        'avg_pnl': total_pnl/total if total > 0 else 0,
        'total_pnl': total_pnl, 'max_streak': max_streak
    }
    
    # Session breakdown
    session_stats = {}
    for sess, trades in by_session.items():
        if trades:
            w = sum(1 for t in trades if t['win'])
            p = sum(t['pnl'] for t in trades)
            session_stats[sess] = {
                'trades': len(trades), 'win_rate': w/len(trades)*100,
                'avg_pnl': p/len(trades), 'total_pnl': p
            }
    
    return overall, session_stats

def run_all_tests(symbol, df):
    print(f"\n{'='*70}")
    print(f"[{symbol}] BOOF 24.1 — Tests 4, 5, 6")
    print(f"{'='*70}")
    
    # TEST 4: Time-of-day breakdown
    print(f"\n{'='*70}")
    print("TEST #4: Time-of-Day Breakdown")
    print(f"{'='*70}")
    print(f"Config: Z > 1.8, VWAP slope filter")
    print(f"\n{'Session':<15} {'Trades':>8} {'WR%':>8} {'Avg%':>10} {'Total%':>10}")
    print(f"{'-'*55}")
    
    sessions = ['open', 'midday', 'afternoon']
    session_results = {}
    
    for session in sessions:
        sigs = generate_signals(df, {'vol_z': 1.8, 'session': session, 'vwap_slope_filter': True})
        overall, sess_stats = backtest(df, sigs)
        if overall:
            session_results[session] = overall
            print(f"{session:<15} {overall['trades']:>8} {overall['win_rate']:>7.1f}% {overall['avg_pnl']:>+9.3f}% {overall['total_pnl']:>+9.2f}%")
    
    # All sessions combined for reference
    sigs_all = generate_signals(df, {'vol_z': 1.8, 'vwap_slope_filter': True})
    overall_all, _ = backtest(df, sigs_all)
    if overall_all:
        print(f"{'all':<15} {overall_all['trades']:>8} {overall_all['win_rate']:>7.1f}% {overall_all['avg_pnl']:>+9.3f}% {overall_all['total_pnl']:>+9.2f}%")
    
    best_session = max(session_results.items(), key=lambda x: x[1]['avg_pnl']) if session_results else None
    if best_session:
        print(f"\n>>> BEST SESSION: {best_session[0].upper()} with {best_session[1]['avg_pnl']:+.3f}% avg")
    
    # TEST 5: Relative Volume Trend
    print(f"\n{'='*70}")
    print("TEST #5: Relative Volume Trend Filter")
    print(f"{'='*70}")
    print(f"{'Filter':<20} {'Trades':>8} {'WR%':>8} {'Avg%':>10} {'Total%':>10}")
    print(f"{'-'*60}")
    
    vol_configs = [
        ('Baseline (no filter)', {'vol_z': 1.8}),
        ('Vol > Previous', {'vol_z': 1.8, 'vol_trend': 'increasing'}),
        ('3-Bar Increasing', {'vol_z': 1.8, 'vol_trend': '3bar'}),
    ]
    
    vol_results = {}
    for name, config in vol_configs:
        sigs = generate_signals(df, config)
        res, _ = backtest(df, sigs)
        if res:
            vol_results[name] = res
            print(f"{name:<20} {res['trades']:>8} {res['win_rate']:>7.1f}% {res['avg_pnl']:>+9.3f}% {res['total_pnl']:>+9.2f}%")
    
    best_vol = max(vol_results.items(), key=lambda x: x[1]['avg_pnl']) if vol_results else None
    if best_vol:
        print(f"\n>>> BEST: {best_vol[0]} with {best_vol[1]['avg_pnl']:+.3f}% avg")
    
    # TEST 6: Breakout Confirmation
    print(f"\n{'='*70}")
    print("TEST #6: Breakout Confirmation (10-bar high/low)")
    print(f"{'='*70}")
    print(f"{'Config':<25} {'Trades':>8} {'WR%':>8} {'Avg%':>10} {'Total%':>10}")
    print(f"{'-'*65}")
    
    breakout_configs = [
        ('Baseline (no breakout)', {'vol_z': 1.8}),
        ('With Breakout Filter', {'vol_z': 1.8, 'breakout': True}),
    ]
    
    breakout_results = {}
    for name, config in breakout_configs:
        sigs = generate_signals(df, config)
        res, _ = backtest(df, sigs)
        if res:
            breakout_results[name] = res
            print(f"{name:<25} {res['trades']:>8} {res['win_rate']:>7.1f}% {res['avg_pnl']:>+9.3f}% {res['total_pnl']:>+9.2f}%")
    
    best_breakout = max(breakout_results.items(), key=lambda x: x[1]['avg_pnl']) if breakout_results else None
    if best_breakout:
        print(f"\n>>> BEST: {best_breakout[0]} with {best_breakout[1]['avg_pnl']:+.3f}% avg")
    
    return {
        'session': best_session,
        'vol_trend': best_vol,
        'breakout': best_breakout
    }

def main():
    print("="*70)
    print("BOOF 24.1 — TESTS 4, 5, 6")
    print("Time-of-Day | Volume Trend | Breakout Confirmation")
    print("="*70)
    
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=90)
    
    for symbol in ['NFLX', 'NVDA']:
        df = fetch_data(symbol, '5Min', start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df is None:
            print(f"[{symbol}] No data")
            continue
        
        print(f"[{symbol}] Loaded {len(df)} bars")
        run_all_tests(symbol, df)
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

if __name__ == '__main__':
    main()
