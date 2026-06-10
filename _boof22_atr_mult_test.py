"""
Boof 22.0 — ATR mult threshold test
Tests widening the signal confirmation ATR threshold (atr_mult)
from current 1.4 down to 0.6 in steps.

atr_mult controls: close < high - atr*mult (peak rejection)
                   close > low  + atr*mult (trough bounce)

Lower = easier to trigger (more signals, potentially lower quality)
Higher = harder to trigger (fewer signals, higher quality)

Current: 1.4 for most symbols
Testing: 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4 (baseline), 1.6, 1.8, 2.0
"""
import pickle, sys
import numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              MAX_HOLD_MIN, FRACTAL_BARS, ATR_LEN, VOL_LEN,
                              SR_DIST_MAX, SR_STRENGTH_MIN)
import pandas as pd

TRADE    = 200
TM_PCT   = 0.08
MAX_HOLD = 30
ATR_TP   = 4.0
ATR_SL   = 2.0

SYMBOLS  = ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
months   = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

print('Loading cache...')
dfs = pickle.load(open('_boof22_cache.pkl','rb'))

def run_with_atr_mult(atr_mult_override, vol_mult=1.3):
    """Re-run Boof 22 signal detection with a custom atr_mult, then apply ATR exits."""
    F = FRACTAL_BARS
    all_pnls = []
    total_signals = 0

    for mo in months:
        for sym in SYMBOLS:
            df = dfs.get((sym, mo))
            if df is None or len(df) < 100: continue

            df = df.copy().reset_index(drop=True)
            if len(df) < max(ATR_LEN, VOL_LEN, F * 2) + 10: continue

            atr_series    = compute_atr(df)
            df['atr']     = atr_series
            df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
            df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
            df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult

            cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult)

            highs  = df['high'].values
            lows   = df['low'].values
            closes = df['close'].values

            in_trade = False

            for i in range(VOL_LEN + ATR_LEN + F, len(df) - F - MAX_HOLD - 2):
                if in_trade:
                    in_trade = False  # reset — we track exits below per signal

                row  = df.iloc[i]
                rvol = row['rvol']
                if rvol < 80: continue

                atr    = row['atr']
                hi_vol = row['hi_vol']
                if pd.isna(atr) or atr == 0 or not hi_vol: continue

                left_highs  = highs[i - F: i]
                right_highs = highs[i + 1: i + F + 1]
                left_lows   = lows[i - F: i]
                right_lows  = lows[i + 1: i + F + 1]

                fractal_peak   = (highs[i] > left_highs.max()) and (highs[i] > right_highs.max())
                fractal_trough = (lows[i]  < left_lows.min())  and (lows[i]  < right_lows.min())

                # ← THIS is the threshold we're testing
                atr_rejected_peak  = closes[i] < highs[i] - atr * atr_mult_override
                atr_bounced_trough = closes[i] > lows[i]  + atr * atr_mult_override

                dist_to_sr = nearest_sr_distance(row['close'], cluster_prices, atr)
                if dist_to_sr > SR_DIST_MAX: continue

                is_peak   = fractal_peak   and atr_rejected_peak
                is_trough = fractal_trough and atr_bounced_trough

                if not is_peak and not is_trough: continue

                # Entry on next bar open
                if i + 1 >= len(df): continue
                ep = float(df.iloc[i + 1]['open'])
                d  = 'short' if is_peak else 'long'

                tp_p = ep + atr * ATR_TP if d == 'long' else ep - atr * ATR_TP
                sl_p = ep - atr * ATR_SL if d == 'long' else ep + atr * ATR_SL

                # Simulate exit
                et = 'time'
                for j in range(i + 2, min(i + 2 + MAX_HOLD, len(df))):
                    hi_j = df['high'].iloc[j]
                    lo_j = df['low'].iloc[j]
                    if d == 'long':
                        if hi_j >= tp_p: et = 'tp'; break
                        if lo_j <= sl_p: et = 'sl'; break
                    else:
                        if lo_j <= tp_p: et = 'tp'; break
                        if hi_j >= sl_p: et = 'sl'; break

                if et == 'tp':   pnl = TRADE * (atr * ATR_TP / ep)
                elif et == 'sl': pnl = -TRADE * (atr * ATR_SL / ep)
                else:            pnl = TRADE * TM_PCT

                all_pnls.append(pnl)
                total_signals += 1

    return np.array(all_pnls), total_signals


# ── Grid test ──
test_mults = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.6, 1.8, 2.0]

print(f'\n{"="*75}')
print(f'BOOF 22.0 — ATR Confirmation Threshold Test (atr_mult)')
print(f'ATR Exits: {ATR_TP}× TP / {ATR_SL}× SL | Full year 2025 | $200/trade')
print(f'{"="*75}')
print(f'{"Mult":<7} {"Signals":>8} {"WR%":>7} {"PF":>7} {"EV$":>7} {"Annual$":>10} {"MaxDD$":>8} {"Note"}')
print(f'{"-"*75}')

results = []
for mult in test_mults:
    arr, n = run_with_atr_mult(mult)
    if n == 0:
        print(f'{mult:<7} {"0":>8} {"–":>7} {"–":>7} {"–":>7} {"–":>10}')
        continue
    wins   = arr[arr > 0]; losses = arr[arr < 0]
    wr     = round(len(wins)/n*100, 1)
    pf     = round(float(sum(wins)/max(abs(sum(losses)),0.01)), 2)
    ev     = round(float(np.mean(arr)), 2)
    annual = round(float(sum(arr)))
    cum    = np.cumsum(arr); peak = np.maximum.accumulate(cum)
    dd     = round(float((peak - cum).max()))
    note   = '← CURRENT' if mult == 1.4 else ('← wider' if mult < 1.4 else '← tighter')
    results.append((mult, n, wr, pf, ev, annual, dd))
    print(f'{mult:<7} {n:>8,} {wr:>7} {pf:>7} ${ev:>6} ${annual:>9,} ${dd:>7,} {note}')

print(f'{"-"*75}')
print(f'\nTOP 5 BY ANNUAL P&L:')
for r in sorted(results, key=lambda x: x[5], reverse=True)[:5]:
    print(f'  mult={r[0]}  signals={r[1]:,}  WR={r[2]}%  PF={r[3]}  EV=${r[4]}  Annual=${r[5]:,}  MaxDD=${r[6]:,}')

print(f'\nTOP 5 BY PROFIT FACTOR:')
for r in sorted(results, key=lambda x: x[3], reverse=True)[:5]:
    print(f'  mult={r[0]}  signals={r[1]:,}  WR={r[2]}%  PF={r[3]}  EV=${r[4]}  Annual=${r[5]:,}  MaxDD=${r[6]:,}')

print(f'\nTOP 5 BY EV/TRADE:')
for r in sorted(results, key=lambda x: x[4], reverse=True)[:5]:
    print(f'  mult={r[0]}  signals={r[1]:,}  WR={r[2]}%  PF={r[3]}  EV=${r[4]}  Annual=${r[5]:,}  MaxDD=${r[6]:,}')
