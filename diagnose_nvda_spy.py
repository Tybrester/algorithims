"""
Diagnose NVDA and SPY — why avg loser >> avg winner
Tests: varying ATR_TP_MULT and ATR_STOP_MULT per symbol
"""
import numpy as np
import pandas as pd
from datetime import datetime
from dataclasses import dataclass
from scipy.signal import argrelextrema
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

# ── shared config ──────────────────────────────────────────
SYMBOLS        = ["SPY", "NVDA"]
TIMEFRAME      = "1Min"
START_DATE     = datetime(2026, 4, 1)
END_DATE       = datetime(2026, 4, 30)
LOOKBACK_BARS  = 120
PIVOT_ORDER    = 5
ATR_TOLERANCE  = 0.25
MIN_TOUCHES    = 2
ATR_BREAK_MULT = 0.1
ATR_BODY_MULT  = 0.3
COMP_BARS      = 20
COMP_PERCENTILE= 40
COMP_RANGE_MULT= 0.8
VWAP_BIAS      = True
TIME_STOP_BARS = 30
OPTION_COST_PCT= 0.004
DELTA          = 0.50
THETA_PER_MIN  = OPTION_COST_PCT * (0.50 / 390)
TIME_FILTER    = True
TIME_WINDOWS   = [(5, 120), (300, 450)]
SYMBOL_RVOL    = {'SPY': (70,85), 'QQQ': (70,85), 'TSLA': (65,82), 'NVDA': (65,82), 'AMD': (60,80)}
RVOL_DEFAULT   = (65, 82)
T2_ZSCORE_THRESH = 1.5
T2_RANGE_EXPAND  = 1.5

# ── sweep params (varied per test) ─────────────────────────
ATR_TP_MULT   = 2.0
ATR_STOP_MULT = None   # None = use level stop; float = ATR-based hard stop

@dataclass
class SRLevel:
    low: float; high: float; touches: int; volume: float
    strength: float; level_type: str; classification: str

def compute_atr(df, period=14):
    hl = df['high'] - df['low']
    hc = np.abs(df['high'] - df['close'].shift())
    lc = np.abs(df['low']  - df['close'].shift())
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(period).mean()

def detect_pivots(df):
    highs = df.iloc[argrelextrema(df['high'].values, np.greater_equal, order=PIVOT_ORDER)[0]]
    lows  = df.iloc[argrelextrema(df['low'].values,  np.less_equal,    order=PIVOT_ORDER)[0]]
    return highs, lows

def get_sr_levels(df):
    highs, lows = detect_pivots(df)
    atr = compute_atr(df).iloc[-1]
    avg_vol = df['volume'].mean()
    raw = []
    for _, row in highs.iterrows():
        raw.append({"price": row['high'], "type": "resistance"})
    for _, row in lows.iterrows():
        raw.append({"price": row['low'], "type": "support"})
    clustered = []
    for lvl in sorted(raw, key=lambda x: x['price']):
        merged = False
        for zone in clustered:
            zone_mid = (zone['low'] + zone['high']) / 2
            if abs(lvl['price'] - zone_mid) < atr * ATR_TOLERANCE:
                zone['low']     = min(zone['low'],  lvl['price'])
                zone['high']    = max(zone['high'], lvl['price'])
                zone['touches'] += 1
                merged = True; break
        if not merged:
            clustered.append({"low": lvl['price'], "high": lvl['price'], "touches": 1, "type": lvl['type']})
    scored = []
    for zone in clustered:
        if zone['touches'] < MIN_TOUCHES: continue
        mid = (zone['low'] + zone['high']) / 2
        touch_score = np.log1p(zone['touches']) * 20
        nearby = df[(df['low'] <= mid) & (df['high'] >= mid)]
        vol_score = (nearby['volume'].mean() / avg_vol) * 30 if len(nearby) else 0
        strength = touch_score + vol_score + min(zone['touches']*5, 20)
        scored.append(SRLevel(zone['low'], zone['high'], zone['touches'],
                               nearby['volume'].sum() if len(nearby) else 0,
                               strength, zone['type'],
                               "major" if strength >= 50 else "minor"))
    return scored, atr

