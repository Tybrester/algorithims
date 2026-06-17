"""
BOOF60 Gap-Down Bounce Long Test
Stock gaps DOWN >1.5% but then bounces off support (PDL or PML) back up
Signal: price touches PDL or PML, bounces >=0.15%, then +1 bar confirmation -> buy call
SPY+QQQ can be either direction (gap-down bounce can happen on mixed/up days too)
1 year: Jun 2025 - Jun 2026
"""
import os, pytz
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
NEAR_PCT    = 0.0015   # within 0.15% of level counts as a touch
BOUNCE      = 0.0015   # must bounce 0.15% off level

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
daily = {}; by_date = {}
for sym, df in data.items():
    rth = df.between_time('09:30','16:00')
    d   = rth.resample('1D').agg(open=('open','first'),high=('high','max'),
                                  low=('low','min'),close=('close','last')).dropna()
    daily[sym] = d
    grp = {}
    for dt, gdf in rth.groupby(rth.index.date):
        grp[dt] = gdf
    by_date[sym] = grp

spy_d = daily['SPY']
to_d  = lambda d: d.date() if hasattr(d,'date') else d
spy_up = {to_d(d) for d,r in spy_d.iterrows() if r['close']>r['open']}
spy_dn = {to_d(d) for d,r in spy_d.iterrows() if r['close']<r['open']}

import datetime
start = datetime.date.fromisoformat("2025-06-01")
all_dates = sorted(d for d in spy_d.index.date if d >= start)[1:]
print(f"  {len(all_dates)} trading days\n")

# ── Support level state machine (bounce off low) ──────────────────
def init_sm(): 
    return {'state':'IDLE','extreme':None,'touch_num':0,'was_above':False,'broken':False}

def update_bounce_sm(sm, level, bar):
    """Detect fresh 1st touch of support level from above + bounce up"""
    low = bar['l']; close = bar['c']
    if close > level: sm['was_above'] = True
    touching = sm['was_above'] and low <= level*(1+NEAR_PCT)
    if sm['state'] == 'IDLE':
        if touching:
            sm['state'] = 'IN'; sm['extreme'] = close; sm['touch_num'] += 1
    elif sm['state'] == 'IN':
        if low <= level*(1+NEAR_PCT):
            sm['extreme'] = max(sm['extreme'], close) if sm['extreme'] else close
        else:
            bounced = sm['extreme'] is not None and (sm['extreme']-level)/level >= BOUNCE
            req = 2 if sm['broken'] else 1
            if bounced and sm['touch_num'] == req:
                sm['state'] = 'FIRED'; return True
            sm['state'] = 'DEAD'; sm['broken'] = True; sm['was_above'] = False
    elif sm['state'] == 'DEAD':
        if sm['was_above']: sm['state']='IDLE'; sm['extreme']=None; sm['touch_num']=0
    return False

