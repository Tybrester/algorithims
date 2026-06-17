"""
BOOF60 2-Year Walk-Forward Test
Reuses boof60_final_paths.pkl if exists, otherwise collects signals
Train 6 months -> Test 2 months, rolling 6 windows
"""
import os, pytz, datetime, pickle
import pandas as pd
import numpy as np

ET     = pytz.timezone('America/New_York')
CACHE  = "boof_data"
SUFFIX = "_5m_2yr.parquet"
BUDGET = 750.0
MULT   = 3.0
MAX_BARS=60; FLAT_BARS=20; FLAT_THRESH=3.0; MAX_POS=5
TP=25.0; SL=-10.0

SYMBOLS = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX',
    'SOFI','IONQ','RGTI','QUBT','ACHR','JOBY','LUNR','RDDT','CAVA','DUOL',
    'CELH','DKNG','MELI','SHOP','PYPL','SPOT','PINS','SNAP','LYFT','RIVN',
    'LCID','CHWY','SOUN','BBAI','AI','ASTS','RKLB','IREN','CORZ',
]

def load_sym(sym):
    path=os.path.join(CACHE,f"{sym}{SUFFIX}")
    if not os.path.exists(path): return pd.DataFrame()
    df=pd.read_parquet(path)
    df.columns=[c.lower() for c in df.columns]
    if df.index.tz is None: df.index=df.index.tz_localize('UTC')
    df.index=df.index.tz_convert(ET)
    return df

PKL="boof60_final_paths.pkl"
if os.path.exists(PKL):
    print(f"Loading cached 2yr paths...")
    with open(PKL,'rb') as f: raw=pickle.load(f)
    print(f"  {len(raw)} paths loaded\n")
    # still need all_dates for window math
    print("Loading SPY for date list...")
    spy_df=load_sym('SPY')
    spy_d=spy_df.between_time('09:30','16:00').resample('1D').agg(
        open=('open','first'),close=('close','last')).dropna()
    all_dates=sorted(spy_d.index.date)[1:]
else:
    print("Loading data for signal collection...")
    data={sym:load_sym(sym) for sym in SYMBOLS+['SPY','QQQ']}
    data={k:v for k,v in data.items() if not v.empty}
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
    both_up={to_d(d) for d,r in spy_d.iterrows() if r['close']>r['open']} & \
            ({to_d(d) for d,r in qqq_d.iterrows() if r['close']>r['open']} if not qqq_d.empty else set())
    both_dn={to_d(d) for d,r in spy_d.iterrows() if r['close']<r['open']} & \
            ({to_d(d) for d,r in qqq_d.iterrows() if r['close']<r['open']} if not qqq_d.empty else set())
    all_dates=sorted(spy_d.index.date)[1:]
    print(f"  {len(all_dates)} days | up:{sum(1 for d in all_dates if d in both_up)} dn:{sum(1 for d in all_dates if d in both_dn)}")
    print("Collecting signals...")
    raw=[]
    for di,day in enumerate(all_dates):
        if di%100==0: print(f"  Day {di}/{len(all_dates)} trades:{len(raw)}")
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
            if is_long and gap_pct<0.5: continue
            if is_short and gap_pct>-0.5: continue
            p1=prev.iloc[-1]
            pdh=float(p1['high']); pdl=float(p1['low'])
            pwh=float(prev.tail(5)['high'].max()); pwl=float(prev.tail(5)['low'].min())
            p10h=float(prev.tail(10)['high'].max()); p10l=float(prev.tail(10)['low'].min())
            p20h=float(prev.tail(20)['high'].max()); p20l=float(prev.tail(20)['low'].min())
            pm_bars=pm_by_date.get(sym,{}).get(day,pd.DataFrame())
            pmh=float(pm_bars['high'].max()) if not pm_bars.empty else None
            pml=float(pm_bars['low'].min())  if not pm_bars.empty else None
            if is_long:
                brk_levels={k:v for k,v in [('PDH',pdh),('PWH',pwh),('P10H',p10h),('P20H',p20h)]+
                            ([('PMH',pmh)] if pmh else []) if v>day_open}
            else:
                brk_levels={k:v for k,v in [('PDL',pdl),('PWL',pwl),('P10L',p10l),('P20L',p20l)]+
                            ([('PML',pml)] if pml else []) if v<day_open}
            if not brk_levels: continue
            brk_broken=set(); brk_confirm=None; brk_confirm_price=None
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
                    stk=(price-ep)/ep*100 if direction=='long' else (ep-price)/ep*100
                    mfe=(high-ep)/ep*100  if direction=='long' else (ep-low)/ep*100
                    mae=(low-ep)/ep*100   if direction=='long' else (ep-high)/ep*100
                    in_trade['bars_held']+=1
                    bar_path.append({'opt_pct':stk*MULT,'mfe_opt':mfe*MULT,'mae_opt':mae*MULT})
                    if in_trade['bars_held']>=MAX_BARS or hm>='15:50':
                        raw.append({'date':day,'sym':sym,'direction':direction,
                            'entry_time':in_trade['entry_time'],'gap_pct':round(gap_pct,2),
                            'signal':in_trade['signal'],'level':in_trade['level'],'bars':bar_path})
                        in_trade=None; bar_path=[]; fired=False
                        if sym in active_pos: del active_pos[sym]
                    continue
                if hm>'10:30': break
                if len(active_pos)>=MAX_POS or fired: continue
                direction='long' if is_long else 'short'
                for lname,lval in sorted(brk_levels.items(),key=lambda x:x[1] if is_short else -x[1]):
                    if lname in brk_broken: continue
                    broke=(price>lval*1.001) if is_long else (price<lval*0.999)
                    if broke:
                        brk_broken.add(lname)
                        if brk_confirm is None: brk_confirm=lname; brk_confirm_price=price
                        else:
                            ok=(price>=brk_confirm_price) if is_long else (price<=brk_confirm_price)
                            if ok:
                                fired=True
                                in_trade={'direction':direction,'entry_price':price,'entry_time':hm,
                                          'bars_held':0,'signal':'BRK_UP' if is_long else 'BRK_DN','level':brk_confirm}
                                active_pos[sym]=True; break
                if not fired and brk_confirm:
                    ok=(price>=brk_confirm_price) if is_long else (price<=brk_confirm_price)
                    if ok:
                        fired=True
                        in_trade={'direction':direction,'entry_price':price,'entry_time':hm,
                                  'bars_held':0,'signal':'BRK_UP' if is_long else 'BRK_DN','level':brk_confirm}
                        active_pos[sym]=True
            if in_trade and bar_path:
                raw.append({'date':day,'sym':sym,'direction':in_trade['direction'],
                    'entry_time':in_trade['entry_time'],'gap_pct':round(gap_pct,2),
                    'signal':in_trade['signal'],'level':in_trade['level'],'bars':bar_path})
    with open(PKL,'wb') as f: pickle.dump(raw,f)
    print(f"  {len(raw)} paths cached\n")

