"""
Boof 23 — Slippage degradation suite
Config: prox=30, engulf=OFF
Tests EV degradation, PF compression, drawdown scaling across slippage levels
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
DAYS   = 342
PROX   = 30

# Slippage levels: fraction of ATR added to entry price (worsens fill)
# 0.00 = clean fill, 0.05 = 5% of ATR slippage, etc.
SLIP_LEVELS = [0.00, 0.05, 0.10, 0.15, 0.25, 0.40]

print('Loading caches...')
cache25 = pickle.load(open('_boof22_cache.pkl', 'rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl', 'rb'))

def run_b23(slip_atr_frac=0.0, prox=30, use_engulf=False):
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

            opens  = df['open'].values;  highs = df['high'].values
            lows   = df['low'].values;   closes= df['close'].values
            atrs   = df['atr'].values;   hi_vol= df['hi_vol'].values

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
                    if zz_h_bar >= 0 and abs(i - zz_h_bar) <= prox:
                        engulf_ok = (not use_engulf) or (closes[i] < opens[i])
                        if engulf_ok:
                            direction = 'short'; slack = ps

                elif ft and ts >= atr_mult and trend == 'down':
                    zz_l_bar = int(zz_low_bar[i])
                    if zz_l_bar >= 0 and abs(i - zz_l_bar) <= prox:
                        engulf_ok = (not use_engulf) or (closes[i] > opens[i])
                        if engulf_ok:
                            direction = 'long'; slack = ts

                if direction is None: continue

                entry_bar = i + 1
                if entry_bar >= len(df) - MAX_HOLD - 2: continue

                atr_slip = atr * slip_atr_frac
                ep_raw   = float(opens[entry_bar])
                # Slippage: long fills higher, short fills lower
                ep = ep_raw + atr_slip if direction == 'long' else ep_raw - atr_slip

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
                all_trades.append({
                    'pnl': pnl_pct * size, 'et': et,
                    'slack': slack, 'tier': 'core' if slack >= 1.4 else 'expanded',
                    'mo': mo
                })
    return all_trades

# ── Run all slip levels ────────────────────────────────────────────
print('Running slippage sweep (prox=30, engulf=off)...\n')
results = {}
for slip in SLIP_LEVELS:
    trades = run_b23(slip_atr_frac=slip)
    results[slip] = trades
    arr = np.array([t['pnl'] for t in trades])
    print(f'  slip={slip:.2f} → n={len(arr):,}  done')

# ── Print degradation table ────────────────────────────────────────
print(f'\n{"="*85}')
print(f'  BOOF 23 — Slippage Degradation (prox=30, engulf=OFF)')
print(f'  Slippage = fraction of ATR added to fill price')
print(f'{"="*85}')
print(f'  {"Slip":>6}  {"Trades":>8}  {"T/day":>7}  {"WR%":>7}  {"PF":>7}  '
      f'{"EV$":>8}  {"Annual$":>11}  {"$/mo":>9}  {"MaxDD$":>9}')
print(f'  {"-"*83}')

baseline_ev  = None
baseline_pf  = None
baseline_ann = None

for slip in SLIP_LEVELS:
    trades = results[slip]
    arr    = np.array([t['pnl'] for t in trades])
    n      = len(arr)
    pos    = arr[arr>0]; neg = arr[arr<0]
    wr     = round(len(pos)/n*100, 1)
    pf     = round(float(sum(pos)/max(abs(sum(neg)), 0.01)), 2)
    ev     = round(float(np.mean(arr)), 2)
    ann    = round(float(sum(arr)))
    tpd    = round(n/DAYS, 1)
    moa    = round(ann/17)

    # Monthly drawdown
    mo_keys = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec',
               'Jan 26','Feb 26','Mar 26','Apr 26','May 26']
    mo_pnls = []
    for mk in mo_keys:
        mo_pnl = sum(t['pnl'] for t in trades if t['mo'] == mk)
        mo_pnls.append(mo_pnl)
    mo_arr  = np.array(mo_pnls)
    cum     = np.cumsum(mo_arr)
    max_dd  = round(float((np.maximum.accumulate(cum) - cum).max()))

    if baseline_ev is None:
        baseline_ev = ev; baseline_pf = pf; baseline_ann = ann

    ev_deg  = round((ev  - baseline_ev)  / max(abs(baseline_ev),  0.01) * 100, 1)
    pf_deg  = round((pf  - baseline_pf)  / max(abs(baseline_pf),  0.01) * 100, 1)
    ann_deg = round((ann - baseline_ann) / max(abs(baseline_ann), 0.01) * 100, 1)

    flag = ''
    if ev < 0:      flag = '  !! NEGATIVE EV'
    elif ev < 3.0:  flag = '  ! LOW EV'

    print(f'  {slip:>6.2f}  {n:>8,}  {tpd:>7}  {wr:>7}  {pf:>7}  '
          f'{ev:>8}  ${ann:>10,}  ${moa:>8,}  ${max_dd:>8,}{flag}')

# ── EV / PF / Drawdown degradation summary ────────────────────────
print(f'\n{"="*85}')
print(f'  DEGRADATION vs 0-slip baseline')
print(f'{"="*85}')
print(f'  {"Slip":>6}  {"EV$":>8}  {"EV chg":>8}  {"PF":>7}  {"PF chg":>8}  '
      f'{"Annual$":>11}  {"Ann chg":>9}  {"MaxDD$":>9}')
print(f'  {"-"*83}')

for slip in SLIP_LEVELS:
    trades = results[slip]
    arr    = np.array([t['pnl'] for t in trades])
    pos    = arr[arr>0]; neg = arr[arr<0]
    pf     = round(float(sum(pos)/max(abs(sum(neg)), 0.01)), 2)
    ev     = round(float(np.mean(arr)), 2)
    ann    = round(float(sum(arr)))

    mo_keys = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec',
               'Jan 26','Feb 26','Mar 26','Apr 26','May 26']
    mo_pnls = [sum(t['pnl'] for t in trades if t['mo'] == mk) for mk in mo_keys]
    cum     = np.cumsum(mo_pnls)
    max_dd  = round(float((np.maximum.accumulate(cum) - cum).max()))

    ev_chg  = round(ev  - baseline_ev,  2)
    pf_chg  = round(pf  - baseline_pf,  2)
    ann_chg = round(ann - baseline_ann)

    print(f'  {slip:>6.2f}  {ev:>8}  {ev_chg:>+8.2f}  {pf:>7}  {pf_chg:>+8.2f}  '
          f'${ann:>10,}  {ann_chg:>+9,}  ${max_dd:>8,}')

print(f'{"="*85}')
print(f'\n  Breakeven slippage: EV hits 0 somewhere between above levels')
print(f'  PF < 1.5 = strategy edge gone | PF < 1.0 = net loser')