# ── Collect signals ───────────────────────────────────────────────
print("Collecting gap-down bounce long signals...")
raw = []
for di, day in enumerate(all_dates):
    spy_prices=[]; regime="neutral"; active_pos={}
    spy_rth = by_date.get('SPY',{}).get(day, pd.DataFrame())

    for sym in SYMBOLS:
        if sym not in by_date or sym not in daily: continue
        dh=daily[sym]; prev=dh[dh.index.date<day]
        if len(prev)<1: continue
        prev_close = float(prev['close'].iloc[-1])
        pdl        = float(prev['low'].iloc[-1])   # previous day low = support
        pdh        = float(prev['high'].iloc[-1])

        rth = by_date[sym].get(day, pd.DataFrame())
        if len(rth)<2: continue

        day_open = float(rth['open'].iloc[0])
        gap_pct  = (day_open - prev_close) / prev_close * 100

        # Only gap-DOWN days for this signal
        if gap_pct > -0.5: continue

        # Pre-market low as additional support level
        premarket = data[sym][data[sym].index.date==day].between_time('04:00','09:29') if sym in data else pd.DataFrame()
        pml = float(premarket['low'].min()) if not premarket.empty else None

        # Build support levels: PDL + PML (if different enough)
        levels = [pdl]
        if pml and abs(pml - pdl)/pdl > 0.002:
            levels.append(pml)

        lvl_sms = {round(lv,4): init_sm() for lv in levels}

        confirm=False; in_trade=None; bar_path=[]; fired=False

        for i,(ts,bar) in enumerate(rth.iterrows()):
            hm    = ts.strftime('%H:%M')
            price = float(bar['close'])
            high  = float(bar['high'])
            low   = float(bar['low'])
            bdict = {'h':high,'l':low,'c':price}

            if i<len(spy_rth):
                spy_prices.append(float(spy_rth.iloc[min(i,len(spy_rth)-1)]['close']))
                if len(spy_prices)>5: spy_prices.pop(0)
                if len(spy_prices)>=3:
                    if   spy_prices[-1]>spy_prices[0]*1.001: regime="bull"
                    elif spy_prices[-1]<spy_prices[0]*0.999: regime="bear"
                    else: regime="neutral"

            if in_trade:
                ep=in_trade['entry_price']
                stk=(price-ep)/ep*100; mfe=(high-ep)/ep*100; mae=(low-ep)/ep*100
                in_trade['bars_held']+=1
                bar_path.append({'opt_pct':stk*MULT,'mfe_opt':mfe*MULT,'mae_opt':mae*MULT})
                if in_trade['bars_held']>=MAX_BARS or hm>='15:50':
                    raw.append({'date':day,'sym':sym,'entry_time':in_trade['entry_time'],
                                'gap_pct':round(gap_pct,2),'spy_regime':in_trade['spy_regime'],
                                'level_type':in_trade['level_type'],'bars':bar_path})
                    in_trade=None; bar_path=[]
                    if sym in active_pos: del active_pos[sym]
                continue

            if hm>'11:00': break
            if len(active_pos)>=MAX_POS or fired: continue

            # Check each support level for a bounce
            for lv, sm in lvl_sms.items():
                if sm['state']=='FIRED': continue
                if update_bounce_sm(sm, lv, bdict):
                    # Bounce confirmed — need +1 bar confirmation (price above entry)
                    if not confirm:
                        confirm=True; confirm_price=price
                    else:
                        if price > confirm_price and regime in ('bull','neutral'):
                            ltype = 'PDL' if abs(lv-pdl)/pdl<0.001 else 'PML'
                            fired=True
                            in_trade={'entry_price':price,'entry_time':hm,'bars_held':0,
                                      'spy_regime': 'up' if day in spy_up else ('dn' if day in spy_dn else 'neutral'),
                                      'level_type':ltype}
                            active_pos[sym]=True; break

        if in_trade and bar_path:
            raw.append({'date':day,'sym':sym,'entry_time':in_trade['entry_time'],
                        'gap_pct':round(gap_pct,2),'spy_regime':in_trade['spy_regime'],
                        'level_type':in_trade['level_type'],'bars':bar_path})

print(f"  Total signals: {len(raw)} ({len(raw)/len(all_dates)*5:.1f}/wk)\n")

# ── Simulate ──────────────────────────────────────────────────────
def sim_trade(t, tp, sl):
    for j,b in enumerate(t['bars']):
        if b['mfe_opt']>=tp:  return BUDGET*tp/100,  'TP'
        if b['mae_opt']<=sl:  return BUDGET*sl/100,  'SL'
        if j>=FLAT_BARS and abs(b['opt_pct'])<FLAT_THRESH:
            return BUDGET*b['opt_pct']/100, 'FLAT'
    return BUDGET*t['bars'][-1]['opt_pct']/100, 'TIMEOUT'

def run(trades, tp=25.0, sl=-10.0, label=""):
    if not trades: return None
    res=[sim_trade(t,tp,sl) for t in trades]
    pnls=[r[0] for r in res]; exits=[r[1] for r in res]
    df=pd.DataFrame({'pnl':pnls,'exit':exits})
    w=df[df['pnl']>0]; l=df[df['pnl']<=0]
    wr=len(w)/len(df); pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    wpw=len(trades)/len(all_dates)*5
    return {'label':label,'n':len(df),'wpw':round(wpw,1),'wr':round(wr*100,1),
            'pf':round(pf,2),'ev':round(df['pnl'].mean(),2),
            'total':round(df['pnl'].sum(),2),'ann':round(df['pnl'].sum(),2),
            'tp_n':exits.count('TP'),'sl_n':exits.count('SL')}

