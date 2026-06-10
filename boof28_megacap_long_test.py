"""
Test mega-cap tech LONG only performance to decide if they should stay in watchlist
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd, pickle, os, numpy as np

MEGACAP = ["MSFT","AAPL","META","GOOGL","GOOG","AMZN","TSLA","NFLX","ORCL","IBM","ADBE","CRM","NOW","INTU","PANW","SNOW"]

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

def run(all_data, ema50, start, end):
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
        if not (qqq_open > e50 and q5 >= 0.001): continue  # bull only
        for sym in MEGACAP:
            if sym not in all_data: continue
            df = all_data[sym].copy()
            df = df[(df.index >= start) & (df.index <= end)]
            day = df[df.index.date == d]
            if len(day)==0: continue
            so = day.between_time('09:30','09:34')
            if len(so)==0: continue
            s5 = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open']
            if not (0.006 <= s5 <= 0.007): continue
            en = day.between_time('09:35','09:35')
            ex = day.between_time('10:20','10:20')
            if len(en)==0 or len(ex)==0: continue
            ep = en.iloc[0]['open']; xp = ex.iloc[0]['open']
            pnl = (xp-ep)/ep*100
            trades.append({'date':d,'symbol':sym,'pnl':pnl,'qqq_5m':round(q5*100,3),'stock_5m':round(s5*100,3)})
    return trades

def report(trades, label):
    if not trades:
        print(f"{label}: NO TRADES"); return
    df = pd.DataFrame(trades)
    W = 80
    wins = df[df['pnl']>0]; loss = df[df['pnl']<=0]
    wr = len(wins)/len(df)*100
    avg = df['pnl'].mean(); tot = df['pnl'].sum()
    pf = wins['pnl'].sum()/abs(loss['pnl'].sum()) if len(loss)>0 else 0
    cum = df['pnl'].cumsum(); dd = (cum.expanding().max()-cum).max()

    print(f"\n{'='*W}")
    print(f"  MEGA-CAP TECH -- LONG ONLY  |  {label}")
    print(f"{'='*W}")
    print(f"  {'Trades:':<20} {len(df)}")
    print(f"  {'Win Rate:':<20} {wr:.1f}%")
    print(f"  {'Avg Trade:':<20} {avg:+.3f}%")
    print(f"  {'Profit Factor:':<20} {pf:.2f}")
    print(f"  {'Max Drawdown:':<20} -{dd:.2f}%")
    print(f"  {'Total Return:':<20} {tot:+.2f}%")
    print(f"  {'-'*W}")
    print(f"  {'Symbol':>8} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Avg':>9} {'Total':>9}")
    print(f"  {'-'*W}")
    sym_stats = []
    for sym, grp in df.groupby('symbol'):
        w = grp[grp['pnl']>0]; l = grp[grp['pnl']<=0]
        _wr = len(w)/len(grp)*100
        _pf = w['pnl'].sum()/abs(l['pnl'].sum()) if len(l)>0 and l['pnl'].sum()!=0 else 0
        sym_stats.append({'sym':sym,'n':len(grp),'wr':_wr,'pf':_pf,'avg':grp['pnl'].mean(),'total':grp['pnl'].sum()})
    sym_df = pd.DataFrame(sym_stats).sort_values('total', ascending=False)
    for _, r in sym_df.iterrows():
        flag = " <-- KEEP" if r['total'] > 0.3 else (" <-- CUT" if r['total'] < 0 else "")
        print(f"  {r['sym']:>8} {r['n']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['avg']:>+8.3f}% {r['total']:>+8.2f}%{flag}")
    print(f"  {'='*W}")

print("Loading...")
all_data = {}
for sym in ['QQQ'] + MEGACAP:
    df = load(sym)
    if df is not None: all_data[sym] = df
print(f"Loaded {len(all_data)} symbols\n")

ema50 = build_ema50(all_data['QQQ'].copy())
s25s = pd.to_datetime('2025-01-01').tz_localize('UTC')
s25e = pd.to_datetime('2025-12-31').tz_localize('UTC')
s26s = pd.to_datetime('2026-01-01').tz_localize('UTC')
s26e = pd.to_datetime('2026-06-09').tz_localize('UTC')

t25 = run(all_data, ema50, s25s, s25e)
t26 = run(all_data, ema50, s26s, s26e)
report(t25, "2025 FULL YEAR")
report(t26, "2026 YTD (Jan-Jun 9)")
report(t25+t26, "COMBINED")
