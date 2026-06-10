# -*- coding: utf-8 -*-
"""
Boof 22 + 23 -- QQQ + SPY only -- Full Year 2025
+35% TP / -15% SL static option exits
"""
import sys, numpy as np, pandas as pd, requests
from collections import defaultdict

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import get_alpaca_credentials
from backtest_boof22 import (compute_atr as b22_atr, build_cluster_array,
                              nearest_sr_distance, DEFAULT_PARAMS as B22_DEF,
                              ATR_LEN as B22_ATR_LEN, VOL_LEN as B22_VOL_LEN,
                              FRACTAL_BARS as B22_FRAC)
import backtest_boof23 as b23mod
from backtest_boof23 import (compute_atr as b23_atr, build_cluster_array as b23_clusters,
                              nearest_sr_distance as b23_sr, _build_zigzag,
                              DEFAULT_PARAMS as B23_DEF,
                              ATR_LEN as B23_ATR_LEN, VOL_LEN as B23_VOL_LEN,
                              FRACTAL_BARS as B23_FRAC, MAX_HOLD as B23_MAX_H)
b23mod.CLUSTER_COMPLETION = False
b23mod.LOW_VOL_FILTER     = False

SYMS   = ['QQQ', 'SPY']
TP_PCT = 0.35
SL_PCT = 0.15
TP_ATR = 0.70
SL_ATR = 0.30
B22_CORE = 600; B22_EXP = 200
B23_CORE = 500; B23_EXP = 200

MONTHS     = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MDAYS      = [ 23,   20,   21,   22,   21,   21,   23,   21,   21,   23,   19,   23]
TOTAL_DAYS = sum(MDAYS)

MONTH_DATES = {
    'Jan': ('2025-01-02','2025-01-31'), 'Feb': ('2025-02-03','2025-02-28'),
    'Mar': ('2025-03-03','2025-03-31'), 'Apr': ('2025-04-01','2025-04-30'),
    'May': ('2025-05-01','2025-05-30'), 'Jun': ('2025-06-02','2025-06-30'),
    'Jul': ('2025-07-01','2025-07-31'), 'Aug': ('2025-08-01','2025-08-29'),
    'Sep': ('2025-09-02','2025-09-30'), 'Oct': ('2025-10-01','2025-10-31'),
    'Nov': ('2025-11-03','2025-11-28'), 'Dec': ('2025-12-01','2025-12-31'),
}

def fetch_bars(symbol, start_str, end_str, api_key, secret_key):
    all_bars = []
    url = f'https://data.alpaca.markets/v2/stocks/{symbol}/bars'
    params = {'timeframe':'1Min','start':start_str+'T09:30:00Z',
              'end':end_str+'T20:00:00Z','adjustment':'raw',
              'feed':'sip','limit':10000}
    headers = {'APCA-API-KEY-ID':api_key,'APCA-API-SECRET-KEY':secret_key}
    while True:
        r = requests.get(url, params=params, headers=headers)
        if r.status_code != 200: print(f'API {r.status_code}', end=' '); break
        d = r.json()
        all_bars.extend(d.get('bars', []))
        token = d.get('next_page_token')
        if not token: break
        params['page_token'] = token
    if not all_bars: return None
    df = pd.DataFrame(all_bars)
    df['time'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})
    return df[['time','open','high','low','close','volume']].set_index('time')

