"""
ES Futures Backtest - Options A, B, C Comparison (Optimized)
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import databento as db

DATABENTO_KEY = os.getenv('DATABENTO_KEY', '')
POINT_VALUE = 12.50  # ES tick value
def fetch_es_data(start_date, end_date):
    if not DATABENTO_KEY:
        print("[ERROR] No DATABENTO_KEY set")
        return None
    try:
        client = db.Historical(DATABENTO_KEY)
        print(f"  Fetching ES.c.0 ({start_date} to {end_date})...")
        data = client.timeseries.get_range(
            dataset='GLBX.MDP3', stype_in='continuous', symbols=['ES.c.0'],
            schema='ohlcv-1m', start=start_date + 'T00:00:00', end=end_date + 'T16:00:00',
        )
        if data is None:
            return None
        df = data.to_df()
        if len(df) == 0:
            return None
        print(f"  Got {len(df)} bars")
        return df
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None

def vwap(df):
    tp = (df['high'] + df['low'] + df['close']) / 3
    return (tp * df['volume']).cumsum() / df['volume'].cumsum()

def adx(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_high, prev_low, prev_close = high.shift(1), low.shift(1), close.shift(1)
    plus_dm = ((high - prev_high) > (prev_low - low)) * (high - prev_high).clip(lower=0)
    minus_dm = ((prev_low - low) > (high - prev_high)) * (prev_low - low).clip(lower=0)
    tr1, tr2, tr3 = high - low, (high - prev_close).abs(), (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * plus_dm.rolling(period).mean() / atr
    minus_di = 100 * minus_dm.rolling(period).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
    return dx.rolling(period).mean()

def is_first_90min(timestamp):
    ts = pd.to_datetime(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    ts_est = ts.tz_convert('US/Eastern')
    h, m = ts_est.hour, ts_est.minute
    return (h == 9 and m >= 30) or (h == 10) or (h == 11 and m == 0)

def generate_signals_a(df):
    """Option A: First 90min + VWAP + 3-bar break + 2.2x volume"""
    df['vwap'] = vwap(df)
    df['vol_avg'] = df['volume'].rolling(20).mean()
    df['prev_high'] = df['high'].rolling(3).max().shift(1)
    df['prev_low'] = df['low'].rolling(3).min().shift(1)
    df['in_time'] = df.index.map(is_first_90min)
    df['vol_spike'] = df['volume'] > df['vol_avg'] * 2.2
    
    long = df['in_time'] & df['vol_spike'] & (df['close'] > df['vwap']) & (df['close'] > df['prev_high'])
    short = df['in_time'] & df['vol_spike'] & (df['close'] < df['vwap']) & (df['close'] < df['prev_low'])
    
    signals = []
    for idx in df[long].index:
        signals.append({'direction': 'long', 'entry_price': df.loc[idx, 'close'], 
                       'entry_time': idx, 'idx': df.index.get_loc(idx)})
    for idx in df[short].index:
        signals.append({'direction': 'short', 'entry_price': df.loc[idx, 'close'],
                       'entry_time': idx, 'idx': df.index.get_loc(idx)})
    return sorted(signals, key=lambda x: x['idx'])

def generate_signals_b(df):
    """Option B: ADX > 18 + 2x volume"""
    df['vwap'] = vwap(df)
    df['adx'] = adx(df, 14)
    df['vol_avg'] = df['volume'].rolling(20).mean()
    df['trend'] = df['adx'] > 18
    df['vol_spike'] = df['volume'] > df['vol_avg'] * 2.0
    
    long = df['trend'] & df['vol_spike'] & (df['close'] > df['vwap'])
    short = df['trend'] & df['vol_spike'] & (df['close'] < df['vwap'])
    
    signals = []
    for idx in df[long].index:
        signals.append({'direction': 'long', 'entry_price': df.loc[idx, 'close'],
                       'entry_time': idx, 'idx': df.index.get_loc(idx), 'adx': df.loc[idx, 'adx']})
    for idx in df[short].index:
        signals.append({'direction': 'short', 'entry_price': df.loc[idx, 'close'],
                       'entry_time': idx, 'idx': df.index.get_loc(idx), 'adx': df.loc[idx, 'adx']})
    return sorted(signals, key=lambda x: x['idx'])

def generate_signals_c(df):
    """Option C: Structure + wick filter < 60% + 2x volume"""
    df['vwap'] = vwap(df)
    df['vol_avg'] = df['volume'].rolling(20).mean()
    df['candle_size'] = df['high'] - df['low']
    df['body'] = (df['close'] - df['open']).abs()
    df['wick_ratio'] = (df['candle_size'] - df['body']) / df['candle_size']
    df['wick_ok'] = df['wick_ratio'] < 0.6
    df['vol_spike'] = df['volume'] > df['vol_avg'] * 2.0
    df['prev_high'] = df['high'].rolling(5).max().shift(1)
    df['prev_low'] = df['low'].rolling(5).min().shift(1)
    
    long = df['vol_spike'] & df['wick_ok'] & (df['close'] > df['vwap']) & (df['close'] > df['prev_high'])
    short = df['vol_spike'] & df['wick_ok'] & (df['close'] < df['vwap']) & (df['close'] < df['prev_low'])
    
    signals = []
    for idx in df[long].index:
        signals.append({'direction': 'long', 'entry_price': df.loc[idx, 'close'],
                       'entry_time': idx, 'idx': df.index.get_loc(idx)})
    for idx in df[short].index:
        signals.append({'direction': 'short', 'entry_price': df.loc[idx, 'close'],
                       'entry_time': idx, 'idx': df.index.get_loc(idx)})
    return sorted(signals, key=lambda x: x['idx'])

def backtest_simple(df, signals, stop_pts=1.0, tp_pts=2.0):
    """Simple backtest - exit at TP or SL, no partials"""
    if not signals:
        return None
    
    wins, losses = 0, 0
    total_pnl = 0
    max_streak, curr_streak = 0, 0
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 10:
            continue
        
        entry = sig['entry_price']
        direction = sig['direction']
        
        if direction == 'long':
            sl, tp = entry - stop_pts, entry + tp_pts
        else:
            sl, tp = entry + stop_pts, entry - stop_pts
        
        pnl = 0
        win = False
        
        for j in range(idx + 1, min(idx + 30, len(df))):
            bar = df.iloc[j]
            if direction == 'long':
                if bar['low'] <= sl:
                    pnl = -stop_pts * 4 * POINT_VALUE
                    win = False
                    break
                if bar['high'] >= tp:
                    pnl = tp_pts * 4 * POINT_VALUE
                    win = True
                    break
            else:
                if bar['high'] >= sl:
                    pnl = -stop_pts * 4 * POINT_VALUE
                    win = False
                    break
                if bar['low'] <= tp:
                    pnl = tp_pts * 4 * POINT_VALUE
                    win = True
                    break
        
        if pnl == 0:  # Time exit
            exit_p = df.iloc[min(idx + 29, len(df) - 1)]['close']
            pnl = (exit_p - entry) * 4 * POINT_VALUE if direction == 'long' else (entry - exit_p) * 4 * POINT_VALUE
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
        'trades': total, 'wins': wins, 'losses': losses,
        'win_rate': wins / total * 100 if total > 0 else 0,
        'total_pnl': total_pnl,
        'avg_pnl': total_pnl / total if total > 0 else 0,
        'max_streak': max_streak
    }

def main():
    print("="*70)
    print("ES FUTURES BACKTEST - OPTIONS A/B/C")
    print("="*70)
    
    if not DATABENTO_KEY:
        print("[ERROR] Set DATABENTO_KEY")
        return
    
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=180)
    
    df = fetch_es_data(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    if df is None:
        return
    
    print(f"\nData: {len(df)} bars | {df.index[0].date()} to {df.index[-1].date()}")
    
    options = {
        'A': ('First 90min + VWAP + 3-bar break + 2.2x vol', generate_signals_a),
        'B': ('ADX > 18 + 2x volume', generate_signals_b),
        'C': ('Structure + wick < 60% + 2x vol', generate_signals_c)
    }
    
    all_results = {}
    
    for name, (desc, func) in options.items():
        print(f"\n{'='*70}")
        print(f"OPTION {name}: {desc}")
        print(f"{'='*70}")
        
        signals = func(df)
        print(f"Signals: {len(signals)}")
        
        if signals:
            r = backtest_simple(df, signals)
            all_results[name] = r
            print(f"\n  Trades: {r['trades']} | WR: {r['win_rate']:.1f}%")
            print(f"  Total P&L: ${r['total_pnl']:.2f} | Avg: ${r['avg_pnl']:.2f}")
            print(f"  Max Loss Streak: {r['max_streak']}")
    
    if all_results:
        print(f"\n{'='*70}")
        print("SUMMARY")
        print(f"{'='*70}")
        print(f"{'Opt':<6} {'Trades':>10} {'WR%':>8} {'Total $':>12} {'Avg $':>10} {'Max SL':>8}")
        print("-"*70)
        for opt in ['A', 'B', 'C']:
            if opt in all_results:
                r = all_results[opt]
                print(f"{opt:<6} {r['trades']:>10} {r['win_rate']:>7.1f}% ${r['total_pnl']:>10.2f} ${r['avg_pnl']:>9.2f} {r['max_streak']:>7}")

if __name__ == '__main__':
    main()
