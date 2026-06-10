"""
Futures Backtest with Databento Data
ES, MES, NQ, MNQ with 1R/2R targets
"""
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

# Databento API
DATABENTO_KEY = os.getenv('DATABENTO_KEY', '')
DATABENTO_URL = 'https://hist.databento.com/v0'

# Futures config
FUTURES_CONFIG = {
    'ES': {'symbol': 'ES.c.0', 'stop': 1.0, 'target': 2.0, 'tick_value': 12.50, 'name': 'E-mini S&P'},
    'MES': {'symbol': 'MES.c.0', 'stop': 10.0, 'target': 20.0, 'tick_value': 1.25, 'name': 'Micro E-mini S&P'},
    'NQ': {'symbol': 'NQ.c.0', 'stop': 2.5, 'target': 5.0, 'tick_value': 5.00, 'name': 'E-mini Nasdaq'},
    'MNQ': {'symbol': 'MNQ.c.0', 'stop': 25.0, 'target': 50.0, 'tick_value': 0.50, 'name': 'Micro E-mini Nasdaq'},
}

SLACK_MAX = 0.8

def fetch_databento_data(symbol, start_date, end_date, schema='ohlcv-1m'):
    """Fetch historical data from Databento"""
    if not DATABENTO_KEY:
        print("[ERROR] No DATABENTO_KEY set")
        return None
    
    url = f"{DATABENTO_URL}/timeseries.get_range"
    headers = {'Authorization': DATABENTO_KEY}
    
    # Convert dates to required format
    start_dt = f"{start_date}T00:00:00"
    end_dt = f"{end_date}T23:59:59"
    
    params = {
        'dataset': 'GLBX.MDP3',
        'symbols': symbol,
        'schema': schema,
        'start': start_dt,
        'end': end_dt,
        'stype_in': 'raw_symbol',
    }
    
    print(f"  Fetching {symbol} from Databento...")
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data and len(data['data']) > 0:
                return process_databento_data(data['data'])
            else:
                print(f"  [WARN] No data returned for {symbol}")
                return None
        else:
            print(f"  [ERROR] Status {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"  [ERROR] {symbol}: {e}")
        return None

def process_databento_data(records):
    """Convert Databento records to DataFrame"""
    # Databento OHLCV format
    df = pd.DataFrame(records)
    
    # Map columns
    if 'ts_event' in df.columns:
        df['timestamp'] = pd.to_datetime(df['ts_event'], unit='ns')
    elif 'ts_event' in df.columns:
        df['timestamp'] = pd.to_datetime(df['ts_event'])
    else:
        df['timestamp'] = pd.to_datetime(df.index)
    
    df = df.rename(columns={
        'open': 'open',
        'high': 'high', 
        'low': 'low',
        'close': 'close',
        'volume': 'volume'
    })
    
    df = df.set_index('timestamp').sort_index()
    return df

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def get_boof_signals(df):
    """Boof 22/23 signals with Slack < 0.8"""
    signals = []
    atr = compute_atr(df)
    
    for i in range(50, len(df) - 1):
        if atr.iloc[i] == 0:
            continue
        
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
            signals.append({
                'bar': i + 1,
                'direction': 'short',
                'slack': peak_slack,
                'entry_price': df.iloc[i + 1]['open'],
                'timestamp': df.index[i + 1]
            })
        elif fractal_trough and atr_bounced_trough and trough_slack < SLACK_MAX:
            signals.append({
                'bar': i + 1,
                'direction': 'long',
                'slack': trough_slack,
                'entry_price': df.iloc[i + 1]['open'],
                'timestamp': df.index[i + 1]
            })
    
    return signals

def test_futures_trade(df, signal, stop_pts, target_pts, max_bars=60):
    """
    Test futures trade with specific stop/target in points
    Returns: hit, pnl_points, exit_type, bars
    """
    entry_bar = signal['bar']
    if entry_bar >= len(df):
        return False, 0, 'error', 0
    
    entry_price = signal['entry_price']
    direction = signal['direction']
    
    # Calculate stop/target prices
    if direction == 'long':
        stop_price = entry_price - stop_pts
        target_price = entry_price + target_pts
    else:  # short
        stop_price = entry_price + stop_pts
        target_price = entry_price - target_pts
    
    for i in range(entry_bar, min(entry_bar + max_bars, len(df))):
        high = df.iloc[i]['high']
        low = df.iloc[i]['low']
        
        if direction == 'long':
            # Check stop loss (low went below stop)
            if low <= stop_price:
                return True, -stop_pts, 'sl', i - entry_bar
            # Check target (high reached target)
            if high >= target_price:
                return True, target_pts, 'tp', i - entry_bar
        else:  # short
            # Check stop loss (high went above stop)
            if high >= stop_price:
                return True, -stop_pts, 'sl', i - entry_bar
            # Check target (low reached target)
            if low <= target_price:
                return True, target_pts, 'tp', i - entry_bar
    
    # Time exit
    exit_price = df.iloc[min(entry_bar + max_bars - 1, len(df) - 1)]['close']
    pnl = exit_price - entry_price
    if direction == 'short':
        pnl = -pnl
    
    return False, pnl, 'time', max_bars

def analyze_consecutive_losses(pnl_list):
    """Find max consecutive loss streak"""
    max_streak = 0
    current_streak = 0
    streaks = []
    
    for pnl in pnl_list:
        if pnl < 0:  # Loss
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:  # Win or breakeven
            if current_streak > 0:
                streaks.append(current_streak)
            current_streak = 0
    
    if current_streak > 0:
        streaks.append(current_streak)
    
    return max_streak, streaks

def backtest_futures(symbol_key, days_back=30):
    """Run backtest for one futures symbol"""
    config = FUTURES_CONFIG[symbol_key]
    
    print(f"\n{'='*60}")
    print(f"[{symbol_key}] {config['name']}")
    print(f"Stop: {config['stop']} pts | Target: {config['target']} pts")
    print(f"Risk: ${config['stop'] * config['tick_value'] * (4 if symbol_key in ['ES', 'NQ'] else 4):.2f}")
    print(f"{'='*60}")
    
    # Date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    # Fetch data
    df = fetch_databento_data(config['symbol'], 
                               start_date.strftime('%Y-%m-%d'),
                               end_date.strftime('%Y-%m-%d'))
    
    if df is None or len(df) < 1000:
        print(f"  [SKIP] Insufficient data")
        return None
    
    print(f"  Data: {len(df)} bars ({df.index[0].date()} to {df.index[-1].date()})")
    
    # Get signals
    signals = get_boof_signals(df)
    print(f"  Signals: {len(signals)}")
    
    if not signals:
        return None
    
    # Test each signal
    results = []
    for signal in signals:
        hit, pnl_pts, exit_type, bars = test_futures_trade(
            df, signal, config['stop'], config['target']
        )
        
        # Convert points to dollars
        tick_size = 0.25
        ticks_per_point = 4
        dollar_pnl = pnl_pts * ticks_per_point * config['tick_value']
        
        results.append({
            'timestamp': signal['timestamp'],
            'direction': signal['direction'],
            'slack': signal['slack'],
            'entry': signal['entry_price'],
            'hit': hit,
            'pnl_pts': pnl_pts,
            'pnl_dollar': dollar_pnl,
            'exit_type': exit_type,
            'bars': bars
        })
    
    df_results = pd.DataFrame(results)
    
    # Analyze
    total = len(df_results)
    wins = len(df_results[df_results['pnl_pts'] > 0])
    losses = len(df_results[df_results['pnl_pts'] < 0])
    win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    
    total_pnl = df_results['pnl_dollar'].sum()
    avg_pnl = df_results['pnl_dollar'].mean()
    
    tp_hits = len(df_results[df_results['exit_type'] == 'tp'])
    sl_hits = len(df_results[df_results['exit_type'] == 'sl'])
    time_exits = len(df_results[df_results['exit_type'] == 'time'])
    
    # Consecutive losses
    pnl_list = df_results['pnl_pts'].tolist()
    max_streak, streaks = analyze_consecutive_losses(pnl_list)
    
    print(f"\n  RESULTS:")
    print(f"    Total Trades: {total}")
    print(f"    Win Rate: {win_rate:.1f}% ({wins} wins / {losses} losses)")
    print(f"    Total P&L: ${total_pnl:.2f}")
    print(f"    Avg P&L per trade: ${avg_pnl:.2f}")
    print(f"    TP hits: {tp_hits} | SL hits: {sl_hits} | Time exits: {time_exits}")
    print(f"    Max Consecutive Losses: {max_streak}")
    if streaks:
        print(f"    Loss streaks: {sorted(set(streaks), reverse=True)[:5]}")
    
    return {
        'symbol': symbol_key,
        'config': config,
        'total_trades': total,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl,
        'tp_hits': tp_hits,
        'sl_hits': sl_hits,
        'time_exits': time_exits,
        'max_loss_streak': max_streak,
        'data': df_results
    }

def main():
    print("="*80)
    print("DATABENTO FUTURES BACKTEST")
    print("Boof 22/23 with 1R/2R Targets")
    print("="*80)
    
    if not DATABENTO_KEY:
        print("[ERROR] DATABENTO_KEY not set")
        print("Set with: $env:DATABENTO_KEY='your-key'")
        return
    
    # Backtest each futures symbol
    all_results = {}
    for symbol_key in ['ES', 'MES', 'NQ', 'MNQ']:
        result = backtest_futures(symbol_key, days_back=30)
        if result:
            all_results[symbol_key] = result
        time.sleep(1)  # Rate limit
    
    # Summary
    if not all_results:
        print("\n[ERROR] No results")
        return
    
    print("\n" + "="*80)
    print("SUMMARY COMPARISON")
    print("="*80)
    print(f"{'Symbol':<8} {'Trades':>10} {'WR%':>8} {'Total $':>12} {'Avg $':>10} {'Max SL':>8}")
    print("-"*80)
    
    for symbol_key, result in all_results.items():
        print(f"{symbol_key:<8} {result['total_trades']:>10} {result['win_rate']:>7.1f}% ${result['total_pnl']:>10.2f} ${result['avg_pnl']:>9.2f} {result['max_loss_streak']:>7}")
    
    # Save
    date_str = datetime.now().strftime('%Y%m%d')
    for symbol_key, result in all_results.items():
        result['data'].to_csv(f'futures_{symbol_key}_{date_str}.csv', index=False)
    print(f"\n[SAVED] futures_*_{date_str}.csv")

if __name__ == '__main__':
    main()
