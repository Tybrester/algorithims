"""
BOOF60 Gap Direction Test
LONG  : SPY+QQQ up day  + stock gaps UP   >1.5% + breaks PDH → call
SHORT : SPY+QQQ down day + stock gaps DOWN >1.5% + breaks PDL → put
2yr, 60 symbols, TP=25%, SL=-10%, flat exit 20 bars, 3x mult
"""
import os, pytz, pickle
import pandas as pd
import numpy as np

ET     = pytz.timezone('America/New_York')
CACHE  = "boof_data"
SUFFIX = "_5m_2yr.parquet"
BUDGET = 750.0
TP     = 25.0
SL     = -10.0
MULT   = 3.0
GAP_MIN    = 1.5
MAX_BARS   = 60
FLAT_BARS  = 20
FLAT_THRESH= 3.0
MAX_POS    = 5

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
print(f"  {len(data)} symbols")

print("Building daily OHLC...")
daily = {}
for sym, df in data.items():
    rth = df.between_time('09:30','16:00')
    d   = rth.resample('1D').agg(open=('open','first'),high=('high','max'),
                                  low=('low','min'),close=('close','last')).dropna()
    daily[sym] = d

spy_d = daily['SPY']; qqq_d = daily.get('QQQ', pd.DataFrame())
all_dates = sorted(spy_d.index.date)[1:]

to_date = lambda d: d.date() if hasattr(d,'date') else d
spy_up = {to_date(d) for d,r in spy_d.iterrows() if r['close']>r['open']}
spy_dn = {to_date(d) for d,r in spy_d.iterrows() if r['close']<r['open']}
qqq_up = {to_date(d) for d,r in qqq_d.iterrows() if r['close']>r['open']} if not qqq_d.empty else set()
qqq_dn = {to_date(d) for d,r in qqq_d.iterrows() if r['close']<r['open']} if not qqq_d.empty else set()

long_days  = spy_up & qqq_up
short_days = spy_dn & qqq_dn
print(f"  {len(all_dates)} days | UP: {len(long_days)} | DOWN: {len(short_days)} | Mixed: {len(all_dates)-len(long_days)-len(short_days)}\n")

PKL = "boof60_gapdirs_paths.pkl"
if os.path.exists(PKL):
    print(f"Loading cached paths...")
    with open(PKL,'rb') as f: raw = pickle.load(f)
    print(f"  {len(raw)} paths\n")
