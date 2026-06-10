"""Quick per-symbol ranking for Boof 22 at atr_mult=0.6"""
import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              FRACTAL_BARS, ATR_LEN, VOL_LEN, SR_DIST_MAX)

TM=0.08; MAX_HOLD=30; ATR_SL=2.0; ATR_TP=4.0; F=FRACTAL_BARS; ATR_MULT=0.6
SYMS=['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
MOS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
DAYS=252

print('Loading...')
dfs = pickle.load(open('_boof22_cache.pkl','rb'))

results=[]
for sym in SYMS:
    pnls=[]; core_n=0; exp_n=0
    for mo in MOS:
        df=dfs.get((sym,mo))
        if df is None or len(df)<100: continue
        df=df.copy().reset_index(drop=True)
        atr_s=compute_atr(df); df['atr']=atr_s
        df['vol_sma']=df['volume'].rolling(VOL_LEN).mean()
        df['rvol']=(df['volume']/df['vol_sma']*100).fillna(0)
        df['hi_vol']=df['volume']>df['vol_sma']*1.3
        cp,_=build_cluster_array(df,atr_s,1.3)
        highs=df['high'].values; lows=df['low'].values; closes=df['close'].values
        for i in range(VOL_LEN+ATR_LEN+F, len(df)-F-MAX_HOLD-3):
            row=df.iloc[i]
            if row['rvol']<80: continue
            atr=row['atr']
            if pd.isna(atr) or atr==0 or not row['hi_vol']: continue
            if nearest_sr_distance(row['close'],cp,atr)>SR_DIST_MAX: continue
            lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
            ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
            fp=(highs[i]>lh.max())and(highs[i]>rh.max())
            ft=(lows[i]<ll.min()) and(lows[i]<rl.min())
            peak_slack=(highs[i]-closes[i])/atr
            trough_slack=(closes[i]-lows[i])/atr
            for direction,is_valid,slack in [('short',fp,peak_slack),('long',ft,trough_slack)]:
                if not is_valid: continue
                if ATR_MULT==0.6 and slack<0.6: continue
                if i+1>=len(df)-MAX_HOLD-2: continue
                ep=float(df.iloc[i+1]['open'])
                tp_p=ep+atr*ATR_TP if direction=='long' else ep-atr*ATR_TP
                sl_p=ep-atr*ATR_SL if direction=='long' else ep+atr*ATR_SL
                # size by slack
                size=600 if slack>=1.4 else 200
                if slack>=1.4: core_n+=1
                else: exp_n+=1
                et='time'
                for j in range(i+2,min(i+2+MAX_HOLD,len(df))):
                    h=df['high'].iloc[j]; l=df['low'].iloc[j]
                    if direction=='long':
                        if h>=tp_p: et='tp'; break
                        if l<=sl_p: et='sl'; break
                    else:
                        if l<=tp_p: et='tp'; break
                        if h>=sl_p: et='sl'; break
                pnl=(size*(atr*ATR_TP/ep) if et=='tp'
                     else -size*(atr*ATR_SL/ep) if et=='sl'
                     else size*TM)
                pnls.append(pnl)
    if not pnls: continue
    arr=np.array(pnls); n=len(arr)
    w=arr[arr>0]; l=arr[arr<0]
    wr=round(len(w)/n*100,1)
    pf=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
    ev=round(float(np.mean(arr)),2)
    annual=round(float(sum(arr)))
    tpd=round(n/DAYS,1)
    results.append((sym,n,tpd,core_n,exp_n,wr,pf,ev,annual))

results.sort(key=lambda x:-x[8])

print(f'\nBoof 22 | atr_mult=0.6 | Core=$600 Expanded=$200 | Full 2025')
print(f'{"Sym":<7}{"Trades":>8}{"T/day":>7}{"Core":>7}{"Exp":>7}{"WR%":>7}{"PF":>7}{"EV$":>8}{"Annual$":>12}')
print(f'{"-"*65}')
for r in results:
    print(f'{r[0]:<7}{r[1]:>8}{r[2]:>7}{r[3]:>7}{r[4]:>7}{r[5]:>7}{r[6]:>7}{r[7]:>8}  ${r[8]:>9,}')

print(f'\nTop 5 by annual:  {", ".join(r[0] for r in results[:5])}')
print(f'Bottom 4 by annual: {", ".join(r[0] for r in results[5:])}')
total_all = sum(r[8] for r in results)
top5 = sum(r[8] for r in results[:5])
print(f'\nAll 9 symbols annual: ${total_all:,}')
print(f'Top 5 symbols annual: ${top5:,} ({round(top5/total_all*100,1)}% of total)')
