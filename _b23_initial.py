"""
Boof 23 — Initial backtest
ZigZag Swing Reversal + RVOL + Mother Bar
Compare vs Boof 22 BOOFINGTON, 2025 full year + 2026 YTD
"""
import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof23 import run_boof23, BOOFINGTON23, compute_atr
from backtest_boof22 import (compute_atr as b22_atr, build_cluster_array,
                              nearest_sr_distance, FRACTAL_BARS, ATR_LEN,
                              VOL_LEN, SR_DIST_MAX, BOOFINGTON)

CORE_SIZE = 600; EXP_SIZE = 200; TM_PCT = 0.08
DAYS_25 = 252; DAYS_26 = 90

MOS_25 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MOS_26 = ['Jan 26','Feb 26','Mar 26','Apr 26','May 26']

print('Loading caches...')
cache25 = pickle.load(open('_boof22_cache.pkl', 'rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl', 'rb'))


def trade_pnl(t, core_size=CORE_SIZE, exp_size=EXP_SIZE):
    size = core_size if t['tier'] == 'core' else exp_size
    return t['pnl_pct'] * size


def run_b23_month(mo_key, cache):
    trades = []
    for sym in BOOFINGTON23:
        df = cache.get((sym, mo_key))
        if df is None or len(df) < 100: continue
        raw = run_boof23(df, symbol=sym)
        for t in raw:
            t['pnl'] = trade_pnl(t)
            trades.append(t)
    return trades


def run_b22_month(mo_key, cache):
    F = FRACTAL_BARS; ATR_MULT = 0.6; MAX_HOLD = 30
    trades = []
    for sym in BOOFINGTON:
        vm = 1.2 if sym == 'AAPL' else 1.3
        df = cache.get((sym, mo_key))
        if df is None or len(df) < 100: continue
        df = df.copy().reset_index(drop=True)
        atr_s = b22_atr(df); df['atr'] = atr_s
        df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
        df['rvol'] = (df['volume'] / df['vol_sma'] * 100).fillna(0)
        df['hi_vol'] = df['volume'] > df['vol_sma'] * vm
        cp, _ = build_cluster_array(df, atr_s, vm)
        highs = df['high'].values; lows = df['low'].values; closes = df['close'].values
        for i in range(VOL_LEN + ATR_LEN + F, len(df) - F - MAX_HOLD - 3):
            row = df.iloc[i]
            if row['rvol'] < 80: continue
            atr = row['atr']
            if pd.isna(atr) or atr == 0 or not row['hi_vol']: continue
            if nearest_sr_distance(row['close'], cp, atr) > SR_DIST_MAX: continue
            lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
            ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
            fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
            ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())
            ps = (highs[i] - closes[i]) / atr
            ts = (closes[i] - lows[i])  / atr
            for direction, is_valid, slack in [('short', fp, ps), ('long', ft, ts)]:
                if not is_valid or slack < ATR_MULT: continue
                if i + 1 >= len(df) - MAX_HOLD - 2: continue
                ep = float(df.iloc[i+1]['open'])
                tp_p = ep + atr*4.0 if direction == 'long' else ep - atr*4.0
                sl_p = ep - atr*2.0 if direction == 'long' else ep + atr*2.0
                size = CORE_SIZE if slack >= 1.4 else EXP_SIZE
                et = 'time'
                for j in range(i+2, min(i+2+MAX_HOLD, len(df))):
                    h = df['high'].iloc[j]; l = df['low'].iloc[j]
                    if direction == 'long':
                        if h >= tp_p: et = 'tp'; break
                        if l <= sl_p: et = 'sl'; break
                    else:
                        if l <= tp_p: et = 'tp'; break
                        if h >= sl_p: et = 'sl'; break
                pnl = (size*(atr*4.0/ep) if et == 'tp'
                       else -size*(atr*2.0/ep) if et == 'sl'
                       else size * TM_PCT)
                trades.append({'pnl': pnl, 'et': et, 'slack': slack,
                               'tier': 'core' if slack >= 1.4 else 'expanded'})
    return trades


def stats(trades):
    if not trades: return 0, 0, 0, 0, 0
    arr = np.array([t['pnl'] for t in trades])
    n = len(arr); w = arr[arr > 0]; l = arr[arr < 0]
    wr  = round(len(w) / n * 100, 1)
    pf  = round(float(sum(w) / max(abs(sum(l)), 0.01)), 2)
    ev  = round(float(np.mean(arr)), 2)
    tot = round(float(sum(arr)), 2)
    return n, wr, pf, ev, tot


# ── Run all months ────────────────────────────────────────────────
print('Running...')
rows = []
for mo, cache in [(m, cache25) for m in MOS_25] + [(m, cache26) for m in MOS_26]:
    t23 = run_b23_month(mo, cache)
    t22 = run_b22_month(mo, cache)
    n23, wr23, pf23, ev23, pnl23 = stats(t23)
    n22, wr22, pf22, ev22, pnl22 = stats(t22)
    rows.append({'mo': mo, 'n23': n23, 'wr23': wr23, 'pf23': pf23,
                 'ev23': ev23, 'pnl23': pnl23,
                 'n22': n22, 'wr22': wr22, 'pf22': pf22,
                 'ev22': ev22, 'pnl22': pnl22})

MO_LABELS = {
    'Jan':'Jan 25','Feb':'Feb 25','Mar':'Mar 25','Apr':'Apr 25',
    'May':'May 25','Jun':'Jun 25','Jul':'Jul 25','Aug':'Aug 25',
    'Sep':'Sep 25','Oct':'Oct 25','Nov':'Nov 25','Dec':'Dec 25',
    'Jan 26':'Jan 26','Feb 26':'Feb 26','Mar 26':'Mar 26',
    'Apr 26':'Apr 26','May 26':'May 26',
}

