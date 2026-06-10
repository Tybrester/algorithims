"""
STEP 1 — Widen ATR confirmation threshold on signal detection
Vectorized: collect all candidate signals once, then filter by mult threshold.
atr_mult controls: close < high - atr*mult (peak) / close > low + atr*mult (trough)
Current = 1.4. Testing 0.6 → 2.0.
"""
import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              FRACTAL_BARS, ATR_LEN, VOL_LEN, SR_DIST_MAX)

TRADE=200; TM=0.08; MAX_HOLD=30; ATR_TP=4.0; ATR_SL=2.0; F=FRACTAL_BARS
SYMS=['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
MOS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

print('Loading cache...')
dfs = pickle.load(open('_boof22_cache.pkl','rb'))

# ── Collect ALL candidate bars once with raw ATR slack values stored ──
print('Pre-computing candidate signals (one pass)...')
candidates = []  # (direction, atr_slack_ratio, ep, atr, pnl_tp, pnl_sl)

for mo in MOS:
    for sym in SYMS:
        df = dfs.get((sym, mo))
        if df is None or len(df) < 100: continue
        df = df.copy().reset_index(drop=True)
        atr_s = compute_atr(df); df['atr'] = atr_s
        df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
        df['rvol'] = (df['volume'] / df['vol_sma'] * 100).fillna(0)
        df['hi_vol'] = df['volume'] > df['vol_sma'] * 1.3
        cp, _ = build_cluster_array(df, atr_s, 1.3)
        highs = df['high'].values; lows = df['low'].values; closes = df['close'].values

        for i in range(VOL_LEN + ATR_LEN + F, len(df) - F - MAX_HOLD - 2):
            row = df.iloc[i]
            if row['rvol'] < 80: continue
            atr = row['atr']
            if pd.isna(atr) or atr == 0 or not row['hi_vol']: continue
            if nearest_sr_distance(row['close'], cp, atr) > SR_DIST_MAX: continue

            lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
            ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
            fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
            ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())

            if not fp and not ft: continue

            # Store the raw wick slack as ATR multiples — filter by mult later
            peak_slack   = (highs[i] - closes[i]) / atr  # > mult → peak confirmed
            trough_slack = (closes[i] - lows[i])  / atr  # > mult → trough confirmed

            if i + 1 >= len(df) - MAX_HOLD - 2: continue
            ep = float(df.iloc[i+1]['open'])

            # Pre-compute exit outcome for this signal (direction-agnostic for tp/sl lookup)
            # Store both long and short outcome — filter by direction after
            for direction, is_valid, slack in [
                ('short', fp, peak_slack),
                ('long',  ft, trough_slack),
            ]:
                if not is_valid: continue
                tp_p = ep + atr*ATR_TP if direction=='long' else ep - atr*ATR_TP
                sl_p = ep - atr*ATR_SL if direction=='long' else ep + atr*ATR_SL
                et = 'time'
                for j in range(i+2, min(i+2+MAX_HOLD, len(df))):
                    h = df['high'].iloc[j]; l = df['low'].iloc[j]
                    if direction == 'long':
                        if h >= tp_p: et='tp'; break
                        if l <= sl_p: et='sl'; break
                    else:
                        if l <= tp_p: et='tp'; break
                        if h >= sl_p: et='sl'; break
                pnl = (TRADE*(atr*ATR_TP/ep) if et=='tp'
                       else -TRADE*(atr*ATR_SL/ep) if et=='sl'
                       else TRADE*TM)
                candidates.append((slack, pnl))

print(f'Total raw candidates: {len(candidates):,}\n')
slacks = np.array([c[0] for c in candidates])
pnls_all = np.array([c[1] for c in candidates])

results = []
print(f'{"="*72}')
print(f'STEP 1 — ATR Confirmation Threshold | $200/trade | Full 2025')
print(f'{"="*72}')
print(f'{"Mult":<7}{"Signals":>8}{"WR%":>7}{"PF":>7}{"EV$":>8}{"Annual$":>11}{"MaxDD$":>9}')
print(f'{"-"*72}')

for mult in [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.6, 1.8, 2.0]:
    mask = slacks >= mult
    arr = pnls_all[mask]; n = len(arr)
    if n == 0: print(f'{mult:<7}{"0":>8}'); continue
    w = arr[arr>0]; l = arr[arr<0]
    wr  = round(len(w)/n*100, 1)
    pf  = round(float(sum(w)/max(abs(sum(l)),0.01)), 2)
    ev  = round(float(np.mean(arr)), 2)
    ann = round(float(sum(arr)))
    cum = np.cumsum(arr); dd = round(float((np.maximum.accumulate(cum)-cum).max()))
    note = ' ← CURRENT' if mult == 1.4 else ''
    results.append((mult, n, wr, pf, ev, ann, dd))
    print(f'{mult:<7}{n:>8,}{wr:>7}{pf:>7}{ev:>8}  ${ann:>9,}  ${dd:>7,}{note}')

print(f'\n{"─"*72}')
print('TOP 3 BY ANNUAL P&L:')
for r in sorted(results, key=lambda x: -x[5])[:3]:
    print(f'  mult={r[0]}  signals={r[1]:,}  WR={r[2]}%  PF={r[3]}  EV=${r[4]}  Annual=${r[5]:,}  MaxDD=${r[6]:,}')
print('TOP 3 BY PF:')
for r in sorted(results, key=lambda x: -x[3])[:3]:
    print(f'  mult={r[0]}  signals={r[1]:,}  WR={r[2]}%  PF={r[3]}  EV=${r[4]}  Annual=${r[5]:,}  MaxDD=${r[6]:,}')
print('TOP 3 BY EV/TRADE:')
for r in sorted(results, key=lambda x: -x[4])[:3]:
    print(f'  mult={r[0]}  signals={r[1]:,}  WR={r[2]}%  PF={r[3]}  EV=${r[4]}  Annual=${r[5]:,}  MaxDD=${r[6]:,}')
