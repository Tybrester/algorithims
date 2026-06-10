"""
Dual-Timeframe Backtest: 30-min Signal + 1-min Entry
======================================================
Signal detection (fractals, SR clusters, ZigZag) on 30m bars.
Entry execution and TP/SL tracking on 1m bars.

Covers Boof 22.0 and Boof 23.0 on the standard BOOFINGTON symbols.
Period: Jan 2025 – May 2026 (17 months).
"""

import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')

import pandas as pd
import numpy as np
from datetime import datetime
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from backtest_boof22 import compute_atr, build_cluster_array, nearest_sr_distance
from backtest_boof23 import (
    compute_atr as compute_atr23,
    build_cluster_array as build_cluster_array23,
    nearest_sr_distance as nearest_sr_distance23,
    _build_zigzag,
    SYMBOL_PARAMS as PARAMS23,
    DEFAULT_PARAMS as DEF23,
)

# ─────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────
SYMBOLS   = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']

# Options model
TRADE_CORE     = 600   # core tier (slack >= 1.4)
TRADE_EXP      = 200   # expanded tier
TP_OPT         =  0.40
SL_OPT         = -0.15

# Underlying move thresholds that correspond to the options TP/SL
# Using conservative delta-0.5 model same as existing backtests
STOCK_TP_PCT   =  0.007   # ~+40% option TP
STOCK_SL_PCT   = -0.002   # ~-15% option SL

MAX_HOLD_1M    = 30   # bars (30 × 1m = 30 min max hold on 1m chart)

ATR_LEN        = 14
VOL_LEN        = 50
FRACTAL_BARS   = 3
ADX_LEN        = 14
ADX_CHOP_TH    = 10
PROX_BARS      = 30   # boof23 ZZ proximity