def is_compressed(df, i):
    if i < 100: return False
    atr_series  = df['atr'].iloc[i-100:i].dropna()
    current_atr = df['atr'].iloc[i]
    if len(atr_series) == 0 or np.isnan(current_atr): return False
    atr_pct   = (atr_series < current_atr).mean() * 100
    window    = df.iloc[i-COMP_BARS:i]
    bar_range = window['high'].max() - window['low'].min()
    return (atr_pct <= COMP_PERCENTILE) and (bar_range < current_atr * COMP_RANGE_MULT * COMP_BARS)

def rvol_tier(df, i, symbol):
    t1, t2   = SYMBOL_RVOL.get(symbol, RVOL_DEFAULT)
    rvol_pct = df['rvol_pct'].iloc[i]
    if np.isnan(rvol_pct) or rvol_pct < t1: return 0
    if rvol_pct >= t2:
        z_ok     = (not np.isnan(df['vol_zscore'].iloc[i])) and df['vol_zscore'].iloc[i] >= T2_ZSCORE_THRESH
        range_ok = (df['high'].iloc[i] - df['low'].iloc[i]) > df['atr'].iloc[i] * T2_RANGE_EXPAND
        return 2 if (z_ok or range_ok) else 1
    return 1

def is_time_allowed(ts):
    m = ts.hour * 60 + ts.minute - 570
    return any(s <= m <= e for s, e in TIME_WINDOWS)

def option_pnl(entry, exit_price, direction, hold_minutes):
    u = (exit_price - entry) / entry if direction == 'LONG' else (entry - exit_price) / entry
    return ((u * DELTA) - (THETA_PER_MIN * hold_minutes)) / OPTION_COST_PCT

def backtest(df, symbol, tp_mult, stop_mult):
    df = df.copy()
    df['atr']       = compute_atr(df)
    df['vol_avg']   = df['volume'].rolling(20).mean()
    df['vwap']      = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df['rvol_pct']  = df['volume'].rolling(100).rank(pct=True) * 100
    roll_std        = df['volume'].rolling(100).std().replace(0, np.nan)
    df['vol_zscore'] = (df['volume'] - df['volume'].rolling(100).mean()) / roll_std

    trades, in_trade = [], False

    for i in range(LOOKBACK_BARS + PIVOT_ORDER, len(df) - TIME_STOP_BARS - 1):
        if in_trade: continue
        if TIME_FILTER and not is_time_allowed(df.index[i]): continue
        atr = df['atr'].iloc[i]
        if np.isnan(atr) or atr == 0: continue
        if not is_compressed(df, i): continue
        tier = rvol_tier(df, i, symbol)
        if tier == 0: continue

        above_vwap    = df['close'].iloc[i] > df['vwap'].iloc[i]
        window        = df.iloc[i - LOOKBACK_BARS: i + 1]
        scored, atr_w = get_sr_levels(window)

        signals = []
        current = window.iloc[-1]
        for lvl in scored:
            if lvl.level_type == "resistance":
                if (current['close'] > lvl.high + atr_w * ATR_BREAK_MULT and
                        (current['close'] - current['open']) > atr_w * ATR_BODY_MULT):
                    signals.append({"type": "LONG_BREAKOUT",  "level": lvl, "tier": tier})
            elif lvl.level_type == "support":
                if (current['close'] < lvl.low - atr_w * ATR_BREAK_MULT and
                        (current['open'] - current['close']) > atr_w * ATR_BODY_MULT):
                    signals.append({"type": "SHORT_BREAKDOWN", "level": lvl, "tier": tier})

        if VWAP_BIAS:
            signals = [s for s in signals if
                       (s['type'] == 'LONG_BREAKOUT'  and above_vwap) or
                       (s['type'] == 'SHORT_BREAKDOWN' and not above_vwap)]
        if not signals: continue

        signals.sort(key=lambda s: s['level'].strength, reverse=True)
        best      = signals[0]
        direction = 'LONG' if best['type'] == 'LONG_BREAKOUT' else 'SHORT'
        lvl       = best['level']

        entry_price = df['close'].iloc[i + 1]
        tp_price    = entry_price + atr * tp_mult if direction == 'LONG' else entry_price - atr * tp_mult

        # Stop: ATR-based if stop_mult given, else level-based
        if stop_mult is not None:
            stop_price = entry_price - atr * stop_mult if direction == 'LONG' else entry_price + atr * stop_mult
        else:
            stop_price = lvl.low if direction == 'LONG' else lvl.high

        in_trade = True
        for j in range(i + 2, min(i + TIME_STOP_BARS + 2, len(df))):
            current      = df['close'].iloc[j]
            hold_minutes = j - (i + 1)
            hit_stop = (direction == 'LONG' and current <= stop_price) or (direction == 'SHORT' and current >= stop_price)
            hit_tp   = (direction == 'LONG' and current >= tp_price)   or (direction == 'SHORT' and current <= tp_price)
            hit_time = j == min(i + TIME_STOP_BARS + 1, len(df) - 1)
            if hit_stop or hit_tp or hit_time:
                pnl = option_pnl(entry_price, current, direction, hold_minutes)
                trades.append({'pnl': pnl, 'exit': 'stop' if hit_stop else ('tp' if hit_tp else 'time')})
                in_trade = False
                break

    return trades

