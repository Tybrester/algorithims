"""
Volume filter comparison test for Boof 20.0
Tests: fixed mult | RVOL percentile | session-relative | z-score
"""
import numpy as np
import pandas as pd
from datetime import datetime
from dataclasses import dataclass
from scipy.signal import argrelextrema
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

# =========================
# CONFIG
# =========================
SYMBOLS    = ["SPY", "QQQ", "TSLA", "NVDA", "AMD"]
TIMEFRAME  = "1Min"
START_DATE = datetime(2026, 4, 1)
END_DATE   = datetime(2026, 4, 30)

LOOKBACK_BARS   = 120
PIVOT_ORDER     = 5
ATR_TOLERANCE   = 0.25
MIN_TOUCHES     = 2
ATR_BREAK_MULT  = 0.1
ATR_BODY_MULT   = 0.3
ATR_TP_MULT     = 2.0
TIME_STOP_BARS  = 30
COMP_BARS       = 20
COMP_PERCENTILE = 40
COMP_RANGE_MULT = 0.8
VWAP_BIAS       = True
OPTION_COST_PCT = 0.004
DELTA           = 0.50
THETA_PER_MIN   = OPTION_COST_PCT * (0.50 / 390)
TIME_FILTER     = True
TIME_WINDOWS    = [(5, 120), (300, 450)]

# Volume mode + thresholds
VOL_MODE        = 'rvol_pct'
RVOL_PERCENTILE = 70        # overridden per-symbol at runtime
VOL_MULT        = 1.5
SESSION_MULT    = 1.5
ZSCORE_THRESH   = 1.0

# Per-symbol RVOL percentile calibration candidates
SYMBOL_RVOL_CANDIDATES = {
    'SPY':  [75, 80, 85],
    'QQQ':  [75, 80, 85],
    'TSLA': [65, 70, 75],
    'NVDA': [70, 75, 80],
    'AMD':  [60, 65, 70],
}

# =========================
# CORE (unchanged)
# =========================
@dataclass
class SRLevel:
    low: float; high: float; touches: int; volume: float
    strength: float; level_type: str; classification: str

def compute_atr(df, period=14):
    hl = df['high'] - df['low']
    hc = np.abs(df['high'] - df['close'].shift())
    lc = np.abs(df['low']  - df['close'].shift())
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(period).mean()

def detect_pivots(df, order=PIVOT_ORDER):
    highs = df.iloc[argrelextrema(df['high'].values, np.greater_equal, order=order)[0]]
    lows  = df.iloc[argrelextrema(df['low'].values,  np.less_equal,    order=order)[0]]
    return highs, lows

def get_sr_levels(df):
    highs, lows = detect_pivots(df)
    atr = compute_atr(df).iloc[-1]
    avg_vol = df['volume'].mean()
    raw = []
    for _, row in highs.iterrows():
        raw.append({"price": row['high'], "type": "resistance"})
    for _, row in lows.iterrows():
        raw.append({"price": row['low'],  "type": "support"})
    clustered = []
    for lvl in sorted(raw, key=lambda x: x['price']):
        merged = False
        for zone in clustered:
            zone_mid = (zone['low'] + zone['high']) / 2
            if abs(lvl['price'] - zone_mid) < atr * ATR_TOLERANCE:
                zone['low']     = min(zone['low'],  lvl['price'])
                zone['high']    = max(zone['high'], lvl['price'])
                zone['touches'] += 1
                merged = True
                break
        if not merged:
            clustered.append({"low": lvl['price'], "high": lvl['price'],
                               "touches": 1, "type": lvl['type']})
    scored = []
    for zone in clustered:
        if zone['touches'] < MIN_TOUCHES:
            continue
        mid         = (zone['low'] + zone['high']) / 2
        touch_score = np.log1p(zone['touches']) * 20
        nearby      = df[(df['low'] <= mid) & (df['high'] >= mid)]
        vol_score   = (nearby['volume'].mean() / avg_vol) * 30 if len(nearby) else 0
        age_score   = min(zone['touches'] * 5, 20)
        strength    = touch_score + vol_score + age_score
        scored.append(SRLevel(
            low=zone['low'], high=zone['high'], touches=zone['touches'],
            volume=nearby['volume'].sum() if len(nearby) else 0,
            strength=strength, level_type=zone['type'],
            classification="major" if strength >= 50 else "minor"
        ))
    return scored, atr

