"""
STEP 2 — Split exits into TWO layers
Layer A: SL stays tight (2x ATR)
Layer B: TP uses ATR stagnation instead of fixed price target
  - Don't exit TP at a fixed price
  - Instead: hold until N bars of low movement (ATR contraction = stall)
  - OR price reverses > threshold ATR from recent high/low

Tests:
  stall_bars   = how many bars of no progress before exiting (3, 5, 8, 10)
  stall_thresh = what counts as "no progress" — move < X * ATR (0.1, 0.2, 0.3)
"""
import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              FRACTAL_BARS, ATR_LEN, VOL_LEN, SR_DIST_MAX)

TRADE=200; TM=0.08; MAX_HOLD=30; ATR_SL=2.0; F=FRACTAL_BARS
SYMS=['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
MOS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
ATR_MULT_ENTRY = 1.4  # keep signal confirmation at current level

print('Loading cache...')
dfs = pickle.load(open('_boof22_cache.pkl','rb'))

# Collect base signals with full bar slices
print('Pre-computing signals...')
signals = []
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
            arp = closes[i] < highs[i] - atr * ATR_MULT_ENTRY
            arb = closes[i] > lows[i]  + atr * ATR_MULT_ENTRY
            if fp and arp: d = 'short'
            elif ft and arb: d = 'long'
            else: continue

            if i + 1 >= len(df) - MAX_HOLD - 2: continue
            ep = float(df.iloc[i+1]['open'])
            bar_highs = df['high'].iloc[i+2 : i+2+MAX_HOLD+5].values
            bar_lows  = df['low'].iloc[i+2 : i+2+MAX_HOLD+5].values
            bar_close = df['close'].iloc[i+2 : i+2+MAX_HOLD+5].values
            if len(bar_close) == 0: continue
            signals.append({'ep': ep, 'atr': atr, 'd': d,
                            'highs': bar_highs, 'lows': bar_lows, 'closes': bar_close})

print(f'Signals: {len(signals):,}\n')

def sim_layer2(signals, stall_bars, stall_thresh):
    """
    Layer A: SL = entry - 2x ATR (unchanged)
    Layer B: No fixed TP price.
             Track best price (running max for long / min for short).
             Exit when no NEW best price for stall_bars consecutive bars
             AND the stall magnitude < stall_thresh * ATR
    """
    pnls = []
    for s in signals:
        ep = s['ep']; atr = s['atr']; d = s['d']
        highs = s['highs']; lows = s['lows']; closes = s['closes']
        sl_p = ep - atr*ATR_SL if d=='long' else ep + atr*ATR_SL

        best = ep  # track best price reached
        stall_count = 0
        et = 'time'; exit_px = closes[-1] if len(closes) > 0 else ep

        for i in range(len(closes)):
            hi = highs[i]; lo = lows[i]; cl = closes[i]

            # Layer A: SL check first
            if d == 'long' and lo <= sl_p:
                et = 'sl'; exit_px = sl_p; break
            if d == 'short' and hi >= sl_p:
                et = 'sl'; exit_px = sl_p; break

            # Track progress
            new_best = hi if d == 'long' else -lo
            curr_best = best if d == 'long' else -best

            if new_best > curr_best + atr * stall_thresh:
                best = hi if d == 'long' else lo
                stall_count = 0
            else:
                stall_count += 1

            if stall_count >= stall_bars:
                et = 'stall'; exit_px = cl; break

            if i >= MAX_HOLD - 1:
                et = 'time'; exit_px = cl; break

        if d == 'long':
            pnl = TRADE * (exit_px - ep) / ep
        else:
            pnl = TRADE * (ep - exit_px) / ep
        pnls.append(pnl)
    return np.array(pnls)

# Also run baseline (fixed ATR TP) for comparison
def sim_baseline(signals):
    pnls = []
    for s in signals:
        ep=s['ep']; atr=s['atr']; d=s['d']
        highs=s['highs']; lows=s['lows']; closes=s['closes']
        tp_p = ep+atr*4.0 if d=='long' else ep-atr*4.0
        sl_p = ep-atr*ATR_SL if d=='long' else ep+atr*ATR_SL
        et='time'; exit_px=closes[-1] if len(closes)>0 else ep
        for i in range(len(closes)):
            h=highs[i]; l=lows[i]
            if d=='long':
                if h>=tp_p: et='tp'; exit_px=tp_p; break
                if l<=sl_p: et='sl'; exit_px=sl_p; break
            else:
                if l<=tp_p: et='tp'; exit_px=tp_p; break
                if h>=sl_p: et='sl'; exit_px=sl_p; break
            if i>=MAX_HOLD-1: et='time'; exit_px=closes[i]; break
        pnls.append(TRADE*(exit_px-ep)/ep if d=='long' else TRADE*(ep-exit_px)/ep)
    return np.array(pnls)

def stats(arr, label):
    n=len(arr); w=arr[arr>0]; l=arr[arr<0]
    wr=round(len(w)/n*100,1)
    pf=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
    ev=round(float(np.mean(arr)),2)
    ann=round(float(sum(arr)))
    cum=np.cumsum(arr); dd=round(float((np.maximum.accumulate(cum)-cum).max()))
    return wr, pf, ev, ann, dd

print(f'{"="*78}')
print(f'STEP 2 — Dual-Layer Exit: tight SL (2x ATR) + ATR stagnation TP')
print(f'{"="*78}')

base = sim_baseline(signals)
bwr,bpf,bev,bann,bdd = stats(base,'baseline')
print(f'\n{"BASELINE (fixed 4x ATR TP)":<40} WR={bwr}%  PF={bpf}  EV=${bev}  Annual=${bann:,}  MaxDD=${bdd}')
print(f'\n{"Stall bars":<12}{"Stall thresh":<14}{"WR%":>6}{"PF":>7}{"EV$":>8}{"Annual$":>11}{"MaxDD$":>9}{"vs base":>10}')
print(f'{"-"*78}')

results = []
for stall_bars in [3, 5, 8, 10, 15]:
    for stall_thresh in [0.05, 0.1, 0.2, 0.3, 0.5]:
        arr = sim_layer2(signals, stall_bars, stall_thresh)
        wr,pf,ev,ann,dd = stats(arr,'')
        delta = ann - bann
        sign = '+' if delta >= 0 else ''
        results.append((stall_bars, stall_thresh, wr, pf, ev, ann, dd, delta))
        print(f'{stall_bars:<12}{stall_thresh:<14}{wr:>6}{pf:>7}{ev:>8}  ${ann:>9,}  ${dd:>7,}  {sign}${delta:,}')

print(f'\n{"─"*78}')
print('TOP 5 BY ANNUAL P&L (vs baseline):')
for r in sorted(results, key=lambda x: -x[5])[:5]:
    print(f'  stall={r[0]}bars thresh={r[1]}xATR  WR={r[2]}%  PF={r[3]}  EV=${r[4]}  Annual=${r[5]:,}  MaxDD=${r[6]:,}  delta=+${r[7]:,}')
