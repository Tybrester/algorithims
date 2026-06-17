"""
BOOF60 Bounce Level Deep Dive
Test which support levels produce the best gap-down bounces:
- PDL  (previous day low)
- PML  (pre-market low)
- PWL  (previous week low)
- P2DL (2-day low)
- P3DL (3-day low)
- VWAP (intraday VWAP as dynamic support)
- Round numbers ($5, $10, $25, $50, $100 etc)
- 50% retracement of prev day range
- Prior pivot lows (mirror of BOOF51 but low pivots)
All signals: SPY UP day + stock gaps down >1.5% + bounce off level
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
NEAR_PCT    = 0.002   # within 0.2% of level = touching
BOUNCE      = 0.002   # must bounce 0.2% off level

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
    grp = {}
    for dt, gdf in rth.groupby(rth.index.date): grp[dt] = gdf
    by_date[sym] = grp
    pmgrp = {}
    for dt, gdf in pm.groupby(pm.index.date): pmgrp[dt] = gdf
    pm_by_date[sym] = pmgrp

spy_d = daily['SPY']
to_d  = lambda d: d.date() if hasattr(d,'date') else d
spy_up = {to_d(d) for d,r in spy_d.iterrows() if r['close']>r['open']}

start = datetime.date.fromisoformat("2025-06-01")
all_dates = sorted(d for d in spy_d.index.date if d >= start)[1:]
print(f"  {len(all_dates)} days\n")

# ── Pivot low builder (mirror of BOOF51 pivot highs) ─────────────
def build_pivot_lows(bars, lookback, wing):
    hist = bars[-lookback:] if len(bars)>=lookback else bars
    if len(hist)<wing+1: return []
    L=[b['l'] for b in hist]
    raw=[L[i] for i in range(wing,len(hist)) if L[i]==min(L[max(0,i-wing):i+1])]
    if not raw: return []
    raw=sorted(raw,reverse=True); cl=[raw[0]]
    for lv in raw[1:]:
        if abs(lv-cl[-1])/cl[-1]<0.002: cl[-1]=(cl[-1]+lv)/2
        else: cl.append(lv)
    return cl

# ── Bounce state machine ──────────────────────────────────────────
def init_sm(): return {'state':'IDLE','extreme':None,'touch_num':0,'was_above':False,'broken':False}

def update_bounce_sm(sm, level, bar):
    low=bar['l']; close=bar['c']
    if close>level: sm['was_above']=True
    touching=sm['was_above'] and low<=level*(1+NEAR_PCT)
    if sm['state']=='IDLE':
        if touching: sm['state']='IN'; sm['extreme']=close; sm['touch_num']+=1
    elif sm['state']=='IN':
        if low<=level*(1+NEAR_PCT): sm['extreme']=max(sm['extreme'] or close, close)
        else:
            bounced=sm['extreme'] is not None and (sm['extreme']-level)/level>=BOUNCE
            req=2 if sm['broken'] else 1
            if bounced and sm['touch_num']==req: sm['state']='FIRED'; return True
            sm['state']='DEAD'; sm['broken']=True; sm['was_above']=False
    elif sm['state']=='DEAD':
        if sm['was_above']: sm['state']='IDLE'; sm['extreme']=None; sm['touch_num']=0
    return False

# ── Collect signals ───────────────────────────────────────────────
print("Collecting bounce signals from multiple level types...")
raw = []

for day in all_dates:
    if day not in spy_up: continue   # SPY up days only
    spy_prices=[]; regime="neutral"; active_pos={}
    spy_rth = by_date.get('SPY',{}).get(day, pd.DataFrame())

    for sym in SYMBOLS:
        if sym not in by_date or sym not in daily: continue
        dh=daily[sym]; prev=dh[dh.index.date<day]
        if len(prev)<2: continue

        prev_close = float(prev['close'].iloc[-1])
        rth = by_date[sym].get(day, pd.DataFrame())
        if len(rth)<2: continue

        day_open = float(rth['open'].iloc[0])
        gap_pct  = (day_open - prev_close) / prev_close * 100
        if gap_pct > -1.5: continue   # only gap-down >1.5%

        # ── Build all support levels ──────────────────────────────
        p1  = prev.iloc[-1]
        p2  = prev.iloc[-2] if len(prev)>=2 else p1
        p3  = prev.iloc[-3] if len(prev)>=3 else p2

        pdl  = float(p1['low'])
        p2dl = float(p2['low'])
        p3dl = float(p3['low'])
        p2dl_min = min(float(p1['low']), float(p2['low']))
        p3dl_min = min(float(p1['low']), float(p2['low']), float(p3['low']))

        # Previous week low
        prev_week = prev[prev.index.date < day]
        pwl = float(prev_week['low'].tail(5).min()) if len(prev_week)>=5 else pdl

        # 50% retracement of prev day range
        p1_range = float(p1['high']) - float(p1['low'])
        fib50 = float(p1['low']) + p1_range * 0.5
        fib38 = float(p1['low']) + p1_range * 0.382
        fib62 = float(p1['low']) + p1_range * 0.618

        # Pre-market low
        pm_bars = pm_by_date.get(sym,{}).get(day, pd.DataFrame())
        pml = float(pm_bars['low'].min()) if not pm_bars.empty else None

        # Round number levels near current price
        price_approx = day_open
        rounds = []
        for step in [1, 2, 5, 10, 25, 50, 100]:
            r = round(price_approx / step) * step
            if abs(r - price_approx)/price_approx < 0.05:
                rounds.append(r)

        # Prior pivot lows (10-bar lookback)
        prev_bars_df = data[sym][data[sym].index.date<day].between_time('09:30','16:00').tail(200)
        prev_bars = [{'h':float(r['high']),'l':float(r['low']),'c':float(r['close'])} for _,r in prev_bars_df.iterrows()]
        pivot_lows_10  = build_pivot_lows(prev_bars, 50, 3)
        pivot_lows_30  = build_pivot_lows(prev_bars, 150, 5)

        # Assemble all named levels (filter to below day_open)
        named_levels = {
            'PDL':  pdl,
            'P2DL': p2dl,
            'P3DL_min': p3dl_min,
            'PWL':  pwl,
            'FIB50': fib50,
            'FIB38': fib38,
            'FIB62': fib62,
        }
        if pml: named_levels['PML'] = pml
        for r in rounds: named_levels[f'ROUND_{r}'] = r
        for i,lv in enumerate(pivot_lows_10[:3]): named_levels[f'PIV10_{i}'] = lv
        for i,lv in enumerate(pivot_lows_30[:2]): named_levels[f'PIV30_{i}'] = lv

        # Only keep levels below day_open (valid support)
        valid_levels = {k:v for k,v in named_levels.items() if v < day_open * 0.998}
        if not valid_levels: continue

        lvl_sms = {k: init_sm() for k in valid_levels}
        confirm=False; confirm_price=None; in_trade=None; bar_path=[]; fired=False

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
                                'gap_pct':round(gap_pct,2),'level_type':in_trade['level_type'],
                                'level_category':in_trade['level_category'],'bars':bar_path})
                    in_trade=None; bar_path=[]
                    if sym in active_pos: del active_pos[sym]
                continue

            if hm>'11:00': break
            if len(active_pos)>=MAX_POS or fired: continue

            for lname, lval in valid_levels.items():
                sm = lvl_sms[lname]
                if sm['state']=='FIRED': continue
                if update_bounce_sm(sm, lval, bdict):
                    if not confirm:
                        confirm=True; confirm_price=price
                    else:
                        if price > confirm_price:
                            # Categorize level type
                            if lname in ('PDL','P2DL','P3DL_min'): cat='DAY_LOWS'
                            elif lname == 'PML': cat='PML'
                            elif lname == 'PWL': cat='PWL'
                            elif lname.startswith('FIB'): cat='FIBS'
                            elif lname.startswith('ROUND'): cat='ROUND'
                            elif lname.startswith('PIV'): cat='PIVOT_LOWS'
                            else: cat='OTHER'
                            fired=True
                            in_trade={'entry_price':price,'entry_time':hm,'bars_held':0,
                                      'level_type':lname,'level_category':cat}
                            active_pos[sym]=True; break

        if in_trade and bar_path:
            raw.append({'date':day,'sym':sym,'entry_time':in_trade['entry_time'],
                        'gap_pct':round(gap_pct,2),'level_type':in_trade['level_type'],
                        'level_category':in_trade['level_category'],'bars':bar_path})

print(f"  Total signals: {len(raw)} ({len(raw)/len(all_dates)*5:.1f}/wk)\n")

# ── Simulate ──────────────────────────────────────────────────────
def sim_trade(t, tp=25.0, sl=-10.0):
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
    wr=len(w)/len(df) if len(df) else 0
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    wpw=len(trades)/len(all_dates)*5
    return {'label':label,'n':len(df),'wpw':round(wpw,1),'wr':round(wr*100,1),
            'pf':round(pf,2),'ev':round(df['pnl'].mean(),2),
            'total':round(df['pnl'].sum(),2),'ann':round(df['pnl'].sum(),2),
            'tp_n':exits.count('TP'),'sl_n':exits.count('SL')}

def pr(r):
    if not r: print("  No trades"); return
    print(f"  {r['label']:<38} n={r['n']:4d} ({r['wpw']:.1f}/wk)  WR={r['wr']}%  "
          f"PF={r['pf']}x  EV=${r['ev']}  Ann=${r['ann']}/yr  TP={r['tp_n']} SL={r['sl_n']}")

print("="*70)
print("BOUNCE LEVEL COMPARISON (SPY up + gap-down >1.5%, 1yr)")
print("="*70)

print("\n── BY LEVEL CATEGORY ──────────────────────────────────────────")
pr(run(raw, label="ALL LEVELS"))
for cat in ['DAY_LOWS','PML','PWL','FIBS','ROUND','PIVOT_LOWS']:
    t=[x for x in raw if x['level_category']==cat]
    pr(run(t, label=cat))

print("\n── BY SPECIFIC LEVEL ──────────────────────────────────────────")
level_counts = {}
for t in raw: level_counts[t['level_type']] = level_counts.get(t['level_type'],0)+1
top_levels = sorted(level_counts, key=lambda x: -level_counts[x])[:15]
for lname in top_levels:
    t=[x for x in raw if x['level_type']==lname]
    pr(run(t, label=lname))

print("\n── BEST CATEGORIES COMBINED ───────────────────────────────────")
combos = [
    ("PDL only",             ['PDL']),
    ("PDL + PML",            ['PDL','PML']),
    ("PDL + PIVOT_LOWS",     ['PDL','PIV10_0','PIV10_1','PIV30_0']),
    ("PDL + FIBs",           ['PDL','FIB50','FIB38','FIB62']),
    ("PML + PIVOT_LOWS",     ['PML','PIV10_0','PIV10_1']),
    ("ROUND + PIVOT",        [l for l in top_levels if l.startswith('ROUND') or l.startswith('PIV')]),
    ("DAY_LOWS + PML",       ['PDL','P2DL','P3DL_min','PML']),
    ("ALL minus ROUND",      [l for l in [t['level_type'] for t in raw] if not l.startswith('ROUND')]),
]
for label, lnames in combos:
    t=[x for x in raw if x['level_type'] in lnames]
    pr(run(t, label=label))

print("\n── TP/SL SWEEP on best level combo ────────────────────────────")
# Find best category
best_cat = max(['DAY_LOWS','PML','PWL','FIBS','ROUND','PIVOT_LOWS'],
               key=lambda c: run([x for x in raw if x['level_category']==c])['total'] if run([x for x in raw if x['level_category']==c]) else -999)
best_trades = [x for x in raw if x['level_category']==best_cat]
print(f"  Best category: {best_cat}  ({len(best_trades)} trades)\n")
rows=[]
for tp,sl in iproduct([10,15,20,25,35,50],[-5,-8,-10,-12,-15,-20]):
    res=[sim_trade(t,tp,sl) for t in best_trades]
    pnls=[r[0] for r in res]; exits=[r[1] for r in res]
    df2=pd.DataFrame({'pnl':pnls})
    w=df2[df2['pnl']>0]; l=df2[df2['pnl']<=0]
    wr=len(w)/len(df2) if len(df2) else 0
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    rows.append({'tp':tp,'sl':sl,'n':len(df2),'wr':round(wr*100,1),'pf':round(pf,2),
                 'total':round(df2['pnl'].sum(),2),'tp_hits':exits.count('TP')})
sw=pd.DataFrame(rows).sort_values('total',ascending=False)
print(sw.head(15)[['tp','sl','n','wr','pf','total','tp_hits']].to_string(index=False))

print("\n── MONTHLY (best category, TP=25, SL=-10) ────────────────────")
mrows=[]
for t in best_trades:
    pnl,ext=sim_trade(t,25.0,-10.0)
    mrows.append({'date':t['date'],'pnl':pnl,'level':t['level_type']})
mdf=pd.DataFrame(mrows)
if not mdf.empty:
    mdf['month']=pd.to_datetime(mdf['date']).dt.to_period('M')
    mb=mdf.groupby('month').agg(n=('pnl','count'),pnl=('pnl','sum'),
        wr=('pnl',lambda x:f"{(x>0).mean()*100:.0f}%"),avg=('pnl','mean')).round(2)
    print(mb.to_string())
