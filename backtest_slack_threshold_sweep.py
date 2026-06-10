"""
backtest_slack_threshold_sweep.py
==================================
Test multiple slack thresholds to find optimal for Boof 22/23
Period: Jan 2026 - Apr 2026
"""

import pandas as pd
import numpy as np
from datetime import datetime
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

# Alpaca credentials
creds = get_alpaca_credentials()
API_KEY = creds['api_key']
API_SECRET = creds['secret_key']

# CONFIG
START_DATE = datetime(2026, 1, 1)
END_DATE = datetime(2026, 4, 30)
TP_PCT = 0.001   # +0.1%
SL_PCT = 0.0005  # -0.05%
SYMBOLS = ['NVDA', 'AAPL', 'META', 'GOOGL', 'AMD']
BASE_AMOUNT = 200

# Slack thresholds to test
THRESHOLDS = [0.8, 0.9, 1.0, 1.1, 1.2, 1.4]


def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def find_fractals(highs, lows, bars=3):
    peaks, troughs = [], []
    for i in range(bars, len(highs) - bars):
        if all(highs[i] > highs[i-j] for j in range(1, bars+1)) and all(highs[i] > highs[i+j] for j in range(1, bars+1)):
            peaks.append(i)
        if all(lows[i] < lows[i-j] for j in range(1, bars+1)) and all(lows[i] < lows[i+j] for j in range(1, bars+1)):
            troughs.append(i)
    return peaks, troughs


def backtest_with_threshold(symbol, bars, threshold, strategy='boof22'):
    """Run backtest with specific slack threshold"""
    trades = []
    if len(bars) < 100:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    df['atr'] = compute_atr(df)
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    # Add trend for Boof 23
    if strategy == 'boof23':
        df['swing_high'] = df['high'].rolling(5).max()
        df['swing_low'] = df['low'].rolling(5).min()
        df['trend'] = np.where(df['close'] > df['swing_high'].shift(5), 'up',
                      np.where(df['close'] < df['swing_low'].shift(5), 'down', None))
        df['trend'] = df['trend'].ffill().fillna('neutral')
    
    in_trade = False
    entry_price = entry_time = entry_slack = position_size = trade_direction = None
    
    for i in range(50, len(df) - 1):
        if in_trade:
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= TP_PCT:
                trades.append({
                    'symbol': symbol, 'entry_time': entry_time, 'exit_time': current['timestamp'],
                    'entry': entry_price, 'exit': entry_price * (1 + TP_PCT),
                    'pnl': position_size * TP_PCT, 'slack': entry_slack,
                    'tier': 'core' if entry_slack >= threshold else 'expanded',
                    'result': 'win'
                })
                in_trade = False
            elif change_pct <= -SL_PCT:
                trades.append({
                    'symbol': symbol, 'entry_time': entry_time, 'exit_time': current['timestamp'],
                    'entry': entry_price, 'exit': entry_price * (1 - SL_PCT),
                    'pnl': -position_size * SL_PCT, 'slack': entry_slack,
                    'tier': 'core' if entry_slack >= threshold else 'expanded',
                    'result': 'loss'
                })
                in_trade = False
            continue
        
        if i in peaks or i in troughs:
            current = df.iloc[i]
            is_peak = i in peaks
            atr_val = current['atr'] if current['atr'] > 0 else 0.001
            
            if is_peak:
                wick = current['high'] - max(current['open'], current['close'])
                slack = wick / atr_val
                
                # Boof 23 requires trend up, Boof 22 doesn't
                trend_ok = True if strategy == 'boof22' else df.iloc[i-1]['trend'] == 'up'
                
                if slack >= 0.6 and trend_ok:  # 0.6 is entry threshold
                    in_trade = True
                    trade_direction = 'short'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
                    is_core = slack >= threshold
                    position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
            else:
                wick = min(current['open'], current['close']) - current['low']
                slack = wick / atr_val
                
                trend_ok = True if strategy == 'boof22' else df.iloc[i-1]['trend'] == 'down'
                
                if slack >= 0.6 and trend_ok:
                    in_trade = True
                    trade_direction = 'long'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
                    is_core = slack >= threshold
                    position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
    
    return trades


def analyze_threshold(trades, threshold):
    if not trades:
        return None
    df = pd.DataFrame(trades)
    wins = len(df[df['result'] == 'win'])
    total = len(df)
    
    return {
        'threshold': threshold,
        'trades': total,
        'win_rate': wins / total if total > 0 else 0,
        'avg_pnl': df['pnl'].mean(),
        'total_pnl': df['pnl'].sum(),
        'pf': abs(df[df['pnl'] > 0]['pnl'].sum() / df[df['pnl'] < 0]['pnl'].sum()) if len(df[df['pnl'] < 0]) > 0 and df[df['pnl'] < 0]['pnl'].sum() != 0 else 999,
        'core_pct': len(df[df['tier'] == 'core']) / total * 100 if total > 0 else 0,
        'core_wr': len(df[(df['tier'] == 'core') & (df['result'] == 'win')]) / len(df[df['tier'] == 'core']) if len(df[df['tier'] == 'core']) > 0 else 0,
        'exp_wr': len(df[(df['tier'] == 'expanded') & (df['result'] == 'win')]) / len(df[df['tier'] == 'expanded']) if len(df[df['tier'] == 'expanded']) > 0 else 0,
    }