SYMBOL_PARAMS_22 = {
    'NVDA': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'META': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'AAPL': {'atr_mult': 0.6, 'vol_mult': 1.2, 'sr_dist': 1.0},
    'GOOGL':{'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'AMD':  {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
}
DEFAULT_22 = {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0}

months = [
    ('Jan 25', datetime(2025,1,1),  datetime(2025,1,31),  23),
    ('Feb 25', datetime(2025,2,1),  datetime(2025,2,28),  20),
    ('Mar 25', datetime(2025,3,1),  datetime(2025,3,31),  21),
    ('Apr 25', datetime(2025,4,1),  datetime(2025,4,30),  22),
    ('May 25', datetime(2025,5,1),  datetime(2025,5,31),  21),
    ('Jun 25', datetime(2025,6,1),  datetime(2025,6,30),  21),
    ('Jul 25', datetime(2025,7,1),  datetime(2025,7,31),  23),
    ('Aug 25', datetime(2025,8,1),  datetime(2025,8,31),  21),
    ('Sep 25', datetime(2025,9,1),  datetime(2025,9,30),  22),
    ('Oct 25', datetime(2025,10,1), datetime(2025,10,31), 23),
    ('Nov 25', datetime(2025,11,1), datetime(2025,11,30), 20),
    ('Dec 25', datetime(2025,12,1), datetime(2025,12,31), 23),
    ('Jan 26', datetime(2026,1,1),  datetime(2026,1,31),  21),
    ('Feb 26', datetime(2026,2,1),  datetime(2026,2,28),  20),
    ('Mar 26', datetime(2026,3,1),  datetime(2026,3,31),  21),
    ('Apr 26', datetime(2026,4,1),  datetime(2026,4,30),  22),
    ('May 26', datetime(2026,5,1),  datetime(2026,5,31),  21),
]


# ─────────────────────────────────────────────────────────────────
# ADX helper (same as boof22_v2.ts)
# ─────────────────────────────────────────────────────────────────
def compute_adx(df, period=ADX_LEN):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    plus_dm  = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm  = plus_dm.where( (plus_dm  > minus_dm) & (plus_dm  > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm)  & (minus_dm > 0), 0)
    atr_s    = tr.ewm(span=period, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, np.nan)
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(span=period, adjust=False).mean().fillna(0)


# ─────────────────────────────────────────────────────────────────
# 1-min exit simulation
# ─────────────────────────────────────────────────────────────────
def simulate_exit_1m(df_1m, signal_time, direction, tp_pct, sl_pct, max_hold=MAX_HOLD_1M):
    """
    Given a signal fired at `signal_time` on 30m chart,
    enter on the next available 1m bar open after that time.
    Track TP/SL/time exit on 1m bars.
    Returns (exit_type, pnl_pct, bars_held) or None if no entry found.
    """
    # Find first 1m bar that opens AFTER the signal time
    future = df_1m[df_1m['time'] > signal_time]
    if future.empty:
        return None

    entry_idx = future.index[0]
    entry_price = df_1m.loc[entry_idx, 'open']
    if entry_price <= 0:
        return None

    tp_price = entry_price * (1 + tp_pct) if direction == 'long' else entry_price * (1 - abs(tp_pct))
    sl_price = entry_price * (1 - abs(sl_pct)) if direction == 'long' else entry_price * (1 + abs(sl_pct))

    loc_pos = df_1m.index.get_loc(entry_idx)
    end_pos  = min(loc_pos + max_hold, len(df_1m) - 1)

    for j in range(loc_pos + 1, end_pos + 1):
        row = df_1m.iloc[j]
        h, l = row['high'], row['low']
        if direction == 'long':
            if h >= tp_price:
                return 'tp', tp_pct, j - loc_pos
            if l <= sl_price:
                return 'sl', sl_pct, j - loc_pos
        else:
            if l <= tp_price:
                return 'tp', tp_pct, j - loc_pos
            if h >= sl_price:
                return 'sl', sl_pct, j - loc_pos

    # Time exit
    close_price = df_1m.iloc[end_pos]['close']
    time_pnl = (close_price - entry_price) / entry_price
    if direction == 'short':
        time_pnl = -time_pnl
    return 'time', time_pnl, end_pos - loc_pos


# ─────────────────────────────────────────────────────────────────
# SIGNAL GENERATORS (30m)
# ─────────────────────────────────────────────────────────────────

def get_boof22_signals_30m(df_30m, symbol):
    """Scan 30m dataframe for Boof 22.0 signals. Returns list of (time, direction, slack)."""
    params   = SYMBOL_PARAMS_22.get(symbol, DEFAULT_22)
    atr_mult = params['atr_mult']
    vol_mult = params['vol_mult']
    sr_dist  = params['sr_dist']

    df = df_30m.copy().reset_index(drop=True)
    if len(df) < max(ATR_LEN, VOL_LEN, FRACTAL_BARS * 2) + 10:
        return []

    atr_series    = compute_atr(df)
    df['atr']     = atr_series
    df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
    df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult

    cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult)

    F       = FRACTAL_BARS
    signals = []

    for i in range(VOL_LEN + ATR_LEN + F, len(df) - F - 1):
        row = df.iloc[i]
        if row['rvol'] < 80 or not row['hi_vol']:
            continue
        atr = row['atr']
        if pd.isna(atr) or atr == 0:
            continue

        highs  = df['high'].values
        lows   = df['low'].values
        closes = df['close'].values

        fp = (highs[i] > highs[i-F:i].max()) and (highs[i] > highs[i+1:i+F+1].max())
        ft = (lows[i]  < lows[i-F:i].min())  and (lows[i]  < lows[i+1:i+F+1].min())
        ar = closes[i] < highs[i] - atr * atr_mult
        ab = closes[i] > lows[i]  + atr * atr_mult

        if nearest_sr_distance(row['close'], cluster_prices, atr) > sr_dist:
            continue

        if fp and ar:
            peak_slack = (highs[i] - closes[i]) / atr
            signals.append((df.iloc[i]['time'], 'short', peak_slack))
        elif ft and ab:
            trough_slack = (closes[i] - lows[i]) / atr
            signals.append((df.iloc[i]['time'], 'long', trough_slack))

    return signals