else:
    print("Collecting signals (both directions)...")
    raw = []
    for di, day in enumerate(all_dates):
        if di % 100 == 0: print(f"  Day {di}/{len(all_dates)} — {day}  trades: {len(raw)}")
        is_long  = day in long_days
        is_short = day in short_days
        if not is_long and not is_short: continue

        spy_prices=[]; regime="neutral"; active_pos={}
        spy_rth = data['SPY'][data['SPY'].index.date==day].between_time('09:30','15:55')

        for sym in SYMBOLS:
            if sym not in data or sym not in daily: continue
            dh=daily[sym]; prev=dh[dh.index.date<day]
            if len(prev)<1: continue
            prev_close = float(prev['close'].iloc[-1])
            pdh        = float(prev['high'].iloc[-1])
            pdl        = float(prev['low'].iloc[-1])

            bars_5m = data[sym]
            rth = bars_5m[bars_5m.index.date==day].between_time('09:30','15:55')
            if len(rth)<2: continue

            day_open = float(rth['open'].iloc[0])
            gap_pct  = (day_open - prev_close) / prev_close * 100  # + = gap up, - = gap down

            # Filter: long days need gap UP, short days need gap DOWN
            if is_long  and gap_pct < GAP_MIN:  continue
            if is_short and gap_pct > -GAP_MIN: continue

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
                    t=in_trade; ep=t['entry_price']; direction=t['direction']
                    if direction=='long':
                        stk=(price-ep)/ep*100; mfe=(high-ep)/ep*100; mae=(low-ep)/ep*100
                    else:
                        stk=(ep-price)/ep*100; mfe=(ep-low)/ep*100; mae=(ep-high)/ep*100
                    t['bars_held']+=1
                    bar_path.append({'opt_pct':stk*MULT,'mfe_opt':mfe*MULT,'mae_opt':mae*MULT,'hm':hm})
                    if t['bars_held']>=MAX_BARS or hm>='15:50':
                        raw.append({'date':day,'sym':sym,'direction':direction,
                            'entry_time':t['entry_time'],'gap_pct':round(gap_pct,2),
                            'bars':bar_path,'day_type':'up' if is_long else 'down'})
                        in_trade=None; bar_path=[]
                        if sym in active_pos: del active_pos[sym]
                    continue

                if hm>'10:00': break
                if len(active_pos)>=MAX_POS: continue

                # LONG: gap up + breaks PDH
                if is_long and price>pdh:
                    if not confirm: confirm=True; continue
                    if regime in ('bull','neutral'):
                        in_trade={'direction':'long','entry_price':price,'entry_time':hm,'bars_held':0}
                        active_pos[sym]=True

                # SHORT: gap down + breaks PDL
                if is_short and price<pdl:
                    if not confirm: confirm=True; continue
                    if regime in ('bear','neutral'):
                        in_trade={'direction':'short','entry_price':price,'entry_time':hm,'bars_held':0}
                        active_pos[sym]=True

            if in_trade and bar_path:
                raw.append({'date':day,'sym':sym,'direction':in_trade['direction'],
                    'entry_time':in_trade['entry_time'],'gap_pct':round(gap_pct,2),
                    'bars':bar_path,'day_type':'up' if is_long else 'down'})

    with open(PKL,'wb') as f: pickle.dump(raw,f)
    print(f"\n  {len(raw)} paths cached\n")

# ── Simulate ──────────────────────────────────────────────────────
def sim_trade(t, tp=TP, sl=SL):
    for j,b in enumerate(t['bars']):
        if b['mfe_opt']>=tp:  return BUDGET*tp/100, 'TP'
        if b['mae_opt']<=sl:  return BUDGET*sl/100, 'SL'
        if j>=FLAT_BARS and abs(b['opt_pct'])<FLAT_THRESH:
            return BUDGET*b['opt_pct']/100, 'FLAT'
    last=t['bars'][-1]
    return BUDGET*last['opt_pct']/100, 'TIMEOUT'

rows=[]
for t in raw:
    pnl,ext=sim_trade(t)
    rows.append({'pnl':pnl,'exit':ext,'date':t['date'],'sym':t['sym'],
                 'direction':t['direction'],'day_type':t['day_type'],'gap_pct':t['gap_pct']})
df=pd.DataFrame(rows)

def stats(subset, label):
    if subset.empty: print(f"  {label}: no trades"); return
    w=subset[subset['pnl']>0]; l=subset[subset['pnl']<=0]
    wr=len(w)/len(subset)
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    wpw=len(subset)/len(all_dates)*5
    print(f"  {label:<40} n={len(subset):4d} ({wpw:.1f}/wk)  WR={wr*100:.1f}%  PF={pf:.2f}x  "
          f"Total=${subset['pnl'].sum():>9.2f}  Ann=${subset['pnl'].sum()/2:>9.2f}/yr")

print(f"{'='*75}")
print("BOOF60 GAP DIRECTION RESULTS — 2 Years")
print(f"{'='*75}")
stats(df,                                "COMBINED")
stats(df[df['direction']=='long'],       "LONGS only (gap-up + SPY up)")
stats(df[df['direction']=='short'],      "SHORTS only (gap-down + SPY dn)")