def is_compressed(df, up_to_idx):
    if up_to_idx < 100:
        return False
    atr_series  = df['atr'].iloc[up_to_idx - 100: up_to_idx].dropna()
    current_atr = df['atr'].iloc[up_to_idx]
    if len(atr_series) == 0 or np.isnan(current_atr):
        return False
    atr_pct     = (atr_series < current_atr).mean() * 100
    window      = df.iloc[up_to_idx - COMP_BARS: up_to_idx]
    bar_range   = window['high'].max() - window['low'].min()
    return (atr_pct <= COMP_PERCENTILE) and (bar_range < current_atr * COMP_RANGE_MULT * COMP_BARS)

def is_time_allowed(ts):
    m = ts.hour * 60 + ts.minute - 570
    return any(s <= m <= e for s, e in TIME_WINDOWS)

def option_pnl(entry, exit_price, direction, hold_minutes):
    u = (exit_price - entry) / entry if direction == 'LONG' else (entry - exit_price) / entry
    return ((u * DELTA) - (THETA_PER_MIN * hold_minutes)) / OPTION_COST_PCT

# =========================
# VOLUME FILTER
# =========================
def volume_ok(df, i):
    vol = df['volume'].iloc[i]

    if VOL_MODE == 'fixed':
        avg = df['vol_avg'].iloc[i]
        return vol > avg * VOL_MULT if avg > 0 else False

    elif VOL_MODE == 'rvol_pct':
        hist = df['volume'].iloc[max(0, i-100): i]
        if len(hist) < 10:
            return False
        return (hist < vol).mean() * 100 >= RVOL_PERCENTILE

    elif VOL_MODE == 'session':
        avg = df['session_vol_avg'].iloc[i]
        return vol > avg * SESSION_MULT if avg > 0 else False

    elif VOL_MODE == 'zscore':
        z = df['vol_zscore'].iloc[i]
        return (not np.isnan(z)) and z > ZSCORE_THRESH

    return False

# =========================
# BREAKOUT DETECTION
# =========================
def detect_breakouts(df, sr_levels, atr, i):
    signals    = []
    current    = df.iloc[-1]
    for lvl in sr_levels:
        vol_pass = volume_ok(df, i)  # uses global df index
        if lvl.level_type == "resistance":
            if (current['close'] > lvl.high + atr * ATR_BREAK_MULT and
                    vol_pass and
                    (current['close'] - current['open']) > atr * ATR_BODY_MULT):
                signals.append({"type": "LONG_BREAKOUT",  "level": lvl})
        elif lvl.level_type == "support":
            if (current['close'] < lvl.low - atr * ATR_BREAK_MULT and
                    vol_pass and
                    (current['open'] - current['close']) > atr * ATR_BODY_MULT):
                signals.append({"type": "SHORT_BREAKDOWN", "level": lvl})
    return signals

