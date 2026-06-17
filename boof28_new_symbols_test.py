"""
BOOF 28 - Test new symbols across expanded sectors
Long only + Short only tests, sorted by total P&L
"""
import sys, pickle, os, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
OUT = open('boof28_new_symbols_results.txt', 'w', encoding='utf-8')
_orig_print = print
def print(*a, **k):
    _orig_print(*a, **k)
    _orig_print(*a, **k, file=OUT)

SECTORS = {
    "Semiconductors": [
        "NVDA","AMD","AVGO","MU","MCHP","ASML","TSM","AMAT","MRVL","INTC","ON","NXPI","TXN","ARM",
        "ENTG","LSCC","ALAB","FORM","AEHR","ACLS","SMTC","CRUS","SYNA","AMKR",
    ],
    "Biotech": [
        "ISRG","MRNA","VRTX","REGN","LLY","GILD","BMY","ABBV","NVO","AMGN",
        "DXCM","PODD","EW","ALGN","RMD","TECH","HOLX","INCY",
    ],
    "Fintech": [
        "HOOD","COIN","SQ","SOFI","AFRM","UPST","PYPL",
        "NU","XYZ","TOST","PAYO","BILL",
    ],
    "Industrials": [
        "CAT","ETN","DE","GE","URI","ROP","HON","EMR",
        "TT","AME","ROK","GWW","ODFL","UNP",
    ],
    "Travel": [
        "UBER","ABNB","RCL","CCL",
        "BKNG","EXPE","MAR","HLT",
    ],
}
SYM_TO_SECTOR = {s: sec for sec, syms in SECTORS.items() for s in syms}
ALL_SYMBOLS   = list(SYM_TO_SECTOR.keys())

def load(s):
    f = f"boof_cache/{s}_2025-01-01_2026-12-31.pkl"
    return pickle.load(open(f,'rb')) if os.path.exists(f) else None

def build_ema50(qqq):
    d = qqq.between_time('16:00','16:00').copy()
    d['date'] = d.index.date
    daily = d.groupby('date')['close'].last()
    return daily.ewm(span=50, adjust=False).mean().shift(1)

def get_ema(s, date):
    ts = pd.Timestamp(date)
    v = s.get(ts)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        prior = [d for d in s.index if pd.Timestamp(d).date() < date]
        v = s[prior[-1]] if prior else None
    return v

def collect(all_data, ema50, start, end):
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    trades = []
    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date']==d]
        qop = qday.between_time('09:30','09:34')
        if len(qop)==0: continue
        q5 = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open']
        qob = qday.between_time('09:30','09:30')
        if len(qob)==0: continue
        qqq_open = qob.iloc[0]['open']
        e50 = get_ema(ema50, d)
        if e50 is None: continue
        bull = qqq_open > e50 and q5 >= 0.001
        bear = qqq_open < e50 and q5 <= -0.001
        if not bull and not bear: continue
        for sym in ALL_SYMBOLS:
            if sym not in all_data: continue
            df2 = all_data[sym].copy()
            df2 = df2[(df2.index >= start) & (df2.index <= end)]
            day = df2[df2.index.date == d]
            if len(day)==0: continue
            so = day.between_time('09:30','09:34')
            if len(so)==0: continue
            s5 = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open']
            en = day.between_time('09:35','09:35')
            ex = day.between_time('10:20','10:20')
            if len(en)==0 or len(ex)==0: continue
            ep = en.iloc[0]['open']; xp = ex.iloc[0]['open']
            sec = SYM_TO_SECTOR.get(sym,'Other')
            direction = None
            if bull and 0.006 <= s5 <= 0.007:
                direction = 'LONG'
            elif bear and -0.015 <= s5 <= -0.008:
                direction = 'SHORT'
            if direction is None: continue
            pnl = (xp-ep)/ep*100 if direction=='LONG' else (ep-xp)/ep*100
            trades.append({'date':d,'symbol':sym,'sector':sec,'side':direction,'pnl':pnl})
    return trades

