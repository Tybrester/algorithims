"""
BOOF 22 & 23 — Higher Timeframe Backtest (30m, 1h)
Target: 0.10% moves on SPY, QQQ + 10 symbols
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

# Boof ETF list
SYMBOLS = ['SPY', 'QQQ', 'AAPL', 'NVDA', 'META', 'MSFT', 'AMZN', 'GOOGL', 'TSLA', 'AMD', 'NFLX', 'CRM']
TIMEFRAMES = ['30Min', '1H']

def fetch_data(symbol, timeframe, start, end):
    """Fetch bars from Alpaca"""
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    
    chunk_size = 90
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

# ───────────────────────────────────────────────────────────────────────────────
# BOOF 22 SIGNAL LOGIC
# ───────────────────────────────────────────────────────────────────────────────
def boof22_signals(df, symbol):
    """
    Boof 22: Volume cluster + fractal swing detection + SR proximity
    """
    df = df.copy()
    
    # ATR
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # Volume
    df['vol_sma'] = df['volume'].rolling(50).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma']
    
    # Fractal detection (3-bar)
    df['fractal_high'] = (df['high'] > df['high'].shift(1)) & (df['high'] > df['high'].shift(-1))
    df['fractal_low'] = (df['low'] < df['low'].shift(1)) & (df['low'] < df['low'].shift(-1))
    
    # Build SR clusters from recent fractals
    lookback = 20
    signals = []
    
    for i in range(lookback + 10, len(df) - 1):
        window = df.iloc[i-lookback:i]
        
        # Find recent fractal highs/lows
        highs = window[window['fractal_high']]['high'].tail(3).values
        lows = window[window['fractal_low']]['low'].tail(3).values
        
        if len(highs) < 2 or len(lows) < 2:
            continue
        
        current = df.iloc[i]
        prev = df.iloc[i-1]
        
        # Volume spike check
        if current['vol_ratio'] < 1.3:
            continue
        
        atr = current['atr']
        if pd.isna(atr) or atr == 0:
            continue
        
        # ATR bounce check - price near fractal level
        for h in highs:
            if abs(current['close'] - h) < atr * 0.6:
                # SHORT setup: near resistance
                if current['close'] < prev['close']:  # Bearish candle
                    signals.append({
                        'direction': 'short',
                        'entry_price': df.iloc[i+1]['open'],
                        'idx': i + 1,
                        'timestamp': df.index[i+1],
                        'reason': 'boof22_sr_short',
                        'slack': current['vol_ratio']
                    })
                    break
        
        for l in lows:
            if abs(current['close'] - l) < atr * 0.6:
                # LONG setup: near support
                if current['close'] > prev['close']:  # Bullish candle
                    signals.append({
                        'direction': 'long',
                        'entry_price': df.iloc[i+1]['open'],
                        'idx': i + 1,
                        'timestamp': df.index[i+1],
                        'reason': 'boof22_sr_long',
                        'slack': current['vol_ratio']
                    })
                    break
    
    return signals

# ───────────────────────────────────────────────────────────────────────────────
# BOOF 23 SIGNAL LOGIC
# ───────────────────────────────────────────────────────────────────────────────
def boof23_signals(df, symbol):
    """
    Boof 23: SR cluster + ZigZag regime + engulfing (simplified for higher TF)
    """
    df = df.copy()
    
    # ATR
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # Volume
    df['vol_sma'] = df['volume'].rolling(50).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma']
    
    # Simple zigzag (3-bar pivot)
    df['zz_high'] = (df['high'] > df['high'].shift(1)) & (df['high'] > df['high'].shift(2)) & \
                    (df['high'] > df['high'].shift(-1)) & (df['high'] > df['high'].shift(-2))
    df['zz_low'] = (df['low'] < df['low'].shift(1)) & (df['low'] < df['low'].shift(2)) & \
                   (df['low'] < df['low'].shift(-1)) & (df['low'] < df['low'].shift(-2))
    
    # Trend from recent zz direction
    df['trend'] = 0
    for i in range(10, len(df)):
        recent_highs = df.iloc[i-10:i]['zz_high'].sum()
        recent_lows = df.iloc[i-10:i]['zz_low'].sum()
        if recent_highs > recent_lows:
            df.iloc[i, df.columns.get_loc('trend')] = 1  # uptrend
        elif recent_lows > recent_highs:
            df.iloc[i, df.columns.get_loc('trend')] = -1  # downtrend
    
    # Engulfing
    df['bull_engulf'] = (df['close'] > df['open']) & (df['open'] < df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
    df['bear_engulf'] = (df['close'] < df['open']) & (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))
    
    signals = []
    
    for i in range(20, len(df) - 1):
        current = df.iloc[i]
        
        if current['vol_ratio'] < 1.3:
            continue
        
        atr = current['atr']
        if pd.isna(atr) or atr == 0:
            continue
        
        # LONG: downtrend + engulfing
        if current['trend'] == -1 and current['bull_engulf']:
            signals.append({
                'direction': 'long',
                'entry_price': df.iloc[i+1]['open'],
                'idx': i + 1,
                'timestamp': df.index[i+1],
                'reason': 'boof23_zz_long',
                'slack': current['vol_ratio']
            })
        
        # SHORT: uptrend + engulfing
        elif current['trend'] == 1 and current['bear_engulf']:
            signals.append({
                'direction': 'short',
                'entry_price': df.iloc[i+1]['open'],
                'idx': i + 1,
                'timestamp': df.index[i+1],
                'reason': 'boof23_zz_short',
                'slack': current['vol_ratio']
            })
    
    return signals

# ───────────────────────────────────────────────────────────────────────────────
# BACKTEST
# ───────────────────────────────────────────────────────────────────────────────
def backtest(df, signals, tp_pct=0.10, sl_pct=0.05, max_bars=5):
    """
    Target 0.10% moves
    TP: +0.10% / SL: -0.05% (2:1 RR)
    """
    if not signals:
        return None
    
    wins, losses = 0, 0
    total_pnl = 0
    max_streak, curr_streak = 0, 0
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 2:
            continue
        
        entry = sig['entry_price']
        direction = sig['direction']
        
        # Calculate targets
        if direction == 'long':
            tp_price = entry * (1 + tp_pct / 100)
            sl_price = entry * (1 - sl_pct / 100)
        else:
            tp_price = entry * (1 - tp_pct / 100)
            sl_price = entry * (1 + sl_pct / 100)
        
        pnl = 0
        win = False
        
        for j in range(idx + 1, min(idx + max_bars, len(df))):
            bar = df.iloc[j]
            
            if direction == 'long':
                if bar['low'] <= sl_price:
                    pnl = -sl_pct
                    win = False
                    break
                if bar['high'] >= tp_price:
                    pnl = tp_pct
                    win = True
                    break
            else:
                if bar['high'] >= sl_price:
                    pnl = -sl_pct
                    win = False
                    break
                if bar['low'] <= tp_price:
                    pnl = tp_pct
                    win = True
                    break
        
        # Time exit
        if pnl == 0:
            exit_p = df.iloc[min(idx + max_bars - 1, len(df) - 1)]['close']
            if direction == 'long':
                pnl = (exit_p - entry) / entry * 100
            else:
                pnl = (entry - exit_p) / entry * 100
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
        'trades': total,
        'wins': wins,
        'losses': losses,
        'win_rate': wins / total * 100 if total > 0 else 0,
        'total_pnl': total_pnl,
        'avg_pnl': total_pnl / total if total > 0 else 0,
        'max_streak': max_streak
    }

def test_symbol(symbol, timeframe, days_back=180):
    """Test Boof 22 and 23 on one symbol/timeframe"""
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back)
    
    print(f"\n[{symbol}] {timeframe} | Fetching...")
    df = fetch_data(symbol, timeframe, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    
    if df is None or len(df) < 50:
        print(f"  [SKIP] No data")
        return None
    
    print(f"  Bars: {len(df)} | {df.index[0].date()} to {df.index[-1].date()}")
    
    # Boof 22
    signals_22 = boof22_signals(df, symbol)
    result_22 = backtest(df, signals_22)
    
    # Boof 23
    signals_23 = boof23_signals(df, symbol)
    result_23 = backtest(df, signals_23)
    
    return {
        'symbol': symbol,
        'timeframe': timeframe,
        'boof22': result_22,
        'boof23': result_23,
        'signals_22': len(signals_22),
        'signals_23': len(signals_23)
    }

def main():
    print("="*80)
    print("BOOF 22 & 23 — Higher Timeframe Backtest")
    print("Target: 0.10% moves | Timeframes: 30m, 1h | Period: 6 months")
    print("="*80)
    
    all_results = []
    
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            result = test_symbol(symbol, timeframe, days_back=180)
            if result:
                all_results.append(result)
    
    if not all_results:
        print("\n[ERROR] No results")
        return
    
    # Summary tables
    print("\n" + "="*80)
    print("SUMMARY: BOOF 22 Results (0.10% target)")
    print("="*80)
    print(f"{'Symbol':<8} {'TF':<8} {'Signals':>8} {'Trades':>8} {'WR%':>8} {'Avg%':>10} {'Total%':>10}")
    print("-"*80)
    
    for r in all_results:
        if r['boof22']:
            b22 = r['boof22']
            print(f"{r['symbol']:<8} {r['timeframe']:<8} {r['signals_22']:>8} {b22['trades']:>8} {b22['win_rate']:>7.1f}% {b22['avg_pnl']:>+9.3f}% {b22['total_pnl']:>+9.2f}%")
    
    print("\n" + "="*80)
    print("SUMMARY: BOOF 23 Results (0.10% target)")
    print("="*80)
    print(f"{'Symbol':<8} {'TF':<8} {'Signals':>8} {'Trades':>8} {'WR%':>8} {'Avg%':>10} {'Total%':>10}")
    print("-"*80)
    
    for r in all_results:
        if r['boof23']:
            b23 = r['boof23']
            print(f"{r['symbol']:<8} {r['timeframe']:<8} {r['signals_23']:>8} {b23['trades']:>8} {b23['win_rate']:>7.1f}% {b23['avg_pnl']:>+9.3f}% {b23['total_pnl']:>+9.2f}%")
    
    # Best performers
    print("\n" + "="*80)
    print("TOP PERFORMERS")
    print("="*80)
    
    boof22_valid = [(r['symbol'], r['timeframe'], r['boof22']) for r in all_results if r['boof22'] and r['boof22']['trades'] > 5]
    boof23_valid = [(r['symbol'], r['timeframe'], r['boof23']) for r in all_results if r['boof23'] and r['boof23']['trades'] > 5]
    
    if boof22_valid:
        best_22 = max(boof22_valid, key=lambda x: x[2]['avg_pnl'])
        print(f"\nBoof 22 Best: {best_22[0]} {best_22[1]} — {best_22[2]['avg_pnl']:+.3f}% avg, {best_22[2]['win_rate']:.1f}% WR")
    
    if boof23_valid:
        best_23 = max(boof23_valid, key=lambda x: x[2]['avg_pnl'])
        print(f"Boof 23 Best: {best_23[0]} {best_23[1]} — {best_23[2]['avg_pnl']:+.3f}% avg, {best_23[2]['win_rate']:.1f}% WR")

if __name__ == '__main__':
    main()
