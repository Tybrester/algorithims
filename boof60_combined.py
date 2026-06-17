"""
BOOF60 Full Combined Signal Engine — 1yr, 60 symbols
One trade per symbol at a time (first signal wins, next queued after close)

LONG  (SPY+QQQ up + gap up  >0.5%):
  [BRK_UP]   Breaks above PDH / PWH / P10H / P20H / PMH
  [BNC_SUP]  Bounces off   PDL / PWL / FIB50 / FIB38 / PML

SHORT (SPY+QQQ dn + gap dn >0.5%):
  [BRK_DN]   Breaks below PDL / PWL / P10L / P20L / PML
  [BNC_RES]  Rejects off  PDH / PWH / FIB62 / FIB50 / PMH

Per-signal stats: trades/wk, WR, PF, EV, Ann
TP=25%, SL=-10%, flat exit 20 bars, 3x mult, $750/trade
"""
import os, pytz, datetime
import pandas as pd
import numpy as np
from itertools import product as iproduct

ET     = pytz.timezone('America/New_York')
CACHE  = "boof_data"
SUFFIX = "_5m_2yr.parquet"
BUDGET = 750.0
MULT   = 3.0
MAX_BARS    = 60
FLAT_BARS   = 20
FLAT_THRESH = 3.0
MAX_POS     = 5
NEAR_PCT    = 0.002
BOUNCE_PCT  = 0.002
TP = 25.0; SL = -10.0

SYMBOLS = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX',
    'SOFI','IONQ','RGTI','QUBT','ACHR','JOBY','LUNR','RDDT','CAVA','DUOL',
    'CELH','DKNG','MELI','SHOP','PYPL','SPOT','PINS','SNAP','LYFT','RIVN',
    'LCID','CHWY','SOUN','BBAI','AI','ASTS','RKLB','IREN','CORZ',
]

def load_sym(sym):
    path = os.path.join(CACHE, f"{sym}{SUFFIX}")
    if not os.path.exists(path): return pd.DataFrame()
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None: df.index = df.index.tz_localize('UTC')
    df.index = df.index.tz_convert(ET)
    return df

print("Loading data...")
data = {sym: load_sym(sym) for sym in SYMBOLS + ['SPY','QQQ']}
data = {k:v for k,v in data.items() if not v.empty}

print("Building daily OHLC + date groups...")
daily={}; by_date={}; pm_by_date={}
for sym,df in data.items():
    rth=df.between_time('09:30','16:00')
    pm =df.between_time('04:00','09:29')
    d  =rth.resample('1D').agg(open=('open','first'),high=('high','max'),
                                low=('low','min'),close=('close','last')).dropna()
    daily[sym]=d
    grp={}
    for dt,gdf in rth.groupby(rth.index.date): grp[dt]=gdf
    by_date[sym]=grp
    pmg={}
    for dt,gdf in pm.groupby(pm.index.date): pmg[dt]=gdf
    pm_by_date[sym]=pmg

spy_d=daily['SPY']; qqq_d=daily.get('QQQ',pd.DataFrame())
to_d=lambda d: d.date() if hasattr(d,'date') else d
spy_up={to_d(d) for d,r in spy_d.iterrows() if r['close']>r['open']}
spy_dn={to_d(d) for d,r in spy_d.iterrows() if r['close']<r['open']}
qqq_up={to_d(d) for d,r in qqq_d.iterrows() if r['close']>r['open']} if not qqq_d.empty else set()
qqq_dn={to_d(d) for d,r in qqq_d.iterrows() if r['close']<r['open']} if not qqq_d.empty else set()
both_up=spy_up&qqq_up; both_dn=spy_dn&qqq_dn

start=datetime.date.fromisoformat("2025-06-01")
all_dates=sorted(d for d in spy_d.index.date if d>=start)[1:]
print(f"  {len(all_dates)} days | up:{sum(1 for d in all_dates if d in both_up)} dn:{sum(1 for d in all_dates if d in both_dn)}\n")

# ── Bounce state machine ──────────────────────────────────────────
def init_sm(side='short'):
    return {'state':'IDLE','extreme':None,'touch_num':0,'was_other':False,'broken':False,'side':side}

