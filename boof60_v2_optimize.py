"""
BOOF60 v2 TP/SL Optimization — replay raw trade paths from boof60_v2_trades.csv
with the bar-by-bar paths stored in boof60_v2_paths.pkl
"""
import pandas as pd
import numpy as np
import pytz
import os
import pickle
from itertools import product

ET     = pytz.timezone('America/New_York')
CACHE  = "boof_data"
SUFFIX = "_5m_6mo.parquet"

SYMBOLS_LONG = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX'
]
ROUTING = {
    "UPST":("PMH",None,None),"APP":("PMH",None,None),"SMCI":("PMH",None,None),
    "HIMS":("PMH",None,None),"GOOGL":("PMH",None,None),"META":("PDH",None,None),
    "AFRM":("PDH",None,None),"TSLA":("PIV",10,2),"CLSK":("PIV",10,2),
    "HOOD":("PIV",10,2),"ADBE":("PIV",30,3),"PANW":("PIV",30,3),
    "MU":("PIV",30,3),"AMD":("PIV",30,3),"COIN":("PIV",30,3),"NVDA":("PIV",30,3),
    "MRVL":("PIV",120,4),"AVGO":("PIV",120,4),"PLTR":("PIV",240,5),"CRM":("PIV",390,5),
}
SHORT_SYMS = list(ROUTING.keys())
ALL_SYMS   = list(set(SYMBOLS_LONG + SHORT_SYMS))

GAP_LONG=1.0; GAP_SHORT=0.5; PDH_BREAK=0.0
NEAR_PCT=0.0015; BOUNCE=0.0015; OVERLAP=0.002
MAX_BARS=60; BUDGET=750.0; MAX_POS=5; OPTION_MULT=2.0

PKL = "boof60_v2_paths.pkl"

def load_sym(sym):
    path = os.path.join(CACHE, f"{sym}{SUFFIX}")
    if not os.path.exists(path): return pd.DataFrame()
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None: df.index = df.index.tz_localize('UTC')
    df.index = df.index.tz_convert(ET)
    return df

def build_pivots(bars, lookback, wing):
    hist = bars[-lookback:] if len(bars) >= lookback else bars
    if len(hist) < wing+1: return []
    H = [b['h'] for b in hist]
    raw = [H[i] for i in range(wing,len(hist)) if H[i]==max(H[max(0,i-wing):i+1])]
    if not raw: return []
    raw=sorted(raw); cl=[raw[0]]
    for lv in raw[1:]:
        if abs(lv-cl[-1])/cl[-1]<OVERLAP: cl[-1]=(cl[-1]+lv)/2
        else: cl.append(lv)
    return cl

def init_sm(): return {'state':'IDLE','extreme':None,'touch_num':0,'was_below':False,'broken':False}

def update_level_sm(sm, level, bar):
    high=bar['h']; close=bar['c']
    if close<level: sm['was_below']=True
    touching=sm['was_below'] and high>=level*(1-NEAR_PCT)
    if sm['state']=='IDLE':
        if touching: sm['state']='IN'; sm['extreme']=close; sm['touch_num']+=1
    elif sm['state']=='IN':
        if high>=level*(1-NEAR_PCT): sm['extreme']=min(sm['extreme'],close)
        else:
            bounced=sm['extreme'] is not None and (level-sm['extreme'])/level>=BOUNCE
            req=2 if sm['broken'] else 1
            if bounced and sm['touch_num']==req: sm['state']='FIRED'; return True
            sm['state']='DEAD'; sm['broken']=True; sm['was_below']=False
    elif sm['state']=='DEAD':
        if sm['was_below']: sm['state']='IDLE'; sm['extreme']=None; sm['touch_num']=0
    return False

# ── Collect raw paths (or load from cache) ───────────────────────
if os.path.exists(PKL):
    print(f"Loading cached paths from {PKL}...")
    with open(PKL,'rb') as f: raw_trades = pickle.load(f)
    print(f"  {len(raw_trades)} trade paths loaded")