# ── Sim ───────────────────────────────────────────────────────────
def sim(t,tp=TP,sl=SL):
    for j,b in enumerate(t['bars']):
        if b['mfe_opt']>=tp:  return BUDGET*tp/100,'TP'
        if b['mae_opt']<=sl:  return BUDGET*sl/100,'SL'
        if j>=FLAT_BARS and abs(b['opt_pct'])<FLAT_THRESH:
            return BUDGET*b['opt_pct']/100,'FLAT'
    return BUDGET*t['bars'][-1]['opt_pct']/100,'TIMEOUT'

def run(trades,label=""):
    if not trades: return None
    res=[sim(t) for t in trades]
    pnls=[r[0] for r in res]; exits=[r[1] for r in res]
    df=pd.DataFrame({'pnl':pnls,'exit':exits,'date':[t['date'] for t in trades]})
    w=df[df['pnl']>0]; l=df[df['pnl']<=0]
    wr=len(w)/len(df)
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    days=max((df['date'].max()-df['date'].min()).days,1)
    return {'label':label,'n':len(df),'wr':round(wr*100,1),'pf':round(pf,2),
            'ev':round(df['pnl'].mean(),2),'total':round(df['pnl'].sum(),2),
            'ann':round(df['pnl'].sum()/days*252,2),'df':df}

# ═══════════════════════════════════════════════════════════════════
# FULL 2-YEAR
# ═══════════════════════════════════════════════════════════════════
print("="*65)
print("FULL 2-YEAR BACKTEST")
print("="*65)
full=run(raw)
wpw=full['n']/len(all_dates)*5
print(f"  Period:      {all_dates[0]} → {all_dates[-1]}")
print(f"  Trades:      {full['n']}  ({wpw:.1f}/wk)")
print(f"  Win Rate:    {full['wr']}%")
print(f"  Prof Factor: {full['pf']}x")
print(f"  EV/trade:    ${full['ev']}")
print(f"  Total 2yr:   ${full['total']:,.2f}")
print(f"  Annualized:  ${full['ann']:,.2f}/yr")

