"""
Boof 21 — rank ALL symbols in 2025 cache, find BOOFINATOR list
Then compare best Boof 21 lineup vs BOOFINGTON (Boof 22)
"""
import pickle, sys, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof21 import backtest as b21
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              FRACTAL_BARS, ATR_LEN, VOL_LEN, SR_DIST_MAX, BOOFINGTON)
import pandas as pd

TRADE=250; TP=0.35; SL=-0.10; TM=0.08
DAYS=252

cache25 = pickle.load(open('_boof21_cache.pkl','rb'))
MOS = ['Jan 25','Feb 25','Mar 25','Apr 25','May 25','Jun 25',
       'Jul 25','Aug 25','Sep 25','Oct 25','Nov 25','Dec 25']

ALL_SYMS = sorted(set(k[0] for k in cache25.keys()))
print(f'Symbols in cache: {ALL_SYMS}')

# ── Boof 21 per-symbol rank ────────────────────────────────────────
print('\nRunning Boof 21 per-symbol...')
b21_stats = {}
for sym in ALL_SYMS:
    pnls=[]; tp_n=sl_n=tm_n=0
    for mo in MOS:
        df = cache25.get((sym, mo))
        if df is None or len(df)<100: continue
        try: raw = b21(df, symbol=sym)
        except: continue
        for t in raw:
            et = t.get('exit_type','time')
            pnl = (TRADE*TP if et=='tp' else TRADE*SL if et=='stop' else TRADE*TM)
            pnls.append(pnl)
            if et=='tp': tp_n+=1
            elif et=='stop': sl_n+=1
            else: tm_n+=1
    if not pnls: continue
    arr=np.array(pnls); n=len(arr)
    w=arr[arr>0]; l=arr[arr<0]
    wr=round(len(w)/n*100,1)
    pf=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
    ev=round(float(np.mean(arr)),2)
    annual=round(float(sum(arr)))
    tpd=round(n/DAYS,1)
    b21_stats[sym]={'n':n,'tpd':tpd,'wr':wr,'pf':pf,'ev':ev,'annual':annual,
                    'tp':tp_n,'sl':sl_n,'tm':tm_n}

# Sort by annual P&L
ranked = sorted(b21_stats.items(), key=lambda x: -x[1]['annual'])

print(f'\nBoof 21 — All Symbols — 2025 Full Year')
print(f'  {"Sym":<7}{"Trades":>8}{"T/day":>7}{"WR%":>7}{"PF":>7}{"EV$":>8}{"Annual$":>12}  {"TP/SL/TM"}')
print(f'  {"-"*72}')
for sym,s in ranked:
    print(f'  {sym:<7}{s["n"]:>8}{s["tpd"]:>7}{s["wr"]:>7}{s["pf"]:>7}{s["ev"]:>8}  ${s["annual"]:>9,}  {s["tp"]}/{s["sl"]}/{s["tm"]}')

# ── Define BOOFINATOR = top performers ────────────────────────────
top5 = [sym for sym,_ in ranked[:5]]
top7 = [sym for sym,_ in ranked[:7]]
noetf = [sym for sym,s in ranked if sym not in ('QQQ','SPY')][:5]

print(f'\n  Top 5:       {top5}  -> ${sum(b21_stats[s]["annual"] for s in top5):,}/yr')
print(f'  Top 7:       {top7}  -> ${sum(b21_stats[s]["annual"] for s in top7):,}/yr')
print(f'  Top 5 no-ETF:{noetf}  -> ${sum(b21_stats[s]["annual"] for s in noetf):,}/yr')

# ── Boof 22 BOOFINGTON 2025 for comparison ─────────────────────────
print(f'\nRunning Boof 22 BOOFINGTON 2025...')
MOS_22 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
F=FRACTAL_BARS; ATR_MULT=0.6

b22_pnls=[]
for mo in MOS_22:
    for sym in BOOFINGTON:
        vm=1.2 if sym=='AAPL' else 1.3
        df=cache25.get((sym,mo))
        if df is None or len(df)<100: continue
        df=df.copy().reset_index(drop=True)
        atr_s=compute_atr(df); df['atr']=atr_s
        df['vol_sma']=df['volume'].rolling(VOL_LEN).mean()
        df['rvol']=(df['volume']/df['vol_sma']*100).fillna(0)
        df['hi_vol']=df['volume']>df['vol_sma']*vm
        cp,_=build_cluster_array(df,atr_s,vm)
        highs=df['high'].values; lows=df['low'].values; closes=df['close'].values
        for i in range(VOL_LEN+ATR_LEN+F, len(df)-F-30-3):
            row=df.iloc[i]
            if row['rvol']<80: continue
            atr=row['atr']
            if pd.isna(atr) or atr==0 or not row['hi_vol']: continue
            if nearest_sr_distance(row['close'],cp,atr)>SR_DIST_MAX: continue
            lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
            ll=lows[i-F:i]; rl=lows[i+1:i+F+1]
            fp=(highs[i]>lh.max())and(highs[i]>rh.max())
            ft=(lows[i]<ll.min())and(lows[i]<rl.min())
            ps=(highs[i]-closes[i])/atr; ts=(closes[i]-lows[i])/atr
            for direction,is_valid,slack in [('short',fp,ps),('long',ft,ts)]:
                if not is_valid or slack<ATR_MULT: continue
                if i+1>=len(df)-30-2: continue
                ep=float(df.iloc[i+1]['open'])
                tp_p=ep+atr*4.0 if direction=='long' else ep-atr*4.0
                sl_p=ep-atr*2.0 if direction=='long' else ep+atr*2.0
                size=600 if slack>=1.4 else 200
                et='time'
                for j in range(i+2,min(i+2+30,len(df))):
                    h=df['high'].iloc[j]; l=df['low'].iloc[j]
                    if direction=='long':
                        if h>=tp_p: et='tp'; break
                        if l<=sl_p: et='sl'; break
                    else:
                        if l<=tp_p: et='tp'; break
                        if h>=sl_p: et='sl'; break
                pnl=(size*(atr*4.0/ep) if et=='tp' else -size*(atr*2.0/ep) if et=='sl' else size*0.08)
                b22_pnls.append(pnl)

b22=np.array(b22_pnls)
b22_ann=round(float(sum(b22)))
b22_mo=round(b22_ann/12)
b22_wr=round(len(b22[b22>0])/len(b22)*100,1)
b22_n=len(b22)

# ── Head-to-head summary ───────────────────────────────────────────
print(f'\n{"="*70}')
print(f'  HEAD-TO-HEAD — 2025 Full Year')
print(f'{"="*70}')
print(f'  {"Config":<35}  {"Annual":>10}  {"Monthly":>9}  {"T/day":>7}  {"WR%"}')
print(f'  {"-"*68}')

for label, syms in [('B21 Top 5',top5),('B21 Top 7',top7),('B21 Top 5 no-ETF',noetf),('B21 QQQ+SPY only',['QQQ','SPY'])]:
    ann=sum(b21_stats.get(s,{}).get('annual',0) for s in syms)
    n=sum(b21_stats.get(s,{}).get('n',0) for s in syms)
    tpd=round(n/DAYS,1)
    avg_wr=round(np.mean([b21_stats[s]['wr'] for s in syms if s in b21_stats]),1)
    print(f'  {label:<35}  ${ann:>9,}  ${ann//12:>8,}  {tpd:>7}  {avg_wr}%')

print(f'  {"B22 BOOFINGTON (5 sym, tiered)":<35}  ${b22_ann:>9,}  ${b22_mo:>8,}  {round(b22_n/DAYS,1):>7}  {b22_wr}%')
print(f'{"="*70}')
