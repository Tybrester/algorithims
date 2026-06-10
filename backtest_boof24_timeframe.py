"""
BOOF 24.1 — Multi-Timeframe Volume Spike Strategy
Tests 1m, 5m, 10m on QQQ, SPY + 10 stocks
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

SYMBOLS = ['QQQ', 'SPY', 'AAPL', 'NVDA', 'META', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'AMD', 'NFLX', 'CRM']
TIMEFRAMES = ['1Min', '5Min', '10Min']

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
                print(f"  [WARN] {symbol} {timeframe}: Status {resp.status_code}")
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

def add_volume_filter(df, window=20, z_threshold=1.8):
    """
    Z-score volume spike filter
    Z > 1.8 = mild spike, Z > 2.5 = strong spike
    """
    df = df.copy()
    df['vol_mean'] = df['volume'].rolling(window).mean()
    df['vol_std'] = df['volume'].rolling(window).std()
    df['vol_z'] = (df['volume'] - df['vol_mean']) / df['vol_std']
    df['vol_spike_mild'] = df['vol_z'] > 1.8
    df['vol_spike_strong'] = df['vol_z'] > 2.5
    return df

def add_direction_pressure(df):
    """
    Bull/Bear pressure based on close vs open
    """
    df = df.copy()
    df['bull_pressure'] = df['close'] > df['open']
    df['bear_pressure'] = df['close'] < df['open']
    df['body_size'] = (df['close'] - df['open']).abs()
    return df

def add_vwap(df):
    """Volume Weighted Average Price"""
    df = df.copy()
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    return df

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def generate_signals_boof24(df, vol_threshold='mild', impulse_mult=0.3):
    """
    BOOF 24.1 Entry Rules:
    1. Volume spike (Z > 1.8 or 2.5)
    2. Direction pressure (close > open for long, < for short)
    3. Price vs VWAP (above for long, below for short)
    4. Impulse filter (body > ATR * 0.3)
    """
    df = add_volume_filter(df, window=20, z_threshold=1.8)
    df = add_direction_pressure(df)
    df = add_vwap(df)
    df['atr'] = compute_atr(df, 14)
    
    signals = []
    
    for i in range(30, len(df) - 1):
        row = df.iloc[i]
        
        # Skip if missing data
        if pd.isna(row['atr']) or pd.isna(row['vol_z']) or pd.isna(row['vwap']):
            continue
        
        # Volume spike check
        if vol_threshold == 'strong':
            vol_ok = row['vol_spike_strong']
        else:
            vol_ok = row['vol_spike_mild']
        
        if not vol_ok:
            continue
        
        # Impulse filter: body > ATR * 0.3
        if row['body_size'] < row['atr'] * impulse_mult:
            continue
        
        entry_price = df.iloc[i + 1]['open']
        timestamp = df.index[i + 1]
        
        # LONG: bull pressure + above VWAP
        if row['bull_pressure'] and row['close'] > row['vwap']:
            signals.append({
                'direction': 'long',
                'entry_price': entry_price,
                'timestamp': timestamp,
                'idx': i + 1,
                'vol_z': row['vol_z'],
                'body_atr_ratio': row['body_size'] / row['atr'] if row['atr'] > 0 else 0,
                'trigger': 'vol_spike_bull_vwap'
            })
        
        # SHORT: bear pressure + below VWAP
        elif row['bear_pressure'] and row['close'] < row['vwap']:
            signals.append({
                'direction': 'short',
                'entry_price': entry_price,
                'timestamp': timestamp,
                'idx': i + 1,
                'vol_z': row['vol_z'],
                'body_atr_ratio': row['body_size'] / row['atr'] if row['atr'] > 0 else 0,
                'trigger': 'vol_spike_bear_vwap'
            })
    
    return signals

def backtest_trades(df, signals, tp_pct=0.8, sl_pct=0.5, max_bars=20):
    """
    Backtest with percentage-based TP/SL
    TP: +0.8% / SL: -0.5% (scalping targets)
    """
    if not signals:
        return None
    
    wins, losses = 0, 0
    total_pnl = 0
    max_streak, curr_streak = 0, 0
    
    results = []
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 5:
            continue
        
        entry = sig['entry_price']
        direction = sig['direction']
        
        # Calculate TP/SL prices
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
            # Time exit
            exit_price = df.iloc[min(idx + max_bars - 1, len(df) - 1)]['close']
            if direction == 'long':
                pnl_pct = (exit_price - entry) / entry * 100
            else:
                pnl_pct = (entry - exit_price) / entry * 100
            win = pnl_pct > 0
            exit_type = 'time'
        
        total_pnl += pnl_pct
        if win:
            wins += 1
            curr_streak = 0
        else:
            losses += 1
            curr_streak += 1
            max_streak = max(max_streak, curr_streak)
        
        results.append({
            'direction': direction,
            'entry': entry,
            'pnl_pct': pnl_pct,
            'win': win,
            'exit_type': exit_type,
            'timestamp': sig['timestamp'],
            'vol_z': sig.get('vol_z', 0),
            'body_atr_ratio': sig.get('body_atr_ratio', 0)
        })
    
    total = wins + losses
    return {
        'trades': total,
        'wins': wins,
        'losses': losses,
        'win_rate': wins / total * 100 if total > 0 else 0,
        'total_pnl_pct': total_pnl,
        'avg_pnl_pct': total_pnl / total if total > 0 else 0,
        'max_streak': max_streak,
        'results': pd.DataFrame(results)
    }

def test_symbol_timeframe(symbol, timeframe, days_back=90):
    """Test one symbol on one timeframe"""
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back)
    
    print(f"\n[{symbol}] {timeframe} | Fetching...")
    df = fetch_data(symbol, timeframe, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    
    if df is None or len(df) < 100:
        print(f"  [SKIP] No data")
        return None
    
    print(f"  Bars: {len(df)} | {df.index[0].date()} to {df.index[-1].date()}")
    
    # Test mild volume spike (Z > 1.8)
    signals_mild = generate_signals_boof24(df, vol_threshold='mild', impulse_mult=0.3)
    result_mild = backtest_trades(df, signals_mild, tp_pct=0.8, sl_pct=0.5)
    
    # Test strong volume spike (Z > 2.5)
    signals_strong = generate_signals_boof24(df, vol_threshold='strong', impulse_mult=0.3)
    result_strong = backtest_trades(df, signals_strong, tp_pct=0.8, sl_pct=0.5)
    
    return {
        'symbol': symbol,
        'timeframe': timeframe,
        'mild': result_mild,
        'strong': result_strong
    }

def main():
    print("="*80)
    print("BOOF 24.1 MULTI-TIMEFRAME BACKTEST")
    print("Volume Spike (Z>1.8/2.5) + Direction + VWAP + Impulse Filter")
    print("="*80)
    print(f"Symbols: {SYMBOLS}")
    print(f"Timeframes: {TIMEFRAMES}")
    print("="*80)
    
    all_results = []
    
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            result = test_symbol_timeframe(symbol, timeframe, days_back=90)
            if result:
                all_results.append(result)
    
    if not all_results:
        print("\n[ERROR] No results")
        return
    
    # Summary table
    print("\n" + "="*80)
    print("SUMMARY: MILD SPIKE (Z > 1.8)")
    print("="*80)
    print(f"{'Symbol':<8} {'TF':<8} {'Trades':>10} {'WR%':>8} {'Total%':>10} {'Avg%':>10} {'MaxSL':>8}")
    print("-"*80)
    
    for r in all_results:
        if r['mild']:
            m = r['mild']
            print(f"{r['symbol']:<8} {r['timeframe']:<8} {m['trades']:>10} {m['win_rate']:>7.1f}% {m['total_pnl_pct']:>+9.2f}% {m['avg_pnl_pct']:>+9.2f}% {m['max_streak']:>7}")
    
    print("\n" + "="*80)
    print("SUMMARY: STRONG SPIKE (Z > 2.5)")
    print("="*80)
    print(f"{'Symbol':<8} {'TF':<8} {'Trades':>10} {'WR%':>8} {'Total%':>10} {'Avg%':>10} {'MaxSL':>8}")
    print("-"*80)
    
    for r in all_results:
        if r['strong']:
            s = r['strong']
            print(f"{r['symbol']:<8} {r['timeframe']:<8} {s['trades']:>10} {s['win_rate']:>7.1f}% {s['total_pnl_pct']:>+9.2f}% {s['avg_pnl_pct']:>+9.2f}% {s['max_streak']:>7}")
    
    # Find best combo
    print("\n" + "="*80)
    print("TOP PERFORMERS")
    print("="*80)
    
    best_mild = sorted([r for r in all_results if r['mild']], 
                       key=lambda x: x['mild']['avg_pnl_pct'], reverse=True)[:5]
    
    print("\nMild Spike (Z>1.8) - Top 5 by Avg P&L:")
    for r in best_mild:
        m = r['mild']
        print(f"  {r['symbol']} {r['timeframe']}: {m['avg_pnl_pct']:+.3f}% per trade, {m['win_rate']:.1f}% WR")
    
    best_strong = sorted([r for r in all_results if r['strong']], 
                         key=lambda x: x['strong']['avg_pnl_pct'], reverse=True)[:5]
    
    print("\nStrong Spike (Z>2.5) - Top 5 by Avg P&L:")
    for r in best_strong:
        s = r['strong']
        print(f"  {r['symbol']} {r['timeframe']}: {s['avg_pnl_pct']:+.3f}% per trade, {s['win_rate']:.1f}% WR")
    
    # Save all results
    date_str = datetime.now().strftime('%Y%m%d')
    for r in all_results:
        if r['mild'] and len(r['mild']['results']) > 0:
            r['mild']['results'].to_csv(f"boof24_{r['symbol']}_{r['timeframe']}_mild_{date_str}.csv", index=False)
        if r['strong'] and len(r['strong']['results']) > 0:
            r['strong']['results'].to_csv(f"boof24_{r['symbol']}_{r['timeframe']}_strong_{date_str}.csv", index=False)
    
    print(f"\n[SAVED] boof24_*_{date_str}.csv")

if __name__ == '__main__':
    main()