print(f"\n── GAP THRESHOLD SWEEP ───────────────────────────────────────")
print(f"  {'Filter':<45} {'n':>5}  {'WR':>6}  {'PF':>5}  {'Ann':>12}")
for gap in [1.0, 1.5, 2.0, 2.5, 3.0]:
    longs  = [t for t in raw if t['direction']=='long'  and t['gap_pct']>=gap]
    shorts = [t for t in raw if t['direction']=='short' and t['gap_pct']<=-gap]
    combo  = longs + shorts
    if not combo: continue
    r2=[]
    for t in combo:
        pnl,ext=sim_trade(t)
        r2.append({'pnl':pnl})
    d2=pd.DataFrame(r2)
    w2=d2[d2['pnl']>0]; l2=d2[d2['pnl']<=0]
    wr2=len(w2)/len(d2)
    pf2=w2['pnl'].sum()/abs(l2['pnl'].sum()) if l2['pnl'].sum()!=0 else 999
    ann=d2['pnl'].sum()/2
    wpw=len(combo)/len(all_dates)*5
    print(f"  gap>{gap}% both directions{'':<20} {len(combo):>5} ({wpw:.1f}/wk)  {wr2*100:>5.1f}%  {pf2:>5.2f}x  ${ann:>10.2f}/yr")

print(f"\n── TP/SL SWEEP on COMBINED (best gap) ───────────────────────")
from itertools import product as iproduct
best_gap=1.5
combo=[t for t in raw if (t['direction']=='long' and t['gap_pct']>=best_gap) or
                          (t['direction']=='short' and t['gap_pct']<=-best_gap)]
print(f"  Pool: {len(combo)} trades ({len(combo)/len(all_dates)*5:.1f}/wk)\n")
sweep=[]
for tp,sl in iproduct([15,20,25,35,50],[5,8,10,12,15,20]):
    r2=[]
    for t in combo:
        pnl,ext=sim_trade(t,tp=tp,sl=-sl)
        r2.append({'pnl':pnl,'exit':ext})
    d2=pd.DataFrame(r2)
    w2=d2[d2['pnl']>0]; l2=d2[d2['pnl']<=0]
    wr2=len(w2)/len(d2) if len(d2) else 0
    pf2=w2['pnl'].sum()/abs(l2['pnl'].sum()) if l2['pnl'].sum()!=0 else 999
    sweep.append({'tp':tp,'sl':sl,'n':len(d2),'wr':round(wr2*100,1),'pf':round(pf2,2),
                  'total':round(d2['pnl'].sum(),2),'ann':round(d2['pnl'].sum()/2,2),
                  'tp_hits':len(d2[d2['exit']=='TP'])})
sw=pd.DataFrame(sweep).sort_values('total',ascending=False)
print(sw.head(15)[['tp','sl','n','wr','pf','total','ann','tp_hits']].to_string(index=False))

print(f"\n── MONTHLY (combined, base TP/SL) ───────────────────────────")
df['month']=pd.to_datetime(df['date']).dt.to_period('M')
mb=df.groupby('month').agg(n=('pnl','count'),pnl=('pnl','sum'),
    wr=('pnl',lambda x:f"{(x>0).mean()*100:.0f}%"),avg=('pnl','mean')).round(2)
print(mb.to_string())

print(f"\n── MONTE CARLO ───────────────────────────────────────────────")
pnls=df['pnl'].values
np.random.seed(42)
mc=np.array([np.random.choice(pnls,size=len(pnls),replace=True).sum() for _ in range(10000)])
print(f"  Prob > $0:      {(mc>0).mean()*100:.1f}%")
print(f"  5th pct:        ${np.percentile(mc,5):,.0f}")
print(f"  Median:         ${np.percentile(mc,50):,.0f}")
print(f"  95th pct:       ${np.percentile(mc,95):,.0f}")
monthly=df.groupby('month')['pnl'].sum()
sharpe=monthly.mean()/monthly.std()*np.sqrt(12) if monthly.std()>0 else 0
print(f"  Monthly Sharpe: {sharpe:.2f}")
print(f"  +ve months:     {(monthly>0).sum()}/{len(monthly)}")
print(f"  Worst month:    ${monthly.min():.2f}")
print(f"  Best month:     ${monthly.max():.2f}")

df.to_csv('boof60_gapdirs_trades.csv',index=False)
print(f"\nTrade log → boof60_gapdirs_trades.csv")