# ── Print table ────────────────────────────────────────────────────
print()
print('=' * 100)
print('  BOOF 23 vs BOOF 22 — BOOFINGTON (AAPL/NVDA/META/GOOGL/AMD) — 2025 + 2026 YTD')
print('  Boof 23: ZigZag swing reversal + RVOL + Mother Bar | Core $600 / Expanded $200')
print('  Boof 22: Fractal ATR reversal + Volume Cluster SR  | Core $600 / Expanded $200')
print('=' * 100)
print(f'  {"Month":<9} | {"":^44} | {"":^44} | {"Win"}')
print(f'  {"":9} | {"--- BOOF 23 (ZigZag) ---":^44} | {"--- BOOF 22 (Fractal) ---":^44} |')
print(f'  {"":9} | {"Trades":>7}{"WR%":>6}{"PF":>7}{"EV$":>7}{"P&L":>14} | {"Trades":>7}{"WR%":>6}{"PF":>7}{"EV$":>7}{"P&L":>14} |')
print(f'  {"-"*98}')

cum23 = 0; cum22 = 0
yr25_23 = 0; yr25_22 = 0

for r in rows:
    label = MO_LABELS.get(r['mo'], r['mo'])
    cum23 += r['pnl23']; cum22 += r['pnl22']
    if '26' not in label:
        yr25_23 += r['pnl23']; yr25_22 += r['pnl22']
    winner = 'B23' if r['pnl23'] > r['pnl22'] else 'B22'
    m23 = '**' if winner == 'B23' else '  '
    m22 = '**' if winner == 'B22' else '  '
    print(f'  {label:<9} |{m23}{r["n23"]:>6}{r["wr23"]:>6}{r["pf23"]:>7}{r["ev23"]:>7}  ${r["pnl23"]:>10,.0f} |{m22}{r["n22"]:>6}{r["wr22"]:>6}{r["pf22"]:>7}{r["ev22"]:>7}  ${r["pnl22"]:>10,.0f} | {winner}')
    if label == 'Dec 25':
        print(f'  {"2025 TOT":<9} | {"":>8}{"":>6}{"":>7}{"":>7}  ${yr25_23:>10,.0f} | {"":>8}{"":>6}{"":>7}{"":>7}  ${yr25_22:>10,.0f} |')
        print(f'  {"-"*98}')

yr26_23 = cum23 - yr25_23; yr26_22 = cum22 - yr25_22
print(f'  {"2026 YTD":<9} | {"":>8}{"":>6}{"":>7}{"":>7}  ${yr26_23:>10,.0f} | {"":>8}{"":>6}{"":>7}{"":>7}  ${yr26_22:>10,.0f} |')
print(f'  {"="*98}')
print(f'  {"TOTAL":<9} | {"":>8}{"":>6}{"":>7}{"":>7}  ${cum23:>10,.0f} | {"":>8}{"":>6}{"":>7}{"":>7}  ${cum22:>10,.0f} |')

# ── Aggregate stats ────────────────────────────────────────────────
def agg_stats(rows, key_n, key_wr, key_pf, key_ev, key_pnl, total_days):
    total_n   = sum(r[key_n] for r in rows)
    total_pnl = sum(r[key_pnl] for r in rows)
    avg_wr    = round(np.mean([r[key_wr] for r in rows if r[key_n] > 0]), 1)
    avg_pf    = round(np.mean([r[key_pf] for r in rows if r[key_n] > 0]), 2)
    avg_ev    = round(np.mean([r[key_ev] for r in rows if r[key_n] > 0]), 2)
    mo_arr    = np.array([r[key_pnl] for r in rows])
    cum       = np.cumsum(mo_arr)
    max_dd    = round(float((np.maximum.accumulate(cum) - cum).max()))
    green     = sum(1 for r in rows if r[key_pnl] > 0)
    return total_n, total_pnl, avg_wr, avg_pf, avg_ev, max_dd, green

n_mos = len(rows)
total_days = DAYS_25 + DAYS_26

print()
print('=' * 100)
print(f'  AGGREGATE SUMMARY ({n_mos} months: Jan 2025 – May 2026)')
print('=' * 100)

for label, keys in [
    ('BOOF 23 (ZigZag swing)', ('n23','wr23','pf23','ev23','pnl23')),
    ('BOOF 22 (Fractal ATR)',  ('n22','wr22','pf22','ev22','pnl22')),
]:
    n, tot, wr, pf, ev, dd, green = agg_stats(rows, *keys, total_days)
    mo_avg = round(tot / n_mos)
    tpd = round(n / total_days, 1)
    print(f'\n  {label}')
    print(f'    Trades:        {n:,}  ({tpd}/day)')
    print(f'    Win Rate:      {wr}%')
    print(f'    Profit Factor: {pf}')
    print(f'    EV/trade:      ${ev}')
    print(f'    Total P&L:     ${tot:,.0f}')
    print(f'    Monthly avg:   ${mo_avg:,}')
    print(f'    Max Drawdown:  ${dd:,}  (monthly peak-to-trough)')
    print(f'    Green months:  {green}/{n_mos}')

print()
print(f'  COMBINED: ${cum23 + cum22:,.0f} total | ${round((cum23+cum22)/n_mos):,}/mo avg')
print('=' * 100)
