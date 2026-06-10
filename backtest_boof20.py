import numpy as np
import pandas as pd
from datetime import datetime
from dataclasses import dataclass
from scipy.signal import argrelextrema
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

# =========================
# CONFIG
# =========================
SYMBOLS    = ["SMCI", "TSLA", "NVDA", "COIN", "PLTR", "AMD", "MRNA", "ENPH", "CCL"]  # Top 10 scan list
TIMEFRAME  = "1Min"
START_DATE = datetime(2026, 4, 1)
END_DATE   = datetime(2026, 4, 30)

LOOKBACK_BARS  = 120   # rolling window to build S/R levels
PIVOT_ORDER    = 5     # bars each side for pivot extrema
ATR_TOLERANCE  = 0.25  # cluster within ATR * 0.25  [PROVEN CRITICAL]
MIN_TOUCHES    = 2

ATR_BREAK_MULT = 0.1   # close must exceed zone by ATR*0.1
ATR_BODY_MULT  = 0.3   # candle body must be > ATR*0.3  [PROVEN: -93% without]

# 2-Tier per-symbol RVOL thresholds
# Tier 1 = base signal, Tier 2 = high conviction (tighter filters)
SYMBOL_RVOL = {
    #         T1    T2
    'SPY':  ( 70,   85),
    'QQQ':  ( 70,   85),
    'TSLA': ( 65,   82),
    'AMD':  ( 60,   80),
    # scan list — high-beta, lower threshold
    'RIVN': ( 60,   78),
    'AMC':  ( 60,   78),
    'SOFI': ( 60,   78),
    'NIO':  ( 60,   78),
    'XPEV': ( 60,   78),
    'GME':  ( 60,   78),
    'HOOD': ( 60,   78),
    'PLUG': ( 60,   78),
    'LCID': ( 60,   78),
}
RVOL_DEFAULT = (60, 78)  # fallback for unlisted symbols

# Per-symbol stop: ATR-based multiplier (float) or level-based (None)
# SPY/QQQ: level stop too wide vs ATR — use tight ATR stop
SYMBOL_STOP_MULT = {
    'SPY': 1.0,
    'QQQ': 1.0,
}

# Symbols restricted to Tier-1 only (Tier-2 vol spikes hurt ETFs)
TIER1_ONLY = {'SPY', 'QQQ'}

# Tier 2 extras: z-score spike OR range expansion required
T2_ZSCORE_THRESH  = 1.5   # volume z-score for tier-2 confirmation
T2_RANGE_EXPAND   = 1.5   # current bar range > ATR * this for tier-2

COMP_BARS       = 20   # bars to measure compression over
COMP_PERCENTILE = 40   # ATR must be in bottom N% of its 100-bar history
COMP_RANGE_MULT = 0.8  # high-low range of window must be < ATR * N

VWAP_BIAS       = True # only LONG above VWAP, SHORT below VWAP

# =========================
# REGIME FILTER
# =========================
# Regime is computed per-bar from the symbol's own price data.
# TRENDING  : EMA20 slope positive + price above EMA50  → favor longs
# BEARISH   : EMA20 slope negative + price below EMA50  → favor shorts
# CHOPPY    : ATR percentile > 80 (too noisy) OR EMA slope flat → skip
REGIME_FILTER    = True
REGIME_EMA_FAST  = 20    # fast EMA for slope
REGIME_EMA_SLOW  = 50    # slow EMA for trend bias
REGIME_SLOPE_MIN = 0.00002 # min abs EMA slope (as % of price) to confirm trend on 1-min bars
REGIME_ATR_MAX   = 90    # skip if ATR percentile above this (too volatile/choppy)

ATR_TP_MULT    = 2.0   # tp = entry ± ATR*2.0 (used when EXIT_MODE='atr')
TIME_STOP_BARS = 30

EXIT_MODE      = 'atr'   # PROVEN BEST — ATR-based TP

OPTION_COST_PCT = 0.004
DELTA           = 0.50
THETA_PER_MIN   = OPTION_COST_PCT * (0.50 / 390)

TIME_FILTER  = True
TIME_WINDOWS = [(5, 120), (300, 450)]

