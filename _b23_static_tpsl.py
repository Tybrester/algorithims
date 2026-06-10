"""
Boof 23 — Static TP/SL vs ATR-based comparison (6 months Jan-Jun 2025)
Tests: +35% TP / -15% SL as fixed % of entry price (options-style)
vs current ATR 4x TP / 2x SL
"""
import pickle, sys
import numpy as np
from collections import defaultdict

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof23 as b23
from backtest_boof23 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              _build_zigzag, SYMBOL_PARAMS, DEFAULT_PARAMS,
                              ATR_LEN, VOL_LEN, ATR_TP, ATR_SL, ATR_MULT,
                              FRACTAL_BARS, MAX_HOLD)

b23.CLUSTER_COMPLETION = False
b23.LOW_VOL_FILTER     = False

SYMS   = ['NVDA','AAPL','MSFT','AMZN','GOOGL','AVGO','META','TSLA','LLY']
MONTHS = ['Jan','Feb','Mar','Apr','May','Jun']
MDAYS  = [23, 20, 21, 22, 21, 21]
TOTAL_DAYS = sum(MDAYS)
B23_EXP = 200; B23_CORE = 500

# Static TP/SL configs to test
CONFIGS = [
    ('ATR 4x/2x  (current)',  'atr',    4.0,  2.0),
    ('+35% / -15% (static)',  'static', 0.35, 0.15),
    ('+25% / -10% (tight)',   'static', 0.25, 0.10),
    ('+50% / -20% (wide)',    'static', 0.50, 0.20),
]

# Static mode: TP/SL are option premium % targets (same as Boof 21).
# The underlying signal fires an entry. We check whether the underlying
# move from entry (as % of ATR) would imply hitting the option TP/SL.
# Approximation used by Boof 21: option premium ≈ 2x ATR in dollar terms.
# So underlying move of +1 ATR ≈ +50% on premium.
# → +35% premium hit when underlying moves +0.70 ATR toward TP
# → -15% premium hit when underlying moves +0.30 ATR against (SL)
# These ATR fractions are used as the exit thresholds on the underlying.
STATIC_TP_ATR = {0.35: 0.70, 0.25: 0.50, 0.50: 1.00}  # premium% → ATR mult
STATIC_SL_ATR = {0.15: 0.30, 0.10: 0.20, 0.20: 0.40}  # premium% → ATR mult

print('Loading cache...')
cache = pickle.load(open('_boof22_cache.pkl', 'rb'))
print('  Done.\n')