# ── main ───────────────────────────────────────────────────
if __name__ == "__main__":
    creds = get_alpaca_credentials()
    dfs   = {}
    for sym in SYMBOLS:
        df = fetch_alpaca_bars(sym, START_DATE, END_DATE, TIMEFRAME,
                               api_key=creds['api_key'], secret_key=creds['secret_key'])
        if df is not None and not df.empty:
            dfs[sym] = df
            print(f"Downloaded {sym}: {len(df)} candles")

    # Test matrix: (label, tp_mult, stop_mult)
    tests = [
        ("TP×2.0 level-stop",  2.0, None),
        ("TP×2.0 stop×0.5",    2.0, 0.5),
        ("TP×2.0 stop×1.0",    2.0, 1.0),
        ("TP×3.0 stop×1.0",    3.0, 1.0),
        ("TP×3.0 stop×1.5",    3.0, 1.5),
        ("TP×4.0 stop×1.0",    4.0, 1.0),
        ("TP×4.0 stop×1.5",    4.0, 1.5),
        ("TP×2.0 stop×1.5",    2.0, 1.5),
    ]

    for sym, df in dfs.items():
        print(f"\n{'='*62}")
        print(f"  {sym}")
        print(f"{'='*62}")
        print(f"  {'CONFIG':<22} {'T':>5} {'WR%':>6} {'PF':>6} {'PNL%':>9} {'W%':>7} {'L%':>7}")
        print(f"  {'-'*60}")
        for label, tp_m, st_m in tests:
            t = backtest(df, sym, tp_m, st_m)
            if not t:
                print(f"  {label:<22}  no trades"); continue
            pnls = [x['pnl'] for x in t]
            wins = [p for p in pnls if p > 0]
            loss = [p for p in pnls if p <= 0]
            pf   = sum(wins)/abs(sum(loss)) if loss else float('inf')
            wr   = len(wins)/len(pnls)*100
            avgw = np.mean(wins)*100 if wins else 0
            avgl = np.mean(loss)*100 if loss else 0
            print(f"  {label:<22} {len(t):>5} {wr:>5.1f}% {pf:>6.2f} {sum(pnls)*100:>8.1f}%  {avgw:>5.1f}%  {avgl:>5.1f}%")