def sym_report(trades, label):
    W = 80
    if not trades:
        print(f"\n{label}: NO TRADES"); return
    df = pd.DataFrame(trades)
    wins = df[df['pnl']>0]; loss = df[df['pnl']<=0]
    wr = len(wins)/len(df)*100
    pf = wins['pnl'].sum()/abs(loss['pnl'].sum()) if len(loss)>0 and loss['pnl'].sum()!=0 else 0
    tot = df['pnl'].sum()
    print(f"\n{'='*W}")
    print(f"  {label}  |  {len(df)} trades  WR {wr:.1f}%  PF {pf:.2f}  Total {tot:+.2f}%")
    print(f"{'='*W}")

    # By sector
    print(f"\n  {'Sector':18} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Avg':>9} {'Total':>9}")
    print(f"  {'-'*W}")
    for sec in SECTORS:
        sub = df[df['sector']==sec]
        if len(sub)==0: continue
        w = sub[sub['pnl']>0]; l = sub[sub['pnl']<=0]
        _wr = len(w)/len(sub)*100
        _pf = w['pnl'].sum()/abs(l['pnl'].sum()) if len(l)>0 and l['pnl'].sum()!=0 else 0
        print(f"  {sec:18} {len(sub):>7} {_wr:>5.1f}% {_pf:>6.2f} {sub['pnl'].mean():>+8.3f}% {sub['pnl'].sum():>+8.2f}%")

    # By symbol
    print(f"\n  {'Symbol':>8} {'Sector':18} {'Trades':>6} {'WR%':>6} {'PF':>6} {'Avg':>9} {'Total':>9}")
    print(f"  {'-'*W}")
    sym_stats = []
    for sym, grp in df.groupby('symbol'):
        w = grp[grp['pnl']>0]; l = grp[grp['pnl']<=0]
        _wr = len(w)/len(grp)*100
        _pf = w['pnl'].sum()/abs(l['pnl'].sum()) if len(l)>0 and l['pnl'].sum()!=0 else 0
        sym_stats.append({'sym':sym,'sec':SYM_TO_SECTOR.get(sym,'?'),
                          'n':len(grp),'wr':_wr,'pf':_pf,
                          'avg':grp['pnl'].mean(),'total':grp['pnl'].sum()})
    for _, r in pd.DataFrame(sym_stats).sort_values('total',ascending=False).iterrows():
        flag = '  ***NEW***' if r['sym'] in NEW_SYMS else ''
        cut  = '  <-- CUT'  if r['total'] < -0.5 else ''
        print(f"  {r['sym']:>8} {r['sec']:18} {r['n']:>6} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['avg']:>+8.3f}% {r['total']:>+8.2f}%{flag}{cut}")
    print(f"{'='*W}")

NEW_SYMS = {
    "ENTG","LSCC","ALAB","FORM","AEHR","ACLS","SMTC","CRUS","SYNA","AMKR",
    "DXCM","PODD","EW","ALGN","RMD","TECH","HOLX","INCY",
    "NU","XYZ","TOST","PAYO","BILL",
    "TT","AME","ROK","GWW","ODFL","UNP",
    "BKNG","EXPE","MAR","HLT",
}

print("Loading...")
all_data = {}
for sym in ['QQQ'] + ALL_SYMBOLS:
    df = load(sym)
    if df is not None: all_data[sym] = df
print(f"Loaded {len(all_data)} symbols\n")

ema50 = build_ema50(all_data['QQQ'].copy())
S25 = pd.to_datetime('2025-01-01').tz_localize('UTC')
E25 = pd.to_datetime('2025-12-31').tz_localize('UTC')
S26 = pd.to_datetime('2026-01-01').tz_localize('UTC')
E26 = pd.to_datetime('2026-06-09').tz_localize('UTC')

print("Running combined (2025+2026)...")
t_all = collect(all_data, ema50, S25, E26)
t_long  = [t for t in t_all if t['side']=='LONG']
t_short = [t for t in t_all if t['side']=='SHORT']

sym_report(t_long,  "LONG ONLY  -- ALL SYMBOLS")
sym_report(t_short, "SHORT ONLY -- ALL SYMBOLS")
sym_report(t_all,   "COMBINED   -- ALL SYMBOLS")
