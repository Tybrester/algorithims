"""
Boof 22 — Static vs ATR Exit Comparison (6 months Jan–Jun 2025)
Same test as B23: +35%/-15%, +25%/-10%, +50%/-20% vs ATR 4x/2x
"""
import pickle, sys
import numpy as np
from collections import defaultdict

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import run_boof22

SYMS   = ['AAPL','NVDA','META','GOOGL','AMD']
MONTHS = ['Jan','Feb','Mar','Apr','May','Jun']
MDAYS  = [23, 20, 21, 22, 21, 21]
TOTAL_DAYS = sum(MDAYS)
B22_EXP = 200; B22_CORE = 600

# B22 run_boof22 already supports tp_pct/sl_pct natively as % of price.
# Default is tp_pct=0.40, sl_pct=-0.15. pnl_pct is returned as % of entry price.
# For dollar P&L: pnl = pnl_pct * size (same as B23).
# Options premium exit model (same as B23 static test):
# Signal fires on underlying. Exit is defined as fixed % gain/loss on the option premium.
# Underlying threshold to trigger: TP premium% / SL premium% mapped to ATR fractions.
# premium ≈ 2x ATR dollars → +1 ATR move on underlying ≈ +50% on premium
# So: +35% premium → underlying moves 0.70 ATR; -15% premium → underlying moves 0.30 ATR
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                               SYMBOL_PARAMS, DEFAULT_PARAMS, ATR_LEN, VOL_LEN,
                               FRACTAL_BARS, SR_DIST_MAX)

CONFIGS = [
    ('B22 baseline (raw)',    None,  None ),   # raw pnl_pct × size for reference
    ('+35% / -15%',          0.35,  0.15 ),
    ('+25% / -10% (tight)',  0.25,  0.10 ),
    ('+50% / -20% (wide)',   0.50,  0.20 ),
]

STATIC_TP_ATR = {0.35: 0.70, 0.25: 0.50, 0.50: 1.00}
STATIC_SL_ATR = {0.15: 0.30, 0.10: 0.20, 0.20: 0.40}

print('Loading cache...')
cache = pickle.load(open('_boof22_cache.pkl', 'rb'))
print('  Done.\n')

def run_config(tp_prem, sl_prem):
    """Run B22 with option-premium style exits using ATR-fraction thresholds."""
    all_pnl = []; by_month = defaultdict(list); by_exit = defaultdict(list)
    MAX_H = 30; F = FRACTAL_BARS

    for mo in MONTHS:
        for sym in SYMS:
            df = cache.get((sym, mo))
            if df is None or len(df) < 100: continue

            if tp_prem is None:
                # Baseline: use run_boof22 native pnl (underlying % × size)
                trades = run_boof22(df, symbol=sym)
                for t in trades:
                    size = B22_CORE if t['tier']=='core' else B22_EXP
                    pnl  = t['pnl_pct'] * size
                    all_pnl.append(pnl); by_month[mo].append(pnl)
                    by_exit[t['exit_type']].append(pnl)
                continue

            # Static option-premium exits — re-run with ATR-fraction thresholds
            params   = SYMBOL_PARAMS.get(sym, DEFAULT_PARAMS)
            atr_mult = params['atr_mult']; vol_mult = params['vol_mult']
            sr_dist  = params['sr_dist']

            df2 = df.copy().reset_index(drop=True)
            atr_s = compute_atr(df2)
            df2['atr']    = atr_s
            df2['vol_sma']= df2['volume'].rolling(VOL_LEN).mean()
            df2['rvol']   = (df2['volume'] / df2['vol_sma'] * 100).fillna(0)
            df2['hi_vol'] = df2['volume'] > df2['vol_sma'] * vol_mult
            cluster_prices, _ = build_cluster_array(df2, atr_s, vol_mult)

            opens  = df2['open'].values;  highs = df2['high'].values
            lows   = df2['low'].values;   closes= df2['close'].values
            atrs   = df2['atr'].values

            tp_atr = STATIC_TP_ATR[tp_prem]
            sl_atr = STATIC_SL_ATR[sl_prem]

            in_trade = False; trade_end = 0
            warmup   = VOL_LEN + ATR_LEN + F

            for i in range(warmup, len(df2) - F - MAX_H - 3):
                if in_trade and i <= trade_end: continue
                atr = atrs[i]
                if np.isnan(atr) or atr == 0: continue
                if df2.iloc[i]['rvol'] < 80:  continue
                if not df2.iloc[i]['hi_vol']:  continue
                if nearest_sr_distance(closes[i], cluster_prices, atr) > sr_dist: continue

                lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
                ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
                fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
                ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())
                ps = (highs[i] - closes[i]) / atr
                ts = (closes[i] - lows[i])  / atr
                ar = closes[i] < highs[i] - atr * atr_mult
                ab = closes[i] > lows[i]  + atr * atr_mult

                direction = None; slack = 0.0
                if fp and ar: direction='short'; slack=ps
                elif ft and ab: direction='long'; slack=ts
                if direction is None: continue

                entry_bar = i + 1
                if entry_bar >= len(df2) - MAX_H - 2: continue
                ep = float(opens[entry_bar])

                tp_p = ep+atr*tp_atr if direction=='long' else ep-atr*tp_atr
                sl_p = ep-atr*sl_atr if direction=='long' else ep+atr*sl_atr

                et='time'; exit_bar=min(entry_bar+MAX_H, len(df2)-1)
                for j in range(entry_bar+1, min(entry_bar+MAX_H+1, len(df2))):
                    h=highs[j]; l=lows[j]
                    if direction=='long':
                        if h>=tp_p: et='tp'; exit_bar=j; break
                        if l<=sl_p: et='sl'; exit_bar=j; break
                    else:
                        if l<=tp_p: et='tp'; exit_bar=j; break
                        if h>=sl_p: et='sl'; exit_bar=j; break

                in_trade=True; trade_end=exit_bar
                size = B22_CORE if slack>=1.4 else B22_EXP
                pnl  = (tp_prem*size if et=='tp'
                        else -sl_prem*size if et=='sl'
                        else 0.08*size)
                all_pnl.append(pnl); by_month[mo].append(pnl)
                by_exit[et].append(pnl)

    return all_pnl, by_month, by_exit

