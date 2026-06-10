"""
Futures Backtest with Databento Python Client
6 months data, ES/MES/NQ/MNQ with 1R/2R targets
Includes consecutive loss streak analysis
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

SLACK_MAX = 0.8

def fetch_databento(symbol_schema, start_date, end_date):
    if not DATABENTO_KEY:
        print("[ERROR] No DATABENTO_KEY set")
        return None
    try:
        print(f"  Connecting to Databento...")
        client = db.Historical(DATABENTO_KEY)
        print(f"  Requesting {symbol_schema} ({start_date} to {end_date})...")
        data = client.timeseries.get_range(
            dataset='GLBX.MDP3',
            stype_in='continuous',
            symbols=[symbol_schema],
            schema='ohlcv-1m',
            start=start_date + 'T00:00:00',
            end=end_date + 'T16:00:00',
        )
        if data is None:
            print(f"  [WARN] No data returned")
            return None
        df = data.to_df()
        if len(df) == 0:
            print(f"  [WARN] Empty dataframe")
            return None
        
        # Filter to market hours only (9:30 AM - 4:00 PM EST)
        # Databento timestamps are UTC, EST is UTC-5 (or UTC-4 during DST)
        # Market open: 9:30 AM EST = 13:30 UTC (EST) or 14:30 UTC (EDT)
        # Market close: 4:00 PM EST = 20:00 UTC (EST) or 21:00 UTC (EDT)
        # We'll use 13:30 to 21:00 UTC to cover both EST and EDT
        df.index = pd.to_datetime(df.index)
        # Convert to EST for filtering
        df['hour_est'] = df.index.tz_convert('US/Eastern').hour
        df['minute_est'] = df.index.tz_convert('US/Eastern').minute
        
        # Market hours: 9:30 AM to 4:00 PM EST
        market_open = (df['hour_est'] == 9) & (df['minute_est'] >= 30) | (df['hour_est'] > 9) & (df['hour_est'] < 16)
        df = df[market_open].copy()
        df = df.drop(columns=['hour_est', 'minute_est'])
        
        print(f"  Got {len(df)} bars (market hours only)")
        return df
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def get_boof_signals(df):
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
            signals.append({'bar': i + 1, 'direction': 'short', 'slack': peak_slack,
                          'entry_price': df.iloc[i + 1]['open'], 'timestamp': df.index[i + 1]})
        elif fractal_trough and atr_bounced_trough and trough_slack < SLACK_MAX:
            signals.append({'bar': i + 1, 'direction': 'long', 'slack': trough_slack,
                          'entry_price': df.iloc[i + 1]['open'], 'timestamp': df.index[i + 1]})
    return signals

def test_futures_trade(df, signal, stop_pts, target_pts, max_bars=60):
    entry_bar = signal['bar']
    if entry_bar >= len(df):
        return False, 0, 'error', 0
    entry_price = signal['entry_price']
    direction = signal['direction']
    if direction == 'long':
        stop_price = entry_price - stop_pts
        target_price = entry_price + target_pts
    else:
        stop_price = entry_price + stop_pts
        target_price = entry_price - target_pts
    for i in range(entry_bar, min(entry_bar + max_bars, len(df))):
        high, low = df.iloc[i]['high'], df.iloc[i]['low']
        if direction == 'long':
            if low <= stop_price:
                return True, -stop_pts, 'sl', i - entry_bar
            if high >= target_price:
                return True, target_pts, 'tp', i - entry_bar
        else:
            if high >= stop_price:
                return True, -stop_pts, 'sl', i - entry_bar
            if low <= target_price:
                return True, target_pts, 'tp', i - entry_bar
    exit_price = df.iloc[min(entry_bar + max_bars - 1, len(df) - 1)]['close']
    pnl = exit_price - entry_price
    if direction == 'short':
        pnl = -pnl
    return False, pnl, 'time', max_bars

def analyze_streaks(pnl_list):
    max_loss_streak = 0
    current_loss = 0
    loss_streaks = []
    for pnl in pnl_list:
        if pnl < 0:
            current_loss += 1
            max_loss_streak = max(max_loss_streak, current_loss)
        else:
            if current_loss > 0:
                loss_streaks.append(current_loss)
            current_loss = 0
    if current_loss > 0:
        loss_streaks.append(current_loss)
    return max_loss_streak, loss_streaks

def backtest_futures(symbol_key, days_back=180):
    config = FUTURES_CONFIG[symbol_key]
    print(f"\n{'='*60}")
    print(f"[{symbol_key}] {config['name']} | Stop: {config['stop']} pts | Target: {config['target']} pts")
    print(f"{'='*60}")
    # Use yesterday as end date since today's data may not be available
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back)
    df = fetch_databento(config['schema_symbol'], start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    if df is None or len(df) < 5000:
        print(f"  [SKIP] Insufficient data")
        return None
    print(f"  Range: {df.index[0].date()} to {df.index[-1].date()}")
    signals = get_boof_signals(df)
    print(f"  Signals: {len(signals)}")
    if not signals:
        return None
    results = []
    for signal in signals:
        hit, pnl_pts, exit_type, bars = test_futures_trade(df, signal, config['stop'], config['target'])
        ticks_per_point = 4
        dollar_pnl = pnl_pts * ticks_per_point * config['tick_value']
        results.append({'timestamp': signal['timestamp'], 'direction': signal['direction'],
                       'slack': signal['slack'], 'entry': signal['entry_price'], 'hit': hit,
                       'pnl_pts': pnl_pts, 'pnl_dollar': dollar_pnl, 'exit_type': exit_type, 'bars': bars})
    df_res = pd.DataFrame(results)
    total = len(df_res)
    wins = len(df_res[df_res['pnl_pts'] > 0])
    losses = len(df_res[df_res['pnl_pts'] < 0])
    win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    total_pnl = df_res['pnl_dollar'].sum()
    avg_pnl = df_res['pnl_dollar'].mean()
    tp_hits = len(df_res[df_res['exit_type'] == 'tp'])
    sl_hits = len(df_res[df_res['exit_type'] == 'sl'])
    time_exits = len(df_res[df_res['exit_type'] == 'time'])
    max_streak, streaks = analyze_streaks(df_res['pnl_pts'].tolist())
    print(f"\n  RESULTS:")
    print(f"    Total Trades: {total}")
    print(f"    Win Rate: {win_rate:.1f}% ({wins} wins / {losses} losses)")
    print(f"    Total P&L: ${total_pnl:.2f}")
    print(f"    Avg P&L per trade: ${avg_pnl:.2f}")
    print(f"    TP hits: {tp_hits} | SL hits: {sl_hits} | Time exits: {time_exits}")
    print(f"    Max Consecutive Losses: {max_streak}")
    if streaks:
        print(f"    Loss streak distribution: {sorted(set(streaks), reverse=True)[:10]}")
    return {'symbol': symbol_key, 'total_trades': total, 'win_rate': win_rate, 'total_pnl': total_pnl,
            'avg_pnl': avg_pnl, 'tp_hits': tp_hits, 'sl_hits': sl_hits, 'time_exits': time_exits,
            'max_loss_streak': max_streak, 'data': df_res}

def main():
    print("="*70)
    print("6-MONTH FUTURES BACKTEST WITH DATABENTO")
    print("Boof 22/23 + 1R/2R Targets")
    print("="*70)
    if not DATABENTO_KEY:
        print("[ERROR] DATABENTO_KEY not set")
        return
    all_results = {}
    for symbol_key in ['ES', 'MES', 'NQ', 'MNQ']:
        result = backtest_futures(symbol_key, days_back=180)
        if result:
            all_results[symbol_key] = result
    if not all_results:
        print("\n[ERROR] No results")
        return
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"{'Symbol':<8} {'Trades':>10} {'WR%':>8} {'Total $':>12} {'Avg $':>10} {'Max SL':>8}")
    print("-"*70)
    for symbol_key, r in all_results.items():
        print(f"{symbol_key:<8} {r['total_trades']:>10} {r['win_rate']:>7.1f}% ${r['total_pnl']:>10.2f} ${r['avg_pnl']:>9.2f} {r['max_loss_streak']:>7}")
    date_str = datetime.now().strftime('%Y%m%d')
    for symbol_key, result in all_results.items():
        result['data'].to_csv(f'futures_{symbol_key}_6mo_{date_str}.csv', index=False)
    print(f"\n[SAVED] futures_*_6mo_{date_str}.csv")

if __name__ == '__main__':
    main()
