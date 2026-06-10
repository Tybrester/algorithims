"""
STEP 4 — Hybrid Exit: SL + ATR stagnation + VWAP flip + time (no fixed TP)
Best structure: exit ONLY if:
  (A) SL hit, OR
  (B) ATR stagnation (no new best for N bars), OR
  (C) VWAP flips against trade for G bars, OR
  (D) Time stop (backup only)
Tests best combos from Steps 2+3 together, plus combined grid.
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
    tp=(df['high']+df['low']+df['close'])/3
    return (tp*df['volume']).cumsum()/df['volume'].cumsum()

print('Pre-computing signals...')
signals=[]
for mo in MOS:
    for sym in SYMS:
        df=dfs.get((sym,mo))
        if df is None or len(df)<100: continue
        df=df.copy().reset_index(drop=True)
        atr_s=compute_atr(df); df['atr']=atr_s
        df['vol_sma']=df['volume'].rolling(VOL_LEN).mean()
        df['rvol']=(df['volume']/df['vol_sma']*100).fillna(0)
        df['hi_vol']=df['volume']>df['vol_sma']*1.3
        df['vwap']=vwap(df)
        cp,_=build_cluster_array(df,atr_s,1.3)
        highs=df['high'].values; lows=df['low'].values
        closes=df['close'].values; vwaps=df['vwap'].values

        for i in range(VOL_LEN+ATR_LEN+F, len(df)-F-MAX_HOLD-2):
            row=df.iloc[i]
            if row['rvol']<80: continue
            atr=row['atr']
            if pd.isna(atr) or atr==0 or not row['hi_vol']: continue
            if nearest_sr_distance(row['close'],cp,atr)>SR_DIST_MAX: continue
            lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
            ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
            fp=(highs[i]>lh.max())and(highs[i]>rh.max())
            ft=(lows[i]<ll.min()) and(lows[i]<rl.min())
            arp=closes[i]<highs[i]-atr*ATR_MULT_ENTRY
            arb=closes[i]>lows[i]+atr*ATR_MULT_ENTRY
            if fp and arp: d='short'
            elif ft and arb: d='long'
            else: continue
            if i+1>=len(df)-MAX_HOLD-2: continue
            ep=float(df.iloc[i+1]['open'])
            s=i+2; e=min(s+MAX_HOLD+10,len(df))
            signals.append({'ep':ep,'atr':atr,'d':d,
                            'highs':df['high'].values[s:e],
                            'lows':df['low'].values[s:e],
                            'closes':closes[s:e],
                            'vwaps':vwaps[s:e]})

print(f'Signals: {len(signals):,}\n')

def sim_hybrid(signals, stall_bars, stall_thresh, vwap_grace, use_tp=False):
    """
    Hybrid exit logic:
      - SL: always tight (2x ATR)
      - Stagnation: no new best for stall_bars AND move < stall_thresh*ATR
      - VWAP: exit if on wrong side for vwap_grace bars
      - Time: hard cap at MAX_HOLD bars
      - Optional fixed TP cap (use_tp=True adds 4x ATR TP as upper bound)
    """
    pnls=[]
    for s in signals:
        ep=s['ep']; atr=s['atr']; d=s['d']
        h=s['highs']; l=s['lows']; c=s['closes']; v=s['vwaps']
        sl_p=ep-atr*ATR_SL if d=='long' else ep+atr*ATR_SL
        tp_p=(ep+atr*ATR_TP if d=='long' else ep-atr*ATR_TP) if use_tp else None
        best=ep; stall=0; wrong_vwap=0
        et='time'; exit_px=c[-1] if len(c)>0 else ep

        for i in range(min(MAX_HOLD,len(c))):
            hi=h[i]; lo=l[i]; cl=c[i]; vw=v[i] if i<len(v) else (v[-1] if len(v)>0 else cl)

            # SL
            if d=='long' and lo<=sl_p: et='sl'; exit_px=sl_p; break
            if d=='short' and hi>=sl_p: et='sl'; exit_px=sl_p; break

            # Optional TP cap
            if use_tp and tp_p:
                if d=='long' and hi>=tp_p: et='tp'; exit_px=tp_p; break
                if d=='short' and lo<=tp_p: et='tp'; exit_px=tp_p; break

            # Track best (progress)
            new_best = hi if d=='long' else -lo
            cur_best = best if d=='long' else -best
            if new_best > cur_best + atr*stall_thresh:
                best = hi if d=='long' else lo
                stall=0
            else:
                stall+=1

            if stall>=stall_bars:
                et='stall'; exit_px=cl; break

            # VWAP alignment
            if d=='long':
                wrong_vwap = (wrong_vwap+1) if cl<vw else 0
            else:
                wrong_vwap = (wrong_vwap+1) if cl>vw else 0
            if wrong_vwap>vwap_grace:
                et='vwap'; exit_px=cl; break

        pnl=TRADE*(exit_px-ep)/ep if d=='long' else TRADE*(ep-exit_px)/ep
        pnls.append(pnl)
    return np.array(pnls)

def baseline(signals):
    pnls=[]
    for s in signals:
        ep=s['ep']; atr=s['atr']; d=s['d']
        h=s['highs']; l=s['lows']; c=s['closes']
        tp_p=ep+atr*ATR_TP if d=='long' else ep-atr*ATR_TP
        sl_p=ep-atr*ATR_SL if d=='long' else ep+atr*ATR_SL
        et='time'; epx=c[-1] if len(c)>0 else ep
        for i in range(min(MAX_HOLD,len(c))):
            if d=='long':
                if h[i]>=tp_p: et='tp'; epx=tp_p; break
                if l[i]<=sl_p: et='sl'; epx=sl_p; break
            else:
                if l[i]<=tp_p: et='tp'; epx=tp_p; break
                if h[i]>=sl_p: et='sl'; epx=sl_p; break
        pnls.append(TRADE*(epx-ep)/ep if d=='long' else TRADE*(ep-epx)/ep)
    return np.array(pnls)

def stats(arr):
    n=len(arr); w=arr[arr>0]; l=arr[arr<0]
    wr=round(len(w)/n*100,1)
    pf=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
    ev=round(float(np.mean(arr)),2)
    ann=round(float(sum(arr)))
    cum=np.cumsum(arr); dd=round(float((np.maximum.accumulate(cum)-cum).max()))
    return wr,pf,ev,ann,dd

base=baseline(signals)
bwr,bpf,bev,bann,bdd=stats(base)
print(f'{"="*82}')
print(f'STEP 4 — Hybrid Exit (SL + Stagnation + VWAP + Time)')
print(f'{"="*82}')
print(f'BASELINE (4x ATR TP, 2x SL): WR={bwr}%  PF={bpf}  EV=${bev}  Annual=${bann:,}  MaxDD=${bdd}')
print(f'\n{"Stall":>6}{"Thresh":>8}{"VWgrace":>9}{"TP cap":>8}{"WR%":>6}{"PF":>7}{"EV$":>7}{"Annual$":>11}{"MaxDD$":>9}{"delta":>10}')
print(f'{"-"*82}')

results=[]
# Test key combos — best from step2 (stall=15, thresh=0.2) + best from step3 (grace=1)
# Plus a grid of combinations
combos=[
    # (stall_bars, stall_thresh, vwap_grace, use_tp)
    (10, 0.1,  0, False),
    (10, 0.2,  0, False),
    (15, 0.2,  0, False),
    (15, 0.2,  1, False),
    (15, 0.2,  2, False),
    (15, 0.2,  3, False),
    (10, 0.2,  1, False),
    (10, 0.2,  2, False),
    (8,  0.2,  1, False),
    (8,  0.2,  2, False),
    (5,  0.2,  1, False),
    # With TP cap added back in
    (10, 0.2,  1, True),
    (15, 0.2,  1, True),
    (15, 0.2,  2, True),
    (10, 0.1,  1, True),
    (8,  0.2,  2, True),
    (5,  0.3,  2, True),
    (20, 0.2,  3, True),
    (20, 0.1,  2, True),
    (25, 0.2,  2, True),
]
for stall,thresh,grace,use_tp in combos:
    arr=sim_hybrid(signals,stall,thresh,grace,use_tp)
    wr,pf,ev,ann,dd=stats(arr)
    delta=ann-bann; sign='+' if delta>=0 else ''
    tp_str='yes' if use_tp else 'no'
    results.append((stall,thresh,grace,use_tp,wr,pf,ev,ann,dd,delta))
    print(f'{stall:>6}{thresh:>8}{grace:>9}{tp_str:>8}{wr:>6}{pf:>7}{ev:>7}  ${ann:>9,}  ${dd:>7,}  {sign}${delta:,}')

print(f'\n{"─"*82}')
print('TOP 5 BY ANNUAL P&L:')
for r in sorted(results,key=lambda x:-x[7])[:5]:
    tp_str='TP+' if r[3] else 'no TP'
    print(f'  stall={r[0]} thresh={r[1]} vwap_grace={r[2]} {tp_str}  WR={r[4]}%  PF={r[5]}  EV=${r[6]}  Annual=${r[7]:,}  MaxDD=${r[8]:,}  delta={"+" if r[9]>=0 else ""}${r[9]:,}')

print(f'\n{"─"*82}')
print(f'FINAL SUMMARY — best of each step vs baseline:')
print(f'{"─"*82}')
print(f'  Baseline (4xTP/2xSL fixed):       WR={bwr}%  PF={bpf}  EV=${bev}  Annual=${bann:,}')

# Step 1 best: lower atr_mult opens more signals — can't rerun here but note result
print(f'  Step 1 best (mult=0.6, more sig):  WR=60.2%  PF=22.84  EV=$5.11  Annual=$152,283  [more signals, same EV]')

best_s2=sorted(results,key=lambda x:-x[7])[0]
tp_s='TP cap' if best_s2[3] else 'no TP'
print(f'  Step 4 best hybrid:                WR={best_s2[4]}%  PF={best_s2[5]}  EV=${best_s2[6]}  Annual=${best_s2[7]:,}  ({tp_s}, stall={best_s2[0]}, thresh={best_s2[1]}, grace={best_s2[2]})')
