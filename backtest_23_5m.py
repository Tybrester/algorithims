"""
backtest_23_5m.py
=================
Boof 23 on 5-minute chart (last 15 months)
Compare to 1m results
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


def find_fractals(highs, lows, bars=2):
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
    return {'pnl': net_pnl, 'gross': gross_pnl, 'costs': costs, 'result': 'win' if net_pnl > 0 else 'loss'}


def backtest_boof23_5m(df):
    """Boof 23 on 5-minute bars"""
    trades = []
    if len(df) < 100:
        return trades
    
    df = df.sort_values('timestamp').reset_index(drop=True)
    df['atr'] = compute_atr(df)
    df['swing_high'] = df['high'].rolling(5).max()
    df['swing_low'] = df['low'].rolling(5).min()
    
    peaks, troughs = find_fractals(df['high'].values, df['low'].values, bars=2)
    
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
    print("BOOF 23: 5-MINUTE TIMEFRAME TEST")
    print("=" * 70)
    print(f"Period: {START_DATE.date()} to {END_DATE.date()}")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print(f"Slack: {SLACK_THRESHOLD}, TP/SL: +{OPTION_TP_PCT*100:.0f}%/-{OPTION_SL_PCT*100:.0f}%")
    print("=" * 70)
    
    all_trades = []
    
    for symbol in SYMBOLS:
        print(f"\n{symbol}...", end=" ")
        
        try:
            df_raw = fetch_alpaca_bars(symbol, START_DATE, END_DATE, '5Min', API_KEY, API_SECRET)
            if df_raw is None or len(df_raw) < 50:
                print("no data")
                continue
            
            df = df_raw.reset_index().rename(columns={'time': 'timestamp'})
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            trades = backtest_boof23_5m(df)
            all_trades.extend(trades)
            
            print(f"OK ({len(trades)} trades)")
            
        except Exception as e:
            print(f"error: {e}")
    
    # Summary
    print("\n" + "=" * 70)
    print("5-MINUTE RESULTS")
    print("=" * 70)
    
    if all_trades:
        stats = analyze(all_trades, "Boof 23 5m")
        
        print(f"\nTotal Trades:  {stats['trades']:,}")
        print(f"Win Rate:      {stats['win_rate']*100:.1f}%")
        print(f"Profit Factor: {stats['profit_factor']:.2f}")
        print(f"Sharpe:        {stats['sharpe']:.2f}")
        print(f"P-Value:       {stats['p_value']:.4f}")
        print(f"Significant:   {'YES' if stats['significant'] else 'NO'}")
        print(f"Total P&L:     ${stats['total_pnl']:,.2f}")
        print(f"Avg/Trade:     ${stats['avg_pnl']:.2f}")
        print(f"Total Costs:   ${stats['total_costs']:,.2f}")
        print(f"Avg Winner:    ${stats['avg_winner']:.2f}")
        print(f"Avg Loser:     ${stats['avg_loser']:.2f}")
        
        print("\n" + "=" * 70)
        print("COMPARISON: 1m vs 5m")
        print("=" * 70)
        print("1m (from prior test): 570 trades, 29.5% WR, $16.90/trade")
        print(f"5m (this test):       {stats['trades']} trades, {stats['win_rate']*100:.1f}% WR, ${stats['avg_pnl']:.2f}/trade")
        
        trade_ratio = stats['trades'] / 570
        print(f"\nTrade frequency: {trade_ratio:.1%} of 1m timeframe")
        
        if stats['win_rate'] > 0.28 and stats['profit_factor'] > 1.3:
            print("\nVERDICT: 5m timeframe WORKS")
        else:
            print("\nVERDICT: 5m timeframe WORSE than 1m")
    else:
        print("No trades generated")
    
    # Save
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    if all_trades:
        pd.DataFrame(all_trades).to_csv(f'boof23_5m_{ts}.csv', index=False)
        print(f"\nSaved: boof23_5m_{ts}.csv")


if __name__ == '__main__':
    main()
