import pandas as pd
import numpy as np
from datetime import datetime
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

# =========================
# CONFIG
# =========================
SYMBOLS = ["SPY", "QQQ"]
TIMEFRAME = "1Min"

START_DATE = datetime(2026, 4, 1)
END_DATE   = datetime(2026, 4, 30)

# S/R level detection
PIVOT_LEN        = 3       # bars each side for minor pivots
CLUSTER_DIST     = 0.002   # 0.2% — levels within this range merge into one
LEVEL_LOOKBACK   = 120     # bars back to scan for levels
MIN_TOUCHES      = 2       # minimum touches to be a valid level
BREAKOUT_BUFFER  = 0.001   # price must close 0.1% beyond level to confirm breakout

# Trade execution
VOL_MULT         = 1.2     # volume must be > 1.2x avg to confirm breakout
TIME_FILTER      = True
TIME_WINDOWS     = [(5, 120), (300, 450)]   # 9:35-11:00, 2:00-3:30

# Exit rules
STOP_DIST        = 0.004   # 0.4% fixed stop below level
TAKE_PROFIT      = 0.012   # 1.2% take profit
TIME_STOP_BARS   = 20      # 20 bars max hold

# 0DTE options model
OPTION_COST_PCT  = 0.004   # ATM option ≈ 0.4% of underlying
DELTA            = 0.50
THETA_PER_MIN    = OPTION_COST_PCT * (0.50 / 390)   # ~50% of value decays over full day

# =========================
# DATA
# =========================
def fetch_data(symbol):
    credentials = get_alpaca_credentials()
    return fetch_alpaca_bars(symbol, START_DATE, END_DATE, TIMEFRAME,
                             api_key=credentials['api_key'],
                             secret_key=credentials['secret_key'])

# =========================
# TIME FILTER
# =========================
def is_time_allowed(ts):
    m = ts.hour * 60 + ts.minute - 570   # minutes from 9:30
    return any(s <= m <= e for s, e in TIME_WINDOWS)

