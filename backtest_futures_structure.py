"""
Futures Backtest v4 - Structure + Imbalance + Regime Filter
24/7 data with improved entry logic
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import databento as db

DATABENTO_KEY = os.getenv('DATABENTO_KEY', '')

FUTURES_CONFIG = {
    'ES': {'schema_symbol': 'ES.c.0', 'stop': 1.0, 'target': 2.0, 'tick_value': 12.50, 'name': 'E-mini S&P'},
    'MES': {'schema_symbol': 'MES.c.0', 'stop': 10.0, 'target': 20.0, 'tick_value': 1.25, 'name': 'Micro E-mini S&P'},
    'NQ': {'schema_symbol': 'NQ.c.0', 'stop': 2.5, 'target': 5.0, 'tick_value': 5.00, 'name': 'E-mini Nasdaq'},
    'MNQ': {'schema_symbol': 'MNQ.c.0', 'stop': 25.0, 'target': 50.0, 'tick_value': 0.50, 'name': 'Micro E-mini Nasdaq'},
}

def fetch_futures_data(symbol_schema, start_date, end_date):
    if not DATABENTO_KEY:
        print("[ERROR] No DATABENTO_KEY set")
        return None
    try:
        client = db.Historical(DATABENTO_KEY)
        print(f"  Fetching {symbol_schema}...")
        data = client.timeseries.get_range(
            dataset='GLBX.MDP3', stype_in='continuous', symbols=[symbol_schema],
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

def add_time_features(df):
    """Add time-based features including session info"""
    df = df.copy()
    ts = pd.to_datetime(df.index)
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    df['ts_est'] = ts.tz_convert('US/Eastern')
    df['hour'] = df['ts_est'].dt.hour
    df['minute'] = df['ts_est'].dt.minute
    df['date'] = df['ts_est'].dt.date
    
    # Session markers
    df['is_rth'] = (df['hour'] >= 9) & (df['hour'] < 16)  # 9:30-4:00 but hour check covers it
    df['after_first_30'] = (df['hour'] > 9) | ((df['hour'] == 9) & (df['minute'] >= 30))  # Skip first 30 min
    return df

def calculate_vwap(df):
    """Calculate VWAP for each day"""
    df = df.copy()
    df['vwap'] = np.nan
    for date in df['date'].unique():
        mask = df['date'] == date
        day_data = df[mask]
        tp = (day_data['high'] + day_data['low'] + day_data['close']) / 3
        vwap = (tp * day_data['volume']).cumsum() / day_data['volume'].cumsum()
        df.loc[mask, 'vwap'] = vwap
    return df

def add_structure_levels(df):
    """
    Calculate key structure levels:
    - Prior day high/low
    - Opening range (first 30 min high/low)
    - VWAP
    """
    df = df.copy()
    df = add_time_features(df)
    df = calculate_vwap(df)
    
    # Prior day high/low
    df['prior_day_high'] = np.nan
    df['prior_day_low'] = np.nan
    df['overnight_high'] = np.nan
    df['overnight_low'] = np.nan
    
    dates = sorted(df['date'].unique())
    for i, date in enumerate(dates):
        if i == 0:
            continue
        prior_date = dates[i-1]
        prior_data = df[df['date'] == prior_date]
        today_data = df[df['date'] == date]
        
        if len(prior_data) > 0:
            df.loc[df['date'] == date, 'prior_day_high'] = prior_data['high'].max()
            df.loc[df['date'] == date, 'prior_day_low'] = prior_data['low'].min()
    
    # Opening range (first 30 minutes of RTH)
    df['opening_high'] = np.nan
    df['opening_low'] = np.nan
    
    for date in dates:
        day_mask = df['date'] == date
        day_data = df[day_mask]
        
        # First 30 min of RTH (9:30-10:00)
        opening = day_data[(day_data['hour'] == 9) & (day_data['minute'] >= 30) | 
                          (day_data['hour'] == 10) & (day_data['minute'] <= 0)]
        if len(opening) > 0:
            df.loc[day_mask, 'opening_high'] = opening['high'].max()
            df.loc[day_mask, 'opening_opening_low'] = opening['low'].min()
    
    return df

def add_regime_filter(df):
    """
    Regime filter: Trade only when:
    - Volatility is expanding (ATR > ATR_sma)
    - Not in tight compression
    """
    df = df.copy()
    
    # ATR
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['atr_sma'] = df['atr'].rolling(20).mean()
    
    # Volatility expansion = ATR > ATR_sma (more volatile = better for breakouts)
    df['vol_expanding'] = df['atr'] > df['atr_sma']
    
    # Compression detection (low ATR vs recent)
    df['atr_percentile'] = df['atr'].rolling(50).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) > 1 else 0.5)
    df['compression'] = df['atr_percentile'] < 0.3  # Bottom 30% of ATR = compression
    
    # VWAP slope (trending vs mean-reverting)
    df['vwap_slope'] = df['vwap'].diff(5)  # 5-bar change
    df['vwap_trending'] = df['vwap_slope'].abs() > (df['atr'] * 0.3)
    
    # GOOD REGIME: Vol expanding + not compressed + VWAP trending
    df['good_regime'] = df['vol_expanding'] & ~df['compression'] & df['vwap_trending']
    
    return df

def add_imbalance(df):
    """
    Imbalance: Order flow proxy
    - Candle body strength (close position in range)
    - Delta proxy (volume weighted by close position)
    """
    df = df.copy()
    
    # Body position (0 = low, 1 = high)
    df['range'] = df['high'] - df['low']
    df['body_pos'] = (df['close'] - df['low']) / df['range']
    df['body_pos'] = df['body_pos'].fillna(0.5)
    
    # Strong imbalance: close near high on up candles, near low on down candles
    df['up_imbalance'] = (df['close'] > df['open']) & (df['body_pos'] > 0.7)
    df['down_imbalance'] = (df['close'] < df['open']) & (df['body_pos'] < 0.3)
    
    # Imbalance score (volume weighted)
    vol_avg = df['volume'].rolling(20).mean()
    df['vol_spike'] = df['volume'] > (vol_avg * 2.0)
    
    # Strong move: high volume + imbalance
    df['strong_up'] = df['vol_spike'] & df['up_imbalance']
    df['strong_down'] = df['vol_spike'] & df['down_imbalance']
    
    return df

def generate_signals_structure(df):
    """
    STRUCTURE-BASED SIGNALS:
    1. Volume spike > 2x
    2. Break of meaningful structure (prior day H/L, opening range, VWAP reclaim)
    3. Imbalance confirmation (close near high/low)
    4. Skip first 30 min of RTH
    5. Good regime only (vol expanding, not compressed)
    """
    df = add_structure_levels(df)
    df = add_regime_filter(df)
    df = add_imbalance(df)
    
    signals = []
    
    for i in range(50, len(df) - 1):
        row = df.iloc[i]
        
        # FILTER 1: Skip first 30 min of RTH
        if not row['after_first_30']:
            continue
        
        # FILTER 2: Good regime only
        if not row['good_regime']:
            continue
        
        # FILTER 3: Volume spike
        if not row['vol_spike']:
            continue
        
        entry_price = df.iloc[i + 1]['open']
        timestamp = df.index[i + 1]
        
        # LONG STRUCTURE BREAKS:
        # 1. Break above prior day high
        if row['strong_up'] and not pd.isna(row['prior_day_high']) and row['close'] > row['prior_day_high']:
            signals.append({
                'direction': 'long', 'entry_price': entry_price, 'timestamp': timestamp,
                'idx': i + 1, 'trigger': 'prior_day_high_break', 'imbalance': row['body_pos']
            })
            continue
        
        # 2. Break above opening range high
        if row['strong_up'] and not pd.isna(row.get('opening_high')) and row['close'] > row['opening_high']:
            signals.append({
                'direction': 'long', 'entry_price': entry_price, 'timestamp': timestamp,
                'idx': i + 1, 'trigger': 'opening_range_high', 'imbalance': row['body_pos']
            })
            continue
        
        # 3. VWAP reclaim (was below, now above with volume)
        prev_vwap = df.iloc[i-1]['vwap']
        if row['strong_up'] and row['close'] > row['vwap'] and df.iloc[i-1]['close'] < prev_vwap:
            signals.append({
                'direction': 'long', 'entry_price': entry_price, 'timestamp': timestamp,
                'idx': i + 1, 'trigger': 'vwap_reclaim', 'imbalance': row['body_pos']
            })
            continue
        
        # SHORT STRUCTURE BREAKS:
        # 1. Break below prior day low
        if row['strong_down'] and not pd.isna(row['prior_day_low']) and row['close'] < row['prior_day_low']:
            signals.append({
                'direction': 'short', 'entry_price': entry_price, 'timestamp': timestamp,
                'idx': i + 1, 'trigger': 'prior_day_low_break', 'imbalance': row['body_pos']
            })
            continue
        
        # 2. Break below opening range low
        if row['strong_down'] and not pd.isna(row.get('opening_low')) and row['close'] < row['opening_low']:
            signals.append({
                'direction': 'short', 'entry_price': entry_price, 'timestamp': timestamp,
                'idx': i + 1, 'trigger': 'opening_range_low', 'imbalance': row['body_pos']
            })
            continue
        
        # 3. VWAP lose (was above, now below with volume)
        if row['strong_down'] and row['close'] < row['vwap'] and df.iloc[i-1]['close'] > prev_vwap:
            signals.append({
                'direction': 'short', 'entry_price': entry_price, 'timestamp': timestamp,
                'idx': i + 1, 'trigger': 'vwap_lose', 'imbalance': row['body_pos']
            })
            continue
    
    return signals

def backtest_futures(df, signals, stop_pts, target_pts, point_value):
    """Simple backtest with 1R stop / 2R target"""
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
            sl, tp = entry - stop_pts, entry + target_pts
        else:
            sl, tp = entry + stop_pts, entry - target_pts
        
        pnl = 0
        win = False
        
        for j in range(idx + 1, min(idx + 60, len(df))):
            bar = df.iloc[j]
            if direction == 'long':
                if bar['low'] <= sl:
                    pnl = -stop_pts * 4 * point_value
                    win = False
                    break
                if bar['high'] >= tp:
                    pnl = target_pts * 4 * point_value
                    win = True
                    break
            else:
                if bar['high'] >= sl:
                    pnl = -stop_pts * 4 * point_value
                    win = False
                    break
                if bar['low'] <= tp:
                    pnl = target_pts * 4 * point_value
                    win = True
                    break
        
        if pnl == 0:  # Time exit
            exit_p = df.iloc[min(idx + 59, len(df) - 1)]['close']
            pnl = (exit_p - entry) * 4 * point_value if direction == 'long' else (entry - exit_p) * 4 * point_value
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
        'total_pnl': total_pnl, 'avg_pnl': total_pnl / total if total > 0 else 0,
        'max_streak': max_streak, 'signals': signals
    }

def backtest_symbol(symbol_key, days_back=180):
    config = FUTURES_CONFIG[symbol_key]
    print(f"\n{'='*70}")
    print(f"[{symbol_key}] {config['name']}")
    print(f"Stop: {config['stop']} pts | Target: {config['target']} pts | Structure + Imbalance")
    print(f"{'='*70}")
    
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back)
    
    df = fetch_futures_data(config['schema_symbol'], 
                            start_date.strftime('%Y-%m-%d'), 
                            end_date.strftime('%Y-%m-%d'))
    
    if df is None or len(df) < 5000:
        print(f"  [SKIP] Insufficient data")
        return None
    
    print(f"  Range: {df.index[0].date()} to {df.index[-1].date()}")
    
    signals = generate_signals_structure(df)
    print(f"  Signals generated: {len(signals)}")
    
    if len(signals) > 0:
        # Show breakdown
        triggers = {}
        for s in signals:
            t = s['trigger']
            triggers[t] = triggers.get(t, 0) + 1
        print(f"  Trigger breakdown: {triggers}")
    
    if signals:
        result = backtest_futures(df, signals, config['stop'], config['target'], config['tick_value'])
        print(f"\n  RESULTS:")
        print(f"    Trades: {result['trades']} | WR: {result['win_rate']:.1f}%")
        print(f"    Total P&L: ${result['total_pnl']:.2f} | Avg: ${result['avg_pnl']:.2f}")
        print(f"    Max Loss Streak: {result['max_streak']}")
        return result
    return None

def main():
    print("="*70)
    print("FUTURES BACKTEST - STRUCTURE + IMBALANCE + REGIME")
    print("Filters: First 30min skip | Vol expanding | Structure break | Imbalance")
    print("="*70)
    
    if not DATABENTO_KEY:
        print("[ERROR] Set DATABENTO_KEY")
        return
    
    all_results = {}
    for symbol in ['ES', 'MES', 'NQ', 'MNQ']:
        result = backtest_symbol(symbol, days_back=180)
        if result:
            all_results[symbol] = result
    
    if all_results:
        print(f"\n{'='*70}")
        print("SUMMARY COMPARISON")
        print(f"{'='*70}")
        print(f"{'Symbol':<8} {'Trades':>10} {'WR%':>8} {'Total $':>12} {'Avg $':>10} {'Max SL':>8}")
        print("-"*70)
        for sym, r in all_results.items():
            print(f"{sym:<8} {r['trades']:>10} {r['win_rate']:>7.1f}% ${r['total_pnl']:>10.2f} ${r['avg_pnl']:>9.2f} {r['max_streak']:>7}")
        
        # Save
        date_str = datetime.now().strftime('%Y%m%d')
        for sym, r in all_results.items():
            if r['signals']:
                df_sig = pd.DataFrame(r['signals'])
                df_sig.to_csv(f'futures_structure_{sym}_{date_str}.csv', index=False)
        print(f"\n[SAVED] futures_structure_*_{date_str}.csv")

if __name__ == '__main__':
    main()
