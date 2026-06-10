"""
backtest_fixed_stress.py
========================
Fixed backtest using proven signal logic from working backtest
Adds Monte Carlo, stress tests, 15-month period
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

creds = get_alpaca_credentials()
API_KEY = creds['api_key']
API_SECRET = creds['secret_key']

# =============================================================================
# CONFIG - MATCHES WORKING BACKTEST
# =============================================================================
START_DATE = datetime(2025, 2, 1)  # 15 months
END_DATE   = datetime(2026, 5, 31)

SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']

# TP/SL - option premium based (what actually works)
OPTION_TP_PCT = 0.40   # +40% option
OPTION_SL_PCT = 0.10   # -10% option  
DELTA = 0.50
TP_PCT = OPTION_TP_PCT / DELTA / 100  # 0.8% underlying
SL_PCT = OPTION_SL_PCT / DELTA / 100  # 0.2% underlying

BASE_AMOUNT = 250
SLACK_THRESHOLD = 0.8


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


# =============================================================================
# BOOF 21 - Volume S/R Retest (PROVEN LOGIC)
# =============================================================================
def backtest_boof21(symbol, bars):
    """Boof 21: EMA trend + S/R retest with volume"""
    trades = []
    if len(bars) < 200:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    df['hl2'] = (df['high'] + df['low']) / 2
    df['rvol'] = df['volume'] / df['volume'].rolling(20).mean()
    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    
    in_trade = False
    entry_price = entry_time = entry_slack = 0
    position_size = 0
    
    for i in range(50, len(df)):
        if in_trade:
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            
            if change_pct >= TP_PCT:
                pnl = position_size * OPTION_TP_PCT
                trades.append({'pnl': pnl, 'slack': entry_slack, 
                              'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                              'result': 'win', 'symbol': symbol})
                in_trade = False
            elif change_pct <= -SL_PCT:
                pnl = -position_size * OPTION_SL_PCT
                trades.append({'pnl': pnl, 'slack': entry_slack,
                              'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded', 
                              'result': 'loss', 'symbol': symbol})
                in_trade = False
            continue
        
        # Entry logic
        window = df.iloc[i-20:i]
        current = df.iloc[i]
        
        highs = window['high'].nlargest(3).values
        lows = window['low'].nsmallest(3).values
        
        price = current['close']
        trend_up = current['ema20'] > current['ema50']
        
        support_dist = min(abs(price - level) for level in lows) if len(lows) > 0 else 999
        resistance_dist = min(abs(price - level) for level in highs) if len(highs) > 0 else 999
        
        level_strength = 10.0 - min(support_dist / price * 100, 10.0)
        rvol_ratio = current['rvol'] if not pd.isna(current['rvol']) else 1.0
        slack = (level_strength / 10) * min(rvol_ratio, 2.0)
        
        signal = None
        if trend_up and support_dist < price * 0.002 and current['rvol'] > 1.2:
            signal = 'long'
        elif not trend_up and resistance_dist < price * 0.002 and current['rvol'] > 1.2:
            signal = 'short'
        
        if signal:
            in_trade = True
            entry_price = price
            entry_time = current['timestamp']
            entry_slack = slack
            is_core = slack >= SLACK_THRESHOLD
            position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
    
    return trades


# =============================================================================
# BOOF 22 - Fractal + Volume Cluster (PROVEN LOGIC)  
# =============================================================================
def backtest_boof22(symbol, bars):
    """Boof 22: Fractal reversal at volume clusters"""
    trades = []
    if len(bars) < 100:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    atr = compute_atr(df)
    df['atr'] = atr
    
    vol_sma = df['volume'].rolling(50).mean()
    df['hi_vol'] = df['volume'] > vol_sma * 1.3
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    in_trade = False
    entry_price = entry_time = entry_slack = trade_direction = 0
    position_size = 0
    
    for i in range(50, len(df) - 1):
        if in_trade:
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= TP_PCT:
                pnl = position_size * OPTION_TP_PCT
                trades.append({'pnl': pnl, 'slack': entry_slack,
                              'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                              'result': 'win', 'symbol': symbol})
                in_trade = False
            elif change_pct <= -SL_PCT:
                pnl = -position_size * OPTION_SL_PCT
                trades.append({'pnl': pnl, 'slack': entry_slack,
                              'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                              'result': 'loss', 'symbol': symbol})
                in_trade = False
            continue
        
        # Entry at fractals
        if i in peaks or i in troughs:
            current = df.iloc[i]
            is_peak = i in peaks
            
            if is_peak:
                wick = current['high'] - max(current['open'], current['close'])
                slack = wick / current['atr'] if current['atr'] > 0 else 0
                
                # Check volume cluster
                vol_ok = df.iloc[i-5:i+1]['hi_vol'].any() or df.iloc[i-3:i+1]['volume'].mean() > df['volume'].rolling(50).mean().iloc[i] * 1.2
                
                if slack >= 0.6 and vol_ok:
                    in_trade = True
                    trade_direction = 'short'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
                    is_core = slack >= SLACK_THRESHOLD
                    position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
            else:
                wick = min(current['open'], current['close']) - current['low']
                slack = wick / current['atr'] if current['atr'] > 0 else 0
                
                vol_ok = df.iloc[i-5:i+1]['hi_vol'].any() or df.iloc[i-3:i+1]['volume'].mean() > df['volume'].rolling(50).mean().iloc[i] * 1.2
                
                if slack >= 0.6 and vol_ok:
                    in_trade = True
                    trade_direction = 'long'
                    entry_price = current['close']
                    entry_time = current['timestamp']
                    entry_slack = slack
                    is_core = slack >= SLACK_THRESHOLD
                    position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
    
    return trades


# =============================================================================
# BOOF 23 - ZigZag Regime Filter (PROVEN LOGIC)
# =============================================================================
def backtest_boof23(symbol, bars):
    """Boof 23: Fractal with ZigZag trend filter"""
    trades = []
    if len(bars) < 100:
        return trades
    
    df = pd.DataFrame(bars)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    atr = compute_atr(df)
    df['atr'] = atr
    
    df['swing_high'] = df['high'].rolling(5).max()
    df['swing_low'] = df['low'].rolling(5).min()
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, 3)
    
    in_trade = False
    entry_price = entry_time = entry_slack = trade_direction = 0
    position_size = 0
    
    for i in range(50, len(df) - 1):
        # Determine trend
        if i > 10:
            recent_high = df['swing_high'].iloc[i-10:i].max()
            recent_low = df['swing_low'].iloc[i-10:i].min()
            price = df['close'].iloc[i]
            
            if price > recent_high * 0.995:
                trend = 'up'
            elif price < recent_low * 1.005:
                trend = 'down'
            else:
                trend = 'neutral'
        else:
            trend = 'neutral'
        
        if in_trade:
            current = df.iloc[i]
            change_pct = (current['close'] - entry_price) / entry_price
            if trade_direction == 'short':
                change_pct = -change_pct
            
            if change_pct >= TP_PCT:
                pnl = position_size * OPTION_TP_PCT
                trades.append({'pnl': pnl, 'slack': entry_slack,
                              'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                              'result': 'win', 'symbol': symbol, 'trend': trend})
                in_trade = False
            elif change_pct <= -SL_PCT:
                pnl = -position_size * OPTION_SL_PCT
                trades.append({'pnl': pnl, 'slack': entry_slack,
                              'tier': 'core' if entry_slack >= SLACK_THRESHOLD else 'expanded',
                              'result': 'loss', 'symbol': symbol, 'trend': trend})
                in_trade = False
            continue
        
        # Entry with regime filter
        if i in peaks and trend == 'up':
            current = df.iloc[i]
            wick = current['high'] - max(current['open'], current['close'])
            slack = wick / current['atr'] if current['atr'] > 0 else 0
            
            if slack >= 0.6:
                in_trade = True
                trade_direction = 'short'
                entry_price = current['close']
                entry_time = current['timestamp']
                entry_slack = slack
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
                entry_time = current['timestamp']
                entry_slack = slack
                is_core = slack >= SLACK_THRESHOLD
                position_size = BASE_AMOUNT * (2.0 if is_core else 1.0)
    
    return trades


# =============================================================================
# ANALYSIS & MONTE CARLO
# =============================================================================
def analyze_trades(trades, name):
    if not trades:
        return {'trades': 0}
    
    df = pd.DataFrame(trades)
    wins = df[df['result'] == 'win']
    losses = df[df['result'] == 'loss']
    
    total = len(df)
    win_rate = len(wins) / total if total > 0 else 0
    
    gross_profit = wins['pnl'].sum() if len(wins) > 0 else 0
    gross_loss = abs(losses['pnl'].sum()) if len(losses) > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    total_pnl = df['pnl'].sum()
    avg_pnl = df['pnl'].mean()
    
    # Tier analysis
    core_df = df[df['tier'] == 'core']
    exp_df = df[df['tier'] == 'expanded']
    
    return {
        'name': name,
        'trades': total,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl,
        'core_trades': len(core_df),
        'core_win_rate': (core_df['result'] == 'win').mean() if len(core_df) > 0 else 0,
        'core_pnl': core_df['pnl'].sum() if len(core_df) > 0 else 0,
        'exp_trades': len(exp_df),
        'exp_win_rate': (exp_df['result'] == 'win').mean() if len(exp_df) > 0 else 0,
        'exp_pnl': exp_df['pnl'].sum() if len(exp_df) > 0 else 0,
    }


def monte_carlo(trades, n=10000):
    """Shuffle trade order 10,000x"""
    if not trades or len(trades) < 10:
        return {}
    
    pnls = [t['pnl'] for t in trades]
    final_pnls = []
    
    for _ in range(n):
        shuffled = random.sample(pnls, len(pnls))
        cumulative = np.cumsum(shuffled)
        final_pnls.append(cumulative[-1])
    
    final_pnls = np.array(final_pnls)
    
    return {
        'prob_profit': (final_pnls > 0).mean(),
        'mean_pnl': final_pnls.mean(),
        'median_pnl': np.median(final_pnls),
        'p5': np.percentile(final_pnls, 5),
        'p95': np.percentile(final_pnls, 95),
        'worst': final_pnls.min(),
        'best': final_pnls.max()
    }


def stress_test(trades, name):
    """Run stress scenarios"""
    if not trades:
        return
    
    pnls = np.array([t['pnl'] for t in trades])
    baseline = pnls.sum()
    
    print(f"\n{'='*50}")
    print(f"STRESS TEST: {name}")
    print(f"{'='*50}")
    print(f"Baseline P&L:        ${baseline:,.2f}")
    print(f"Win Rate:            {(pnls > 0).mean()*100:.1f}%")
    
    # +20% slippage
    adj = pnls - 5  # $5 slippage per trade
    print(f"\n+$5 slippage/trade: ${adj.sum():,.2f}")
    
    # -5% win rate
    n_wins = (pnls > 0).sum()
    n_losses = (pnls < 0).sum()
    wins_to_flip = int(n_wins * 0.05)
    if wins_to_flip > 0 and n_wins > 0 and n_losses > 0:
        avg_win = pnls[pnls > 0].mean()
        avg_loss = pnls[pnls < 0].mean()
        adjusted = baseline - wins_to_flip * (avg_win - avg_loss)
        print(f"-5% win rate:       ${adjusted:,.2f}")
    
    # Worst 10-trade streak
    sorted_pnls = np.sort(pnls)
    worst_10 = sorted_pnls[:10].sum()
    print(f"Worst 10 trades:     ${worst_10:,.2f}")


def main():
    print("=" * 70)
    print("FIXED BACKTEST: Boof 21 / 22 / 23")
    print("Period: Feb 2025 - May 2026 (15 months)")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print(f"TP/SL: +{OPTION_TP_PCT*100:.0f}% / -{OPTION_SL_PCT*100:.0f}% (option premium)")
    print("=" * 70)
    
    all_trades = {'Boof 21': [], 'Boof 22': [], 'Boof 23': []}
    
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol}...")
        try:
            df = fetch_alpaca_bars(symbol, START_DATE, END_DATE, '1Min', API_KEY, API_SECRET)
            if df is not None and len(df) > 100:
                df = df.reset_index().rename(columns={'time': 'timestamp'})
                bars = df.to_dict('records')
                
                all_trades['Boof 21'].extend(backtest_boof21(symbol, bars))
                all_trades['Boof 22'].extend(backtest_boof22(symbol, bars))
                all_trades['Boof 23'].extend(backtest_boof23(symbol, bars))
                
                print(f"  Loaded: B21={len([t for t in all_trades['Boof 21'] if t['symbol']==symbol])}, "
                      f"B22={len([t for t in all_trades['Boof 22'] if t['symbol']==symbol])}, "
                      f"B23={len([t for t in all_trades['Boof 23'] if t['symbol']==symbol])}")
            else:
                print(f"  No data")
        except Exception as e:
            print(f"  Error: {e}")
    
    # Results
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    for name, trades in all_trades.items():
        if not trades:
            continue
        
        stats = analyze_trades(trades, name)
        mc = monte_carlo(trades)
        
        print(f"\n{'='*70}")
        print(f"{stats['name']}")
        print(f"{'='*70}")
        print(f"Total Trades:        {stats['trades']:,}")
        print(f"Win Rate:            {stats['win_rate']*100:.1f}%")
        print(f"Profit Factor:       {stats['profit_factor']:.2f}")
        print(f"Total P&L:           ${stats['total_pnl']:,.2f}")
        print(f"Avg per Trade:       ${stats['avg_pnl']:.2f}")
        print(f"\nCore (slack>=0.8):   {stats['core_trades']} trades, {stats['core_win_rate']*100:.1f}% WR, ${stats['core_pnl']:,.2f}")
        print(f"Expanded:            {stats['exp_trades']} trades, {stats['exp_win_rate']*100:.1f}% WR, ${stats['exp_pnl']:,.2f}")
        
        if mc:
            print(f"\nMonte Carlo (10,000 runs):")
            print(f"  Probability Profit:  {mc['prob_profit']*100:.1f}%")
            print(f"  Mean P&L:           ${mc['mean_pnl']:,.2f}")
            print(f"  5th Percentile:     ${mc['p5']:,.2f}")
            print(f"  95th Percentile:    ${mc['p95']:,.2f}")
        
        stress_test(trades, name)
    
    # Combined
    all_combined = all_trades['Boof 21'] + all_trades['Boof 22'] + all_trades['Boof 23']
    if all_combined:
        print(f"\n{'='*70}")
        print("COMBINED ALL BOTS")
        print(f"{'='*70}")
        stats_all = analyze_trades(all_combined, "COMBINED")
        print(f"Total Trades:  {stats_all['trades']:,}")
        print(f"Win Rate:      {stats_all['win_rate']*100:.1f}%")
        print(f"Total P&L:     ${stats_all['total_pnl']:,.2f}")
        print(f"Avg per Trade: ${stats_all['avg_pnl']:.2f}")
    
    # Save
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    for name, trades in all_trades.items():
        if trades:
            pd.DataFrame(trades).to_csv(f'fixed_{name.replace(" ", "_")}_{ts}.csv', index=False)
    print(f"\nSaved CSVs: {ts}")


if __name__ == '__main__':
    main()
