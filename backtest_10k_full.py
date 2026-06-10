"""
backtest_10k_full.py
====================
Maximize trade count: 8 symbols, 15 months, all 3 bots
No walk-forward (data limited), just full period analysis
"""

import pandas as pd
import numpy as np
from datetime import datetime
from scipy import stats
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

creds = get_alpaca_credentials()
API_KEY = creds['api_key']
API_SECRET = creds['secret_key']

# =============================================================================
# CONFIG
# =============================================================================
START_DATE = datetime(2025, 2, 1)
END_DATE = datetime(2026, 5, 31)
SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'TSLA', 'QQQ', 'SPY']

OPTION_TP_PCT = 0.40
OPTION_SL_PCT = 0.10
DELTA = 0.50
TP_PCT = OPTION_TP_PCT / DELTA / 100
SL_PCT = OPTION_SL_PCT / DELTA / 100

BASE_AMOUNT = 250
SLACK_THRESHOLD = 0.8
COMMISSION = 2.00
SLIPPAGE_PCT = 0.0005


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


def run_trade(gross_pnl, position_size):
    costs = (2 * COMMISSION) + (position_size * SLIPPAGE_PCT * 2)
    net_pnl = gross_pnl - costs
    return {
        'pnl': net_pnl,
        'gross': gross_pnl,
        'costs': costs,
        'result': 'win' if net_pnl > 0 else 'loss'
    }


# =============================================================================
# BOOF 21
# =============================================================================
def backtest_boof21(df):
    trades = []
    if len(df) < 200:
        return trades
    
    df = df.sort_values('timestamp').reset_index(drop=True)
    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['rvol'] = df['volume'] / df['volume'].rolling(20).mean()
    
    in_trade = False
    entry_price = position_size = 0
    
    for i in range(50, len(df)):
        if in_trade:
            change_pct = (df['close'].iloc[i] - entry_price) / entry_price
            if change_pct >= TP_PCT or change_pct <= -SL_PCT:
                gross = position_size * (OPTION_TP_PCT if change_pct > 0 else -OPTION_SL_PCT)
                trades.append(run_trade(gross, position_size))
                in_trade = False
            continue
        
        window = df.iloc[i-20:i]
        lows = window['low'].nsmallest(3).values
        highs = window['high'].nlargest(3).values
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
        
        if signal and slack >= 0.6:  # 0.6 min slack
            in_trade = True
            entry_price = price
            is_core = slack >= SLACK_THRESHOLD
            position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
    
    return trades


# =============================================================================
# BOOF 22
# =============================================================================
def backtest_boof22(df):
    trades = []
    if len(df) < 100:
        return trades
    
    df = df.sort_values('timestamp').reset_index(drop=True)
    df['atr'] = compute_atr(df)
    vol_sma = df['volume'].rolling(50).mean()
    df['hi_vol'] = df['volume'] > vol_sma * 1.3
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    in_trade = False
    entry_price = trade_direction = 0
    position_size = 0
    
    for i in range(50, len(df) - 1):
        if in_trade:
            change_pct = (df['close'].iloc[i] - entry_price) / entry_price
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= TP_PCT or change_pct <= -SL_PCT:
                gross = position_size * (OPTION_TP_PCT if change_pct > 0 else -OPTION_SL_PCT)
                trades.append(run_trade(gross, position_size))
                in_trade = False
            continue
        
        if i in peaks or i in troughs:
            is_peak = i in peaks
            current = df.iloc[i]
            
            if is_peak:
                wick = current['high'] - max(current['open'], current['close'])
                slack = wick / current['atr'] if current['atr'] > 0 else 0
                vol_ok = df.iloc[max(0,i-5):i+1]['hi_vol'].any() if i >= 5 else True
                
                if slack >= 0.6 and vol_ok:
                    in_trade = True
                    trade_direction = 'short'
                    entry_price = current['close']
                    is_core = slack >= SLACK_THRESHOLD
                    position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
            else:
                wick = min(current['open'], current['close']) - current['low']
                slack = wick / current['atr'] if current['atr'] > 0 else 0
                vol_ok = df.iloc[max(0,i-5):i+1]['hi_vol'].any() if i >= 5 else True
                
                if slack >= 0.6 and vol_ok:
                    in_trade = True
                    trade_direction = 'long'
                    entry_price = current['close']
                    is_core = slack >= SLACK_THRESHOLD
                    position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
    
    return trades


