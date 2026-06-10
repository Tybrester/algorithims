"""
Boof 21 vs Boof 22 — Full comparison Jan 2025 through May 2026
Monthly P&L, WR, EV, running total, head-to-head
Boof 22: BOOFINGTON (AAPL, NVDA, META, GOOGL, AMD), atr_mult=0.6, tiered sizing
Boof 21: QQQ + SPY, $250/trade, +35% TP / -10% SL
"""
import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              FRACTAL_BARS, ATR_LEN, VOL_LEN, SR_DIST_MAX, BOOFINGTON)
from backtest_boof21 import backtest as backtest_boof21

TRADE22_BASE=200; TM=0.08; MAX_HOLD=30; ATR_SL=2.0; ATR_TP=4.0; F=FRACTAL_BARS
TRADE21=250; TP21=0.35; SL21=-0.10; TIME21=0.08
ATR_MULT=0.6

print('Loading caches...')
cache25 = pickle.load(open('_boof22_cache.pkl', 'rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl', 'rb'))
cache21 = pickle.load(open('_boof21_cache.pkl', 'rb'))

MONTHS = [
    # label,   b22_key,  b21_key,    tdays, c22,    c21
    ('Jan 25', 'Jan',    'Jan 25', 23, cache25, cache21),
    ('Feb 25', 'Feb',    'Feb 25', 20, cache25, cache21),
    ('Mar 25', 'Mar',    'Mar 25', 21, cache25, cache21),
    ('Apr 25', 'Apr',    'Apr 25', 22, cache25, cache21),
    ('May 25', 'May',    'May 25', 21, cache25, cache21),
    ('Jun 25', 'Jun',    'Jun 25', 21, cache25, cache21),
    ('Jul 25', 'Jul',    'Jul 25', 23, cache25, cache21),
    ('Aug 25', 'Aug',    'Aug 25', 21, cache25, cache21),
    ('Sep 25', 'Sep',    'Sep 25', 21, cache25, cache21),
    ('Oct 25', 'Oct',    'Oct 25', 23, cache25, cache21),
    ('Nov 25', 'Nov',    'Nov 25', 20, cache25, cache21),
    ('Dec 25', 'Dec',    'Dec 25', 23, cache25, cache21),
    ('Jan 26', 'Jan 26', 'Jan 26', 22, cache26, cache26),
    ('Feb 26', 'Feb 26', 'Feb 26', 20, cache26, cache26),
    ('Mar 26', 'Mar 26', 'Mar 26', 21, cache26, cache26),
    ('Apr 26', 'Apr 26', 'Apr 26', 22, cache26, cache26),
    ('May 26', 'May 26', 'May 26', 18, cache26, cache26),
]
# Boof 21 exit_type: 'tp', 'stop', 'time'
B21_SL_PNL = TRADE21 * SL21   # -$25
B21_TP_PNL = TRADE21 * TP21   # +$87.50
B21_TM_PNL = TRADE21 * TIME21 # +$20

def run_b22_month(mo_key, cache):
    trades=[]
    for sym in BOOFINGTON:
        df=cache.get((sym, mo_key))
        if df is None or len(df)<100: continue
        df=df.copy().reset_index(drop=True)
        vm=1.2 if sym=='AAPL' else 1.3
        atr_s=compute_atr(df); df['atr']=atr_s
        df['vol_sma']=df['volume'].rolling(VOL_LEN).mean()
        df['rvol']=(df['volume']/df['vol_sma']*100).fillna(0)
        df['hi_vol']=df['volume']>df['vol_sma']*vm
        cp,_=build_cluster_array(df,atr_s,vm)
        highs=df['high'].values; lows=df['low'].values; closes=df['close'].values
        for i in range(VOL_LEN+ATR_LEN+F, len(df)-F-MAX_HOLD-3):
            row=df.iloc[i]
            if row['rvol']<80: continue
            atr=row['atr']
            if pd.isna(atr) or atr==0 or not row['hi_vol']: continue
            if nearest_sr_distance(row['close'],cp,atr)>SR_DIST_MAX: continue
            lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
            ll=lows[i-F:i]; rl=lows[i+1:i+F+1]
            fp=(highs[i]>lh.max())and(highs[i]>rh.max())
            ft=(lows[i]<ll.min())and(lows[i]<rl.min())
            peak_slack=(highs[i]-closes[i])/atr
            trough_slack=(closes[i]-lows[i])/atr
            for direction,is_valid,slack in [('short',fp,peak_slack),('long',ft,trough_slack)]:
                if not is_valid or slack<ATR_MULT: continue
                if i+1>=len(df)-MAX_HOLD-2: continue
                ep=float(df.iloc[i+1]['open'])
                tp_p=ep+atr*ATR_TP if direction=='long' else ep-atr*ATR_TP
                sl_p=ep-atr*ATR_SL if direction=='long' else ep+atr*ATR_SL
                size=600 if slack>=1.4 else 200
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
                trades.append({'pnl':pnl,'et':et})
    return trades