else:
    print("Building raw trade paths (first run — will cache)...")
    data = {sym: load_sym(sym) for sym in ALL_SYMS+['SPY']}
    daily= {}
    for sym in ALL_SYMS+['SPY']:
        df=data[sym]
        if df.empty: daily[sym]=pd.DataFrame(); continue
        rth=df.between_time('09:30','16:00')
        d=rth.resample('1D').agg(open=('open','first'),high=('high','max'),
                                  low=('low','min'),close=('close','last')).dropna()
        daily[sym]=d
    all_dates=sorted(daily['SPY'].index.date)[1:]
    print(f"  {len(all_dates)} days, {len(ALL_SYMS)} symbols")

    raw_trades=[]
    for day in all_dates:
        spy_prices=[]; regime="neutral"
        spy_df=data['SPY']
        spy_rth=spy_df[spy_df.index.date==day].between_time('09:30','15:55') if not spy_df.empty else pd.DataFrame()
        sym_state={}
        for sym in ALL_SYMS:
            dh=daily.get(sym,pd.DataFrame()); prev=dh[dh.index.date<day]
            if len(prev)<1: continue
            prev_close=float(prev['close'].iloc[-1]); pdh=float(prev['high'].iloc[-1])
            bars_5m=data.get(sym,pd.DataFrame())
            if bars_5m.empty: continue
            rth=bars_5m[bars_5m.index.date==day].between_time('09:30','15:55')
            if len(rth)<2: continue
            day_open=float(rth['open'].iloc[0])
            gap_pct=(day_open-prev_close)/prev_close*100
            gap_long=gap_pct>GAP_LONG; gap_short=gap_pct>GAP_SHORT
            levels=[]; lvl_sms={}
            rtype,lb,wing=ROUTING.get(sym,(None,None,None))
            if rtype and gap_short:
                prev_bars_df=bars_5m[bars_5m.index.date<day].between_time('09:30','16:00').tail(500)
                prev_bars=[{'h':float(r['high']),'l':float(r['low']),'c':float(r['close'])} for _,r in prev_bars_df.iterrows()]
                if rtype=='PMH':
                    pm=bars_5m[bars_5m.index.date==day].between_time('04:00','09:29')
                    if not pm.empty: levels=[float(pm['high'].max())]
                elif rtype=='PDH': levels=[pdh]
                elif rtype=='PIV' and lb and wing: levels=build_pivots(prev_bars,lb,wing)
                for lv in levels: lvl_sms[round(lv,4)]=init_sm()
            sym_state[sym]={'rth':rth,'prev_close':prev_close,'pdh':pdh,'gap_pct':gap_pct,
                            'gap_long':gap_long,'gap_short':gap_short,'levels':levels,'lvl_sms':lvl_sms,
                            'confirm_long':False,'pdh_broken':False,'short_fired':False,
                            'in_trade':None,'bar_path':[]}

        max_len=max((len(ss['rth']) for ss in sym_state.values()),default=0)
        active_pos={}
        for i in range(max_len):
            if i<len(spy_rth):
                spy_prices.append(float(spy_rth.iloc[min(i,len(spy_rth)-1)]['close']))
                if len(spy_prices)>5: spy_prices.pop(0)
                if len(spy_prices)>=3:
                    if   spy_prices[-1]>spy_prices[0]*1.001: regime="bull"
                    elif spy_prices[-1]<spy_prices[0]*0.999: regime="bear"
                    else: regime="neutral"
            for sym,ss in sym_state.items():
                rth=ss['rth']
                if i>=len(rth): continue
                ts=rth.index[i]; bar=rth.iloc[i]; hm=ts.strftime('%H:%M')
                price=float(bar['close']); o_px=float(bar['open'])
                high=float(bar['high']); low=float(bar['low'])
                bdict={'h':high,'l':low,'c':price,'o':o_px}
                if ss['in_trade']:
                    t=ss['in_trade']; entry_px=t['entry_price']; direction=t['direction']
                    if direction=='long':
                        stk_pct=(price-entry_px)/entry_px*100
                        mfe_stk=(high-entry_px)/entry_px*100; mae_stk=(low-entry_px)/entry_px*100
                    else:
                        stk_pct=(entry_px-price)/entry_px*100
                        mfe_stk=(entry_px-low)/entry_px*100; mae_stk=(entry_px-high)/entry_px*100
                    opt_pct=stk_pct*OPTION_MULT; mfe_opt=mfe_stk*OPTION_MULT; mae_opt=mae_stk*OPTION_MULT
                    t['bars_held']+=1
                    ss['bar_path'].append({'opt_pct':opt_pct,'mfe_opt':mfe_opt,'mae_opt':mae_opt,'hm':hm})
                    if t['bars_held']>=MAX_BARS or hm>='15:50':
                        raw_trades.append({'date':day,'sym':sym,'direction':direction,
                            'entry_time':t['entry_time'],'regime':t['regime'],
                            'gap_pct':gap_pct,'signal':t['signal'],'bars':ss['bar_path']})
                        ss['in_trade']=None; ss['bar_path']=[]
                        if sym in active_pos: del active_pos[sym]
                    continue
                if hm>='15:30' or len(active_pos)>=MAX_POS or ss['in_trade']: continue
                pdh=ss['pdh']
                if ss['gap_long'] and price>pdh and not ss['pdh_broken']:
                    if not ss['confirm_long']: ss['confirm_long']=True; continue
                    if regime in ('bull','neutral'):
                        ss['pdh_broken']=True
                        ss['in_trade']={'direction':'long','entry_price':price,'entry_time':hm,
                                        'bars_held':0,'regime':regime,'signal':'BOOF55'}
                        active_pos[sym]=True
                if ss['gap_short'] and not ss['short_fired'] and not ss['pdh_broken']:
                    for lv,sm in ss['lvl_sms'].items():
                        if sm['state']=='FIRED': continue
                        if update_level_sm(sm,lv,bdict):
                            if regime in ('bear','neutral'):
                                ss['short_fired']=True
                                ss['in_trade']={'direction':'short','entry_price':price,'entry_time':hm,
                                                'bars_held':0,'regime':regime,'signal':'BOOF51'}
                                active_pos[sym]=True; break
        for sym,ss in sym_state.items():
            if ss['in_trade'] and ss['bar_path']:
                raw_trades.append({'date':day,'sym':sym,'direction':ss['in_trade']['direction'],
                    'entry_time':ss['in_trade']['entry_time'],'regime':ss['in_trade']['regime'],
                    'gap_pct':ss['gap_pct'],'signal':ss['in_trade']['signal'],'bars':ss['bar_path']})

    with open(PKL,'wb') as f: pickle.dump(raw_trades,f)
    print(f"  {len(raw_trades)} paths collected and cached to {PKL}")