# =========================
# BACKTEST
# =========================
def backtest(df):
    df = df.copy()
    df['atr']     = compute_atr(df)
    df['vol_avg'] = df['volume'].rolling(20).mean()
    df['vwap']    = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()

    # Pre-compute session-relative volume avg (expanding mean per minute-of-day)
    df['minute'] = df.index.hour * 60 + df.index.minute
    df['session_vol_avg'] = df.groupby('minute')['volume'].transform(
        lambda x: x.expanding().mean().shift(1)
    ).fillna(df['vol_avg'])

    # Pre-compute rolling z-score
    roll_mean = df['volume'].rolling(100).mean()
    roll_std  = df['volume'].rolling(100).std()
    df['vol_zscore'] = (df['volume'] - roll_mean) / roll_std.replace(0, np.nan)

    trades   = []
    in_trade = False

    for i in range(LOOKBACK_BARS + PIVOT_ORDER, len(df) - TIME_STOP_BARS - 1):
        if in_trade:
            continue
        if TIME_FILTER and not is_time_allowed(df.index[i]):
            continue
        atr = df['atr'].iloc[i]
        if np.isnan(atr) or atr == 0:
            continue
        if not is_compressed(df, i):
            continue

        above_vwap = df['close'].iloc[i] > df['vwap'].iloc[i]

        window        = df.iloc[i - LOOKBACK_BARS: i + 1]
        scored, atr_w = get_sr_levels(window)
        signals       = detect_breakouts(df, scored, atr_w, i)
        if not signals:
            continue

        if VWAP_BIAS:
            signals = [s for s in signals if
                       (s['type'] == 'LONG_BREAKOUT'  and above_vwap) or
                       (s['type'] == 'SHORT_BREAKDOWN' and not above_vwap)]
        if not signals:
            continue

        signals.sort(key=lambda s: s['level'].strength, reverse=True)
        best      = signals[0]
        direction = 'LONG' if best['type'] == 'LONG_BREAKOUT' else 'SHORT'
        lvl       = best['level']

        entry_price = df['close'].iloc[i + 1]
        stop_price  = lvl.low  if direction == 'LONG' else lvl.high
        tp_price    = entry_price + atr * ATR_TP_MULT if direction == 'LONG' else entry_price - atr * ATR_TP_MULT

        in_trade = True

        for j in range(i + 2, min(i + TIME_STOP_BARS + 2, len(df))):
            current      = df['close'].iloc[j]
            hold_minutes = j - (i + 1)
            hit_stop = (direction == 'LONG'  and current <= stop_price) or \
                       (direction == 'SHORT' and current >= stop_price)
            hit_tp   = (direction == 'LONG'  and current >= tp_price)   or \
                       (direction == 'SHORT' and current <= tp_price)
            hit_time = (j == min(i + TIME_STOP_BARS + 1, len(df) - 1))
            if hit_stop or hit_tp or hit_time:
                pnl = option_pnl(entry_price, current, direction, hold_minutes)
                trades.append(pnl)
                in_trade = False
                break

    return trades

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    credentials = get_alpaca_credentials()

    print("Downloading data...")
    dfs = {}
    for sym in SYMBOLS:
        df = fetch_alpaca_bars(sym, START_DATE, END_DATE, TIMEFRAME,
                               api_key=credentials['api_key'],
                               secret_key=credentials['secret_key'])
        if df is not None and not df.empty:
            dfs[sym] = df
            print(f"  {sym}: {len(df)} candles")

    # -- Per-symbol percentile calibration --
    best_pct = {}
    print(f"\n{'='*58}")
    print(f"{'SYMBOL':<6} {'PCT':>5} {'TRADES':>7} {'WR%':>7} {'PF':>6} {'PNL%':>10}")
    print(f"{'='*58}")

    for sym, df in dfs.items():
        candidates = SYMBOL_RVOL_CANDIDATES.get(sym, [65, 70, 75])
        sym_best   = None
        for pct in candidates:
            RVOL_PERCENTILE = pct
            t = backtest(df)
            if not t:
                print(f"{sym:<6} {pct:>5}   {'0':>7}")
                continue
            w   = [p for p in t if p > 0]
            l   = [p for p in t if p <= 0]
            pf  = sum(w) / abs(sum(l)) if l else float('inf')
            wr  = len(w) / len(t) * 100
            tot = sum(t) * 100
            print(f"{sym:<6} {pct:>5} {len(t):>7} {wr:>6.1f}% {pf:>6.2f} {tot:>9.2f}%")
            if sym_best is None or tot > sym_best[1]:
                sym_best = (pct, tot)
        best_pct[sym] = sym_best[0] if sym_best else candidates[-1]
        print(f"  --> Best for {sym}: {best_pct[sym]}th percentile\n")

    # -- Combined run with best per-symbol settings --
    print(f"{'='*58}")
    print(f"COMBINED with per-symbol calibration:")
    print(f"{'='*58}")
    print(f"{'SYMBOL':<6} {'PCT':>5} {'TRADES':>7} {'WR%':>7} {'PF':>6} {'PNL%':>10}")
    print(f"{'-'*58}")
    all_pnls = []
    for sym, df in dfs.items():
        RVOL_PERCENTILE = best_pct[sym]
        t = backtest(df)
        all_pnls.extend(t)
        if not t:
            print(f"{sym:<6} {RVOL_PERCENTILE:>5}   {'0':>7}")
            continue
        w  = [p for p in t if p > 0]
        l  = [p for p in t if p <= 0]
        pf = sum(w) / abs(sum(l)) if l else float('inf')
        print(f"{sym:<6} {RVOL_PERCENTILE:>5} {len(t):>7} {len(w)/len(t)*100:>6.1f}% {pf:>6.2f} {sum(t)*100:>9.2f}%")

    if all_pnls:
        w  = [p for p in all_pnls if p > 0]
        l  = [p for p in all_pnls if p <= 0]
        pf = sum(w) / abs(sum(l)) if l else float('inf')
        print(f"{'='*58}")
        print(f"{'TOTAL':<6} {'':>5} {len(all_pnls):>7} {len(w)/len(all_pnls)*100:>6.1f}% {pf:>6.2f} {sum(all_pnls)*100:>9.2f}%")
        print(f"{'='*58}")
        print(f"\nBest per-symbol percentiles: {best_pct}")
        print("Update SYMBOL_RVOL_PCT in backtest_boof20.py with these values.")
