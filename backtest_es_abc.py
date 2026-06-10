"""
ES Futures Backtest - Options A, B, C Comparison
6 months data from Databento
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import databento as db

DATABENTO_KEY = os.getenv('DATABENTO_KEY', '')

# Parameters
RISK_PER_TRADE = 50  # $50 risk per trade
POINT_VALUE = 12.50  # ES = $12.50 per tick, 4 ticks = 1 point = $50
STOP_POINTS = 1.0    # 1 ES point stop
TP1_POINTS = 1.5     # +1.5 points first target
TP2_POINTS = 2.0     # +2 points runner

def fetch_es_data(start_date, end_date):
    """Fetch ES continuous contract from Databento"""
    if not DATABENTO_KEY:
        print("[ERROR] No DATABENTO_KEY set")
        return None
    try:
        client = db.Historical(DATABENTO_KEY)
        print(f"  Fetching ES.c.0 ({start_date} to {end_date})...")
        data = client.timeseries.get_range(
            dataset='GLBX.MDP3',
            stype_in='continuous',
            symbols=['ES.c.0'],
            schema='ohlcv-1m',
            start=start_date + 'T00:00:00',
            end=end_date + 'T16:00:00',
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
    """Volume Weighted Average Price"""
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    return (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

def adx(df, period=14):
    """Average Directional Index"""
    high, low, close = df['high'], df['low'], df['close']
    prev_high, prev_low, prev_close = high.shift(1), low.shift(1), close.shift(1)
    
    plus_dm = ((high - prev_high) > (prev_low - low)) * (high - prev_high).clip(lower=0)
    minus_dm = ((prev_low - low) > (high - prev_high)) * (prev_low - low).clip(lower=0)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr = tr.rolling(period).mean()
    plus_di = 100 * plus_dm.rolling(period).mean() / atr
    minus_di = 100 * minus_dm.rolling(period).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
    return dx.rolling(period).mean()

def is_market_hours(timestamp):
    """Check if timestamp is within 9:30 AM - 11:00 AM EST (first 90 min)"""
    ts = pd.to_datetime(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    ts_est = ts.tz_convert('US/Eastern')
    hour, minute = ts_est.hour, ts_est.minute
    # First 90 minutes: 9:30 - 11:00
    return (hour == 9 and minute >= 30) or (hour == 10) or (hour == 11 and minute == 0)

def option_A(df):
    """ES optimized breakout scalp - first 90 min only"""
    df = df.copy()
    df['vwap'] = vwap(df)
    df['vol_avg'] = df['volume'].rolling(20).mean()
    
    signals = []
    
    for i in range(20, len(df)):
        row = df.iloc[i]
        timestamp = df.index[i]
        
        # Time filter: only first 90 minutes
        if not is_market_hours(timestamp):
            continue
        
        # Volume spike > 2.2x
        vol_spike = row['volume'] > row['vol_avg'] * 2.2
        
        # Previous 3-bar high/low
        prev_high = df['high'].iloc[i-3:i].max()
        prev_low = df['low'].iloc[i-3:i].min()
        
        if vol_spike:
            # Long: above VWAP and breaks prev high
            if row['close'] > row['vwap'] and row['close'] > prev_high:
                signals.append({
                    'direction': 'long',
                    'entry_price': row['close'],
                    'entry_time': timestamp,
                    'index': i
                })
            # Short: below VWAP and breaks prev low
            elif row['close'] < row['vwap'] and row['close'] < prev_low:
                signals.append({
                    'direction': 'short',
                    'entry_price': row['close'],
                    'entry_time': timestamp,
                    'index': i
                })
    
    return signals

def option_B(df):
    """Regime filter system - ADX trend filter"""
    df = df.copy()
    df['vwap'] = vwap(df)
    df['adx'] = adx(df, 14)
    
    signals = []
    
    for i in range(20, len(df)):
        row = df.iloc[i]
        timestamp = df.index[i]
        
        # Trend regime: ADX > 18
        current_adx = row['adx'] if not pd.isna(row['adx']) else 0
        if current_adx < 18:
            continue
        
        # Volume spike > 2x
        vol_avg = df['volume'].rolling(20).mean().iloc[i]
        vol_spike = row['volume'] > vol_avg * 2.0
        
        if vol_spike:
            if row['close'] > row['vwap']:
                signals.append({
                    'direction': 'long',
                    'entry_price': row['close'],
                    'entry_time': timestamp,
                    'index': i,
                    'adx': current_adx
                })
            else:
                signals.append({
                    'direction': 'short',
                    'entry_price': row['close'],
                    'entry_time': timestamp,
                    'index': i,
                    'adx': current_adx
                })
    
    return signals

def option_C(df):
    """Structure + volume confirmation with wick filter"""
    df = df.copy()
    df['vwap'] = vwap(df)
    df['vol_avg'] = df['volume'].rolling(20).mean()
    
    signals = []
    
    for i in range(20, len(df)):
        row = df.iloc[i]
        timestamp = df.index[i]
        
        # Volume spike > 2x
        vol_spike = row['volume'] > row['vol_avg'] * 2.0
        
        # Candle analysis
        candle_size = row['high'] - row['low']
        body = abs(row['close'] - row['open'])
        wick_ratio = (candle_size - body) / candle_size if candle_size != 0 else 1
        
        # Reject if wick > 60% (fake spike)
        if wick_ratio >= 0.6:
            continue
        
        if vol_spike:
            # Long: close > VWAP and higher highs
            prev_high = df['high'].iloc[i-5:i].max()
            if row['close'] > row['vwap'] and row['close'] > prev_high * 0.999:
                signals.append({
                    'direction': 'long',
                    'entry_price': row['close'],
                    'entry_time': timestamp,
                    'index': i,
                    'wick_ratio': wick_ratio
                })
            # Short: close < VWAP and lower lows
            else:
                prev_low = df['low'].iloc[i-5:i].min()
                if row['close'] < row['vwap'] and row['close'] < prev_low * 1.001:
                    signals.append({
                        'direction': 'short',
                        'entry_price': row['close'],
                        'entry_time': timestamp,
                        'index': i,
                        'wick_ratio': wick_ratio
                    })
    
    return signals

def run_backtest(df, signals, stop_pts=1.0, tp1_pts=1.5, tp2_pts=2.0):
    """
    Run backtest with 2-tier exit:
    - TP1 at +1.5R (partial close)
    - TP2 at +2R (runner)
    - SL at -1R
    """
    if not signals:
        return None
    
    total_pnl = 0
    wins = 0
    losses = 0
    current_streak = 0
    max_loss_streak = 0
    tp1_hits = 0
    tp2_hits = 0
    sl_hits = 0
    
    results = []
    
    for signal in signals:
        idx = signal['index']
        direction = signal['direction']
        entry_price = signal['entry_price']
        entry_time = signal['entry_time']
        
        if idx >= len(df) - 1:
            continue
        
        # Calculate stop/target prices
        if direction == 'long':
            sl_price = entry_price - stop_pts
            tp1_price = entry_price + tp1_pts
            tp2_price = entry_price + tp2_pts
        else:
            sl_price = entry_price + stop_pts
            tp1_price = entry_price - tp1_pts
            tp2_price = entry_price - tp2_pts
        
        # Simulate trade
        exit_price = None
        exit_type = None
        pnl = 0
        
        for j in range(idx + 1, min(idx + 60, len(df))):
            bar = df.iloc[j]
            high, low = bar['high'], bar['low']
            
            if direction == 'long':
                # Check SL
                if low <= sl_price:
                    pnl = -stop_pts * POINT_VALUE * 4  # 4 ticks per point
                    exit_price = sl_price
                    exit_type = 'sl'
                    losses += 1
                    current_streak += 1
                    max_loss_streak = max(max_loss_streak, current_streak)
                    break
                # Check TP2 first (higher target)
                if high >= tp2_price:
                    pnl = tp2_pts * POINT_VALUE * 4
                    exit_price = tp2_price
                    exit_type = 'tp2'
                    tp2_hits += 1
                    wins += 1
                    current_streak = 0
                    break
                # Check TP1
                if high >= tp1_price:
                    # Partial exit at TP1, but for simplicity count full
                    pnl = tp1_pts * POINT_VALUE * 4
                    exit_price = tp1_price
                    exit_type = 'tp1'
                    tp1_hits += 1
                    wins += 1
                    current_streak = 0
                    break
            else:  # short
                # Check SL
                if high >= sl_price:
                    pnl = -stop_pts * POINT_VALUE * 4
                    exit_price = sl_price
                    exit_type = 'sl'
                    losses += 1
                    current_streak += 1
                    max_loss_streak = max(max_loss_streak, current_streak)
                    break
                # Check TP2
                if low <= tp2_price:
                    pnl = tp2_pts * POINT_VALUE * 4
                    exit_price = tp2_price
                    exit_type = 'tp2'
                    tp2_hits += 1
                    wins += 1
                    current_streak = 0
                    break
                # Check TP1
                if low <= tp1_price:
                    pnl = tp1_pts * POINT_VALUE * 4
                    exit_price = tp1_price
                    exit_type = 'tp1'
                    tp1_hits += 1
                    wins += 1
                    current_streak = 0
                    break
        
        if exit_type is None:
            # Time exit
            exit_price = df.iloc[min(idx + 59, len(df) - 1)]['close']
            pnl = (exit_price - entry_price) if direction == 'long' else (entry_price - exit_price)
            pnl *= POINT_VALUE * 4
            exit_type = 'time'
            if pnl > 0:
                wins += 1
                current_streak = 0
            else:
                losses += 1
                current_streak += 1
                max_loss_streak = max(max_loss_streak, current_streak)
        
        total_pnl += pnl
        
        results.append({
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': pnl,
            'exit_type': exit_type,
            'entry_time': entry_time
        })
    
    total_trades = wins + losses
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
    
    return {
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl,
        'max_loss_streak': max_loss_streak,
        'tp1_hits': tp1_hits,
        'tp2_hits': tp2_hits,
        'sl_hits': sl_hits,
        'results': pd.DataFrame(results)
    }

def main():
    print("="*70)
    print("ES FUTURES BACKTEST - OPTIONS A/B/C COMPARISON")
    print("6 Months | 1R Stop | 1.5R/2R Targets")
    print("="*70)
    
    if not DATABENTO_KEY:
        print("[ERROR] Set DATABENTO_KEY environment variable")
        return
    
    # Fetch 6 months data
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=180)
    
    df = fetch_es_data(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    
    if df is None:
        print("[ERROR] Failed to fetch data")
        return
    
    print(f"\nData: {df.index[0]} to {df.index[-1]}")
    print(f"Bars: {len(df)}")
    
    # Run all 3 options
    options = {
        'A': ('First 90min + VWAP + 3-bar break + 2.2x volume', option_A),
        'B': ('ADX regime filter (>18) + 2x volume', option_B),
        'C': ('Structure + wick filter (<60%) + 2x volume', option_C)
    }
    
    all_results = {}
    
    for opt_name, (opt_desc, opt_func) in options.items():
        print(f"\n{'='*70}")
        print(f"OPTION {opt_name}: {opt_desc}")
        print(f"{'='*70}")
        
        signals = opt_func(df)
        print(f"Signals generated: {len(signals)}")
        
        if signals:
            result = run_backtest(df, signals)
            all_results[opt_name] = result
            
            print(f"\n  RESULTS:")
            print(f"    Trades: {result['total_trades']}")
            print(f"    Win Rate: {result['win_rate']:.1f}% ({result['wins']}W / {result['losses']}L)")
            print(f"    Total P&L: ${result['total_pnl']:.2f}")
            print(f"    Avg per trade: ${result['avg_pnl']:.2f}")
            print(f"    Max Loss Streak: {result['max_loss_streak']}")
            print(f"    TP1 hits: {result['tp1_hits']} | TP2 hits: {result['tp2_hits']}")
        else:
            print("  [NO SIGNALS]")
    
    # Summary comparison
    if all_results:
        print(f"\n{'='*70}")
        print("COMPARISON SUMMARY")
        print(f"{'='*70}")
        print(f"{'Option':<8} {'Trades':>10} {'Win%':>8} {'Total $':>12} {'Avg $':>10} {'Max SL':>8}")
        print("-"*70)
        
        for opt_name in ['A', 'B', 'C']:
            if opt_name in all_results:
                r = all_results[opt_name]
                print(f"{opt_name:<8} {r['total_trades']:>10} {r['win_rate']:>7.1f}% ${r['total_pnl']:>10.2f} ${r['avg_pnl']:>9.2f} {r['max_loss_streak']:>7}")
        
        # Save results
        date_str = datetime.now().strftime('%Y%m%d')
        for opt_name, result in all_results.items():
            result['results'].to_csv(f'es_opt{opt_name}_{date_str}.csv', index=False)
        print(f"\n[SAVED] es_optA/B/C_{date_str}.csv")

if __name__ == '__main__':
    main()
