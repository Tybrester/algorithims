"""
Boof 23 — Proximity window sweep: 10, 15, 20, 30
Keep engulf on, vary swing proximity window only
"""
import pickle, sys, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof23 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              _build_zigzag, BOOFINGTON23, SYMBOL_PARAMS, DEFAULT_PARAMS,
                              ATR_LEN, VOL_LEN, ATR_TP, ATR_SL, ATR_MULT,
                              FRACTAL_BARS, SR_DIST_MAX, TIME_EXIT_PCT, MAX_HOLD)

CORE_SIZE = 600; EXP_SIZE = 200
MOS_25 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MOS_26 = ['Jan 26','Feb 26','Mar 26','Apr 26','May 26']
DAYS   = 342  # 17 months

print('Loading caches...')
cache25 = pickle.load(open('_boof22_cache.pkl', 'rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl', 'rb'))

def run_b23_prox(prox_window, use_engulf=True):
    import pandas as pd
    F = FRACTAL_BARS
    all_trades = []

    for mo, cache in [(m, cache25) for m in MOS_25] + [(m, cache26) for m in MOS_26]:
        for sym in BOOFINGTON23:
            df = cache.get((sym, mo))
            if df is None or len(df) < 100: continue

            params      = SYMBOL_PARAMS.get(sym, DEFAULT_PARAMS)
            vol_mult    = params['vol_mult']
            atr_mult    = params['atr_mult']
            sr_dist_max = params['sr_dist']

            df = df.copy().reset_index(drop=True)
            atr_series    = compute_atr(df)
            df['atr']     = atr_series
            df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
            df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
            df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult
            cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult)

            opens  = df['open'].values;  highs  = df['high'].values
            lows   = df['low'].values;   closes = df['close'].values
            atrs   = df['atr'].values;   hi_vol = df['hi_vol'].values

            trend_arr, zz_high, zz_high_bar, zz_low, zz_low_bar = _build_zigzag(
                highs, lows, opens, closes)

            in_trade = False; trade_end = 0
            warmup = VOL_LEN + ATR_LEN + F

            for i in range(warmup, len(df) - F - MAX_HOLD - 3):
                if in_trade and i <= trade_end: continue
                row   = df.iloc[i]
                atr   = atrs[i]
                trend = trend_arr[i]
                if np.isnan(atr) or atr == 0: continue
                if row['rvol'] < 80:          continue
                if not hi_vol[i]:             continue
                if trend == '':               continue
                if nearest_sr_distance(row['close'], cluster_prices, atr) > sr_dist_max:
                    continue

                lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
                ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
                fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
                ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())
                ps = (highs[i] - closes[i]) / atr
                ts = (closes[i] - lows[i])  / atr

                direction = None; slack = 0.0

                if fp and ps >= atr_mult and trend == 'up':
                    zz_h_bar = int(zz_high_bar[i])
                    if zz_h_bar >= 0 and abs(i - zz_h_bar) <= prox_window:
                        engulf_ok = (not use_engulf) or (closes[i] < opens[i])
                        if engulf_ok:
                            direction = 'short'; slack = ps

                elif ft and ts >= atr_mult and trend == 'down':
                    zz_l_bar = int(zz_low_bar[i])
                    if zz_l_bar >= 0 and abs(i - zz_l_bar) <= prox_window:
                        engulf_ok = (not use_engulf) or (closes[i] > opens[i])
                        if engulf_ok:
                            direction = 'long'; slack = ts

                if direction is None: continue

                entry_bar = i + 1
                if entry_bar >= len(df) - MAX_HOLD - 2: continue
                ep   = float(opens[entry_bar])
                tp_p = ep + atr*ATR_TP if direction=='long' else ep - atr*ATR_TP
                sl_p = ep - atr*ATR_SL if direction=='long' else ep + atr*ATR_SL
                et = 'time'; exit_bar = min(entry_bar + MAX_HOLD, len(df)-1)
                for j in range(entry_bar+1, min(entry_bar+MAX_HOLD+1, len(df))):
                    h = highs[j]; l = lows[j]
                    if direction == 'long':
                        if h >= tp_p: et='tp'; exit_bar=j; break
                        if l <= sl_p: et='sl'; exit_bar=j; break
                    else:
                        if l <= tp_p: et='tp'; exit_bar=j; break
                        if h >= sl_p: et='sl'; exit_bar=j; break

                in_trade = True; trade_end = exit_bar
                pnl_pct  = ((atr*ATR_TP/ep) if et=='tp'
                            else -(atr*ATR_SL/ep) if et=='sl'
                            else TIME_EXIT_PCT)
                size = CORE_SIZE if slack >= 1.4 else EXP_SIZE
                all_trades.append({'pnl': pnl_pct * size, 'et': et, 'slack': slack,
                                   'tier': 'core' if slack >= 1.4 else 'expanded'})
    return all_trades

# ── Sweep ──────────────────────────────────────────────────────────
windows = [10, 15, 20, 30, 50]

print(f'\n{"="*72}')
print(f'  Boof 23 — Proximity Window Sweep (engulf ON)')
print(f'  {"Window":>8}  {"Trades":>8}  {"T/day":>7}  {"WR%":>7}  {"PF":>7}  {"EV$":>8}  {"Annual$":>12}  {"$/mo":>9}')
print(f'  {"-"*70}')

for w in windows:
    trades = run_b23_prox(w, use_engulf=True)
    if not trades:
        print(f'  {w:>8}  NO TRADES')
        continue
    arr = np.array([t['pnl'] for t in trades])
    n   = len(arr)
    pos = arr[arr > 0]; neg = arr[arr < 0]
    wr  = round(len(pos)/n*100, 1)
    pf  = round(float(sum(pos)/max(abs(sum(neg)), 0.01)), 2)
    ev  = round(float(np.mean(arr)), 2)
    ann = round(float(sum(arr)))
    tpd = round(n/DAYS, 1)
    moa = round(ann/17)
    print(f'  {w:>8}  {n:>8}  {tpd:>7}  {wr:>7}  {pf:>7}  {ev:>8}  ${ann:>10,}  ${moa:>8,}')

# ── Also test: best window + engulf OFF ───────────────────────────
print(f'\n{"="*72}')
print(f'  Engulf OFF comparison (best windows)')
print(f'  {"Config":<16}  {"Trades":>8}  {"T/day":>7}  {"WR%":>7}  {"PF":>7}  {"EV$":>8}  {"Annual$":>12}  {"$/mo":>9}')
print(f'  {"-"*70}')

for w in [20, 30]:
    for eng in [True, False]:
        trades = run_b23_prox(w, use_engulf=eng)
        if not trades: continue
        arr = np.array([t['pnl'] for t in trades])
        n   = len(arr)
        pos = arr[arr > 0]; neg = arr[arr < 0]
        wr  = round(len(pos)/n*100, 1)
        pf  = round(float(sum(pos)/max(abs(sum(neg)), 0.01)), 2)
        ev  = round(float(np.mean(arr)), 2)
        ann = round(float(sum(arr)))
        tpd = round(n/DAYS, 1)
        moa = round(ann/17)
        label = f'prox={w} eng={"on" if eng else "off"}'
        print(f'  {label:<16}  {n:>8}  {tpd:>7}  {wr:>7}  {pf:>7}  {ev:>8}  ${ann:>10,}  ${moa:>8,}')

print(f'{"="*72}')
