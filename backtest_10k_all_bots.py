"""
backtest_10k_all_bots.py
========================
10,000+ trades with walk-forward optimization for Boof 21, 22, 23
Period: 2021-2026 (5+ years)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy import stats
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

creds = get_alpaca_credentials()
API_KEY = creds['api_key']
API_SECRET = creds['secret_key']

# =============================================================================
# CONFIG
# =============================================================================
START_DATE = datetime(2025, 2, 1)  # 15 months of data
END_DATE = datetime(2026, 5, 31)
SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'TSLA', 'QQQ', 'SPY']

# Option TP/SL
OPTION_TP_PCT = 0.40
OPTION_SL_PCT = 0.10
DELTA = 0.50
TP_PCT = OPTION_TP_PCT / DELTA / 100
SL_PCT = OPTION_SL_PCT / DELTA / 100

BASE_AMOUNT = 250
COMMISSION = 2.00
SLIPPAGE_PCT = 0.0005

# Walk-forward - shorter windows for 15mo period
WF_WINDOW_MONTHS = 3  # 3mo train, test forward
SLACK_OPTIONS = [0.6, 0.7, 0.8, 0.9, 1.0, 1.2]


def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def find_fractals(highs, lows, bars=3):
    peaks, troughs = [], []
    for i in range(bars, len(highs) - bars):
        if all(highs[i] > highs[i-j] for j in range(1, bars+1)) and \
           all(highs[i] > highs[i+j] for j in range(1, bars+1)):
            peaks.append(i)
        if all(lows[i] < lows[i-j] for j in range(1, bars+1)) and \
           all(lows[i] < lows[i+j] for j in range(1, bars+1)):
            troughs.append(i)
    return peaks, troughs


def run_trade(pnl, costs):
    """Record a trade with costs"""
    net_pnl = pnl - costs
    return {'pnl': net_pnl, 'gross': pnl, 'costs': costs, 'result': 'win' if net_pnl > 0 else 'loss'}


# =============================================================================
# BOOF 21 - Volume S/R Retest
# =============================================================================
def backtest_boof21(df, slack_thresh):
    trades = []
    if len(df) < 200:
        return trades
    
    df = df.copy().sort_values('timestamp').reset_index(drop=True)
    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['rvol'] = df['volume'] / df['volume'].rolling(20).mean()
    
    in_trade = False
    entry_price = entry_slack = 0
    position_size = 0
    
    for i in range(50, len(df)):
        if in_trade:
            change_pct = (df['close'].iloc[i] - entry_price) / entry_price
            if change_pct >= TP_PCT or change_pct <= -SL_PCT:
                gross = position_size * (OPTION_TP_PCT if change_pct > 0 else -OPTION_SL_PCT)
                costs = (2 * COMMISSION) + (position_size * SLIPPAGE_PCT * 2)
                trades.append(run_trade(gross, costs))
                in_trade = False
            continue
        
        window = df.iloc[i-20:i]
        highs = window['high'].nlargest(3).values
        lows = window['low'].nsmallest(3).values
        price = df['close'].iloc[i]
        trend_up = df['ema20'].iloc[i] > df['ema50'].iloc[i]
        
        support_dist = min(abs(price - level) for level in lows) if len(lows) > 0 else 999
        resistance_dist = min(abs(price - level) for level in highs) if len(highs) > 0 else 999
        
        level_strength = 10.0 - min(support_dist / price * 100, 10.0)
        rvol_ratio = df['rvol'].iloc[i] if not pd.isna(df['rvol'].iloc[i]) else 1.0
        slack = (level_strength / 10) * min(rvol_ratio, 2.0)
        
        signal = None
        if trend_up and support_dist < price * 0.002 and df['rvol'].iloc[i] > 1.2:
            signal = 'long'
        elif not trend_up and resistance_dist < price * 0.002 and df['rvol'].iloc[i] > 1.2:
            signal = 'short'
        
        if signal and slack >= slack_thresh:
            in_trade = True
            entry_price = price
            entry_slack = slack
            is_core = slack >= slack_thresh
            position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
    
    return trades


# =============================================================================
# BOOF 22 - Fractal + Volume
# =============================================================================
def backtest_boof22(df, slack_thresh):
    trades = []
    if len(df) < 100:
        return trades
    
    df = df.copy().sort_values('timestamp').reset_index(drop=True)
    df['atr'] = compute_atr(df)
    vol_sma = df['volume'].rolling(50).mean()
    df['hi_vol'] = df['volume'] > vol_sma * 1.3
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    in_trade = False
    entry_price = entry_slack = trade_direction = 0
    position_size = 0
    
    for i in range(50, len(df) - 1):
        if in_trade:
            change_pct = (df['close'].iloc[i] - entry_price) / entry_price
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= TP_PCT or change_pct <= -SL_PCT:
                gross = position_size * (OPTION_TP_PCT if change_pct > 0 else -OPTION_SL_PCT)
                costs = (2 * COMMISSION) + (position_size * SLIPPAGE_PCT * 2)
                trades.append(run_trade(gross, costs))
                in_trade = False
            continue
        
        if i in peaks or i in troughs:
            is_peak = i in peaks
            current = df.iloc[i]
            
            if is_peak:
                wick = current['high'] - max(current['open'], current['close'])
                slack = wick / current['atr'] if current['atr'] > 0 else 0
                vol_ok = df.iloc[max(0,i-5):i+1]['hi_vol'].any() if i >= 5 else True
                
                if slack >= slack_thresh and vol_ok:
                    in_trade = True
                    trade_direction = 'short'
                    entry_price = current['close']
                    entry_slack = slack
                    is_core = slack >= slack_thresh
                    position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
            else:
                wick = min(current['open'], current['close']) - current['low']
                slack = wick / current['atr'] if current['atr'] > 0 else 0
                vol_ok = df.iloc[max(0,i-5):i+1]['hi_vol'].any() if i >= 5 else True
                
                if slack >= slack_thresh and vol_ok:
                    in_trade = True
                    trade_direction = 'long'
                    entry_price = current['close']
                    entry_slack = slack
                    is_core = slack >= slack_thresh
                    position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
    
    return trades


# =============================================================================
# BOOF 23 - Fractal + Trend Filter
# =============================================================================
def backtest_boof23(df, slack_thresh):
    trades = []
    if len(df) < 100:
        return trades
    
    df = df.copy().sort_values('timestamp').reset_index(drop=True)
    df['atr'] = compute_atr(df)
    df['swing_high'] = df['high'].rolling(5).max()
    df['swing_low'] = df['low'].rolling(5).min()
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    in_trade = False
    entry_price = entry_slack = trade_direction = 0
    position_size = 0
    
    for i in range(50, len(df) - 1):
        # Trend
        if i > 10:
            recent_high = df['swing_high'].iloc[i-10:i].max()
            recent_low = df['swing_low'].iloc[i-10:i].min()
            price = df['close'].iloc[i]
            trend = 'up' if price > recent_high * 0.995 else 'down' if price < recent_low * 1.005 else 'neutral'
        else:
            trend = 'neutral'
        
        if in_trade:
            change_pct = (df['close'].iloc[i] - entry_price) / entry_price
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= TP_PCT or change_pct <= -SL_PCT:
                gross = position_size * (OPTION_TP_PCT if change_pct > 0 else -OPTION_SL_PCT)
                costs = (2 * COMMISSION) + (position_size * SLIPPAGE_PCT * 2)
                trades.append(run_trade(gross, costs))
                in_trade = False
            continue
        
        # Entry with trend filter
        if i in peaks and trend == 'up':
            current = df.iloc[i]
            wick = current['high'] - max(current['open'], current['close'])
            slack = wick / current['atr'] if current['atr'] > 0 else 0
            
            if slack >= slack_thresh:
                in_trade = True
                trade_direction = 'short'
                entry_price = current['close']
                entry_slack = slack
                is_core = slack >= slack_thresh
                position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
        
        elif i in troughs and trend == 'down':
            current = df.iloc[i]
            wick = min(current['open'], current['close']) - current['low']
            slack = wick / current['atr'] if current['atr'] > 0 else 0
            
            if slack >= slack_thresh:
                in_trade = True
                trade_direction = 'long'
                entry_price = current['close']
                entry_slack = slack
                is_core = slack >= slack_thresh
                position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
    
    return trades


def analyze(trades, name):
    if not trades or len(trades) < 10:
        return None
    
    pnls = np.array([t['pnl'] for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    
    total = len(pnls)
    win_rate = len(wins) / total
    
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    
    t_stat, p_value = stats.ttest_1samp(pnls, 0)
    
    return {
        'name': name,
        'trades': total,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'total_pnl': pnls.sum(),
        'avg_pnl': pnls.mean(),
        'sharpe': (pnls.mean() / pnls.std()) * np.sqrt(252) if pnls.std() > 0 else 0,
        't_stat': t_stat,
        'p_value': p_value,
        'significant': p_value < 0.05,
        'costs': sum(t['costs'] for t in trades)
    }


def walk_forward(df, backtest_func, name):
    """Walk-forward: optimize slack on rolling windows"""
    results = []
    
    # Create rolling windows
    df = df.sort_values('timestamp').reset_index(drop=True)
    start = df['timestamp'].min()
    end = df['timestamp'].max()
    
    current = start
    window_num = 0
    
    while current + timedelta(days=WF_WINDOW_MONTHS*30) < end:
        train_start = current
        train_end = current + timedelta(days=WF_WINDOW_MONTHS*30)
        test_end = min(train_end + timedelta(days=WF_WINDOW_MONTHS*15), end)
        
        train_df = df[(df['timestamp'] >= train_start) & (df['timestamp'] < train_end)]
        test_df = df[(df['timestamp'] >= train_end) & (df['timestamp'] < test_end)]
        
        if len(train_df) < 1000 or len(test_df) < 500:
            current = test_end
            continue
        
        window_num += 1
        print(f"\n  Window {window_num}: {train_start.date()} to {test_end.date()}")
        
        # Optimize slack on train
        best_slack = 0.8
        best_pnl = -999999
        
        for slack in SLACK_OPTIONS:
            train_trades = backtest_func(train_df, slack)
            if train_trades:
                pnl = sum(t['pnl'] for t in train_trades)
                if pnl > best_pnl:
                    best_pnl = pnl
                    best_slack = slack
        
        # Test on out-of-sample
        test_trades = backtest_func(test_df, best_slack)
        test_pnl = sum(t['pnl'] for t in test_trades) if test_trades else 0
        
        print(f"    Optimal slack: {best_slack} (train: ${best_pnl:.0f})")
        print(f"    Test: {len(test_trades)} trades, ${test_pnl:.0f}")
        
        results.append({
            'window': window_num,
            'best_slack': best_slack,
            'train_pnl': best_pnl,
            'test_trades': test_trades,
            'test_pnl': test_pnl
        })
        
        current = test_end
    
    return results


def main():
    print("=" * 70)
    print("10K TRADE WALK-FORWARD: Boof 21 / 22 / 23")
    print("=" * 70)
    print(f"Period: {START_DATE.date()} to {END_DATE.date()} (15 months)")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print(f"Window: {WF_WINDOW_MONTHS}mo train, optimize slack, test forward")
    print(f"Note: Alpaca limits to ~10k bars, using recent 15mo data")
    print("=" * 70)
    
    all_results = {'Boof 21': [], 'Boof 22': [], 'Boof 23': []}
    backtest_funcs = {'Boof 21': backtest_boof21, 'Boof 22': backtest_boof22, 'Boof 23': backtest_boof23}
    
    for symbol in SYMBOLS:
        print(f"\n{'='*60}")
        print(f"Processing {symbol}")
        print(f"{'='*60}")
        
        try:
            df_raw = fetch_alpaca_bars(symbol, START_DATE, END_DATE, '1Min', API_KEY, API_SECRET)
            if df_raw is None or len(df_raw) < 1000:
                print(f"  Insufficient data")
                continue
            
            df = df_raw.reset_index().rename(columns={'time': 'timestamp'})
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            print(f"  Loaded {len(df)} bars")
            
            for name, func in backtest_funcs.items():
                print(f"\n  {name}:")
                wf_results = walk_forward(df, func, name)
                all_results[name].extend(wf_results)
                
        except Exception as e:
            print(f"  Error: {e}")
    
    # Summary
    print("\n" + "=" * 70)
    print("WALK-FORWARD RESULTS")
    print("=" * 70)
    
    for name, results in all_results.items():
        if not results:
            continue
        
        all_test_trades = []
        for r in results:
            all_test_trades.extend(r['test_trades'])
        
        total_train_pnl = sum(r['train_pnl'] for r in results)
        total_test_pnl = sum(r['test_pnl'] for r in results)
        
        print(f"\n{'='*60}")
        print(f"{name}")
        print(f"{'='*60}")
        print(f"Windows: {len(results)}")
        print(f"Total Test Trades: {len(all_test_trades)}")
        print(f"Train P&L: ${total_train_pnl:,.2f}")
        print(f"Test P&L:  ${total_test_pnl:,.2f}")
        
        if all_test_trades:
            stats = analyze(all_test_trades, name)
            print(f"\n  Win Rate: {stats['win_rate']*100:.1f}%")
            print(f"  Profit Factor: {stats['profit_factor']:.2f}")
            print(f"  Sharpe: {stats['sharpe']:.2f}")
            print(f"  P-Value: {stats['p_value']:.4f}")
            print(f"  Significant: {'YES' if stats['significant'] else 'NO'}")
            print(f"  Total Costs: ${stats['costs']:,.2f}")
    
    # Combined
    print("\n" + "=" * 70)
    print("COMBINED ALL BOTS")
    print("=" * 70)
    
    all_combined = []
    for results in all_results.values():
        for r in results:
            all_combined.extend(r['test_trades'])
    
    if all_combined:
        total_trades = len(all_combined)
        total_pnl = sum(t['pnl'] for t in all_combined)
        
        print(f"Total Trades: {total_trades:,}")
        print(f"Total P&L: ${total_pnl:,.2f}")
        
        if total_trades >= 10000:
            print("\n*** 10,000+ TRADES ACHIEVED ***")
        else:
            print(f"\nNeed {10000-total_trades:,} more trades for 10K target")
    
    # Save
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    for name, results in all_results.items():
        all_trades = []
        for r in results:
            all_trades.extend(r['test_trades'])
        if all_trades:
            pd.DataFrame(all_trades).to_csv(f'10k_{name.replace(" ", "_")}_{ts}.csv', index=False)
    
    print(f"\nSaved with timestamp: {ts}")


if __name__ == '__main__':
    main()