def pr(r):
    if not r: print("  No trades"); return
    print(f"  {r['label']:<45} n={r['n']:4d} ({r['wpw']:.1f}/wk)  WR={r['wr']}%  "
          f"PF={r['pf']}x  EV=${r['ev']}  Ann=${r['ann']}/yr  TP={r['tp_n']} SL={r['sl_n']}")

print("="*70)
print("GAP-DOWN BOUNCE LONG (PDL/PML support) — 1 Year")
print("="*70)

print("\n── OVERALL ────────────────────────────────────────────────────")
pr(run(raw, label="all gap-down bounces"))

print("\n── BY SPY REGIME ──────────────────────────────────────────────")
pr(run([t for t in raw if t['spy_regime']=='up'],  label="SPY up day"))
pr(run([t for t in raw if t['spy_regime']=='dn'],  label="SPY down day"))
pr(run([t for t in raw if t['spy_regime']=='neutral'], label="SPY neutral day"))

print("\n── BY LEVEL TYPE ──────────────────────────────────────────────")
pr(run([t for t in raw if t['level_type']=='PDL'], label="bounce off PDL"))
pr(run([t for t in raw if t['level_type']=='PML'], label="bounce off PML"))

print("\n── GAP SIZE FILTER ────────────────────────────────────────────")
for gap in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
    t = [x for x in raw if x['gap_pct'] <= -gap]
    pr(run(t, label=f"gap-down >{gap}%"))

print("\n── SPY UP + GAP DOWN (counter-trend bounce) ───────────────────")
for gap in [1.0, 1.5, 2.0, 2.5]:
    t = [x for x in raw if x['gap_pct']<=-gap and x['spy_regime']=='up']
    pr(run(t, label=f"spy_up + gap-dn >{gap}%"))

print("\n── TP/SL SWEEP (best filter: gap >1.5%, spy up) ───────────────")
best = [t for t in raw if t['gap_pct']<=-1.5 and t['spy_regime']=='up']
print(f"  Pool: {len(best)} trades ({len(best)/len(all_dates)*5:.1f}/wk)\n")
rows=[]
for tp,sl in iproduct([10,15,20,25,35,50],[-5,-8,-10,-12,-15,-20]):
    res=[sim_trade(t,tp,sl) for t in best]
    pnls=[r[0] for r in res]; exits=[r[1] for r in res]
    df2=pd.DataFrame({'pnl':pnls})
    w=df2[df2['pnl']>0]; l=df2[df2['pnl']<=0]
    wr=len(w)/len(df2) if len(df2) else 0
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    rows.append({'tp':tp,'sl':sl,'n':len(df2),'wr':round(wr*100,1),'pf':round(pf,2),
                 'total':round(df2['pnl'].sum(),2),'tp_hits':exits.count('TP')})
sw=pd.DataFrame(rows).sort_values('total',ascending=False)
print(sw.head(15)[['tp','sl','n','wr','pf','total','tp_hits']].to_string(index=False))

print("\n── MONTHLY (gap >1.5%, spy up, TP=25, SL=-10) ────────────────")
mrows=[]
for t in best:
    pnl,ext=sim_trade(t,25.0,-10.0)
    mrows.append({'date':t['date'],'pnl':pnl})
mdf=pd.DataFrame(mrows)
if not mdf.empty:
    mdf['month']=pd.to_datetime(mdf['date']).dt.to_period('M')
    mb=mdf.groupby('month').agg(n=('pnl','count'),pnl=('pnl','sum'),
        wr=('pnl',lambda x:f"{(x>0).mean()*100:.0f}%"),avg=('pnl','mean')).round(2)
    print(mb.to_string())
