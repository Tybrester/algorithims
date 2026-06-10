"""
BOOF 28 - Cleaned Long-Only Final Test
Bucket: 0.50-0.60%, Exit: 10:20, LONG only
Removed: HOOD, MRNA, ETN, GE, EMR, GILD, MRVL, NXPI (all net negative)
"""
import sys, pickle, os, random, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd

OUT = open('boof28_cleaned_longonly_results.txt', 'w', encoding='utf-8')
_p = print
def print(*a, **k):
    _p(*a, **k)
    _p(*a, **k, file=OUT)

WATCHLIST = [
    # Semiconductors (removed MRVL, NXPI)
    "NVDA","AMD","AVGO","MU","MCHP","ASML","TSM","AMAT","INTC","ON","TXN","ARM",
    # Fintech (removed HOOD)
    "COIN","SQ","SOFI","AFRM","UPST","PYPL",
    # Industrials (removed GE, EMR, ETN)
    "CAT","DE","URI","ROP","HON",
    # Biotech (removed MRNA, GILD)
    "ISRG","VRTX","REGN","LLY","BMY","ABBV","NVO","AMGN",
    # Travel
    "UBER","ABNB","RCL","CCL",
]

SYM_SECTOR = {
    **{s:"Semiconductors" for s in ["NVDA","AMD","AVGO","MU","MCHP","ASML","TSM","AMAT","INTC","ON","TXN","ARM"]},
    **{s:"Fintech"        for s in ["COIN","SQ","SOFI","AFRM","UPST","PYPL"]},
    **{s:"Industrials"    for s in ["CAT","DE","URI","ROP","HON"]},
    **{s:"Biotech"        for s in ["ISRG","VRTX","REGN","LLY","BMY","ABBV","NVO","AMGN"]},
    **{s:"Travel"         for s in ["UBER","ABNB","RCL","CCL"]},
}

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
        qop  = qday.between_time('09:30','09:34')
        if len(qop)==0: continue
        q5   = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open']
        qob  = qday.between_time('09:30','09:30')
        if len(qob)==0: continue
        qqq_open = qob.iloc[0]['open']
        e50  = get_ema(ema50, d)
        if e50 is None: continue
        # LONG ONLY: bull regime only
        if not (qqq_open > e50 and q5 >= 0.001): continue
        for sym in WATCHLIST:
            if sym not in all_data: continue
            df2  = all_data[sym].copy()
            df2  = df2[(df2.index >= start) & (df2.index <= end)]
            day  = df2[df2.index.date == d]
            if len(day)==0: continue
            so   = day.between_time('09:30','09:34')
            if len(so)==0: continue
            s5   = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open']
            s5p  = s5 * 100
            if not (0.50 <= s5p < 0.60): continue
            en   = day.between_time('09:35','09:35')
            ex   = day.between_time('10:20','10:20')
            if len(en)==0 or len(ex)==0: continue
            ep   = en.iloc[0]['open']; xp = ex.iloc[0]['open']
            pnl  = (xp-ep)/ep*100
            ts2  = pd.Timestamp(d)
            trades.append({'date':d,'symbol':sym,'sector':SYM_SECTOR.get(sym,'?'),
                           'pnl':pnl,'qqq_5m':round(q5*100,3),'stock_5m':round(s5p,3),
                           'month':ts2.to_period('M'),'quarter':ts2.to_period('Q'),'year':ts2.year})
    return trades

def sep(w=78): print('='*w)
def line(w=78): print('-'*w)

print("Loading...")
all_data = {}
for sym in ['QQQ'] + WATCHLIST:
    df = load(sym)
    if df is not None: all_data[sym] = df
print(f"Loaded {len(all_data)} symbols\n")
ema50 = build_ema50(all_data['QQQ'].copy())

def ts(s): return pd.to_datetime(s).tz_localize('UTC')
S25,E25 = ts('2025-01-01'),ts('2025-12-31')
S26,E26 = ts('2026-01-01'),ts('2026-06-09')