def get_boof23_signals_30m(df_30m, symbol):
    """Scan 30m dataframe for Boof 23.0 signals. Returns list of (time, direction, slack)."""
    params   = PARAMS23.get(symbol, DEF23)
    atr_mult = params['atr_mult']
    vol_mult = params['vol_mult']
    sr_dist  = params['sr_dist']

    df = df_30m.copy().reset_index(drop=True)
    if len(df) < max(ATR_LEN, VOL_LEN, FRACTAL_BARS * 2) + 50:
        return []

    atr_series    = compute_atr23(df)
    df['atr']     = atr_series
    df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
    df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult

    cluster_prices, _ = build_cluster_array23(df, atr_series, vol_mult)

    # Run ZigZag engine
    opens  = df['open'].values
    highs  = df['high'].values
    lows   = df['low'].values
    closes = df['close'].values
    atrs   = df['atr'].values

    trend_arr, zz_high, zz_high_bar, zz_low, zz_low_bar = _build_zigzag(highs, lows, opens, closes)

    F        = FRACTAL_BARS
    signals  = []

    for i in range(VOL_LEN + ATR_LEN + F, len(df) - F - 1):
        atr = atrs[i]
        if np.isnan(atr) or atr == 0:
            continue

        fp = (highs[i] > highs[i-F:i].max()) and (highs[i] > highs[i+1:i+F+1].max())
        ft = (lows[i]  < lows[i-F:i].min())  and (lows[i]  < lows[i+1:i+F+1].min())
        ar = closes[i] < highs[i] - atr * atr_mult
        ab = closes[i] > lows[i]  + atr * atr_mult

        if nearest_sr_distance23(closes[i], cluster_prices, atr) > sr_dist:
            continue

        trend     = trend_arr[i]
        # For shorts: want ZZ trend='up', swing high nearby
        # For longs:  want ZZ trend='down', swing low nearby
        if fp and ar and trend == 'up':
            swing_bar = int(zz_high_bar[i])
            if swing_bar >= 0 and i - swing_bar <= PROX_BARS:
                peak_slack = (highs[i] - closes[i]) / atr
                signals.append((df.iloc[i]['time'], 'short', peak_slack))

        elif ft and ab and trend == 'down':
            swing_bar = int(zz_low_bar[i])
            if swing_bar >= 0 and i - swing_bar <= PROX_BARS:
                trough_slack = (closes[i] - lows[i]) / atr
                signals.append((df.iloc[i]['time'], 'long', trough_slack))

    return signals


# ─────────────────────────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────────────────────────

