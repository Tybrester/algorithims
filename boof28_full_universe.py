"""
BOOF 28 - Full Universe Test (75 symbols)
LONG:  QQQ>EMA50, QQQ_5m>=+0.10%, stock_5m 0.60-0.70%, entry 9:35, exit 10:15
SHORT: QQQ<EMA50, QQQ_5m<=-0.10%, stock_5m -0.80 to -1.50%, entry 9:35, exit 10:15
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import pickle
import os
import numpy as np

SECTORS = {
    "Semiconductors": ["NVDA","AMD","AVGO","QCOM","MU","AMAT","ASML","TSM","LRCX","KLAC","MRVL","ADI","NXPI","TXN","MCHP","ON","MPWR","ARM","INTC","TER"],
    "Mega-cap Tech":  ["MSFT","AAPL","AMZN","META","GOOGL","NFLX","TSLA"],
    "Fintech":        ["HOOD","COIN","SQ","FI","PYPL","SOFI","CAVA"],
    "Industrials":    ["CAT","ETN","PH","TT","URI","DE","GE","ROP","EMR"],
    "Biotech":        ["LLY","NVO","ISRG","MRNA","VRTX","REGN","AMGN","GILD","ABBV"],
    "Banks":          ["JPM","GS","MS","BAC","WFC","C","SCHW","BLK"],
    "Energy":         ["XOM","CVX","COP","SLB","EOG","MPC","VLO","PSX"],
    "Travel":         ["UBER","ABNB","DASH","RCL","CCL","BKNG","EXPE"],
}

SYM_TO_SECTOR = {s: sec for sec, syms in SECTORS.items() for s in syms}
ALL_SYMBOLS = list(SYM_TO_SECTOR.keys())

def load_cached(s):
    f = f"boof_cache/{s}_2025-01-01_2026-12-31.pkl"
    return pickle.load(open(f,'rb')) if os.path.exists(f) else None

def build_ema50(qqq):
    d = qqq.between_time('16:00','16:00').copy()
    d['date'] = d.index.date
    return d.groupby('date')['close'].last().ewm(span=50, adjust=False).mean()

def get_ema(s, date):
    v = s.get(date)
    if v is None:
        prior = [d for d in s.index if d < date]
        v = s[prior[-1]] if prior else None
    return v

def collect(all_data, ema50, start, end):
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    trades = []
    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date'] == d]
        qop  = qday.between_time('09:30','09:34')
        if len(qop) == 0: continue
        q5   = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open'] * 100
        qcb  = qday.between_time('16:00','16:00')
        qc   = qcb.iloc[-1]['close'] if len(qcb) > 0 else qday.iloc[-1]['close']
        e50  = get_ema(ema50, d)
        if e50 is None: continue
        bull = qc > e50
        bear = qc < e50
        for sym in ALL_SYMBOLS:
            if sym not in all_data: continue
            df  = all_data[sym].copy()
            df  = df[(df.index >= start) & (df.index <= end)]
            day = df[df.index.date == d]
            if len(day) == 0: continue
            so  = day.between_time('09:30','09:34')
            if len(so) == 0: continue
            s5  = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open'] * 100
            en  = day.between_time('09:35','09:35')
            ex  = day.between_time('10:15','10:15')
            if len(en) == 0 or len(ex) == 0: continue
            ep  = en.iloc[0]['close']
            xp  = ex.iloc[0]['close']
            sec = SYM_TO_SECTOR.get(sym, 'Other')
            if bull and q5 >= 0.10 and (0.60 <= s5 < 0.70):
                trades.append({'sym':sym,'sector':sec,'side':'LONG', 'pnl':(xp-ep)/ep*100,'date':d})
            elif bear and q5 <= -0.10 and (-1.50 <= s5 <= -0.80):
                trades.append({'sym':sym,'sector':sec,'side':'SHORT','pnl':(ep-xp)/ep*100,'date':d})
    return trades

def report(trades, label):
    if not trades:
        print(f"\n{label}: NO TRADES"); return
    df = pd.DataFrame(trades)
    l = df[df['side']=='LONG']; s = df[df['side']=='SHORT']

    def row(d, name):
        if len(d)==0: return
        wr  = len(d[d['pnl']>0])/len(d)*100
        avg = d['pnl'].mean(); tot = d['pnl'].sum()
        gp  = d[d['pnl']>0]['pnl'].sum(); gl = abs(d[d['pnl']<=0]['pnl'].sum())
        pf  = gp/gl if gl>0 else 0
        d2  = d.copy(); d2['cum'] = d2['pnl'].cumsum()
        dd  = (d2['cum'].expanding().max()-d2['cum']).max()
        print(f"  {name:8} {len(d):>7}  {wr:>5.1f}%  {avg:>+8.3f}%  {tot:>+8.2f}%  {pf:>5.2f}  -{dd:>6.2f}%")

    print(f"\n{'='*80}")
    print(f" {label}")
    print(f"{'='*80}")
    print(f"  {'':8} {'Trades':>7}  {'WR%':>6}  {'Avg P&L':>9}  {'Total':>9}  {'PF':>5}  {'MaxDD':>8}")
    print(f"  {'-'*70}")
    row(l, 'LONG'); row(s, 'SHORT'); row(df, 'COMBINED')

    # Sector breakdown
    print(f"\n  {'Sector':15} {'Trades':>7}  {'WR%':>6}  {'Avg':>9}  {'Total':>9}  {'PF':>5}  {'Best':>6}")
    print(f"  {'-'*70}")
    sector_order = ["Semiconductors","Mega-cap Tech","Fintech","Industrials","Biotech","Banks","Energy","Travel"]
    for sec in sector_order:
        sub = df[df['sector']==sec]
        if len(sub)==0: continue
        wins= sub[sub['pnl']>0]; loss=sub[sub['pnl']<=0]
        wr  = len(wins)/len(sub)*100
        avg = sub['pnl'].mean(); tot = sub['pnl'].sum()
        gp  = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
        pf  = gp/gl if gl>0 else 0
        best= sub.groupby('sym')['pnl'].sum().idxmax()
        print(f"  {sec:15} {len(sub):>7}  {wr:>5.1f}%  {avg:>+8.3f}%  {tot:>+8.2f}%  {pf:>5.2f}  {best:>6}")

    # Monthly
    print(f"\n  {'Month':10} {'L':>4} {'S':>4} {'Tot':>6}  {'WR%':>6}  {'Total':>9}  {'Cum':>9}")
    print(f"  {'-'*60}")
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    cum = 0
    for m in sorted(df['month'].unique()):
        mdf = df[df['month']==m]
        ml  = len(mdf[mdf['side']=='LONG'])
        ms  = len(mdf[mdf['side']=='SHORT'])
        mwr = len(mdf[mdf['pnl']>0])/len(mdf)*100
        mt  = mdf['pnl'].sum(); cum += mt
        print(f"  {str(m):10} {ml:>4} {ms:>4} {len(mdf):>6}  {mwr:>5.1f}%  {mt:>+8.2f}%  {cum:>+8.2f}%")

    # Top/Bottom symbols
    sym_tot = df.groupby('sym')['pnl'].sum().sort_values(ascending=False)
    print(f"\n  TOP 10:    {', '.join(f'{s}(+{v:.1f}%)' for s,v in sym_tot.head(10).items())}")
    print(f"  BOTTOM 10: {', '.join(f'{s}({v:+.1f}%)' for s,v in sym_tot.tail(10).items())}")

    # P&L distribution
    n = len(df)
    thresholds = [0.5, 1.0, 1.5, 2.0]
    print(f"\n  {'─'*60}")
    print(f"  P&L OUTCOME DISTRIBUTION  (n={n})")
    print(f"  {'─'*60}")
    print(f"  {'Threshold':12} {'Winners':>10} {'%':>6}   {'Losers':>10} {'%':>6}")
    print(f"  {'─'*60}")
    for thr in thresholds:
        w = len(df[df['pnl'] >  thr])
        l = len(df[df['pnl'] < -thr])
        print(f"  > {thr:.1f}%      {w:>10}  {w/n*100:>5.1f}%   {l:>10}  {l/n*100:>5.1f}%")
    print(f"  {'─'*60}")
    # Buckets
    buckets = [(-99,-2.0),(-2.0,-1.5),(-1.5,-1.0),(-1.0,-0.5),(-0.5,0.0),(0.0,0.5),(0.5,1.0),(1.0,1.5),(1.5,2.0),(2.0,99)]
    labels  = ['< -2.0%','-2.0/-1.5','-1.5/-1.0','-1.0/-0.5','-0.5/0.0','0.0/+0.5','+0.5/+1.0','+1.0/+1.5','+1.5/+2.0','> +2.0%']
    print(f"\n  {'Bucket':12} {'Count':>7} {'%':>6}  {'Bar'}")
    print(f"  {'─'*60}")
    max_c = 0
    bucket_counts = []
    for (lo,hi), lbl in zip(buckets, labels):
        c = len(df[(df['pnl']>lo)&(df['pnl']<=hi)])
        bucket_counts.append((lbl, c))
        max_c = max(max_c, c)
    for lbl, c in bucket_counts:
        bar = '█' * int(c / max_c * 30) if max_c > 0 else ''
        print(f"  {lbl:12} {c:>7} {c/n*100:>5.1f}%  {bar}")

# ── Main ─────────────────────────────────────────────────────────────
print("Loading data...")
all_data = {}
for sym in ['QQQ'] + ALL_SYMBOLS:
    df = load_cached(sym)
    if df is not None:
        all_data[sym] = df
    else:
        print(f"  WARNING: {sym} not cached")
print(f"Loaded {len(all_data)} symbols ({len(all_data)-1} stocks + QQQ)\n")

ema50 = build_ema50(all_data['QQQ'].copy())

s25s = pd.to_datetime('2025-01-01').tz_localize('UTC')
s25e = pd.to_datetime('2025-12-31').tz_localize('UTC')
s26s = pd.to_datetime('2026-01-01').tz_localize('UTC')
s26e = pd.to_datetime('2026-06-09').tz_localize('UTC')

print("Running 2025..."); t25 = collect(all_data, ema50, s25s, s25e)
print("Running 2026..."); t26 = collect(all_data, ema50, s26s, s26e)

report(t25,       "2025 FULL YEAR")
report(t26,       "2026 YTD (Jan-Jun 9)")
report(t25+t26,   "COMBINED (2025 + 2026 YTD)")