# =========================
# VWAP
# =========================
def calc_vwap(df):
    return (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()

# =========================
# S/R LEVEL BUILDER
# Finds all pivot highs/lows in window, clusters nearby ones,
# scores each by number of touches + volume significance
# =========================
def build_sr_levels(df, up_to_idx, lookback=LEVEL_LOOKBACK):
    start = max(0, up_to_idx - lookback)
    window = df.iloc[start:up_to_idx]

    raw_levels = []

    # Collect all pivot highs and lows
    n = PIVOT_LEN
    for i in range(n, len(window) - n):
        hi = window['high'].iloc[i]
        lo = window['low'].iloc[i]

        if hi == window['high'].iloc[i-n:i+n+1].max():
            raw_levels.append({'price': hi, 'type': 'resistance', 'vol': window['volume'].iloc[i]})

        if lo == window['low'].iloc[i-n:i+n+1].min():
            raw_levels.append({'price': lo, 'type': 'support', 'vol': window['volume'].iloc[i]})

    if not raw_levels:
        return []

    # Cluster nearby levels
    raw_levels.sort(key=lambda x: x['price'])
    clusters = []
    for lv in raw_levels:
        merged = False
        for cl in clusters:
            if abs(lv['price'] - cl['price']) / cl['price'] < CLUSTER_DIST:
                # Merge: weighted average price, accumulate touches and volume
                cl['touches'] += 1
                cl['vol'] += lv['vol']
                cl['price'] = (cl['price'] * (cl['touches'] - 1) + lv['price']) / cl['touches']
                merged = True
                break
        if not merged:
            clusters.append({'price': lv['price'], 'touches': 1, 'vol': lv['vol']})

    # Filter to levels with enough touches
    valid = [c for c in clusters if c['touches'] >= MIN_TOUCHES]

    # Score each level: score = touches * log(vol+1)
    for c in valid:
        c['score'] = c['touches'] * np.log1p(c['vol'])

    return valid

# =========================
# 0DTE OPTIONS PnL
# =========================
def option_pnl(entry, exit_price, direction, hold_minutes):
    underlying_pnl = (exit_price - entry) / entry if direction == 'LONG' else (entry - exit_price) / entry
    gain = underlying_pnl * DELTA
    theta = THETA_PER_MIN * hold_minutes
    return (gain - theta) / OPTION_COST_PCT   # as % of option cost

# =========================
# BACKTEST ENGINE
# =========================
def backtest(df):
    df = df.copy()
    df['vwap']    = calc_vwap(df)
    df['vol_avg'] = df['volume'].rolling(20).mean()

    trades = []
    in_trade = False

    for i in range(LEVEL_LOOKBACK + PIVOT_LEN, len(df) - TIME_STOP_BARS - 1):

        if in_trade:
            continue

        if TIME_FILTER and not is_time_allowed(df.index[i]):
            continue

        row          = df.iloc[i]
        current_vwap = row['vwap']
        vol_ok       = row['volume'] > row['vol_avg'] * VOL_MULT

        if not vol_ok:
            continue

        # Build S/R levels from the lookback window
        levels = build_sr_levels(df, i)
        if not levels:
            continue

        entry_signal = None
        best_score   = 0

        for lv in levels:
            price = lv['price']
            score = lv['score']

            # LONG: close above resistance by buffer, and above VWAP
            if (row['close'] > price * (1 + BREAKOUT_BUFFER) and
                    row['close'] > current_vwap):
                if score > best_score:
                    best_score   = score
                    entry_signal = ('LONG', price, score)

            # SHORT: close below support by buffer, and below VWAP
            if (row['close'] < price * (1 - BREAKOUT_BUFFER) and
                    row['close'] < current_vwap):
                if score > best_score:
                    best_score   = score
                    entry_signal = ('SHORT', price, score)

        if entry_signal is None:
            continue

        direction, broken_level, signal_score = entry_signal
        entry_price = df['close'].iloc[i + 1]

        if direction == 'LONG':
            stop_price = broken_level * (1 - STOP_DIST)
        else:
            stop_price = broken_level * (1 + STOP_DIST)

        in_trade = True

        for j in range(i + 2, min(i + TIME_STOP_BARS + 2, len(df))):
            current      = df['close'].iloc[j]
            hold_minutes = j - (i + 1)
            underly_pnl  = (current - entry_price) / entry_price if direction == 'LONG' else (entry_price - current) / entry_price

            hit_stop = (direction == 'LONG' and current <= stop_price) or \
                       (direction == 'SHORT' and current >= stop_price)
            hit_tp   = underly_pnl >= TAKE_PROFIT
            hit_time = (j == min(i + TIME_STOP_BARS + 1, len(df) - 1))

            if hit_stop or hit_tp or hit_time:
                pnl = option_pnl(entry_price, current, direction, hold_minutes)
                trades.append({
                    'pnl':       pnl,
                    'direction': direction,
                    'score':     signal_score,
                    'hold':      hold_minutes,
                    'exit':      'stop' if hit_stop else ('tp' if hit_tp else 'time'),
                    'underlying_pnl': underly_pnl
                })
                in_trade = False
                break

    return trades

# =========================
# RUN
# =========================
def run():
    all_trades = {}

    for symbol in SYMBOLS:
        print(f"\n================ {symbol} ================")

        df = fetch_data(symbol)
        if df is None or df.empty:
            print("No data")
            continue

        print(f"Downloaded {len(df)} candles")
        trades = backtest(df)

        if not trades:
            print("No trades")
            continue

        pnls       = [t['pnl'] for t in trades]
        wins       = [p for p in pnls if p > 0]
        losses     = [p for p in pnls if p <= 0]
        winrate    = len(wins) / len(pnls)
        avg_pnl    = np.mean(pnls)
        pf         = sum(wins) / abs(sum(losses)) if losses else float('inf')
        total_pnl  = sum(pnls)

        exit_counts = {}
        for t in trades:
            exit_counts[t['exit']] = exit_counts.get(t['exit'], 0) + 1

        # Breakdown by score quartile (minor vs major levels)
        scores     = sorted(set(t['score'] for t in trades))
        mid_score  = np.median(scores)
        minor      = [t for t in trades if t['score'] <= mid_score]
        major      = [t for t in trades if t['score'] >  mid_score]

        print(f"Trades: {len(trades)}")
        print(f"Win Rate: {winrate*100:.2f}%")
        print(f"Avg PnL (option %): {avg_pnl*100:.2f}%")
        print(f"Avg Winner: {np.mean(wins)*100:.2f}%  |  Avg Loser: {np.mean(losses)*100:.2f}%")
        print(f"Profit Factor: {pf:.2f}")
        print(f"Total PnL: {total_pnl*100:.2f}%")
        print(f"Exits → {exit_counts}")
        print(f"  Minor levels ({len(minor)} trades): WR {sum(1 for t in minor if t['pnl']>0)/len(minor)*100:.1f}%  PnL {sum(t['pnl'] for t in minor)*100:.2f}%" if minor else "  Minor: 0 trades")
        print(f"  Major levels ({len(major)} trades): WR {sum(1 for t in major if t['pnl']>0)/len(major)*100:.1f}%  PnL {sum(t['pnl'] for t in major)*100:.2f}%" if major else "  Major: 0 trades")

        all_trades[symbol] = trades

    combined = [t for v in all_trades.values() for t in v]
    if combined:
        pnls = [t['pnl'] for t in combined]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        print(f"\n================ SUMMARY ================")
        print(f"Total Trades: {len(combined)}")
        print(f"Win Rate: {len(wins)/len(pnls)*100:.2f}%")
        pf = sum(wins) / abs(sum(losses)) if losses else float('inf')
        print(f"Profit Factor: {pf:.2f}")
        print(f"Total Option PnL: {sum(pnls)*100:.2f}%")

if __name__ == "__main__":
    run()