# =========================
# LEVEL DATA CLASS
# =========================
@dataclass
class SRLevel:
    low: float; high: float; touches: int; volume: float
    strength: float; level_type: str; classification: str

# =========================
# ATR
# =========================
def compute_atr(df, period=14):
    hl = df['high'] - df['low']
    hc = np.abs(df['high'] - df['close'].shift())
    lc = np.abs(df['low']  - df['close'].shift())
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(period).mean()

# =========================
# PIVOT DETECTION
# =========================
def detect_pivots(df, order=PIVOT_ORDER):
    highs = df.iloc[argrelextrema(df['high'].values, np.greater_equal, order=order)[0]]
    lows  = df.iloc[argrelextrema(df['low'].values,  np.less_equal,    order=order)[0]]
    return highs, lows

# =========================
# S/R PIPELINE
# =========================
def get_sr_levels(df):
    highs, lows = detect_pivots(df)
    atr = compute_atr(df).iloc[-1]
    avg_vol = df['volume'].mean()

    raw = []
    for _, row in highs.iterrows():
        raw.append({"price": row['high'], "type": "resistance"})
    for _, row in lows.iterrows():
        raw.append({"price": row['low'],  "type": "support"})

    # Cluster nearby levels into zones
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

    # Score zones
    scored = []
    for zone in clustered:
        if zone['touches'] < MIN_TOUCHES:
            continue
        mid          = (zone['low'] + zone['high']) / 2
        touch_score  = np.log1p(zone['touches']) * 20
        nearby       = df[(df['low'] <= mid) & (df['high'] >= mid)]
        vol_score    = (nearby['volume'].mean() / avg_vol) * 30 if len(nearby) else 0
        age_score    = min(zone['touches'] * 5, 20)
        strength     = touch_score + vol_score + age_score
        scored.append(SRLevel(
            low=zone['low'], high=zone['high'], touches=zone['touches'],
            volume=nearby['volume'].sum() if len(nearby) else 0,
            strength=strength, level_type=zone['type'],
            classification="major" if strength >= 50 else "minor"
        ))
    return scored, atr

# =========================
# REGIME DETECTION
# =========================
def detect_regime(df, i):
    """
    Returns: 'trending_up' | 'trending_down' | 'choppy'
    Uses pre-computed EMA columns for speed.
    """
    if i < REGIME_EMA_SLOW + 10:
        return 'choppy'

    price   = df['close'].iloc[i]
    ef_now  = df['ema_fast'].iloc[i]
    ef_prev = df['ema_fast'].iloc[i - 5]
    es_now  = df['ema_slow'].iloc[i]
    atr_pct = df['atr_pct'].iloc[i]

    if np.isnan(ef_now) or np.isnan(es_now):
        return 'choppy'

    # Skip if ATR percentile too high (chaotic market)
    if not np.isnan(atr_pct) and atr_pct > REGIME_ATR_MAX:
        return 'choppy'

    slope = (ef_now - ef_prev) / (price * 5) if price > 0 else 0
    if abs(slope) < REGIME_SLOPE_MIN:
        return 'choppy'

    if slope > 0 and price > es_now:
        return 'trending_up'
    if slope < 0 and price < es_now:
        return 'trending_down'
    return 'choppy'

# =========================
# COMPRESSION FILTER
# =========================
def is_compressed(df, up_to_idx):
    """True if price is in a squeeze before the breakout bar."""
    if up_to_idx < 100:
        return False

    # ATR percentile: current ATR vs last 100 bars
    atr_series  = df['atr'].iloc[up_to_idx - 100: up_to_idx].dropna()
    current_atr = df['atr'].iloc[up_to_idx]
    if len(atr_series) == 0 or np.isnan(current_atr):
        return False
    atr_pct = (atr_series < current_atr).mean() * 100  # percentile rank
    atr_low = atr_pct <= COMP_PERCENTILE

    # Range contraction: high-low range of last COMP_BARS < ATR * mult
    window    = df.iloc[up_to_idx - COMP_BARS: up_to_idx]
    bar_range = window['high'].max() - window['low'].min()
    range_tight = bar_range < current_atr * COMP_RANGE_MULT * COMP_BARS

    return atr_low and range_tight

