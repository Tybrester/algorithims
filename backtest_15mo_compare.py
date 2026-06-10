"""
backtest_15mo_compare.py
========================
15-month backtest: Boof 22 + 23 (no ETFs)
Compare: Options +40%/-10% vs Stock +0.1%/-0.05%
Symbols: AAPL, NVDA, META, GOOGL, AMD (BOOFINGTON list)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

creds = get_alpaca_credentials()
API_KEY = creds['api_key']
API_SECRET = creds['secret_key']

# =============================================================================
# CONFIG
# =============================================================================
# 15 months: Feb 2025 to May 2026
START_DATE = datetime(2025, 2, 1)
END_DATE   = datetime(2026, 5, 31)

# BOOFINGTON list - no ETFs
SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']

# Option scenario
OPTION_TP_PCT = 0.40    # +40% option premium
OPTION_SL_PCT = 0.10    # -10% option premium
OPTION_SIZE = 250       # $250 per trade
DELTA = 0.50
# Convert to underlying price movement
OPTION_TP_UNDERLYING = OPTION_TP_PCT / DELTA / 100  # 0.008 = 0.8%
OPTION_SL_UNDERLYING = OPTION_SL_PCT / DELTA / 100  # 0.002 = 0.2%

# Stock movement scenario
STOCK_TP_PCT = 0.001    # +0.1% underlying
STOCK_SL_PCT = 0.0005   # -0.05% underlying

# Slack threshold
SLACK_THRESHOLD = 0.8


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


def backtest_boof22_options(symbol, bars):
    """Boof 22 with option P&L: +40% / -10% on $250"""
    trades = []
    if len(bars) < 100:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    df['atr'] = compute_atr(df)
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    in_trade = False
    entry_price = entry_time = entry_slack = trade_direction = None
    
    for i in range(50, len(df) - 1):
        if in_trade:
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= OPTION_TP_UNDERLYING:
                pnl = OPTION_SIZE * OPTION_TP_PCT
                trades.append({'pnl': pnl, 'result': 'win', 'slack': entry_slack})
                in_trade = False
            elif change_pct <= -OPTION_SL_UNDERLYING:
                pnl = -OPTION_SIZE * OPTION_SL_PCT
                trades.append({'pnl': pnl, 'result': 'loss', 'slack': entry_slack})
                in_trade = False
            continue
        
        if i in peaks or i in troughs:
            current = df.iloc[i]
            is_peak = i in peaks
            atr_val = current['atr'] if current['atr'] > 0 else 0.001
            
            if is_peak:
                wick = current['high'] - max(current['open'], current['close'])
                slack = wick / atr_val
                if slack >= 0.6:
                    in_trade = True
                    trade_direction = 'short'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
            else:
                wick = min(current['open'], current['close']) - current['low']
                slack = wick / atr_val
                if slack >= 0.6:
                    in_trade = True
                    trade_direction = 'long'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
    
    return trades


def backtest_boof22_stock(symbol, bars):
    """Boof 22 with stock movement: +0.1% / -0.05%, report win rate only"""
    trades = []
    if len(bars) < 100:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    df['atr'] = compute_atr(df)
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    in_trade = False
    trade_direction = None
    
    for i in range(50, len(df) - 1):
        if in_trade:
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= STOCK_TP_PCT or change_pct <= -STOCK_SL_PCT:
                result = 'win' if change_pct >= STOCK_TP_PCT else 'loss'
                trades.append({'result': result})
                in_trade = False
            continue
        
        if i in peaks or i in troughs:
            current = df.iloc[i]
            is_peak = i in peaks
            atr_val = current['atr'] if current['atr'] > 0 else 0.001
            
            if is_peak:
                wick = current['high'] - max(current['open'], current['close'])
                slack = wick / atr_val
                if slack >= 0.6:
                    in_trade = True
                    trade_direction = 'short'
                    entry_price = current['close']
            else:
                wick = min(current['open'], current['close']) - current['low']
                slack = wick / atr_val
                if slack >= 0.6:
                    in_trade = True
                    trade_direction = 'long'
                    entry_price = current['close']
    
    return trades


def backtest_boof23_options(symbol, bars):
    """Boof 23 with option P&L: +40% / -10% on $250"""
    trades = []
    if len(bars) < 100:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    df['atr'] = compute_atr(df)
    
    df['swing_high'] = df['high'].rolling(5).max()
    df['swing_low'] = df['low'].rolling(5).min()
    df['trend'] = np.where(df['close'] > df['swing_high'].shift(5), 'up',
                  np.where(df['close'] < df['swing_low'].shift(5), 'down', None))
    df['trend'] = df['trend'].ffill().fillna('neutral')
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    in_trade = False
    entry_price = entry_time = entry_slack = trade_direction = None
    
    for i in range(50, len(df) - 1):
        if in_trade:
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= OPTION_TP_UNDERLYING:
                pnl = OPTION_SIZE * OPTION_TP_PCT
                trades.append({'pnl': pnl, 'result': 'win', 'slack': entry_slack})
                in_trade = False
            elif change_pct <= -OPTION_SL_UNDERLYING:
                pnl = -OPTION_SIZE * OPTION_SL_PCT
                trades.append({'pnl': pnl, 'result': 'loss', 'slack': entry_slack})
                in_trade = False
            continue
        
        if i in peaks or i in troughs:
            current = df.iloc[i]
            trend = df.iloc[i-1]['trend']
            is_peak = i in peaks
            atr_val = current['atr'] if current['atr'] > 0 else 0.001
            
            if is_peak:
                wick = current['high'] - max(current['open'], current['close'])
                slack = wick / atr_val
                if slack >= 0.6 and trend == 'up':
                    in_trade = True
                    trade_direction = 'short'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
            else:
                wick = min(current['open'], current['close']) - current['low']
                slack = wick / atr_val
                if slack >= 0.6 and trend == 'down':
                    in_trade = True
                    trade_direction = 'long'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
    
    return trades


def backtest_boof23_stock(symbol, bars):
    """Boof 23 with stock movement: +0.1% / -0.05%, report win rate only"""
    trades = []
    if len(bars) < 100:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    df['atr'] = compute_atr(df)
    
    df['swing_high'] = df['high'].rolling(5).max()
    df['swing_low'] = df['low'].rolling(5).min()
    df['trend'] = np.where(df['close'] > df['swing_high'].shift(5), 'up',
                  np.where(df['close'] < df['swing_low'].shift(5), 'down', None))
    df['trend'] = df['trend'].ffill().fillna('neutral')
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    in_trade = False
    trade_direction = None
    
    for i in range(50, len(df) - 1):
        if in_trade:
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= STOCK_TP_PCT or change_pct <= -STOCK_SL_PCT:
                result = 'win' if change_pct >= STOCK_TP_PCT else 'loss'
                trades.append({'result': result})
                in_trade = False
            continue
        
        if i in peaks or i in troughs:
            current = df.iloc[i]
            trend = df.iloc[i-1]['trend']
            is_peak = i in peaks
            atr_val = current['atr'] if current['atr'] > 0 else 0.001
            
            if is_peak:
                wick = current['high'] - max(current['open'], current['close'])
                slack = wick / atr_val
                if slack >= 0.6 and trend == 'up':
                    in_trade = True
                    trade_direction = 'short'
                    entry_price = current['close']
            else:
                wick = min(current['open'], current['close']) - current['low']
                slack = wick / atr_val
                if slack >= 0.6 and trend == 'down':
                    in_trade = True
                    trade_direction = 'long'
                    entry_price = current['close']
    
    return trades


def analyze_options(trades, name):
    if not trades:
        return {'trades': 0, 'win_rate': 0, 'total_pnl': 0, 'avg_pnl': 0}
    df = pd.DataFrame(trades)
    wins = len(df[df['result'] == 'win'])
    total = len(df)
    total_pnl = df['pnl'].sum()
    avg_pnl = df['pnl'].mean()
    return {
        'trades': total,
        'win_rate': wins / total if total > 0 else 0,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl
    }


def analyze_stock(trades, name):
    if not trades:
        return {'trades': 0, 'win_rate': 0}
    df = pd.DataFrame(trades)
    wins = len(df[df['result'] == 'win'])
    total = len(df)
    return {
        'trades': total,
        'win_rate': wins / total if total > 0 else 0
    }


def main():
    print("=" * 70)
    print("15-MONTH BACKTEST: Boof 22 + 23 (No ETFs)")
    print(f"Period: {START_DATE.date()} to {END_DATE.date()}")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print("=" * 70)
    
    all_bars = {}
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol}...")
        try:
            df = fetch_alpaca_bars(symbol, START_DATE, END_DATE, '1Min', API_KEY, API_SECRET)
            if df is not None and len(df) > 100:
                df = df.reset_index().rename(columns={'time': 'timestamp'})
                all_bars[symbol] = df.to_dict('records')
                print(f"  Loaded {len(all_bars[symbol])} bars")
            else:
                print(f"  Failed to load data")
        except Exception as e:
            print(f"  Error: {e}")
    
    # Run backtests
    results = {
        'boof22_options': [],
        'boof22_stock': [],
        'boof23_options': [],
        'boof23_stock': []
    }
    
    for symbol, bars in all_bars.items():
        results['boof22_options'].extend(backtest_boof22_options(symbol, bars))
        results['boof22_stock'].extend(backtest_boof22_stock(symbol, bars))
        results['boof23_options'].extend(backtest_boof23_options(symbol, bars))
        results['boof23_stock'].extend(backtest_boof23_stock(symbol, bars))
    
    # Analyze
    stats_22_opt = analyze_options(results['boof22_options'], 'Boof 22 Options')
    stats_22_stock = analyze_stock(results['boof22_stock'], 'Boof 22 Stock')
    stats_23_opt = analyze_options(results['boof23_options'], 'Boof 23 Options')
    stats_23_stock = analyze_stock(results['boof23_stock'], 'Boof 23 Stock')
    
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    print(f"\n{'='*70}")
    print("OPTIONS (+40% / -10%, $250/trade)")
    print(f"{'='*70}")
    print(f"{'Strategy':<15} {'Trades':<10} {'Win Rate':<12} {'Avg P&L':<12} {'Total P&L':<15}")
    print("-" * 70)
    print(f"{'Boof 22':<15} {stats_22_opt['trades']:<10} {stats_22_opt['win_rate']*100:>6.1f}%     ${stats_22_opt['avg_pnl']:>7.2f}      ${stats_22_opt['total_pnl']:>10.2f}")
    print(f"{'Boof 23':<15} {stats_23_opt['trades']:<10} {stats_23_opt['win_rate']*100:>6.1f}%     ${stats_23_opt['avg_pnl']:>7.2f}      ${stats_23_opt['total_pnl']:>10.2f}")
    
    print(f"\n{'='*70}")
    print("STOCK MOVEMENT (+0.1% / -0.05%) - WIN RATE ONLY")
    print(f"{'='*70}")
    print(f"{'Strategy':<15} {'Trades':<10} {'Win Rate':<12}")
    print("-" * 70)
    print(f"{'Boof 22':<15} {stats_22_stock['trades']:<10} {stats_22_stock['win_rate']*100:>6.1f}%")
    print(f"{'Boof 23':<15} {stats_23_stock['trades']:<10} {stats_23_stock['win_rate']*100:>6.1f}%")
    
    print(f"\n{'='*70}")
    print("COMBINED (Options only)")
    print(f"{'='*70}")
    combined_trades = stats_22_opt['trades'] + stats_23_opt['trades']
    combined_pnl = stats_22_opt['total_pnl'] + stats_23_opt['total_pnl']
    print(f"Total trades: {combined_trades}")
    print(f"Total P&L: ${combined_pnl:,.2f}")
    print(f"Avg per trade: ${combined_pnl/combined_trades:.2f}" if combined_trades > 0 else "")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for name, trades in results.items():
        if trades:
            pd.DataFrame(trades).to_csv(f'15mo_{name}_{timestamp}.csv', index=False)
    print(f"\nSaved CSV files with timestamp {timestamp}")


if __name__ == '__main__':
    main()