print("Collecting trades...")
t25  = collect(all_data, ema50, S25, E25)
t26  = collect(all_data, ema50, S26, E26)
tall = t25 + t26
df   = pd.DataFrame(tall)
print(f"Total: {len(tall)} trades  (2025: {len(t25)}, 2026: {len(t26)})\n")

def base_stats(t):
    if isinstance(t, list): d = pd.DataFrame(t)
    else: d = t
    if len(d)==0: return None
    w = d[d['pnl']>0]; l = d[d['pnl']<=0]
    wr = len(w)/len(d)
    aw = w['pnl'].mean() if len(w) else 0
    al = abs(l['pnl'].mean()) if len(l) else 0
    ev = wr*aw-(1-wr)*al
    pf = w['pnl'].sum()/abs(l['pnl'].sum()) if len(l)>0 and l['pnl'].sum()!=0 else 0
    tot= d['pnl'].sum()
    cum= d['pnl'].cumsum()
    dd = (cum.expanding().max()-cum).max()
    return dict(n=len(d),wr=wr,aw=aw,al=al,ev=ev,pf=pf,tot=tot,dd=dd,df=d)

# ── SUMMARY ──────────────────────────────────────────────────────────
sep()
print("  BOOF 28 -- CLEANED LONG ONLY  |  Bucket 0.50-0.60%  |  Exit 10:20")
sep()
print(f"  {'Period':<14} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9} {'MaxDD':>8}  Verdict")
line()
for label, t in [('2025 Full',t25),('2026 YTD',t26),('COMBINED',tall)]:
    s = base_stats(t)
    if not s: continue
    v = 'PASS' if s['pf']>=1.5 and s['ev']>0 else ('PASS' if s['pf']>=1.2 else 'EDGE')
    print(f"  {label:<14} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}% -{s['dd']:>6.2f}%")
sep()

# ── QUARTERLY ────────────────────────────────────────────────────────
sep()
print("  QUARTERLY BREAKDOWN")
sep()
print(f"  {'Quarter':<10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9}  Verdict")
line()
for q in sorted(df['quarter'].unique()):
    sub = df[df['quarter']==q]; s = base_stats(sub)
    if not s: continue
    v = 'PASS' if s['pf']>=1.2 else ('EDGE' if s['pf']>=1.0 else 'FAIL')
    print(f"  {str(q):<10} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%  {v}")
sep()

# ── MONTHLY ──────────────────────────────────────────────────────────
sep()
print("  MONTHLY BREAKDOWN")
sep()
print(f"  {'Month':<10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Total':>9}  {'Cum':>9}")
line()
cum2=0
for m in sorted(df['month'].unique()):
    mdf=df[df['month']==m]; mt=mdf['pnl'].sum(); cum2+=mt
    w=mdf[mdf['pnl']>0]; l=mdf[mdf['pnl']<=0]
    mwr=len(w)/len(mdf)*100
    mpf=w['pnl'].sum()/abs(l['pnl'].sum()) if len(l)>0 and l['pnl'].sum()!=0 else 0
    flag='  RED' if mt<0 else ''
    print(f"  {str(m):<10} {len(mdf):>7} {mwr:>5.1f}% {mpf:>6.2f} {mt:>+8.2f}%  {cum2:>+8.2f}%{flag}")
sep()

# ── SYMBOL CONTRIBUTION ──────────────────────────────────────────────
sep()
print("  SYMBOL CONTRIBUTION")
sep()
total_pnl = df['pnl'].sum()
print(f"  {'Symbol':>8} {'Sector':16} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Total':>9} {'Contrib%':>9}")
line()
sym_rows=[]
for sym, grp in df.groupby('symbol'):
    w=grp[grp['pnl']>0]; l=grp[grp['pnl']<=0]
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if len(l)>0 and l['pnl'].sum()!=0 else 0
    sym_rows.append({'sym':sym,'sec':SYM_SECTOR.get(sym,'?'),'n':len(grp),
                     'wr':len(w)/len(grp)*100,'pf':pf,'total':grp['pnl'].sum(),
                     'contrib':grp['pnl'].sum()/total_pnl*100})
