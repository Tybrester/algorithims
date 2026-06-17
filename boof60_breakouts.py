"""
BOOF60 Breakout Test
LONG  breakouts: SPY up day + stock gaps up + breaks THROUGH resistance levels
SHORT breakouts: SPY down day + stock gaps down + breaks THROUGH support levels

Resistance levels tested (longs):
- PDH (previous day high)
- PWH (previous week high)
- P10H (10-day high)
- P20H (20-day high)
- PMH (pre-market high)
- Round numbers above price

Support levels tested (shorts):
- PDL (previous day low)
- PWL (previous week low)
- P10L (10-day low)
- P20L (20-day low)
- PML (pre-market low)
- Round numbers below price

Signal: price closes a bar ABOVE resistance (long) or BELOW support (short)
+1 bar confirmation then entry
1 year, 60 symbols, TP=25%, SL=-10%, flat exit 20 bars, 3x mult
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
daily = {}; by_date = {}; pm_by_date = {}
for sym, df in data.items():
    rth = df.between_time('09:30','16:00')
    pm  = df.between_time('04:00','09:29')
    d   = rth.resample('1D').agg(open=('open','first'),high=('high','max'),
                                  low=('low','min'),close=('close','last')).dropna()
    daily[sym] = d
    grp={}
    for dt,gdf in rth.groupby(rth.index.date): grp[dt]=gdf
    by_date[sym]=grp
    pmgrp={}
    for dt,gdf in pm.groupby(pm.index.date): pmgrp[dt]=gdf
    pm_by_date[sym]=pmgrp

spy_d=daily['SPY']; qqq_d=daily.get('QQQ',pd.DataFrame())
to_d=lambda d: d.date() if hasattr(d,'date') else d
spy_up={to_d(d) for d,r in spy_d.iterrows() if r['close']>r['open']}
spy_dn={to_d(d) for d,r in spy_d.iterrows() if r['close']<r['open']}
qqq_up={to_d(d) for d,r in qqq_d.iterrows() if r['close']>r['open']} if not qqq_d.empty else set()
qqq_dn={to_d(d) for d,r in qqq_d.iterrows() if r['close']<r['open']} if not qqq_d.empty else set()
both_up = spy_up & qqq_up
both_dn = spy_dn & qqq_dn

start=datetime.date.fromisoformat("2025-06-01")
all_dates=sorted(d for d in spy_d.index.date if d>=start)[1:]
print(f"  {len(all_dates)} days | both-up: {sum(1 for d in all_dates if d in both_up)} | both-dn: {sum(1 for d in all_dates if d in both_dn)}\n")

# ── Collect signals ───────────────────────────────────────────────
print("Collecting breakout signals...")
raw=[]

for day in all_dates:
    is_long_day  = day in both_up
    is_short_day = day in both_dn
    if not is_long_day and not is_short_day: continue

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

        # Gap filter: long days need gap up, short days need gap down
        if is_long_day  and gap_pct < 0.5: continue
        if is_short_day and gap_pct > -0.5: continue

        # ── Build resistance (for longs) / support (for shorts) ──
        p1=prev.iloc[-1]
        pdh=float(p1['high']); pdl=float(p1['low'])
        pwh=float(prev.tail(5)['high'].max())
        pwl=float(prev.tail(5)['low'].min())
        p10h=float(prev.tail(10)['high'].max())
        p10l=float(prev.tail(10)['low'].min())
        p20h=float(prev.tail(20)['high'].max())
        p20l=float(prev.tail(20)['low'].min())

        pm_bars=pm_by_date.get(sym,{}).get(day,pd.DataFrame())
        pmh=float(pm_bars['high'].max()) if not pm_bars.empty else None
        pml=float(pm_bars['low'].min())  if not pm_bars.empty else None

        if is_long_day:
            levels={}
            levels['PDH']=pdh
            if pwh>pdh*1.001:  levels['PWH']=pwh
            if p10h>pdh*1.001: levels['P10H']=p10h
            if p20h>pdh*1.001: levels['P20H']=p20h
            if pmh and pmh>day_open*1.001: levels['PMH']=pmh
            # Only levels above day_open (unbroken resistance)
            levels={k:v for k,v in levels.items() if v>day_open}
        else:
            levels={}
            levels['PDL']=pdl
            if pwl<pdl*0.999:  levels['PWL']=pwl
            if p10l<pdl*0.999: levels['P10L']=p10l
            if p20l<pdl*0.999: levels['P20L']=p20l
            if pml and pml<day_open*0.999: levels['PML']=pml
            # Only levels below day_open (unbroken support)
            levels={k:v for k,v in levels.items() if v<day_open}

        if not levels: continue

        # Track which levels have been broken already
        broken=set(); confirm_level=None; confirm_price=None
        in_trade=None; bar_path=[]; fired=False

        for i,(ts,bar) in enumerate(rth.iterrows()):
            hm=ts.strftime('%H:%M')
            price=float(bar['close']); high=float(bar['high']); low=float(bar['low'])

            if i<len(spy_rth):
                spy_prices.append(float(spy_rth.iloc[min(i,len(spy_rth)-1)]['close']))
                if len(spy_prices)>5: spy_prices.pop(0)
                if len(spy_prices)>=3:
                    if   spy_prices[-1]>spy_prices[0]*1.001: regime="bull"
                    elif spy_prices[-1]<spy_prices[0]*0.999: regime="bear"
                    else: regime="neutral"

            if in_trade:
                ep=in_trade['entry_price']; direction=in_trade['direction']
                if direction=='long':
                    stk=(price-ep)/ep*100; mfe=(high-ep)/ep*100; mae=(low-ep)/ep*100
                else:
                    stk=(ep-price)/ep*100; mfe=(ep-low)/ep*100; mae=(ep-high)/ep*100
                in_trade['bars_held']+=1
                bar_path.append({'opt_pct':stk*MULT,'mfe_opt':mfe*MULT,'mae_opt':mae*MULT})
                if in_trade['bars_held']>=MAX_BARS or hm>='15:50':
                    raw.append({'date':day,'sym':sym,'direction':direction,
                        'entry_time':in_trade['entry_time'],'gap_pct':round(gap_pct,2),
                        'level_type':in_trade['level_type'],'day_type':'up' if is_long_day else 'dn',
                        'bars':bar_path})
                    in_trade=None; bar_path=[]
                    if sym in active_pos: del active_pos[sym]
                continue

            if hm>'10:30': break
            if len(active_pos)>=MAX_POS or fired: continue

            if is_long_day:
                # Check if price breaks above any resistance
                for lname,lval in sorted(levels.items(), key=lambda x:x[1]):
                    if lname in broken: continue
                    if price>lval*1.001:  # broke through
                        broken.add(lname)
                        if confirm_level is None:
                            confirm_level=lname; confirm_price=price
                        else:
                            # +1 bar confirm — enter on next bar above confirm
                            if price>=confirm_price:
                                fired=True
                                in_trade={'direction':'long','entry_price':price,
                                         'entry_time':hm,'bars_held':0,'level_type':confirm_level}
                                active_pos[sym]=True; break
                # If waiting for confirm, check next bar
                if not fired and confirm_level and price>=confirm_price:
                    fired=True
                    in_trade={'direction':'long','entry_price':price,
                             'entry_time':hm,'bars_held':0,'level_type':confirm_level}
                    active_pos[sym]=True

            else:  # short day
                for lname,lval in sorted(levels.items(), key=lambda x:-x[1]):
                    if lname in broken: continue
                    if price<lval*0.999:  # broke below
                        broken.add(lname)
                        if confirm_level is None:
                            confirm_level=lname; confirm_price=price
                        else:
                            if price<=confirm_price:
                                fired=True
                                in_trade={'direction':'short','entry_price':price,
                                         'entry_time':hm,'bars_held':0,'level_type':confirm_level}
                                active_pos[sym]=True; break
                if not fired and confirm_level and price<=confirm_price:
                    fired=True
                    in_trade={'direction':'short','entry_price':price,
                             'entry_time':hm,'bars_held':0,'level_type':confirm_level}
                    active_pos[sym]=True

        if in_trade and bar_path:
            raw.append({'date':day,'sym':sym,'direction':in_trade['direction'],
                'entry_time':in_trade['entry_time'],'gap_pct':round(gap_pct,2),
                'level_type':in_trade['level_type'],'day_type':'up' if is_long_day else 'dn',
                'bars':bar_path})

print(f"  Total signals: {len(raw)} ({len(raw)/len(all_dates)*5:.1f}/wk)\n")

# ── Simulate ──────────────────────────────────────────────────────
def sim_trade(t,tp=25.0,sl=-10.0):
    for j,b in enumerate(t['bars']):
        if b['mfe_opt']>=tp:  return BUDGET*tp/100, 'TP'
        if b['mae_opt']<=sl:  return BUDGET*sl/100, 'SL'
        if j>=FLAT_BARS and abs(b['opt_pct'])<FLAT_THRESH:
            return BUDGET*b['opt_pct']/100, 'FLAT'
    return BUDGET*t['bars'][-1]['opt_pct']/100, 'TIMEOUT'

def run(trades,tp=25.0,sl=-10.0,label=""):
    if not trades: return None
    res=[sim_trade(t,tp,sl) for t in trades]
    pnls=[r[0] for r in res]; exits=[r[1] for r in res]
    df=pd.DataFrame({'pnl':pnls,'exit':exits})
    w=df[df['pnl']>0]; l=df[df['pnl']<=0]
    wr=len(w)/len(df) if len(df) else 0
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    wpw=len(trades)/len(all_dates)*5
    return {'label':label,'n':len(df),'wpw':round(wpw,1),'wr':round(wr*100,1),
            'pf':round(pf,2),'ev':round(df['pnl'].mean(),2),
            'total':round(df['pnl'].sum(),2),'ann':round(df['pnl'].sum(),2),
            'tp_n':exits.count('TP'),'sl_n':exits.count('SL')}

def pr(r):
    if not r: print("  No trades"); return
    print(f"  {r['label']:<40} n={r['n']:4d} ({r['wpw']:.1f}/wk)  WR={r['wr']}%  "
          f"PF={r['pf']}x  EV=${r['ev']}  Ann=${r['ann']}/yr  TP={r['tp_n']} SL={r['sl_n']}")

print("="*72)
print("BREAKOUT RESULTS — 1 Year (SPY+QQQ aligned + gap filter)")
print("="*72)

print("\n── OVERALL ───────────────────────────────────────────────────")
pr(run(raw,                                       label="ALL breakouts"))
pr(run([t for t in raw if t['direction']=='long'],label="LONG breakouts (gap-up thru resistance)"))
pr(run([t for t in raw if t['direction']=='short'],label="SHORT breakouts (gap-down thru support)"))

print("\n── BY LEVEL TYPE — LONGS ─────────────────────────────────────")
for lv in ['PDH','PWH','P10H','P20H','PMH']:
    t=[x for x in raw if x['direction']=='long' and x['level_type']==lv]
    pr(run(t,label=f"  LONG  {lv}"))

print("\n── BY LEVEL TYPE — SHORTS ────────────────────────────────────")
for lv in ['PDL','PWL','P10L','P20L','PML']:
    t=[x for x in raw if x['direction']=='short' and x['level_type']==lv]
    pr(run(t,label=f"  SHORT {lv}"))

print("\n── GAP SIZE vs QUALITY ───────────────────────────────────────")
for direction,label in [('long','LONG gap>'),('short','SHORT gap>')]:
    for gap in [0.5,1.0,1.5,2.0,3.0]:
        if direction=='long':
            t=[x for x in raw if x['direction']=='long' and x['gap_pct']>=gap]
        else:
            t=[x for x in raw if x['direction']=='short' and x['gap_pct']<=-gap]
        pr(run(t,label=f"  {label}{gap}%"))

print("\n── STACKED BREAKOUTS (broke multiple levels) ─────────────────")
# Trades where level broken is a higher TF level (PWH/P10H/P20H = stronger)
strong_long  =[t for t in raw if t['direction']=='long'  and t['level_type'] in ('PWH','P10H','P20H','PMH')]
strong_short =[t for t in raw if t['direction']=='short' and t['level_type'] in ('PWL','P10L','P20L','PML')]
pr(run(strong_long,  label="LONG  multi-TF resistance breaks"))
pr(run(strong_short, label="SHORT multi-TF support breaks"))
pr(run(strong_long+strong_short, label="BOTH  multi-TF breaks combined"))

print("\n── TP/SL SWEEP (all breakouts) ───────────────────────────────")
rows=[]
for tp,sl in iproduct([10,15,20,25,35,50],[-5,-8,-10,-12,-15,-20,-25]):
    res=[sim_trade(t,tp,sl) for t in raw]
    pnls=[r[0] for r in res]; exits=[r[1] for r in res]
    df2=pd.DataFrame({'pnl':pnls})
    w=df2[df2['pnl']>0]; l=df2[df2['pnl']<=0]
    wr=len(w)/len(df2) if len(df2) else 0
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    rows.append({'tp':tp,'sl':sl,'n':len(df2),'wr':round(wr*100,1),'pf':round(pf,2),
                 'total':round(df2['pnl'].sum(),2),'tp_hits':exits.count('TP')})
sw=pd.DataFrame(rows).sort_values('total',ascending=False)
print(sw.head(15)[['tp','sl','n','wr','pf','total','ann' if 'ann' in sw.columns else 'total','tp_hits']].to_string(index=False))

print("\n── MONTHLY (all breakouts, TP=25, SL=-10) ────────────────────")
mrows=[]
for t in raw:
    pnl,ext=sim_trade(t,25.0,-10.0)
    mrows.append({'date':t['date'],'pnl':pnl,'direction':t['direction'],'level':t['level_type']})
mdf=pd.DataFrame(mrows)
if not mdf.empty:
    mdf['month']=pd.to_datetime(mdf['date']).dt.to_period('M')
    mb=mdf.groupby('month').agg(n=('pnl','count'),pnl=('pnl','sum'),
        wr=('pnl',lambda x:f"{(x>0).mean()*100:.0f}%"),avg=('pnl','mean')).round(2)
    print(mb.to_string())

print("\n── COMPARE: BREAKOUTS vs GAP-DIRECTION (same period) ─────────")
import pickle
if os.path.exists('boof60_2yr_paths.pkl'):
    with open('boof60_2yr_paths.pkl','rb') as f: long_raw=pickle.load(f)
    long_1yr=[t for t in long_raw if t['date']>=start]
    rl=run(long_1yr,25.0,-10.0,"BOOF55 gap-up longs (baseline)")
    rb=run(raw,25.0,-10.0,"ALL breakouts (new)")
    print(f"\n  Baseline:"); pr(rl)
    print(f"  New:    "); pr(rb)
