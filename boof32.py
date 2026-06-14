#!/usr/bin/env python3
"""
BOOF32 - Support Sweep / Reclaim / Continuation Long Strategy
Real 1-minute Alpaca data, ~6 months
Symbols: TSLA, AMD, META, NVDA, NFLX
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import warnings
warnings.filterwarnings('ignore')

# ── Credentials ──────────────────────────────────────────────
API_KEY    = 'AKPDLKERTEC2OG42UROO65QMW7'
API_SECRET = 'MTDQmZk5KuQU5p5ZQE4YWMvksTLcxJeGJiCeA4j2vPM'

# ── Parameters ───────────────────────────────────────────────
SUPPORT_TOL      = 0.002
SWEEP_BUFFER     = 0.002
LOOKBACK         = 80
MAX_CONFIRM_BARS = 5
HOLD_BARS        = 3
COOLDOWN_BARS    = 30
SCORE_REQUIRED   = 6
SLIPPAGE         = 0.0002
STOP_LOSS        = 0.0025
TP1              = 0.005
TRAIL_STOP       = 0.0025
MAX_HOLD_BARS    = 30

SYMBOLS = ['TSLA', 'AMD', 'META', 'NVDA', 'NFLX']

# ── Data fetch ────────────────────────────────────────────────
def fetch_data(symbol):
    cache_file = f'boof32_data_{symbol}.csv'
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, parse_dates=['datetime'])
        df['date'] = df['datetime'].dt.date
        return df
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    end    = datetime.now()
    start  = end - timedelta(days=182)
    req    = StockBarsRequest(
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
    df.to_csv(cache_file, index=False)
    return df

# ── Indicators ────────────────────────────────────────────────
def add_indicators(day):
    day = day.copy()
    typical          = (day['high'] + day['low'] + day['close']) / 3
    day['vwap']      = (typical * day['volume']).cumsum() / day['volume'].cumsum()
    day['vwap_slope']= day['vwap'].pct_change(5)
    day['avg_vol_20']= day['volume'].rolling(20).mean()
    day['ema20']     = day['close'].ewm(span=20, adjust=False).mean()
    day['ema50']     = day['close'].ewm(span=50, adjust=False).mean()
    return day

# ── Support detection ─────────────────────────────────────────
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

# ── Setup detection ───────────────────────────────────────────
def detect_long_sequence(day, i):
    support, touches = find_support(day, i)
    if support is None:
        return False, {}
    bar = day.iloc[i]
    # ── Trend pre-conditions (must ALL be true before sweep) ──
    if pd.isna(day['vwap'].iloc[i]) or pd.isna(day['ema20'].iloc[i]) or pd.isna(day['ema50'].iloc[i]):
        return False, {}
    if bar['close'] <= day['vwap'].iloc[i]:
        return False, {}
    if day['vwap_slope'].iloc[i] <= 0:
        return False, {}
    if day['ema20'].iloc[i] <= day['ema50'].iloc[i]:
        return False, {}
    # ─────────────────────────────────────────────────────────
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

# ── Scoring ───────────────────────────────────────────────────
def score_setup(day, sig):
    score     = 0
    sweep_bar = day.iloc[sig['sweep_i']]
    break_bar = day.iloc[sig['break_i']]
    avg_vol   = day['avg_vol_20'].iloc[sig['break_i']]
    if pd.isna(avg_vol) or avg_vol <= 0:
        return 0
    # Trend alignment
    if break_bar['close'] > day['vwap'].iloc[sig['break_i']]:                   score += 1
    if day['vwap_slope'].iloc[sig['break_i']] > 0:                              score += 1
    if break_bar['close'] > day['ema20'].iloc[sig['break_i']]:                  score += 1
    if day['ema20'].iloc[sig['break_i']] > day['ema50'].iloc[sig['break_i']]:   score += 1
    # Support quality
    if sig['touches'] >= 3: score += 1
    if sig['touches'] >= 4: score += 1
    # Reclaim strength
    lower_wick = min(sweep_bar['open'], sweep_bar['close']) - sweep_bar['low']
    body = abs(sweep_bar['close'] - sweep_bar['open'])
    if body > 0 and lower_wick > body * 1.5:   score += 1
    if sweep_bar['close'] > sweep_bar['open']:  score += 1
    if sweep_bar['close'] > sig['support']:     score += 1
    # Volume
    if sweep_bar['volume'] > avg_vol:           score += 1
    if break_bar['volume'] > avg_vol:           score += 1
    if break_bar['volume'] > avg_vol * 1.2:     score += 1
    # Timing
    if 0 <= sig['break_i'] - sig['sweep_i'] <= MAX_CONFIRM_BARS: score += 1
    if support_held(day, sig['support'], sig['sweep_i'] + 1):     score += 1
    return score

# ── Exit simulation ───────────────────────────────────────────
def simulate_exit(day, entry_i, entry_price, sig, tp, sl, use_smart_exit=False):
    end_i   = min(entry_i + MAX_HOLD_BARS, len(day))
    future  = day.iloc[entry_i:end_i]
    highs   = future['high'].values
    lows    = future['low'].values
    closes  = future['close'].values
    tp_price = entry_price * (1 + tp)
    sl_price = entry_price * (1 - sl) if sl > 0 else None
    support  = sig['support']
    mfe = (highs.max() - entry_price) / entry_price
    mae = (lows.min()  - entry_price) / entry_price

    if not use_smart_exit:
        # Vectorized: find first bar that hits TP or SL
        tp_hit = np.where(highs >= tp_price)[0]
        sl_hit = np.where(lows  <= sl_price)[0] if sl_price else np.array([])
        first_tp = tp_hit[0] if len(tp_hit) else len(highs)
        first_sl = sl_hit[0] if len(sl_hit) else len(highs)
        if first_tp <= first_sl:
            return mfe, mae, tp - SLIPPAGE
        elif first_sl < len(highs):
            return mfe, mae, -sl - SLIPPAGE
    else:
        ema20s = future['ema20'].values
        for k in range(len(closes)):
            if highs[k] >= tp_price:
                return mfe, mae, tp - SLIPPAGE
            if not np.isnan(ema20s[k]) and closes[k] < ema20s[k]:
                return mfe, mae, (closes[k] - entry_price) / entry_price - SLIPPAGE
            if closes[k] < support:
                return mfe, mae, (closes[k] - entry_price) / entry_price - SLIPPAGE

    pnl = (closes[-1] - entry_price) / entry_price - SLIPPAGE
    return mfe, mae, pnl

# ── Detect setups once (scan only) ────────────────────────────
def detect_setups(symbol, df):
    setups = []
    dates = list(df.groupby('date'))
    for di, (date, day) in enumerate(dates):
        print(f"  {symbol} {di+1}/{len(dates)}   ", end='\r', flush=True)
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
            # Store the future bars slice for exit replay
            future_slice = day.iloc[entry_i: entry_i + MAX_HOLD_BARS].copy().reset_index(drop=True)
            setups.append({
                'symbol':      symbol,
                'date':        date,
                'entry_time':  day['datetime'].iloc[entry_i],
                'score':       score,
                'support':     sig['support'],
                'touches':     sig['touches'],
                'entry_price': entry_price,
                'future':      future_slice,
            })
            last_trade_i = i
    return setups

# ── Replay exits for a given config ───────────────────────────
def replay_exits(setup_list, tp, sl, use_smart_exit):
    trades = []
    for s in setup_list:
        mfe, mae, pnl = simulate_exit_from_slice(
            s['future'], s['entry_price'], s['support'], tp, sl, use_smart_exit
        )
        trades.append({**{k: v for k, v in s.items() if k != 'future'},
                       'mfe': mfe, 'mae': mae, 'pnl': pnl})
    return trades

def simulate_exit_from_slice(future, entry_price, support, tp, sl, use_smart_exit):
    if future.empty:
        return 0.0, 0.0, 0.0
    highs  = future['high'].values
    lows   = future['low'].values
    closes = future['close'].values
    tp_price = entry_price * (1 + tp)
    sl_price = entry_price * (1 - sl) if sl > 0 else None
    mfe = (highs.max() - entry_price) / entry_price
    mae = (lows.min()  - entry_price) / entry_price
    if not use_smart_exit:
        tp_hit = np.where(highs >= tp_price)[0]
        sl_hit = np.where(lows  <= sl_price)[0] if sl_price else np.array([])
        first_tp = tp_hit[0] if len(tp_hit) else len(highs)
        first_sl = sl_hit[0] if len(sl_hit) else len(highs)
        if first_tp <= first_sl:
            return mfe, mae, tp - SLIPPAGE
        elif first_sl < len(highs):
            return mfe, mae, -sl - SLIPPAGE
    else:
        ema20s = future['ema20'].values
        for k in range(len(closes)):
            if highs[k] >= tp_price:
                return mfe, mae, tp - SLIPPAGE
            if not np.isnan(ema20s[k]) and closes[k] < ema20s[k]:
                return mfe, mae, (closes[k] - entry_price) / entry_price - SLIPPAGE
            if closes[k] < support:
                return mfe, mae, (closes[k] - entry_price) / entry_price - SLIPPAGE
    pnl = (closes[-1] - entry_price) / entry_price - SLIPPAGE
    return mfe, mae, pnl

# ── Summary ───────────────────────────────────────────────────
def summarize(all_trades, label):
    if not all_trades:
        print(f"  {label}: No trades")
        return
    r      = pd.DataFrame(all_trades)
    wins   = r[r['pnl'] > 0]
    losses = r[r['pnl'] <= 0]
    wr     = len(wins) / len(r)
    pf     = wins['pnl'].sum() / abs(losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else float('inf')
    ev     = r['pnl'].mean()
    std    = r['pnl'].std()
    sharpe = (ev / std * np.sqrt(252 * 390)) if std > 0 else 0
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Trades        : {len(r)}")
    print(f"  Win Rate      : {wr:.1%}")
    print(f"  Profit Factor : {pf:.2f}")
    print(f"  EV / trade    : {ev:.4%}")
    print(f"  Sharpe        : {sharpe:.3f}")
    print(f"  Total P&L     : {r['pnl'].sum():.2%}")
    print(f"  Avg MFE       : {r['mfe'].mean():.3%}")
    print(f"  Avg MAE       : {r['mae'].mean():.3%}")
    print("\n  By Symbol:")
    sym = r.groupby('symbol').agg(trades=('pnl','count'), avg_pnl=('pnl','mean'))
    sym['win_rate'] = r.groupby('symbol').apply(lambda x: (x['pnl'] > 0).mean())
    print(sym.sort_values('avg_pnl', ascending=False).to_string())

TESTS = [
    {'label': 'Current  TP:0.50% SL:0.25%',         'tp': 0.005,  'sl': 0.0025, 'smart': False},
    {'label': 'Test A   TP:0.50% SL:0.40%',          'tp': 0.005,  'sl': 0.004,  'smart': False},
    {'label': 'Test B   TP:0.75% SL:0.40%',          'tp': 0.0075, 'sl': 0.004,  'smart': False},
    {'label': 'Test C   TP:0.50% No SL (smart exit)', 'tp': 0.005,  'sl': 0,      'smart': True},
]

# ── Main ──────────────────────────────────────────────────────
def main():
    print("BOOF32 - Real 1-min Data Backtest (~6 months)")
    print(f"Symbols : {SYMBOLS}  |  Score: {SCORE_REQUIRED}+")
    print("=" * 60)

    data = {}
    for symbol in SYMBOLS:
        print(f"Loading {symbol}...", end=' ', flush=True)
        try:
            df = fetch_data(symbol)
            data[symbol] = df
            print(f"{len(df):,} bars")
        except Exception as e:
            print(f"ERROR: {e}")

    # Detect setups once per symbol
    print("\nDetecting setups (one-time scan)...")
    setups = {}
    for symbol, df in data.items():
        setups[symbol] = detect_setups(symbol, df)
        print(f"  {symbol}: {len(setups[symbol])} setups")

    # Replay exits for each test config
    for test in TESTS:
        print(f"\nRunning: {test['label']}")
        all_trades = []
        for symbol, setup_list in setups.items():
            trades = replay_exits(setup_list, test['tp'], test['sl'], test['smart'])
            all_trades.extend(trades)
            print(f"  {symbol}: {len(trades)} trades")
        summarize(all_trades, test['label'])


if __name__ == "__main__":
    main()