def run_month(algo, label, start, end, creds):
    all_trades = []
    for sym in SYMBOLS:
        df_30m = fetch_alpaca_bars(sym, start, end, '30Min', creds['api_key'], creds['secret_key'])
        df_1m  = fetch_alpaca_bars(sym, start, end, '1Min',  creds['api_key'], creds['secret_key'])

        if df_30m is None or df_1m is None or len(df_30m) < 60 or len(df_1m) < 60:
            continue

        # Ensure time column exists
        if 'time' not in df_30m.columns:
            df_30m['time'] = pd.to_datetime(df_30m.get('t', df_30m.index))
        if 'time' not in df_1m.columns:
            df_1m['time'] = pd.to_datetime(df_1m.get('t', df_1m.index))

        df_1m = df_1m.sort_values('time').reset_index(drop=True)
        df_30m = df_30m.sort_values('time').reset_index(drop=True)

        if algo == 'boof22':
            signals = get_boof22_signals_30m(df_30m, sym)
        else:
            try:
                signals = get_boof23_signals_30m(df_30m, sym)
            except Exception as e:
                print(f'  [{sym}] boof23 signal error: {e}')
                signals = []

        last_exit_time = None

        for sig_time, direction, slack in signals:
            # No overlapping trades per symbol
            if last_exit_time is not None and sig_time <= last_exit_time:
                continue

            result = simulate_exit_1m(df_1m, sig_time, direction, STOCK_TP_PCT, STOCK_SL_PCT)
            if result is None:
                continue

            exit_type, pnl_pct, bars_held = result

            # Update last exit time
            future = df_1m[df_1m['time'] > sig_time]
            if not future.empty:
                entry_idx = future.index[0]
                loc = df_1m.index.get_loc(entry_idx)
                exit_loc = min(loc + bars_held, len(df_1m) - 1)
                last_exit_time = df_1m.iloc[exit_loc]['time']

            tier  = 'core' if slack >= 1.4 else 'expanded'
            size  = TRADE_CORE if tier == 'core' else TRADE_EXP

            opt_pnl = (
                size * TP_OPT  if exit_type == 'tp'
                else size * SL_OPT if exit_type == 'sl'
                else size * pnl_pct * 50  # rough time-exit scaling
            )

            all_trades.append({
                'symbol':    sym,
                'direction': direction,
                'exit_type': exit_type,
                'pnl_pct':   pnl_pct,
                'opt_pnl':   opt_pnl,
                'slack':     slack,
                'tier':      tier,
            })

    return all_trades


def summarise(algo_name, all_results):
    print(f'\n{"="*70}')
    print(f'  {algo_name.upper()} — 30m Signal / 1m Entry — {len(SYMBOLS)} symbols')
    print(f'{"="*70}')
    total_trades = total_pnl = total_tp = total_sl = total_tm = 0
    for label, trades, tdays in all_results:
        if not trades:
            print(f'  {label}:  no trades')
            continue
        tp = sum(1 for t in trades if t['exit_type'] == 'tp')
        sl = sum(1 for t in trades if t['exit_type'] == 'sl')
        tm = sum(1 for t in trades if t['exit_type'] == 'time')
        pnl = sum(t['opt_pnl'] for t in trades)
        wr  = tp / len(trades) * 100 if trades else 0
        pf  = (tp * TRADE_CORE * TP_OPT) / max(sl * TRADE_CORE * abs(SL_OPT), 1)
        total_trades += len(trades); total_pnl += pnl
        total_tp += tp; total_sl += sl; total_tm += tm
        print(f'  {label}: {len(trades):>4} trades  WR={wr:.0f}%  PF={pf:.1f}  P&L=${pnl:>8,.0f}  ({tp}tp/{sl}sl/{tm}tm)')
    if total_trades:
        wr  = total_tp / total_trades * 100
        pf  = (total_tp * TRADE_CORE * TP_OPT) / max(total_sl * TRADE_CORE * abs(SL_OPT), 1)
        ev  = total_pnl / total_trades
        print(f'{"─"*70}')
        print(f'  TOTAL: {total_trades} trades  WR={wr:.1f}%  PF={pf:.1f}  EV=${ev:.2f}/trade  Annual P&L=${total_pnl:,.0f}')
    print()


if __name__ == '__main__':
    creds = get_alpaca_credentials()
    print(f'Running 30m Signal / 1m Entry backtest — {len(SYMBOLS)} symbols × {len(months)} months')
    print(f'Algos: Boof 22.0 + Boof 23.0\n')

    boof22_results = []
    boof23_results = []

    for label, start, end, tdays in months:
        print(f'  Fetching {label}...', end=' ', flush=True)

        t22 = run_month('boof22', label, start, end, creds)
        t23 = run_month('boof23', label, start, end, creds)

        boof22_results.append((label, t22, tdays))
        boof23_results.append((label, t23, tdays))
        print(f'22={len(t22)}tr  23={len(t23)}tr')

    summarise('Boof 22.0', boof22_results)
    summarise('Boof 23.0', boof23_results)