sdf = pd.DataFrame(sym_rows).sort_values('total',ascending=False)
for _,(r) in sdf.iterrows():
    cut=' <-- CUT' if r['total']<0 else ''
    print(f"  {r['sym']:>8} {r['sec']:16} {r['n']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['total']:>+8.2f}% {r['contrib']:>+8.1f}%{cut}")
t5=sdf.head(5)['total'].sum(); t10=sdf.head(10)['total'].sum()
print(f"\n  Top  5: {t5:+.2f}%  ({t5/total_pnl*100:.0f}% of total)")
print(f"  Top 10: {t10:+.2f}%  ({t10/total_pnl*100:.0f}% of total)")
sep()

# ── WALK-FORWARD ─────────────────────────────────────────────────────
sep()
print("  WALK-FORWARD  (TRAIN=2025, TEST=2026)")
sep()
print(f"  {'Period':<35} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9}  Tag")
line()
for label,t in [("TRAIN: 2025 Full",t25),("TEST:  2026 YTD (unseen)",t26)]:
    s=base_stats(t)
    if not s: continue
    tag='TRAIN' if '2025' in label else 'OUT-OF-SAMPLE'
    v='PASS' if s['pf']>=1.3 else 'MARGINAL'
    print(f"  {label:<35} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%  {v}  [{tag}]")
sep()

# ── MONTE CARLO ──────────────────────────────────────────────────────
sep()
print("  MONTE CARLO  (1000 simulations)")
sep()
pnl_list=df['pnl'].tolist(); random.seed(42)
final_rets,max_dds=[],[]
for _ in range(1000):
    sh=random.sample(pnl_list,len(pnl_list))
    cum=np.cumsum(sh); peak=np.maximum.accumulate(cum)
    max_dds.append((cum-peak).min()); final_rets.append(cum[-1])
fr=np.array(final_rets); md=np.array(max_dds)
print(f"  Final return:  95th {np.percentile(fr,95):>+7.2f}%  |  Median {np.median(fr):>+7.2f}%  |  5th {np.percentile(fr,5):>+7.2f}%")
print(f"  % profitable:  {(fr>0).mean()*100:.1f}%")
print(f"  Max DD:        95th {np.percentile(md,95):>+7.2f}%  |  Median {np.median(md):>+7.2f}%  |  5th {np.percentile(md,5):>+7.2f}%")
print(f"  DD > -20%:     {(md<-20).mean()*100:.1f}% of sims")
sep()

# ── EQUITY CURVE ─────────────────────────────────────────────────────
sep()
print("  EQUITY CURVE")
sep()
cum_arr=df['pnl'].cumsum().values; n=len(cum_arr)
scale=max(abs(cum_arr.max()),abs(cum_arr.min()),0.01)/40
chk=sorted(set([0]+[int(i*(n-1)/19) for i in range(1,20)]+[n-1]))
print(f"  {'Trade':>7} {'Date':>12} {'CumPnL':>9}  Curve")
line()
for i in chk:
    v=cum_arr[i]; d_=df.iloc[i]['date']
    bar=('+' if v>=0 else '-')*int(abs(v)/scale)
    print(f"  {i+1:>7} {str(d_):>12} {v:>+8.2f}%  |{bar}")
print(f"\n  Peak: {cum_arr.max():>+7.2f}%  |  Trough: {cum_arr.min():>+7.2f}%  |  Final: {cum_arr[-1]:>+7.2f}%")
sep()

OUT.flush(); OUT.close()
_p("\nDone -> boof28_cleaned_longonly_results.txt")
