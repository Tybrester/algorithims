"""
Early Move Pattern Detector
Analyzes compression → impulse → spike on existing Boof signals
NO changes to signal logic - just pattern detection overlay
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
    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp', 'n': 'trades', 'vw': 'vwap'})
    return df.set_index('timestamp').sort_index()

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def compute_vol_sma(df, period=20):
    return df['volume'].rolling(period).mean()

def detect_compression(df, lookback=10):
    """
    Detect compression period before signal
    Returns: compression_score (0-1), avg_range, range_trend
    """
    highs = df['high'].values[-lookback:]
    lows = df['low'].values[-lookback:]
    ranges = highs - lows
    
    # Compression = tightening range
    early_range = ranges[:5].mean()
    late_range = ranges[5:].mean()
    
    # Range should tighten
    range_trend = (late_range - early_range) / early_range if early_range > 0 else 0
    
    # Score: negative trend (tightening) = compression
    compression_score = max(0, -range_trend)
    
    return compression_score, ranges.mean(), range_trend

def detect_impulse_candle(df, signal_direction):
    """
    Detect first impulse candle characteristics
    Returns: impulse_score (0-1), body_pct, momentum
    """
    open_price = df['open'].iloc[-1]
    high = df['high'].iloc[-1]
    low = df['low'].iloc[-1]
    close = df['close'].iloc[-1]
    
    candle_range = high - low
    if candle_range == 0: return 0, 0, 0
    
    # Body size vs wick
    body = abs(close - open_price)
    body_pct = body / candle_range
    
    # Direction consistency
    if signal_direction == 'long':
        momentum = (close - open_price) / candle_range  # Positive = good
    else:
        momentum = (open_price - close) / candle_range  # Positive = good
    
    # Impulse score: large body + strong momentum in direction
    impulse_score = body_pct * max(0, momentum)
    
    return impulse_score, body_pct, momentum

def detect_participation_spike(df, lookback=10):
    """
    Detect volume/activity spike
    Returns: spike_score (0-1), vol_ratio, candle_momentum
    """
    # Volume spike
    current_vol = df['volume'].iloc[-1]
    avg_vol = df['volume'].iloc[-lookback:-1].mean()
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1
    
    # Candle size spike (proxy when volume not available)
    current_range = (df['high'].iloc[-1] - df['low'].iloc[-1])
    avg_range = (df['high'].iloc[-lookback:-1] - df['low'].iloc[-lookback:-1]).mean()
    range_ratio = current_range / avg_range if avg_range > 0 else 1
    
    # Spike score: volume OR range expansion
    spike_score = min(1, (vol_ratio + range_ratio) / 2 - 0.5)  # Normalize
    
    # Candle momentum (speed proxy)
    price_change = abs(df['close'].iloc[-1] - df['open'].iloc[-1])
    candle_momentum = price_change / current_range if current_range > 0 else 0
    
    return spike_score, vol_ratio, candle_momentum

def get_boof_signals_with_patterns(df):
    """
    Standard Boof 22/23 signals + pattern detection overlay
    NO changes to signal logic
    """
    signals = []
    atr = compute_atr(df)
    vol_sma = compute_vol_sma(df)
    
    for i in range(60, len(df) - 1):  # Extra buffer for pattern lookback
        if atr.iloc[i] == 0 or vol_sma.iloc[i] == 0: continue
        
        # Standard Boof signal logic (unchanged)
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
        
        # PATTERN DETECTION OVERLAY (new - doesn't affect signal)
        pattern_window = df.iloc[i-10:i+1]
        
        comp_score, avg_range, range_trend = detect_compression(pattern_window, 10)
        impulse_score, body_pct, momentum = detect_impulse_candle(pattern_window.iloc[[-1]], direction)
        spike_score, vol_ratio, candle_mom = detect_participation_spike(pattern_window, 10)
        
        # Early move composite score
        early_move_score = (comp_score * 0.3) + (impulse_score * 0.4) + (spike_score * 0.3)
        
        signals.append({
            'bar': i + 1,
            'direction': direction,
            'slack': slack,
            'entry_price': df.iloc[i + 1]['open'],
            'timestamp': df.index[i + 1],
            # Pattern scores
            'compression': comp_score,
            'impulse': impulse_score,
            'spike': spike_score,
            'early_move_score': early_move_score,
            # Raw metrics
            'range_trend': range_trend,
            'body_pct': body_pct,
            'momentum': momentum,
            'vol_ratio': vol_ratio,
            'candle_mom': candle_mom
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
            if up_move >= move_pct: return {'hit': True, 'pnl': move_pct, 'win': True}
            if down_move <= -move_pct: return {'hit': True, 'pnl': -move_pct, 'win': False}
        else:
            if down_move <= -move_pct: return {'hit': True, 'pnl': move_pct, 'win': True}
            if up_move >= move_pct: return {'hit': True, 'pnl': -move_pct, 'win': False}
    
    # Time exit
    exit_price = df.iloc[min(entry_bar + max_bars - 1, len(df) - 1)]['close']
    actual = (exit_price - entry_price) / entry_price * 100
    return {'hit': False, 'pnl': actual if direction == 'long' else -actual, 'win': False}

def main():
    print("="*80)
    print("EARLY MOVE PATTERN DETECTION")
    print("Compression → Impulse → Spike Overlay")
    print("="*80)
    print("NO changes to Boof 22/23 signal logic")
    print("Pattern detection runs AFTER signal generation")
    print("="*80)
    
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    
    all_results = []
    
    for symbol in SYMBOLS[:5]:  # Test on 5 symbols
        print(f"\n[{symbol}] Analyzing...")
        df = fetch_data(symbol, start, end)
        if df is None or len(df) < 1000:
            continue
        
        signals = get_boof_signals_with_patterns(df)
        print(f"  Signals: {len(signals)}")
        
        if not signals:
            continue
        
        for signal in signals:
            # Test 0.5% in 15 min
            result = test_micro_move(df, signal, 0.5, 15)
            
            all_results.append({
                'symbol': symbol,
                'direction': signal['direction'],
                'slack': signal['slack'],
                'timestamp': signal['timestamp'],
                'compression': signal['compression'],
                'impulse': signal['impulse'],
                'spike': signal['spike'],
                'early_move_score': signal['early_move_score'],
                'hit_0.5_15': result['hit'],
                'pnl_0.5_15': result['pnl'],
                'win_0.5_15': result['win']
            })
    
    if not all_results:
        print("\n[ERROR] No results")
        return
    
    df_results = pd.DataFrame(all_results)
    
    print("\n" + "="*80)
    print("RESULTS: Pattern Score vs Performance")
    print("="*80)
    
    # Overall stats
    total = len(df_results)
    hits = df_results['hit_0.5_15'].sum()
    wins = df_results['win_0.5_15'].sum()
    
    print(f"\nAll Signals (n={total}):")
    print(f"  Hit 0.5% target: {hits} ({hits/total*100:.1f}%)")
    print(f"  Win rate (of hits): {wins/hits*100:.1f}%" if hits > 0 else "  No hits")
    
    # Sort by early move score and compare top vs bottom
    df_sorted = df_results.sort_values('early_move_score', ascending=False)
    
    top_20_pct = int(len(df_sorted) * 0.2)
    top_signals = df_sorted.head(top_20_pct)
    bottom_signals = df_sorted.tail(top_20_pct)
    
    print(f"\n{'='*80}")
    print(f"TOP 20% by Early Move Score (n={len(top_signals)}):")
    print(f"  Avg Score: {top_signals['early_move_score'].mean():.3f}")
    print(f"  Avg Compression: {top_signals['compression'].mean():.3f}")
    print(f"  Avg Impulse: {top_signals['impulse'].mean():.3f}")
    print(f"  Avg Spike: {top_signals['spike'].mean():.3f}")
    
    top_hits = top_signals['hit_0.5_15'].sum()
    top_wins = top_signals['win_0.5_15'].sum()
    print(f"\n  Hit Rate: {top_hits}/{len(top_signals)} = {top_hits/len(top_signals)*100:.1f}%")
    print(f"  Win Rate (of hits): {top_wins/top_hits*100:.1f}%" if top_hits > 0 else "  No hits")
    print(f"  Avg P&L: {top_signals['pnl_0.5_15'].mean():.3f}%")
    
    print(f"\n{'='*80}")
    print(f"BOTTOM 20% by Early Move Score (n={len(bottom_signals)}):")
    print(f"  Avg Score: {bottom_signals['early_move_score'].mean():.3f}")
    print(f"  Avg Compression: {bottom_signals['compression'].mean():.3f}")
    print(f"  Avg Impulse: {bottom_signals['impulse'].mean():.3f}")
    print(f"  Avg Spike: {bottom_signals['spike'].mean():.3f}")
    
    bot_hits = bottom_signals['hit_0.5_15'].sum()
    bot_wins = bottom_signals['win_0.5_15'].sum()
    print(f"\n  Hit Rate: {bot_hits}/{len(bottom_signals)} = {bot_hits/len(bottom_signals)*100:.1f}%")
    print(f"  Win Rate (of hits): {bot_wins/bot_hits*100:.1f}%" if bot_hits > 0 else "  No hits")
    print(f"  Avg P&L: {bottom_signals['pnl_0.5_15'].mean():.3f}%")
    
    # Score buckets
    print(f"\n{'='*80}")
    print("SCORE BUCKETS:")
    print("="*80)
    
    df_results['score_bucket'] = pd.cut(df_results['early_move_score'], 
                                         bins=[0, 0.2, 0.4, 0.6, 0.8, 1.0],
                                         labels=['0-0.2', '0.2-0.4', '0.4-0.6', '0.6-0.8', '0.8-1.0'])
    
    for bucket in ['0-0.2', '0.2-0.4', '0.4-0.6', '0.6-0.8', '0.8-1.0']:
        bucket_df = df_results[df_results['score_bucket'] == bucket]
        if len(bucket_df) == 0:
            continue
        
        hits = bucket_df['hit_0.5_15'].sum()
        wins = bucket_df['win_0.5_15'].sum()
        hit_rate = hits / len(bucket_df) * 100
        win_rate = wins / hits * 100 if hits > 0 else 0
        avg_pnl = bucket_df['pnl_0.5_15'].mean()
        
        print(f"\nScore {bucket} (n={len(bucket_df)}):")
        print(f"  Hit Rate: {hit_rate:.1f}% | Win Rate: {win_rate:.1f}% | Avg P&L: {avg_pnl:+.3f}%")
    
    # Save
    date_str = datetime.now().strftime('%Y%m%d')
    df_results.to_csv(f'early_move_analysis_{date_str}.csv', index=False)
    print(f"\n[SAVED] early_move_analysis_{date_str}.csv")

if __name__ == '__main__':
    main()