# ── Sweep TP/SL ───────────────────────────────────────────────────
TP_VALUES = [5, 8, 10, 12, 15, 20, 25, 35]
SL_VALUES = [-5, -8, -10, -12, -15, -20, -25, -35]

def sim(tp, sl):
    results=[]
    for t in raw_trades:
        pnl=None; exit_type='TIMEOUT'
        for b in t['bars']:
            if b['mfe_opt']>=tp:   pnl=BUDGET*tp/100;  exit_type='TP'; break
            if b['mae_opt']<=sl:   pnl=BUDGET*sl/100;  exit_type='SL'; break
        if pnl is None:
            last=t['bars'][-1]; pnl=BUDGET*last['opt_pct']/100; exit_type='TIMEOUT'
        results.append({'pnl':pnl,'exit':exit_type,'signal':t['signal'],'regime':t['regime']})
    df=pd.DataFrame(results)
    wins=df[df['pnl']>0]; losses=df[df['pnl']<=0]
    wr  = len(wins)/len(df) if len(df) else 0
    pf  = wins['pnl'].sum()/abs(losses['pnl'].sum()) if losses['pnl'].sum()!=0 else 999
    ev  = df['pnl'].mean(); tot=df['pnl'].sum()
    tp_n= len(df[df['exit']=='TP']); sl_n=len(df[df['exit']=='SL'])
    b55_pnl = df[df['signal']=='BOOF55']['pnl'].sum()
    b51_pnl = df[df['signal']=='BOOF51']['pnl'].sum()
    return {'tp':tp,'sl':sl,'wr':round(wr*100,1),'pf':round(pf,2),'ev':round(ev,2),
            'total':round(tot,2),'tp_hits':tp_n,'sl_hits':sl_n,
            'b55':round(b55_pnl,2),'b51':round(b51_pnl,2),'n':len(df)}

print(f"\nSweeping {len(TP_VALUES)*len(SL_VALUES)} TP/SL combos on {len(raw_trades)} trades...")
rows=[]
for tp,sl in product(TP_VALUES,SL_VALUES):
    rows.append(sim(tp,sl))

res=pd.DataFrame(rows).sort_values('total',ascending=False)

print(f"\n{'='*75}")
print("TOP 20 BY TOTAL P&L")
print(f"{'='*75}")
print(res.head(20)[['tp','sl','wr','pf','ev','total','tp_hits','sl_hits','b55','b51']].to_string(index=False))

print(f"\n{'='*75}")
print("TOP 10 BY PROFIT FACTOR")
print(f"{'='*75}")
print(res.sort_values('pf',ascending=False).head(10)[['tp','sl','wr','pf','ev','total','tp_hits','sl_hits']].to_string(index=False))

print(f"\n{'='*75}")
print("BEST BALANCED — PF>1.3 AND WR>52%")
print(f"{'='*75}")
bal=res[(res['pf']>1.3)&(res['wr']>52)]
if bal.empty:
    print("None at those thresholds — showing PF>1.2 AND WR>50%:")
    bal=res[(res['pf']>1.2)&(res['wr']>50)]
print(bal[['tp','sl','wr','pf','ev','total','tp_hits','sl_hits','b55','b51']].to_string(index=False))

# Full heatmap pivot
print(f"\n{'='*75}")
print("TOTAL P&L HEATMAP (rows=TP, cols=SL)")
print(f"{'='*75}")
pivot=res.pivot(index='tp',columns='sl',values='total').round(0)
print(pivot.to_string())

res.to_csv('boof60_v2_sweep.csv',index=False)
print(f"\nFull sweep → boof60_v2_sweep.csv")
