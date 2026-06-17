"""
BOOF60 Gap-Down Short Test
SPY+QQQ both down on the day + stock gaps down >1.5% + breaks PDL → put
1 year: Jun 2025 - Jun 2026, 60 symbols, TP=25%, SL=-10%, flat exit 20 bars, 3x mult
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
MAX_BARS   = 60
FLAT_BARS  = 20
FLAT_THRESH= 3.0
MAX_POS    = 5
START_DATE = "2025-06-01"   # 1 year

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
daily = {}
by_date = {}   # by_date[sym][date] = rth DataFrame for that day
for sym, df in data.items():
    rth = df.between_time('09:30','16:00')
    d   = rth.resample('1D').agg(open=('open','first'),high=('high','max'),
                                  low=('low','min'),close=('close','last')).dropna()
    daily[sym] = d
    # pre-group by date
    grp = {}
    for dt, grp_df in rth.groupby(rth.index.date):
        grp[dt] = grp_df
    by_date[sym] = grp

spy_d = daily['SPY']; qqq_d = daily.get('QQQ', pd.DataFrame())
to_d  = lambda d: d.date() if hasattr(d,'date') else d
spy_dn = {to_d(d) for d,r in spy_d.iterrows() if r['close'] < r['open']}
qqq_dn = {to_d(d) for d,r in qqq_d.iterrows() if r['close'] < r['open']} if not qqq_d.empty else set()
short_days = spy_dn & qqq_dn

from datetime import date as date_type
import datetime
start = datetime.date.fromisoformat(START_DATE)
all_dates = sorted(d for d in spy_d.index.date if d >= start)[1:]
test_short_days = [d for d in all_dates if d in short_days]
print(f"  {len(all_dates)} trading days | SPY+QQQ down days: {len(test_short_days)}\n")

# ── Collect signals ───────────────────────────────────────────────
print("Collecting gap-down short signals...")
raw = []
for di, day in enumerate(all_dates):
    if day not in short_days: continue
    spy_prices=[]; regime="neutral"; active_pos={}
    spy_rth = by_date.get('SPY',{}).get(day, pd.DataFrame())

    for sym in SYMBOLS:
        if sym not in by_date or sym not in daily: continue
        dh=daily[sym]; prev=dh[dh.index.date<day]
        if len(prev)<1: continue
        prev_close = float(prev['close'].iloc[-1])
        pdl        = float(prev['low'].iloc[-1])
        rth = by_date[sym].get(day, pd.DataFrame())
        if len(rth)<2: continue

        day_open = float(rth['open'].iloc[0])
        gap_pct  = (day_open - prev_close) / prev_close * 100  # negative = gap down

        confirm=False; in_trade=None; bar_path=[]
        for i,(ts,bar) in enumerate(rth.iterrows()):
            hm    = ts.strftime('%H:%M')
            price = float(bar['close'])
            high  = float(bar['high'])
            low   = float(bar['low'])

            if i<len(spy_rth):
                spy_prices.append(float(spy_rth.iloc[min(i,len(spy_rth)-1)]['close']))
                if len(spy_prices)>5: spy_prices.pop(0)
                if len(spy_prices)>=3:
                    if   spy_prices[-1]>spy_prices[0]*1.001: regime="bull"
                    elif spy_prices[-1]<spy_prices[0]*0.999: regime="bear"
                    else: regime="neutral"

            if in_trade:
                ep=in_trade['entry_price']
                stk=(ep-price)/ep*100; mfe=(ep-low)/ep*100; mae=(ep-high)/ep*100
                in_trade['bars_held']+=1
                bar_path.append({'opt_pct':stk*MULT,'mfe_opt':mfe*MULT,'mae_opt':mae*MULT})
                if in_trade['bars_held']>=MAX_BARS or hm>='15:50':
                    raw.append({'date':day,'sym':sym,'entry_time':in_trade['entry_time'],
                                'gap_pct':round(gap_pct,2),'bars':bar_path})
                    in_trade=None; bar_path=[]
                    if sym in active_pos: del active_pos[sym]
                continue

            if hm>'10:00': break
            if len(active_pos)>=MAX_POS: continue

            # Signal: stock breaks below PDL (with gap-down filter per sweep below)
            if price < pdl:
                if not confirm: confirm=True; continue
                if regime in ('bear','neutral'):
                    in_trade={'entry_price':price,'entry_time':hm,'bars_held':0}
                    active_pos[sym]=True

        if in_trade and bar_path:
            raw.append({'date':day,'sym':sym,'entry_time':in_trade['entry_time'],
                        'gap_pct':round(gap_pct,2),'bars':bar_path})

print(f"  Total signals (no gap filter): {len(raw)}")
print(f"  Avg per week: {len(raw)/len(all_dates)*5:.1f}\n")

# ── Simulate ──────────────────────────────────────────────────────
def sim_trade(t, tp, sl):
    for j,b in enumerate(t['bars']):
        if b['mfe_opt']>=tp:  return BUDGET*tp/100,   'TP'
        if b['mae_opt']<=sl:  return BUDGET*sl/100,   'SL'
        if j>=FLAT_BARS and abs(b['opt_pct'])<FLAT_THRESH:
            return BUDGET*b['opt_pct']/100, 'FLAT'
    return BUDGET*t['bars'][-1]['opt_pct']/100, 'TIMEOUT'

def run(trades, tp, sl, label=""):
    if not trades: return None
    results=[sim_trade(t,tp,sl) for t in trades]
    pnls=[r[0] for r in results]; exits=[r[1] for r in results]
    df=pd.DataFrame({'pnl':pnls,'exit':exits})
    w=df[df['pnl']>0]; l=df[df['pnl']<=0]
    wr=len(w)/len(df)
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    wpw=len(trades)/len(all_dates)*5
    return {'label':label,'n':len(df),'wpw':round(wpw,1),'wr':round(wr*100,1),
            'pf':round(pf,2),'ev':round(df['pnl'].mean(),2),
            'total':round(df['pnl'].sum(),2),'ann':round(df['pnl'].sum(),2),
            'tp_n':exits.count('TP'),'sl_n':exits.count('SL')}

def pr(r):
    if not r: return
    print(f"  {r['label']:<42} n={r['n']:4d} ({r['wpw']:.1f}/wk)  WR={r['wr']}%  "
          f"PF={r['pf']}x  EV=${r['ev']}  Ann=${r['ann']}/yr  TP={r['tp_n']} SL={r['sl_n']}")

TP=25.0; SL=-10.0

print("="*70)
print("GAP-DOWN SHORT RESULTS (SPY+QQQ down days, 1 year)")
print("="*70)

# Gap filter sweep
print("\n── GAP THRESHOLD (how big must the gap-down be?) ─────────────")
for gap in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
    filtered = [t for t in raw if t['gap_pct'] <= -gap]
    r = run(filtered, TP, SL, f"gap-down >{gap}%")
    pr(r)

# Entry time
print("\n── ENTRY TIME WINDOW ──────────────────────────────────────────")
for cutoff in ['09:45','10:00','10:30','11:00']:
    filtered = [t for t in raw if t.get('entry_time','00:00') <= cutoff]
    r = run(filtered, TP, SL, f"entry ≤{cutoff}")
    pr(r)

# TP/SL sweep on best gap filter
print("\n── TP/SL SWEEP (gap-down >1.5%, entry ≤10:00) ────────────────")
best = [t for t in raw if t['gap_pct']<=-1.5 and t.get('entry_time','00:00')<='10:00']
print(f"  Pool: {len(best)} trades ({len(best)/len(all_dates)*5:.1f}/wk)\n")
rows=[]
for tp,sl in iproduct([10,15,20,25,35,50],[-5,-8,-10,-12,-15,-20]):
    results=[sim_trade(t,tp,sl) for t in best]
    pnls=[r[0] for r in results]; exits=[r[1] for r in results]
    df2=pd.DataFrame({'pnl':pnls,'exit':exits})
    w=df2[df2['pnl']>0]; l=df2[df2['pnl']<=0]
    wr=len(w)/len(df2) if len(df2) else 0
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    rows.append({'tp':tp,'sl':sl,'n':len(df2),'wr':round(wr*100,1),'pf':round(pf,2),
                 'total':round(df2['pnl'].sum(),2),'tp_hits':exits.count('TP')})
sw=pd.DataFrame(rows).sort_values('total',ascending=False)
print(sw.head(15)[['tp','sl','n','wr','pf','total','tp_hits']].to_string(index=False))

# Monthly on best combo
print("\n── MONTHLY (gap-down >1.5%, entry ≤10:00, TP=25, SL=-10) ────")
best_r=[]
for t in best:
    pnl,ext=sim_trade(t,25.0,-10.0)
    best_r.append({'date':t['date'],'pnl':pnl,'exit':ext})
mdf=pd.DataFrame(best_r)
if not mdf.empty:
    mdf['month']=pd.to_datetime(mdf['date']).dt.to_period('M')
    mb=mdf.groupby('month').agg(n=('pnl','count'),pnl=('pnl','sum'),
        wr=('pnl',lambda x:f"{(x>0).mean()*100:.0f}%"),avg=('pnl','mean')).round(2)
    print(mb.to_string())

# Compare vs longs
print("\n── COMPARISON vs GAP-UP LONGS (same period) ──────────────────")
long_trades=[t for t in raw if t['gap_pct']>=1.5 and t.get('entry_time','00:00')<='10:00']
# load longs from the 2yr paths pkl if it exists
import pickle, os
if os.path.exists('boof60_2yr_paths.pkl'):
    with open('boof60_2yr_paths.pkl','rb') as f: long_raw=pickle.load(f)
    from datetime import date as dtp
    long_1yr=[t for t in long_raw if t['date']>=start]
    rl=run(long_1yr,25.0,-10.0,"LONGS gap-up >1.5% spy-up (1yr)")
    rs=run(best,25.0,-10.0,"SHORTS gap-down >1.5% spy-dn (1yr)")
    rc=run(long_1yr+best,25.0,-10.0,"COMBINED both (1yr)")
    pr(rl); pr(rs); pr(rc)
