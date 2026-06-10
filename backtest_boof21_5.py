"""
backtest_boof21_5.py
====================
Boof 21.5 — Volume Cluster S/R with CONFIGURABLE CHOP FILTER
Entry: S/R flip retest — price retests a broken resistance level from above
"""

import numpy as np
import pandas as pd
from datetime import datetime
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from volume_cluster_sr import build_levels, breakout_signals, retest_signals, rejection_signals

# =========================
# CONFIG
# =========================
SYMBOLS      = ["SMCI", "TSLA", "NVDA", "COIN", "PLTR", "AMD", "MRNA", "ENPH", "CCL"]
START_DATE   = datetime(2026, 4, 1)
END_DATE     = datetime(2026, 4, 30)
MAX_TRADES_PER_DAY = 999  # no daily limit
TRADING_DAYS = 21

# MTF mode: 5-min levels + 1-min entries
MTF_MODE       = True   # True = 5-min levels / 1-min entry; False = 1-min only

# Level building params
LOOKBACK       = 39    # bars on level TF (~1 session on 10-min)
VOL_THRESHOLD  = 1.3
CLUSTER_PCT    = 0.2   # $1.40 zone on $700 SPY
LEVEL_REBUILD  = 3     # rebuild every 3 x 10-min bars = 30min
MIN_TOUCHES    = 3
MIN_LEVEL_STR      = 8.0
ALERT_MIN_STRENGTH = 8.0
MAX_LEVEL_STR      = 999.0  # global ceiling (override per-symbol)
RETEST_PCT         = 0.002

# Entry / exit
RVOL_MIN       = 80
ATR_PERIOD     = 14
RETEST_ZONE    = 2.0   # price within N * ATR of level
ATR_TP_MULT    = 3.0
ATR_STOP_MULT  = 1.5
TIME_STOP_BARS = 30

TIME_FILTER  = True
TRADE_START  = (9, 31)
TRADE_END    = (15, 30)
LONGS_ONLY   = True  # global default; overridden per-symbol in SYMBOL_CFG

# Regime filter (Pine: emaFast/emaSlow)
EMA_FAST     = 20
EMA_SLOW     = 50
CHOP_THRESH  = 0.05
SPY_BO_VOL_MULT = 1.4
LEVEL_COOLDOWN_BARS = 15    # Pine: cooldownBars
LEVEL_COOLDOWN_PCT  = 0.0015 # Pine: 0.0015 proximity to failed level

# ── CONFIGURABLE CHOP FILTER ──
USE_CHOP_FILTER = False  # Set to False for Boof 21.5 without chop filter