def run_b21_month(mo_key, cache):
    trades=[]
    for sym in ['QQQ','SPY']:
        df=cache.get((sym, mo_key))
        if df is None or len(df)<100: continue
        try:
            raw=backtest_boof21(df, symbol=sym)
        except Exception:
            continue
        for t in raw:
            et=t.get('exit_type','time')
            # Boof21 exit types: 'tp', 'stop', 'time'
            pnl=(B21_TP_PNL if et=='tp'
                 else B21_SL_PNL if et=='stop'
                 else B21_TM_PNL)
            trades.append({'pnl':pnl,'et':et})
    return trades

# ── Run all months ─────────────────────────────────────────────────
print('Running backtests...')
rows=[]
for label, mo22, mo21, tdays, c22, c21 in MONTHS:
    t22=run_b22_month(mo22, c22)
    t21=run_b21_month(mo21, c21)
    p22=np.array([t['pnl'] for t in t22]) if t22 else np.array([])
    p21=np.array([t['pnl'] for t in t21]) if t21 else np.array([])

    def mo_stats(arr, tdays):
        if len(arr)==0: return 0,0,0,0,0,0
        w=arr[arr>0]; l=arr[arr<0]
        wr=round(len(w)/len(arr)*100,1)
        pf=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
        ev=round(float(np.mean(arr)),2)
        tot=round(float(sum(arr)),2)
        tpd=round(len(arr)/tdays,1)
        return wr,pf,ev,tot,tpd,len(arr)

    r22=mo_stats(p22,tdays)
    r21=mo_stats(p21,tdays)
    rows.append({'mo':label,'tdays':tdays,
                 'wr22':r22[0],'pf22':r22[1],'ev22':r22[2],'pnl22':r22[3],'tpd22':r22[4],'n22':r22[5],
                 'wr21':r21[0],'pf21':r21[1],'ev21':r21[2],'pnl21':r21[3],'tpd21':r21[4],'n21':r21[5]})
    print(f'  {label}: B22=${r22[3]:>9,.0f} ({r22[4]}/day)  B21=${r21[3]:>7,.0f} ({r21[4]}/day)')

# ── Print table ────────────────────────────────────────────────────
print(f'\n{"="*110}')
print(f'  BOOF 21 vs BOOF 22 — Jan 2025 through May 2026')
print(f'  Boof 22: BOOFINGTON (AAPL/NVDA/META/GOOGL/AMD) | atr_mult=0.6 | Core $600 / Expanded $200')
print(f'  Boof 21: QQQ + SPY | $250/trade | +35% TP / -10% SL / +8% time')
print(f'{"="*110}')
print(f'  {"Month":<9} | {"":^40} | {"":^40} | {"Winner":^10}')
print(f'  {"":9} | {"--- BOOF 22 ---":^40} | {"--- BOOF 21 ---":^40} |')
print(f'  {"":9} | {"Trades":>7}{"WR%":>6}{"PF":>7}{"EV$":>7}{"P&L":>12} | {"Trades":>7}{"WR%":>6}{"PF":>7}{"EV$":>7}{"P&L":>12} |')
print(f'  {"-"*108}')

cum22=0; cum21=0
yr25_22=0; yr25_21=0; yr26_22=0; yr26_21=0

