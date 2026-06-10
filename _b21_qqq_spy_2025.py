# -*- coding: utf-8 -*-
"""
Boof 21 — Full Year 2025 on QQQ + SPY only
+35% TP / -15% SL static option exits
"""
import sys, numpy as np, pandas as pd, requests
from collections import defaultdict

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import get_alpaca_credentials
from backtest_boof21 import backtest as b21_backtest

SYMS   = ['NVDA','AAPL','MSFT','AMZN','GOOGL','AVGO','META','TSLA','QQQ','SPY','LLY','BRK.B']
TP_PCT = 0.35
SL_PCT = 0.15
SIZE   = 250

MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MDAYS  = [ 23,   20,   21,   22,   21,   21,   23,   21,   21,   23,   19,   23]
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

def remap_b21(raw):
    result = []
    for t in raw:
        et = t['exit_type']
        if et == 'tp':        pnl = TP_PCT * SIZE
        elif et == 'stop':    pnl = -SL_PCT * SIZE
        else:
            pnl = float(t['pnl']) * SIZE * 2.0
            pnl = max(-SL_PCT * SIZE, min(TP_PCT * SIZE, pnl))
        result.append({'pnl': pnl, 'exit_type': et})
    return result

def stats(arr):
    if not arr: return dict(n=0,wr=0,ev=0,pf=0,total=0)
    p = np.array(arr); pos = p[p>0]; neg = p[p<0]
    return dict(n=len(p), wr=round(len(pos)/len(p)*100,1),
                ev=round(float(np.mean(p)),2),
                pf=round(float(sum(pos)/max(abs(sum(neg)),0.01)),2),
                total=round(float(sum(p)),0))

creds = get_alpaca_credentials()
by_month = {mo: [] for mo in MONTHS}
by_sym   = {s: [] for s in SYMS}

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
        print(f'{len(df)} bars', end=' -> ', flush=True)
        raw = b21_backtest(df, sym)
        trades = remap_b21(raw)
        print(f'{len(trades)} trades ({len(trades)/days:.1f}/d)  WR={round(sum(1 for t in trades if t["pnl"]>0)/max(len(trades),1)*100,1)}%')
        pnls = [t['pnl'] for t in trades]
        by_month[mo] += pnls
        by_sym[sym]  += pnls

# ── Report ──
W = 72
print('\n' + '='*W)
print(f"  BOOF 21 -- QQQ + SPY -- Full Year 2025  (+35% TP / -15% SL)")
print('='*W)
print(f"  {'Month':<6}  {'P&L':>10}  {'Running':>10}  {'Trades':>7}  {'T/d':>5}  {'WR':>6}")
print('  ' + '-'*(W-2))
run = 0; all_pnl = []
for mo, days in zip(MONTHS, MDAYS):
    p = by_month[mo]; all_pnl += p
    run += sum(p)
    n = len(p); wr = round(sum(1 for x in p if x>0)/max(n,1)*100,1)
    print(f"  {mo:<6}  ${sum(p):>9,.0f}  ${run:>9,.0f}  {n:>7}  {n/days:>5.1f}  {wr:>5.1f}%")
print('  ' + '='*(W-2))

st = stats(all_pnl)
print(f"\n  Total Trades:    {st['n']:,}  ({round(st['n']/TOTAL_DAYS,1)}/day avg)")
print(f"  Win Rate:        {st['wr']}%")
print(f"  EV / Trade:      ${st['ev']:.2f}")
print(f"  Profit Factor:   {st['pf']:.2f}")
print(f"  Total 2025 P&L:  ${st['total']:,.0f}")
red = sum(1 for mo in MONTHS if sum(by_month[mo]) < 0)
print(f"  Red Months:      {red}")

print(f"\n  Per Symbol:")
for sym in SYMS:
    s = stats(by_sym[sym])
    print(f"    {sym:<5}  N={s['n']:>4}  WR={s['wr']:>5.1f}%  EV=${s['ev']:>7.2f}  P&L=${s['total']:>9,.0f}")
print('='*W)