def run_b22(df):
    if df is None or len(df) < 200: return []
    params   = B22_DEF
    atr_mult = params['atr_mult']; vol_mult = params['vol_mult']; sr_dist = params['sr_dist']
    df2 = df.copy().reset_index(drop=True)
    atr_s = b22_atr(df2)
    df2['atr']    = atr_s
    df2['vol_sma']= df2['volume'].rolling(B22_VOL_LEN).mean()
    df2['rvol']   = (df2['volume'] / df2['vol_sma'] * 100).fillna(0)
    df2['hi_vol'] = df2['volume'] > df2['vol_sma'] * vol_mult
    cluster_prices, _ = build_cluster_array(df2, atr_s, vol_mult)
    opens=df2['open'].values; highs=df2['high'].values
    lows=df2['low'].values; closes=df2['close'].values; atrs=df2['atr'].values
    F=B22_FRAC; MAX_H=30; warmup=B22_VOL_LEN+B22_ATR_LEN+F
    in_trade=False; trade_end=0; trades=[]
    for i in range(warmup, len(df2)-F-MAX_H-3):
        if in_trade and i<=trade_end: continue
        atr=atrs[i]
        if np.isnan(atr) or atr==0: continue
        if df2.iloc[i]['rvol']<80: continue
        if not df2.iloc[i]['hi_vol']: continue
        if nearest_sr_distance(closes[i], cluster_prices, atr) > sr_dist: continue
        lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
        ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
        fp=(highs[i]>lh.max()) and (highs[i]>rh.max())
        ft=(lows[i]<ll.min())  and (lows[i]<rl.min())
        ps=(highs[i]-closes[i])/atr; ts=(closes[i]-lows[i])/atr
        ar=closes[i]<highs[i]-atr*atr_mult; ab=closes[i]>lows[i]+atr*atr_mult
        direction=None; slack=0.0
        if fp and ar: direction='short'; slack=ps
        elif ft and ab: direction='long'; slack=ts
        if direction is None: continue
        ep=float(opens[min(i+1,len(df2)-1)])
        tp_p=ep+atr*TP_ATR if direction=='long' else ep-atr*TP_ATR
        sl_p=ep-atr*SL_ATR if direction=='long' else ep+atr*SL_ATR
        et='time'; exit_bar=min(i+1+MAX_H, len(df2)-1)
        for j in range(i+2, min(i+MAX_H+2, len(df2))):
            h=highs[j]; l=lows[j]
            if direction=='long':
                if h>=tp_p: et='tp'; exit_bar=j; break
                if l<=sl_p: et='sl'; exit_bar=j; break
            else:
                if l<=tp_p: et='tp'; exit_bar=j; break
                if h>=sl_p: et='sl'; exit_bar=j; break
        in_trade=True; trade_end=exit_bar
        size=B22_CORE if slack>=1.4 else B22_EXP
        pnl=TP_PCT*size if et=='tp' else -SL_PCT*size if et=='sl' else 0.05*size
        trades.append({'pnl': pnl, 'exit_type': et})
    return trades

def run_b23(df):
    if df is None or len(df) < 200: return []
    params   = B23_DEF
    atr_mult = params['atr_mult']; vol_mult = params['vol_mult']; sr_dist = params['sr_dist']
    df2 = df.copy().reset_index(drop=True)
    atr_s = b23_atr(df2)
    df2['atr']    = atr_s
    df2['vol_sma']= df2['volume'].rolling(B23_VOL_LEN).mean()
    df2['rvol']   = (df2['volume'] / df2['vol_sma'] * 100).fillna(0)
    df2['hi_vol'] = df2['volume'] > df2['vol_sma'] * vol_mult
    cluster_prices, _ = b23_clusters(df2, atr_s, vol_mult)
    opens=df2['open'].values; highs=df2['high'].values
    lows=df2['low'].values; closes=df2['close'].values; atrs=df2['atr'].values
    zz_trend, zz_high, zz_high_bar, zz_low, zz_low_bar = _build_zigzag(highs, lows, opens, closes)
    F=B23_FRAC; MAX_H=B23_MAX_H; warmup=B23_VOL_LEN+B23_ATR_LEN+F
    ZZ_PROX=30; in_trade=False; trade_end=0; trades=[]
    for i in range(warmup, len(df2)-F-MAX_H-3):
        if in_trade and i<=trade_end: continue
        atr=atrs[i]
        if np.isnan(atr) or atr==0: continue
        if df2.iloc[i]['rvol']<80: continue
        if not df2.iloc[i]['hi_vol']: continue
        if b23_sr(closes[i], cluster_prices, atr) > sr_dist: continue
        lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
        ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
        fp=(highs[i]>lh.max()) and (highs[i]>rh.max())
        ft=(lows[i]<ll.min())  and (lows[i]<rl.min())
        ps=(highs[i]-closes[i])/atr; ts=(closes[i]-lows[i])/atr
        ar=closes[i]<highs[i]-atr*atr_mult; ab=closes[i]>lows[i]+atr*atr_mult
        zzt=zz_trend[i]
        direction=None; slack=0.0
        if fp and ar and zzt=='up'   and abs(i-int(zz_high_bar[i]))<=ZZ_PROX: direction='short'; slack=ps
        elif ft and ab and zzt=='down' and abs(i-int(zz_low_bar[i]))<=ZZ_PROX: direction='long';  slack=ts
        if direction is None: continue
        ep=float(opens[min(i+1,len(df2)-1)])
        tp_p=ep+atr*TP_ATR if direction=='long' else ep-atr*TP_ATR
        sl_p=ep-atr*SL_ATR if direction=='long' else ep+atr*SL_ATR
        et='time'; exit_bar=min(i+1+MAX_H, len(df2)-1)
        for j in range(i+2, min(i+MAX_H+2, len(df2))):
            h=highs[j]; l=lows[j]
            if direction=='long':
                if h>=tp_p: et='tp'; exit_bar=j; break
                if l<=sl_p: et='sl'; exit_bar=j; break
            else:
                if l<=tp_p: et='tp'; exit_bar=j; break
                if h>=sl_p: et='sl'; exit_bar=j; break
        in_trade=True; trade_end=exit_bar
        size=B23_CORE if slack>=1.4 else B23_EXP
        pnl=TP_PCT*size if et=='tp' else -SL_PCT*size if et=='sl' else 0.05*size
        trades.append({'pnl': pnl, 'exit_type': et})
    return trades