def update_sm(sm, level, bar):
    p=bar['c']; h=bar['h']; l=bar['l']
    if sm['side']=='short':  # reject off resistance
        if p<level: sm['was_other']=True
        touch=sm['was_other'] and h>=level*(1-NEAR_PCT)
        if sm['state']=='IDLE':
            if touch: sm['state']='IN'; sm['extreme']=p; sm['touch_num']+=1
        elif sm['state']=='IN':
            if h>=level*(1-NEAR_PCT): sm['extreme']=min(sm['extreme'],p)
            else:
                ok=sm['extreme'] is not None and (level-sm['extreme'])/level>=BOUNCE_PCT
                if ok and sm['touch_num']==(2 if sm['broken'] else 1): sm['state']='FIRED'; return True
                sm['state']='DEAD'; sm['broken']=True; sm['was_other']=False
        elif sm['state']=='DEAD':
            if sm['was_other']: sm['state']='IDLE'; sm['extreme']=None; sm['touch_num']=0
    else:  # bounce off support
        if p>level: sm['was_other']=True
        touch=sm['was_other'] and l<=level*(1+NEAR_PCT)
        if sm['state']=='IDLE':
            if touch: sm['state']='IN'; sm['extreme']=p; sm['touch_num']+=1
        elif sm['state']=='IN':
            if l<=level*(1+NEAR_PCT): sm['extreme']=max(sm['extreme'] or p,p)
            else:
                ok=sm['extreme'] is not None and (sm['extreme']-level)/level>=BOUNCE_PCT
                if ok and sm['touch_num']==(2 if sm['broken'] else 1): sm['state']='FIRED'; return True
                sm['state']='DEAD'; sm['broken']=True; sm['was_other']=False
        elif sm['state']=='DEAD':
            if sm['was_other']: sm['state']='IDLE'; sm['extreme']=None; sm['touch_num']=0
    return False

# ── Signal collection ─────────────────────────────────────────────
print("Collecting all signals...")
raw=[]

for day in all_dates:
    is_long=day in both_up; is_short=day in both_dn
    if not is_long and not is_short: continue

    spy_prices=[]; regime="neutral"; active_pos={}
    spy_rth=by_date.get('SPY',{}).get(day,pd.DataFrame())

    for sym in SYMBOLS:
        if sym not in by_date or sym not in daily: continue
        dh=daily[sym]; prev=dh[dh.index.date<day]
        if len(prev)<5: continue
        prev_close=float(prev['close'].iloc[-1])
        rth=by_date[sym].get(day,pd.DataFrame())
        if len(rth)<2: continue
        day_open=float(rth['open'].iloc[0])
        gap_pct=(day_open-prev_close)/prev_close*100
        if is_long  and gap_pct< 0.5: continue
        if is_short and gap_pct>-0.5: continue

        p1=prev.iloc[-1]
        pdh=float(p1['high']); pdl=float(p1['low'])
        pwh=float(prev.tail(5)['high'].max()); pwl=float(prev.tail(5)['low'].min())
        p10h=float(prev.tail(10)['high'].max()); p10l=float(prev.tail(10)['low'].min())
        p20h=float(prev.tail(20)['high'].max()); p20l=float(prev.tail(20)['low'].min())
        rng=pdh-pdl
        fib38=pdl+rng*0.382; fib50=pdl+rng*0.5; fib62=pdl+rng*0.618
        pm_bars=pm_by_date.get(sym,{}).get(day,pd.DataFrame())
        pmh=float(pm_bars['high'].max()) if not pm_bars.empty else None
        pml=float(pm_bars['low'].min())  if not pm_bars.empty else None

        if is_long:
            brk_levels={k:v for k,v in [('PDH',pdh),('PWH',pwh),('P10H',p10h),('P20H',p20h)]+
                        ([('PMH',pmh)] if pmh else []) if v>day_open}
            bnc_levels={k:v for k,v in [('PDL',pdl),('PWL',pwl),('FIB50',fib50),('FIB38',fib38)]+
                        ([('PML',pml)] if pml else []) if v<day_open}
            bnc_sms={k:init_sm('long') for k in bnc_levels}
        else:
            brk_levels={k:v for k,v in [('PDL',pdl),('PWL',pwl),('P10L',p10l),('P20L',p20l)]+
                        ([('PML',pml)] if pml else []) if v<day_open}
            bnc_levels={k:v for k,v in [('PDH',pdh),('PWH',pwh),('FIB62',fib62),('FIB50',fib50)]+
                        ([('PMH',pmh)] if pmh else []) if v>day_open}
            bnc_sms={k:init_sm('short') for k in bnc_levels}

        brk_broken=set(); brk_confirm=None; brk_confirm_price=None
        in_trade=None; bar_path=[]; fired=False

        for i,(ts,bar) in enumerate(rth.iterrows()):
            hm=ts.strftime('%H:%M')
            price=float(bar['close']); high=float(bar['high']); low=float(bar['low'])
            bdict={'h':high,'l':low,'c':price}

            if i<len(spy_rth):
                spy_prices.append(float(spy_rth.iloc[min(i,len(spy_rth)-1)]['close']))
                if len(spy_prices)>5: spy_prices.pop(0)
                if len(spy_prices)>=3:
                    if   spy_prices[-1]>spy_prices[0]*1.001: regime="bull"
                    elif spy_prices[-1]<spy_prices[0]*0.999: regime="bear"
                    else: regime="neutral"

            if in_trade:
                ep=in_trade['entry_price']; direction=in_trade['direction']
                stk=(price-ep)/ep*100 if direction=='long' else (ep-price)/ep*100
                mfe=(high-ep)/ep*100  if direction=='long' else (ep-low)/ep*100
                mae=(low-ep)/ep*100   if direction=='long' else (ep-high)/ep*100
                in_trade['bars_held']+=1
                bar_path.append({'opt_pct':stk*MULT,'mfe_opt':mfe*MULT,'mae_opt':mae*MULT})
                if in_trade['bars_held']>=MAX_BARS or hm>='15:50':
                    raw.append({'date':day,'sym':sym,'direction':direction,
                        'entry_time':in_trade['entry_time'],'gap_pct':round(gap_pct,2),
                        'signal':in_trade['signal'],'level':in_trade['level'],
                        'day_type':'up' if is_long else 'dn','bars':bar_path})
                    in_trade=None; bar_path=[]; fired=False
                    if sym in active_pos: del active_pos[sym]
                continue

            if hm>'10:30': break
            if len(active_pos)>=MAX_POS or fired: continue

            direction='long' if is_long else 'short'

            # ── Breakout signal ────────────────────────────────
            for lname,lval in sorted(brk_levels.items(),
                                     key=lambda x:x[1] if is_short else -x[1]):
                if lname in brk_broken: continue
                broke=(price>lval*1.001) if is_long else (price<lval*0.999)
                if broke:
                    brk_broken.add(lname)
                    if brk_confirm is None:
                        brk_confirm=lname; brk_confirm_price=price
                    else:
                        ok=(price>=brk_confirm_price) if is_long else (price<=brk_confirm_price)
                        if ok:
                            fired=True
                            in_trade={'direction':direction,'entry_price':price,'entry_time':hm,
                                      'bars_held':0,'signal':'BRK_UP' if is_long else 'BRK_DN',
                                      'level':brk_confirm}
                            active_pos[sym]=True; break
            if not fired and brk_confirm:
                ok=(price>=brk_confirm_price) if is_long else (price<=brk_confirm_price)
                if ok:
                    fired=True
                    in_trade={'direction':direction,'entry_price':price,'entry_time':hm,
                              'bars_held':0,'signal':'BRK_UP' if is_long else 'BRK_DN',
                              'level':brk_confirm}
                    active_pos[sym]=True

            # ── Bounce signal ──────────────────────────────────
            if not fired:
                for lname,lval in bnc_levels.items():
                    sm=bnc_sms[lname]
                    if sm['state']=='FIRED': continue
                    if update_sm(sm,lval,bdict):
                        fired=True
                        in_trade={'direction':direction,'entry_price':price,'entry_time':hm,
                                  'bars_held':0,'signal':'BNC_SUP' if is_long else 'BNC_RES',
                                  'level':lname}
                        active_pos[sym]=True; break

        if in_trade and bar_path:
            raw.append({'date':day,'sym':sym,'direction':in_trade['direction'],
                'entry_time':in_trade['entry_time'],'gap_pct':round(gap_pct,2),
                'signal':in_trade['signal'],'level':in_trade['level'],
                'day_type':'up' if is_long else 'dn','bars':bar_path})

