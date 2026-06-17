"""
RVOL Filter Test
Adds RVOL 1.2-3.0 filter to Boof 22/23 signals
Compare: All signals vs RVOL-filtered signals
"""
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Alpaca API
ALPACA_KEY = os.getenv('ALPACA_KEY', 'PKGA4ZC63QX27XHF22CB6YP547')
ALPACA_SECRET = os.getenv('ALPACA_SECRET', 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q')
DATA_URL = 'https://data.alpaca.markets'

SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'TSLA', 'AMZN', 'MSFT', 'NFLX', 'CRM']
SLACK_MAX = 0.8

# RVOL sweet spot from earlier analysis
RVOL_MIN = 1.2
RVOL_MAX = 3.0

def fetch_data(symbol, start, end):
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    current_start = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    
    while current_start < end_dt:
        chunk_end = min(current_start + timedelta(days=30), end_dt)
        params = {
            'timeframe': '1Min', 'start': current_start.strftime('%Y-%m-%d'),
            'end': chunk_end.strftime('%Y-%m-%d'), 'limit': 10000, 'feed': 'iex'
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                bars = resp.json().get('bars', [])
                if bars: all_bars.extend(bars)
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")
        current_start = chunk_end
    
    if not all_bars: return None
    df = pd.DataFrame(all_bars)
    df['t'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'})
    df = df.set_index('timestamp').sort_index()
    return df

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def compute_rvol(df, period=20):
    """Calculate relative volume (current / average)"""
    avg_vol = df['volume'].rolling(period).mean()
    rvol = df['volume'] / avg_vol
    return rvol

def get_boof_signals_with_rvol(df):
    """Boof 22/23 signals WITH RVOL tracking (no filter yet)"""
    signals = []
    atr = compute_atr(df)
    rvol = compute_rvol(df)
    
    for i in range(60, len(df) - 1):
        if atr.iloc[i] == 0: continue
        if pd.isna(rvol.iloc[i]): continue
        
        # Standard Boof logic
        highs = df.iloc[i-3:i+3]['high'].values
        lows = df.iloc[i-3:i+3]['low'].values
        closes = df.iloc[i-3:i+3]['close'].values
        
        left_highs, right_highs = highs[:3], highs[4:]
        left_lows, right_lows = lows[:3], lows[4:]
        
        fractal_peak = (highs[3] > left_highs.max()) and (highs[3] > right_highs.max())
        fractal_trough = (lows[3] < left_lows.min()) and (lows[3] < right_lows.min())
        
        atr_rejected_peak = closes[3] < highs[3] - atr.iloc[i] * 0.6
        atr_bounced_trough = closes[3] > lows[3] + atr.iloc[i] * 0.6
        
        peak_slack = (highs[3] - closes[3]) / atr.iloc[i] if atr.iloc[i] > 0 else 1
        trough_slack = (closes[3] - lows[3]) / atr.iloc[i] if atr.iloc[i] > 0 else 1
        
        if fractal_peak and atr_rejected_peak and peak_slack < SLACK_MAX:
            direction = 'short'
            slack = peak_slack
        elif fractal_trough and atr_bounced_trough and trough_slack < SLACK_MAX:
            direction = 'long'
            slack = trough_slack
        else:
            continue
        
        signals.append({
            'bar': i + 1,
            'direction': direction,
            'slack': slack,
            'entry_price': df.iloc[i + 1]['open'],
            'timestamp': df.index[i + 1],
            'rvol': rvol.iloc[i],
            'volume': df.iloc[i]['volume']
        })
    
    return signals

def test_micro_move(df, signal, move_pct, max_bars):
    """Test if move hits target"""
    entry_bar = signal['bar']
    if entry_bar >= len(df): return None
    
    entry_price = signal['entry_price']
    direction = signal['direction']
    
    for i in range(entry_bar, min(entry_bar + max_bars, len(df))):
        high = df.iloc[i]['high']
        low = df.iloc[i]['low']
        
        up_move = (high - entry_price) / entry_price * 100
        down_move = (low - entry_price) / entry_price * 100
        
        if direction == 'long':
            if up_move >= move_pct: return {'hit': True, 'pnl': move_pct, 'win': True, 'bars': i - entry_bar}
            if down_move <= -move_pct: return {'hit': True, 'pnl': -move_pct, 'win': False, 'bars': i - entry_bar}
        else:
            if down_move <= -move_pct: return {'hit': True, 'pnl': move_pct, 'win': True, 'bars': i - entry_bar}
            if up_move >= move_pct: return {'hit': True, 'pnl': -move_pct, 'win': False, 'bars': i - entry_bar}
    
    exit_price = df.iloc[min(entry_bar + max_bars - 1, len(df) - 1)]['close']
    actual = (exit_price - entry_price) / entry_price * 100
    return {'hit': False, 'pnl': actual if direction == 'long' else -actual, 'win': False, 'bars': max_bars}

def analyze_rvol_bucket(df, signals, label, rvol_min=None, rvol_max=None):
    """Analyze performance for a specific RVOL bucket"""
    
    # Filter signals by RVOL if specified
    if rvol_min is not None and rvol_max is not None:
        filtered_signals = [s for s in signals if rvol_min <= s['rvol'] <= rvol_max]
    else:
        filtered_signals = signals
    
    if not filtered_signals:
        return None
    
    results = []
    for signal in filtered_signals:
        result = test_micro_move(df, signal, 0.5, 15)  # 0.5% in 15 min
        results.append({
            'rvol': signal['rvol'],
            'slack': signal['slack'],
            'hit': result['hit'],
            'pnl': result['pnl'],
            'win': result['win'],
            'bars': result['bars']
        })
    
    results_df = pd.DataFrame(results)
    
    total = len(results_df)
    hits = results_df['hit'].sum()
    wins = results_df['win'].sum()
    hit_rate = hits / total * 100 if total > 0 else 0
    win_rate = wins / hits * 100 if hits > 0 else 0
    avg_pnl = results_df['pnl'].mean()
    avg_rvol = results_df['rvol'].mean()
    avg_slack = results_df['slack'].mean()
    
    return {
        'label': label,
        'count': total,
        'hit_rate': hit_rate,
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'avg_rvol': avg_rvol,
        'avg_slack': avg_slack
    }

def main():
    print("="*80)
    print("RVOL FILTER TEST")
    print(f"RVOL Sweet Spot: {RVOL_MIN} - {RVOL_MAX}")
    print("="*80)
    
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    
    all_stats = []
    
    for symbol in SYMBOLS[:5]:
        print(f"\n[{symbol}] Fetching...")
        df = fetch_data(symbol, start, end)
        if df is None or len(df) < 1000:
            print(f"  [SKIP] Insufficient data")
            continue
        
        signals = get_boof_signals_with_rvol(df)
        print(f"  Signals: {len(signals)}")
        
        if not signals:
            continue
        
        # All signals
        all_result = analyze_rvol_bucket(df, signals, 'All Signals')
        if all_result:
            all_stats.append({**all_result, 'symbol': symbol})
        
        # RVOL filtered (1.2-3.0)
        rvol_result = analyze_rvol_bucket(df, signals, 'RVOL 1.2-3.0', RVOL_MIN, RVOL_MAX)
        if rvol_result:
            all_stats.append({**rvol_result, 'symbol': symbol})
        
        # RVOL too low (< 1.2)
        low_result = analyze_rvol_bucket(df, signals, 'RVOL < 1.2', 0, 1.2)
        if low_result:
            all_stats.append({**low_result, 'symbol': symbol})
        
        # RVOL too high (> 3.0)
        high_result = analyze_rvol_bucket(df, signals, 'RVOL > 3.0', 3.0, 100)
        if high_result:
            all_stats.append({**high_result, 'symbol': symbol})
    
    if not all_stats:
        print("\n[ERROR] No results")
        return
    
    df_stats = pd.DataFrame(all_stats)
    
    print("\n" + "="*80)
    print("AGGREGATE RESULTS BY RVOL BUCKET")
    print("="*80)
    
    for label in ['All Signals', 'RVOL < 1.2', 'RVOL 1.2-3.0', 'RVOL > 3.0']:
        bucket_df = df_stats[df_stats['label'] == label]
        if len(bucket_df) == 0:
            continue
        
        total_trades = bucket_df['count'].sum()
        weighted_hit = (bucket_df['hit_rate'] * bucket_df['count']).sum() / total_trades
        weighted_win = (bucket_df['win_rate'] * bucket_df['count']).sum() / total_trades
        weighted_pnl = (bucket_df['avg_pnl'] * bucket_df['count']).sum() / total_trades
        avg_rvol = bucket_df['avg_rvol'].mean()
        
        print(f"\n{label}:")
        print(f"  Total Trades: {total_trades}")
        print(f"  Avg RVOL: {avg_rvol:.2f}")
        print(f"  Hit Rate: {weighted_hit:.1f}%")
        print(f"  Win Rate (of hits): {weighted_win:.1f}%")
        print(f"  Avg P&L: {weighted_pnl:+.3f}%")
        
        # Calculate expectancy
        hit_pct = weighted_hit / 100
        win_pct = weighted_win / 100
        if hit_pct > 0:
            expectancy = hit_pct * ((win_pct * 0.5) - ((1 - win_pct) * 0.5))
            print(f"  Expectancy: {expectancy:+.4f}%")
    
    # Comparison table
    print("\n" + "="*80)
    print("COMPARISON TABLE")
    print("="*80)
    print(f"{'Bucket':<20} {'Trades':>10} {'Avg RVOL':>10} {'Hit%':>8} {'Win%':>8} {'P&L%':>10}")
    print("-"*80)
    
    for label in ['RVOL < 1.2', 'RVOL 1.2-3.0', 'RVOL > 3.0']:
        bucket_df = df_stats[df_stats['label'] == label]
        if len(bucket_df) == 0:
            continue
        
        total_trades = bucket_df['count'].sum()
        weighted_hit = (bucket_df['hit_rate'] * bucket_df['count']).sum() / total_trades
        weighted_win = (bucket_df['win_rate'] * bucket_df['count']).sum() / total_trades
        weighted_pnl = (bucket_df['avg_pnl'] * bucket_df['count']).sum() / total_trades
        avg_rvol = bucket_df['avg_rvol'].mean()
        
        print(f"{label:<20} {total_trades:>10} {avg_rvol:>9.2f} {weighted_hit:>7.1f}% {weighted_win:>7.1f}% {weighted_pnl:>+9.3f}%")
    
    # Save
    date_str = datetime.now().strftime('%Y%m%d')
    df_stats.to_csv(f'rvol_test_{date_str}.csv', index=False)
    print(f"\n[SAVED] rvol_test_{date_str}.csv")

if __name__ == '__main__':
    main()