# ── Per-symbol overrides ─────────────────────────────────────
# Keys match symbol string exactly. Any key not set falls back to globals above.
SYMBOL_CFG = {
    'SPY': {
        'longs_only':     False,
        'cluster_pct':    0.2,
        'retest_pct':     0.002,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'QQQ': {
        'longs_only':     False,
        'cluster_pct':    0.2,
        'retest_pct':     0.002,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.5,
        'allow_reject':   False,
        'allow_breakout': True,
        'rvol_min':       80,
    },
    'TSLA': {
        'longs_only':     False,
        'cluster_pct':    0.4,
        'retest_pct':     0.004,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'NVDA': {
        'longs_only':     False,
        'cluster_pct':    0.4,
        'retest_pct':     0.004,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'AMD': {
        'longs_only':     False,
        'cluster_pct':    0.4,
        'retest_pct':     0.004,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'SMCI': {
        'longs_only':     False,
        'cluster_pct':    0.4,
        'retest_pct':     0.004,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'COIN': {
        'longs_only':     False,
        'cluster_pct':    0.4,
        'retest_pct':     0.004,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'PLTR': {
        'longs_only':     False,
        'cluster_pct':    0.4,
        'retest_pct':     0.004,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'MRNA': {
        'longs_only':     False,
        'cluster_pct':    0.4,
        'retest_pct':     0.004,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'ENPH': {
        'longs_only':     False,
        'cluster_pct':    0.4,
        'retest_pct':     0.004,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'CCL': {
        'longs_only':     False,
        'cluster_pct':    0.4,
        'retest_pct':     0.004,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'AAPL': {
        'longs_only':     False,
        'cluster_pct':    0.3,
        'retest_pct':     0.003,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'AMZN': {
        'longs_only':     False,
        'cluster_pct':    0.3,
        'retest_pct':     0.003,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'META': {
        'longs_only':     False,
        'cluster_pct':    0.4,
        'retest_pct':     0.004,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
    'GOOGL': {
        'longs_only':     False,
        'cluster_pct':    0.3,
        'retest_pct':     0.003,
        'atr_tp_mult':    3.0,
        'atr_stop_mult':  1.8,
        'allow_reject':   False,
        'allow_breakout': False,
        'rvol_min':       80,
    },
}


# =========================
# HELPERS
# =========================
def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def compute_atr(df, period=ATR_PERIOD):
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low']  - df['close'].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(period).mean()

def is_time_allowed(ts):
    t = ts.hour * 60 + ts.minute
    return (TRADE_START[0]*60 + TRADE_START[1]) <= t <= (TRADE_END[0]*60 + TRADE_END[1])

def rvol_pct(df, i, window=100):
    if i < window:
        return 0.0
    return float((df['volume'].iloc[i - window: i] < df['volume'].iloc[i]).mean() * 100)

def underlying_pnl(entry, exit_price, direction):
    if direction == 'LONG':
        return (exit_price - entry) / entry
    return (entry - exit_price) / entry


# Pine alertcondition labels
_ALERT_MAP = {
    ('LONG',  'breakout'):  'LONG BREAKOUT',
    ('SHORT', 'breakout'):  'SHORT BREAKOUT',
    ('LONG',  'retest'):    'LONG RETEST',
    ('SHORT', 'retest'):    'SHORT RETEST',
    ('LONG',  'rejection'): 'LONG REJECTION',
    ('SHORT', 'rejection'): 'SHORT REJECTION',
}

def _alert_label(direction: str, sig_type: str) -> str:
    return _ALERT_MAP.get((direction, sig_type), f'{direction} {sig_type}'.upper())


# =========================
# BACKTEST ENGINE
# =========================
def _resample_tf(df1m, tf='10min'):
    return df1m.resample(tf).agg(
        {'open':'first','high':'max','low':'min','close':'last','volume':'sum'}
    ).dropna()


def backtest(df: pd.DataFrame, symbol: str) -> list:
    df = df.copy()
    df['atr']      = compute_atr(df)
    df['vwap']     = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df['ema_fast'] = compute_ema(df['close'], EMA_FAST)
    df['ema_slow'] = compute_ema(df['close'], EMA_SLOW)
    df['trend']    = df['ema_fast'] - df['ema_slow']

    # ── Per-symbol overrides ──
    cfg            = SYMBOL_CFG.get(symbol.upper(), {})
    sym_longs_only    = cfg.get('longs_only',     LONGS_ONLY)
    sym_cluster_pct   = cfg.get('cluster_pct',    CLUSTER_PCT)
    sym_retest_pct    = cfg.get('retest_pct',     RETEST_PCT)
    sym_tp_mult       = cfg.get('atr_tp_mult',    ATR_TP_MULT)
    sym_stop_mult     = cfg.get('atr_stop_mult',  ATR_STOP_MULT)
    sym_allow_reject  = cfg.get('allow_reject',   True)
    sym_allow_breakout= cfg.get('allow_breakout', True)
    sym_rvol_min      = cfg.get('rvol_min',       RVOL_MIN)
    sym_max_lvl_str   = cfg.get('max_level_str',  MAX_LEVEL_STR)
    sym_time_stop     = cfg.get('time_stop_bars', TIME_STOP_BARS)
    is_spy            = symbol.upper() == 'SPY'

    # MTF: precompute level-TF bars and a fast index lookup
    if MTF_MODE:
        df5m       = _resample_tf(df, '10min')
        df5m_times = df5m.index.tolist()
        import bisect
        def get_5m_idx(ts):
            pos = bisect.bisect_right(df5m_times, ts)
            return pos - 1 if pos > 0 else None

    trades        = []
    in_trade      = False
    trade_exit_i  = -1
    active_levels = []
    last_rebuild  = -1
    trades_today       = 0
    current_date       = None
    last_failed_price  = None   # Pine: lastFailedLevel
    last_failed_bar    = -999   # Pine: lastFailedBar
    MIN_BARS      = (LOOKBACK * 10 + ATR_PERIOD + 5) if MTF_MODE else (LOOKBACK + ATR_PERIOD + 5)

    for i in range(MIN_BARS, len(df) - TIME_STOP_BARS - 1):
        if in_trade or i <= trade_exit_i:
            continue
        bar_date = df.index[i].date()
        if bar_date != current_date:
            current_date = bar_date
            trades_today = 0
        if trades_today >= MAX_TRADES_PER_DAY:
            continue
        if TIME_FILTER and not is_time_allowed(df.index[i]):
            continue

        atr_val = df['atr'].iloc[i]
        if np.isnan(atr_val) or atr_val == 0:
            continue

        # ── Rebuild levels (5-min or 1-min) ──
        if MTF_MODE:
            ts       = df.index[i]
            idx5     = get_5m_idx(ts)
            if idx5 is None or idx5 < LOOKBACK:
                continue
            if idx5 != last_rebuild or not active_levels:
                window5       = df5m.iloc[idx5 - LOOKBACK: idx5 + 1]
                active_levels = build_levels(window5, lookback=LOOKBACK,
                                             vol_threshold=VOL_THRESHOLD,
                                             cluster_pct=sym_cluster_pct)
                last_rebuild  = idx5
        else:
            if i >= last_rebuild + LEVEL_REBUILD or not active_levels:
                active_levels = build_levels(df.iloc[i - LOOKBACK: i + 1],
                                             lookback=LOOKBACK,
                                             vol_threshold=VOL_THRESHOLD,
                                             cluster_pct=sym_cluster_pct)
                last_rebuild = i

        if not active_levels:
            continue

        rv = rvol_pct(df, i)
        if rv < sym_rvol_min:
            continue

        price      = df['close'].iloc[i]
        price_prev = df['close'].iloc[i - 1]
        above_vwap = price > df['vwap'].iloc[i]

        if sym_longs_only and not above_vwap:
            continue

        quality = [l for l in active_levels
                   if l['touches'] >= MIN_TOUCHES
                   and MIN_LEVEL_STR <= l['level_strength'] <= sym_max_lvl_str
                   and not (                              # Pine: levelLocked
                       last_failed_price is not None and
                       abs(l['price'] - last_failed_price) / l['price'] < LEVEL_COOLDOWN_PCT and
                       (i - last_failed_bar) < LEVEL_COOLDOWN_BARS
                   )]
        if not quality:
            continue

        # ── Regime (Pine: emaFast - emaSlow) ──
        trend_val  = df['trend'].iloc[i]
        trend_mode = trend_val > 0
        chop_mode  = abs(trend_val) < CHOP_THRESH

        # ── Step 4 signals ──
        bar        = df.iloc[i]
        avg_vol    = df['volume'].iloc[i-100:i].mean()
        close_prev2 = df['close'].iloc[i - 2] if i >= 2 else None
        bo      = breakout_signals(price_prev, price, bar['volume'],
                                   avg_vol, VOL_THRESHOLD, ALERT_MIN_STRENGTH, quality,
                                   open_now=bar['open'], close_prev2=close_prev2)
        rt      = retest_signals(price, quality, sym_retest_pct)
        rj      = rejection_signals(bar['low'], bar['high'], price, quality)

        # ── CONFIGURABLE CHOP FILTER ──
        if USE_CHOP_FILTER and chop_mode:
            continue

        allow_retest   = True
        allow_breakout = sym_allow_breakout and (trend_mode or not is_spy)
        allow_reject   = sym_allow_reject

        direction  = None
        lvl_used   = None
        sig_type   = None

        if above_vwap or not sym_longs_only:
            if allow_reject and rj['long'] and above_vwap:
                lvl_used, direction, sig_type = rj['long'][0], 'LONG', 'rejection'
            elif rt['long'] and allow_retest and above_vwap:
                lvl_used, direction, sig_type = rt['long'][0], 'LONG', 'retest'
            elif bo['long'] and allow_breakout and above_vwap:
                lvl_used, direction, sig_type = bo['long'][0], 'LONG', 'breakout'

        if not sym_longs_only and direction is None:
            if allow_reject and rj['short'] and not above_vwap:
                lvl_used, direction, sig_type = rj['short'][0], 'SHORT', 'rejection'
            elif rt['short'] and allow_retest and not above_vwap:
                lvl_used, direction, sig_type = rt['short'][0], 'SHORT', 'retest'
            elif bo['short'] and allow_breakout and not above_vwap:
                lvl_used, direction, sig_type = bo['short'][0], 'SHORT', 'breakout'

        if direction is None:
            continue

        entry_price = df['close'].iloc[i + 1]
        stop_price  = entry_price - atr_val * sym_stop_mult if direction == 'LONG' \
                      else entry_price + atr_val * sym_stop_mult
        tp_price    = entry_price + atr_val * sym_tp_mult   if direction == 'LONG' \
                      else entry_price - atr_val * sym_tp_mult

        in_trade = True
        for j in range(i + 2, min(i + sym_time_stop + 2, len(df))):
            current  = df['close'].iloc[j]
            hit_stop = (direction=='LONG' and current<=stop_price) or (direction=='SHORT' and current>=stop_price)
            hit_tp   = (direction=='LONG' and current>=tp_price)   or (direction=='SHORT' and current<=tp_price)
            hit_time = j == min(i + sym_time_stop + 1, len(df) - 1)

            if hit_stop or hit_tp or hit_time:
                trades.append({
                    'symbol':    symbol,
                    'direction': direction,
                    'entry':     round(entry_price, 2),
                    'exit':      round(current, 2),
                    'pnl':       underlying_pnl(entry_price, current, direction),
                    'exit_type': 'stop' if hit_stop else ('tp' if hit_tp else 'time'),
                    'hold_min':  j - (i + 1),
                    'rvol':      round(rv, 1),
                    'level':     round(lvl_used['price'], 2),
                    'touches':   lvl_used['touches'],
                    'lvl_score': round(lvl_used['level_strength'], 1),
                    'sig_type':  sig_type,
                    'alert':     _alert_label(direction, sig_type),
                    'entry_time': df.index[i],
                })
                in_trade     = False
                trade_exit_i = j
                last_rebuild = j
                trades_today += 1
                if hit_stop:
                    level_actually_broken = (
                        (direction == 'LONG'  and current < lvl_used['price']) or
                        (direction == 'SHORT' and current > lvl_used['price'])
                    )
                    if level_actually_broken:
                        last_failed_price = lvl_used['price']
                        last_failed_bar   = i
                break

    return trades


# =========================
# RUN
# =========================
def run():
    creds      = get_alpaca_credentials()
    all_trades = {}
    chop_status = "ON" if USE_CHOP_FILTER else "OFF"

    print(f"\n{'='*16} Boof 21.5 — Chop Filter: {chop_status} {'='*16}")

    for symbol in SYMBOLS:
        print(f"\n{'='*16} {symbol} {'='*16}")
        df = fetch_alpaca_bars(symbol, START_DATE, END_DATE,
                               timeframe='1Min',
                               api_key=creds['api_key'],
                               secret_key=creds['secret_key'])
        if df is None or len(df) < 500:
            print("  insufficient data")
            continue
        print(f"  {len(df)} bars")
        trades = backtest(df, symbol)
        all_trades[symbol] = trades

        if not trades:
            print("  No trades")
            continue

        pnls   = [t['pnl'] for t in trades]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        pf     = sum(wins) / abs(sum(losses)) if losses else float('inf')
        exits  = {}
        for t in trades:
            exits[t['exit_type']] = exits.get(t['exit_type'], 0) + 1
        print(f"  Trades:    {len(trades)}  ({len(trades)/TRADING_DAYS:.1f}/day)")
        print(f"  Win Rate:  {len(wins)/len(pnls)*100:.1f}%")
        if wins and losses:
            print(f"  Avg W/L:   +{np.mean(wins)*100:.2f}% / {np.mean(losses)*100:.2f}%  (underlying)")
        print(f"  PF:        {pf:.2f}")
        print(f"  Total PnL: {sum(pnls)*100:.2f}%  (underlying)")
        alerts = {}
        for t in trades:
            a = t.get('alert', '?')
            alerts[a] = alerts.get(a, 0) + 1
        print(f"  Exits:     {exits}")
        print(f"  Alerts:    {alerts}")

    combined = [t for v in all_trades.values() for t in v]
    if not combined:
        print("\nNo trades.")
        return
    pnls   = [t['pnl'] for t in combined]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    pf     = sum(wins) / abs(sum(losses)) if losses else float('inf')
    print(f"\n{'='*40}")
    print(f"COMBINED — {len(SYMBOLS)} symbols, April 2026 (Chop Filter: {chop_status})")
    print(f"  Trades:    {len(combined)}  ({len(combined)/TRADING_DAYS:.1f}/day)")
    print(f"  Win Rate:  {len(wins)/len(pnls)*100:.1f}%")
    print(f"  PF:        {pf:.2f}")
    if wins and losses:
        print(f"  Avg W/L:   +{np.mean(wins)*100:.2f}% / {np.mean(losses)*100:.2f}%  (underlying)")
    print(f"  Total PnL: {sum(pnls)*100:.2f}%")


if __name__ == "__main__":
    run()