print(f"  Total signals: {len(raw)} ({len(raw)/len(all_dates)*5:.1f}/wk)\n")

# ── Simulate ──────────────────────────────────────────────────────
def sim_trade(t,tp=TP,sl=SL):
    for j,b in enumerate(t['bars']):
        if b['mfe_opt']>=tp:  return BUDGET*tp/100, 'TP'
        if b['mae_opt']<=sl:  return BUDGET*sl/100, 'SL'
        if j>=FLAT_BARS and abs(b['opt_pct'])<FLAT_THRESH:
            return BUDGET*b['opt_pct']/100, 'FLAT'
    return BUDGET*t['bars'][-1]['opt_pct']/100, 'TIMEOUT'

def stats(trades, label=""):
    if not trades: print(f"  {label}: no trades"); return None
    res=[sim_trade(t) for t in trades]
    pnls=[r[0] for r in res]; exits=[r[1] for r in res]
    df=pd.DataFrame({'pnl':pnls,'exit':exits})
    w=df[df['pnl']>0]; l=df[df['pnl']<=0]
    wr=len(w)/len(df); pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    wpw=len(trades)/len(all_dates)*5
    r={'label':label,'n':len(df),'wpw':round(wpw,1),'wr':round(wr*100,1),
       'pf':round(pf,2),'ev':round(df['pnl'].mean(),2),
       'total':round(df['pnl'].sum(),2),'tp':exits.count('TP'),'sl':exits.count('SL')}
    print(f"  {label:<45} {r['n']:4d} trades ({r['wpw']:4.1f}/wk)  "
          f"WR={r['wr']}%  PF={r['pf']}x  EV=${r['ev']:6.2f}  Ann=${r['total']:>9.2f}/yr")
    return r