def main():
    print("=" * 80)
    print("SLACK THRESHOLD SWEEP - Boof 22 vs Boof 23")
    print(f"Period: {START_DATE.date()} to {END_DATE.date()}")
    print(f"TP: {TP_PCT*100:.2f}% | SL: {SL_PCT*100:.2f}%")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print("=" * 80)
    
    # Fetch all data first
    all_bars = {}
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol}...")
        df = fetch_alpaca_bars(symbol, START_DATE, END_DATE, '1Min', API_KEY, API_SECRET)
        if df is not None and len(df) > 100:
            df = df.reset_index().rename(columns={'time': 'timestamp'})
            all_bars[symbol] = df.to_dict('records')
            print(f"  Loaded {len(all_bars[symbol])} bars")
        else:
            print(f"  Failed to load data")
    
    # Test each threshold
    results_22 = {t: [] for t in THRESHOLDS}
    results_23 = {t: [] for t in THRESHOLDS}
    
    for symbol, bars in all_bars.items():
        for threshold in THRESHOLDS:
            trades_22 = backtest_with_threshold(symbol, bars, threshold, 'boof22')
            trades_23 = backtest_with_threshold(symbol, bars, threshold, 'boof23')
            results_22[threshold].extend(trades_22)
            results_23[threshold].extend(trades_23)
    
    # Analyze results
    print("\n" + "=" * 80)
    print("BOOF 22 RESULTS BY THRESHOLD")
    print("=" * 80)
    print(f"{'Threshold':<10} {'Trades':<8} {'Win%':<8} {'Avg $':<8} {'Total $':<10} {'PF':<6} {'Core%':<8} {'CoreWR':<8} {'ExpWR':<8}")
    print("-" * 80)
    
    best_22 = None
    best_score_22 = -999
    
    for t in THRESHOLDS:
        stats = analyze_threshold(results_22[t], t)
        if stats:
            print(f"{stats['threshold']:<10.1f} {stats['trades']:<8} {stats['win_rate']*100:<8.1f} "
                  f"${stats['avg_pnl']:<7.2f} ${stats['total_pnl']:<9.2f} {stats['pf']:<6.1f} "
                  f"{stats['core_pct']:<7.1f}% {stats['core_wr']*100:<7.1f}% {stats['exp_wr']*100:<7.1f}%")
            
            # Score = total P&L * win rate (favor consistent profitability)
            score = stats['total_pnl'] * stats['win_rate']
            if score > best_score_22:
                best_score_22 = score
                best_22 = stats
    
    print("\n" + "=" * 80)
    print("BOOF 23 RESULTS BY THRESHOLD")
    print("=" * 80)
    print(f"{'Threshold':<10} {'Trades':<8} {'Win%':<8} {'Avg $':<8} {'Total $':<10} {'PF':<6} {'Core%':<8} {'CoreWR':<8} {'ExpWR':<8}")
    print("-" * 80)
    
    best_23 = None
    best_score_23 = -999
    
    for t in THRESHOLDS:
        stats = analyze_threshold(results_23[t], t)
        if stats:
            print(f"{stats['threshold']:<10.1f} {stats['trades']:<8} {stats['win_rate']*100:<8.1f} "
                  f"${stats['avg_pnl']:<7.2f} ${stats['total_pnl']:<9.2f} {stats['pf']:<6.1f} "
                  f"{stats['core_pct']:<7.1f}% {stats['core_wr']*100:<7.1f}% {stats['exp_wr']*100:<7.1f}%")
            
            score = stats['total_pnl'] * stats['win_rate']
            if score > best_score_23:
                best_score_23 = score
                best_23 = stats
    
    # Summary
    print("\n" + "=" * 80)
    print("OPTIMAL THRESHOLDS")
    print("=" * 80)
    if best_22:
        print(f"\nBoof 22: Threshold = {best_22['threshold']}")
        print(f"  - {best_22['trades']} trades, {best_22['win_rate']*100:.1f}% WR, ${best_22['total_pnl']:.2f} total")
        print(f"  - {best_22['core_pct']:.1f}% core signals, Core WR: {best_22['core_wr']*100:.1f}%, Exp WR: {best_22['exp_wr']*100:.1f}%")
    
    if best_23:
        print(f"\nBoof 23: Threshold = {best_23['threshold']}")
        print(f"  - {best_23['trades']} trades, {best_23['win_rate']*100:.1f}% WR, ${best_23['total_pnl']:.2f} total")
        print(f"  - {best_23['core_pct']:.1f}% core signals, Core WR: {best_23['core_wr']*100:.1f}%, Exp WR: {best_23['exp_wr']*100:.1f}%")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for t in THRESHOLDS:
        if results_22[t]:
            pd.DataFrame(results_22[t]).to_csv(f'sweep_b22_t{t}_{timestamp}.csv', index=False)
        if results_23[t]:
            pd.DataFrame(results_23[t]).to_csv(f'sweep_b23_t{t}_{timestamp}.csv', index=False)
    
    print(f"\nSaved CSV files with timestamp {timestamp}")


if __name__ == '__main__':
    main()