def run_static(tp_val, sl_val, mode):
    """Re-run B23 signal detection but replace exit logic with static %."""
    all_pnl = []; by_month = defaultdict(list); by_exit = defaultdict(list)

    for mo in MONTHS:
        for sym in SYMS:
            df = cache.get((sym, mo))
            if df is None or len(df) < 100: continue

            params      = SYMBOL_PARAMS.get(sym, DEFAULT_PARAMS)
            vol_mult    = params['vol_mult']
            atr_mult_v  = params['atr_mult']
            sr_dist_max = params['sr_dist']
            use_engulf  = params['use_engulf']
            F           = FRACTAL_BARS

            df2 = df.copy().reset_index(drop=True)
            atr_s = compute_atr(df2)
            df2['atr']    = atr_s
            df2['vol_sma']= df2['volume'].rolling(VOL_LEN).mean()
            df2['rvol']   = (df2['volume'] / df2['vol_sma'] * 100).fillna(0)
            df2['hi_vol'] = df2['volume'] > df2['vol_sma'] * vol_mult
            cluster_prices, _ = build_cluster_array(df2, atr_s, vol_mult)

            opens  = df2['open'].values;  highs = df2['high'].values
            lows   = df2['low'].values;   closes= df2['close'].values
            atrs   = df2['atr'].values;   hi_vol= df2['hi_vol'].values
            trend_arr, _, zz_high_bar, _, zz_low_bar = _build_zigzag(
                highs, lows, opens, closes)

            in_trade = False; trade_end = 0
            warmup = VOL_LEN + ATR_LEN + F

            for i in range(warmup, len(df2) - F - MAX_HOLD - 3):
                if in_trade and i <= trade_end: continue
                atr   = atrs[i]; trend = trend_arr[i]
                if np.isnan(atr) or atr == 0: continue
                if df2.iloc[i]['rvol'] < 80:  continue
                if not hi_vol[i]:             continue
                if trend == '':              continue
                if nearest_sr_distance(closes[i], cluster_prices, atr) > sr_dist_max:
                    continue

                lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
                ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
                fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
                ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())
                ps = (highs[i] - closes[i]) / atr
                ts = (closes[i] - lows[i])  / atr

                direction = None; slack = 0.0
                if fp and ps >= atr_mult_v and trend == 'up':
                    zz_h = int(zz_high_bar[i])
                    if zz_h >= 0 and abs(i - zz_h) <= 10:
                        engulf_ok = (not use_engulf) or (closes[i] < opens[i])
                        if engulf_ok: direction = 'short'; slack = ps
                elif ft and ts >= atr_mult_v and trend == 'down':
                    zz_l = int(zz_low_bar[i])
                    if zz_l >= 0 and abs(i - zz_l) <= 10:
                        engulf_ok = (not use_engulf) or (closes[i] > opens[i])
                        if engulf_ok: direction = 'long'; slack = ts
                if direction is None: continue

                entry_bar = i + 1
                if entry_bar >= len(df2) - MAX_HOLD - 2: continue
                ep = float(opens[entry_bar])

                # ── Exit logic ──────────────────────────────────
                if mode == 'atr':
                    tp_p = ep + atr*tp_val if direction=='long' else ep - atr*tp_val
                    sl_p = ep - atr*sl_val if direction=='long' else ep + atr*sl_val
                else:
                    # Static: thresholds expressed as ATR fractions
                    # (premium move proxy — see STATIC_TP_ATR/SL_ATR mapping)
                    tp_atr = STATIC_TP_ATR.get(tp_val, tp_val * 2)
                    sl_atr = STATIC_SL_ATR.get(sl_val, sl_val * 2)
                    tp_p = ep + atr*tp_atr if direction=='long' else ep - atr*tp_atr
                    sl_p = ep - atr*sl_atr if direction=='long' else ep + atr*sl_atr

                et = 'time'; exit_bar = min(entry_bar + MAX_HOLD, len(df2)-1)
                for j in range(entry_bar+1, min(entry_bar+MAX_HOLD+1, len(df2))):
                    h = highs[j]; l = lows[j]
                    if direction == 'long':
                        if h >= tp_p: et = 'tp'; exit_bar = j; break
                        if l <= sl_p: et = 'sl'; exit_bar = j; break
                    else:
                        if l <= tp_p: et = 'tp'; exit_bar = j; break
                        if h >= sl_p: et = 'sl'; exit_bar = j; break

                in_trade = True; trade_end = exit_bar

                size = B23_CORE if slack >= 1.4 else B23_EXP

                if mode == 'atr':
                    # ATR mode: P&L as % of entry price × position size
                    # (matches backtest_boof23 run_boof23 logic)
                    pnl_pct = (atr*tp_val/ep if et=='tp'
                               else -atr*sl_val/ep if et=='sl'
                               else 0.08)   # TIME_EXIT_PCT
                    pnl = pnl_pct * size
                else:
                    # Static mode: TP/SL as fixed % gain/loss on position size
                    # i.e. +35% means the options position gained 35% of notional
                    pnl = (tp_val * size if et=='tp'
                           else -sl_val * size if et=='sl'
                           else 0.08 * size)  # time exit same as ATR
                all_pnl.append(pnl)
                by_month[mo].append(pnl)
                by_exit[et].append(pnl)

    return all_pnl, by_month, by_exit