print("="*78)
print("BOOF60 COMBINED — ALL SIGNALS  (1yr, 60 syms, TP=25%, SL=-10%, 3x mult)")
print("="*78)

print(f"\n{'─'*78}")
print(f"  {'Signal':<45} {'n':>4}  {'wpw':>5}   {'WR':>5}  {'PF':>5}  {'EV':>7}  {'Ann':>10}")
print(f"{'─'*78}")

all_r  = stats(raw, "TOTAL COMBINED")
print()
long_r = stats([t for t in raw if t['direction']=='long'],  "  ALL LONGS")
short_r= stats([t for t in raw if t['direction']=='short'], "  ALL SHORTS")
print()
stats([t for t in raw if t['signal']=='BRK_UP'],  "  BRK_UP  (gap-up + breaks resistance)")
stats([t for t in raw if t['signal']=='BNC_SUP'], "  BNC_SUP (gap-up + bounces support)")
stats([t for t in raw if t['signal']=='BRK_DN'],  "  BRK_DN  (gap-dn + breaks support)")
stats([t for t in raw if t['signal']=='BNC_RES'], "  BNC_RES (gap-dn + rejects resistance)")

print(f"\n{'─'*78}")
print("  BY LEVEL")
print(f"{'─'*78}")
level_counts={}
for t in raw: level_counts[t['level']]=level_counts.get(t['level'],0)+1
for lv in sorted(level_counts,key=lambda x:-level_counts[x])[:12]:
    stats([t for t in raw if t['level']==lv], f"    {lv}")

print(f"\n{'─'*78}")
print("  BY GAP SIZE")
print(f"{'─'*78}")
for gap in [0.5,1.0,1.5,2.0,3.0]:
    t=[x for x in raw if abs(x['gap_pct'])>=gap]
    stats(t, f"  gap >{gap}% (both dirs)")

print(f"\n{'─'*78}")
print("  TP/SL SWEEP")
print(f"{'─'*78}")
rows=[]
for tp,sl in iproduct([15,20,25,35,50],[-5,-8,-10,-12,-15,-20]):
    res=[sim_trade(t,tp,sl) for t in raw]
    pnls=[r[0] for r in res]; exits=[r[1] for r in res]
    df2=pd.DataFrame({'pnl':pnls})
    w=df2[df2['pnl']>0]; l=df2[df2['pnl']<=0]
    wr=len(w)/len(df2) if len(df2) else 0
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    rows.append({'tp':tp,'sl':sl,'n':len(df2),'wr':round(wr*100,1),'pf':round(pf,2),
                 'total':round(df2['pnl'].sum(),2),'tp_hits':exits.count('TP')})
sw=pd.DataFrame(rows).sort_values('total',ascending=False)
print(sw.head(12)[['tp','sl','n','wr','pf','total','tp_hits']].to_string(index=False))

print(f"\n{'─'*78}")
print("  MONTHLY")
print(f"{'─'*78}")
mrows=[]
for t in raw:
    pnl,ext=sim_trade(t)
    mrows.append({'date':t['date'],'pnl':pnl,'signal':t['signal']})
mdf=pd.DataFrame(mrows)
mdf['month']=pd.to_datetime(mdf['date']).dt.to_period('M')
mb=mdf.groupby('month').agg(n=('pnl','count'),pnl=('pnl','sum'),
    wr=('pnl',lambda x:f"{(x>0).mean()*100:.0f}%"),avg=('pnl','mean')).round(2)
print(mb.to_string())

print(f"\n{'─'*78}")
print("  MONTE CARLO (5,000 runs)")
print(f"{'─'*78}")
pnls_arr=mdf['pnl'].values
np.random.seed(42)
mc=np.array([np.random.choice(pnls_arr,size=len(pnls_arr),replace=True).sum() for _ in range(5000)])
print(f"  Prob > $0:      {(mc>0).mean()*100:.1f}%")
print(f"  5th pct:        ${np.percentile(mc,5):>10,.0f}/yr")
print(f"  Median:         ${np.percentile(mc,50):>10,.0f}/yr")
print(f"  95th pct:       ${np.percentile(mc,95):>10,.0f}/yr")
monthly=mdf.groupby('month')['pnl'].sum()
sharpe=monthly.mean()/monthly.std()*np.sqrt(12) if monthly.std()>0 else 0
print(f"  Monthly Sharpe: {sharpe:.2f}")
print(f"  +ve months:     {(monthly>0).sum()}/{len(monthly)}")
print(f"  Worst month:    ${monthly.min():,.2f}")
print(f"  Best month:     ${monthly.max():,.2f}")