for r in rows:
    cum22+=r['pnl22']; cum21+=r['pnl21']
    if '25' in r['mo']: yr25_22+=r['pnl22']; yr25_21+=r['pnl21']
    else: yr26_22+=r['pnl22']; yr26_21+=r['pnl21']
    winner='B22' if r['pnl22']>r['pnl21'] else 'B21' if r['pnl21']>r['pnl22'] else 'TIE'
    mark='**' if winner=='B22' else '  '
    mark21='**' if winner=='B21' else '  '
    print(f'  {r["mo"]:<9} | {r["n22"]:>7}{r["wr22"]:>6}{r["pf22"]:>7}{r["ev22"]:>7}  ${r["pnl22"]:>9,.0f} |{mark21}{r["n21"]:>6}{r["wr21"]:>6}{r["pf21"]:>7}{r["ev21"]:>7}  ${r["pnl21"]:>9,.0f}{mark}|  {winner}')
    # Year separator
    if r['mo']=='Dec 25':
        print(f'  {"2025 TOTAL":<9} | {"":>7}{"":>6}{"":>7}{"":>7}  ${yr25_22:>9,.0f} | {"":>7}{"":>6}{"":>7}{"":>7}  ${yr25_21:>9,.0f}|')
        print(f'  {"-"*108}')

print(f'  {"2026 YTD":<9} | {"":>7}{"":>6}{"":>7}{"":>7}  ${yr26_22:>9,.0f} | {"":>7}{"":>6}{"":>7}{"":>7}  ${yr26_21:>9,.0f}|')
print(f'  {"="*108}')
print(f'  {"TOTAL":<9} | {"":>7}{"":>6}{"":>7}{"":>7}  ${cum22:>9,.0f} | {"":>7}{"":>6}{"":>7}{"":>7}  ${cum21:>9,.0f}|')
print(f'  {"COMBINED":<9} | ${cum22+cum21:,.0f} total across both strategies')

# ── Aggregate — flatten all monthly pnl lists already stored in rows ──────
all22_pnls = [r['pnl22'] for r in rows for _ in range(1)]  # monthly totals
all21_pnls = [r['pnl21'] for r in rows for _ in range(1)]
all22=np.array(all22_pnls)
all21=np.array(all21_pnls)

def agg(arr, label, is22):
    # arr = monthly P&L array (17 values)
    tot=round(float(sum(arr)))
    mo_avg=round(tot/17)
    cum=np.cumsum(arr); dd=round(float((np.maximum.accumulate(cum)-cum).max()))
    green=sum(1 for v in arr if v>0)
    # per-trade stats from rows
    fld_n='n22' if is22 else 'n21'
    fld_wr='wr22' if is22 else 'wr21'
    fld_pf='pf22' if is22 else 'pf21'
    fld_ev='ev22' if is22 else 'ev21'
    total_n=sum(r[fld_n] for r in rows)
    avg_wr=round(np.mean([r[fld_wr] for r in rows if r[fld_n]>0]),1)
    avg_pf=round(np.mean([r[fld_pf] for r in rows if r[fld_n]>0]),2)
    avg_ev=round(np.mean([r[fld_ev] for r in rows if r[fld_n]>0]),2)
    tpd=round(total_n/362,1)
    print(f'\n  {label}')
    print(f'    Trades:        {total_n:,}  ({tpd}/day)')
    print(f'    Win Rate:      {avg_wr}%')
    print(f'    Profit Factor: {avg_pf}')
    print(f'    EV/trade:      ${avg_ev}')
    print(f'    Total P&L:     ${tot:,}')
    print(f'    Monthly avg:   ${mo_avg:,}')
    print(f'    Max Drawdown:  ${dd:,}  (monthly)')
    print(f'    Green months:  {green}/17')

print(f'\n{"="*110}')
print(f'  AGGREGATE SUMMARY (17 months)')
print(f'{"="*110}')
agg(all22,'BOOF 22 (BOOFINGTON + tiered sizing)', True)
agg(all21,'BOOF 21 (QQQ + SPY)', False)
print(f'\n  COMBINED TOTAL:  ${round(float(sum(all22)+sum(all21))):,}  |  Avg ${round((float(sum(all22)+sum(all21)))/17):,}/mo')
print(f'{"="*110}')