def stats(arr):
    if not arr: return 0, 0.0, 0.0, 0.0, 0.0
    p=np.array(arr); pos=p[p>0]; neg=p[p<0]
    return (len(p), round(len(pos)/len(p)*100,1),
            round(float(np.mean(p)),2),
            round(float(sum(pos)/max(abs(sum(neg)),0.01)),2),
            round(float(sum(p)),0))

SEP = '=' * 78
all_results = {}
for name, tp, sl in CONFIGS:
    print(f'  Running {name}...')
    pnl, by_mo, by_exit = run_config(tp, sl)
    all_results[name] = {'pnl': pnl, 'by_mo': by_mo, 'by_exit': by_exit}

print(f'\n{SEP}')
print('  BOOF 22 — STATIC vs ATR EXIT COMPARISON  (6 months Jan–Jun)')
print(SEP)
print(f'  {"Config":<28}  {"N":>5}  {"T/d":>5}  {"WR":>7}  {"EV":>9}  '
      f'{"PF":>7}  {"6mo P&L":>10}  {"Ann est":>10}')
print(f'  {"-"*76}')
for name, tp, sl in CONFIGS:
    r = all_results[name]
    n, wr, ev, pf, tot = stats(r['pnl'])
    print(f'  {name:<28}  {n:>5}  {n/TOTAL_DAYS:>5.1f}  {wr:>6.1f}%  ${ev:>8.2f}  '
          f'{pf:>7.2f}  ${tot*2:>9,.0f}  ${tot*4:>9,.0f}')

print(f'\n{SEP}')
print('  EXIT BREAKDOWN PER CONFIG')
print(SEP)
for name, tp, sl in CONFIGS:
    r = all_results[name]
    total_n = len(r['pnl'])
    print(f'\n  {name}:')
    print(f'  {"Exit":<8}  {"N":>6}  {"WR":>7}  {"EV":>10}  {"Total":>12}  {"% trades":>9}')
    print(f'  {"-"*56}')
    for et in ['tp','sl','time']:
        pnls = r['by_exit'].get(et, [])
        if not pnls: continue
        n, wr, ev, _, tot = stats(pnls)
        print(f'  {et:<8}  {n:>6}  {wr:>6.1f}%  ${ev:>9.2f}  ${tot:>11,.0f}  {n/total_n*100:>8.1f}%')

print(f'\n{SEP}')
print('  MONTHLY BREAKDOWN')
print(SEP)
names = [c[0] for c in CONFIGS]
print(f'  {"Month":<8}', end='')
for name in names: print(f'  {name.split()[0]:>12}', end='')
print()
print(f'  {"-"*64}')
for mo in MONTHS:
    print(f'  {mo:<8}', end='')
    for name in names:
        pnl = sum(all_results[name]['by_mo'][mo])*2
        flag='*' if pnl<0 else ' '
        print(f'  ${pnl:>10,.0f}{flag}', end='')
    print()
print(f'  {"-"*64}')
print(f'  {"TOTAL":<8}', end='')
for name in names:
    tot = sum(p for mo in MONTHS for p in all_results[name]['by_mo'][mo])*2
    print(f'  ${tot:>10,.0f} ', end='')
print()

# Side-by-side B22 vs B23 best config
print(f'\n{SEP}')
print('  VERDICT')
print(SEP)
base_ann = sum(all_results[CONFIGS[0][0]]['pnl'])*4
base_ann = sum(all_results[CONFIGS[0][0]]['pnl'])*4
for i,(name, tp, sl) in enumerate(CONFIGS):
    n,wr,ev,pf,tot = stats(all_results[name]['pnl'])
    ann = tot*4
    delta = f'(baseline)' if i==0 else f'({ann-base_ann:+,.0f} vs current)'
    red   = sum(1 for mo in MONTHS if sum(all_results[name]['by_mo'][mo])*2 < 0)
    print(f'  {name:<28}  EV=${ev:.2f}  WR={wr}%  PF={pf:.1f}  '
          f'Ann=${ann:,.0f}  Red={red}mo  {delta}')

print(f'\n  B22 vs B23 at +35%/-15%:')
b22_35 = stats(all_results['+35% / -15%']['pnl'])
print(f'  B22: {b22_35[0]} trades  WR={b22_35[1]}%  EV=${b22_35[2]:.2f}  Ann=${b22_35[4]*4:,.0f}')
print(f'  B23: 1657 trades  WR=59.3%  EV=$37.95  Ann=$251,540')
print(SEP)