# =============================================================================
# BOOF 23
# =============================================================================
def backtest_boof23(df):
    trades = []
    if len(df) < 100:
        return trades
    
    df = df.sort_values('timestamp').reset_index(drop=True)
    df['atr'] = compute_atr(df)
    df['swing_high'] = df['high'].rolling(5).max()
    df['swing_low'] = df['low'].rolling(5).min()
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    in_trade = False
    entry_price = trade_direction = 0
    position_size = 0
    
    for i in range(50, len(df) - 1):
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
                trades.append(run_trade(gross, position_size))
                in_trade = False
            continue
        
        if i in peaks and trend == 'up':
            current = df.iloc[i]
            wick = current['high'] - max(current['open'], current['close'])
            slack = wick / current['atr'] if current['atr'] > 0 else 0
            
            if slack >= 0.6:
                in_trade = True
                trade_direction = 'short'
                entry_price = current['close']
                is_core = slack >= SLACK_THRESHOLD
                position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
        
        elif i in troughs and trend == 'down':
            current = df.iloc[i]
            wick = min(current['open'], current['close']) - current['low']
            slack = wick / current['atr'] if current['atr'] > 0 else 0
            
            if slack >= 0.6:
                in_trade = True
                trade_direction = 'long'
                entry_price = current['close']
                is_core = slack >= SLACK_THRESHOLD
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
        'total_costs': sum(t['costs'] for t in trades),
        'avg_winner': wins.mean() if len(wins) > 0 else 0,
        'avg_loser': losses.mean() if len(losses) > 0 else 0
    }


def main():
    print("=" * 70)
    print("10K TRADE TARGET: Boof 21 / 22 / 23 (Full Period)")
    print("=" * 70)
    print(f"Period: {START_DATE.date()} to {END_DATE.date()} (15 months)")
    print(f"Symbols: {len(SYMBOLS)} stocks")
    print(f"Slack Threshold: {SLACK_THRESHOLD} (core=2x, expanded=1x)")
    print("=" * 70)
    
    all_results = {'Boof 21': [], 'Boof 22': [], 'Boof 23': []}
    backtest_funcs = {
        'Boof 21': backtest_boof21,
        'Boof 22': backtest_boof22,
        'Boof 23': backtest_boof23
    }
    
    for symbol in SYMBOLS:
        print(f"\n{symbol}...", end=" ")
        
        try:
            df_raw = fetch_alpaca_bars(symbol, START_DATE, END_DATE, '1Min', API_KEY, API_SECRET)
            if df_raw is None or len(df_raw) < 100:
                print("no data")
                continue
            
            df = df_raw.reset_index().rename(columns={'time': 'timestamp'})
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            for name, func in backtest_funcs.items():
                trades = func(df)
                all_results[name].extend(trades)
            
            print(f"OK (B21={len(backtest_boof21(df))}, B22={len(backtest_boof22(df))}, B23={len(backtest_boof23(df))})")
            
        except Exception as e:
            print(f"error: {e}")
    
    # Summary
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    grand_total = 0
    for name, trades in all_results.items():
        if not trades:
            continue
        
        stats = analyze(trades, name)
        grand_total += stats['trades']
        
        print(f"\n{name}:")
        print(f"  Trades:      {stats['trades']:,}")
        print(f"  Win Rate:    {stats['win_rate']*100:.1f}%")
        print(f"  Profit Fact: {stats['profit_factor']:.2f}")
        print(f"  Sharpe:      {stats['sharpe']:.2f}")
        print(f"  P-Value:     {stats['p_value']:.4f}")
        print(f"  Significant: {'YES' if stats['significant'] else 'NO'}")
        print(f"  P&L:         ${stats['total_pnl']:,.2f}")
        print(f"  Avg/Trade:   ${stats['avg_pnl']:.2f}")
        print(f"  Costs:       ${stats['total_costs']:,.2f}")
        print(f"  Avg Winner:  ${stats['avg_winner']:.2f}")
        print(f"  Avg Loser:   ${stats['avg_loser']:.2f}")
    
    # Combined
    all_trades = all_results['Boof 21'] + all_results['Boof 22'] + all_results['Boof 23']
    if all_trades:
        print(f"\n{'='*70}")
        print("COMBINED ALL BOTS")
        print(f"{'='*70}")
        
        combined = analyze(all_trades, "Combined")
        print(f"Total Trades:  {combined['trades']:,}")
        print(f"Total P&L:     ${combined['total_pnl']:,.2f}")
        print(f"Win Rate:      {combined['win_rate']*100:.1f}%")
        print(f"Avg/Trade:     ${combined['avg_pnl']:.2f}")
        print(f"Total Costs:   ${combined['total_costs']:,.2f}")
        
        if combined['trades'] >= 10000:
            print("\n*** 10,000+ TRADES ACHIEVED ***")
        else:
            remaining = 10000 - combined['trades']
            print(f"\nNeed {remaining:,} more trades for 10K target")
            print(f"Current: {combined['trades']:,} / 10,000 ({combined['trades']/100:.1f}%)")
    
    # Save
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    for name, trades in all_results.items():
        if trades:
            pd.DataFrame(trades).to_csv(f'10k_{name.replace(" ", "_")}_{ts}.csv', index=False)
    
    if all_trades:
        pd.DataFrame(all_trades).to_csv(f'10k_combined_{ts}.csv', index=False)
    
    print(f"\nSaved: {ts}")


if __name__ == '__main__':
    main()