# =========================
# RVOL TIER CHECK
# =========================
def rvol_tier(df, i, symbol):
    """Returns 0 (no signal), 1 (tier-1), or 2 (tier-2 high conviction)."""
    t1, t2   = SYMBOL_RVOL.get(symbol, RVOL_DEFAULT)
    rvol_pct = df['rvol_pct'].iloc[i]
    if np.isnan(rvol_pct) or rvol_pct < t1:
        return 0
    if symbol in TIER1_ONLY:
        return 1  # ETFs: never escalate to tier-2
    if rvol_pct >= t2:
        zscore    = df['vol_zscore'].iloc[i]
        bar_range = df['high'].iloc[i] - df['low'].iloc[i]
        atr_val   = df['atr'].iloc[i]
        z_ok      = (not np.isnan(zscore)) and zscore >= T2_ZSCORE_THRESH
        range_ok  = (not np.isnan(atr_val)) and bar_range > atr_val * T2_RANGE_EXPAND
        return 2 if (z_ok or range_ok) else 1
    return 1

# =========================
# BREAKOUT DETECTION
# =========================
def detect_breakouts(df, sr_levels, atr, tier):
    signals = []
    current = df.iloc[-1]
    for lvl in sr_levels:
        if lvl.level_type == "resistance":
            if (current['close'] > lvl.high + atr * ATR_BREAK_MULT and
                    (current['close'] - current['open']) > atr * ATR_BODY_MULT):
                signals.append({"type": "LONG_BREAKOUT",  "level": lvl, "tier": tier})
        elif lvl.level_type == "support":
            if (current['close'] < lvl.low - atr * ATR_BREAK_MULT and
                    (current['open'] - current['close']) > atr * ATR_BODY_MULT):
                signals.append({"type": "SHORT_BREAKDOWN", "level": lvl, "tier": tier})
    return signals

# =========================
# TIME FILTER
# =========================
def is_time_allowed(ts):
    m = ts.hour * 60 + ts.minute - 570
    return any(s <= m <= e for s, e in TIME_WINDOWS)

# =========================
# 0DTE OPTIONS PnL
# =========================
def option_pnl(entry, exit_price, direction, hold_minutes):
    u = (exit_price - entry) / entry if direction == 'LONG' else (entry - exit_price) / entry
    return ((u * DELTA) - (THETA_PER_MIN * hold_minutes)) / OPTION_COST_PCT

# =========================
# BACKTEST ENGINE
# =========================
def backtest(df, symbol=''):
    df = df.copy()
    df['atr']      = compute_atr(df)
    df['vol_avg']  = df['volume'].rolling(20).mean()
    df['vwap']     = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    # Pre-compute RVOL percentile rank and z-score
    df['rvol_pct']  = df['volume'].rolling(100).rank(pct=True) * 100
    roll_mean       = df['volume'].rolling(100).mean()
    roll_std        = df['volume'].rolling(100).std().replace(0, np.nan)
    df['vol_zscore'] = (df['volume'] - roll_mean) / roll_std
    # Pre-compute regime EMAs
    df['ema_fast'] = df['close'].ewm(span=REGIME_EMA_FAST, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=REGIME_EMA_SLOW, adjust=False).mean()
    df['atr_pct']  = df['atr'].rolling(100).rank(pct=True) * 100

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

        tier = rvol_tier(df, i, symbol)
        if tier == 0:
            continue

        # Regime filter — skip choppy bars, align direction with trend
        if REGIME_FILTER:
            regime = detect_regime(df, i)
            if regime == 'choppy':
                continue
        else:
            regime = None

        above_vwap = df['close'].iloc[i] > df['vwap'].iloc[i]

        window          = df.iloc[i - LOOKBACK_BARS: i + 1]
        scored, atr_w   = get_sr_levels(window)
        signals         = detect_breakouts(window, scored, atr_w, tier)
        if not signals:
            continue

        # VWAP bias: only keep signals aligned with VWAP direction
        if VWAP_BIAS:
            signals = [s for s in signals if
                       (s['type'] == 'LONG_BREAKOUT'  and above_vwap) or
                       (s['type'] == 'SHORT_BREAKDOWN' and not above_vwap)]
        if not signals:
            continue

        # Regime alignment: trending_up → longs only, trending_down → shorts only
        if REGIME_FILTER and regime is not None:
            signals = [s for s in signals if
                       (regime == 'trending_up'   and s['type'] == 'LONG_BREAKOUT') or
                       (regime == 'trending_down' and s['type'] == 'SHORT_BREAKDOWN')]
        if not signals:
            continue

        signals.sort(key=lambda s: s['level'].strength, reverse=True)
        best      = signals[0]
        direction = 'LONG' if best['type'] == 'LONG_BREAKOUT' else 'SHORT'
        lvl       = best['level']

        entry_price = df['close'].iloc[i + 1]
        stop_mult   = SYMBOL_STOP_MULT.get(symbol, None)
        if stop_mult is not None:
            stop_price = entry_price - atr * stop_mult if direction == 'LONG' else entry_price + atr * stop_mult
        else:
            stop_price = lvl.low if direction == 'LONG' else lvl.high
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
                trades.append({
                    'pnl':    pnl,
                    'class':  lvl.classification,
                    'exit':   'stop' if hit_stop else ('tp' if hit_tp else 'time'),
                    'hold':   hold_minutes,
                    'tier':   best['tier'],
                    'regime': regime,
                })
                in_trade = False
                break

    return trades

