"""Quick V1 vs V2 summary only"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import pickle
import os
import numpy as np

SYMBOLS = [
    "NVDA","AMD","AVGO","QCOM","AMAT","MU","MRVL","LRCX","KLAC","ASML","TSM","ARM","INTC","ON",
    "MCHP","ADI","NXPI","TXN","MPWR","TER","SMCI","ANET","DELL","HPE","STM",
    "MSFT","GOOGL","META","AMZN","AAPL","TSLA","NFLX",
    "CRM","ADBE","INTU","NOW","SHOP","ORCL","IBM","CSCO",
    "PLTR","SNOW","DDOG","MDB","NET","CRWD","PANW","ZS","ESTC","S",
    "AI","PATH","DOCN","FSLY","AKAM",
    "PYPL","SQ","HOOD","COIN","ADP","FIS","FI","GPN","JKHY",
    "UBER","ABNB","DASH","RBLX","APP",
    "TTD","DUOL","CELH","CAVA","RKLB",
    "LLY","NVO","ABBV","JNJ","MRK","AMGN","GILD","REGN","VRTX","ISRG",
    "BIIB","BMY","PFE","MRNA","NBIX",
    "GE","CAT","ETN","PH","TT","DE","HON","EMR","ROP","URI"
]

def load_cached(s):
    f = f"boof_cache/{s}_2025-01-01_2026-12-31.pkl"
    return pickle.load(open(f,'rb')) if os.path.exists(f) else None

def build_ema50(qqq):
    d = qqq.between_time('16:00','16:00').copy()
    d['date'] = d.index.date
    return d.groupby('date')['close'].last().ewm(span=50,adjust=False).mean()

def get_ema(s, date):
    v = s.get(date)
    if v is None:
        prior = [d for d in s.index if d < date]
        v = s[prior[-1]] if prior else None
    return v

def collect(all_data, ema50, s1, e1, qqq_filter):
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index>=s1)&(qqq.index<=e1)]
    qqq['date'] = qqq.index.date
    trades = []
    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date']==d]
        qop = qday.between_time('09:30','09:34')
        if len(qop)==0: continue
        q5 = (qop.iloc[-1]['close']-qop.iloc[0]['open'])/qop.iloc[0]['open']*100
        qcb = qday.between_time('16:00','16:00')
        qc  = qcb.iloc[-1]['close'] if len(qcb)>0 else qday.iloc[-1]['close']
        e50 = get_ema(ema50, d)
        if e50 is None: continue
        bull = qc > e50
        bear = qc < e50
        for sym in SYMBOLS:
            if sym not in all_data: continue
            df = all_data[sym].copy()
            df = df[(df.index>=s1)&(df.index<=e1)]
            day = df[df.index.date==d]
            if len(day)==0: continue
            so = day.between_time('09:30','09:34')
            if len(so)==0: continue
            s5 = (so.iloc[-1]['close']-so.iloc[0]['open'])/so.iloc[0]['open']*100
            en = day.between_time('09:35','09:35')
            ex = day.between_time('10:15','10:15')
            if len(en)==0 or len(ex)==0: continue
            ep = en.iloc[0]['close']; xp = ex.iloc[0]['close']
            long_ok  = bull and (0.60<=s5<0.70)
            short_ok = bear and (-1.50<=s5<=-0.80)
            if qqq_filter:
                long_ok  = long_ok  and q5>=0.05
                short_ok = short_ok and q5<=-0.05
            if long_ok:
                trades.append({'side':'L','pnl':(xp-ep)/ep*100})
            elif short_ok:
                trades.append({'side':'S','pnl':(ep-xp)/ep*100})
    return trades

def summary(trades, label):
    if not trades:
        print(f"{label}: NO TRADES"); return
    df = pd.DataFrame(trades)
    l = df[df['side']=='L']; s = df[df['side']=='S']
    def row(d, name):
        if len(d)==0: return f"  {name:8} {'0':>6}  {'---':>6}  {'---':>9}  {'---':>9}  {'---':>5}"
        wr = len(d[d['pnl']>0])/len(d)*100
        avg= d['pnl'].mean(); tot=d['pnl'].sum()
        gp = d[d['pnl']>0]['pnl'].sum(); gl=abs(d[d['pnl']<=0]['pnl'].sum())
        pf = gp/gl if gl>0 else 0
        return f"  {name:8} {len(d):>6}  {wr:>5.1f}%  {avg:>+8.3f}%  {tot:>+8.2f}%  {pf:>5.2f}"
    ds = df.sort_values('pnl').copy(); ds['cum']=df.sort_values('pnl')['pnl'].cumsum()
    df2=df.copy(); df2['cum']=df2['pnl'].cumsum()
    dd=(df2['cum'].expanding().max()-df2['cum']).max()
    print(f"\n{'='*65}")
    print(f" {label}")
    print(f"{'='*65}")
    print(f"  {'':8} {'Trades':>6}  {'WR%':>6}  {'Avg P&L':>9}  {'Total':>9}  {'PF':>5}")
    print(f"  {'-'*60}")
    print(row(l,'LONG'))
    print(row(s,'SHORT'))
    print(f"  {'-'*60}")
    print(row(df,'COMBINED'))
    print(f"  Max Drawdown: -{dd:.2f}%")

all_data = {}
print("Loading...")
for sym in ['QQQ']+SYMBOLS:
    df = load_cached(sym)
    if df is not None: all_data[sym] = df
print(f"Loaded {len(all_data)} symbols")

ema50 = build_ema50(all_data['QQQ'].copy())

s25s = pd.to_datetime('2025-01-01').tz_localize('UTC')
s25e = pd.to_datetime('2025-12-31').tz_localize('UTC')
s26s = pd.to_datetime('2026-01-01').tz_localize('UTC')
s26e = pd.to_datetime('2026-06-09').tz_localize('UTC')

print("\n" + "="*65)
print(" VERSION 1 — EMA50 regime only (no QQQ 5m filter)")
print("="*65)
v1_25 = collect(all_data, ema50, s25s, s25e, False)
v1_26 = collect(all_data, ema50, s26s, s26e, False)
summary(v1_25,       "2025")
summary(v1_26,       "2026 YTD")
summary(v1_25+v1_26, "COMBINED")

print("\n" + "="*65)
print(" VERSION 2 — EMA50 + QQQ 5m >= +0.05% / <= -0.05%")
print("="*65)
v2_25 = collect(all_data, ema50, s25s, s25e, True)
v2_26 = collect(all_data, ema50, s26s, s26e, True)
summary(v2_25,       "2025")
summary(v2_26,       "2026 YTD")
summary(v2_25+v2_26, "COMBINED")
