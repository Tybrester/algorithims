#!/usr/bin/env python3
"""
BOOF32 v2 - Long Trend Pullback Continuation
Real 1-minute Alpaca cached data (~6 months)
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

# ── Credentials ───────────────────────────────────────────────
API_KEY    = 'AKPDLKERTEC2OG42UROO65QMW7'
API_SECRET = 'MTDQmZk5KuQU5p5ZQE4YWMvksTLcxJeGJiCeA4j2vPM'

# ── Parameters ────────────────────────────────────────────────
SYMBOLS = ['NVDA', 'TSLA', 'NFLX', 'AMZN', 'META', 'AVGO']

SCORE_REQUIRED   = 6
COOLDOWN_BARS    = 20  # 20 minutes on 1-min bars
MAX_HOLD_BARS    = 30
TP               = 0.0075  # 0.75%
SL               = 0.004   # 0.40%
SLIPPAGE         = 0.0002
PULLBACK_MIN_BARS = 2
PULLBACK_MAX_BARS = 5
IMPULSE_LOOKBACK  = 20
VOL_LOOKBACK      = 20

# ── Data fetch (cached) ───────────────────────────────────────
def fetch_data(symbol):
    cache_file = f'boof32_data_{symbol}.csv'
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, parse_dates=['datetime'])
        df['date'] = df['datetime'].dt.date
        return df
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    end   = datetime.now()
    start = end - timedelta(days=182)
    req   = StockBarsRequest(symbol_or_symbols=symbol,
                             timeframe=TimeFrame.Minute,
                             start=start, end=end)
    bars = client.get_stock_bars(req)
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level='symbol')
    df = df.reset_index().rename(columns={'timestamp': 'datetime'})
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)
    df['date'] = df['datetime'].dt.date
    df.to_csv(cache_file, index=False)
    return df

# ── Indicators ────────────────────────────────────────────────
def add_indicators(day):
    day = day.copy()
    typical = (day['high'] + day['low'] + day['close']) / 3
    day['vwap']       = (typical * day['volume']).cumsum() / day['volume'].cumsum()
    day['vwap_slope'] = day['vwap'].pct_change(5)
    day['ema20']      = day['close'].ewm(span=20, adjust=False).mean()
    day['ema50']      = day['close'].ewm(span=50, adjust=False).mean()
    day['avg_vol']    = day['volume'].rolling(VOL_LOOKBACK).mean()
    day['body']       = abs(day['close'] - day['open'])
    return day

# ── Trend score (0-3) ─────────────────────────────────────────
def trend_score(day, i):
    score = 0
    bar = day.iloc[i]
    if bar['close'] > bar['vwap']:        score += 1
    if bar['vwap_slope'] > 0:             score += 1
    if bar['ema20'] > bar['ema50']:       score += 1
    return score

# ── Pullback detection ────────────────────────────────────────
def find_pullback(day, i):
    for length in range(PULLBACK_MIN_BARS, PULLBACK_MAX_BARS + 1):
        start = i - length
        end   = i
        if start < IMPULSE_LOOKBACK:
            continue
        pullback = day.iloc[start:end]
        red_count = (pullback['close'] < pullback['open']).sum()
        if red_count < length - 1:
            continue
        impulse_start = max(0, start - IMPULSE_LOOKBACK)
        impulse = day.iloc[impulse_start:start]
        impulse_low  = impulse['low'].min()
        impulse_high = impulse['high'].max()
        impulse_move = impulse_high - impulse_low
        if impulse_move <= 0:
            continue
        pullback_depth   = impulse_high - pullback['low'].min()
        shallow_pullback = pullback_depth / impulse_move < 0.50
        first_vol        = pullback['volume'].iloc[0]
        last_vol         = pullback['volume'].iloc[-1]
        volume_contracting = last_vol < first_vol
        pullback_high = pullback['high'].max()
        return {
            'found': True, 'length': length,
            'pullback_high': pullback_high,
            'shallow': shallow_pullback,
            'volume_contracting': volume_contracting,
            'red_count': int(red_count),
        }
    return {'found': False}

# ── Pullback score (0-3) ──────────────────────────────────────
def pullback_score(pb):
    score = 0
    if pb['red_count'] >= 2:          score += 1
    if pb['volume_contracting']:      score += 1
    if pb['shallow']:                 score += 1
    return score

# ── Trigger score (0-3) ───────────────────────────────────────
def trigger_score(day, i, pb):
    score = 0
    bar     = day.iloc[i]
    avg_vol = bar['avg_vol']
    if pd.isna(avg_vol) or avg_vol <= 0:
        return 0
    if bar['close'] > pb['pullback_high']:    score += 1
    if bar['close'] > bar['open']:            score += 1
    if bar['volume'] > avg_vol * 1.2:         score += 1
    return score

# ── Signal ────────────────────────────────────────────────────
def boof32v2_signal(day, i):
    if i < 80:
        return False, {}
    pb = find_pullback(day, i)
    if not pb['found']:
        return False, {}
    score = trend_score(day, i) + pullback_score(pb) + trigger_score(day, i, pb)
    if score < SCORE_REQUIRED:
        return False, {}
    return True, {'score': score, 'pullback_length': pb['length'], 'pullback_high': pb['pullback_high']}

# ── Exit simulation (vectorized) ──────────────────────────────
def simulate_trade(day, entry_i, entry_price):
    future = day.iloc[entry_i: entry_i + MAX_HOLD_BARS]
    if future.empty:
        return 0.0, 'no_future', 0.0, 0
    highs  = future['high'].values
    lows   = future['low'].values
    closes = future['close'].values
    mfe = (highs.max() - entry_price) / entry_price
    bars_to_peak = int(np.argmax(highs))
    tp_price = entry_price * (1 + TP)
    sl_price = entry_price * (1 - SL)
    tp_hit = np.where(highs >= tp_price)[0]
    sl_hit = np.where(lows  <= sl_price)[0]
    first_tp = tp_hit[0] if len(tp_hit) else len(highs)
    first_sl = sl_hit[0] if len(sl_hit) else len(highs)
    if first_tp <= first_sl:
        return TP - SLIPPAGE * 2, 'target', mfe, bars_to_peak
    elif first_sl < len(highs):
        return -SL - SLIPPAGE * 2, 'stop', mfe, bars_to_peak
    pnl = (closes[-1] - entry_price) / entry_price - SLIPPAGE * 2
    return pnl, 'time', mfe, bars_to_peak

# ── Setup detection (cached, no TP/SL) ───────────────────────
def detect_setups(symbol, df):
    setups = []
    dates = list(df.groupby('date'))
    pullback_counter = {}  # track pullback# per day
    for di, (date, day) in enumerate(dates):
        print(f"  {symbol} {di+1}/{len(dates)}   ", end='\r', flush=True)
        day = day.copy().reset_index(drop=True)
        if len(day) < 150:
            continue
        day = add_indicators(day)
        last_trade_i = -999999
        day_trade_count = 0  # resets every day - this is pullback #N within the day
        for i in range(80, len(day) - MAX_HOLD_BARS - 2):
            if i - last_trade_i < COOLDOWN_BARS:
                continue
            found, sig = boof32v2_signal(day, i)
            if not found:
                continue
            entry_i = i + 1
            if entry_i >= len(day):
                continue
            entry_price = day['open'].iloc[entry_i] * (1 + SLIPPAGE)
            # Future slice starts AFTER entry bar, capped to same-day bars
            end_i = min(entry_i + 1 + MAX_HOLD_BARS, len(day))
            future_slice = day.iloc[entry_i + 1:end_i][['high','low','close']].copy().reset_index(drop=True)
            if future_slice.empty:
                continue
            highs = future_slice['high'].values
            mfe = (highs.max() - entry_price) / entry_price
            bars_to_peak = int(np.argmax(highs))
            day_trade_count += 1
            setups.append({
                'symbol':          symbol,
                'date':            date,
                'entry_time':      day['datetime'].iloc[entry_i],
                'score':           sig['score'],
                'pullback_length': sig['pullback_length'],
                'pullback_number': day_trade_count,
                'entry_price':     entry_price,
                'mfe':             mfe,
                'bars_to_peak':    bars_to_peak,
                'future_high':     future_slice['high'].values,
                'future_low':      future_slice['low'].values,
                'future_close':    future_slice['close'].values,
            })
            last_trade_i = i
    print()
    return setups

# ── Replay exits for a given TP/SL ────────────────────────────
def replay_exits(setups, tp, sl):
    trades = []
    for s in setups:
        highs  = s['future_high']
        lows   = s['future_low']
        closes = s['future_close']
        ep     = s['entry_price']
        tp_price = ep * (1 + tp)
        sl_price = ep * (1 - sl)
        tp_hit = np.where(highs >= tp_price)[0]
        sl_hit = np.where(lows  <= sl_price)[0]
        first_tp = tp_hit[0] if len(tp_hit) else len(highs)
        first_sl = sl_hit[0] if len(sl_hit) else len(highs)
        if first_tp < len(highs) and first_tp <= first_sl:
            pnl, reason = tp - SLIPPAGE * 2, 'target'
        elif first_sl < len(highs):
            pnl, reason = -sl - SLIPPAGE * 2, 'stop'
        else:
            pnl, reason = (closes[-1] - ep) / ep - SLIPPAGE * 2, 'time'
        trades.append({**{k: v for k, v in s.items() if k not in ('future_high','future_low','future_close')},
                       'pnl': pnl, 'exit_reason': reason})
    return trades

# ── Summary ───────────────────────────────────────────────────
def max_drawdown(pnl_series):
    equity = (1 + pnl_series).cumprod()
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max
    return dd.min()

def summarize(results):
    if results.empty:
        print("No trades found.")
        return
    wins   = results[results['pnl'] > 0]
    losses = results[results['pnl'] < 0]
    pf     = wins['pnl'].sum() / abs(losses['pnl'].sum()) if len(losses) > 0 else float('inf')
    wr     = len(wins) / len(results)
    ev     = results['pnl'].mean()
    std    = results['pnl'].std()
    sharpe = ev / std if std > 0 else 0
    mdd    = max_drawdown(results['pnl'])
    trading_days = results['date'].nunique()
    tpd    = len(results) / trading_days if trading_days > 0 else 0

    print("\nBOOF32 v2 - LONG TREND PULLBACK (Top 6 Symbols)")
    print("=" * 60)
    print(f"Trades        : {len(results)}")
    print(f"Trades/day    : {tpd:.1f}")
    print(f"Win Rate      : {wr:.1%}")
    print(f"Profit Factor : {pf:.2f}")
    print(f"EV / trade    : {ev:.4%}")
    print(f"Sharpe/trade  : {sharpe:.3f}")
    print(f"Total P&L     : {results['pnl'].sum():.2%}")
    print(f"Max Drawdown  : {mdd:.2%}")

    print("\nBy Symbol:")
    sym_rows = []
    for sym_name, grp in results.groupby('symbol'):
        x = grp['pnl']
        w = (x > 0).sum()
        l = (x <= 0).sum()
        pf_s = x[x > 0].sum() / abs(x[x <= 0].sum()) if l > 0 and x[x <= 0].sum() != 0 else float('inf')
        sym_rows.append({'symbol': sym_name, 'trades': len(x), 'win_rate': round(w/len(x), 3), 'pf': round(pf_s, 2), 'ev': round(x.mean(), 6), 'total': round(x.sum(), 4)})
    sym_df = pd.DataFrame(sym_rows).set_index('symbol').sort_values('total', ascending=False)
    print(sym_df.to_string())

    print("\nBy Score:")
    print(results.groupby('score')['pnl'].agg(['count','mean','sum']).to_string())

    print("\nExit Reasons:")
    print(results['exit_reason'].value_counts().to_string())

    print("\nTrades/day per Symbol:")
    tpd_sym = results.groupby('symbol').apply(
        lambda x: round(len(x) / x['date'].nunique(), 1)
    ).sort_values(ascending=False)
    print(tpd_sym.to_string())

    print("\nTrades by Hour (all symbols):")
    results['hour'] = pd.to_datetime(results['entry_time']).dt.hour
    hourly = results.groupby('hour').agg(trades=('pnl','count'), win_rate=('pnl', lambda x: (x>0).mean()), avg_pnl=('pnl','mean'))
    print(hourly.to_string())

    print("\nOverlap check - min gap between trades (same symbol, same day):")
    results['entry_dt'] = pd.to_datetime(results['entry_time'])
    results_sorted = results.sort_values(['symbol','entry_dt'])
    results_sorted['gap_min'] = results_sorted.groupby('symbol')['entry_dt'].diff().dt.total_seconds() / 60
    min_gap = results_sorted['gap_min'].dropna()
    print(f"  Min gap   : {min_gap.min():.0f} min")
    print(f"  Avg gap   : {min_gap.mean():.1f} min")
    print(f"  <20 min   : {(min_gap < 20).sum()} occurrences")

# ── Compact compare summary ───────────────────────────────────
def compare_summary(r):
    if r.empty:
        print("  No trades.")
        return
    wins = r[r['pnl'] > 0]
    losses = r[r['pnl'] <= 0]
    wr  = len(wins) / len(r)
    pf  = wins['pnl'].sum() / abs(losses['pnl'].sum()) if losses['pnl'].sum() != 0 else float('inf')
    ev  = r['pnl'].mean()
    std = r['pnl'].std()
    sharpe = ev / std if std > 0 else 0
    trading_days = r['date'].nunique()
    tpd = len(r) / trading_days if trading_days > 0 else 0
    print(f"  Trades/day    : {tpd:.1f}")
    print(f"  Win Rate      : {wr:.1%}")
    print(f"  Profit Factor : {pf:.2f}")
    print(f"  EV / trade    : {ev:.4%}")
    print(f"  Sharpe/trade  : {sharpe:.3f}")
    print(f"  Total P&L     : {r['pnl'].sum():.2%}")

# ── Main ──────────────────────────────────────────────────────
def main():
    import pickle
    SETUP_CACHE = 'boof32v2_setups.pkl'

    print("BOOF32 v2 - Long Trend Pullback (~6 months)")
    print(f"Symbols: {SYMBOLS}")
    print(f"TP: {TP:.2%}  SL: {SL:.2%}  Score >= {SCORE_REQUIRED}")
    print("=" * 60)

    # ── Load or build setup cache (no TP/SL baked in) ──
    if os.path.exists(SETUP_CACHE):
        with open(SETUP_CACHE, 'rb') as f:
            all_setups = pickle.load(f)
        # Invalidate if missing new fields
        if not all_setups or 'future_high' not in all_setups[0] or not isinstance(all_setups[0]['future_high'], np.ndarray):
            print("Cache outdated - deleting and rebuilding...")
            os.remove(SETUP_CACHE)
            all_setups = None
        else:
            print(f"Loading cached setups... {len(all_setups)} loaded instantly")
    else:
        all_setups = None

    if all_setups is None:
        all_setups = []
        for symbol in SYMBOLS:
            print(f"Loading {symbol}...", end=' ', flush=True)
            try:
                df = fetch_data(symbol)
                print(f"{len(df):,} bars")
                setups = detect_setups(symbol, df)
                all_setups.extend(setups)
                print(f"  {symbol}: {len(setups)} setups")
            except Exception as e:
                print(f"ERROR: {e}")
        with open(SETUP_CACHE, 'wb') as f:
            pickle.dump(all_setups, f)
        print(f"Setups cached to {SETUP_CACHE} ({len(all_setups)} total)")

    # ── 9:30-10:30 ET filter (15:30-16:30 UTC) ──
    def et_window(setups):
        out = []
        for s in setups:
            t = pd.Timestamp(s['entry_time'])
            h, m = t.hour, t.minute
            if (h == 15 and m >= 30) or (h == 16 and m <= 30):
                out.append(s)
        return out

    morning = et_window(all_setups)
    print(f"\n9:30-10:30 ET setups: {len(morning)}")

    # ── Helper ──
    def stats_line(trades, label):
        if not trades: print(f"  {label}: no trades"); return
        x = pd.Series([t['pnl'] for t in trades])
        w = (x > 0).sum()
        l = (x <= 0).sum()
        pf_s = x[x>0].sum()/abs(x[x<=0].sum()) if l>0 and x[x<=0].sum()!=0 else float('inf')
        tdays = len(set(t['date'] for t in trades))
        tpd = len(trades)/tdays if tdays else 0
        mfe_avg = np.mean([t['mfe'] for t in trades])*100
        peak_avg = np.mean([t['bars_to_peak'] for t in trades])
        print(f"  {label:30s}  n:{len(trades):4d}  t/day:{tpd:.1f}  WR:{w/len(x):.1%}  PF:{pf_s:.2f}  EV:{x.mean():.4%}  MFE:{mfe_avg:.2f}%  peak:{peak_avg:.0f}bar")

    # ════════════════════════════════════════════════════════════
    # MFE Study - all 1076 morning trades
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print("  MFE Study - 9:30-10:30 ET (all 1076 trades)")
    print(f"{'='*60}")
    all_mfes = [s['mfe'] for s in morning]
    for pct in [0.0010, 0.0020, 0.0030, 0.0040, 0.0050]:
        reached = sum(1 for m in all_mfes if m >= pct)
        print(f"  Reach {pct:.2%}: {reached:4d} / {len(morning)}  = {reached/len(morning):.1%}")

    # ════════════════════════════════════════════════════════════
    # TEST 1: META only - TP/SL sweep
    # ════════════════════════════════════════════════════════════
    meta = [s for s in morning if s['symbol'] == 'META']
    print(f"\n{'='*60}")
    print("  TEST 1: META only - TP/SL sweep")
    print(f"{'='*60}")
    for tp_val, sl_val in [(0.005,0.0025),(0.0075,0.004),(0.010,0.004)]:
        trades = replay_exits(meta, tp_val, sl_val)
        stats_line(trades, f"TP:{tp_val:.2%} SL:{sl_val:.2%}")

    # ════════════════════════════════════════════════════════════
    # TEST 2: META+NFLX - TP/SL sweep
    # ════════════════════════════════════════════════════════════
    meta_nflx = [s for s in morning if s['symbol'] in ('META','NFLX')]
    print(f"\n{'='*60}")
    print("  TEST 2: META+NFLX - TP/SL sweep")
    print(f"{'='*60}")
    for tp_val, sl_val in [(0.005,0.0025),(0.0075,0.004),(0.010,0.004)]:
        trades = replay_exits(meta_nflx, tp_val, sl_val)
        stats_line(trades, f"TP:{tp_val:.2%} SL:{sl_val:.2%}")

    # ════════════════════════════════════════════════════════════
    # TEST 3: Pullback # breakdown (META+NFLX, best TP/SL)
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print("  TEST 3: Pullback # (META+NFLX, TP:0.75% SL:0.40%)")
    print(f"{'='*60}")
    all_mn = replay_exits(meta_nflx, 0.0075, 0.004)
    for pb_n in [1, 2, 3]:
        label = f"Pullback #{pb_n}" if pb_n < 3 else "Pullback #3+"
        subset = [t for t in all_mn if (t['pullback_number'] == pb_n if pb_n < 3 else t['pullback_number'] >= 3)]
        stats_line(subset, label)


if __name__ == "__main__":
    main()
