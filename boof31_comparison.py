#!/usr/bin/env python3
"""
BOOF32 - Real Data Backtest
Support Sweep / Reclaim / Continuation Long Strategy
Real 1-minute Alpaca data, 6 months
Symbols: TSLA, AMD, META, NVDA, NFLX
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import warnings
warnings.filterwarnings('ignore')

# Alpaca credentials
API_KEY    = 'PK2O2N4OQ4PEATNTDN57MNSIB7'
API_SECRET = '894T7WQpHVjfLXitiv1cG1ZkGeQsegtWhA2jLocVfCnc'

# BOOF32 Parameters
SUPPORT_TOL    = 0.002
SWEEP_BUFFER   = 0.002
LOOKBACK       = 80
MAX_CONFIRM_BARS = 5
HOLD_BARS      = 3
COOLDOWN_BARS  = 30
SCORE_REQUIRED = 6
SLIPPAGE       = 0.0002
STOP_LOSS      = 0.0025
TP1            = 0.005
TRAIL_STOP     = 0.0025
MAX_HOLD_BARS  = 30

SYMBOLS = ['TSLA', 'AMD', 'META', 'NVDA', 'NFLX']

client = StockHistoricalDataClient(API_KEY, API_SECRET)


def fetch_data(symbol):
    end   = datetime.now()
    start = end - timedelta(days=182)  # ~6 months
    req   = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end
    )
    bars = client.get_stock_bars(req)
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level='symbol')
    df = df.reset_index()
    df = df.rename(columns={'timestamp': 'datetime'})
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)
    df['date'] = df['datetime'].dt.date
    return df


def add_indicators(day):
    day = day.copy()
    typical = (day['high'] + day['low'] + day['close']) / 3
    day['vwap']       = (typical * day['volume']).cumsum() / day['volume'].cumsum()
    day['vwap_slope'] = day['vwap'].pct_change(5)
    day['avg_vol_20'] = day['volume'].rolling(20).mean()
    day['ema20']      = day['close'].ewm(span=20, adjust=False).mean()
    day['ema50']      = day['close'].ewm(span=50, adjust=False).mean()
    return day


def find_support(day, i):
    window = day.iloc[max(0, i - LOOKBACK):i]
    if len(window) < 20:
        return None, 0
    lows = window['low'].values
    best_level, best_touches = None, 0
    for low in lows:
        touches = int(np.sum(np.abs(lows - low) / low <= SUPPORT_TOL))
        if touches > best_touches:
            best_touches = touches
            best_level   = low
    if best_touches < 2:
        return None, 0
    return best_level, best_touches


def prior_swing_high(day, i, lookback=20):
    if i < lookback:
        return None
    return day['high'].iloc[i - lookback:i].max()


def support_held(day, support, start_i):
    end_i = min(start_i + HOLD_BARS, len(day))
    for j in range(start_i, end_i):
        if day['close'].iloc[j] < support:
            return False
    return True


def detect_long_sequence(day, i):
    support, touches = find_support(day, i)
    if support is None:
        return False, {}
    bar = day.iloc[i]
    if not (bar['low'] < support * (1 - SWEEP_BUFFER) and bar['close'] > support):
        return False, {}
    if not support_held(day, support, i + 1):
        return False, {}
    swing_high = prior_swing_high(day, i)
    if swing_high is None:
        return False, {}
    breakout_level = max(bar['high'], swing_high)
    for j in range(i + 1, min(i + 1 + MAX_CONFIRM_BARS, len(day) - 1)):
        if day.iloc[j]['close'] > breakout_level:
            return True, {
                'sweep_i': i, 'break_i': j, 'entry_i': j + 1,
                'support': support, 'touches': touches,
                'swing_high': swing_high, 'breakout_level': breakout_level,
            }
    return False, {}


def score_setup(day, sig):
    score     = 0
    sweep_bar = day.iloc[sig['sweep_i']]
    break_bar = day.iloc[sig['break_i']]
    avg_vol   = day['avg_vol_20'].iloc[sig['break_i']]
    if pd.isna(avg_vol) or avg_vol <= 0:
        return 0
    # Trend
    if break_bar['close'] > day['vwap'].iloc[sig['break_i']]:  score += 1
    if day['vwap_slope'].iloc[sig['break_i']] > 0:             score += 1
    if break_bar['close'] > day['ema20'].iloc[sig['break_i']]:  score += 1
    if day['ema20'].iloc[sig['break_i']] > day['ema50'].iloc[sig['break_i']]: score += 1
    # Support quality
    if sig['touches'] >= 3: score += 1
    if sig['touches'] >= 4: score += 1
    # Reclaim
    lower_wick = min(sweep_bar['open'], sweep_bar['close']) - sweep_bar['low']
    body = abs(sweep_bar['close'] - sweep_bar['open'])
    if body > 0 and lower_wick > body * 1.5:          score += 1
    if sweep_bar['close'] > sweep_bar['open']:         score += 1
    if sweep_bar['close'] > sig['support']:            score += 1
    # Volume
    if sweep_bar['volume'] > avg_vol:                  score += 1
    if break_bar['volume'] > avg_vol:                  score += 1
    if break_bar['volume'] > avg_vol * 1.2:            score += 1
    # Timing
    if 0 <= sig['break_i'] - sig['sweep_i'] <= MAX_CONFIRM_BARS: score += 1
    if support_held(day, sig['support'], sig['sweep_i'] + 1):     score += 1
    return score


def simulate_exit(day, entry_i, entry_price):
    pnl, half_exited, best_price = 0.0, False, entry_price
    future = day.iloc[entry_i: entry_i + MAX_HOLD_BARS]
    if future.empty:
        return 0.0
    for _, bar in future.iterrows():
        if not half_exited and (bar['low'] - entry_price) / entry_price <= -STOP_LOSS:
            return -STOP_LOSS
        if half_exited:
            best_price = max(best_price, bar['high'])
            trail_price = best_price * (1 - TRAIL_STOP)
            if bar['low'] <= trail_price:
                pnl += 0.5 * (trail_price - entry_price) / entry_price
                return pnl
        if not half_exited and (bar['high'] - entry_price) / entry_price >= TP1:
            pnl += 0.5 * TP1
            half_exited = True
            best_price  = bar['high']
    last_close = future.iloc[-1]['close']
    final_move = (last_close - entry_price) / entry_price
    if half_exited:
        pnl += 0.5 * final_move
        return pnl
    return final_move


def backtest_symbol(symbol, df):
    trades = []
    for date, day in df.groupby('date'):
        day = day.copy().reset_index(drop=True)
        if len(day) < 150:
            continue
        day = add_indicators(day)
        last_trade_i = -999999
        for i in range(LOOKBACK + 50, len(day) - MAX_HOLD_BARS - MAX_CONFIRM_BARS - 2):
            if i - last_trade_i < COOLDOWN_BARS:
                continue
            found, sig = detect_long_sequence(day, i)
            if not found:
                continue
            score = score_setup(day, sig)
            if score < SCORE_REQUIRED:
                continue
            entry_i = sig['entry_i']
            if entry_i >= len(day):
                continue
            entry_price = day['open'].iloc[entry_i] * (1 + SLIPPAGE)
            raw_pnl = simulate_exit(day, entry_i, entry_price)
            pnl     = raw_pnl - SLIPPAGE * 2
            trades.append({
                'symbol':      symbol,
                'date':        date,
                'entry_time':  day['datetime'].iloc[entry_i],
                'score':       score,
                'support':     sig['support'],
                'touches':     sig['touches'],
                'entry_price': entry_price,
                'pnl':         pnl,
            })
            last_trade_i = i
    return trades


def summarize(all_trades):
    if not all_trades:
        print("No trades found.")
        return
    r  = pd.DataFrame(all_trades)
    wins   = r[r['pnl'] > 0]
    losses = r[r['pnl'] < 0]
    wr  = len(wins) / len(r)
    pf  = wins['pnl'].sum() / abs(losses['pnl'].sum()) if len(losses) > 0 else float('inf')
    ev  = r['pnl'].mean()
    std = r['pnl'].std()
    sharpe = (ev / std * np.sqrt(252 * 390)) if std > 0 else 0

    print("\n" + "=" * 60)
    print("BOOF32 REAL DATA RESULTS")
    print("=" * 60)
    print(f"Trades        : {len(r)}")
    print(f"Win Rate      : {wr:.1%}")
    print(f"Profit Factor : {pf:.2f}")
    print(f"EV / trade    : {ev:.4%}")
    print(f"Sharpe        : {sharpe:.3f}")
    print(f"Total P&L     : {r['pnl'].sum():.2%}")
    print(f"Avg Win       : {wins['pnl'].mean():.3%}" if len(wins) > 0 else "Avg Win       : N/A")
    print(f"Avg Loss      : {losses['pnl'].mean():.3%}" if len(losses) > 0 else "Avg Loss      : N/A")

    print("\nBy Symbol:")
    sym = r.groupby('symbol')['pnl'].agg(['count','mean','sum'])
    sym.columns = ['trades','avg_pnl','total_pnl']
    sym['win_rate'] = r.groupby('symbol').apply(lambda x: (x['pnl'] > 0).mean())
    print(sym.sort_values('total_pnl', ascending=False).to_string())

    print("\nBy Score:")
    sc = r.groupby('score')['pnl'].agg(['count','mean','sum'])
    sc.columns = ['trades','avg_pnl','total_pnl']
    print(sc.sort_index().to_string())

    r.to_csv('boof32_trades.csv', index=False)
    print("\nSaved: boof32_trades.csv")


def main():
    print("BOOF32 - Real 1-min Data Backtest (~6 months)")
    print(f"Symbols: {SYMBOLS}")
    print(f"Score required: {SCORE_REQUIRED}")
    print("=" * 60)

    all_trades = []
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol}...", end=' ', flush=True)
        try:
            df = fetch_data(symbol)
            print(f"{len(df):,} bars  |  ", end='', flush=True)
            trades = backtest_symbol(symbol, df)
            all_trades.extend(trades)
            print(f"{len(trades)} trades")
        except Exception as e:
            print(f"ERROR: {e}")

    summarize(all_trades)


if __name__ == "__main__":
    main()