def stats(arr):
    if not arr: return dict(n=0,wr=0,ev=0,pf=0,total=0)
    p=np.array(arr); pos=p[p>0]; neg=p[p<0]
    return dict(n=len(p), wr=round(len(pos)/len(p)*100,1),
                ev=round(float(np.mean(p)),2),
                pf=round(float(sum(pos)/max(abs(sum(neg)),0.01)),2),
                total=round(float(sum(p)),0))

creds = get_alpaca_credentials()
res = {'b22':{mo:[] for mo in MONTHS}, 'b23':{mo:[] for mo in MONTHS}}

for mo, days in zip(MONTHS, MDAYS):
    start, end = MONTH_DATES[mo]
    print(f'\n-- {mo} 2025 --')
    for sym in SYMS:
        print(f'  {sym}...', end=' ', flush=True)
        try:
            df = fetch_bars(sym, start, end, api_key=creds['api_key'], secret_key=creds['secret_key'])
        except Exception as e:
            print(f'ERR: {e}'); continue
        if df is None or len(df) < 300: print('skip'); continue
        t22 = run_b22(df); t23 = run_b23(df)
        res['b22'][mo] += [t['pnl'] for t in t22]
        res['b23'][mo] += [t['pnl'] for t in t23]
        print(f'{len(df)} bars | B22={len(t22)} ({len(t22)/days:.1f}/d) B23={len(t23)} ({len(t23)/days:.1f}/d)')

W = 80
print('\n' + '='*W)
print(f"  BOOF 22 + 23 -- QQQ + SPY only -- Full Year 2025  (+35%/-15%)")
print('='*W)
print(f"  {'Month':<6}  {'B22 P&L':>10}  {'B22 Run':>10}  {'B23 P&L':>10}  {'B23 Run':>10}  {'T/d 22':>7}  {'T/d 23':>7}")
print('  ' + '-'*(W-2))
run22=0; run23=0; all22=[]; all23=[]
for mo, days in zip(MONTHS, MDAYS):
    p22=res['b22'][mo]; p23=res['b23'][mo]
    all22+=p22; all23+=p23
    run22+=sum(p22); run23+=sum(p23)
    n22=len(p22); n23=len(p23)
    print(f"  {mo:<6}  ${sum(p22):>9,.0f}  ${run22:>9,.0f}  ${sum(p23):>9,.0f}  ${run23:>9,.0f}  {n22/days:>7.1f}  {n23/days:>7.1f}")
print('  ' + '='*(W-2))

for label,arr,all_p in [('Boof 22','b22',all22),('Boof 23','b23',all23)]:
    st=stats(all_p)
    print(f"\n  {label}")
    print(f"    Trades/Day:  {round(st['n']/TOTAL_DAYS,1)}")
    print(f"    Win Rate:    {st['wr']}%")
    print(f"    EV/Trade:    ${st['ev']:.2f}")
    print(f"    PF:          {st['pf']:.2f}")
    print(f"    Total P&L:   ${st['total']:,.0f}")
    print(f"    Red Months:  {sum(1 for mo in MONTHS if sum(res[label.lower().replace(' ','')][mo])<0)}")
print('='*W)