# =========================
# RUN
# =========================
def run():
    credentials = get_alpaca_credentials()
    all_trades  = {}

    for symbol in SYMBOLS:
        print(f"\n================ {symbol} ================")
        df = fetch_alpaca_bars(symbol, START_DATE, END_DATE, TIMEFRAME,
                               api_key=credentials['api_key'],
                               secret_key=credentials['secret_key'])
        if df is None or df.empty:
            print("No data")
            continue

        print(f"Downloaded {len(df)} candles")
        trades = backtest(df, symbol)
        if not trades:
            print("No trades")
            continue

        pnls   = [t['pnl'] for t in trades]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        pf     = sum(wins) / abs(sum(losses)) if losses else float('inf')
        exits  = {}
        for t in trades:
            exits[t['exit']] = exits.get(t['exit'], 0) + 1

        print(f"Trades:        {len(trades)}")
        print(f"Win Rate:      {len(wins)/len(pnls)*100:.2f}%")
        if wins and losses:
            print(f"Avg Winner:    {np.mean(wins)*100:.2f}%  |  Avg Loser: {np.mean(losses)*100:.2f}%")
        print(f"Profit Factor: {pf:.2f}")
        print(f"Total PnL:     {sum(pnls)*100:.2f}%")
        print(f"Exits:         {exits}")

        def sub(label, subset):
            if not subset: return
            sp = [t['pnl'] for t in subset]
            wr = sum(1 for p in sp if p > 0) / len(sp)
            print(f"  {label} ({len(subset)}): WR {wr*100:.1f}%  PnL {sum(sp)*100:.2f}%")

        sub("Major",  [t for t in trades if t['class'] == 'major'])
        sub("Minor",  [t for t in trades if t['class'] == 'minor'])
        sub("Tier-1", [t for t in trades if t['tier'] == 1])
        sub("Tier-2", [t for t in trades if t['tier'] == 2])
        sub("Trend↑", [t for t in trades if t['regime'] == 'trending_up'])
        sub("Trend↓", [t for t in trades if t['regime'] == 'trending_down'])
        all_trades[symbol] = trades

    combined = [t for v in all_trades.values() for t in v]
    if combined:
        pnls   = [t['pnl'] for t in combined]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        pf     = sum(wins) / abs(sum(losses)) if losses else float('inf')
        print(f"\n================ SUMMARY ================")
        print(f"Total Trades:  {len(combined)}")
        print(f"Win Rate:      {len(wins)/len(pnls)*100:.2f}%")
        print(f"Profit Factor: {pf:.2f}")
        print(f"Total PnL:     {sum(pnls)*100:.2f}%")

if __name__ == "__main__":
    run()
