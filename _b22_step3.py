"""
STEP 3 — Trend continuation allowance via VWAP bias
Instead of exiting on ATR compression, hold if price still on correct side of VWAP.
Tests: hold if VWAP aligned, exit only if VWAP flips against trade.
"""
import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              FRACTAL_BARS, ATR_LEN, VOL_LEN, SR_DIST_MAX)

TRADE=200; TM=0.08; MAX_HOLD=30; ATR_SL=2.0; ATR_TP=4.0; F=FRACTAL_BARS
ATR_MULT_ENTRY=1.4
SYMS=['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
MOS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

print('Loading cache...')
dfs = pickle.load(open('_boof22_cache.pkl','rb'))

def vwap(df):
    tp = (df['high'] + df['low'] + df['close']) / 3
    vol = df['volume']
    return (tp * vol).cumsum() / vol.cumsum()

print('Pre-computing signals with VWAP context...')
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
        df['vwap'] = vwap(df)
        cp, _ = build_cluster_array(df, atr_s, 1.3)
        highs=df['high'].values; lows=df['low'].values
        closes=df['close'].values; vwaps=df['vwap'].values

        for i in range(VOL_LEN + ATR_LEN + F, len(df) - F - MAX_HOLD - 2):
            row = df.iloc[i]
            if row['rvol'] < 80: continue
            atr = row['atr']
            if pd.isna(atr) or atr == 0 or not row['hi_vol']: continue
            if nearest_sr_distance(row['close'], cp, atr) > SR_DIST_MAX: continue

            lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
            ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
            fp=(highs[i]>lh.max())and(highs[i]>rh.max())
            ft=(lows[i]<ll.min()) and(lows[i]<rl.min())
            arp=closes[i]<highs[i]-atr*ATR_MULT_ENTRY
            arb=closes[i]>lows[i]+atr*ATR_MULT_ENTRY
            if fp and arp: d='short'
            elif ft and arb: d='long'
            else: continue

            if i+1 >= len(df)-MAX_HOLD-2: continue
            ep = float(df.iloc[i+1]['open'])
            slice_h = df['high'].iloc[i+2:i+2+MAX_HOLD+5].values
            slice_l = df['low'].iloc[i+2:i+2+MAX_HOLD+5].values
            slice_c = df['close'].iloc[i+2:i+2+MAX_HOLD+5].values
            slice_v = vwaps[i+2:i+2+MAX_HOLD+5]
            if len(slice_c) == 0: continue
            signals.append({'ep':ep,'atr':atr,'d':d,
                            'highs':slice_h,'lows':slice_l,'closes':slice_c,'vwaps':slice_v})

print(f'Signals: {len(signals):,}\n')

def sim_vwap(signals, vwap_grace=0, max_hold_ext=0):
    """
    Standard ATR TP/SL exits BUT:
    - if TP not yet hit AND price still on correct VWAP side → extend hold by max_hold_ext bars
    - vwap_grace: allow price to be this many bars on wrong side before exiting
    """
    pnls = []
    for s in signals:
        ep=s['ep']; atr=s['atr']; d=s['d']
        h=s['highs']; l=s['lows']; c=s['closes']; v=s['vwaps']
        tp_p=ep+atr*ATR_TP if d=='long' else ep-atr*ATR_TP
        sl_p=ep-atr*ATR_SL if d=='long' else ep+atr*ATR_SL
        wrong_side=0; et='time'; exit_px=c[-1] if len(c)>0 else ep
        limit = min(MAX_HOLD + max_hold_ext, len(c))
        for i in range(limit):
            hi=h[i]; lo=l[i]; cl=c[i]; vw=v[i] if i<len(v) else v[-1]
            if d=='long':
                if hi>=tp_p: et='tp'; exit_px=tp_p; break
                if lo<=sl_p: et='sl'; exit_px=sl_p; break
                # VWAP alignment check
                if cl < vw:  # price dropped below VWAP — wrong side
                    wrong_side += 1
                    if wrong_side > vwap_grace:
                        et='vwap'; exit_px=cl; break
                else:
                    wrong_side = 0
            else:
                if lo<=tp_p: et='tp'; exit_px=tp_p; break
                if hi>=sl_p: et='sl'; exit_px=sl_p; break
                if cl > vw:  # price above VWAP for short — wrong side
                    wrong_side += 1
                    if wrong_side > vwap_grace:
                        et='vwap'; exit_px=cl; break
                else:
                    wrong_side = 0
            if i >= limit-1: et='time'; exit_px=cl; break

        pnl = TRADE*(exit_px-ep)/ep if d=='long' else TRADE*(ep-exit_px)/ep
        pnls.append(pnl)
    return np.array(pnls)

def baseline(signals):
    pnls=[]
    for s in signals:
        ep=s['ep']; atr=s['atr']; d=s['d']
        h=s['highs']; l=s['lows']; c=s['closes']
        tp_p=ep+atr*ATR_TP if d=='long' else ep-atr*ATR_TP
        sl_p=ep-atr*ATR_SL if d=='long' else ep+atr*ATR_SL
        et='time'; ep_x=c[-1] if len(c)>0 else ep
        for i in range(min(MAX_HOLD,len(c))):
            if d=='long':
                if h[i]>=tp_p: et='tp'; ep_x=tp_p; break
                if l[i]<=sl_p: et='sl'; ep_x=sl_p; break
            else:
                if l[i]<=tp_p: et='tp'; ep_x=tp_p; break
                if h[i]>=sl_p: et='sl'; ep_x=sl_p; break
        pnls.append(TRADE*(ep_x-ep)/ep if d=='long' else TRADE*(ep-ep_x)/ep)
    return np.array(pnls)

def stats(arr):
    n=len(arr); w=arr[arr>0]; l=arr[arr<0]
    return (round(len(w)/n*100,1),
            round(float(sum(w)/max(abs(sum(l)),0.01)),2),
            round(float(np.mean(arr)),2),
            round(float(sum(arr))),
            round(float((np.maximum.accumulate(np.cumsum(arr))-np.cumsum(arr)).max())))

base=baseline(signals)
bwr,bpf,bev,bann,bdd=stats(base)

print(f'{"="*78}')
print(f'STEP 3 — VWAP Trend Continuation Filter')
print(f'{"="*78}')
print(f'BASELINE (4x ATR TP, 2x SL, no VWAP): WR={bwr}%  PF={bpf}  EV=${bev}  Annual=${bann:,}  MaxDD=${bdd}')
print(f'\n{"Grace bars":<13}{"Ext hold":<12}{"WR%":>6}{"PF":>7}{"EV$":>8}{"Annual$":>11}{"MaxDD$":>9}{"delta":>10}')
print(f'{"-"*78}')

results=[]
for grace in [0, 1, 2, 3, 5]:
    for ext in [0, 5, 10, 15]:
        arr=sim_vwap(signals, vwap_grace=grace, max_hold_ext=ext)
        wr,pf,ev,ann,dd=stats(arr)
        delta=ann-bann
        sign='+' if delta>=0 else ''
        results.append((grace,ext,wr,pf,ev,ann,dd,delta))
        print(f'{grace:<13}{ext:<12}{wr:>6}{pf:>7}{ev:>8}  ${ann:>9,}  ${dd:>7,}  {sign}${delta:,}')

print(f'\n{"─"*78}')
print('TOP 5 BY ANNUAL P&L:')
for r in sorted(results,key=lambda x:-x[5])[:5]:
    print(f'  grace={r[0]}bars ext={r[1]}bars  WR={r[2]}%  PF={r[3]}  EV=${r[4]}  Annual=${r[5]:,}  MaxDD=${r[6]:,}  delta={"+" if r[7]>=0 else ""}${r[7]:,}')