print("\n  Per signal:")
for sig in ['BRK_UP','BRK_DN']:
    t=[x for x in raw if x['signal']==sig]
    r=run(t)
    if r: print(f"    {sig}  n={r['n']} ({r['n']/len(all_dates)*5:.1f}/wk)  WR={r['wr']}%  PF={r['pf']}x  Ann=${r['ann']:,.0f}/yr")

print("\n  Monthly:")
full['df']['month']=pd.to_datetime(full['df']['date']).dt.to_period('M')
mb=full['df'].groupby('month').agg(n=('pnl','count'),pnl=('pnl','sum'),
    wr=('pnl',lambda x:f"{(x>0).mean()*100:.0f}%"),avg=('pnl','mean')).round(2)
print(mb.to_string())

# ═══════════════════════════════════════════════════════════════════
# WALK-FORWARD
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*65}")
print("WALK-FORWARD  (train 6mo → test 2mo, 6 windows)")
print("="*65)

TRAIN=126; TEST=42
wf=[]
for i in range(8):
    ts=i*TEST; te=ts+TRAIN; xs=te; xe=xs+TEST
    if xe>len(all_dates): break
    train_set=set(all_dates[ts:te]); test_set=set(all_dates[xs:xe])
    tr=run([t for t in raw if t['date'] in train_set])
    te_r=run([t for t in raw if t['date'] in test_set])
    if not tr or not te_r: continue
    wf.append({'w':i+1,'tr_start':all_dates[ts],'tr_end':all_dates[te-1],
               'te_start':all_dates[xs],'te_end':all_dates[xe-1],
               'tr_n':tr['n'],'tr_wr':tr['wr'],'tr_pf':tr['pf'],'tr_pnl':tr['total'],
               'te_n':te_r['n'],'te_wr':te_r['wr'],'te_pf':te_r['pf'],'te_pnl':te_r['total'],
               'te_ann':te_r['ann']})
    print(f"\n  Window {i+1}:")
    print(f"    TRAIN {all_dates[ts]}→{all_dates[te-1]}  n={tr['n']}  WR={tr['wr']}%  PF={tr['pf']}x  P&L=${tr['total']:>9,.2f}")
    print(f"    TEST  {all_dates[xs]}→{all_dates[xe-1]}  n={te_r['n']}  WR={te_r['wr']}%  PF={te_r['pf']}x  P&L=${te_r['total']:>9,.2f}  Ann=${te_r['ann']:>10,.2f}/yr")

wf_df=pd.DataFrame(wf)
print(f"\n  ── Walk-Forward Summary ─────────────────────────────")
print(f"  Windows run:        {len(wf_df)}")
print(f"  Profitable:         {(wf_df['te_pnl']>0).sum()}/{len(wf_df)}")
print(f"  Avg test WR:        {wf_df['te_wr'].mean():.1f}%")
print(f"  Avg test PF:        {wf_df['te_pf'].mean():.2f}x")
print(f"  Avg test P&L/2mo:   ${wf_df['te_pnl'].mean():,.2f}")
print(f"  Avg test Ann:       ${wf_df['te_ann'].mean():,.2f}/yr")
print(f"  Worst window:       ${wf_df['te_pnl'].min():,.2f}")
print(f"  Best window:        ${wf_df['te_pnl'].max():,.2f}")
train_avg_per_test=wf_df['tr_pnl'].mean()/(126/42)
print(f"  WF Efficiency:      {wf_df['te_pnl'].mean()/train_avg_per_test*100:.0f}%  (test vs proportional train)")

print(f"\n  ── Verdict ──────────────────────────────────────────")
checks=[
    ("WR ≥ 55%",          wf_df['te_wr'].mean()>=55,     f"{wf_df['te_wr'].mean():.1f}%"),
    ("PF ≥ 1.5x",         wf_df['te_pf'].mean()>=1.5,    f"{wf_df['te_pf'].mean():.2f}x"),
    ("≥5/6 profitable",   (wf_df['te_pnl']>0).sum()>=5,  f"{(wf_df['te_pnl']>0).sum()}/{len(wf_df)}"),
    ("No window < -$3k",  wf_df['te_pnl'].min()>-3000,   f"${wf_df['te_pnl'].min():,.0f}"),
    ("Ann avg > $20k",    wf_df['te_ann'].mean()>20000,   f"${wf_df['te_ann'].mean():,.0f}/yr"),
]
for name,passed,val in checks:
    print(f"  {'✓' if passed else '✗'}  {name:<25} {val}")
all_pass=all(c[1] for c in checks)
print(f"\n  {'DEPLOY READY ✓' if all_pass else 'NOT READY — review failing checks'}")