def stats(arr):
    if not arr: return 0, 0.0, 0.0, 0.0, 0.0
    p = np.array(arr); pos = p[p>0]; neg = p[p<0]
    return (len(p), round(len(pos)/len(p)*100,1),
            round(float(np.mean(p)),2),
            round(float(sum(pos)/max(abs(sum(neg)),0.01)),2),
            round(float(sum(p)),0))

SEP = '=' * 76

# Run all configs
all_results = {}
for name, mode, tp, sl in CONFIGS:
    print(f'  Running {name}...')
    pnl, by_mo, by_exit = run_static(tp, sl, mode)
    all_results[name] = {'pnl': pnl, 'by_mo': by_mo, 'by_exit': by_exit}

print(f'\n{SEP}')
print('  BOOF 23 — STATIC vs ATR EXIT COMPARISON  (6 months Jan–Jun)')
print(SEP)
print(f'  {"Config":<28}  {"N":>5}  {"T/d":>5}  {"WR":>7}  {"EV":>9}  '
      f'{"PF":>7}  {"6mo P&L":>10}  {"Ann est":>10}')
print(f'  {"-"*74}')
for name, mode, tp, sl in CONFIGS:
    r = all_results[name]
    n, wr, ev, pf, tot = stats(r['pnl'])
    print(f'  {name:<28}  {n:>5}  {n/TOTAL_DAYS:>5.1f}  {wr:>6.1f}%  ${ev:>8.2f}  '
          f'{pf:>7.2f}  ${tot*2:>9,.0f}  ${tot*4:>9,.0f}')

# Exit breakdown per config
print(f'\n{SEP}')
print('  EXIT BREAKDOWN PER CONFIG')
print(SEP)
for name, mode, tp, sl in CONFIGS:
    r = all_results[name]
    print(f'\n  {name}:')
    print(f'  {"Exit":<8}  {"N":>6}  {"WR":>7}  {"EV":>10}  {"Total":>12}  {"% of trades":>12}')
    print(f'  {"-"*58}')
    total_n = len(r['pnl'])
    for et in ['tp','sl','time']:
        pnls = r['by_exit'][et]
        if not pnls: continue
        n, wr, ev, _, tot = stats(pnls)
        print(f'  {et:<8}  {n:>6}  {wr:>6.1f}%  ${ev:>9.2f}  ${tot:>11,.0f}  {n/total_n*100:>11.1f}%')

# Monthly for best static vs ATR
print(f'\n{SEP}')
print('  MONTHLY: ATR 4x/2x  vs  +35%/-15%  vs  +50%/-15%')
print(SEP)
names = list(all_results.keys())
print(f'  {"Month":<8}', end='')
for name in names:
    print(f'  {name.split()[0]:>10}', end='')
print()
print(f'  {"-"*58}')
for mo in MONTHS:
    print(f'  {mo:<8}', end='')
    for name in names:
        pnl = sum(all_results[name]['by_mo'][mo]) * 2
        flag = '*' if pnl < 0 else ' '
        print(f'  ${pnl:>9,.0f}{flag}', end='')
    print()
print(f'  {"-"*58}')
print(f'  {"TOTAL":<8}', end='')
for name in names:
    total = sum(p for mo in MONTHS for p in all_results[name]['by_mo'][mo]) * 2
    print(f'  ${total:>9,.0f} ', end='')
print()

print(f'\n{SEP}')
print('  VERDICT')
print(SEP)
base_ann = sum(all_results[CONFIGS[0][0]]['pnl']) * 4
for name, mode, tp, sl in CONFIGS:
    n, wr, ev, pf, tot = stats(all_results[name]['pnl'])
    ann = tot * 4
    delta = ann - base_ann
    red = sum(1 for mo in MONTHS if sum(all_results[name]['by_mo'][mo])*2 < 0)
    vs = f'({delta:+,.0f} vs ATR)' if mode != 'atr' else '(baseline)'
    print(f'  {name:<28}  EV=${ev:.2f}  WR={wr}%  PF={pf:.1f}  '
          f'Ann=${ann:,.0f}  Red={red}mo  {vs}')
print(SEP)
