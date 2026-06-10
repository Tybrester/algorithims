"""BOOF 28 - Long Only test on current watchlist (Version C)"""
import sys, pickle, os, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd

WATCHLIST = [
    'NVDA','AMD','AVGO','MU','MCHP','ASML','TSM','AMAT','MRVL','INTC','ON','NXPI','TXN','ARM',
    'HOOD','COIN','SQ','SOFI','CAVA',
    'CAT','ETN','DE','GE','URI',
    'ISRG','MRNA','VRTX','REGN','LLY',
    'MSFT','TSLA','CRM','IBM',
    'UBER','RCL','CCL','ABNB'
]

def load(s):
    f = f'boof_cache/{s}_2025-01-01_2026-12-31.pkl'
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

all_data = {}
for sym in ['QQQ'] + WATCHLIST:
    df = load(sym)
    if df is not None: all_data[sym] = df

ema50 = build_ema50(all_data['QQQ'].copy())

def run(start_str, end_str):
    S = pd.to_datetime(start_str).tz_localize('UTC')
    E = pd.to_datetime(end_str).tz_localize('UTC')
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= S) & (qqq.index <= E)]
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
        if not (qqq_open > e50 and q5 >= 0.001): continue
        for sym in WATCHLIST:
            if sym not in all_data: continue
            df2 = all_data[sym].copy()
            df2 = df2[(df2.index >= S) & (df2.index <= E)]
            day = df2[df2.index.date == d]
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
            trades.append({'date':d,'symbol':sym,'pnl':pnl,
                           'qqq_5m':round(q5*100,3),'stock_5m':round(s5*100,3),
                           'month':pd.Timestamp(d).to_period('M')})
    return trades

def report(trades, label):
    W = 72
    df = pd.DataFrame(trades)
    wins = df[df['pnl']>0]; loss = df[df['pnl']<=0]
    wr   = len(wins)/len(df)*100
    pf   = wins['pnl'].sum()/abs(loss['pnl'].sum()) if len(loss)>0 else 0
    avg  = df['pnl'].mean(); tot = df['pnl'].sum()
    cum  = df['pnl'].cumsum(); dd = (cum.expanding().max()-cum).max()
    tdays= df['date'].nunique(); tpd = len(df)/tdays
    aw   = wins['pnl'].mean(); al = abs(loss['pnl'].mean()) if len(loss)>0 else 0
    ev   = (len(wins)/len(df))*aw - (len(loss)/len(df))*al

    print('='*W)
    print(f'  BOOF 28 -- LONG ONLY  |  {label}')
    print('='*W)
    print(f'  Trades:        {len(df)}   ({tpd:.2f}/day on {tdays} active days)')
    print(f'  Win Rate:      {wr:.1f}%')
    print(f'  Avg Trade:     {avg:+.3f}%')
    print(f'  Avg Winner:   +{aw:.3f}%  |  Avg Loser: -{al:.3f}%')
    print(f'  EV per trade:  {ev:+.4f}%')
    print(f'  Profit Factor: {pf:.2f}')
    print(f'  Max Drawdown:  -{dd:.2f}%')
    print(f'  Total Return:  {tot:+.2f}%')

    print(f'\n  {"Symbol":>8} {"Trades":>7} {"WR%":>6} {"PF":>6} {"Avg":>9} {"Total":>9}')
    print('-'*W)
    sym_stats = []
    for sym, grp in df.groupby('symbol'):
        w = grp[grp['pnl']>0]; l = grp[grp['pnl']<=0]
        _wr = len(w)/len(grp)*100
        _pf = w['pnl'].sum()/abs(l['pnl'].sum()) if len(l)>0 and l['pnl'].sum()!=0 else 0
        sym_stats.append({'sym':sym,'n':len(grp),'wr':_wr,'pf':_pf,
                          'avg':grp['pnl'].mean(),'total':grp['pnl'].sum()})
    for _, r in pd.DataFrame(sym_stats).sort_values('total',ascending=False).iterrows():
        flag = '  <-- CUT' if r['total'] < 0 else ''
        print(f'  {r["sym"]:>8} {r["n"]:>7} {r["wr"]:>5.1f}% {r["pf"]:>6.2f} {r["avg"]:>+8.3f}% {r["total"]:>+8.2f}%{flag}')

    print(f'\n  {"Month":>10}  {"Trades":>6}  {"WR%":>5}  {"Total":>8}  {"Cum":>8}')
    print('-'*W)
    cum2 = 0
    for m in sorted(df['month'].unique()):
        mdf = df[df['month']==m]; mt = mdf['pnl'].sum(); cum2 += mt
        mwr = len(mdf[mdf['pnl']>0])/len(mdf)*100
        print(f'  {str(m):>10}  {len(mdf):>6}  {mwr:>4.0f}%  {mt:>+7.2f}%  {cum2:>+7.2f}%')
    print('='*W)

t25 = run('2025-01-01','2025-12-31')
t26 = run('2026-01-01','2026-06-09')
report(t25, '2025 FULL YEAR')
report(t26, '2026 YTD (Jan-Jun 9)')
report(t25+t26, 'COMBINED')
